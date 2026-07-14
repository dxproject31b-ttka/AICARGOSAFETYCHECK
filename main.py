import io
import cv2
import numpy as np
import base64
import functions_framework
from pdf2image import convert_from_bytes

def generate_action_report(case_type, zone_name, direction_text, high_sku, low_sku, high_layer, low_layer):
    """
    ฟังก์ชันคลัง Template สรุปรูปแบบประโยคข้อความแจ้งแยกตามประเภทงาน 4 รูปแบบ
    (ปรับปรุงกระชับและใช้คำว่าเหลื่อมกว่าด้านตรงกันข้าม)
    """
    if case_type == "STEP_DOWN_RISK":  # รูปแบบที่ 1: รอยเหลื่อมต่างระดับกลางตู้
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
        
    elif case_type == "REAR_EMPTY_RISK":  # รูปแบบที่ 2: สินค้าสูงขนาบพื้นที่โล่งท้ายตู้
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
        
    elif case_type == "FRONT_EMPTY_RISK":  # รูปแบบที่ 3: สินค้าสูงขนาบพื้นที่โล่งหัวตู้
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
        
    else:  # รูปแบบที่ 4: ปลอดภัย (SAFE)
        return (
            f"ปลอดภัย (SAFE)\n\n"
            f"🟢 [STATUS] ผลการตรวจสอบสถานะความปลอดภัย: ปลอดภัย (SAFE)\n"
            f"* 📍 พิกัดพื้นที่: ตรวจสอบระนาบภาพ FRONT และ BACK หน้า 2 ครบถ้วน\n"
            f"* 📦 สถานะสินค้า: ระดับความสูงและการกระจายน้ำหนักของกลุ่มสินค้าทุกบล็อกจัดวางอยู่ในแนวราบสมดุลเสมอกัน "
            f"ไม่มีพิกัดใดที่มีความสูงเหลื่อมกว่าด้านตรงกันข้าม สินค้าค้ำยันประคองซึ่งกันและกันอย่างสมบูรณ์\n\n"
            f"🛠️ ACTION REQUIRED:\n"
            f"* ไม่ต้องดำเนินการใดๆ เพิ่มเติม สามารถอนุมัติปล่อยรถออกเดินทางขนส่งได้ทันที"
        )

