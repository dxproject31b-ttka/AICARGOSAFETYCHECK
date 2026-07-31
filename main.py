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
# Backend API สำหรับ AI Cargo Safety Checker ( High-Precision Rear/Front Engine )
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
    if case_type == "STEP_DOWN_RISK":
        return f"🚨 [ALERT] พบรอยเหลื่อมต่างระดับมากกว่า 1 ชั้นบริเวณกลางตู้\n{description}\n🛠️ ACTION: ติดตั้งแผ่นไม้กั้นขวางและรัดตรึงป้องกันสินค้าล้มไถล"
    elif case_type == "REAR_EMPTY_RISK":
        return f"🚨 [ALERT] พบสินค้าต่างระดับ/พื้นที่โล่งบริเวณฝั่งท้ายตู้ประตูเปิด (REAR)\n{description}\n🛠️ ACTION: ติดตั้งแผ่นไม้ค้ำยันแนวดิ่ง (Rear Tomming) และรัดตรึงป้องกันสินค้าล้มไถล"
    elif case_type == "FRONT_EMPTY_RISK":
        return f"🚨 [ALERT] พบสินค้าสูงขนาบพื้นที่โล่งติดผนังหัวตู้สีเหลือง (FRONT)\n{description}\n🛠️ ACTION: ติดตั้งแผ่นไม้ค้ำยันฝั่งหัวตู้ (Front Blocking) และรัดตรึงป้องกันสินค้าล้มไถล"
    else:
        return "🟢 [STATUS] ปลอดภัย (SAFE)\nไม่มีความเสี่ยงที่ต้องดำเนินการเพิ่มเติม"

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

