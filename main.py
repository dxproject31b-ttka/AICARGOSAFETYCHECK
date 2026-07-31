import base64
import io
import json
import os
import time
import gc
import traceback
from pdf2image import convert_from_bytes
import PIL.Image
import PIL.ImageDraw
import PIL.ImageStat
import functions_framework
import google.generativeai as genai

# ---------------------------------------------------------------------------
# Backend API สำหรับ AI Cargo Safety Checker ( High-Precision v3 )
# แก้ไข:
#   [v3] - ลด DPI 250 → 180 เพื่อประหยัด Gemini API quota
#   [v3] - detect_page_layout(): รองรับ TOP_BOTTOM และ LEFT_RIGHT layout
#   [v3] - Adaptive rear crop coordinates ตาม layout จริง
#   [v3] - เพิ่ม REAR_LATERAL_IMBALANCE risk type (ท้ายตู้สูงต่ำแนวกว้าง)
#   [v3] - แก้ color-bias false positive ใน prompt (สีกล่อง ≠ ความสูง)
#   [v3] - Dense Cargo Rule เข้มขึ้น: ใช้เฉพาะ longitudinal perspective
# ---------------------------------------------------------------------------

# ============================================================
# SECTION 1 — UTILITY: API KEYS
# ============================================================

def get_api_keys_pool():
    keys = []
    for env_k, env_v in os.environ.items():
        k_upper = env_k.upper().strip()
        if ("GEMINI" in k_upper or "API_KEY" in k_upper) and env_v and env_v.strip():
            extracted_keys = [k.strip() for k in env_v.split(",") if k.strip()]
            keys.extend(extracted_keys)
            
    keys = list(set(keys))
    if keys:
        print(f"✅ Loaded {len(keys)} unique API key(s) into the pool.")
        return keys
    
    print("❌ No Gemini API keys found.")
    return []

# ============================================================
# SECTION 2 — UTILITY: ACTION REPORTS (7 risk types)
# ============================================================

def generate_action_report(case_type, description):
    actions = {
        "STEP_DOWN_RISK":
            f"🚨 [ALERT] พบรอยต่างระดับระหว่างกองสินค้า (Step-Down)\n{description}\n"
            f"🛠️ ACTION: ติดตั้งแผ่นไม้กั้นขวาง (Void Filler / Dunnage) ระหว่างกอง "
            f"และรัดตรึงให้ครบทุกจุด",

        "REAR_EMPTY_RISK":
            f"🚨 [ALERT] พบพื้นที่โล่ง/สินค้าต่างระดับ ฝั่งประตูท้ายตู้ (REAR EMPTY)\n{description}\n"
            f"🛠️ ACTION: ติดตั้งแผ่นไม้ค้ำแนวดิ่ง (Rear Tomming) + "
            f"รัดตรึงป้องกันสินค้าไถลออกประตู",

        "REAR_LATERAL_IMBALANCE":
            f"🚨 [ALERT] พบสินค้าท้ายตู้สูงต่ำไม่เท่ากันในแนวกว้าง (Rear Lateral Imbalance)\n"
            f"{description}\n"
            f"🛠️ ACTION: เสริมด้านที่ต่ำกว่าด้วย Void Filler / Dunnage ให้ระดับเท่ากัน "
            f"+ รัดตรึงขวางป้องกันสินค้าล้มตะแคงเมื่อเปิดประตู",

        "FRONT_EMPTY_RISK":
            f"🚨 [ALERT] พบพื้นที่โล่ง/สินค้าต่างระดับ ฝั่งผนังหัวตู้ (FRONT EMPTY)\n{description}\n"
            f"🛠️ ACTION: ติดตั้งแผ่นไม้ค้ำฝั่งหัวตู้ (Front Blocking) + "
            f"รัดตรึงป้องกันสินค้าไถลหน้าเมื่อเบรก",

        "LATERAL_GAP_RISK":
            f"🚨 [ALERT] พบช่องว่างด้านข้างระหว่างกองสินค้า (Lateral Gap)\n{description}\n"
            f"🛠️ ACTION: ใส่ Air Bag หรือ Void Filler ด้านข้าง + "
            f"รัดตรึงป้องกันสินค้าเลื่อนตะแคงขณะเลี้ยว",

        "TALL_UNSTABLE_RISK":
            f"🚨 [ALERT] พบสินค้าสูงโดดเดี่ยว ไม่มีของข้างค้ำ (Tall / Unstable)\n{description}\n"
            f"🛠️ ACTION: ค้ำยันด้านข้างกองสูง + รัดตรึงแนวขวาง ป้องกันล้มตะแคง",

        "OVERHANG_RISK":
            f"🚨 [ALERT] พบสินค้าชั้นบนยื่นพ้นขอบสินค้าชั้นล่าง (Overhang)\n{description}\n"
            f"🛠️ ACTION: จัดเรียงใหม่ให้ชั้นบนไม่ยื่นพ้นฐาน "
            f"หรือใส่แผ่นรองรับและรัดตรึง",
    }
    return actions.get(
        case_type,
        "🟢 [STATUS] ปลอดภัย (SAFE)\nไม่พบจุดเสี่ยงที่ต้องดำเนินการเพิ่มเติม"
    )


# ============================================================
# SECTION 3 — UTILITY: JSON CLEANER
# ============================================================

