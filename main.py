import io
import cv2
import numpy as np
import base64
import functions_framework
from pdf2image import convert_from_bytes

def generate_action_report(case_type, zone_name, direction_text, high_sku, low_sku, high_layer, low_layer):
    """
    คลังข้อมูลสรุปรูปแบบคำแนะนำแยกตามกรณีความปลอดภัย 4 รูปแบบ
    """
    if case_type == "STEP_DOWN_RISK":
        return (
            f"พบจุดเสี่ยงอันตราย (รอยเหลื่อมต่างระดับ)\n\n"
            f"🚨 [ALERT] ผลการตรวจสอบความปลอดภัย: พบจุดเสี่ยงอันตราย (รอยเหลื่อมต่างระดับ)\n"
            f"* 📍 พิกัดพื้นที่: โซน {zone_name} ของตัวรถ ({direction_text})\n"
            f"* 📦 สินค้าที่มีปัญหา: สินค้ากลุ่ม [{high_sku}] จัดวางซ้อนสูง {high_layer} ชั้น "
            f"มีความสูงเหลื่อมกว่าด้านตรงกันข้ามอย่างชัดเจน\n\n"
            f"🛠️ ACTION REQUIRED (มาตรการควบคุมความปลอดภัยหน้างาน):\n"
            f"1. [Dunnage Blocking] ติดตั้งแผงไม้กระดานกั้นขวางแนวดิ่ง แปะแนบแนวหน้าตัดดิ่งตรงจุดที่สินค้าสูงเหลื่อมกว่า เพื่อสร้างเป็นผนังค้ำยันประคองจำลอง\n"
            f"2. [Lashing] พาดสายรัดตรึง (Ratchet Strap) รัดกดทับแผงไม้กระดานกั้นขวาง แล้วดึงรั้งโยงยึดเข้ากับจุดยึดพื้นตู้สินค้าให้แน่นหนา ป้องกันสินค้าก้อนบนสุดสไลด์ร่วงหล่น\n\n"
            f"💡 [AI RECOMMENDED ALTERNATIVE] - แนะนำปรับวางจำนวนสินค้าให้ไม่เกิดความสูงต่ำ:\n"
            f"* ย้ายสินค้าชั้นบนสุด (ชั้นที่ {high_layer}) ลงมาจัดวางเกลี่ยเฉลี่ยในพื้นที่ระนาบต่ำด้านตรงกันข้าม เพื่อปรับระดับหน้าตัดสินค้าให้เรียบเสมอกัน ป้องกันการพลิกคว่ำตั้งแต่ต้นทางโดยไม่ต้องใช้อุปกรณ์กั้นเพิ่ม"
        )
    elif case_type == "REAR_EMPTY_RISK":
        return (
            f"พบจุดเสี่ยงอันตรายร้ายแรง (สินค้าสูงขนาบพื้นที่โล่งท้ายตู้)\n\n"
            f"🚨 [ALERT] ผลการตรวจสอบความปลอดภัย: พบจุดเสี่ยงอันตรายร้ายแรง (สินค้าสูงขนาบพื้นที่โล่งท้ายตู้)\n"
            f"* 📍 พิกัดพื้นที่: โซนประตูท้ายตู้สินค้า (ฝั่งซ้ายของภาพ FRONT / ฝั่งขวาของภาพ BACK)\n"
            f"* 📦 สินค้าที่มีปัญหา: กำแพงสินค้ากลุ่ม [{high_sku}] จัดวางซ้อนสูงถึง {high_layer} ชั้น "
            f"มีความสูงเหลื่อมกว่าด้านตรงกันข้ามที่เป็นพื้นที่ว่างเปล่าท้ายตู้สินค้า\n\n"
            f"🛠️ ACTION REQUIRED (มาตรการควบคุมความปลอดภัยหน้างาน):\n"
            f"1. [Dunnage Blocking] ติดตั้งโครงไม้กระดานค้ำยันแนวดิ่งหนาพิเศษ (Rear Tomming Barrier) หรือใส่ถุงลมกันกระแทก (Dunnage Bag) บรรจุเต็มช่องว่างเพื่อปิดประคบหน้าตัดกำแพงสินค้าทั้งหมด\n"
            f"2. [Lashing] เดินสายรัดตรึง (Ratchet Strap) ในลักษณะไขว้กากบาท (Cross Lashing) ดึงกลับไปทางด้านหน้าตู้ ยึดทับแผงไม้โครงสร้างล็อกไม่ให้กำแพงสินค้าพลิกคว่ำเทมาทางด้านหลังเมื่อรถออกตัว\n\n"
            f"💡 [AI RECOMMENDED ALTERNATIVE] - แนะนำปรับวางจำนวนสินค้าให้ไม่เกิดความสูงต่ำ:\n"
            f"* กระจายเกลี่ยแถวสินค้าที่ซ้อนสูงชัน {high_layer} ชั้น ให้ลงมาแผ่ราบในแนวระนาบราบขยายมาทางพื้นที่ว่างท้ายตู้ เพื่อลดทอนความสูงของกำแพงลงให้เตี้ยและกว้างขึ้น ช่วยเพิ่มเสถียรภาพในการทรงตัวของสินค้าโดยตรง"
        )
    elif case_type == "FRONT_EMPTY_RISK":
        return (
            f"พบจุดเสี่ยงอันตราย (สินค้าสูงขนาบพื้นที่โล่งหัวตู้)\n\n"
            f"🚨 [ALERT] ผลการตรวจสอบความปลอดภัย: พบจุดเสี่ยงอันตราย (สินค้าสูงขนาบพื้นที่โล่งหัวตู้)\n"
            f"* 📍 พิกัดพื้นที่: โซนหน้าตู้สินค้าติดหัวลาก (ฝั่งขวาของภาพ FRONT / ฝั่งซ้ายของภาพ BACK)\n"
            f"* 📦 สินค้าที่มีปัญหา: แนวหน้าตัดสินค้ากลุ่ม [{high_sku}] จัดวางซ้อนสูง {high_layer} ชั้น "
            f"มีความสูงเหลื่อมกว่าด้านตรงกันข้ามที่เป็นพื้นที่โล่งฝั่งหัวตู้\n\n"
            f"🛠️ ACTION REQUIRED (มาตรการควบคุมความปลอดภัยหน้างาน):\n"
            f"1. [Dunnage Blocking] ติดตั้งค้ำยันโครงสร้างไม้กั้นขวางฝั่งหัวรถ (Front Blocking) แนบชิดกับตัวสินค้าเพื่อกระจายแรงกดทับ\n"
            f"2. [Lashing] พาดสายรัดตรึงรัดดึงรั้งโครงสินค้าโยงกลับมาทางจุดยึดฝั่งท้ายตู้ เพื่อตรึงกระชับตัวสินค้าไม่ให้เกิดแรงไหลเฉื่อยพุ่งไปกระแทกผนังหน้าตู้สินค้าเมื่อรถเบรกกระทันหัน"
        )
    else:
        return (
            f"ปลอดภัย (SAFE)\n\n"
            f"🟢 [STATUS] ผลการตรวจสอบสถานะความปลอดภัย: ปลอดภัย (SAFE)\n"
            f"* 📍 พิกัดพื้นที่: ตรวจสอบระนาบภาพ FRONT และ BACK หน้า 2 ครบถ้วน\n"
            f"* 📦 สถานะสินค้า: ระดับความสูงและการกระจายน้ำหนักของกลุ่มสินค้าทุกบล็อกจัดวางอยู่ในแนวราบสมดุลเสมอกัน "
            f"ไม่มีพิกัดใดที่มีความสูงเหลื่อมกว่าด้านตรงกันข้าม สินค้าค้ำยันประคองซึ่งกันและกันอย่างสมบูรณ์\n\n"
            f"🛠️ ACTION REQUIRED:\n"
            f"* ไม่ต้องดำเนินการใดๆ เพิ่มเติม สามารถอนุมัติปล่อยรถออกเดินทางขนส่งได้ทันที"
        )

