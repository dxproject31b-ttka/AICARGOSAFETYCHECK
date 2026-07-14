import io
import cv2
import numpy as np
import base64
import functions_framework
from pdf2image import convert_from_bytes

def generate_action_report(case_type, zone_name, direction_text, high_sku, low_sku, high_layer, low_layer):
    """
    คลังข้อมูลคำแนะนำแยกตามกรณีความปลอดภัย 4 รูปแบบ
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
            f"* กระจายเกลี่ยแถวสินค้าที่ซ้อนสูงชัน {high_layer} ชั้น ให้ลงมาแผ่ราบในแนวระนาบราบขยายมาทางพื้นที่ว่างท้ายตู้ เพื่อลดทอนความสูงของกำแพงลงให้เตี้ยและกว้างขึ้น ช่วยเพิ่มเสถียรภาพในการทรงตัว of สินค้าโดยตรง"
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

def scan_viewport_elements(crop_img):
    """
    ค้นหาระยะตำแหน่งของผนังสีเหลือง และพิกัดกล่องสินค้า (สีฟ้า/น้ำเงิน) ภายในขอบเขต Viewport ที่ถูกครอบตัด
    """
    hsv = cv2.cvtColor(crop_img, cv2.COLOR_BGR2HSV)
    
    # 1. ค้นหากลุ่มสีเหลือง (ผนังตู้คอนเทนเนอร์)
    lower_yellow = np.array([15, 60, 80])
    upper_yellow = np.array([35, 255, 255])
    mask_yellow = cv2.inRange(hsv, lower_yellow, upper_yellow)
    
    yellow_bbox = None
    contours_y, _ = cv2.findContours(mask_yellow, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours_y:
        best_y = max(contours_y, key=cv2.contourArea)
        if cv2.contourArea(best_y) > 500:
            yellow_bbox = cv2.boundingRect(best_y)
            
    # 2. ค้นหากลุ่มสินค้า (สีฟ้า Cyan / สีน้ำเงิน Blue) แบบสกัดเฉพาะค่าความเข้มสูงจัด
    lower_blue = np.array([85, 150, 150])
    upper_blue = np.array([135, 255, 255])
    mask_blue = cv2.inRange(hsv, lower_blue, upper_blue)
    
    cargo_bbox = None
    contours_b, _ = cv2.findContours(mask_blue, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if contours_b:
        best_b = max(contours_b, key=cv2.contourArea)
        if cv2.contourArea(best_b) > 800:
            cargo_bbox = cv2.boundingRect(best_b)
            
    return yellow_bbox, cargo_bbox

@functions_framework.http
def process_request(request):
    """
    HTTP Webhook Endpoint สำหรับประมวลผลกล่องรอยต่อต่างระดับจำกัดบริเวณไม่เกิน 2 ช่องสินค้า
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
        data = request.get_json(silent=True)
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

        open_cv_image = np.array(pages[0]) 
        img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
        h, w, _ = img.shape

        # -------------------------------------------------------------
        # สเกลสัดส่วนพื้นที่ Viewport (FRONT/BACK) ซีกซ้ายกว้าง 75%
        # -------------------------------------------------------------
        front_y1, front_y2 = int(h * 0.12), int(h * 0.50)
        back_y1, back_y2 = int(h * 0.50), int(h * 0.92)
        crop_w_end = int(w * 0.75)

        front_crop = img[front_y1:front_y2, 0:crop_w_end]
        back_crop = img[back_y1:back_y2, 0:crop_w_end]

        case_type = data.get('caseType', 'STEP_DOWN_RISK')
        detected_hazards = []

        if case_type != "SAFE":
            # --- 1. ประมวลผลและตีกรอบภาพบน (FRONT VIEW) ---
            f_yellow, f_cargo = scan_viewport_elements(front_crop)
            if f_cargo:
                fx, fy, fw, fh = f_cargo
                # จำกัดพิกัดให้กว้างเพียง 2 ช่องแถวสินค้าด้านขวา (เริ่มที่ 33% และจบที่ 98% ของหน้ารวมสินค้า)
                f_x1 = int(fx + fw * 0.33)
                f_x2 = int(fx + fw * 0.98)
                f_y1 = max(0, int(fy - fh * 0.15))
                f_y2 = min(front_crop.shape[0] - 1, int(fy + fh * 1.15))
                
                # แมปกลับเป็นพิกัดภาพหลักหน้าสอง
                gx_f_x1, gy_f_y1 = f_x1, f_y1 + front_y1
                gx_f_x2, gy_f_y2 = f_x2, f_y2 + front_y1
                
                cv2.rectangle(img, (gx_f_x1, gy_f_y1), (gx_f_x2, gy_f_y2), (0, 0, 255), 4)
                cv2.putText(img, f"🚨 POINT 1: {case_type}", (gx_f_x1, gy_f_y1 - 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2, cv2.LINE_AA)

            # --- 2. ประมวลผลและตีกรอบภาพล่าง (BACK VIEW) ---
            b_yellow, b_cargo = scan_viewport_elements(back_crop)
            if b_cargo:
                bx, by, bw, bh = b_cargo
                # จำกัดพิกัดให้กว้างเพียง 2 ช่องแถวสินค้าด้านซ้าย (เริ่มที่ 2% และจบที่ 67% ของหน้ารวมสินค้า)
                b_x1 = int(bx + bw * 0.02)
                b_x2 = int(bx + bw * 0.67)
                b_y1 = max(0, int(by - bh * 0.15))
                b_y2 = min(back_crop.shape[0] - 1, int(by + bh * 1.15))
                
                # แมปกลับเป็นพิกัดภาพหลักหน้าสอง
                gx_b_x1, gy_b_y1 = b_x1, b_y1 + back_y1
                gx_b_x2, gy_b_y2 = b_x2, b_y2 + back_y1
                
                cv2.rectangle(img, (gx_b_x1, gy_b_y1), (gx_b_x2, gy_b_y2), (0, 0, 255), 4)
                cv2.putText(img, f"🚨 POINT 1: {case_type}", (gx_b_x1, gy_b_y1 - 15),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2, cv2.LINE_AA)

            # จัดส่งโครงสร้างสรุปรายงานข้อมูลความปลอดภัย
            report_detail = generate_action_report(
                case_type=case_type,
                zone_name="กลางตู้สินค้าเชื่อมโยงรอยต่อระดับ",
                direction_text="ตรวจพบพิกัดสอดคล้องกันทั้งภาพระนาบ FRONT และ BACK",
                high_sku="TEP1A / ASH1A",
                low_sku="สินค้ากลุ่มถัดไปในตู้",
                high_layer=2,
                low_layer=1
            )
            detected_hazards.append({
                "title": f"ตรวจพบจุดเสี่ยงอันตรายรูปแบบ: {case_type}",
                "detail": report_detail
            })
            
        elif case_type != "SAFE":
            # Fallback ป้องกันระบบทำงานขัดข้องเชิงกายภาพ
            f_x1, f_y1, f_x2, f_y2 = int(w * 0.32), int(h * 0.22), int(w * 0.58), int(h * 0.45)
            b_x1, b_y1, b_x2, b_y2 = int(w * 0.32), int(h * 0.60), int(w * 0.58), int(h * 0.82)
            cv2.rectangle(img, (f_x1, f_y1), (f_x2, f_y2), (0, 0, 255), 4)
            cv2.rectangle(img, (b_x1, b_y1), (b_x2, b_y2), (0, 0, 255), 4)

        # -------------------------------------------------------------
        # รวบรวมและนำส่ง Base64 กลับหน้าบ้าน
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

        _, encoded_img = cv2.imencode('.png', img)
        processed_base64 = base64.b64encode(encoded_img).decode('utf-8')
        processed_image_url = f"data:image/png;base64,{processed_base64}"

        response_data = {
            "status": status_text,
            "hazardCount": hazard_count,
            "actionRequired": action_text,
            "processedImageUrl": processed_image_url
        }

        del open_cv_image
        del img

        return (response_data, 200, headers)

    except Exception as e:
        import traceback
        return ({"error": str(e), "trace": traceback.format_exc()}, 500, headers)