def clean_json_response(text):
    text = text.strip()
    start_list  = text.find('[')
    end_list    = text.rfind(']')
    start_dict  = text.find('{')
    end_dict    = text.rfind('}')

    if start_list != -1 and end_list != -1:
        if start_dict == -1 or start_list < start_dict:
            return text[start_list:end_list + 1]

    if start_dict != -1 and end_dict != -1:
        return text[start_dict:end_dict + 1]

    return text


# ============================================================
# SECTION 4 — LAYOUT DETECTOR  [NEW v3]
# ============================================================

def detect_page_layout(img: PIL.Image.Image, crop_y_start: int, crop_y_end: int) -> str:
    """
    ตรวจสอบว่า Page 2 ของ manifest จัด layout แบบใด:
      "TOP_BOTTOM" — Front view อยู่บน, Back view อยู่ล่าง (AA02, AA05, AC05)
      "LEFT_RIGHT" — Front view อยู่ซ้าย, Back view อยู่ขวา (AC03)

    วิธี: วัดความสว่างเฉลี่ยของแถบกลาง (10% ของมิติ) ทั้งแนวนอนและแนวตั้ง
    แถบที่สว่างกว่าคือเส้นแบ่งระหว่าง 2 view → บอก orientation ของเส้นแบ่งนั้น

    เส้นแบ่งแนวนอน (horizontal band สว่าง) → layout = TOP_BOTTOM
    เส้นแบ่งแนวตั้ง  (vertical band สว่าง)  → layout = LEFT_RIGHT
    """
    try:
        crop_w = img.size[0]
        crop_h = crop_y_end - crop_y_start

        band_thickness_h = max(1, int(crop_h * 0.08))  # 8% of height
        band_thickness_v = max(1, int(crop_w * 0.08))  # 8% of width

        center_y = crop_y_start + crop_h // 2
        center_x = crop_w // 2

        # แถบแนวนอน (ตรวจ TOP_BOTTOM separator)
        h_band = img.crop((
            0,
            center_y - band_thickness_h // 2,
            crop_w,
            center_y + band_thickness_h // 2
        )).convert("L")
        h_brightness = PIL.ImageStat.Stat(h_band).mean[0]  # 0–255

        # แถบแนวตั้ง (ตรวจ LEFT_RIGHT separator)
        v_band = img.crop((
            center_x - band_thickness_v // 2,
            crop_y_start,
            center_x + band_thickness_v // 2,
            crop_y_end
        )).convert("L")
        v_brightness = PIL.ImageStat.Stat(v_band).mean[0]  # 0–255

        print(f"🔍 Layout detection — H-band brightness: {h_brightness:.1f} | "
              f"V-band brightness: {v_brightness:.1f}")

        # เส้นแบ่งสว่างกว่า (whitespace) ≥ 8 point margin → ถือว่าชัดเจน
        if v_brightness > h_brightness + 8:
            layout = "LEFT_RIGHT"
        elif h_brightness > v_brightness + 8:
            layout = "TOP_BOTTOM"
        else:
            # ต่างกันน้อย → default TOP_BOTTOM (layout ที่พบบ่อยกว่า)
            layout = "TOP_BOTTOM"

        print(f"✅ Detected layout: {layout}")
        return layout

    except Exception as e:
        print(f"⚠️ Layout detection failed ({e}), defaulting to TOP_BOTTOM")
        return "TOP_BOTTOM"


# ============================================================
# SECTION 5 — AI: REAR ZONE CROP ANALYSIS  [UPGRADED v3]
# ============================================================