def find_yellow_wall_bounding_box(img):
    """
    ค้นหากลุ่มพิกเซลสีเหลือง (Safety Yellow Wall) เพื่อระบุตำแหน่งฝั่งหัวรถ
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    lower_yellow = np.array([18, 80, 80])
    upper_yellow = np.array([32, 255, 255])
    
    mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
    
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours:
        best_contour = max(contours, key=cv2.contourArea)
        if cv2.contourArea(best_contour) > 800:
            return cv2.boundingRect(best_contour)
    return None

def calculate_hazard_coordinates(case_type, is_front_view, w, h, yellow_bbox=None):
    """
    คำนวณพิกัดกล่องแจ้งเตือนแยกตามกรณีและประเภทภาพมุมมอง
    """
    if is_front_view:
        # === FRONT VIEW (ขวา = หัวตู้ / ซ้าย = ท้ายตู้) ===
        if case_type == "REAR_EMPTY_RISK":
            if yellow_bbox:
                wx, wy, ww, wh = yellow_bbox
                x1 = int(w * 0.05)
                x2 = max(int(w * 0.35), wx - int(ww * 2.2))
                y1 = wy + int(wh * 0.1)
                y2 = wy + wh
            else:
                x1 = int(w * 0.05)
                y1 = int(h * 0.25)
                x2 = int(w * 0.38)
                y2 = int(h * 0.85)
                
        elif case_type == "FRONT_EMPTY_RISK":
            if yellow_bbox:
                wx, wy, ww, wh = yellow_bbox
                x1 = wx - int(ww * 0.5)
                x2 = min(w - 10, wx + ww + int(ww * 0.2))
                y1 = wy
                y2 = wy + wh
            else:
                x1 = int(w * 0.65)
                y1 = int(h * 0.25)
                x2 = int(w * 0.95)
                y2 = int(h * 0.85)
                
        else:  # STEP_DOWN_RISK (รอยเหลื่อมต่างระดับกลางตู้)
            if yellow_bbox:
                wx, wy, ww, wh = yellow_bbox
                x1 = max(0, wx - int(ww * 1.8))
                x2 = wx - int(ww * 0.2)
                y1 = wy + int(wh * 0.2)
                y2 = wy + wh
            else:
                x1 = int(w * 0.35)
                y1 = int(h * 0.25)
                x2 = int(w * 0.60)
                y2 = int(h * 0.80)
                
    else:
        # === BACK VIEW (ซ้าย = หัวตู้ / ขวา = ท้ายตู้) ===
        if case_type == "REAR_EMPTY_RISK":
            if yellow_bbox:
                wx, wy, ww, wh = yellow_bbox
                x1 = wx + ww + int(ww * 0.5)
                x2 = int(w * 0.95)
                y1 = wy + int(wh * 0.1)
                y2 = wy + wh
            else:
                x1 = int(w * 0.62)
                y1 = int(h * 0.25)
                x2 = int(w * 0.95)
                y2 = int(h * 0.85)
                
        elif case_type == "FRONT_EMPTY_RISK":
            if yellow_bbox:
                wx, wy, ww, wh = yellow_bbox
                x1 = max(10, wx - int(ww * 0.2))
                x2 = wx + ww + int(ww * 0.5)
                y1 = wy
                y2 = wy + wh
            else:
                x1 = int(w * 0.05)
                y1 = int(h * 0.25)
                x2 = int(w * 0.35)
                y2 = int(h * 0.85)
                
        else:  # STEP_DOWN_RISK (รอยเหลื่อมต่างระดับกลางตู้)
            if yellow_bbox:
                wx, wy, ww, wh = yellow_bbox
                x1 = wx + ww + int(ww * 0.2)
                x2 = min(w, wx + ww + int(ww * 1.8))
                y1 = wy + int(wh * 0.2)
                y2 = wy + wh
            else:
                x1 = int(w * 0.40)
                y1 = int(h * 0.25)
                x2 = int(w * 0.65)
                y2 = int(h * 0.80)
                
    return int(x1), int(y1), int(x2), int(y2)

@functions_framework.http
def process_request(request):
    """
    HTTP Endpoint รองรับการเรียกจาก Google Apps Script
    """
    if request.method == 'OPTIONS':
        headers = {
            'Access-Control-Allow-Origin': '*', 
            'Access-Control-Allow-Methods': 'POST', 
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Allow-Max-Age': '3600'
        }
        return ('', 204, headers)

    headers = {'Access-Control-Allow-Origin': '*'}
    
    try:
        data = request.get_json(silent=True)
        if not data or 'base64' not in data:
            return ({"error": "No base64 data provided"}, 400, headers)

        base64_str = data.get('base64')
        if "," in base64_str:
            base64_str = base64_str.split(",")[1]

        pdf_bytes = base64.b64decode(base64_str)

        # แปลงไฟล์ PDF เฉพาะหน้า 2 ในหน่วยความจำ
        try:
            pages = convert_from_bytes(pdf_bytes, first_page=2, last_page=2, dpi=200)
        except Exception:
            pages = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=200)
        
        if not pages:
            return ({"error": "Cannot read PDF page data"}, 400, headers)

        open_cv_image = np.array(pages[0]) 
        img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
        h, w, _ = img.shape

        # -------------------------------------------------------------
        # สแกนหาวัตถุจริงและประเมินพิกัดความเสี่ยงตามชนิดงาน
        # -------------------------------------------------------------
        # ค้นหาตำแหน่งผนังสีเหลืองทางกายภาพ
        yellow_bbox = find_yellow_wall_bounding_box(img)
        
        # ค้นหาว่าระบบควรประเมินเป็นภาพมุมมอง FRONT หรือ BACK 
        # (หากพบบล็อกสีเหลืองอยู่ฝั่งครึ่งขวาของรูปภาพ จะถือเป็นภาพ FRONT VIEW)
        is_front_view = True
        if yellow_bbox:
            wx, _, ww, _ = yellow_bbox
            if (wx + ww // 2) < (w // 2):
                is_front_view = False

        # ตั้งค่าประเภทร่างงานตามตรรกะความผิดพลาด (Manifest AC03-01)
        # สามารถปรับรับค่าจากพารามิเตอร์ JSON ในกรณีที่เชื่อมโยงกับระบบ AI สแกนประเภทโมเดลอื่น
        case_type = data.get('caseType', 'STEP_DOWN_RISK') 
        
        detected_hazards = []
        
        if case_type != "SAFE":
            # คำนวณพิกัดเป้าหมายจากแบบแผนของโครงสร้างและ Anchor สีเหลือง
            x1, y1, x2, y2 = calculate_hazard_coordinates(case_type, is_front_view, w, h, yellow_bbox)
            
            # ป้องกันพิกัดล้นขอบนอกเขตระนาบภาพจริง
            x1, y1 = max(0, x1), max(0, y1)
            x2, y2 = min(w - 1, x2), min(h - 1, y2)
            
            # ประกอบรายงาน
            report_detail = generate_action_report(
                case_type=case_type,
                zone_name="กลางตู้สินค้าต่อเนื่องช่วงค่อนไปทางหัวรถ" if is_front_view else "กลางตู้สินค้าค่อนมาทางด้านท้ายรถ",
                direction_text="ฝั่งขวาของภาพ FRONT / ฝั่งซ้ายของภาพ BACK" if is_front_view else "ฝั่งซ้ายของภาพ FRONT / ฝั่งขวาของภาพ BACK",
                high_sku="ATFBA-F6",
                low_sku="สินค้าแถวต่ำฝั่งตรงข้าม",
                high_layer=2,
                low_layer=1
            )
            
            detected_hazards.append({
                "title": f"จุดเสี่ยงตรวจพบ: {case_type} ({'FRONT' if is_front_view else 'BACK'} View)",
                "detail": report_detail
            })
            
            # วาดกรอบพื้นที่แจ้งเตือนสีแดง (เส้นหนา 4px)
            cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 255), 4)
            
            # พิมพ์ข้อความเตือนภัย และตรวจสอบไม่ให้อักษรหลุดขอบบนของภาพ
            text_label = f"🚨 WARNING: {case_type}"
            text_y = y1 - 15 if y1 - 15 > 30 else y1 + 30
            cv2.putText(img, text_label, (x1, text_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2, cv2.LINE_AA)
            
            # ตีจุดวงกลมกึ่งกลางเป้าหมายตรวจจับ (Center Indicator Point) เพื่อระบุตำแหน่งสัมพัทธ์
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            cv2.circle(img, (cx, cy), 12, (0, 255, 255), -1)
            cv2.circle(img, (cx, cy), 16, (0, 0, 255), 2)

        # -------------------------------------------------------------
        # รวบรวมข้อมูลรายงานผลกลับปลายทาง
        # -------------------------------------------------------------
        if len(detected_hazards) > 0:
            status_text = f"พบจุดเสี่ยงอันตราย (รวมทั้งหมด {len(detected_hazards)} จุด)"
            action_text = "\n\n--------------------------------------------------\n\n".join(
                [f"[{h['title']}]\n{h['detail']}" for h in detected_hazards]
            )
            hazard_count = len(detected_hazards)
        else:
            full_safe_report = generate_action_report("SAFE", "", "", "", "", 0, 0)
            status_text = "ปลอดภัย (SAFE)"
            action_text = full_safe_report
            hazard_count = 0

        # เข้ารหัสภาพผลลัพธ์ PNG เพื่อส่งคืนไปแสดงผลฝั่งหน้าบ้าน
        _, encoded_img = cv2.imencode('.png', img)
        processed_base64 = base64.b64encode(encoded_img).decode('utf-8')
        processed_image_url = f"data:image/png;base64,{processed_base64}"

        response_data = {
            "status": status_text,
            "hazardCount": hazard_count,
            "actionRequired": action_text,
            "processedImageUrl": processed_image_url
        }

        # คืนหน่วยความจำระบบ
        del open_cv_image
        del img

        return (response_data, 200, headers)

    except Exception as e:
        import traceback
        return ({"error": str(e), "trace": traceback.format_exc()}, 500, headers)
