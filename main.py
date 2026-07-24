import base64
import io
import json
import os
import time
import traceback
from pdf2image import convert_from_bytes
import PIL.Image
import PIL.ImageDraw
import functions_framework
import google.generativeai as genai

# ---------------------------------------------------------------------------
# Backend API สำหรับ AI Cargo Safety Checker (เวอร์ชัน Google GenAI SDK)
# ---------------------------------------------------------------------------

# ตั้งค่า API Key ให้กับ SDK
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

def analyze_image_with_ai(image: PIL.Image.Image, view_name: str):
    """
    ส่งรูปภาพไปให้ AI วิเคราะห์ผ่าน Official Google GenAI SDK
    """
    if not api_key:
        return [{"risk_type": "ERROR", "description": "ระบบหา GEMINI_API_KEY ไม่พบ โปรดตั้งค่าใน Cloud Run"}]

    prompt = f"""
    You are an expert Cargo Loading Safety Inspector. 
    Analyze this 3D isometric cargo diagram ({view_name} view). 
    Focus entirely on the colored cargo blocks. Ignore the yellow container outline.

    CRITICAL RULES for detecting risks:
    1. STEP_DOWN_RISK: Look at the top surface of all cargo blocks. If the top surface is NOT perfectly flat across all blocks, this is a STEP_DOWN_RISK.
    2. REAR_EMPTY_RISK: If there is a tall stack of cargo but the floor space behind it is completely empty.
    3. FRONT_EMPTY_RISK: If there is a tall stack of cargo but the floor space in front of it is completely empty.

    OUTPUT FORMAT:
    Return ONLY a JSON array.
    [
      {{
        "risk_type": "STEP_DOWN_RISK", 
        "description": "อธิบายจุดที่พบความเสี่ยงเป็นภาษาไทยสั้นๆ",
        "box_2d": [ymin, xmin, ymax, xmax]
      }}
    ]
    """

    try:
        # ใช้ Official Google SDK เรียกโมเดลโดยตรง
        model = genai.GenerativeModel(
            model_name="gemini-1.5-flash",
            generation_config={"response_mime_type": "application/json"}
        )
        
        # ส่ง Prompt และรูปภาพ PIL เข้า SDK ตรงๆ
        response = model.generate_content([prompt, image])
        
        raw_text = response.text if response and response.text else "[]"
        clean_text = clean_json_response(raw_text)
        
        if not clean_text or clean_text == '""' or clean_text == "[]":
            return []
            
        risks = json.loads(clean_text)
        if isinstance(risks, dict):
            risks = [risks]
        return risks

    except Exception as e:
        err_msg = str(e)[:200].replace('\n', ' ')
        print(f"Google SDK Error: {err_msg}")
        return [{"risk_type": "ERROR", "description": f"SDK Error: {err_msg}"}]

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
            pages = convert_from_bytes(pdf_bytes, first_page=2, last_page=2, dpi=200)
        except Exception:
            pages = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=200)
        
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

        # 1. วิเคราะห์ภาพ FRONT
        front_risks = analyze_image_with_ai(front_crop, "FRONT")
        
        # 🚨 2. หน่วงเวลา 4 วินาที ป้องกัน Rate Limit
        time.sleep(4)
        
        # 3. วิเคราะห์ภาพ BACK
        back_risks = analyze_image_with_ai(back_crop, "BACK")

        draw = PIL.ImageDraw.Draw(img)
        detected_hazards = []

        def process_and_draw(risks, x_off, y_off, w, h, view_name):
            if not isinstance(risks, list):
                return
                
            for risk in risks:
                risk_type = str(risk.get("risk_type", "")).upper().strip()
                
                if "STEP_DOWN" in risk_type:
                    risk_type = "STEP_DOWN_RISK"
                elif "REAR_EMPTY" in risk_type:
                    risk_type = "REAR_EMPTY_RISK"
                elif "FRONT_EMPTY" in risk_type:
                    risk_type = "FRONT_EMPTY_RISK"
                elif risk_type == "ERROR":
                    detected_hazards.append({
                        "title": f"⚠️ เกิดข้อผิดพลาดในการวิเคราะห์ ({view_name})",
                        "detail": risk.get("description", "โปรดตรวจสอบข้อมูลอีกครั้ง"),
                        "is_error": True
                    })
                    continue
                else:
                    continue
                    
                desc = risk.get("description", "ตรวจพบความไม่สมดุลของสินค้า")
                box = risk.get("box_2d") or risk.get("boundingBox") or risk.get("box2d") or risk.get("box")
                drawn_exact = False
                
                if box and isinstance(box, list) and len(box) == 4:
                    try:
                        ymin, xmin, ymax, xmax = map(float, box)
                        if max(ymin, xmin, ymax, xmax) <= 1.0 and max(ymin, xmin, ymax, xmax) > 0:
                            ymin, xmin, ymax, xmax = ymin*1000, xmin*1000, ymax*1000, xmax*1000
                            
                        abs_xmin = int(x_off + (xmin * w / 1000))
                        abs_ymin = int(y_off + (ymin * h / 1000))
                        abs_xmax = int(x_off + (xmax * w / 1000))
                        abs_ymax = int(y_off + (ymax * h / 1000))
                        
                        draw.rectangle([abs_xmin, abs_ymin, abs_xmax, abs_ymax], outline="red", width=8)
                        drawn_exact = True
                    except Exception as e:
                        print(f"Drawing Error: {e}")
                        
                if not drawn_exact:
                    draw.rectangle([x_off, y_off, x_off + w, y_off + h], outline="orange", width=8)
                    desc += "\n*(หมายเหตุ: ระบบตีกรอบภาพรวมสีส้ม เนื่องจาก AI ไม่สามารถระบุพิกัดย่อยได้ชัดเจน)*"
                
                detected_hazards.append({
                    "title": f"ตรวจพบความเสี่ยง: {risk_type}",
                    "detail": generate_action_report(risk_type, desc),
                    "is_error": False
                })

        process_and_draw(front_risks, front_x_offset, front_y_offset, front_w, front_h, "FRONT")
        process_and_draw(back_risks, back_x_offset, back_y_offset, back_w, back_h, "BACK")

        real_hazards = [h for h in detected_hazards if not h.get("is_error", False)]
        has_errors = any(h.get("is_error", False) for h in detected_hazards)

        if len(real_hazards) > 0:
            status_text = f"พบจุดเสี่ยงอันตราย (รวมทั้งหมด {len(real_hazards)} จุด)"
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
        img.save(buffered, format="PNG")
        processed_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
        processed_image_url = f"data:image/png;base64,{processed_base64}"

        response_data = {
            "status": status_text,
            "hazardCount": hazard_count,
            "actionRequired": action_text,
            "processedImageUrl": processed_image_url,
            "ai_analysis": {
                "front": front_risks,
                "back": back_risks
            }
        }

        return (response_data, 200, headers)

    except Exception as e:
        print(traceback.format_exc())
        return ({"error": str(e), "trace": traceback.format_exc()}, 500, headers)