def analyze_rear_zone_with_ai(rear_crop: PIL.Image.Image, api_keys: list,
                               view_label: str = "UNKNOWN") -> dict:
    """
    วิเคราะห์ภาพ Crop เฉพาะ Zone ท้ายตู้ (door end) แยกต่างหาก
    ตรวจทั้ง REAR_EMPTY_RISK และ REAR_LATERAL_IMBALANCE [v3]
    """
    rear_prompt = f"""
You are a Cargo Safety Inspector. This image is a ZOOMED-IN CROP of the DOOR END (REAR) zone
of a 3D isometric container loading diagram — the side with the open door and red floor arrows.
This is the {view_label} view of the manifest.

YOUR TASK: Detect TWO possible risks in this cropped door-end area.

=======================================================================
RISK A — REAR_EMPTY_RISK (longitudinal shortage)
=======================================================================
Signals:
1. Visible empty yellow floor grid near the open door (no boxes placed there)
2. The last cargo column is clearly 1 or more FULL BOX LAYERS shorter than the columns
   further inside the container (shorter in the depth/length direction)
3. Unsupported upper gap above the last stack

=======================================================================
RISK B — REAR_LATERAL_IMBALANCE (lateral height difference at rear)
=======================================================================
Signals:
1. At the door-end zone, the cargo on the LEFT side is clearly taller than the RIGHT side
   (or vice versa) by 1 or more full box layers
2. This is a WIDTH-direction (side-to-side) height difference, NOT a depth difference
3. The imbalance creates risk of cargo tipping sideways when the door is opened

=======================================================================
CRITICAL RULES — PREVENT FALSE POSITIVES
=======================================================================
- Box COLOR (blue, green, red, etc.) indicates SKU type ONLY — it does NOT mean
  height difference. Do NOT report a risk based on color alone.
- A stagger/offset where boxes are shifted horizontally but remain the SAME HEIGHT
  is NOT a risk — do not report it.
- 3D perspective naturally makes the far side appear smaller — compensate for this.
  Only report if height difference is clearly ≥ 1 full box layer.
- If you cannot clearly count the difference → SAFE (do not guess).

=======================================================================
OUTPUT — Return ONLY this exact JSON object:
=======================================================================
{{
  "rear_zone_risk": "REAR_EMPTY_RISK" | "REAR_LATERAL_IMBALANCE" | "BOTH" | "SAFE",
  "reasoning": "Describe exactly what you see: stack heights, floor gaps, lateral differences.",
  "confidence": "HIGH" | "MEDIUM" | "LOW"
}}
"""
    last_err = ""
    model_candidates = ["gemini-3.6-flash"]

    for current_key in api_keys:
        try:
            genai.configure(api_key=current_key)
            for model_name in model_candidates:
                try:
                    model = genai.GenerativeModel(
                        model_name=model_name,
                        generation_config={"response_mime_type": "application/json"}
                    )
                    response = model.generate_content([rear_prompt, rear_crop])
                    raw_text = response.text if response and response.text else "{}"
                    clean_text = clean_json_response(raw_text)
                    result = json.loads(clean_text)
                    if isinstance(result, list):
                        result = result[0] if result else {}
                    return result
                except Exception as e:
                    last_err = str(e)
                    if "404" in last_err or "not found" in last_err.lower():
                        continue
                    break
        except Exception as e:
            last_err = str(e)
            continue

    return {"rear_zone_risk": "ERROR", "reasoning": last_err[:120], "confidence": "LOW"}


# ============================================================
# SECTION 6 — AI: FULL DIAGRAM ANALYSIS  [UPGRADED v3]
# ============================================================