def analyze_rear_zone_with_ai(rear_crop: PIL.Image.Image, api_keys: list):
    """
    ส่งภาพ Crop เฉพาะ Zone 3 (ท้ายตู้) ให้ AI วิเคราะห์ซ้ำอีกรอบ
    เพื่อยืนยัน / จับ REAR_EMPTY_RISK ที่อาจพลาดจากภาพเต็ม
    """
    rear_prompt = """
You are a Cargo Safety Inspector focusing ONLY on the REAR (DOOR END) zone of a container.
This image is a zoomed-in crop of approximately the right 35% of a 3D isometric container diagram, showing the door end area.

### YOUR ONLY TASK: Assess REAR_EMPTY_RISK
Look for these specific signals in this cropped image:
1. Is there a visible empty yellow floor grid near the open door end?
2. Is the last cargo stack clearly 1 or more full box layers shorter than the stacks just behind it (further inside the container)?
3. Is there an unsupported upper gap above the last cargo stack that could cause it to topple when the door is opened?

### DECISION RULE:
- If ANY of the above signals are clearly visible → report REAR_EMPTY_RISK
- If the cargo stacks appear uniform in height and no floor gap is visible → report SAFE
- If perspective distortion makes it impossible to judge clearly → report SAFE (do not guess)

### OUTPUT FORMAT:
Return ONLY a valid JSON object (not an array):
{
  "rear_zone_risk": "REAR_EMPTY_RISK" or "SAFE",
  "reasoning": "Describe exactly what you see — stack heights, floor gaps, unsupported gaps.",
  "confidence": "HIGH" or "MEDIUM" or "LOW"
}
"""
    last_err = ""
    for current_key in api_keys:
        try:
            genai.configure(api_key=current_key)
            model = genai.GenerativeModel(
                model_name="gemini-flash-latest",
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
            continue
    return {"rear_zone_risk": "ERROR", "reasoning": last_err[:120], "confidence": "LOW"}


def analyze_diagram_image_with_ai(diagram_image: PIL.Image.Image):
    api_keys = get_api_keys_pool()
    if not api_keys:
        env_keys_list = [k for k in os.environ.keys() if not k.startswith("NIX_")]
        return [{
            "risk_type": "ERROR", 
            "description": f"ไม่พบตัวแปร GEMINI_API_KEYS ใน Cloud Run (กรุณาตรวจเช็คชื่อตัวแปรใน Cloud Run Variables & Secrets) | Env Vars ที่มีในระบบ: {env_keys_list[:8]}"
        }]

    prompt = """
You are an expert Cargo Loading Safety Inspector analyzing a 3D isometric container loading diagram from a manifest PDF.

---
### STEP 1: LAYOUT IDENTIFICATION
Identify which of 2 layout types is used on this page:
- TYPE A (Top-Bottom): "Front" diagram = TOP HALF | "Back" diagram = BOTTOM HALF
- TYPE B (Side-by-Side): "Front" diagram = LEFT HALF | "Back" diagram = RIGHT HALF
Analyze EACH diagram independently. Do not mix findings between diagrams.

---
### STEP 2: CRITICAL CONTAINER ORIENTATION RULES
WARNING: Labels "Front" / "Back" are camera view names ONLY. Do NOT use them to identify physical ends.
Use these visual landmarks instead:
1. PHYSICAL REAR (DOOR END) = Open side with visible yellow floor grid + 2 red arrows. No wall present.
2. PHYSICAL FRONT (HEAD WALL) = Solid yellow wall. Always opposite the door end.

Zone direction per diagram:
- FRONT view: LEFT side = Zone 3 (Door/Red Arrows) | CENTER = Zone 2 | RIGHT side = Zone 1 (Yellow Wall)
- BACK view:  LEFT side = Zone 1 (Yellow Wall) | CENTER = Zone 2 | RIGHT side = Zone 3 (Door/Red Arrows)

---
### STEP 3: DENSE CARGO AWARENESS (CRITICAL FOR HIGH-UTILIZATION LOADS)
When cargo fill rate is high (approx. 70%+), boxes are tightly packed and the 3D isometric angle can create optical illusions.
Apply these extra cautions:
- A height difference caused purely by the 3D camera perspective (diagonal visual slope) is NOT a real step-down. Look for actual box edges that are lower than adjacent stacks.
- If the top surface of cargo appears as one continuous diagonal slope (typical of a full load viewed at an angle), this is perspective distortion, NOT a step-down risk.
- Only flag a risk if you can clearly count that one stack is 1 full box layer shorter than the adjacent stack.

---
### STEP 4: ZONE 2 ANCHOR RULE (MANDATORY — prevents false positives)
Before reporting FRONT_EMPTY_RISK or REAR_EMPTY_RISK, you MUST first assess Zone 2 (middle) as a height reference anchor.

FRONT_EMPTY_RISK decision logic (Zone 1 vs Zone 2):
- Measure: Is Zone 1 (head wall cargo) clearly lower than Zone 2 (middle cargo) by 1 or more full box layers?
  - YES, Zone 1 is clearly ≥1 layer lower than Zone 2 → REPORT FRONT_EMPTY_RISK
  - NO, Zone 1 is at same height OR only slightly lower than Zone 2 (less than 1 full layer) → DO NOT REPORT. Mark as SAFE for Zone 1.
  - UNCERTAIN due to 3D perspective distortion → DO NOT REPORT. Err on side of caution (no false alarm).

REAR_EMPTY_RISK decision logic (Zone 3 vs Zone 2):
- Measure: Is Zone 3 (door end cargo) clearly lower than Zone 2 (middle cargo) by 1 or more full box layers? OR is the floor grid empty at door end?
  - YES, clearly ≥1 layer lower or floor is empty → REPORT REAR_EMPTY_RISK
  - NO, Zone 3 is same height or slightly lower → DO NOT REPORT.
  - UNCERTAIN → DO NOT REPORT.

STEP_DOWN_RISK decision logic (within Zone 2):
- Is there a sudden height drop of ≥1 full box layer between adjacent stacks inside Zone 2?
  - YES, clearly ≥1 layer difference → REPORT STEP_DOWN_RISK
  - NO or UNCERTAIN → DO NOT REPORT.

---
### STEP 5: SYSTEMATIC ZONAL INSPECTION SEQUENCE (MUST FOLLOW IN ORDER)
For EACH diagram view independently:

[A] Identify Zone 2 height first → record as your reference baseline.
[B] Compare Zone 1 height vs Zone 2 baseline → apply FRONT_EMPTY_RISK logic above.
[C] Compare Zone 3 height vs Zone 2 baseline → apply REAR_EMPTY_RISK logic above.
[D] Inspect Zone 2 internally for sudden drops → apply STEP_DOWN_RISK logic above.
[E] If NO risk found in any zone → return SAFE entry for that view.

---
### STEP 6: STRICT BOUNDING BOX ACCURACY
- Format: [ymin, xmin, ymax, xmax] in normalized coordinates (0 to 1000).
- NEVER draw bounding boxes in empty white space outside the container boundary.
- For empty floor gaps → draw box tightly around the visible empty YELLOW FLOOR GRID only.
- For height step-downs → draw box tightly around the cargo boxes forming the uneven edge.
- If risk is uncertain, do not draw a box — omit the entry entirely.

---
### OUTPUT FORMAT:
Return ONLY a valid JSON array. Each object MUST contain "reasoning" written BEFORE box_2d is calculated.
Use this structure:

[
  {
    "view": "FRONT",
    "risk_type": "FRONT_EMPTY_RISK",
    "zone2_baseline": "Zone 2 cargo height appears to be 3 layers tall across the full width.",
    "reasoning": "Zone 1 check: Cargo at yellow wall is visibly 2 layers tall — clearly 1 full layer shorter than Zone 2 baseline of 3 layers. Height gap is unambiguous, not a perspective artifact.",
    "description": "พบสินค้าชิดผนังหัวตู้สีเหลืองเตี้ยกว่ากลางตู้อย่างชัดเจนมากกว่า 1 ชั้น เสี่ยงสินค้าเลื่อนไถล",
    "box_2d": [300, 150, 600, 350]
  },
  {
    "view": "BACK",
    "risk_type": "REAR_EMPTY_RISK",
    "zone2_baseline": "Zone 2 cargo height is 3 layers. Zone 3 near red arrows shows only 2 layers with empty floor grid visible.",
    "reasoning": "Zone 3 check: Last stack near red arrows is 1 full layer lower than Zone 2 baseline. Empty yellow floor grid is visible at door end. Risk confirmed.",
    "description": "พบสินค้าฝั่งประตูท้ายตู้ต่ำกว่ากลางตู้ 1 ชั้น และเห็นพื้นตู้โล่ง เสี่ยงสินค้าล้มออกเมื่อเปิดประตู",
    "box_2d": [600, 750, 950, 950]
  },
  {
    "view": "FRONT",
    "risk_type": "SAFE",
    "zone2_baseline": "Zone 2 cargo is 3 layers uniform.",
    "reasoning": "All zones in FRONT view are at equal height. No step-down or empty gap detected. Dense load with perspective distortion confirmed but no real height difference found.",
    "description": "ปลอดภัย ไม่พบความเสี่ยงในมุมมอง FRONT",
    "box_2d": null
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

        # --- STEP 1: Render PDF at higher DPI for clearer layer detection ---
        try:
            pages = convert_from_bytes(pdf_bytes, first_page=2, last_page=2, dpi=250)
        except Exception:
            try:
                pages = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=250)
            except Exception:
                pages = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=180)

        if not pages:
            return ({"error": "Cannot render PDF page data"}, 400, headers)

        img = pages[0]
        width, height = img.size

        # --- STEP 2: Crop diagram area (remove header/footer) ---
        crop_y_start = int(height * 0.10)
        crop_y_end = int(height * 0.90)
        crop_w = width
        crop_h = crop_y_end - crop_y_start

        diagram_crop = img.crop((0, crop_y_start, crop_w, crop_y_end))

        # --- STEP 3: Full diagram analysis (all zones) ---
        all_risks = analyze_diagram_image_with_ai(diagram_crop)

        # --- STEP 4: Rear Zone Crop — zoom in on Zone 3 (rightmost 35%) for confirmation ---
        # Crop ทั้งสองครึ่ง (Front diagram และ Back diagram) ฝั่งท้ายตู้แยกกัน
        diagram_half_h = crop_h // 2

        # Front view diagram → Zone 3 อยู่ฝั่งซ้าย (x: 0–35%)
        rear_crop_front = img.crop((
            0,
            crop_y_start,
            int(crop_w * 0.38),
            crop_y_start + diagram_half_h
        ))

        # Back view diagram → Zone 3 อยู่ฝั่งขวา (x: 62–100%)
        rear_crop_back = img.crop((
            int(crop_w * 0.62),
            crop_y_start + diagram_half_h,
            crop_w,
            crop_y_end
        ))

        # วิเคราะห์ท้ายตู้แยกทั้งสองมุม
        api_keys_local = get_api_keys_pool()
        rear_result_front = analyze_rear_zone_with_ai(rear_crop_front, api_keys_local)
        rear_result_back  = analyze_rear_zone_with_ai(rear_crop_back,  api_keys_local)

        # --- STEP 5: Merge rear zone findings into all_risks ---
        # ถ้า rear analysis พบ REAR_EMPTY_RISK และ confidence ไม่ใช่ LOW
        # และยังไม่มีใน all_risks → เพิ่มเข้าไป (ป้องกันการพลาด)
        existing_rear_views = {
            str(r.get("view", "")).upper()
            for r in (all_risks if isinstance(all_risks, list) else [])
            if "REAR_EMPTY" in str(r.get("risk_type", "")).upper()
        }

        for view_label, rear_result in [("FRONT", rear_result_front), ("BACK", rear_result_back)]:
            if not isinstance(rear_result, dict):
                continue
            rear_zone_risk = str(rear_result.get("rear_zone_risk", "")).upper()
            confidence     = str(rear_result.get("confidence", "LOW")).upper()
            reasoning      = rear_result.get("reasoning", "")

            if rear_zone_risk == "REAR_EMPTY_RISK" and confidence in ("HIGH", "MEDIUM"):
                if view_label not in existing_rear_views:
                    # เพิ่ม risk ที่พลาดจากการวิเคราะห์ภาพเต็ม
                    all_risks.append({
                        "view": view_label,
                        "risk_type": "REAR_EMPTY_RISK",
                        "zone2_baseline": "Assessed from rear zone crop independently.",
                        "reasoning": f"[Rear Crop Confirmation] {reasoning}",
                        "description": "พบสินค้าฝั่งประตูท้ายตู้ต่ำกว่ากลางตู้หรือเห็นพื้นโล่ง (ยืนยันจากการวิเคราะห์ภาพ Zoom ท้ายตู้)",
                        "box_2d": None
                    })

        draw = PIL.ImageDraw.Draw(img)
        detected_hazards = []

        if isinstance(all_risks, list):
            for risk in all_risks:
                risk_type = str(risk.get("risk_type", "")).upper().strip()
                view_name = str(risk.get("view", "GENERAL")).upper()
                
                if "STEP_DOWN" in risk_type:
                    risk_type = "STEP_DOWN_RISK"
                elif "REAR_EMPTY" in risk_type:
                    risk_type = "REAR_EMPTY_RISK"
                elif "FRONT_EMPTY" in risk_type:
                    risk_type = "FRONT_EMPTY_RISK"
                elif risk_type == "ERROR":
                    detected_hazards.append({
                        "title": "⚠️ ข้อผิดพลาด API",
                        "detail": risk.get("description", "โปรดตรวจสอบโควตา Gemini API Keys ใน Cloud Run"),
                        "is_error": True
                    })
                    continue
                else:
                    continue
                    
                desc = risk.get("description", "พบความไม่สมดุลของสินค้า")
                box = risk.get("box_2d") or risk.get("boundingBox") or risk.get("box2d") or risk.get("box")
                
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
                        
                        draw.rectangle([abs_xmin, abs_ymin, abs_xmax, abs_ymax], outline="red", width=8)
                        drawn_exact = True
                    except Exception:
                        pass
                        
                if not drawn_exact:
                    draw.rectangle([0, crop_y_start, crop_w, crop_y_end], outline="orange", width=8)
                
                detected_hazards.append({
                    "title": f"ความเสี่ยง ({view_name}): {risk_type}",
                    "detail": generate_action_report(risk_type, desc),
                    "is_error": False
                })

        real_hazards = [h for h in detected_hazards if not h.get("is_error", False)]
        has_errors = any(h.get("is_error", False) for h in detected_hazards)

        if len(real_hazards) > 0:
            status_text = f"พบจุดเสี่ยงอันตราย ({len(real_hazards)} จุด)"
            action_text = "\n\n--------------------------------------------------\n\n".join(
                [f"[{h['title']}]\n{h['detail']}" for h in real_hazards]
            )
            hazard_count = len(real_hazards)
        elif has_errors:
            status_text = "เกิดข้อผิดพลาดในการวิเคราะห์ AI"
            error_hazards = [h for h in detected_hazards if h.get("is_error", False)]
            action_text = "\n\n--------------------------------------------------\n\n".join(
                [f"[{h['title']}]\n{h['detail']}" for h in error_hazards]
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
