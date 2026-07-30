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
import functions_framework
import google.generativeai as genai

# ---------------------------------------------------------------------------
# Backend API สำหรับ AI Cargo Safety Checker ( High-Precision v2 )
# แก้ไข: ครอบคลุมจุดเสี่ยงการเลื่อน/ไถล/พลิกคว่ำ ทุกทิศทาง
# ---------------------------------------------------------------------------

def get_api_keys_pool():
    raw_keys = ""
    found_var_name = ""
    
    for env_k, env_v in os.environ.items():
        k_upper = env_k.upper().strip()
        if ("GEMINI" in k_upper or "API_KEY" in k_upper) and env_v and env_v.strip():
            raw_keys = env_v.strip()
            found_var_name = env_k
            break
            
    if not raw_keys:
        raw_keys = os.environ.get("GEMINI_API_KEYS", 
                   os.environ.get("GEMINI_API_KEY", 
                   os.environ.get("gemini_api_keys", 
                   os.environ.get("gemini_api_key", "")))).strip()

    keys = [k.strip() for k in raw_keys.split(",") if k.strip()]
    if keys:
        print(f"✅ Successfully loaded {len(keys)} API keys from variable: '{found_var_name}'")
    return keys

def generate_action_report(case_type, description):
    actions = {
        "DOOR_TALL_RISK":
            f"🚨🚨 [CRITICAL] พบสินค้าสูงโดดเดี่ยวบริเวณปากประตู ไม่มีสินค้าค้ำด้านหลัง\n{description}\n"
            f"🛠️ ACTION: ห้ามเปิดประตูก่อนค้ำยัน! ติดตั้ง Rear Tomming แนวดิ่งทันที + รัดตรึงกองสูงทุกจุด "
            f"ก่อนเปิดประตูตู้สินค้าทุกครั้ง",

        "STEP_DOWN_RISK":
            f"🚨 [ALERT] พบรอยต่างระดับระหว่างกองสินค้า (Step-Down)\n{description}\n"
            f"🛠️ ACTION: ติดตั้งแผ่นไม้กั้นขวาง (Void Filler / Dunnage) ระหว่างกอง และรัดตรึงให้ครบทุกจุด",

        "REAR_EMPTY_RISK":
            f"🚨 [ALERT] พบพื้นที่โล่ง/สินค้าต่างระดับ ฝั่งประตูท้ายตู้ (REAR)\n{description}\n"
            f"🛠️ ACTION: ติดตั้งแผ่นไม้ค้ำแนวดิ่ง (Rear Tomming) + รัดตรึงป้องกันสินค้าไถลออกประตู",

        "FRONT_EMPTY_RISK":
            f"🚨 [ALERT] พบพื้นที่โล่ง/สินค้าต่างระดับ ฝั่งผนังหัวตู้ (FRONT)\n{description}\n"
            f"🛠️ ACTION: ติดตั้งแผ่นไม้ค้ำฝั่งหัวตู้ (Front Blocking) + รัดตรึงป้องกันสินค้าไถลหน้า",

        "LATERAL_GAP_RISK":
            f"🚨 [ALERT] พบช่องว่างด้านข้างระหว่างกองสินค้า (Lateral Gap)\n{description}\n"
            f"🛠️ ACTION: ใส่ Air Bag หรือ Void Filler ด้านข้าง + รัดตรึงป้องกันสินค้าเลื่อนตะแคง",

        "TALL_UNSTABLE_RISK":
            f"🚨 [ALERT] พบสินค้าสูงโดดเดี่ยว หรือกองสูงชันไม่มีของข้างค้ำ (Tall/Unstable)\n{description}\n"
            f"🛠️ ACTION: ค้ำยันด้านข้างกองสูง + รัดตรึงแนวขวาง ป้องกันล้มตะแคง",

        "OVERHANG_RISK":
            f"🚨 [ALERT] พบสินค้าชั้นบนยื่นพ้นขอบสินค้าชั้นล่าง (Overhang)\n{description}\n"
            f"🛠️ ACTION: จัดเรียงใหม่ให้ชั้นบนไม่ยื่นพ้นฐาน หรือใส่แผ่นรองรับและรัดตรึง",
    }
    return actions.get(case_type,
        "🟢 [STATUS] ปลอดภัย (SAFE)\nไม่พบจุดเสี่ยงที่ต้องดำเนินการเพิ่มเติม")

