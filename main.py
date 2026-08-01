import base64
import io
import json
import os
import time
import gc
import traceback
import random
from pdf2image import convert_from_bytes
import PIL.Image
import PIL.ImageDraw
import PIL.ImageStat
import functions_framework
import google.generativeai as genai

# ---------------------------------------------------------------------------
# Backend API สำหรับ AI Cargo Safety Checker ( High-Precision v4 )
# แก้ไขจาก v3:
#   [v4-FIX1] - _get_fallback_box(): จำกัด y ให้อยู่แค่โซน cargo จริง (ไม่ใช่ทั้งหน้า)
#   [v4-FIX2] - ลบ duplicate analyze_diagram_image_with_ai() ออก (เรียกครั้งเดียว)
#   [v4-FIX3] - ลบ duplicate detect_page_layout() ออก (เรียกครั้งเดียว ก่อน AI)
#   [v4-FIX4] - box_2d จาก AI: เพิ่ม clamp + กรอง box ที่ใหญ่เกิน 80% ของภาพ
# ---------------------------------------------------------------------------

# ============================================================
# SECTION 1 — UTILITY: API KEYS (ปรับปรุงให้จำสถานะ Global)
# ============================================================

# [เพิ่ม] ตัวแปร Global 
GLOBAL_API_KEYS = []
GLOBAL_KEY_INDEX = 0

def get_api_keys_pool():
    global GLOBAL_API_KEYS
    # หากดึงคีย์และสลับตำแหน่งไว้แล้ว ให้ใช้รายการเดิม (เพื่อไม่ให้ Index คลาดเคลื่อน)
    if GLOBAL_API_KEYS:
        return GLOBAL_API_KEYS

    keys = []
    for env_k, env_v in os.environ.items():
        k_upper = env_k.upper().strip()
        if ("GEMINI" in k_upper or "API_KEY" in k_upper) and env_v and env_v.strip():
            extracted_keys = [k.strip() for k in env_v.split(",") if k.strip()]
            keys.extend(extracted_keys)

    keys = list(set(keys))
    if keys:
        random.shuffle(keys)
        print(f"✅ Loaded {len(keys)} unique API key(s) into the pool.")
        GLOBAL_API_KEYS = keys
        return GLOBAL_API_KEYS

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
    start_list = text.find('[')
    end_list   = text.rfind(']')
    start_dict = text.find('{')
    end_dict   = text.rfind('}')

    if start_list != -1 and end_list != -1:
        if start_dict == -1 or start_list < start_dict:
            return text[start_list:end_list + 1]

    if start_dict != -1 and end_dict != -1:
        return text[start_dict:end_dict + 1]

    return text


# ============================================================
# SECTION 4 — LAYOUT DETECTOR
# ============================================================

def detect_page_layout(img: PIL.Image.Image, crop_y_start: int, crop_y_end: int) -> str:
    """
    ตรวจสอบว่า Page 2 ของ manifest จัด layout แบบใด:
      "TOP_BOTTOM" — Front view อยู่บน, Back view อยู่ล่าง (AA02, AA05, AC05)
      "LEFT_RIGHT" — Front view อยู่ซ้าย, Back view อยู่ขวา (AC03)

    วิธี: วัดความสว่างเฉลี่ยของแถบกลาง (8% ของมิติ) ทั้งแนวนอนและแนวตั้ง
    แถบที่สว่างกว่าคือเส้นแบ่งระหว่าง 2 view → บอก orientation ของเส้นแบ่งนั้น
    """
    try:
        crop_w = img.size[0]
        crop_h = crop_y_end - crop_y_start

        band_thickness_h = max(1, int(crop_h * 0.08))
        band_thickness_v = max(1, int(crop_w * 0.08))

        center_y = crop_y_start + crop_h // 2
        center_x = crop_w // 2

        h_band = img.crop((
            0,
            center_y - band_thickness_h // 2,
            crop_w,
            center_y + band_thickness_h // 2
        )).convert("L")
        h_brightness = PIL.ImageStat.Stat(h_band).mean[0]

        v_band = img.crop((
            center_x - band_thickness_v // 2,
            crop_y_start,
            center_x + band_thickness_v // 2,
            crop_y_end
        )).convert("L")
        v_brightness = PIL.ImageStat.Stat(v_band).mean[0]

        print(f"🔍 Layout detection — H-band brightness: {h_brightness:.1f} | "
              f"V-band brightness: {v_brightness:.1f}")

        if v_brightness > h_brightness + 8:
            layout = "LEFT_RIGHT"
        elif h_brightness > v_brightness + 8:
            layout = "TOP_BOTTOM"
        else:
            layout = "TOP_BOTTOM"

        print(f"✅ Detected layout: {layout}")
        return layout

    except Exception as e:
        print(f"⚠️ Layout detection failed ({e}), defaulting to TOP_BOTTOM")
        return "TOP_BOTTOM"


