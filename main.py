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

def analyze_diagram_image_with_ai(diagram_image: PIL.Image.Image):
    api_keys = get_api_keys_pool()
    if not api_keys:
        env_keys_list = [k for k in os.environ.keys() if not k.startswith("NIX_")]
        return [{
            "risk_type": "ERROR", 
            "description": f"ไม่พบตัวแปร GEMINI_API_KEYS ใน Cloud Run (กรุณาตรวจเช็คชื่อตัวแปรใน Cloud Run Variables & Secrets) | Env Vars ที่มีในระบบ: {env_keys_list[:8]}"
        }]

    prompt = """
You are an expert Cargo Loading Safety Inspector analyzing a 3D container loading diagram on Page 2 of a manifest PDF.

### STEP 1: LAYOUT IDENTIFICATION
Determine the layout arrangement of the 2 diagrams on Page 2:
- TYPE A (Top-Bottom Layout): "Front" diagram is in the TOP HALF. "Back" diagram is in the BOTTOM HALF.
- TYPE B (Side-by-Side Layout): "Front" diagram is in the LEFT HALF. "Back" diagram is in the RIGHT HALF.

### STEP 2: CRITICAL CONTAINER ORIENTATION RULES (MUST READ)
WARNING: The text "Front" or "Back" printed in the corner of the diagram is merely the name of the camera view. DO NOT use it to identify the physical front or rear of the vehicle.

Apply these physical rules strictly to BOTH views:
1. PHYSICAL REAR (DOOR END) = The open side showing the floor grid, 2 red arrows nearby, and no wall. 
   -> ANY empty space here is the REAR of the truck.
2. PHYSICAL FRONT (HEAD WALL) = The solid yellow wall. Opposite DOOR END always.
3. Observe cargo layout from the SOLID YELLOW WALL (Front) toward the OPEN END (Rear).

### STEP 3: MANDATORY EXHAUSTIVE INSPECTION (MUST FIND ALL)
You MUST scan BOTH diagrams comprehensively. 
- It is VERY COMMON to have MULTIPLE hazards in a single view (e.g., a hazard at the front AND a hazard at the rear in the same image).
- You MUST return a separate JSON object for EVERY single hazard you find. Do not stop at just one.

### STEP 4: CARGO COLLAPSE & SLIDE RISK CRITERIA
Inspect ONLY physical height drops and floor gaps:

1. REAR_EMPTY_RISK (พื้นที่ว่างท้ายตู้):
   - Unfilled floor space, gaps, or cargo height drops located at the OPEN REAR DOOR END (the side with floor grids and 2 red arrows nearby).
   - OR a cargo height drop (step-down) facing the rear door. If the last stack of cargo near the red arrows is LOWER than the cargo behind it, THIS IS A RISK. Flag it.
   - High risk of cargo sliding out of the container doors.
   - *CRITICAL FIX*: If you see an empty grid space (like the red box area), it is the REAR, NOT the front. This must be flagged as REAR_EMPTY_RISK.

2. STEP_DOWN_RISK:
   - Unsupported height step drop GREATER THAN OR EQUAL TO 1 CARGO LAYER between adjacent cargo stacks.
   - IGNORE flat top surfaces where adjacent cargo stacks have the EXACT SAME height.
   - This risk can occur within adjacent inner longitudinal rows, adjacent outer longitudinal rows, or as a pocket/depression height drop at the contact interface between inner and outer rows.
   
3. FRONT_EMPTY_RISK (พื้นที่ว่างหัวตู้):
   - Unfilled floor space or lower tier stacks placed DIRECTLY AGAINST THE SOLID YELLOW FRONT WALL.
   - OR lower tier stacks (step-down) placed against the yellow wall. If the cargo touching the yellow wall is LOWER than the cargo in front of it, it creates an empty gap at the top. THIS IS A RISK. Flag it.
   - This applies ONLY to the solid wall side, never the open side.

### CRITICAL RULES:
- Bounding Box Format: [ymin, xmin, ymax, xmax] in normalized coordinates (0 to 1000).
- If the container is fully packed with a flat surface and no height drop, return an empty array [].
- DO NOT hallucinate height drops on flat cargo surfaces.

### OUTPUT FORMAT:
Return strictly a valid JSON array of objects. Example of returning MULTIPLE risks:
[
  {
    "view": "FRONT",
    "risk_type": "FRONT_EMPTY_RISK",
    "description": "พบสินค้าเตี้ยกว่าระดับปกติวางชิดผนังหัวตู้สีเหลือง ทำให้เกิดพื้นที่ว่างด้านบน",
    "box_2d": [200, 100, 500, 300]
  },
  {
    "view": "FRONT",
    "risk_type": "REAR_EMPTY_RISK",
    "description": "พบสินค้าระดับเตี้ยลงทางฝั่งประตูท้ายตู้ (ด้านที่เปิดโล่ง) เสี่ยงต่อการล้มสไลด์",
    "box_2d": [500, 700, 900, 950]
  }
]
""""

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
