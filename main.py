import base64
import io
import json
import os
import time
import gc
from pdf2image import convert_from_bytes
import PIL.Image
import PIL.ImageDraw
import functions_framework
import google.generativeai as genai

# ---------------------------------------------------------------------------
# Backend API สำหรับ AI Cargo Safety Checker ( High-Precision Version )
# ---------------------------------------------------------------------------

def get_api_keys_pool():
    raw_keys = ""
    for env_k, env_v in os.environ.items():
        k_upper = env_k.upper().strip()
        if ("GEMINI" in k_upper or "API_KEY" in k_upper) and env_v and env_v.strip():
            raw_keys = env_v.strip()
            break
            
    if not raw_keys:
        raw_keys = os.environ.get("GEMINI_API_KEYS", os.environ.get("GEMINI_API_KEY", "")).strip()

    return [k.strip() for k in raw_keys.split(",") if k.strip()]

def generate_action_report(case_type, description):
    if case_type == "STEP_DOWN_RISK":
        return f"🚨 [ALERT] พบรอยเหลื่อมต่างระดับมากกว่า 1 ชั้นบริเวณกลางตู้\n{description}\n🛠️ ACTION: ติดตั้งแผ่นไม้กั้นขวางและรัดตรึงป้องกันสินค้าล้มไถล"
    elif case_type == "REAR_EMPTY_RISK":
        return f"🚨 [ALERT] พบสินค้าต่างระดับ/พื้นที่โล่งบริเวณฝั่งประตูท้ายตู้ (REAR)\n{description}\n🛠️ ACTION: ติดตั้งแผ่นไม้ค้ำยันแนวดิ่ง (Rear Tomming) และรัดตรึงป้องกันสินค้าล้มไถล"
    elif case_type == "FRONT_EMPTY_RISK":
        return f"🚨 [ALERT] พบพื้นที่ว่างหรือสินค้าวางต่ำผิดปกติบริเวณชิดผนังหัวตู้สีเหลือง (FRONT)\n{description}\n🛠️ ACTION: ติดตั้งแผ่นไม้ค้ำยันฝั่งหัวตู้ (Front Blocking) และรัดตรึงป้องกันสินค้าล้มไถล"
    else:
        return "🟢 [STATUS] ปลอดภัย (SAFE)\nไม่มีความเสี่ยงที่ต้องดำเนินการเพิ่มเติม"

def clean_json_response(text):
    text = text.strip()
    start_list = text.find('[')
    end_list = text.rfind(']')
    if start_list != -1 and end_list != -1:
        return text[start_list:end_list+1]
    start_dict = text.find('{')
    end_dict = text.rfind('}')
    if start_dict != -1 and end_dict != -1:
        return text[start_dict:end_dict+1]
    return text