# ============================================================
# SECTION 5 — AI: REAR ZONE CROP ANALYSIS
# ============================================================

def analyze_rear_zone_with_ai(rear_crop: PIL.Image.Image, api_keys: list,
                               view_label: str = "UNKNOWN") -> dict:
    global GLOBAL_KEY_INDEX # [เพิ่ม] เรียกใช้ตัวแปรจำตำแหน่งคีย์
    """
    วิเคราะห์ภาพ Crop เฉพาะ Zone ท้ายตู้ (door end) แยกต่างหาก
    ตรวจทั้ง REAR_EMPTY_RISK และ REAR_LATERAL_IMBALANCE
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
    total_keys = len(api_keys)

    if total_keys == 0:
        return {"rear_zone_risk": "ERROR", "reasoning": "No API keys", "confidence": "LOW"}

    for i in range(total_keys):
        # [เพิ่ม] คำนวณหา Index ปัจจุบัน (เริ่มจากคีย์ล่าสุดที่ใช้ได้)
        current_index = (GLOBAL_KEY_INDEX + i) % total_keys
        current_key = api_keys[current_index]
        
        try:
            if hasattr(genai, '_client'):
                genai._client = None
                
            genai.configure(api_key=current_key)
            for model_name in model_candidates:
                try:
                    model = genai.GenerativeModel(
                        model_name=model_name,
                        generation_config={"response_mime_type": "application/json"}
                    )
                    # ใช้ prompt ที่คุณตั้งไว้ (rear_prompt)
                    response = model.generate_content([rear_prompt, rear_crop]) 
                    raw_text = response.text if response and response.text else "{}"
                    clean_text = clean_json_response(raw_text)
                    result = json.loads(clean_text)
                    if isinstance(result, list):
                        result = result[0] if result else {}
                        
                    # [เพิ่ม] วิเคราะห์ผ่านแล้ว! อัปเดตตำแหน่งคีย์ล่าสุด
                    GLOBAL_KEY_INDEX = current_index 
                    return result
                    
                except Exception as e:
                    last_err = str(e)
                    if "404" in last_err or "not found" in last_err.lower():
                        continue
                    break # เจอโควตาเต็ม (429) ให้เบรกเพื่อเปลี่ยนคีย์ทันที
        except Exception as e:
            last_err = str(e)
            continue

    return {"rear_zone_risk": "ERROR", "reasoning": last_err[:120], "confidence": "LOW"}
                                   
# ============================================================
# SECTION 5.5 — AI: FRONT ZONE CROP ANALYSIS (ใหม่)
# ============================================================

def analyze_front_zone_with_ai(front_crop: PIL.Image.Image, api_keys: list,
                               view_label: str = "UNKNOWN") -> dict:
    global GLOBAL_KEY_INDEX
    front_prompt = f"""
You are a Cargo Safety Inspector. This image is a ZOOMED-IN CROP of the HEAD WALL (FRONT) zone
of a 3D isometric container loading diagram — the side with the SOLID YELLOW/TAN WALL.
This is the {view_label} view of the manifest.

YOUR TASK: Detect if there is a FRONT_EMPTY_RISK in this cropped area.

=======================================================================
SIGNALS FOR FRONT_EMPTY_RISK (longitudinal shortage)
=======================================================================
1. Visible empty floor space between the solid yellow head wall and the first cargo column.
2. The first cargo column touching the wall is clearly 1 or more FULL BOX LAYERS shorter
   than the adjacent cargo columns further inside the container.

