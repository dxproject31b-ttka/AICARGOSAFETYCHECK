import io
import cv2
import numpy as np
import base64
import functions_framework
from pdf2image import convert_from_bytes
import traceback

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
            f"1. [Blocking] ติดตั้งแผงไม้กระดานกั้นขวางแนวดิ่ง แปะแนบแนวหน้าตัดดิ่งตรงจุดที่สินค้าสูงเหลื่อมกว่า เพื่อสร้างเป็นผนังค้ำยันประคอง\n"
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
            f"1. [Blocking] ติดตั้งโครงไม้กระดานค้ำยันแนวดิ่ง (Rear Tomming Barrier) เพื่อปิดประกบสินค้าทั้งหมด\n"
            f"2. [Lashing] เดินสายรัดตรึง (Ratchet Strap) ในลักษณะไขว้กากบาท (Cross Lashing) ดึงกลับไปทางด้านหน้าตู้ ยึดทับแผงไม้โครงสร้างล็อกไม่ให้สินค้าพลิกคว่ำเทมาทางด้านหลังเมื่อรถออกตัว\n\n"
            f"💡 [AI RECOMMENDED ALTERNATIVE] - แนะนำปรับวางจำนวนสินค้าให้ไม่เกิดความสูงต่ำ:\n"
            f"* กระจายเกลี่ยแถวสินค้าที่ซ้อนสูง {high_layer} ชั้น ให้ลงมาแผ่ราบในแนวระนาบขยายมาทางพื้นที่ว่างท้ายตู้ เพื่อลดทอนความสูงของสินค้าลงให้เตี้ยและกว้างขึ้น ช่วยเพิ่มเสถียรภาพในการทรงตัวของสินค้าโดยตรง"
        )
    elif case_type == "FRONT_EMPTY_RISK":
        return (
            f"พบจุดเสี่ยงอันตราย (สินค้าสูงขนาบพื้นที่โล่งหัวตู้)\n\n"
            f"🚨 [ALERT] ผลการตรวจสอบความปลอดภัย: พบจุดเสี่ยงอันตราย (สินค้าสูงขนาบพื้นที่โล่งหัวตู้)\n"
            f"* 📍 พิกัดพื้นที่: โซนหน้าตู้สินค้าติดหัวรถ (ฝั่งขวาของภาพ FRONT / ฝั่งซ้ายของภาพ BACK)\n"
            f"* 📦 สินค้าที่มีปัญหา: แนวหน้าตัดสินค้ากลุ่ม [{high_sku}] จัดวางซ้อนสูง {high_layer} ชั้น "
            f"มีความสูงเหลื่อมกว่าด้านตรงกันข้ามที่เป็นพื้นที่โล่งฝั่งหัวตู้\n\n"
            f"🛠️ ACTION REQUIRED (มาตรการควบคุมความปลอดภัยหน้างาน):\n"
            f"1. [Dunnage Blocking] ติดตั้งค้ำยันโครงสร้างไม้กั้นขวางฝั่งหัวรถ (Front Blocking) แนบชิดกับตัวสินค้าเพื่อกระจายแรงกดทับ\n"
            f"2. [Lashing] พาดสายรัดตรึงรัดดึงรั้งสินค้าโยงกลับมาทางจุดยึดฝั่งท้ายตู้ เพื่อตรึงกระชับตัวสินค้าไม่ให้เกิดแรงไหลเฉื่อยพุ่งไปกระแทกผนังหน้าตู้สินค้าเมื่อรถเบรกกระทันหัน"
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
    ค้นหาระยะพิกัดโมเดลสินค้าและแนวตู้หลัก ภายในขอบเขต Viewport ที่ถูกครอบตัด
    """
    gray = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
    binary = (gray < 250).astype(np.uint8) * 255
    
    cargo_bbox = None
    best_area = 0
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    for c in contours:
        x, y, w, h = cv2.boundingRect(c)
        if w > 150 and h > 150 and w < crop_img.shape[1] - 10:
            area = cv2.contourArea(c)
            if area > best_area:
                best_area = area
                cargo_bbox = (x, y, w, h)
                
    return cargo_bbox

def analyze_cargo_height_profile(crop_img, cargo_bbox):
    """
    วิเคราะห์ระดับความสูงและเปรียบเทียบรอยต่างระดับของหน้าตัดสินค้าด้านซ้ายและขวา
    """
    if cargo_bbox is None:
        return "SAFE", 0, 0, 0
        
    x, y, w, h = cargo_bbox
    gray = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
    binary = (gray < 250).astype(np.uint8) * 255
    cargo_crop = binary[y:y+h, x:x+w]
    
    profile = []
    for col in range(w):
        col_pixels = cargo_crop[:, col]
        non_zero = np.where(col_pixels > 0)[0]
        if len(non_zero) > 0:
            profile.append(h - non_zero[0])
        else:
            profile.append(0)
            
    profile = np.array(profile)
    
    # คำนวณความสูงเฉลี่ยฝั่งซ้ายและขวา
    left_margin = int(w * 0.1)
    mid_left = int(w * 0.4)
    mid_right = int(w * 0.6)
    right_margin = int(w * 0.9)
    
    left_height = np.mean(profile[left_margin:mid_left]) if mid_left > left_margin else 0
    right_height = np.mean(profile[mid_right:right_margin]) if right_margin > mid_right else 0
    
    height_diff = abs(left_height - right_height)
    height_ratio_diff = height_diff / max(1, h)
    
    # หาจำนวนเส้นขอบกล่องแนวนอน (Horizontal Lines)
    edges = cv2.Canny(gray[y:y+h, x:x+w], 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=40, minLineLength=30, maxLineGap=10)
    
    horizontal_lines_count = 0
    if lines is not None:
        for line in lines:
            x1_l, y1_l, x2_l, y2_l = line[0]
            angle = np.abs(np.arctan2(y2_l - y1_l, x2_l - x1_l) * 180 / np.pi)
            if angle < 10 or angle > 170:
                horizontal_lines_count += 1
                
    # ใช้เกณฑ์ความเหลื่อมที่ 12% เพื่อให้ครอบคลุมกรณีมองผ่านเปอร์สเปกทีฟเอียงเฉียง
    if height_ratio_diff > 0.12:
        if left_height < (h * 0.15):
            return "FRONT_EMPTY_RISK", float(left_height), float(right_height), horizontal_lines_count
        elif right_height < (h * 0.15):
            return "REAR_EMPTY_RISK", float(left_height), float(right_height), horizontal_lines_count
        else:
            return "STEP_DOWN_RISK", float(left_height), float(right_height), horizontal_lines_count
            
    return "SAFE", float(left_height), float(right_height), horizontal_lines_count

def find_step_transition_ratio(crop_img, cargo_bbox):
    """
    ค้นหาระดับการเปลี่ยนผ่านระดับความสูง (Transition point) บนพื้นผิวหน้าตัดเพื่อกำหนดช่วง Ratio อัตโนมัติ
    """
    if cargo_bbox is None:
        return 0.33, 0.98
        
    x, y, w, h = cargo_bbox
    gray = cv2.cvtColor(crop_img, cv2.COLOR_BGR2GRAY)
    binary = (gray < 250).astype(np.uint8) * 255
    cargo_crop = binary[y:y+h, x:x+w]
    
    profile = []
    for col in range(w):
        col_pixels = cargo_crop[:, col]
        non_zero = np.where(col_pixels > 0)[0]
        if len(non_zero) > 0:
            profile.append(h - non_zero[0])
        else:
            profile.append(0)
    profile = np.array(profile)
    
    # หาตำแหน่งที่มีการเปลี่ยนแปลงสูงที่สุด (Gradient Peak)
    smoothed = np.convolve(profile, np.ones(15)/15, mode='same')
    gradients = np.abs(np.diff(smoothed))
    
    search_start = int(w * 0.2)
    search_end = int(w * 0.8)
    
    if search_end > search_start:
        peak_idx = np.argmax(gradients[search_start:search_end]) + search_start
    else:
        peak_idx = int(w * 0.5)
        
    transition_ratio = peak_idx / w
    
    # กำหนดพื้นที่เสี่ยงเป็นระยะกว้าง +/- 20% จากจุดเปลี่ยนระดับความสูง
    x1 = max(0.01, transition_ratio - 0.20)
    x2 = min(0.99, transition_ratio + 0.20)
    return x1, x2

@functions_framework.http
def process_request(request):
    """
    HTTP Webhook Endpoint สำหรับประมวลผลกล่องรอยต่อต่างระดับและกรณีอื่นๆ
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

        open_cv_image = np.array(pages[0]) 
        img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
        h, w, _ = img.shape

        # สเกลสัดส่วนพื้นที่ Viewport (FRONT/BACK) ซีกซ้ายกว้าง 75%
        front_y1, front_y2 = int(h * 0.12), int(h * 0.50)
        back_y1, back_y2 = int(h * 0.50), int(h * 0.92)
        crop_w_end = int(w * 0.75)

        front_crop = img[front_y1:front_y2, 0:crop_w_end]
        back_crop = img[back_y1:back_y2, 0:crop_w_end]

        # 1. รันการวิเคราะห์ทางภาพเชิงวิศวกรรมโดยอัตโนมัติ
        f_cargo = scan_viewport_elements(front_crop)
        b_cargo = scan_viewport_elements(back_crop)
        
        f_case, f_l_h, f_r_h, f_lines = analyze_cargo_height_profile(front_crop, f_cargo)
        b_case, b_l_h, b_r_h, b_lines = analyze_cargo_height_profile(back_crop, b_cargo)

        # 2. ตรวจสอบ Case Type: ถ้าใน payload ระบุให้ AUTO/SAFE แต่ภาพจริงพบความเสี่ยง ให้ยึดจากความจริงในภาพ
        payload_case_type = data.get('caseType', 'AUTO')
        if payload_case_type in ['AUTO', 'SAFE']:
            if f_case != "SAFE":
                case_type = f_case
            elif b_case != "SAFE":
                case_type = b_case
            else:
                case_type = "SAFE"
        else:
            case_type = payload_case_type

        detected_hazards = []

        if case_type != "SAFE":
            # ดึงช่วงอัตราส่วน (Ratios) จาก payload
            raw_front_ratios = data.get('frontRiskRatios') or data.get('frontRiskRatio')
            raw_back_ratios = data.get('backRiskRatios') or data.get('backRiskRatio')
            
            # หากไม่ได้ระบุ Ratio มา ให้คำนวณแบบ Dynamic จากการวัดความต่างระดับขอบเขตของตัวกล่องโดยอัตโนมัติ
            if not raw_front_ratios:
                if f_case != "SAFE":
                    ax1, ax2 = find_step_transition_ratio(front_crop, f_cargo)
                    raw_front_ratios = [{'x1': float(ax1), 'x2': float(ax2)}]
                else:
                    raw_front_ratios = [{'x1': 0.33, 'x2': 0.98}]
                    
            if not raw_back_ratios:
                if b_case != "SAFE":
                    ax1, ax2 = find_step_transition_ratio(back_crop, b_cargo)
                    raw_back_ratios = [{'x1': float(ax1), 'x2': float(ax2)}]
                else:
                    raw_back_ratios = [{'x1': 0.02, 'x2': 0.67}]
            
            front_ratios_list = raw_front_ratios if isinstance(raw_front_ratios, list) else [raw_front_ratios]
            back_ratios_list = raw_back_ratios if isinstance(raw_back_ratios, list) else [raw_back_ratios]
            
            has_detection = False

            # --- วาดกล่องจุดเสี่ยงใน FRONT VIEW ---
            if f_cargo:
                fx, fy, fw, fh = f_cargo
                for i, ratio in enumerate(front_ratios_list):
                    if not ratio or 'x1' not in ratio or 'x2' not in ratio:
                        continue
                    has_detection = True
                    f_x1 = int(fx + fw * ratio['x1'])
                    f_x2 = int(fx + fw * ratio['x2'])
                    f_y1 = max(0, int(fy - fh * 0.05))
                    f_y2 = min(front_crop.shape[0] - 1, int(fy + fh * 1.05))
                    
                    gx_f_x1, gy_f_y1 = f_x1, f_y1 + front_y1
                    gx_f_x2, gy_f_y2 = f_x2, f_y2 + front_y1
                    
                    overlay = img.copy()
                    cv2.rectangle(overlay, (gx_f_x1, gy_f_y1), (gx_f_x2, gy_f_y2), (0, 0, 255), -1)
                    cv2.addWeighted(overlay, 0.2, img, 0.8, 0, img)
                    
                    cv2.rectangle(img, (gx_f_x1, gy_f_y1), (gx_f_x2, gy_f_y2), (0, 0, 255), 4)
                    cv2.putText(img, f"HAZARD #{i+1}: {case_type}", (gx_f_x1, gy_f_y1 - 15),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2, cv2.LINE_AA)

            # --- วาดกล่องจุดเสี่ยงใน BACK VIEW ---
            if b_cargo:
                bx, by, bw, bh = b_cargo
                for i, ratio in enumerate(back_ratios_list):
                    if not ratio or 'x1' not in ratio or 'x2' not in ratio:
                        continue
                    has_detection = True
                    b_x1 = int(bx + bw * ratio['x1'])
                    b_x2 = int(bx + bw * ratio['x2'])
                    b_y1 = max(0, int(by - bh * 0.05))
                    b_y2 = min(back_crop.shape[0] - 1, int(by + bh * 1.05))
                    
                    gx_b_x1, gy_b_y1 = b_x1, b_y1 + back_y1
                    gx_b_x2, gy_b_y2 = b_x2, b_y2 + back_y1
                    
                    overlay = img.copy()
                    cv2.rectangle(overlay, (gx_b_x1, gy_b_y1), (gx_b_x2, gy_b_y2), (0, 0, 255), -1)
                    cv2.addWeighted(overlay, 0.2, img, 0.8, 0, img)
                    
                    cv2.rectangle(img, (gx_b_x1, gy_b_y1), (gx_b_x2, gy_b_y2), (0, 0, 255), 4)
                    cv2.putText(img, f"HAZARD #{i+1}: {case_type}", (gx_b_x1, gy_b_y1 - 15),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2, cv2.LINE_AA)

            # --- ดึงข้อมูลรายละเอียดของสินค้าเพื่อออกรายงานความปลอดภัย ---
            zone_name = data.get('zoneName', 'กลางตู้สินค้าเชื่อมโยงรอยต่อระดับ')
            direction_text = data.get('directionText', 'สอดคล้องกันทั้งภาพระนาบ FRONT และ BACK')
            high_sku = data.get('highSku', 'ไม่ระบุ')
            low_sku = data.get('lowSku', 'ไม่ระบุ')
            high_layer = data.get('highLayer', 2)
            low_layer = data.get('lowLayer', 1)

            report_detail = generate_action_report(
                case_type=case_type,
                zone_name=zone_name,
                direction_text=direction_text,
                high_sku=high_sku,
                low_sku=low_sku,
                high_layer=high_layer,
                low_layer=low_layer
            )
            detected_hazards.append({
                "title": f"ตรวจพบจุดเสี่ยงอันตรายรูปแบบ: {case_type}",
                "detail": report_detail
            })
            
            # Fallback หากสแกนวัตถุทั้งหมดล้มเหลว
            if not has_detection:
                f_x1, f_y1, f_x2, f_y2 = int(w * 0.32), int(h * 0.22), int(w * 0.58), int(h * 0.45)
                b_x1, b_y1, b_x2, b_y2 = int(w * 0.32), int(h * 0.60), int(w * 0.58), int(h * 0.82)
                
                overlay = img.copy()
                cv2.rectangle(overlay, (f_x1, f_y1), (f_x2, f_y2), (0, 0, 255), -1)
                cv2.rectangle(overlay, (b_x1, b_y1), (b_x2, b_y2), (0, 0, 255), -1)
                cv2.addWeighted(overlay, 0.2, img, 0.8, 0, img)
                
                cv2.rectangle(img, (f_x1, f_y1), (f_x2, f_y2), (0, 0, 255), 4)
                cv2.rectangle(img, (b_x1, b_y1), (b_x2, b_y2), (0, 0, 255), 4)

        # -------------------------------------------------------------
        # ส่งค่ากลับไปยังปลายทาง
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
            "processedImageUrl": processed_image_url,
            "physicalAnalysis": {
                "frontView": {
                    "detectedCase": f_case,
                    "leftHeightPx": f_l_h,
                    "rightHeightPx": f_r_h,
                    "horizontalLinesFound": f_lines
                },
                "backView": {
                    "detectedCase": b_case,
                    "leftHeightPx": b_l_h,
                    "rightHeightPx": b_r_h,
                    "horizontalLinesFound": b_lines
                }
            }
        }

        del open_cv_image
        del img

        return (response_data, 200, headers)

    except Exception as e:
        return ({"error": str(e), "trace": traceback.format_exc()}, 500, headers)