def analyze_diagram_image_with_ai(diagram_image: PIL.Image.Image):
    api_keys = get_api_keys_pool()
    if not api_keys:
        env_keys_list = [k for k in os.environ.keys() if not k.startswith("NIX_")]
        return [{
            "risk_type": "ERROR",
            "description": f"ไม่พบตัวแปร GEMINI_API_KEYS ใน Cloud Run | "
                           f"Env Vars: {env_keys_list[:8]}"
        }]

    # ==========================================================================
    # PROMPT v3
    # Changes vs v2:
    #   + RISK TYPE 7: REAR_LATERAL_IMBALANCE (ท้ายตู้สูงต่ำแนวกว้าง)
    #   + COLOR BIAS WARNING: กล่องสีต่างกัน ≠ ความสูงต่างกัน
    #   + Dense Cargo Rule: perspective artifact ใช้เฉพาะแนวยาว ไม่ใช้แนวกว้าง
    #   + Zone 2 anchor rule: เพิ่มกรณี REAR_LATERAL_IMBALANCE
    #   + Output schema: เพิ่ม "lateral_side" field
    # ==========================================================================
    prompt = """
You are an expert Cargo Loading Safety Inspector. Your mission is to detect ALL physical risks
of cargo shifting, sliding, tipping, or collapsing INSIDE a container/truck — in ANY direction.

This image shows Page 2 of a MaxLoad Pro manifest: a 3D cargo loading diagram with
two views labeled "Front" and "Back" (these are CAMERA VIEW NAMES only, not physical positions).

=======================================================================
PART 0 — CRITICAL ANTI-FALSE-POSITIVE RULES (read FIRST, apply ALWAYS)
=======================================================================

⛔ COLOR RULE — Box color = SKU type identity ONLY.
   Blue boxes, green boxes, red boxes — these are just different product types.
   Different colors stacked together do NOT indicate height difference.
   NEVER report any risk based on color difference alone.

⛔ STAGGER/OFFSET RULE — Boxes that are offset or staggered horizontally
   (like brick-laying pattern) but remain at the SAME overall HEIGHT
   are NOT a risk. Do not report STEP_DOWN or OVERHANG for normal stagger.

⛔ UNIFORM LOAD RULE — If all cargo stacks appear to reach the same height
   across the full length and width of the container, report SAFE for that view.
   Do not invent risks from visual texture or color variation.

=======================================================================
PART 1 — IDENTIFY PHYSICAL ORIENTATION (do this FIRST for EACH view)
=======================================================================

The container always has TWO ends:
  • DOOR END (Physical Rear): Open side with visible FLOOR GRID and
    TWO RED ARROWS pointing at the floor. NO solid wall here.
  • HEAD WALL (Physical Front): SOLID YELLOW/TAN WALL closing one end.

For EACH diagram view, identify which side is Door End and which is Head Wall
BEFORE scanning for risks. Use the red arrows and yellow wall as anchors —
NOT the "Front"/"Back" camera label.

=======================================================================
PART 2 — SYSTEMATIC RISK SCAN (7 risk types, ALL directions)
=======================================================================

Scan EVERY column and row in BOTH views for ALL 7 risk types below.

--- RISK TYPE 1: REAR_EMPTY_RISK ---
Trigger: Near the DOOR END — in the LENGTH direction:
  - Empty floor grid (no boxes where boxes could be placed)
  - OR last cargo column is clearly ≥1 FULL BOX LAYER shorter than columns beside it
    (measuring depth/length direction, not width direction)
  Risk: cargo slides backward and falls when door opens.

--- RISK TYPE 2: REAR_LATERAL_IMBALANCE ---  ← NEW
Trigger: Near the DOOR END — in the WIDTH direction:
  - At the door-end zone, the cargo on the LEFT wall side is clearly ≥1 FULL BOX LAYER
    taller OR shorter than the cargo on the RIGHT wall side
  - This is a SIDE-TO-SIDE height difference (across the container width), NOT depth
  - The taller side creates an unbalanced mass that can topple sideways when the door opens
  Risk: asymmetric cargo collapses laterally the moment door constraint is removed.
  NOTE: Only report if difference is clearly ≥1 full layer. Perspective shrinkage of far
  side is normal — compensate for it before judging.

--- RISK TYPE 3: FRONT_EMPTY_RISK ---
Trigger: Near the HEAD WALL — in the LENGTH direction:
  - Empty floor space between wall and first cargo column
  - OR first cargo column is clearly ≥1 FULL LAYER shorter than adjacent column
  Risk: cargo shifts forward under braking.

--- RISK TYPE 4: STEP_DOWN_RISK ---
Trigger: In the MIDDLE section (not at either end):
  - Adjacent cargo columns differ by ≥1 full layer in height — staircase shape
  Risk: taller column topples onto shorter one.

--- RISK TYPE 5: LATERAL_GAP_RISK ---
Trigger: Side-to-side (WIDTH direction), across the full container:
  - Visible empty space between cargo groups in width direction
  - OR cargo clearly does not span the full container width
  Risk: cargo slides sideways during cornering.

--- RISK TYPE 6: TALL_UNSTABLE_RISK ---
Trigger: A cargo column is notably taller than ALL surrounding columns on
  BOTH sides (longitudinal AND lateral):
  - The tall stack has no neighboring cargo of similar height on ≥2 sides
  Risk: tipping in any direction due to lack of lateral support.

--- RISK TYPE 7: OVERHANG_RISK ---
Trigger: A box or layer on TOP of a stack extends BEYOND the footprint
  of the boxes directly below it (overhangs the edge in any direction).
  Risk: upper cargo slides off or causes lower cargo to tip.

=======================================================================
PART 2B — DENSE CARGO PERSPECTIVE RULE
       (Apply ONLY to longitudinal/depth direction)
=======================================================================

When the container is heavily loaded (boxes packed tightly wall-to-wall
in the LENGTH direction), the 3D isometric camera creates a DIAGONAL
VISUAL SLOPE across the top surface of the cargo. This slope is a
PERSPECTIVE ARTIFACT for the LENGTH direction only — it is NOT a real
step-down or height difference in depth.

  ✅ Apply this rule to: REAR_EMPTY_RISK, FRONT_EMPTY_RISK, STEP_DOWN_RISK
     → Only flag if you can clearly COUNT ≥1 FULL BOX LAYER difference.
     → A gradual slope in the lengthwise direction → DO NOT REPORT.

  ❌ Do NOT apply this rule to: REAR_LATERAL_IMBALANCE, LATERAL_GAP_RISK
     → Side-to-side height differences are NOT a perspective artifact.
     → If left side is taller than right side by 1 full layer → REPORT it.

=======================================================================
PART 2C — ZONE 2 ANCHOR RULE (MANDATORY — prevents false positives)
=======================================================================

Before reporting FRONT_EMPTY_RISK, REAR_EMPTY_RISK, or STEP_DOWN_RISK,
assess Zone 2 (middle 30% of container length) as your HEIGHT BASELINE.

FRONT_EMPTY_RISK:
  • Count layers in Zone 1 (head wall side) vs Zone 2 (middle).
  • Zone 1 clearly ≥1 FULL LAYER shorter than Zone 2 → REPORT
  • Same height or <1 full layer difference → DO NOT REPORT
  • Uncertain (3D distortion) → DO NOT REPORT

REAR_EMPTY_RISK:
  • Count layers in Zone 3 (door end) vs Zone 2 (middle).
  • Zone 3 clearly ≥1 FULL LAYER shorter, OR visible empty floor → REPORT
  • Same height or <1 full layer difference → DO NOT REPORT
  • Uncertain → DO NOT REPORT

STEP_DOWN_RISK:
  • Adjacent stacks within Zone 2: clearly ≥1 FULL LAYER difference → REPORT
  • Uncertain → DO NOT REPORT

REAR_LATERAL_IMBALANCE:
  • At Zone 3 (door end): left side vs right side height.
  • Clearly ≥1 FULL LAYER difference side-to-side → REPORT
  • Stagger/offset at same height → DO NOT REPORT
  • Uncertain → DO NOT REPORT

=======================================================================
PART 3 — BOUNDING BOX RULES
=======================================================================

Format: [ymin, xmin, ymax, xmax] normalized 0–1000.
(0,0) = TOP-LEFT corner of the ENTIRE IMAGE provided.

- Draw box TIGHTLY around the SPECIFIC CARGO or FLOOR AREA triggering the risk.
- NEVER draw a box in the white margin outside the container diagram.
- For REAR_LATERAL_IMBALANCE: box around BOTH the taller and shorter side stacks at door end.
- For empty floor: box around the visible empty yellow floor grid.
- For height mismatch (longitudinal): box around both taller and shorter adjacent columns.
- For lateral gap: box around the visible empty space between cargo groups.
- For overhang: box around the overhanging top layer only.

=======================================================================
OUTPUT FORMAT — Strict JSON array. No markdown, no preamble.
=======================================================================

Return ONLY a valid JSON array. Each detected risk = one object.
Multiple risks of same type in different locations = separate objects.
NO risks found at all → return: []

Schema:
{
  "view": "FRONT" | "BACK",
  "risk_type": "REAR_EMPTY_RISK" | "REAR_LATERAL_IMBALANCE" | "FRONT_EMPTY_RISK" |
               "STEP_DOWN_RISK" | "LATERAL_GAP_RISK" | "TALL_UNSTABLE_RISK" | "OVERHANG_RISK",
  "direction": "LONGITUDINAL" | "LATERAL" | "VERTICAL",
  "lateral_side": "LEFT_HIGHER" | "RIGHT_HIGHER" | "N/A",
  "zone2_baseline": "<Describe Zone 2 middle cargo height, e.g. '3 layers uniform full width'>",
  "reasoning": "<Visual evidence: describe exactly what you see — which columns, what height
                difference, what gap. For FRONT/REAR risks, explicitly compare vs zone2_baseline.
                For REAR_LATERAL_IMBALANCE, describe left vs right stack heights at door end.>",
  "description": "<Thai language: อธิบายตำแหน่งและลักษณะของความเสี่ยงที่พบ>",
  "box_2d": [ymin, xmin, ymax, xmax]
}

Example outputs (do not copy — use your actual findings):
[
  {
    "view": "FRONT",
    "risk_type": "REAR_LATERAL_IMBALANCE",
    "direction": "LATERAL",
    "lateral_side": "LEFT_HIGHER",
    "zone2_baseline": "3 layers uniform across full width in the middle section",
    "reasoning": "At the door end (left side of Front view), left wall cargo stack is 3 layers high
                  while right wall cargo stack at same longitudinal position is only 2 layers high.
                  Difference = 1 full layer. Not a perspective effect — both sides visible clearly.",
    "description": "พบสินค้าท้ายตู้ฝั่งซ้ายสูงกว่าฝั่งขวา 1 ชั้น เสี่ยงล้มตะแคงเมื่อเปิดประตู",
    "box_2d": [400, 50, 850, 400]
  },
  {
    "view": "BACK",
    "risk_type": "LATERAL_GAP_RISK",
    "direction": "LATERAL",
    "lateral_side": "N/A",
    "zone2_baseline": "3 layers uniform across full width",
    "reasoning": "In BACK view, cargo on the left side stops at approximately x=0.45 of width.
                  Right side from x=0.45 to x=0.75 shows empty yellow floor.",
    "description": "พบช่องว่างด้านข้างตู้ฝั่งขวา มุมมอง BACK สินค้าไม่เต็มความกว้าง",
    "box_2d": [450, 500, 850, 750]
  }
]
"""

    model_candidates = ["gemini-3.6-flash"]
    last_error_msg = ""

    for pass_round in range(2):
        for current_key in api_keys:
            try:
                genai.configure(api_key=current_key)
                for model_name in model_candidates:
                    try:
                        model = genai.GenerativeModel(
                            model_name=model_name,
                            generation_config={"response_mime_type": "application/json"}
                        )
                        response = model.generate_content([prompt, diagram_image])
                        raw_text = response.text if response and response.text else "[]"
                        clean_text = clean_json_response(raw_text)

                        if not clean_text or clean_text in ('""', '[]'):
                            return []

                        risks = json.loads(clean_text)
                        if isinstance(risks, dict):
                            risks = [risks]
                        return risks

                    except Exception as model_err:
                        err_str = str(model_err)
                        last_error_msg = err_str
                        if "404" in err_str or "not found" in err_str.lower():
                            continue
                        elif "429" in err_str or "quota" in err_str.lower() \
                                or "resourceexhausted" in err_str.lower():
                            raise model_err
                        else:
                            break

            except Exception as key_err:
                last_error_msg = str(key_err)
                continue

        if pass_round == 0:
            time.sleep(10)

    return [{
        "risk_type": "ERROR",
        "description": f"AI Error (รวมทั้ง {len(api_keys)} Keys): {last_error_msg[:120]}"
    }]


