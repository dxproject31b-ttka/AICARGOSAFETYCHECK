import base64
import json
import functions_framework
import traceback
from pdf2image import convert_from_bytes
import google.generativeai as genai
import os
import PIL.Image
import PIL.ImageDraw
import io

# ---------------------------------------------------------------------------
# กำหนด API Key สำหรับ Gemini
# ---------------------------------------------------------------------------
genai.configure(api_key=os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY_HERE"))

# ใช้ Model มาตรฐานร่วมกับ SDK เวอร์ชันใหม่
model = genai.GenerativeModel('gemini-1.5-flash')

def generate_action_report(case_type, description):
    """
    สร้างข้อความแจ้งเตือนความปลอดภัยตาม Template เดิม
    """
    if case_type == "STEP_DOWN_RISK":
        return f"🚨 [ALERT] พบรอยเหลื่อมต่างระดับ\n{description}\n🛠️ ACTION: ติดตั้งแผงไม้กั้นขวางและรัดสาย Ratchet Strap"
    elif case_type == "REAR_EMPTY_RISK":
        return f"🚨 [ALERT] พบสินค้าสูงขนาบพื้นที่โล่งท้ายตู้\n{description}\n🛠️ ACTION: ติดตั้งโครงไม้ค้ำยันแนวดิ่ง (Rear Tomming) และรัดไขว้กากบาท"
    elif case_type == "FRONT_EMPTY_RISK":
        return f"🚨 [ALERT] พบสินค้าสูงขนาบพื้นที่โล่งหัวตู้\n{description}\n🛠️ ACTION: ติดตั้งค้ำยันกั้นขวางฝั่งหัวรถ (Front Blocking)"
    else:
        return "🟢 [STATUS] ปลอดภัย (SAFE)\nไม่มีความเสี่ยงที่ต้องดำเนินการเพิ่มเติม"

def clean_json_response(text):
    """
    ดึงเฉพาะข้อมูล Array [...] หรือ Object {...} จากข้อความที่ AI ตอบกลับ
    ตัดข้อความขยะที่ AI อาจจะแถมมาทิ้งไปแบบเด็ดขาด
    """
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
    ส่งรูปภาพไปให้ Gemini AI วิเคราะห์จุดเสี่ยง พร้อมขอพิกัดตีกรอบ (Bounding Box)
    """
    prompt = f"""
    You are an expert Cargo Loading Safety Inspector. 
    Analyze this 3D isometric cargo diagram ({view_name} view). 
    Focus entirely on the colored cargo blocks. Ignore the yellow container outline.

    CRITICAL RULES for detecting risks:
    1. STEP_DOWN_RISK: Look at the top surface of all cargo blocks. If the top surface is NOT perfectly flat across all blocks (e.g., one block stack is noticeably higher or lower than the adjacent stack), this is a STEP_DOWN_RISK.
    2. REAR_EMPTY_RISK: If there is a tall stack of cargo but the floor space behind it (towards the rear doors) is completely empty.
    3. FRONT_EMPTY_RISK: If there is a tall stack of cargo but the floor space in front of it (towards the front wall) is completely empty.

    OUTPUT FORMAT:
    - You MUST return ONLY a JSON array. Do not include any conversational text.
    - If the cargo is perfectly level and has no empty space risks, return an empty array: []
    - If you find risks, return them in this format:
    [
      {{
        "risk_type": "STEP_DOWN_RISK", 
        "description": "อธิบายจุดที่พบความเสี่ยงเป็นภาษาไทยสั้นๆ เช่น พบรอยเหลื่อมความสูงระหว่างกล่องสีฟ้าและสีฟ้าอ่อน",
        "box_2d": [ymin, xmin, ymax, xmax]
      }}
    ]
    - 'box_2d' is MANDATORY if a risk is found. It must be an array of exactly 4 numbers [ymin, xmin, ymax, xmax] normalized 0-1000 representing the bounding box of the specific problematic cargo blocks.
    """

    try:
        response = model.generate_content(
            [prompt, image],
            generation_config={"response_mime_type": "application/json"}
        )
        
        # คลีนข้อมูลก่อนแปลงเป็น JSON
        clean_text = clean_json_response(response.text)
        
        # ถ้า AI ตอบกลับมาเป็นค่าว่าง (ปลอดภัย)
        if not clean_text or clean_text == '""' or clean_text == "[]":
            return []
            
        risks = json.loads(clean_text)
        
        # ตรวจสอบว่าถ้าคืนค่ามาเป็น dict ตัวเดียว ให้แปลงเป็น list
        if isinstance(risks, dict):
            risks = [risks]
            
        return risks
    except json.JSONDecodeError as e:
        print(f"JSON Parse Error: {e} - Raw text: {response.text}")
        return [{"risk_type": "ERROR", "description": f"AI ส่งข้อมูลผิดรูปแบบ JSON (ลองอีกครั้ง)"}]
    except Exception as e:
        print(f"AI Analysis Error: {e}")
        return [{"risk_type": "ERROR", "description": str(e)}]

@functions_framework.http
def process_request(request):
    """
    HTTP Webhook Endpoint สำหรับวิเคราะห์ PDF ผ่าน Cloud Functions
    """
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*', 
            'Access-Control-Allow-Methods': 'POST', 
            'Access-Control-Allow-Headers': 'Content-Type',
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
        
        # Crop ภาพแบ่งเป็น Front และ Back
        front_x_offset, front_y_offset = 0, int(height * 0.12)
        front_w = int(width * 0.75)
        front_h = int(height * 0.50) - front_y_offset
        
        back_x_offset, back_y_offset = 0, int(height * 0.50)
        back_w = int(width * 0.75)
        back_h = int(height * 0.92) - back_y_offset

        front_crop = img.crop((front_x_offset, front_y_offset, front_x_offset + front_w, front_y_offset + front_h))
        back_crop = img.crop((back_x_offset, back_y_offset, back_x_offset + back_w, back_y_offset + back_h))

        # ส่งให้ AI วิเคราะห์
        front_risks = analyze_image_with_ai(front_crop, "FRONT")
        back_risks = analyze_image_with_ai(back_crop, "BACK")

        draw = PIL.ImageDraw.Draw(img)
        detected_hazards = []

        def process_and_draw(risks, x_off, y_off, w, h, view_name):
            if not isinstance(risks, list):
                return
                
            for risk in risks:
                # จัดการเผื่อ AI พิมพ์เล็ก/ใหญ่ ไม่ตรง
                risk_type = str(risk.get("risk_type", "")).upper().strip()
                
                # เช็ค Template ว่าเป็นความเสี่ยงรูปแบบไหน
                if "STEP_DOWN" in risk_type:
                    risk_type = "STEP_DOWN_RISK"
                elif "REAR_EMPTY" in risk_type:
                    risk_type = "REAR_EMPTY_RISK"
                elif "FRONT_EMPTY" in risk_type:
                    risk_type = "FRONT_EMPTY_RISK"
                elif risk_type == "ERROR":
                    detected_hazards.append({
                        "title": f"⚠️ เกิดข้อผิดพลาดในการวิเคราะห์ ({view_name})",
                        "detail": risk.get("description", "โปรดตรวจสอบข้อมูลอีกครั้ง")
                    })
                    continue
                else:
                    # ถ้าเจอคำที่ไม่รู้จัก ให้ข้ามไป
                    continue
                    
                desc = risk.get("description", "ตรวจพบความไม่สมดุลของสินค้า")
                
                # ค้นหาพิกัดกรอบ (เผื่อ AI ตั้งชื่อ Key ผิด)
                box = risk.get("box_2d") or risk.get("boundingBox") or risk.get("box2d") or risk.get("box")
                drawn_exact = False
                
                # วาดกรอบสีแดง (ถ้าระบุพิกัดมา)
                if box and isinstance(box, list) and len(box) == 4:
                    try:
                        # ใช้ float เผื่อ AI ส่งทศนิยมมา
                        ymin, xmin, ymax, xmax = map(float, box)
                        
                        # เผื่อกรณี AI คืนค่าสเกล 0-1 แทน 0-1000
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
                        
                # กรณีที่ AI ไม่ยอมคืนค่าพิกัดมา (หรือคืนค่ามาผิด) วาดกรอบสีส้มคลุมภาพรวมแทน
                if not drawn_exact:
                    draw.rectangle([x_off, y_off, x_off + w, y_off + h], outline="orange", width=8)
                    desc += "\n*(หมายเหตุ: ระบบตีกรอบภาพรวมสีส้ม เนื่องจาก AI ไม่สามารถระบุพิกัดย่อยได้ชัดเจน)*"
                
                detected_hazards.append({
                    "title": f"ตรวจพบความเสี่ยง: {risk_type}",
                    "detail": generate_action_report(risk_type, desc)
                })

        process_and_draw(front_risks, front_x_offset, front_y_offset, front_w, front_h, "FRONT")
        process_and_draw(back_risks, back_x_offset, back_y_offset, back_w, back_h, "BACK")

        # สรุปผลลัพธ์เพื่อส่งกลับไปยัง Frontend
        if len(detected_hazards) > 0:
            status_text = f"พบจุดเสี่ยงอันตราย (รวมทั้งหมด {len(detected_hazards)} จุด)"
            action_text = "\n\n--------------------------------------------------\n\n".join(
                [f"[{h['title']}]\n{h['detail']}" for h in detected_hazards]
            )
            hazard_count = len(detected_hazards)
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
