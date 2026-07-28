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
# Backend API สำหรับ AI Cargo Safety Checker (เวอร์ชัน Self-Healing Exponential Backoff)
# ---------------------------------------------------------------------------

api_key = os.environ.get("GEMINI_API_KEY", "").strip()
if api_key:
    genai.configure(api_key=api_key)

def generate_action_report(case_type, description):
    if case_type == "STEP_DOWN_RISK":
        return f"🚨 [ALERT] พบรอยเหลื่อมต่างระดับ\n{description}\n🛠️ ACTION: ติดตั้งแผงไม้กั้นขวางและรัดสาย Ratchet Strap"
    elif case_type == "REAR_EMPTY_RISK":
        return f"🚨 [ALERT] พบสินค้าสูงขนาบพื้นที่โล่งท้ายตู้\n{description}\n🛠️ ACTION: ติดตั้งโครงไม้ค้ำยันแนวดิ่ง (Rear Tomming) และรัดไขว้กากบาท"
    elif case_type == "FRONT_EMPTY_RISK":
        return f"🚨 [ALERT] พบสินค้าสูงขนาบพื้นที่โล่งหัวตู้\n{description}\n🛠️ ACTION: ติดตั้งค้ำยันกั้นขวางฝั่งหัวรถ (Front Blocking)"
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

def analyze_combined_image_with_ai(combined_image: PIL.Image.Image):
    if not api_key:
        return [{"risk_type": "ERROR", "description": "ไม่พบ GEMINI_API_KEY ใน Cloud Run"}]

    prompt = """
    You are an expert Cargo Loading Safety Inspector. 
    Analyze this combined 3D cargo diagram containing TWO stacked views:
    - TOP HALF: FRONT view of container
    - BOTTOM HALF: BACK view of container

    CRITICAL RULES:
    1. STEP_DOWN_RISK: Cargo top surface is not flat across all blocks.
    2. REAR_EMPTY_RISK: Tall cargo stack but empty space behind it.
    3. FRONT_EMPTY_RISK: Tall cargo stack but empty space in front of it.

    OUTPUT FORMAT ONLY A JSON ARRAY:
    [
      {
        "view": "FRONT",
        "risk_type": "STEP_DOWN_RISK", 
        "description": "อธิบายจุดที่พบความเสี่ยงเป็นภาษาไทยสั้นๆ",
        "box_2d": [ymin, xmin, ymax, xmax]
      }
    ]
    """

    model_candidates = ["models/gemini-flash-latest", "gemini-flash-latest"]
    last_error_msg = ""

    for model_name in model_candidates:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                model = genai.GenerativeModel(
                    model_name=model_name,
                    generation_config={"response_mime_type": "application/json"}
                )
                response = model.generate_content([prompt, combined_image])
                raw_text = response.text if response and response.text else "[]"
                clean_text = clean_json_response(raw_text)
                
                if not clean_text or clean_text == '""' or clean_text == "[]":
                    return []
                    
                risks = json.loads(clean_text)
                if isinstance(risks, dict):
                    risks = [risks]
                return risks

            except Exception as e:
                err_str = str(e)
                last_error_msg = err_str
                
                if "404" in err_str or "not found" in err_str.lower():
                    break
                    
                # 🚀 Smart Exponential Backoff: สลีป 10 วินาทีในรอบแรก และ 20 วินาทีในรอบสอง เพื่อรอ Token Reset
                if "429" in err_str or "quota" in err_str.lower() or "resourceexhausted" in err_str.lower():
                    sleep_time = 10 * (attempt + 1)
                    print(f"Hit 429 Rate Limit. Backoff sleeping {sleep_time}s (Attempt {attempt+1}/{max_retries})...")
                    time.sleep(sleep_time)
                else:
                    time.sleep(3)

    return [{"risk_type": "ERROR", "description": f"AI Error (429/Quota): {last_error_msg[:120]}"}]

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
            pages = convert_from_bytes(pdf_bytes, first_page=2, last_page=2, dpi=130)
        except Exception:
            pages = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=130)
        
        if not pages:
            return ({"error": "Cannot render PDF page data"}, 400, headers)

        img = pages[0]
        width, height = img.size
        
        front_x_offset, front_y_offset = 0, int(height * 0.12)
        front_w = int(width * 0.75)
        front_h = int(height * 0.50) - front_y_offset
        
        back_x_offset, back_y_offset = 0, int(height * 0.50)
        back_w = int(width * 0.75)
        back_h = int(height * 0.92) - back_y_offset

        front_crop = img.crop((front_x_offset, front_y_offset, front_x_offset + front_w, front_y_offset + front_h))
        back_crop = img.crop((back_x_offset, back_y_offset, back_x_offset + back_w, back_y_offset + back_h))

        combined_w = max(front_w, back_w)
        combined_h = front_h + back_h
        combined_img = PIL.Image.new('RGB', (combined_w, combined_h), color=(255, 255, 255))
        combined_img.paste(front_crop, (0, 0))
        combined_img.paste(back_crop, (0, front_h))

        all_risks = analyze_combined_image_with_ai(combined_img)

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
                        "detail": risk.get("description", "โปรดตรวจสอบโควตา Gemini API"),
                        "is_error": True
                    })
                    continue
                else:
                    continue
                    
                desc = risk.get("description", "พบความไม่สมดุลของสินค้า")
                box = risk.get("box_2d") or risk.get("boundingBox") or risk.get("box2d") or risk.get("box")
                
                y_base_offset = front_y_offset if "FRONT" in view_name else back_y_offset
                w_ref = front_w if "FRONT" in view_name else back_w
                h_ref = front_h if "FRONT" in view_name else back_h
                
                drawn_exact = False
                if box and isinstance(box, list) and len(box) == 4:
                    try:
                        ymin, xmin, ymax, xmax = map(float, box)
                        if max(ymin, xmin, ymax, xmax) <= 1.0 and max(ymin, xmin, ymax, xmax) > 0:
                            ymin, xmin, ymax, xmax = ymin*1000, xmin*1000, ymax*1000, xmax*1000
                            
                        abs_xmin = int(xmin * w_ref / 1000)
                        abs_ymin = int(y_base_offset + (ymin * h_ref / 1000))
                        abs_xmax = int(xmax * w_ref / 1000)
                        abs_ymax = int(y_base_offset + (ymax * h_ref / 1000))
                        
                        draw.rectangle([abs_xmin, abs_ymin, abs_xmax, abs_ymax], outline="red", width=6)
                        drawn_exact = True
                    except Exception:
                        pass
                        
                if not drawn_exact:
                    draw.rectangle([0, y_base_offset, w_ref, y_base_offset + h_ref], outline="orange", width=6)
                
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

        # คืนหน่วยความจำชั่วคราว
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