def analyze_diagram_image_with_ai(diagram_image: PIL.Image.Image):
    api_keys = get_api_keys_pool()
    if not api_keys:
        return [{"risk_type": "ERROR", "description": "ไม่พบตัวแปร GEMINI_API_KEYS ใน Cloud Run"}]

    prompt = """
You are an expert Cargo Loading Safety Inspector analyzing a 3D container loading diagram from Page 2 of a MaxLoad Pro manifest PDF.

### STEP 1: DETECT DIAGRAM LAYOUT
Identify the layout arrangement on Page 2:
- TYPE A (Stacked Layout): "FRONT" view is in TOP HALF, "BACK" view is in BOTTOM HALF.
- TYPE B (Side-by-Side Layout): "FRONT" view is in LEFT HALF, "BACK" view is in RIGHT HALF.

### STEP 2: PHYSICAL CONTAINER ORIENTATION ANCHORS
NEVER rely on camera labels. Locate physical container ends using these visual anchors:
1. PHYSICAL REAR (DOOR END): The side with an OPEN container floor grid and TWO RED ARROWS.
2. PHYSICAL FRONT (HEAD WALL): The SOLID YELLOW WALL closing the container.

Orientation Mapping Guidelines:
- In "FRONT" View:
  - DOOR END (Red Arrows) = Left Side (Zone 3)
  - MIDDLE = Center Space (Zone 2)
  - HEAD WALL (Yellow Wall) = Right Side (Zone 1)
- In "BACK" View:
  - HEAD WALL (Yellow Wall) = Left Side (Zone 1)
  - MIDDLE = Center Space (Zone 2)
  - DOOR END (Red Arrows) = Right Side (Zone 3)

### STEP 3: STRICT ZONAL RISK CRITERIA
Report a risk ONLY if there is an actual structural safety defect. If the cargo is loaded uniformly, flat, or completely full, return an EMPTY ARRAY `[]`.

1. FRONT_EMPTY_RISK (Zone 1 - Head Wall):
   - Found ONLY if there is an empty floor gap at the yellow wall OR cargo touching the yellow wall is 1+ layers lower than middle cargo.
   - Description (TH): "พบพื้นที่ว่างหรือสินค้าวางต่ำกว่าระดับปกติบริเวณชิดผนังหัวตู้สีเหลือง"

2. STEP_DOWN_RISK (Zone 2 - Middle Container):
   - Found ONLY if adjacent cargo stacks have a height difference of 1 or more layers creating an unbraced step.
   - Description (TH): "พบสินค้าจัดวางต่างระดับเป็นขั้นบันได เสี่ยงต่อการล้มสไลด์ระหว่างขนส่ง"

3. REAR_EMPTY_RISK (Zone 3 - Door End):
   - Found ONLY if the floor grid near the red arrows is empty OR the rear stack is lower/unbraced.
   - Description (TH): "พบพื้นที่ว่างบนพื้นตู้ฝั่งประตูท้าย (บริเวณลูกศรสีแดง) เสี่ยงต่อการเคลื่อนตัวของสินค้า"

### STEP 4: BOUNDING BOX (`box_2d`) RULES
- Format: [ymin, xmin, ymax, xmax] in normalized coordinates (0 to 1000) relative to the input image.
- MUST be tightly drawn around the specific cargo boxes or empty yellow floor grid inside the container drawing ONLY. NEVER output coordinates outside the container drawing frame.

### OUTPUT FORMAT
Return strictly a valid JSON array. If no hazards exist, return `[]`.
Example:
[
  {
    "view": "FRONT",
    "risk_type": "REAR_EMPTY_RISK",
    "reasoning": "In FRONT view, Zone 3 (Left side - Red Arrows) has an empty floor grid visible near the door end.",
    "description": "พบพื้นที่ว่างบนพื้นตู้ฝั่งประตูท้าย (บริเวณลูกศรสีแดง) เสี่ยงต่อการเคลื่อนตัวของสินค้า",
    "box_2d": [550, 100, 850, 380]
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
                        
                        if not clean_text or clean_text in ['""', "[]", "{}"]:
                            return []
                            
                        risks = json.loads(clean_text)
                        if isinstance(risks, dict):
                            risks = [risks]
                        return risks
                    except Exception as model_err:
                        last_error_msg = str(model_err)
                        continue
            except Exception as key_err:
                last_error_msg = str(key_err)
                continue
        if pass_round == 0:
            time.sleep(5)

    return [{"risk_type": "ERROR", "description": f"AI Error: {last_error_msg[:120]}"}]

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
        
        # 📌 FIXสำคัญ: ครอปเฉพาะส่วนรูป 3D ตู้คอนเทนเนอร์ (ความกว้าง 0% ถึง 62%)
        # ตัดตารางข้อความ Load Summary ฝั่งขวาออก 100% ป้องกัน Bounding Box โผล่ไปทับตาราง
        crop_x_start = 0
        crop_x_end = int(width * 0.62)
        crop_y_start = int(height * 0.08)
        crop_y_end = int(height * 0.92)
        
        crop_w = crop_x_end - crop_x_start
        crop_h = crop_y_end - crop_y_start

        diagram_crop = img.crop((crop_x_start, crop_y_start, crop_x_end, crop_y_end))

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
                        "detail": risk.get("description", "โปรดตรวจสอบโควตา Gemini API Keys"),
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
                            
                        abs_xmin = int(crop_x_start + (xmin * crop_w / 1000.0))
                        abs_xmax = int(crop_x_start + (xmax * crop_w / 1000.0))
                        abs_ymin = int(crop_y_start + (ymin * crop_h / 1000.0))
                        abs_ymax = int(crop_y_start + (ymax * crop_h / 1000.0))
                        
                        draw.rectangle([abs_xmin, abs_ymin, abs_xmax, abs_ymax], outline="red", width=8)
                        drawn_exact = True
                    except Exception:
                        pass
                        
                if not drawn_exact:
                    draw.rectangle([crop_x_start, crop_y_start, crop_x_end, crop_y_end], outline="orange", width=8)
                
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