OUTPUT — Return ONLY this exact JSON object:
{{
  "front_zone_risk": "FRONT_EMPTY_RISK" | "SAFE",
  "reasoning": "Describe exactly what you see near the solid wall.",
  "confidence": "HIGH" | "MEDIUM" | "LOW"
}}
"""
    last_err = ""
    model_candidates = ["gemini-3.6-flash"]
    total_keys = len(api_keys)

    if total_keys == 0:
        return {"front_zone_risk": "ERROR", "reasoning": "No API keys", "confidence": "LOW"}

    for i in range(total_keys):
        current_index = (GLOBAL_KEY_INDEX + i) % total_keys
        current_key = api_keys[current_index]
        
        try:
            if hasattr(genai, '_client'):
                genai._client = None
                
            genai.configure(api_key=current_key)
            for model_name in model_candidates:
                try:
                    model = genai.GenerativeModel(
                        model_name=model_name,
                        generation_config={"response_mime_type": "application/json"}
                    )
                    response = model.generate_content([front_prompt, front_crop]) 
                    raw_text = response.text if response and response.text else "{}"
                    clean_text = clean_json_response(raw_text)
                    result = json.loads(clean_text)
                    if isinstance(result, list):
                        result = result[0] if result else {}
                        
                    GLOBAL_KEY_INDEX = current_index 
                    return result
                    
                except Exception as e:
                    last_err = str(e)
                    if "404" in last_err or "not found" in last_err.lower(): continue
                    break
        except Exception as e:
            last_err = str(e)
            continue

    return {"front_zone_risk": "ERROR", "reasoning": last_err[:120], "confidence": "LOW"}

# ============================================================
# SECTION 6 — AI: FULL DIAGRAM ANALYSIS
# ============================================================

def analyze_diagram_image_with_ai(diagram_image: PIL.Image.Image):
    global GLOBAL_KEY_INDEX # [เพิ่ม] เรียกใช้ตัวแปรจำตำแหน่งคีย์
    
    api_keys = get_api_keys_pool()
    if not api_keys:
        env_keys_list = [k for k in os.environ.keys() if not k.startswith("NIX_")]
        return [{
            "risk_type": "ERROR",
            "description": f"ไม่พบตัวแปร GEMINI_API_KEYS ใน Cloud Run | "
                           f"Env Vars: {env_keys_list[:8]}"
        }]

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

--- RISK TYPE 2: REAR_LATERAL_IMBALANCE ---
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
    total_keys = len(api_keys)

    for pass_round in range(2):
        for i in range(total_keys):
            # [เพิ่ม] คำนวณหา Index เริ่มจากคีย์ที่ทำงานได้ล่าสุด
            current_index = (GLOBAL_KEY_INDEX + i) % total_keys
            current_key = api_keys[current_index]
            
            try:
                if hasattr(genai, '_client'):
                    genai._client = None
                    
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
                            
                        # [เพิ่ม] วิเคราะห์สำเร็จ อัปเดตตำแหน่งคีย์ล่าสุด
                        GLOBAL_KEY_INDEX = current_index
                        return risks

                    except Exception as model_err:
                        err_str = str(model_err)
                        last_error_msg = err_str
                        if "404" in err_str or "not found" in err_str.lower():
                            continue
                        elif "429" in err_str or "quota" in err_str.lower() \
                                or "resourceexhausted" in err_str.lower():
                            break 
                        else:
                            break 

            except Exception as key_err:
                last_error_msg = str(key_err)
                continue

        if pass_round == 0:
            time.sleep(2) # ใช้ 2 วินาทีพอเพื่อลดโอกาสเกิด Timeout 500

    return [{
        "risk_type": "ERROR",
        "description": f"AI Error (รวมทั้ง {len(api_keys)} Keys): {last_error_msg[:120]}"
    }]


# ============================================================
# SECTION 7 — FALLBACK BOX HELPER  [v4-FIX1]
# ============================================================

def _get_fallback_box(risk_type: str, view_label: str, layout: str,
                      crop_w: int, crop_y_start: int, crop_h: int):
    vl = view_label.upper()
    crop_y_end = crop_y_start + crop_h
                          
    if layout == "TOP_BOTTOM":
        half_h = crop_h // 2
        front_y0 = crop_y_start + int(half_h * 0.50)
        front_y1 = crop_y_start + half_h
        back_y0  = crop_y_start + half_h + int(half_h * 0.50)
        back_y1  = crop_y_end

        zones = {
            # ท้ายตู้ (Door)
            ("REAR_EMPTY_RISK",        "FRONT"): (0,               front_y0, int(crop_w * 0.35), front_y1),
            ("REAR_LATERAL_IMBALANCE", "FRONT"): (0,               front_y0, int(crop_w * 0.35), front_y1),
            ("REAR_EMPTY_RISK",        "BACK"):  (int(crop_w*0.65), back_y0,  crop_w,             back_y1),
            ("REAR_LATERAL_IMBALANCE", "BACK"):  (int(crop_w*0.65), back_y0,  crop_w,             back_y1),
            # หัวตู้ (Head Wall)
            ("FRONT_EMPTY_RISK",       "FRONT"): (int(crop_w*0.65), front_y0, crop_w,             front_y1),
            ("FRONT_EMPTY_RISK",       "BACK"):  (0,               back_y0,  int(crop_w * 0.35), back_y1),
        }

    else:  # LEFT_RIGHT
        y0 = crop_y_start + int(crop_h * 0.30)
        y1 = crop_y_start + int(crop_h * 0.80)

        zones = {
            # ท้ายตู้ (Door)
            ("REAR_EMPTY_RISK",        "FRONT"): (0,                y0, int(crop_w * 0.20), y1),
            ("REAR_LATERAL_IMBALANCE", "FRONT"): (0,                y0, int(crop_w * 0.20), y1),
            ("REAR_EMPTY_RISK",        "BACK"):  (int(crop_w*0.80), y0, crop_w,             y1),
            ("REAR_LATERAL_IMBALANCE", "BACK"):  (int(crop_w*0.80), y0, crop_w,             y1),
            # หัวตู้ (Head Wall)
            ("FRONT_EMPTY_RISK",       "FRONT"): (int(crop_w*0.80), y0, crop_w,             y1),
            ("FRONT_EMPTY_RISK",       "BACK"):  (0,                y0, int(crop_w * 0.20), y1),
        }

    key = (risk_type, vl)
    coords = zones.get(key)
    if coords:
        xmin, ymin, xmax, ymax = coords
        return [xmin, ymin, xmax, ymax]
    return None

# ============================================================
# SECTION 8 — MAIN CLOUD FUNCTION HANDLER  [v4]
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
        # STEP 1: Render PDF — DPI 180
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
        crop_w       = int(width * 0.72)
        crop_h       = crop_y_end - crop_y_start

        diagram_crop = img.crop((0, crop_y_start, crop_w, crop_y_end))

        # ------------------------------------------------------------------
        # STEP 3: Detect layout ก่อน — เรียกครั้งเดียว  [v4-FIX2, FIX3]
        # ------------------------------------------------------------------
        layout = detect_page_layout(img, crop_y_start, crop_y_end)

        # ------------------------------------------------------------------
        # STEP 4: Full diagram analysis — เรียกครั้งเดียว  [v4-FIX2]
        # ------------------------------------------------------------------
        all_risks = analyze_diagram_image_with_ai(diagram_crop)

        # ------------------------------------------------------------------
        # STEP 4.5: POST-FILTER FRONT_EMPTY_RISK สำหรับ LEFT_RIGHT layout
        # เหตุผล: AC03-type สินค้าชิดหัวตู้ AI เห็น FRONT_EMPTY เป็น
        #         perspective artifact — ตกลงกันว่าไม่นับเป็น risk
        # ------------------------------------------------------------------
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
                print(f"🗑️ [v4] Removed {removed} FRONT_EMPTY_RISK(s) "
                      f"(LEFT_RIGHT layout — not counted per business rule)")

        # ------------------------------------------------------------------
        # STEP 5: Rear&Front Zone Crop — adaptive per layout
        #
        # TOP_BOTTOM (AA02, AA05, AC05):
        #   Front view = upper half → door end = LEFT  (x: 0–38%)
        #   Back  view = lower half → door end = RIGHT (x: 62–100%)
        #
        # LEFT_RIGHT (AC03):
        #   Front view = left half  → door end = LEFT  (x: 0–22%, full h)
        #   Back  view = right half → door end = RIGHT (x: 78–100%, full h)
        # ------------------------------------------------------------------
        if layout == "TOP_BOTTOM":
            half_h = crop_h // 2
            # Rear (ท้ายตู้)
            rear_crop_front = img.crop((0, crop_y_start, int(crop_w * 0.38), crop_y_start + half_h))
            rear_crop_back = img.crop((int(crop_w * 0.62), crop_y_start + half_h, crop_w, crop_y_end))
            # Front (หัวตู้)
            front_crop_front = img.crop((int(crop_w * 0.62), crop_y_start, crop_w, crop_y_start + half_h))
            front_crop_back = img.crop((0, crop_y_start + half_h, int(crop_w * 0.38), crop_y_end))
        else:  # LEFT_RIGHT
            # Rear (ท้ายตู้)
            rear_crop_front = img.crop((0, crop_y_start, int(crop_w * 0.22), crop_y_end))
            rear_crop_back = img.crop((int(crop_w * 0.78), crop_y_start, crop_w, crop_y_end))
            # Front (หัวตู้)
            front_crop_front = img.crop((int(crop_w * 0.78), crop_y_start, crop_w, crop_y_end))
            front_crop_back = img.crop((0, crop_y_start, int(crop_w * 0.22), crop_y_end))
            print("🗺️ Rear&Front crop: LEFT_RIGHT mode")

        # ------------------------------------------------------------------
        # STEP 5.5: Rear&Front zone AI analysis
        # ------------------------------------------------------------------
        api_keys_pool = get_api_keys_pool()
        
        # ตรวจท้ายตู้
        rear_result_front = analyze_rear_zone_with_ai(rear_crop_front, api_keys_pool, "FRONT")
        rear_result_back = analyze_rear_zone_with_ai(rear_crop_back, api_keys_pool, "BACK")
        
        # ตรวจหัวตู้
        front_result_front = analyze_front_zone_with_ai(front_crop_front, api_keys_pool, "FRONT")
        front_result_back = analyze_front_zone_with_ai(front_crop_back, api_keys_pool, "BACK")

        # ------------------------------------------------------------------
        # STEP 6: Merge rear crop findings into all_risks
        # ------------------------------------------------------------------
        if not isinstance(all_risks, list):
            all_risks = []

        def _existing_risk_views(risk_type_substr: str) -> set:
            return {
                str(r.get("view", "")).upper() for r in all_risks 
                if risk_type_substr in str(r.get("risk_type", "")).upper()
            }

        # Merge ท้ายตู้
        for view_label, rear_result in [("FRONT", rear_result_front), ("BACK",  rear_result_back)]:
            if not isinstance(rear_result, dict): continue
            rear_zone_risk = str(rear_result.get("rear_zone_risk", "")).upper()
            confidence = str(rear_result.get("confidence", "LOW")).upper()
            reasoning = rear_result.get("reasoning", "")

            if confidence in ("HIGH", "MEDIUM"):
                if rear_zone_risk in ("REAR_EMPTY_RISK", "BOTH") and view_label not in _existing_risk_views("REAR_EMPTY"):
                    all_risks.append({
                        "view": view_label, "risk_type": "REAR_EMPTY_RISK", "direction": "LONGITUDINAL", "lateral_side": "N/A",
                        "zone2_baseline": "Assessed from rear zone crop.",
                        "reasoning": f"[Rear Confirm] {reasoning}",
                        "description": "พบสินค้าฝั่งประตูท้ายตู้ต่ำกว่ากลางตู้ หรือเห็นพื้นโล่ง (วิเคราะห์จาก Zoom ท้ายตู้)",
                        "box_2d": None
                    })
                if rear_zone_risk in ("REAR_LATERAL_IMBALANCE", "BOTH") and view_label not in _existing_risk_views("REAR_LATERAL"):
                    all_risks.append({
                        "view": view_label, "risk_type": "REAR_LATERAL_IMBALANCE", "direction": "LATERAL", "lateral_side": rear_result.get("lateral_side", "N/A"),
                        "zone2_baseline": "Assessed from rear zone crop.",
                        "reasoning": f"[Rear Confirm] {reasoning}",
                        "description": "พบสินค้าท้ายตู้สูงต่ำไม่เท่ากันในแนวกว้าง (วิเคราะห์จาก Zoom ท้ายตู้)",
                        "box_2d": None
                    })

        # Merge หัวตู้ (ใหม่!)
        for view_label, front_result in [("FRONT", front_result_front), ("BACK", front_result_back)]:
            if not isinstance(front_result, dict): continue
            front_zone_risk = str(front_result.get("front_zone_risk", "")).upper()
            confidence = str(front_result.get("confidence", "LOW")).upper()
            reasoning = front_result.get("reasoning", "")

            if confidence in ("HIGH", "MEDIUM") and front_zone_risk == "FRONT_EMPTY_RISK":
                # จะเพิ่มเข้า Report ก็ต่อเมื่อภาพรวมไม่ได้หาเจออยู่แล้ว
                if view_label not in _existing_risk_views("FRONT_EMPTY"):
                    all_risks.append({
                        "view": view_label,
                        "risk_type": "FRONT_EMPTY_RISK",
                        "direction": "LONGITUDINAL",
                        "lateral_side": "N/A",
                        "zone2_baseline": "Assessed from front zone crop independently.",
                        "reasoning": f"[Front Confirm] {reasoning}",
                        "description": "พบพื้นที่โล่งหรือสินค้าต่างระดับ ฝั่งผนังหัวตู้ (ยืนยันจากการวิเคราะห์ภาพ Zoom หัวตู้)",
                        "box_2d": None
                    })

        # ------------------------------------------------------------------
        # STEP 7: Draw bounding boxes + build hazard list
        # ------------------------------------------------------------------
        draw = PIL.ImageDraw.Draw(img)
        detected_hazards = []

        RISK_COLORS = {
            "STEP_DOWN_RISK":          "red",
            "REAR_EMPTY_RISK":         "orange",
            "REAR_LATERAL_IMBALANCE":  "deeppink",
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

            risk_type    = matched_type
            desc         = risk.get("description", "พบความไม่สมดุลของสินค้า")
            direction    = risk.get("direction", "")
            lateral_side = risk.get("lateral_side", "")
            box          = (risk.get("box_2d") or risk.get("boundingBox")
                            or risk.get("box2d") or risk.get("box"))
            outline_color = RISK_COLORS.get(risk_type, "red")

            # ----------------------------------------------------------------
            # Draw bounding box  [v4-FIX4: clamp + size guard]
            # ----------------------------------------------------------------
            drawn = False
            if box and isinstance(box, list) and len(box) == 4:
                try:
                    ymin, xmin, ymax, xmax = map(float, box)

                    # Normalize 0–1 → 0–1000
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

                    # [v4-FIX4] Clamp ไม่ให้หลุดออกนอก crop zone
                    abs_xmin = max(0,            min(abs_xmin, crop_w - 1))
                    abs_xmax = max(abs_xmin + 1, min(abs_xmax, crop_w))
                    abs_ymin = max(crop_y_start, min(abs_ymin, crop_y_end - 1))
                    abs_ymax = max(abs_ymin + 1, min(abs_ymax, crop_y_end))

                    # [v4-FIX4] กรองกรอบที่ใหญ่เกินสมเหตุสมผล (> 80% ของ crop)
                    box_w_ratio = (abs_xmax - abs_xmin) / crop_w
                    box_h_ratio = (abs_ymax - abs_ymin) / crop_h
                    if box_w_ratio < 0.80 and box_h_ratio < 0.80:
                        draw.rectangle(
                            [abs_xmin, abs_ymin, abs_xmax, abs_ymax],
                            outline=outline_color, width=8
                        )
                        drawn = True
                    else:
                        print(f"⚠️ [v4] Box too large "
                              f"({box_w_ratio:.0%}w × {box_h_ratio:.0%}h) "
                              f"for {risk_type} {view_name} — using fallback")

                except Exception:
                    pass  # invalid box → fall through to fallback

            # [v4-FIX1] Fallback box สำหรับ risks ที่ box_2d = None
            # หรือ AI box ใหญ่เกิน / invalid
            if not drawn:
                fallback = _get_fallback_box(
                    risk_type, view_name, layout, crop_w, crop_y_start, crop_h
                )
                if fallback:
                    xmin_f, ymin_f, xmax_f, ymax_f = fallback
                    draw.rectangle(
                        [xmin_f, ymin_f, xmax_f, ymax_f],
                        outline=outline_color, width=8
                    )

            # ---- Build hazard label ----
            dir_label  = f" [{direction}]" if direction else ""
            side_label = f" ({lateral_side})" if lateral_side and lateral_side != "N/A" else ""
            detected_hazards.append({
                "title":    f"ความเสี่ยง ({view_name}){dir_label}{side_label}: {risk_type}",
                "detail":   generate_action_report(risk_type, desc),
                "is_error": False
            })

        # ------------------------------------------------------------------
        # STEP 8: Build response
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
        # STEP 9: Encode result image and return
        # ------------------------------------------------------------------
        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=80)
        processed_base64    = base64.b64encode(buffered.getvalue()).decode('utf-8')
        processed_image_url = f"data:image/jpeg;base64,{processed_base64}"

        gc.collect()

        return ({
            "status":            status_text,
            "hazardCount":       hazard_count,
            "layout":            layout,
            "actionRequired":    action_text,
            "processedImageUrl": processed_image_url
        }, 200, headers)

    except Exception as e:
        err_trace = traceback.format_exc()
        # [เพิ่มบรรทัดนี้] สั่งให้ Print Error ทิ้งไว้ใน Log ของ Cloud Run
        print("🚨 CRITICAL ERROR DETAILS:")
        print(err_trace) 
        
        gc.collect()
        return ({"error": str(e), "trace": err_trace[-500:]}, 500, headers)
