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
# กำหนด API Key สำหรับ Gemini (แนะนำให้ตั้งเป็น Environment Variable ใน Cloud Functions)
# ---------------------------------------------------------------------------
# os.environ["GEMINI_API_KEY"] = "YOUR_GOOGLE_GEMINI_API_KEY"
genai.configure(api_key=os.environ.get("GEMINI_API_KEY", "YOUR_API_KEY_HERE"))

# ใช้ Model ตัวล่าสุดที่รองรับ Vision
model = genai.GenerativeModel('gemini-1.5-flash')

def generate_action_report(case_type, description):
    """
    สร้างข้อความแจ้งเตือนความปลอดภัย
    """
    if case_type == "STEP_DOWN_RISK":
        return f"🚨 [ALERT] พบรอยเหลื่อมต่างระดับ\n{description}\n🛠️ ACTION: ติดตั้งแผงไม้กั้นขวางและรัดสาย Ratchet Strap"
    elif case_type == "REAR_EMPTY_RISK":
        return f"🚨 [ALERT] พบสินค้าสูงขนาบพื้นที่โล่งท้ายตู้\n{description}\n🛠️ ACTION: ติดตั้งโครงไม้ค้ำยันแนวดิ่ง (Rear Tomming) และรัดไขว้กากบาท"
    elif case_type == "FRONT_EMPTY_RISK":
        return f"🚨 [ALERT] พบสินค้าสูงขนาบพื้นที่โล่งหัวตู้\n{description}\n🛠️ ACTION: ติดตั้งค้ำยันกั้นขวางฝั่งหัวรถ (Front Blocking)"
    else:
        return "🟢 [STATUS] ปลอดภัย (SAFE)\nไม่มีความเสี่ยงที่ต้องดำเนินการเพิ่มเติม"

def analyze_image_with_ai(image: PIL.Image.Image, view_name: str):
    """
    ส่งรูปภาพไปให้ Gemini AI วิเคราะห์จุดเสี่ยง พร้อมขอพิกัดตีกรอบ (Bounding Box)
    """
    prompt = f"""
    You are an expert Cargo Loading Safety Inspector. 
    Analyze this 3D isometric cargo loading diagram ({view_name} view).
    
    Look for HEIGHT DISCREPANCIES (step-downs) between adjacent cargo stacks.
    The cargo boxes have different colors (red, blue, green, etc.). Ignore the yellow container walls and dimension lines.

    Identify ALL safety risks present based on these rules:
    - STEP_DOWN_RISK: A stack of boxes is noticeably higher or lower than the stack immediately next to it.
    - FRONT_EMPTY_RISK: High stack of boxes with empty space at the very front of the container (left side of BACK view, right side of FRONT view).
    - REAR_EMPTY_RISK: High stack of boxes with empty space at the very back doors (right side of FRONT view, left side of BACK view).
    - SAFE: All boxes form a perfectly flat, level top surface with no gaps or height differences.

    Return the result STRICTLY as a JSON array of objects. Example:
    [
      {{
        "risk_type": "STEP_DOWN_RISK",
        "description": "The red box stack is lower than the blue box stack next to it.",
        "box_2d": [ymin, xmin, ymax, xmax]
      }}
    ]
    * IMPORTANT: 'box_2d' must be an array of exactly 4 integers representing the bounding box [ymin, xmin, ymax, xmax].
    * The values must be normalized to a scale of 0 to 1000 relative to this specific image's dimensions.
    * If the status is SAFE, you can omit 'box_2d'.
    """

    try:
        response = model.generate_content(
            [prompt, image],
            generation_config={"response_mime_type": "application/json"}
        )
        risks = json.loads(response.text)
        return risks
    except Exception as e:
        print(f"AI Analysis Error: {e}")
        return [{"risk_type": "ERROR", "description": "Failed to analyze image with AI."}]

@functions_framework.http
def process_request(request):
    """
    HTTP Webhook Endpoint สำหรับวิเคราะห์ PDF
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
        
        # กำหนดสัดส่วนภาพสำหรับครอป
        front_x_offset, front_y_offset = 0, int(height * 0.12)
        front_w = int(width * 0.75)
        front_h = int(height * 0.50) - front_y_offset
        
        back_x_offset, back_y_offset = 0, int(height * 0.50)
        back_w = int(width * 0.75)
        back_h = int(height * 0.92) - back_y_offset

        front_crop = img.crop((front_x_offset, front_y_offset, front_x_offset + front_w, front_y_offset + front_h))
        back_crop = img.crop((back_x_offset, back_y_offset, back_x_offset + back_w, back_y_offset + back_h))

        # วิเคราะห์ผ่าน AI
        front_risks = analyze_image_with_ai(front_crop, "FRONT")
        back_risks = analyze_image_with_ai(back_crop, "BACK")

        # เตรียมวาดภาพ (Draw Bounding Box)
        draw = PIL.ImageDraw.Draw(img)
        detected_hazards = []

        def process_and_draw(risks, x_off, y_off, w, h):
            for risk in risks:
                risk_type = risk.get("risk_type", "SAFE")
                if risk_type not in ["SAFE", "ERROR"]:
                    desc = risk.get("description", "ตรวจพบความไม่สมดุลของสินค้า")
                    detected_hazards.append({
                        "title": f"ตรวจพบความเสี่ยง: {risk_type}",
                        "detail": generate_action_report(risk_type, desc)
                    })
                    
                    # วาดกรอบสีแดงตามพิกัดที่ AI คืนค่ามา
                    if "box_2d" in risk and len(risk["box_2d"]) == 4:
                        try:
                            ymin, xmin, ymax, xmax = risk["box_2d"]
                            # แปลงพิกัดสเกล (0-1000) กลับมาเป็นพิกัดจริงบนรูปภาพหลัก
                            abs_xmin = x_off + (xmin * w / 1000)
                            abs_ymin = y_off + (ymin * h / 1000)
                            abs_xmax = x_off + (xmax * w / 1000)
                            abs_ymax = y_off + (ymax * h / 1000)
                            
                            # วาดกรอบสี่เหลี่ยมสีแดง เส้นหนา 5 พิกเซล
                            draw.rectangle([abs_xmin, abs_ymin, abs_xmax, abs_ymax], outline="red", width=5)
                        except Exception as e:
                            print(f"Drawing Error: {e}")

        process_and_draw(front_risks, front_x_offset, front_y_offset, front_w, front_h)
        process_and_draw(back_risks, back_x_offset, back_y_offset, back_w, back_h)

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

        # ส่งภาพต้นฉบับที่มีกรอบสีแดงกลับไป
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
        return ({"error": str(e), "trace": traceback.format_exc()}, 500, headers)