def clean_json_response(text):
    text = text.strip()
    start_list = text.find('[')
    end_list = text.rfind(']')
    start_dict = text.find('{')
    end_dict = text.rfind('}')
    
    if start_list != -1 and end_list != -1:
        if start_dict == -1 or start_list < start_dict:
            return text[start_list:end_list+1]
            
    if start_dict != -1 and end_dict != -1:
        return text[start_dict:end_dict+1]
        
    return text

def analyze_diagram_image_with_ai(diagram_image: PIL.Image.Image):
    api_keys = get_api_keys_pool()
    if not api_keys:
        env_keys_list = [k for k in os.environ.keys() if not k.startswith("NIX_")]
        return [{
            "risk_type": "ERROR", 
            "description": f"ไม่พบตัวแปร GEMINI_API_KEYS ใน Cloud Run | Env Vars: {env_keys_list[:8]}"
        }]

    # =====================================================================
    # PROMPT v3 — ครอบคลุมจุดเสี่ยงทุกทิศทาง + Perspective Guard
    #             ป้องกัน False Positive จาก 3D perspective distortion
    # =====================================================================
    prompt = """
You are an expert Cargo Loading Safety Inspector analyzing a MaxLoad Pro 3D loading diagram.
Your mission: detect REAL physical risks of cargo shifting, sliding, tipping, or collapsing
inside the container — in ANY direction. Precision is critical. False alarms are as harmful
as missed risks.

This image is Page 2 of the manifest. It contains TWO 3D perspective diagrams of the SAME
truck/container, viewed from different camera angles, labeled "Front" and "Back".
These labels are CAMERA VIEW NAMES only — not the physical front or rear of the vehicle.

=======================================================================
PART 1 — PHYSICAL ORIENTATION (mandatory first step for EACH view)
=======================================================================

Identify these two physical landmarks in EACH diagram independently:

  • DOOR END (Physical Rear of vehicle):
    - The OPEN end — no solid wall closing it
    - Visible YELLOW FLOOR GRID extending out
    - TWO RED ARROWS on or near the floor at this end
    - Cargo here is the LAST to be loaded, FIRST to unload

  • HEAD WALL (Physical Front of vehicle):
    - The CLOSED end — a SOLID YELLOW/TAN WALL seals it
    - No floor grid extension, no red arrows
    - Cargo here is pushed all the way to this wall first

⚠️ CRITICAL PERSPECTIVE WARNING:
These are 3D isometric/perspective drawings. Boxes that are FARTHER from the camera
appear SMALLER and LOWER in the image, even if they are the SAME PHYSICAL HEIGHT.
DO NOT judge cargo height from apparent pixel height alone.
To correctly compare heights: count the NUMBER OF BOX LAYERS stacked vertically,
not the pixel height. One layer = one box height unit, regardless of perspective.

=======================================================================
PART 2 — RISK DETECTION (scan BOTH views, all 6 risk types)
=======================================================================

For each view, scan column by column along the container's length (Door→Head Wall).
Count layers carefully using the box grid lines, not pixel size.

--- RISK TYPE 1: REAR_EMPTY_RISK (longitudinal, toward door) ---
UNDERSTAND THE PHYSICS FIRST:
  The DOOR END is the last barrier before cargo falls out. ANY height mismatch here
  is dangerous — whether the door-side column is too SHORT (unsupported above, can topple
  inward) OR too TALL (sticks up beyond neighbors, no support behind it, falls OUT when
  door opens). BOTH are equally dangerous.

TRIGGER — must satisfy AT LEAST ONE:
  (a) Empty floor grid is visible at the DOOR END (red arrows side) — no boxes where
      floor grid is exposed and additional cargo could have been placed
  (b) The cargo column nearest the DOOR END is ≥2 layers SHORTER than the adjacent
      interior column → unsupported gap above, inward topple risk
  (c) *** NEW *** The cargo column nearest the DOOR END is ≥2 layers TALLER than the
      adjacent interior column → tall column at door has NO SUPPORT BEHIND IT,
      will fall outward when door opens. This is HIGH PRIORITY — look for this.

VISUAL CUE FOR (c): In the Front/Back view, the DOOR END column sticks up above
  the rest of the cargo like a "tower" or "spike" at the open end.
  Example: interior columns are 2 layers, door-side column is 3-4 layers = TRIGGER.

NOT a trigger:
  - All columns at and near the door are the same layer count (uniform height = safe)
  - Single-layer difference (1 layer) that is symmetric and intentional
  - Perspective-caused apparent size difference — verify by counting actual box layers

--- RISK TYPE 2: FRONT_EMPTY_RISK (longitudinal, toward head wall) ---
TRIGGER — must satisfy AT LEAST ONE:
  (a) A visible empty floor gap exists between the HEAD WALL and the first cargo column
  (b) The cargo column touching or nearest the HEAD WALL is ≥2 layers SHORTER than
      the column beside it (count actual box layers)
NOT a trigger:
  - Boxes touching or nearly touching the yellow wall at the SAME layer count as
    their neighbors — this is SAFE, do NOT report it
  - Perspective making far boxes look smaller — verify layer count before reporting

--- RISK TYPE 3: STEP_DOWN_RISK (longitudinal, middle section) ---
TRIGGER:
  - Any two ADJACENT columns in the MIDDLE portion differ by ≥2 box layers in height
  - Creates an unsupported face on the taller column that can topple
NOT a trigger:
  - A 1-layer difference across the entire load (gradual taper is often intentional)
  - Perspective distortion making uniform stacks appear uneven

--- RISK TYPE 3b: DOOR_TALL_RISK (highest priority — falls out on door open) ---
THIS IS THE MOST DANGEROUS SCENARIO — prioritize detection above all others.

PHYSICS: When the truck door opens, there is ZERO barrier behind the door-side cargo.
A tall column at the door end that is higher than its neighbors has:
  - No cargo support behind it (the door was the only thing holding it)
  - Gravity + vibration will cause it to tip outward immediately

TRIGGER:
  - The column(s) at or within 1 column of the DOOR END are visibly taller (≥1 layer)
    than the columns further inside the container
  - The tall column at the door has empty space or missing cargo on its DOOR-FACING side
  - Result: cargo tower at door with no rear support → falls out when door opens

VISUAL SIGNATURE: Look for a "staircase going UP toward the door" — cargo gets taller
  as you move toward the open end. This is opposite of safe loading (should taper down).

NOT a trigger:
  - All columns uniform height all the way to the door (safe)
  - Taller column is in the MIDDLE, not at the door end

--- RISK TYPE 4: LATERAL_GAP_RISK (side-to-side / width direction) ---
TRIGGER:
  - A visible empty lane or gap runs along the WIDTH of the container (side to side)
  - Cargo does not span full container width, leaving floor grid exposed on a side wall
NOT a trigger:
  - Normal spacing between individual boxes within a column (box joints, not gaps)
  - The visual gap between two stacked rows when viewed in perspective

--- RISK TYPE 5: TALL_UNSTABLE_RISK (multi-directional tipping risk) ---
TRIGGER:
  - One column or group is ≥2 layers taller than ALL neighbors on BOTH longitudinal
    sides AND both lateral sides — isolated tall stack with no support on multiple faces
NOT a trigger:
  - A tall column that is against the head wall (wall provides support on one face)
  - A column taller on one side only (needs support on that one side, not all)

--- RISK TYPE 6: OVERHANG_RISK (vertical / toppling) ---
TRIGGER:
  - A box on the TOP of a stack visually extends beyond the footprint of the boxes
    directly beneath it — the top layer's edge exceeds the layer below's edge
NOT a trigger:
  - Normal 3D perspective making top faces look offset (check actual edge alignment)

=======================================================================
PART 3 — SELF-CHECK BEFORE REPORTING (mandatory)
=======================================================================

Before adding any risk to your output, ask yourself:
  1. Did I COUNT the actual box layers, or did I judge by pixel height? (must count)
  2. Could perspective distortion explain this apparent height difference? (if yes → skip)
  3. Is the cargo touching the head wall at THE SAME layer count as its neighbor?
     (if same count → NOT FRONT_EMPTY_RISK, do not report)
  4. Is the empty space I see actually empty floor, or just the perspective gap between
     box rows? (must be actual uncovered floor grid → report; perspective gap → skip)
  5. Does this risk meet the ≥2 layer threshold? (1-layer difference alone → not reportable
     UNLESS it is combined with an actual empty floor area)

=======================================================================
PART 4 — BOUNDING BOX RULES
=======================================================================

- Format: [ymin, xmin, ymax, xmax] normalized 0–1000.
  (0,0) = TOP-LEFT of the ENTIRE image sent to you.
- Draw TIGHTLY around the specific cargo boxes or floor area that triggered the risk.
- NEVER draw a box in the white margin or outside the container outline.
- Height mismatch: box covers the taller column + shorter adjacent column together.
- Empty floor: box covers only the visible uncovered yellow floor grid area.
- Lateral gap: box covers the empty space between cargo groups (width direction).
- Overhang: box covers the overhanging top layer only.

=======================================================================
OUTPUT FORMAT — Strict JSON array only. No markdown, no preamble.
=======================================================================

Return ONLY a valid JSON array. Each detected risk is one object.
If multiple risks of the same type exist in different locations, create separate objects.
If NO risks are found at all, return: []

Schema for each risk object:
{
  "view": "FRONT" | "BACK",
  "risk_type": "DOOR_TALL_RISK" | "REAR_EMPTY_RISK" | "FRONT_EMPTY_RISK" | "STEP_DOWN_RISK" | "LATERAL_GAP_RISK" | "TALL_UNSTABLE_RISK" | "OVERHANG_RISK",
  "direction": "LONGITUDINAL" | "LATERAL" | "VERTICAL",
  "reasoning": "<Visual evidence: describe exactly what you see — which boxes, which columns, what height difference, what gap size>",
  "description": "<Thai language: อธิบายตำแหน่งและลักษณะของความเสี่ยงที่พบ>",
  "box_2d": [ymin, xmin, ymax, xmax]
}

Example of correct output (do not copy — use your actual findings):
[
  {
    "view": "FRONT",
    "risk_type": "STEP_DOWN_RISK",
    "direction": "LONGITUDINAL",
    "reasoning": "Column at x≈0.4 has 3 layers high. Column at x≈0.55 has only 2 layers, creating a 1-layer step down toward the door end.",
    "description": "พบสินค้าต่างระดับ 1 ชั้น บริเวณกลางตู้ มุมมอง FRONT คอลัมน์ที่ 3-4 สูงกว่าคอลัมน์ที่ 5 ทำให้เกิดแรงดันด้านข้าง",
    "box_2d": [320, 380, 680, 620]
  },
  {
    "view": "BACK",
    "risk_type": "LATERAL_GAP_RISK",
    "direction": "LATERAL",
    "reasoning": "In the BACK view, cargo on the left side stops at approximately x=0.45 of the container width. The right side from x=0.45 to x=0.75 shows empty yellow floor, meaning cargo does not span full width.",
    "description": "พบช่องว่างด้านข้างตู้ฝั่งขวา มุมมอง BACK สินค้าไม่เต็มความกว้าง เสี่ยงเลื่อนตะแคงขณะเลี้ยว",
    "box_2d": [450, 500, 850, 750]
  }
]
"""
    
    model_candidates = ["models/gemini-flash-latest", "gemini-flash-latest"]
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
                        
                        if not clean_text or clean_text == '""' or clean_text == "[]":
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
                        elif "429" in err_str or "quota" in err_str.lower() or "resourceexhausted" in err_str.lower():
                            raise model_err
                        else:
                            break

            except Exception as key_err:
                last_error_msg = str(key_err)
                continue
        
        if pass_round == 0:
            time.sleep(10)

    return [{"risk_type": "ERROR", "description": f"AI Error (รวมทั้ง {len(api_keys)} Keys): {last_error_msg[:120]}"}]

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

        try:
            pages = convert_from_bytes(pdf_bytes, first_page=2, last_page=2, dpi=180)
        except Exception:
            pages = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=180)
        
        if not pages:
            return ({"error": "Cannot render PDF page data"}, 400, headers)

        img = pages[0]
        width, height = img.size
        
        crop_y_start = int(height * 0.10)
        crop_y_end = int(height * 0.90)
        crop_w = width
        crop_h = crop_y_end - crop_y_start

        diagram_crop = img.crop((0, crop_y_start, crop_w, crop_y_end))

        all_risks = analyze_diagram_image_with_ai(diagram_crop)

        draw = PIL.ImageDraw.Draw(img)
        detected_hazards = []

        # ---- Color map ต่อ risk_type ----
        RISK_COLORS = {
            "DOOR_TALL_RISK":    "red",      # อันตรายสูงสุด — แดงสด
            "STEP_DOWN_RISK":    "orangered",
            "REAR_EMPTY_RISK":   "orange",
            "FRONT_EMPTY_RISK":  "yellow",
            "LATERAL_GAP_RISK":  "cyan",
            "TALL_UNSTABLE_RISK":"magenta",
            "OVERHANG_RISK":     "lime",
        }

        VALID_RISK_TYPES = set(RISK_COLORS.keys())

        if isinstance(all_risks, list):
            for risk in all_risks:
                raw_risk_type = str(risk.get("risk_type", "")).upper().strip()
                view_name = str(risk.get("view", "GENERAL")).upper()

                # ---- normalize risk_type ----
                matched_type = None
                for vrt in VALID_RISK_TYPES:
                    if vrt.replace("_RISK","") in raw_risk_type or raw_risk_type in vrt:
                        matched_type = vrt
                        break
                if matched_type is None and raw_risk_type in VALID_RISK_TYPES:
                    matched_type = raw_risk_type

                if raw_risk_type == "ERROR":
                    detected_hazards.append({
                        "title": "⚠️ ข้อผิดพลาด API",
                        "detail": risk.get("description", "โปรดตรวจสอบโควตา Gemini API Keys"),
                        "is_error": True
                    })
                    continue

                if matched_type is None:
                    continue  # skip unknown risk types

                risk_type = matched_type
                desc = risk.get("description", "พบความไม่สมดุลของสินค้า")
                direction = risk.get("direction", "")
                box = risk.get("box_2d") or risk.get("boundingBox") or risk.get("box2d") or risk.get("box")
                outline_color = RISK_COLORS.get(risk_type, "red")
                
                drawn_exact = False
                if box and isinstance(box, list) and len(box) == 4:
                    try:
                        ymin, xmin, ymax, xmax = map(float, box)
                        if max(ymin, xmin, ymax, xmax) <= 1.0 and max(ymin, xmin, ymax, xmax) > 0:
                            ymin, xmin, ymax, xmax = ymin*1000, xmin*1000, ymax*1000, xmax*1000
                            
                        abs_xmin = int(xmin * crop_w / 1000.0)
                        abs_xmax = int(xmax * crop_w / 1000.0)
                        abs_ymin = int(crop_y_start + (ymin * crop_h / 1000.0))
                        abs_ymax = int(crop_y_start + (ymax * crop_h / 1000.0))
                        
                        draw.rectangle([abs_xmin, abs_ymin, abs_xmax, abs_ymax],
                                       outline=outline_color, width=8)
                        drawn_exact = True
                    except Exception:
                        pass
                        
                if not drawn_exact:
                    draw.rectangle([0, crop_y_start, crop_w, crop_y_end],
                                   outline=outline_color, width=8)
                
                dir_label = f" [{direction}]" if direction else ""
                detected_hazards.append({
                    "title": f"ความเสี่ยง ({view_name}){dir_label}: {risk_type}",
                    "detail": generate_action_report(risk_type, desc),
                    "is_error": False
                })

        real_hazards = [h for h in detected_hazards if not h.get("is_error", False)]
        has_errors = any(h.get("is_error", False) for h in detected_hazards)

        if len(real_hazards) > 0:
            status_text = f"พบจุดเสี่ยงอันตราย ({len(real_hazards)} จุด)"
            action_text = "\n\n--------------------------------------------------\n\n".join(
                [f"[{h['title']}]\n{h['detail']}" for h in detected_hazards]
            )
            hazard_count = len(real_hazards)
        elif has_errors:
            status_text = "เกิดข้อผิดพลาดในการวิเคราะห์ AI"
            action_text = "\n\n--------------------------------------------------\n\n".join(
                [f"[{h['title']}]\n{h['detail']}" for h in detected_hazards]
            )
            hazard_count = 0
        else:
            status_text = "ปลอดภัย (SAFE)"
            action_text = generate_action_report("SAFE", "")
            hazard_count = 0

        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=80)
        processed_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
        processed_image_url = f"data:image/jpeg;base64,{processed_base64}"

        gc.collect()

        return ({
            "status": status_text,
            "hazardCount": hazard_count,
            "actionRequired": action_text,
            "processedImageUrl": processed_image_url
        }, 200, headers)

    except Exception as e:
        gc.collect()
        return ({"error": str(e)}, 500, headers)