@functions_framework.http
def process_request(request):
    """
    HTTP Webhook รับ Request แบบ Base64 (Stateless)
    """
    # 1. จัดการเรื่อง CORS เพื่ออนุญาตให้ยิงข้ามโดเมนได้สำหรับการรันเว็บแอป
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

        file_name = data.get('fileName', 'unknown.pdf')
        base64_str = data.get('base64')
        
        # ลบ Data URI scheme ออกถ้ามีติดมา (เช่น data:application/pdf;base64,...)
        if "," in base64_str:
            base64_str = base64_str.split(",")[1]

        # 2. ถอดรหัส Base64 ให้กลับเป็นไฟล์ไบนารี (Bytes) เข้าสู่หน่วยความจำ
        pdf_bytes = base64.b64decode(base64_str)

        # 3. แปลง PDF หน้า 2 ให้เป็นไฟล์รูปภาพตาม Logic ที่กำหนด
        try:
            # พยายามดึงเฉพาะหน้า 2 (first_page=2, last_page=2)
            pages = convert_from_bytes(pdf_bytes, first_page=2, last_page=2, dpi=200)
        except Exception:
            # Fallback เผื่อกรณีไฟล์มีหน้าเดียวให้ดึงหน้าแรกแทน เพื่อป้องกัน Error
            pages = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=200)
        
        if not pages:
            return ({"error": "Cannot read page 2 of the PDF"}, 400, headers)

        # แปลงโครงสร้างภาพของ PIL ให้เป็นอาร์เรย์ในระบบสี BGR เพื่อให้ OpenCV นำไปประมวลผล
        open_cv_image = np.array(pages[0]) 
        img = cv2.cvtColor(open_cv_image, cv2.COLOR_RGB2BGR)
        h, w, _ = img.shape

        # =========================================================================
        # 🧠 4. CORE AI MULTI-LOGIC SELECTION 
        # อ้างอิงตามเกณฑ์: ผนังสีเหลือง = ฝั่งหัวตู้สินค้า (ติดหัวลาก)
        # 📸 ภาพแรก FRONT View: ขวามือ = หัวตู้สินค้า (ขอบเหลือง) | ซ้ายมือ = ท้ายตู้สินค้า (ประตูท้าย)
        # 📸 ภาพสอง BACK View: ซ้ายมือ = หัวตู้สินค้า (แผงเหลือง) | ขวามือ = ท้ายตู้สินค้า (ประตูท้าย)
        # =========================================================================
        detected_hazards = []
        
        # 🧪 ตัวอย่างสถานการณ์จำลอง (Manifest AC03-01): 
        # ตรวจพบสินค้าสีน้ำเงินเข้ม [ATFBA-F6] ฝั่งท้ายตู้ซ้อนสูง 2 ชั้น เหลื่อมกว่าฝั่งหัวตู้ติดผนังสีเหลืองที่เตี้ยเพียงชั้นเดียว
        has_step_risk_ac03 = True  
        has_other_risk = False
        
        # --- [ตรวจสอบจุดเสี่ยงรอยเหลื่อมต่างระดับผิวเปิดฝั่งค่อนไปทางหัวตู้สินค้า] ---
        if has_step_risk_ac03:
            report_1 = generate_action_report(
                case_type="STEP_DOWN_RISK", 
                zone_name="กลางตู้สินค้าต่อเนื่องช่วงค่อนไปทางหัวรถ", 
                direction_text="ฝั่งขวาของภาพ FRONT / ฝั่งซ้ายของภาพ BACK",
                high_sku="ATFBA-F6", 
                low_sku="สินค้าแถวหน้าฝั่งหัวตู้", 
                high_layer=2, 
                low_layer=1
            )
            detected_hazards.append({
                "title": "จุดเสี่ยงที่ 1: รอยเหลื่อมต่างระดับผิวเปิดโล่ง (มีความสูงเหลื่อมกว่าด้านตรงกันข้ามฝั่งผนังสีเหลือง)",
                "detail": report_1
            })
            
            # 📸 OpenCV ตีกรอบแจ้งเตือนสีแดงในภาพแรก FRONT View (วาดกรอบตรงรอยเหลื่อมกลางตู้ค่อนไปทางขวา)
            cv2.rectangle(img, (int(w * 0.35), int(h * 0.25)), (int(w * 0.55), int(h * 0.45)), (0, 0, 255), 4)
            cv2.putText(img, "🚨 POINT 1: RISK DETECTED", (int(w * 0.35), int(h * 0.25) - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
            
            # 📸 OpenCV ตีกรอบแจ้งเตือนสีแดงในภาพสอง BACK View (วาดกรอบตรงรอยเหลื่อมกลางตู้ค่อนไปทางซ้าย)
            cv2.rectangle(img, (int(w * 0.45), int(h * 0.70)), (int(w * 0.65), int(h * 0.90)), (0, 0, 255), 4)

        # --- ตัวอย่างเงื่อนไขการดักจับรูปแบบที่ 2 หรืออื่นๆ ในอนาคต ---
        if has_other_risk:
            pass

        # =========================================================================
        # 5. รวบรวมข้อมูลและมัดก้อนรายงานผลลัพธ์ (Final Output Compilation)
        # =========================================================================
        if len(detected_hazards) > 0:
            status_text = f"พบจุดเสี่ยงอันตราย (รวมทั้งหมด {len(detected_hazards)} จุด)"
            # นำรายงานใน List ทั้งหมดมาร้อยต่อกันและคั่นด้วยเส้นประยาวเพื่อให้อ่านง่ายบนจอมือถือ
            action_text = "\n\n--------------------------------------------------\n\n".join(
                [f"[{h['title']}]\n{h['detail']}" for h in detected_hazards]
            )
            hazard_count = len(detected_hazards)
        else:
            # หากประมวลผลแล้วปลอดภัยครบถ้วน ให้ดึงรูปแบบที่ 4 (SAFE) มาแสดงผล
            full_safe_report = generate_action_report("SAFE", "", "", "", "", 0, 0)
            status_text = "ปลอดภัย (SAFE)"
            action_text = full_safe_report
            hazard_count = 0

        # 6. แปลงภาพผลลัพธ์จาก OpenCV กลับเป็น Base64
        _, encoded_img = cv2.imencode('.png', img)
        processed_base64 = base64.b64encode(encoded_img).decode('utf-8')
        processed_image_url = f"data:image/png;base64,{processed_base64}"

        # 7. คืนค่าเป็น JSON กลับไปยัง Google Apps Script
        response_data = {
            "status": status_text,
            "hazardCount": hazard_count,
            "actionRequired": action_text,
            "processedImageUrl": processed_image_url
        }

        return (response_data, 200, headers)

    except Exception as e:
        import traceback
        return ({"error": str(e), "trace": traceback.format_exc()}, 500, headers)