# ============================================================
# SECTION 7 — MAIN CLOUD FUNCTION HANDLER  [UPGRADED v3]
# ============================================================

@functions_framework.http
def process_request(request):
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'POST',
            'Access-Control-Allow-Headers': 'Content-Type, x-goog-api-key',
            'Access-Control-Max-Age': '3600'
        }
        return ('', 204, headers)

    headers = {'Access-Control-Allow-Origin': '*'}

    try:
        data = request.get_json(silent=True) or {}
        if not data or 'base64' not in data:
            return ({"error": "No base64 data provided"}, 400, headers)

        base64_str = data.get('base64')
        if "," in base64_str:
            base64_str = base64_str.split(",")[1]

        pdf_bytes = base64.b64decode(base64_str)

        # ------------------------------------------------------------------
        # STEP 1: Render PDF — DPI 180 [v3: ลดจาก 250 เพื่อประหยัด quota]
        # ------------------------------------------------------------------
        try:
            pages = convert_from_bytes(pdf_bytes, first_page=2, last_page=2, dpi=180)
        except Exception:
            try:
                pages = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=180)
            except Exception:
                pages = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=150)

        if not pages:
            return ({"error": "Cannot render PDF page data"}, 400, headers)

        img = pages[0]
        width, height = img.size
        print(f"📄 Rendered image: {width}x{height}px @ 180 DPI")

        # ------------------------------------------------------------------
        # STEP 2: Crop diagram area (remove header/footer bands)
        # ------------------------------------------------------------------
        crop_y_start = int(height * 0.10)
        crop_y_end   = int(height * 0.90)
        crop_w       = width
        crop_h       = crop_y_end - crop_y_start

        diagram_crop = img.crop((0, crop_y_start, crop_w, crop_y_end))

        # ------------------------------------------------------------------
        # STEP 3: Full diagram analysis — all zones, all 7 risk types
        # ------------------------------------------------------------------
        all_risks = analyze_diagram_image_with_ai(diagram_crop)

        # ------------------------------------------------------------------
        # [FIX 2] POST-FILTER: ลบ FRONT_EMPTY_RISK ออกเมื่อ layout = LEFT_RIGHT
        # เหตุผล: AC03-type (LEFT_RIGHT) มีสินค้าชิดหัวตู้ การที่ AI เห็น
        #         FRONT_EMPTY เป็น perspective artifact ของ isometric view
        #         ที่หัวตู้ทั้ง FRONT และ BACK — ตกลงกันว่าไม่นับเป็น risk
        # ------------------------------------------------------------------
        # NOTE: ต้องรัน detect_page_layout ก่อน ย้าย STEP 3.5 ขึ้นมาก่อน STEP 3

        # วิธีแก้: สลับ STEP 3.5 ขึ้นมาก่อน STEP 3 แล้วเพิ่ม filter:

        layout = detect_page_layout(img, crop_y_start, crop_y_end)  # ← ย้ายขึ้นมา

        all_risks = analyze_diagram_image_with_ai(diagram_crop)

        if layout == "LEFT_RIGHT":
            before = len(all_risks)
            all_risks = [
                r for r in all_risks
                if not (
                    isinstance(r, dict) and
                    str(r.get("risk_type", "")).upper() == "FRONT_EMPTY_RISK"
                )
            ]
            removed = before - len(all_risks)
            if removed:
                print(f"🗑️ [FIX2] Removed {removed} FRONT_EMPTY_RISK(s) "
                      f"(LEFT_RIGHT layout — head-wall risks not counted)")
        
        # ------------------------------------------------------------------
        # STEP 3.5: Detect page layout  [NEW v3]
        # ------------------------------------------------------------------
        layout = detect_page_layout(img, crop_y_start, crop_y_end)

        # ------------------------------------------------------------------
        # STEP 4: Rear Zone Crop — adaptive coordinates per layout  [v3]
        # ------------------------------------------------------------------
        #
        # TOP_BOTTOM layout (AA02, AA05, AC05):
        #   • Front view occupies TOP half  → door end = LEFT  (x: 0–38%)
        #   • Back  view occupies BOT half  → door end = RIGHT (x: 62–100%)
        #
        # LEFT_RIGHT layout (AC03):
        #   • Front view occupies LEFT half  → door end = LEFT edge of left half
        #                                       = x: 0–22% of total width, full height
        #   • Back  view occupies RIGHT half → door end = RIGHT edge of right half
        #                                       = x: 78–100% of total width, full height
        # ------------------------------------------------------------------

        if layout == "TOP_BOTTOM":
            half_h = crop_h // 2
            rear_crop_front = img.crop((
                0,
                crop_y_start,
                int(crop_w * 0.38),
                crop_y_start + half_h
            ))
            rear_crop_back = img.crop((
                int(crop_w * 0.62),
                crop_y_start + half_h,
                crop_w,
                crop_y_end
            ))
            print("🗺️ Rear crop: TOP_BOTTOM mode")

        else:  # LEFT_RIGHT
            rear_crop_front = img.crop((
                0,
                crop_y_start,
                int(crop_w * 0.22),
                crop_y_end
            ))
            rear_crop_back = img.crop((
                int(crop_w * 0.78),
                crop_y_start,
                crop_w,
                crop_y_end
            ))
            print("🗺️ Rear crop: LEFT_RIGHT mode")

        # ------------------------------------------------------------------
        # STEP 4.5: Run rear zone AI analysis (with view label for context)
        # ------------------------------------------------------------------
        api_keys_for_rear  = get_api_keys_pool()
        rear_result_front  = analyze_rear_zone_with_ai(
            rear_crop_front, api_keys_for_rear, view_label="FRONT"
        )
        rear_result_back   = analyze_rear_zone_with_ai(
            rear_crop_back, api_keys_for_rear, view_label="BACK"
        )

        # ------------------------------------------------------------------
        # STEP 5: Merge rear crop findings into all_risks  [UPGRADED v3]
        #   Now handles: REAR_EMPTY_RISK, REAR_LATERAL_IMBALANCE, BOTH
        # ------------------------------------------------------------------
        if not isinstance(all_risks, list):
            all_risks = []

        def _existing_risk_views(risk_type_substr: str) -> set:
            return {
                str(r.get("view", "")).upper()
                for r in all_risks
                if risk_type_substr in str(r.get("risk_type", "")).upper()
            }

        for view_label, rear_result in [
            ("FRONT", rear_result_front),
            ("BACK",  rear_result_back)
        ]:
            if not isinstance(rear_result, dict):
                continue

            rear_zone_risk = str(rear_result.get("rear_zone_risk", "")).upper()
            confidence     = str(rear_result.get("confidence", "LOW")).upper()
            reasoning      = rear_result.get("reasoning", "")

            if confidence not in ("HIGH", "MEDIUM"):
                continue  # skip LOW confidence and ERROR

            # ---- REAR_EMPTY_RISK (from rear crop) ----
            if rear_zone_risk in ("REAR_EMPTY_RISK", "BOTH"):
                if view_label not in _existing_risk_views("REAR_EMPTY"):
                    all_risks.append({
                        "view":           view_label,
                        "risk_type":      "REAR_EMPTY_RISK",
                        "direction":      "LONGITUDINAL",
                        "lateral_side":   "N/A",
                        "zone2_baseline": "Assessed from rear zone crop independently.",
                        "reasoning":      f"[Rear Crop Confirm] {reasoning}",
                        "description":    "พบสินค้าฝั่งประตูท้ายตู้ต่ำกว่ากลางตู้ หรือเห็นพื้นโล่ง "
                                          "(ยืนยันจากการวิเคราะห์ภาพ Zoom ท้ายตู้)",
                        "box_2d":         None
                    })

            # ---- REAR_LATERAL_IMBALANCE (from rear crop)  [NEW v3] ----
            if rear_zone_risk in ("REAR_LATERAL_IMBALANCE", "BOTH"):
                if view_label not in _existing_risk_views("REAR_LATERAL"):
                    all_risks.append({
                        "view":           view_label,
                        "risk_type":      "REAR_LATERAL_IMBALANCE",
                        "direction":      "LATERAL",
                        "lateral_side":   rear_result.get("lateral_side", "N/A"),
                        "zone2_baseline": "Assessed from rear zone crop independently.",
                        "reasoning":      f"[Rear Crop Confirm] {reasoning}",
                        "description":    "พบสินค้าท้ายตู้สูงต่ำไม่เท่ากันในแนวกว้าง "
                                          "(ยืนยันจากการวิเคราะห์ภาพ Zoom ท้ายตู้)",
                        "box_2d":         None
                    })

        # ============================================================
        # [FIX 1] FALLBACK BOX สำหรับ rear crop risks (box_2d = None)
        # ============================================================
        # วางหลัง STEP 5 ก่อน STEP 6

        def _get_fallback_box(risk_type: str, view_label: str, layout: str,
                              crop_w: int, crop_y_start: int, crop_h: int) -> list | None:
            """
            สร้าง bounding box โดยประมาณสำหรับ risks ที่ไม่มี box_2d
            ใช้ตำแหน่ง zone ที่รู้อยู่แล้วจาก layout
            คืนค่าใน pixel coordinates (abs) ของ img จริง
            """
            if layout == "TOP_BOTTOM":
                half_h = crop_h // 2
                zones = {
                    # FRONT view — ด้านบน, door end = ฝั่งซ้าย
                    ("REAR_EMPTY_RISK",        "FRONT"): (0, crop_y_start, int(crop_w*0.40), crop_y_start + half_h),
                    ("REAR_LATERAL_IMBALANCE", "FRONT"): (0, crop_y_start, int(crop_w*0.40), crop_y_start + half_h),
                    # BACK view — ด้านล่าง, door end = ฝั่งขวา
                    ("REAR_EMPTY_RISK",        "BACK"):  (int(crop_w*0.60), crop_y_start + half_h, crop_w, crop_y_start + crop_h),
                    ("REAR_LATERAL_IMBALANCE", "BACK"):  (int(crop_w*0.60), crop_y_start + half_h, crop_w, crop_y_start + crop_h),
                }
            else:  # LEFT_RIGHT
                zones = {
                    ("REAR_EMPTY_RISK",        "FRONT"): (0, crop_y_start, int(crop_w*0.24), crop_y_start + crop_h),
                    ("REAR_LATERAL_IMBALANCE", "FRONT"): (0, crop_y_start, int(crop_w*0.24), crop_y_start + crop_h),
                    ("REAR_EMPTY_RISK",        "BACK"):  (int(crop_w*0.76), crop_y_start, crop_w, crop_y_start + crop_h),
                    ("REAR_LATERAL_IMBALANCE", "BACK"):  (int(crop_w*0.76), crop_y_start, crop_w, crop_y_start + crop_h),
                }

            key = (risk_type, view_label.upper())
            coords = zones.get(key)
            if coords:
                xmin, ymin, xmax, ymax = coords
                return [xmin, ymin, xmax, ymax]  # pixel coords โดยตรง (ไม่ต้อง normalize)
            return None
                                  
        # ------------------------------------------------------------------
        # STEP 6: Draw bounding boxes + build hazard list
        # ------------------------------------------------------------------
        draw = PIL.ImageDraw.Draw(img)
        detected_hazards = []

        RISK_COLORS = {
            "STEP_DOWN_RISK":          "red",
            "REAR_EMPTY_RISK":         "orange",
            "REAR_LATERAL_IMBALANCE":  "deeppink",   # NEW v3
            "FRONT_EMPTY_RISK":        "yellow",
            "LATERAL_GAP_RISK":        "cyan",
            "TALL_UNSTABLE_RISK":      "magenta",
            "OVERHANG_RISK":           "lime",
        }

        VALID_RISK_TYPES = set(RISK_COLORS.keys())

        for risk in all_risks:
            raw_risk_type = str(risk.get("risk_type", "")).upper().strip()
            view_name     = str(risk.get("view", "GENERAL")).upper()

            # ---- normalize risk_type (fuzzy match) ----
            matched_type = None
            if raw_risk_type in VALID_RISK_TYPES:
                matched_type = raw_risk_type
            else:
                for vrt in VALID_RISK_TYPES:
                    keyword = vrt.replace("_RISK", "")
                    if keyword in raw_risk_type or raw_risk_type in vrt:
                        matched_type = vrt
                        break

            if raw_risk_type == "ERROR":
                detected_hazards.append({
                    "title":    "⚠️ ข้อผิดพลาด API",
                    "detail":   risk.get("description",
                                         "โปรดตรวจสอบโควตา Gemini API Keys"),
                    "is_error": True
                })
                continue

            if matched_type is None:
                continue  # skip unknown / unrecognized

            risk_type     = matched_type
            desc          = risk.get("description", "พบความไม่สมดุลของสินค้า")
            direction     = risk.get("direction", "")
            lateral_side  = risk.get("lateral_side", "")
            box           = (risk.get("box_2d") or risk.get("boundingBox")
                             or risk.get("box2d") or risk.get("box"))
            outline_color = RISK_COLORS.get(risk_type, "red")

            # ---- Draw bounding box if valid ----
            drawn = False
            if box and isinstance(box, list) and len(box) == 4:
                try:
                    ymin, xmin, ymax, xmax = map(float, box)
                    if max(ymin, xmin, ymax, xmax) <= 1.0 \
                            and max(ymin, xmin, ymax, xmax) > 0:
                        ymin, xmin, ymax, xmax = (
                            ymin * 1000, xmin * 1000,
                            ymax * 1000, xmax * 1000
                        )
                    abs_xmin = int(xmin * crop_w / 1000.0)
                    abs_xmax = int(xmax * crop_w / 1000.0)
                    abs_ymin = int(crop_y_start + (ymin * crop_h / 1000.0))
                    abs_ymax = int(crop_y_start + (ymax * crop_h / 1000.0))
                    draw.rectangle([abs_xmin, abs_ymin, abs_xmax, abs_ymax],
                                   outline=outline_color, width=8)
                    drawn = True
                except Exception:
                    pass

            # [FIX 1] Fallback box สำหรับ risks ที่ box_2d = None
            if not drawn:
                fallback = _get_fallback_box(
                    risk_type, view_name, layout, crop_w, crop_y_start, crop_h
                )
                if fallback:
                    xmin_f, ymin_f, xmax_f, ymax_f = fallback
                    draw.rectangle([xmin_f, ymin_f, xmax_f, ymax_f],
                                   outline=outline_color, width=8)

            # ---- Build label ----
            dir_label  = f" [{direction}]" if direction else ""
            side_label = f" ({lateral_side})" if lateral_side and lateral_side != "N/A" else ""
            detected_hazards.append({
                "title":    f"ความเสี่ยง ({view_name}){dir_label}{side_label}: {risk_type}",
                "detail":   generate_action_report(risk_type, desc),
                "is_error": False
            })

        # ------------------------------------------------------------------
        # STEP 7: Build response
        # ------------------------------------------------------------------
        real_hazards  = [h for h in detected_hazards if not h.get("is_error")]
        error_hazards = [h for h in detected_hazards if h.get("is_error")]
        sep = "\n\n" + "-" * 50 + "\n\n"

        if real_hazards:
            status_text  = f"พบจุดเสี่ยงอันตราย ({len(real_hazards)} จุด)"
            action_text  = sep.join(f"[{h['title']}]\n{h['detail']}" for h in real_hazards)
            hazard_count = len(real_hazards)
        elif error_hazards:
            status_text  = "เกิดข้อผิดพลาดในการวิเคราะห์ AI"
            action_text  = sep.join(f"[{h['title']}]\n{h['detail']}" for h in error_hazards)
            hazard_count = 0
        else:
            status_text  = "ปลอดภัย (SAFE)"
            action_text  = generate_action_report("SAFE", "")
            hazard_count = 0

        # ------------------------------------------------------------------
        # STEP 8: Encode result image and return
        # ------------------------------------------------------------------
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=80)
        processed_base64    = base64.b64encode(buffered.getvalue()).decode('utf-8')
        processed_image_url = f"data:image/jpeg;base64,{processed_base64}"

        gc.collect()

        return ({
            "status":            status_text,
            "hazardCount":       hazard_count,
            "layout":            layout,          # debug info
            "actionRequired":    action_text,
            "processedImageUrl": processed_image_url
        }, 200, headers)

    except Exception as e:
        gc.collect()
        return ({"error": str(e), "trace": traceback.format_exc()[-500:]}, 500, headers)
