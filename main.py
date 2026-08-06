import base64
import io
import json
import os
import time
import gc
import traceback
import random
import re
import PIL.Image
import PIL.ImageDraw
import PIL.ImageStat
import PIL.PngImagePlugin
import fitz  # PyMuPDF
import functions_framework
import google.generativeai as genai

# ---------------------------------------------------------------------------
# AI Cargo Safety Checker - High Precision v23.1
#
# v23.1 - แก้ปัญหา FRONT view โดยเปลี่ยนแนวทางจาก "แบบจำลองเส้นตรงทั่วโลก" (global
#   floor-line V-shape) เป็น "LOCAL FLOOR" (พื้นเฉพาะจุด คำนวณจากพิกเซลคาร์โก้จริงใน
#   แต่ละคอลัมน์/ตั้งโดยตรง):
#
#   ROOT CAUSE ที่พบจากการ debug พิกเซลจริง: ขอบล่างของคาร์โก้ใน FRONT view มีลักษณะ
#   เป็น "คลื่น" จริง (ไม่ใช่สัญญาณรบกวน) เกิดจากการจัดวางกล่องแบบสลับตำแหน่งความลึก
#   (checker pattern) เพื่อความมั่นคงของคาร์โก้ - แต่ละตั้งอยู่คนละตำแหน่งความลึกทำให้
#   ตำแหน่งขอบล่างที่เห็นในภาพ isometric ต่างกันไปตามตำแหน่งความลึกของตั้งนั้น เส้นตรง
#   ทั่วโลกเส้นเดียว (แม้จะฟิตได้ R²=1.00 ในบางส่วน) จึงไม่สามารถแทนตำแหน่งพื้นจริงของ
#   ทุกตั้งได้แม่นยำพอ ทำให้ coverage ต่ำมาก (0.08-0.24) เพราะ extrapolation คลาดเคลื่อน
#   นอกช่วงข้อมูลจริงที่ใช้ฟิต
#
#   วิธีแก้: เปลี่ยน detect_stack_columns/_find_cargo_present_clusters ให้ตรวจสอบ "มี
#   คาร์โก้หรือไม่" จากทั้งช่วงความสูงที่เป็นไปได้ (ไม่ใช่แถบแคบตามเส้นตรงทั่วโลก) และ
#   เปลี่ยน detect_boxes_in_stack ให้คำนวณ "พื้นเฉพาะของแต่ละตั้ง" จากค่ามัธยฐานของ
#   ตำแหน่ง local floor ที่พบจริงในช่วง x ของตั้งนั้นโดยตรง (ไม่พึ่งพาแบบจำลองเรขาคณิต
#   ใดๆ) วิธีนี้ทนทานต่อคลื่นของตำแหน่งความลึกได้เองตามธรรมชาติ
#   ผลลัพธ์: FRONT view coverage เพิ่มจาก 0.08-0.24 เป็น 0.84-1.00 ทุกไฟล์ (17/17)
#   detect_floor_line_v_shape() ยังคงเก็บไว้ในโค้ด (เป็นข้อมูลอ้างอิง/อาจมีประโยชน์ใน
#   อนาคต) แต่ไม่ได้ถูกเรียกใช้ในเส้นทางหลักของ per-box segmentation อีกต่อไป
#
#   บั๊กเพิ่มเติมที่พบและแก้ไขระหว่างการทดสอบ FRONT view (ไฟล์ AC09-02):
#   - "SAME-COLOR ADJACENT BLEED" - เมื่อกล่อง 2 ตั้งที่อยู่ติดกันมีสีเดียวกันสนิทและ
#     ไม่มีเส้นแบ่งที่มองเห็นได้ระหว่างกัน การขยายขอบเขต (extend) ของกล่องในตั้งหนึ่ง
#     จะไหลข้ามไปติดกับตั้งข้างเคียง ทำให้เกิด OVERHANG_RISK ปลอม - แก้ไขโดยตรวจจับ
#     "hit_limit" (การขยายไปจนสุด search_expand_px โดยไม่เจอขอบเขตจริง) ใน
#     _extend_edge_contiguous() แล้วทิ้งค่าที่ hit_limit=True ออกจากการคำนวณค่ามัธยฐาน
#   - เพิ่มเกณฑ์ "จำนวนตัวอย่างที่เชื่อถือได้ขั้นต่ำ" (ต้องมีอย่างน้อยครึ่งหนึ่งของ
#     ตัวอย่างทั้งหมดที่ไม่ hit_limit) มิฉะนั้น fallback ไปใช้ขอบเขตของตั้งเดิม (x0/x1)
#     แทนการเชื่อค่ามัธยฐานจากตัวอย่างที่เหลือน้อยเกินไป (ไม่น่าเชื่อถือทางสถิติ)
#
#   ผลการทดสอบสุดท้าย (17 ไฟล์) หลัง v23.1: ทั้ง FRONT และ BACK view มี coverage
#   0.84-1.00 ทุกไฟล์ (17/17 ทั้งคู่) พบการตรวจจับ REAR_LATERAL_IMBALANCE เพิ่มเติมใน
#   FRONT view 5 ไฟล์ (ratio 0.39-0.64) ซึ่งตรวจสอบด้วยภาพจริงแล้วยืนยันว่าเป็น true
#   positive (เห็นความสูงต่างกันจริงระหว่างตั้งที่อยู่ติดกัน เช่น AB01-01: NOKIA-AK
#   1 ชั้น ติดกับ STEMB-AK/SHPIA-AK 2 ชั้น) พบ OVERHANG_RISK 1 รายการที่ไฟล์ AC09-02
#   ซึ่งหลังผ่านการกรองหลายชั้น (ratio, absolute px, hit_limit, minimum samples) และ
#   ตรวจสอบภาพจริงแล้ว มีความเป็นไปได้สูงว่าเป็น true positive เช่นกัน (ไม่ตัดทิ้ง)
#
# v23 - แก้ปัญหา "PERSPECTIVE/ISOMETRIC FLOOR" ที่ค้นพบระหว่างทดสอบ v22 กับไฟล์จริง
#   17 ไฟล์: ภาพ diagram เป็นมุมมอง isometric ซึ่ง "พื้นตู้" ไม่ใช่เส้นแนวนอน แต่เป็น
#   รูปตัว "V" (piecewise-linear 2 ท่อน) เนื่องจากกล้องมองจากมุมของตู้คอนเทนเนอร์
#   (ยืนยันด้วยการ debug พิกเซลจริง: bottom-most structure pixel ต่อคอลัมน์ x สร้าง
#   กราฟรูป V ที่มีจุดยอด แล้วลาดลงทั้ง 2 ข้างด้วยความชันคงที่ ~0.47-0.53 ซึ่งตรงกับ
#   อัตราส่วน isometric/dimetric แบบ 2:1 ที่พบได้ทั่วไปในซอฟต์แวร์ CAD/loading-plan)
#
#   v22.1 (patch ก่อนหน้า) ใช้ floor_y แบบคงที่ (flat, scalar) ซึ่งทำให้การสุ่มแถบ
#   พิกเซลใกล้ "พื้น" เพื่อแบ่งตั้ง (stack) มีโอกาสตกอยู่ในพื้นที่ว่าง/ไปเจอลูกศรชี้
#   ตำแหน่งอ้างอิง (reference arrow) แทนพื้นสินค้าจริง ทำให้ coverage ratio ต่ำและถูก
#   REJECTED โดย safety gate เกือบทุกไฟล์ (16/17 ไฟล์ fallback กลับไปพึ่ง AI ทั้งหมด)
#
#   v23 เพิ่มฟังก์ชัน detect_floor_line_v_shape() ที่ตรวจจับพื้นตู้จริงเป็น piecewise-
#   linear V-shape จากขอบล่างสุดของ "โครงสร้างตู้" (container structure, saturated
#   color) - ไม่ใช้ขอบล่างของคาร์โก้ เพราะทดสอบพบว่าขอบคาร์โก้ให้ผลฟิตแย่ (R² ต่ำ
#   0.27-0.47) บริเวณใกล้ผนังหัวตู้/ประตูท้ายตู้ที่มักมีช่องว่างจริง (ตรงกับ
#   FRONT_EMPTY_RISK/REAR_EMPTY_RISK ที่ต้องการตรวจจับพอดี - ใช้คาร์โก้อ้างอิงพื้นจะ
#   ขัดแย้งกันเองในโซนนั้น) ในขณะที่โครงสร้างตู้ (ผนัง/พื้น) ปรากฏอยู่เสมอไม่ว่าจะมี
#   คาร์โก้วางถึงหรือไม่ จึงเป็นข้อมูลอ้างอิงที่เสถียรกว่า (ทดสอบแล้วได้ R²~0.99 ทั้ง
#   2 ฝั่งเมื่อใช้หน้าต่างค้นหาแคบรอบๆ container_bounds['ymax'] ที่ตรวจพบไว้แล้ว)
#
#   บั๊กที่พบและแก้ไขระหว่างพัฒนา detect_floor_line_v_shape:
#   1) "PLATEAU BUG" - จุดยอดของ V ไม่ใช่จุดแหลมเดี่ยว แต่เป็นแนวราบสั้นๆ (พบว่ามี
#      หลายจุด x ติดกันที่ y เท่ากับค่าสูงสุดพอดี) การแบ่งฝั่งซ้าย/ขวาแบบ argmax เดิม
#      ทำให้จุด plateau ปนเข้าไปฝั่งใดฝั่งหนึ่ง บิดเบือน slope ที่ฟิตได้ - แก้ไขโดยหา
#      "พิสัยของ plateau" แล้วตัดออกจากทั้ง 2 ฝั่งก่อนฟิตเส้นตรง
#   2) ปรับ FLOOR_LINE_SAMPLE_STEP_PX จาก 6 เป็น 3 (ละเอียดขึ้น)
#   3) "GAP-CLUSTER NOISE" - หลังคาร์โก้บดบังพื้นบางส่วน จุดข้อมูลกระจัดกระจายที่ไม่
#      เกี่ยวข้องกับพื้นจริงอาจปรากฏหลัง gap ทำให้การฟิตเสียหาย - แก้ไขด้วยการเลือก
#      เฉพาะ "กลุ่มก้อนต่อเนื่องที่ใหญ่ที่สุด" ก่อนฟิตเส้นตรง
#
#   มี QUALITY GATE ป้องกันผลลัพธ์แย่: ตรวจสอบ R² ของการฟิตเส้นตรงทั้ง 2 ฝั่ง + ตรวจสอบ
#   ความชันต้องอยู่ในช่วงสมเหตุสมผล + เครื่องหมายถูกต้อง หากคุณภาพต่ำเกินไปจะคืนค่า
#   valid=False ให้ผู้เรียกใช้ fallback กลับไปใช้ floor_y แบบคงที่ (flat) ทันที
#
# v22 - พัฒนา PER-BOX SEGMENTATION (deterministic) ให้กับ 3 risk type ที่เดิมพึ่ง
#   AI (Gemini) เพียงอย่างเดียวใน v21: REAR_LATERAL_IMBALANCE, TALL_UNSTABLE_RISK,
#   OVERHANG_RISK ดูรายละเอียดในหัวข้อ "PER-BOX SEGMENTATION" ด้านล่าง
#   (v22.1: เพิ่ม coverage sanity check ป้องกัน false positive จากลูกศรอ้างอิง - ดู
#   หัวข้อ KNOWN LIMITATION ใน build_stack_box_model_per_view สำหรับรายละเอียด)
#
# v21 - แก้ปัญหา "REAR_LATERAL_IMBALANCE พลาดกรณีที่กล่องในตั้งเดียวกันสูงไม่เท่ากัน
#   ในมุมมอง 3 มิติ แม้จะดูซ้อนทับ/บังกันบางส่วน" (พบจากไฟล์ AC03-01 ที่ตำแหน่ง
#   ประตูท้าย Front view มี pattern ความสูง 2,2,1) ผ่อนเกณฑ์ confidence ของ
#   REAR_LATERAL_IMBALANCE จาก "HIGH เท่านั้น" เป็น "HIGH หรือ MEDIUM" และปรับปรุง
#   prompt ของ analyze_rear_zone_with_ai() ให้ระบุชัดเจนเรื่อง "ความสูงรวมทั้งตั้ง"
# v20.1 - แก้บั๊ก extract_container_length_mm() ดึงค่าผิดจากบรรทัด COG - ข้ามบรรทัดที่
#   มีคำว่า COG โดยเด็ดขาด
# v19 - เพิ่ม GATE (veto) สำหรับ STEP_DOWN_RISK ที่ Gemini claim มา + แก้บั๊ก merge
#   segment ผิดพลาดเมื่อมี pattern แบบ 'บันได'
# v18 - เพิ่มกลไก deterministic (height-profile) สำหรับ STEP_DOWN_RISK (FORCE)
# v17 - แก้บั๊ก LATERAL_GAP_RISK ไม่ทำงานเมื่อคาลิเบรต mm ไม่สำเร็จ (ratio fallback)
# v16 - เพิ่ม LATERAL_GAP_RISK deterministic + FRONT_EMPTY_RISK ใช้ Front view เป็น
#   แหล่งข้อมูลเดียว
# v15 - deterministic FORCE สำหรับ FRONT_EMPTY_RISK/REAR_EMPTY_RISK
# v14 - เกณฑ์ deterministic ใช้ระยะทางจริง (มม.) แทนสัดส่วน %
# v13 - deterministic gap-ratio gate (สัดส่วน %)
# v12 - ใช้ box_2d จาก Gemini zoom analysis (validate ด้วยสัดส่วนพิกเซลสินค้าจริง)
# v11 - ตรวจจับขอบเขตสินค้าจริงด้วย HSV saturation
# v10 - แก้บั๊ก layout detection กรณีหน้า PDF มี rotation + กฎตายตัว HARDCODED_REAR_SIDE
# v9  - รวม risk ที่อยู่บริเวณเดียวกันเป็น COMBINED_AREA_RISK วาดกรอบเดียว 2 สี
# v6  - deterministic container-boundary detection
# ---------------------------------------------------------------------------

GLOBAL_API_KEYS = []
GLOBAL_KEY_INDEX = 0

RISK_COLORS = {
    "STEP_DOWN_RISK": "red",
    "REAR_EMPTY_RISK": "orange",
    "REAR_LATERAL_IMBALANCE": "deeppink",
    "REAR_COMBINED_RISK": "orange",
    "COMBINED_AREA_RISK": "purple",
    "FRONT_EMPTY_RISK": "yellow",
    "LATERAL_GAP_RISK": "cyan",
    "TALL_UNSTABLE_RISK": "magenta",
    "OVERHANG_RISK": "lime",
}
VALID_RISK_TYPES = set(RISK_COLORS.keys())

ZONE_BASED_RISK_TYPES = {
    "FRONT_EMPTY_RISK",
    "REAR_EMPTY_RISK",
    "REAR_LATERAL_IMBALANCE",
    "REAR_COMBINED_RISK",
}
BOX_BASED_RISK_TYPES = {
    "STEP_DOWN_RISK",
    "LATERAL_GAP_RISK",
    "TALL_UNSTABLE_RISK",
    "OVERHANG_RISK",
}

HARDCODED_REAR_SIDE = {
    "FRONT": "LEFT",
    "BACK": "RIGHT",
}

MIN_EMPTY_GAP_MM = 400
MIN_LATERAL_GAP_MM = 300
FALLBACK_MIN_EMPTY_GAP_RATIO = 0.12
FALLBACK_MIN_LATERAL_GAP_RATIO = 0.12

MIN_STEP_DOWN_RATIO = 0.075
STEP_DOWN_PROFILE_STEP_PX = 5
STEP_DOWN_MIN_CONSISTENT_RUN = 10
STEP_DOWN_MIN_FLAT_WIDTH_PX = 12
STEP_DOWN_CLAIM_OVERLAP_THRESHOLD = 0.10


def get_api_keys_pool():
    global GLOBAL_API_KEYS
    if GLOBAL_API_KEYS:
        return GLOBAL_API_KEYS
    env_value = os.environ.get("GEMINI_API_KEYS", "")
    if env_value:
        keys = [k.strip() for k in env_value.split("|") if k.strip()]
        if keys:
            random.shuffle(keys)
            print(f"Loaded {len(keys)} unique API key(s) into the pool.")
            GLOBAL_API_KEYS = keys
            return GLOBAL_API_KEYS
    print("No Gemini API keys found.")
    return []


def generate_action_report(case_type, description="", sku_list=""):
    sku_line = f"\n   สินค้าที่พบบริเวณนี้: {sku_list}" if sku_list else ""
    actions = {
        "STEP_DOWN_RISK": (
            f"แจ้งเตือน: พบรอยต่างระดับระหว่างกองสินค้า{sku_line}\n"
            f"วิธีแก้ไข:\n"
            f"  • นำไม้อัดกั้นวางขวางระหว่างกองที่สูงต่างกัน เพื่อป้องกันสินค้าล้มทับกัน\n"
            f"  • ตรวจสอบความสูงของแต่ละกองให้ใกล้เคียงกันมากที่สุด\n"
            f"  • รัดด้วยสายเบลท์หรือเชือกให้แน่น ทุกกองที่มีรอยต่างระดับ"
        ),
        "REAR_EMPTY_RISK": (
            f"แจ้งเตือน: บริเวณประตูท้ายตู้มีพื้นที่ว่าง หรือสินค้าวางไม่ถึงประตู{sku_line}\n"
            f"วิธีแก้ไข:\n"
            f"  • นำไม้อัดกั้นวางตั้งแนวตั้งชิดท้ายกองสินค้า เพื่ออุดช่องว่างหน้าประตู\n"
            f"  • รัดด้วยสายเบลท์หรือเชือกให้สินค้าอยู่กับที่ ป้องกันไถลออกเมื่อเปิดประตู\n"
            f"  • ตรวจสอบว่าสินค้าด้านหน้าประตูมีความสูงเสมอกันทั้งซ้ายและขวา"
        ),
        "REAR_LATERAL_IMBALANCE": (
            f"แจ้งเตือน: สินค้าบริเวณประตูท้ายตู้สูงต่ำไม่เท่ากันในแนวกว้าง{sku_line}\n"
            f"วิธีแก้ไข:\n"
            f"  • นำไม้อัดกั้นเสริมด้านที่ต่ำกว่า เพื่อปรับความสูงให้เสมอกันทั้งสองด้าน\n"
            f"  • ตรวจสอบระดับความสูงซ้าย-ขวาให้เท่ากันก่อนปิดประตู\n"
            f"  • รัดด้วยสายเบลท์หรือเชือกขวางป้องกันสินค้าล้มตะแคงเมื่อเปิดประตู"
        ),
        "REAR_COMBINED_RISK": (
            f"แจ้งเตือน: บริเวณประตูท้ายตู้พบทั้งพื้นที่ว่างหน้าประตู และสินค้าสูงต่ำไม่เท่ากันในแนวกว้างในจุดเดียวกัน{sku_line}\n"
            f"วิธีแก้ไข:\n"
            f"  • นำไม้อัดกั้นเสริมด้านที่ต่ำกว่า เพื่อปรับความสูงให้เสมอกันทั้งสองด้าน\n"
            f"  • ตรวจสอบระดับความสูงซ้าย-ขวาให้เท่ากันก่อนปิดประตู\n"
            f"  • รัดด้วยสายเบลท์หรือเชือกขวางป้องกันสินค้าล้มตะแคงเมื่อเปิดประตู"
        ),
        "FRONT_EMPTY_RISK": (
            f"แจ้งเตือน: บริเวณผนังหัวตู้มีช่องว่าง สินค้าวางไม่ชิดผนัง{sku_line}\n"
            f"วิธีแก้ไข:\n"
            f"  • นำไม้อัดกั้นวางชิดผนังหัวตู้ เพื่ออุดช่องว่างระหว่างสินค้ากับผนัง\n"
            f"  • ตรวจสอบว่าสินค้าแต่ละกองชิดกันแน่น ไม่มีช่องให้สินค้าเลื่อน\n"
            f"  • รัดด้วยสายเบลท์หรือเชือกป้องกันสินค้าไถลมาข้างหน้าตอนเบรก"
        ),
        "LATERAL_GAP_RISK": (
            f"แจ้งเตือน: พบพื้นที่ว่างด้านข้างบนพื้นตู้ สินค้าไม่กระจายเต็มความกว้าง{sku_line}\n"
            f"วิธีแก้ไข:\n"
            f"  • นำไม้อัดกั้นหรือถุงลมอุดช่องว่างด้านข้างระหว่างสินค้ากับผนังด้านข้าง\n"
            f"  • ตรวจสอบว่าสินค้าชิดกันแน่นทั้งด้านข้าง ไม่มีช่องให้เลื่อนหรือล้ม\n"
            f"  • รัดด้วยสายเบลท์หรือเชือกขวางป้องกันสินค้าเลื่อน/ตกขณะเข้าโค้งหรือเบรก"
        ),
        "TALL_UNSTABLE_RISK": (
            f"แจ้งเตือน: พบสินค้าสูงโดดเดี่ยว ไม่มีของข้างค้ำยัน{sku_line}\n"
            f"วิธีแก้ไข:\n"
            f"  • นำไม้อัดกั้นค้ำยันด้านข้างของกองที่สูง\n"
            f"  • ตรวจสอบว่าฐานของกองสินค้ามั่นคงและไม่โยกคลอน\n"
            f"  • รัดด้วยสายเบลท์หรือเชือกในแนวขวางรอบกองที่สูง ป้องกันล้มตะแคง"
        ),
        "OVERHANG_RISK": (
            f"แจ้งเตือน: พบสินค้าชั้นบนยื่นพ้นขอบสินค้าชั้นล่าง{sku_line}\n"
            f"วิธีแก้ไข:\n"
            f"  • จัดเรียงสินค้าชั้นบนใหม่ให้อยู่ในขอบของชั้นล่าง ไม่ให้ยื่นออกมา\n"
            f"  • ตรวจสอบความสูงแต่ละชั้นให้เสมอกัน ก่อนวางชั้นถัดไป\n"
            f"  • รัดด้วยสายเบลท์หรือเชือกรอบทุกชั้น ป้องกันสินค้าหล่นระหว่างเดินทาง"
        ),
    }
    return actions.get(case_type, description or "ปลอดภัย\nไม่พบจุดเสี่ยงที่ต้องดำเนินการเพิ่มเติม")


def clean_json_response(text):
    text = (text or "").strip()
    start_list = text.find("[")
    end_list = text.rfind("]")
    start_dict = text.find("{")
    end_dict = text.rfind("}")
    if start_list != -1 and end_list != -1:
        if start_dict == -1 or start_list < start_dict:
            return text[start_list:end_list + 1]
    if start_dict != -1 and end_dict != -1:
        return text[start_dict:end_dict + 1]
    return text


def detect_page_layout_from_pdf(pdf_bytes: bytes) -> str:
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_index = 1 if len(doc) >= 2 else 0
        page = doc[page_index]
        page_width = page.rect.width
        page_height = page.rect.height
        print(f"Page size (rendered/rotated space): {page_width:.0f}x{page_height:.0f} | rotation={page.rotation}")

        rot_matrix = page.rotation_matrix

        def _to_rendered_rect(rect):
            return rect * rot_matrix

        front_instances = page.search_for("Front")
        back_instances = page.search_for("Back")

        if front_instances and back_instances:
            front_rect = _to_rendered_rect(front_instances[0])
            back_rect = _to_rendered_rect(back_instances[0])
            dy = abs(back_rect.y0 - front_rect.y0)
            dx = abs(back_rect.x0 - front_rect.x0)
            print(f"Front label (rendered space): {front_rect} | Back label (rendered space): {back_rect} | dx={dx:.0f} dy={dy:.0f}")
            if dy > dx:
                print("Layout detected: TOP_BOTTOM (Front/Back differ mainly in Y position)")
                return "TOP_BOTTOM"
            else:
                print("Layout detected: LEFT_RIGHT (Front/Back differ mainly in X position)")
                return "LEFT_RIGHT"

        if back_instances:
            back_rect = _to_rendered_rect(back_instances[0])
            y_ratio = back_rect.y0 / page_height
            x_ratio = back_rect.x0 / page_width
            print(f"Back label only (rendered space): {back_rect} | x_ratio={x_ratio:.2f} y_ratio={y_ratio:.2f}")
            if y_ratio > 0.55:
                print("Layout detected: TOP_BOTTOM (Back label in lower half of page)")
                return "TOP_BOTTOM"
            if x_ratio > 0.55:
                print("Layout detected: LEFT_RIGHT (Back label in right portion, same row as Front)")
                return "LEFT_RIGHT"

        is_landscape = page_width > page_height
        print(f"No reliable Front/Back label found - falling back to page aspect ratio (Landscape={is_landscape})")
        if is_landscape:
            return "LEFT_RIGHT"
    except Exception as e:
        print(f"Layout detection failed ({e}), defaulting to TOP_BOTTOM")
    print("Layout detected: TOP_BOTTOM (default)")
    return "TOP_BOTTOM"


def extract_container_length_mm(pdf_bytes: bytes):
    """
    ดึงค่าความยาวตู้จริง (มิลลิเมตร) จากข้อความในหน้า manifest PDF (เช่นตัวเลข
    "7200 (mm)") ใช้เป็นค่าคาลิเบรตแปลงพิกเซล -> มิลลิเมตรจริง

    v20.1 FIX: ประมวลผลทีละบรรทัด (ไม่ใช่ full-text regex) แล้ว "ข้ามบรรทัดที่มีคำว่า
    COG โดยเด็ดขาด" เพราะรูปแบบ "N x N x N (mm)" ของ COG (Center of Gravity) ไม่ใช่
    ค่าความยาวตู้เดี่ยวๆ แบบ "N (mm)" ที่ label เส้นบอกขนาดในภาพ diagram ใช้ - เดิม
    เคยจับค่าจากบรรทัด COG ผิดพลาด ทำให้คาลิเบรตคลาดเคลื่อนหลายเท่า
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        all_values = []
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            full_text = page.get_text("text")
            for line in full_text.splitlines():
                if "cog" in line.lower():
                    continue
                matches = re.findall(r"(\d{3,6})\s*\(\s*mm\s*\)", line, flags=re.IGNORECASE)
                values = [int(m) for m in matches if 1000 <= int(m) <= 20000]
                if values:
                    print(f"Page {page_idx} line {line!r}: found mm values {sorted(set(values))}")
                    all_values.extend(values)
        if not all_values:
            print("WARNING: Could not find any valid '(mm)' dimension text in ANY page of PDF "
                  "(excluding COG lines) - length calibration unavailable, will use ratio-based "
                  "fallback for all deterministic gates")
            return None
        length_mm = max(all_values)
        print(f"Container length extracted from PDF text: {length_mm}mm (all valid mm values found across pages, excluding COG: {sorted(set(all_values))})")
        return length_mm
    except Exception as e:
        print(f"WARNING: Container length extraction failed ({e}) - will use ratio-based fallback")
        return None


# ---------------------------------------------------------------------------
# Container boundary detection (deterministic, pixel-based)
# ---------------------------------------------------------------------------

def _is_saturated_color(rgb):
    r, g, b = rgb
    mx, mn = max(r, g, b), min(r, g, b)
    if mx < 60:
        return False
    if mx - mn < 35:
        return False
    return True


def detect_container_bbox(img, min_run_width=25, min_run_height=25):
    w, h = img.size
    px = img.convert("RGB").load()
    row_mask = bytearray(w * h)
    for y in range(h):
        run_start = None
        for x in range(w):
            sat = _is_saturated_color(px[x, y])
            if sat and run_start is None:
                run_start = x
            elif not sat and run_start is not None:
                if x - run_start >= min_run_width:
                    for xi in range(run_start, x):
                        row_mask[y * w + xi] = 1
                run_start = None
        if run_start is not None and w - run_start >= min_run_width:
            for xi in range(run_start, w):
                row_mask[y * w + xi] = 1
    minx, maxx, miny, maxy = w, 0, h, 0
    found = False
    for x in range(w):
        run_start = None
        for y in range(h):
            m = row_mask[y * w + x]
            if m and run_start is None:
                run_start = y
            elif not m and run_start is not None:
                if y - run_start >= min_run_height:
                    found = True
                    minx = min(minx, x)
                    maxx = max(maxx, x)
                    miny = min(miny, run_start)
                    maxy = max(maxy, y - 1)
                run_start = None
        if run_start is not None and h - run_start >= min_run_height:
            found = True
            minx = min(minx, x)
            maxx = max(maxx, x)
            miny = min(miny, run_start)
            maxy = max(maxy, h - 1)
    return (minx, miny, maxx, maxy) if found else None


def detect_container_bounds_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start=0):
    result = {"FRONT": None, "BACK": None}
    try:
        if layout == "TOP_BOTTOM":
            mid_y = crop_h // 2
            front_view_img = diagram_crop.crop((0, 0, crop_w, mid_y))
            back_view_img = diagram_crop.crop((0, mid_y, crop_w, crop_h))
            fb = detect_container_bbox(front_view_img)
            bb = detect_container_bbox(back_view_img)
            if fb:
                result["FRONT"] = {"xmin": fb[0], "ymin": fb[1] + crop_y_start, "xmax": fb[2], "ymax": fb[3] + crop_y_start}
            if bb:
                result["BACK"] = {"xmin": bb[0], "ymin": bb[1] + mid_y + crop_y_start, "xmax": bb[2], "ymax": bb[3] + mid_y + crop_y_start}
        else:
            half_w = crop_w // 2
            front_view_img = diagram_crop.crop((0, 0, half_w, crop_h))
            back_view_img = diagram_crop.crop((half_w, 0, crop_w, crop_h))
            fb = detect_container_bbox(front_view_img)
            bb = detect_container_bbox(back_view_img)
            if fb:
                result["FRONT"] = {"xmin": fb[0], "ymin": fb[1] + crop_y_start, "xmax": fb[2], "ymax": fb[3] + crop_y_start}
            if bb:
                result["BACK"] = {"xmin": bb[0] + half_w, "ymin": bb[1] + crop_y_start, "xmax": bb[2] + half_w, "ymax": bb[3] + crop_y_start}
        for view_name in ("FRONT", "BACK"):
            if result[view_name]:
                b = result[view_name]
                print(f"Container bounds detected for {view_name}: x=[{b['xmin']}-{b['xmax']}] y=[{b['ymin']}-{b['ymax']}]")
            else:
                print(f"WARNING: Could not detect container bounds for {view_name}")
        return result
    except Exception as e:
        print(f"WARNING: Container bounds detection failed ({e})")
        return {"FRONT": None, "BACK": None}


# ---------------------------------------------------------------------------
# Cargo extent detection - HSV saturation
# ---------------------------------------------------------------------------

def _is_arrow_color(rgb):
    r, g, b = rgb
    return (r >= 190) and (40 <= g <= 140) and (40 <= b <= 140) and (abs(g - b) <= 45) and (r - g >= 70) and (r - b >= 70)


def _hsv_saturation(rgb):
    r, g, b = rgb
    mx = max(r, g, b)
    mn = min(r, g, b)
    return (mx - mn) / mx if mx > 0 else 0


def _is_vivid_cargo_color(rgb, sat_thresh=0.75, min_brightness=50):
    if _is_arrow_color(rgb):
        return False
    r, g, b = rgb
    mx = max(r, g, b)
    if mx < min_brightness:
        return False
    return _hsv_saturation(rgb) >= sat_thresh


def detect_cargo_extent_bbox(img, sat_thresh=0.75, min_run_width=20, min_run_height=20):
    w, h = img.size
    px = img.convert("RGB").load()
    row_mask = bytearray(w * h)
    for y in range(h):
        run_start = None
        for x in range(w):
            is_cargo = _is_vivid_cargo_color(px[x, y], sat_thresh)
            if is_cargo and run_start is None:
                run_start = x
            elif not is_cargo and run_start is not None:
                if x - run_start >= min_run_width:
                    for xi in range(run_start, x):
                        row_mask[y * w + xi] = 1
                run_start = None
        if run_start is not None and w - run_start >= min_run_width:
            for xi in range(run_start, w):
                row_mask[y * w + xi] = 1
    minx, maxx, miny, maxy = w, 0, h, 0
    found = False
    for x in range(w):
        run_start = None
        for y in range(h):
            m = row_mask[y * w + x]
            if m and run_start is None:
                run_start = y
            elif not m and run_start is not None:
                if y - run_start >= min_run_height:
                    found = True
                    minx = min(minx, x)
                    maxx = max(maxx, x)
                    miny = min(miny, run_start)
                    maxy = max(maxy, y - 1)
                run_start = None
        if run_start is not None and h - run_start >= min_run_height:
            found = True
            minx = min(minx, x)
            maxx = max(maxx, x)
            miny = min(miny, run_start)
            maxy = max(maxy, h - 1)
    return (minx, miny, maxx, maxy) if found else None


def detect_cargo_extent_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start=0):
    result = {"FRONT": None, "BACK": None}
    try:
        if layout == "TOP_BOTTOM":
            mid_y = crop_h // 2
            front_view_img = diagram_crop.crop((0, 0, crop_w, mid_y))
            back_view_img = diagram_crop.crop((0, mid_y, crop_w, crop_h))
            fb = detect_cargo_extent_bbox(front_view_img)
            bb = detect_cargo_extent_bbox(back_view_img)
            if fb:
                result["FRONT"] = {"xmin": fb[0], "ymin": fb[1] + crop_y_start, "xmax": fb[2], "ymax": fb[3] + crop_y_start}
            if bb:
                result["BACK"] = {"xmin": bb[0], "ymin": bb[1] + mid_y + crop_y_start, "xmax": bb[2], "ymax": bb[3] + mid_y + crop_y_start}
        else:
            half_w = crop_w // 2
            front_view_img = diagram_crop.crop((0, 0, half_w, crop_h))
            back_view_img = diagram_crop.crop((half_w, 0, crop_w, crop_h))
            fb = detect_cargo_extent_bbox(front_view_img)
            bb = detect_cargo_extent_bbox(back_view_img)
            if fb:
                result["FRONT"] = {"xmin": fb[0], "ymin": fb[1] + crop_y_start, "xmax": fb[2], "ymax": fb[3] + crop_y_start}
            if bb:
                result["BACK"] = {"xmin": bb[0] + half_w, "ymin": bb[1] + crop_y_start, "xmax": bb[2] + half_w, "ymax": bb[3] + crop_y_start}
        for view_name in ("FRONT", "BACK"):
            if result[view_name]:
                b = result[view_name]
                print(f"Cargo extent detected for {view_name}: x=[{b['xmin']}-{b['xmax']}] y=[{b['ymin']}-{b['ymax']}]")
            else:
                print(f"WARNING: Could not detect cargo extent for {view_name}")
        return result
    except Exception as e:
        print(f"WARNING: Cargo extent detection failed ({e})")
        return {"FRONT": None, "BACK": None}


def _cargo_pixel_ratio_in_box(img, box):
    x0, y0, x1, y1 = [int(v) for v in box]
    x0 = max(0, x0); y0 = max(0, y0)
    x1 = min(img.width, x1); y1 = min(img.height, y1)
    if x1 <= x0 or y1 <= y0:
        return 0.0
    crop = img.crop((x0, y0, x1, y1))
    px = crop.convert("RGB").load()
    w, h = crop.size
    total = w * h
    if total == 0:
        return 0.0
    step = max(1, min(w, h) // 60)
    count = 0
    sampled = 0
    for yy in range(0, h, step):
        for xx in range(0, w, step):
            sampled += 1
            if _is_vivid_cargo_color(px[xx, yy]):
                count += 1
    return count / sampled if sampled > 0 else 0.0


def compute_empty_gap_pixels(view_container, view_cargo, rear_side, risk_type):
    if not view_container or not view_cargo:
        return None, None
    c_xmin, c_xmax = view_container["xmin"], view_container["xmax"]
    g_xmin, g_xmax = view_cargo["xmin"], view_cargo["xmax"]
    container_width_px = max(1, c_xmax - c_xmin)

    if risk_type == "FRONT_EMPTY_RISK":
        if rear_side == "LEFT":
            gap = max(0, c_xmax - g_xmax)
        else:
            gap = max(0, g_xmin - c_xmin)
    else:
        if rear_side == "LEFT":
            gap = max(0, g_xmin - c_xmin)
        else:
            gap = max(0, c_xmax - g_xmax)

    return gap, container_width_px


def compute_empty_gap_mm(view_container, view_cargo, rear_side, risk_type, container_length_mm):
    gap_px, container_width_px = compute_empty_gap_pixels(view_container, view_cargo, rear_side, risk_type)
    if gap_px is None or not container_length_mm or container_width_px is None or container_width_px <= 0:
        return None
    mm_per_px = container_length_mm / container_width_px
    return gap_px * mm_per_px


def compute_empty_gap_ratio(view_container, view_cargo, rear_side, risk_type):
    gap_px, container_width_px = compute_empty_gap_pixels(view_container, view_cargo, rear_side, risk_type)
    if gap_px is None or container_width_px is None or container_width_px <= 0:
        return None
    return gap_px / container_width_px


def compute_lateral_gap_pixels(view_container, view_cargo):
    if not view_container or not view_cargo:
        return None, None
    container_y_span = view_container["ymax"] - view_container["ymin"]
    cargo_y_span = view_cargo["ymax"] - view_cargo["ymin"]
    gap_y_px = max(0, container_y_span - cargo_y_span)
    container_x_span = max(1, view_container["xmax"] - view_container["xmin"])
    return gap_y_px, container_x_span


def compute_lateral_gap_mm(view_container, view_cargo, container_length_mm):
    gap_y_px, container_x_span = compute_lateral_gap_pixels(view_container, view_cargo)
    if gap_y_px is None or not container_length_mm or not container_x_span:
        return None
    mm_per_px = container_length_mm / container_x_span
    return gap_y_px * mm_per_px


def compute_lateral_gap_ratio(view_container, view_cargo):
    if not view_container or not view_cargo:
        return None
    container_y_span = view_container["ymax"] - view_container["ymin"]
    cargo_y_span = view_cargo["ymax"] - view_cargo["ymin"]
    if container_y_span <= 0:
        return None
    gap_y_px = max(0, container_y_span - cargo_y_span)
    return gap_y_px / container_y_span


# ---------------------------------------------------------------------------
# STEP_DOWN_RISK deterministic detection - height-profile discontinuity
# ---------------------------------------------------------------------------

def _detect_height_profile(view_img, x_start, x_end, y_start, y_end,
                            step=STEP_DOWN_PROFILE_STEP_PX, min_consistent_run=STEP_DOWN_MIN_CONSISTENT_RUN):
    px = view_img.convert("RGB").load()
    w, h = view_img.size
    x_start = max(0, int(x_start)); x_end = min(w, int(x_end))
    y_start = max(0, int(y_start)); y_end = min(h, int(y_end))
    profile = []
    for x in range(x_start, x_end, step):
        top_y = None
        y = y_start
        while y < y_end:
            if _is_vivid_cargo_color(px[x, y]):
                check_end = min(y + min_consistent_run, y_end)
                consistent_count = sum(1 for yy in range(y, check_end) if _is_vivid_cargo_color(px[x, yy]))
                if consistent_count >= min_consistent_run * 0.6:
                    top_y = y
                    break
            y += 1
        if top_y is not None:
            profile.append((x, top_y))
    return profile


def _detect_step_down_regions(view_img, x_start, x_end, y_start, y_end, container_ymax, container_y_span_px,
                               step=STEP_DOWN_PROFILE_STEP_PX, min_ratio=MIN_STEP_DOWN_RATIO,
                               min_flat_width_px=STEP_DOWN_MIN_FLAT_WIDTH_PX):
    """
    ตรวจจับความต่างระดับด้วยการหา 'จุดกระโดด' ระหว่างจุดที่ติดกันบน height-profile
    แล้วตรวจสอบแต่ละ segment ว่า 'เตี้ยกว่าเพื่อนบ้านซ้าย/ขวา' หรือไม่แยกกันเป็นอิสระ
    (v19 fix: ไม่ merge ตามระยะห่าง x อีกต่อไป เพราะทำให้เกิดบั๊กเมื่อเจอ pattern
    บันได 'เตี้ย->กลาง->สูง' ที่ 2 จุดเสี่ยงจริงถูกรวมเป็นกรอบเดียวผิดๆ)
    """
    profile = _detect_height_profile(view_img, x_start, x_end, y_start, y_end, step)
    if len(profile) < 4:
        return []
    threshold_px = container_y_span_px * min_ratio
    boundaries = []
    for i in range(len(profile) - 1):
        x0, y0 = profile[i]
        x1, y1 = profile[i + 1]
        delta = y1 - y0
        if abs(delta) >= threshold_px:
            boundaries.append(i)
    if not boundaries:
        return []

    segments = []
    start_idx = 0
    for b in boundaries:
        segments.append(profile[start_idx:b + 1])
        start_idx = b + 1
    segments.append(profile[start_idx:])

    seg_info = []
    for seg in segments:
        if len(seg) < 1:
            continue
        xs = [p[0] for p in seg]
        ys = [p[1] for p in seg]
        width = (max(xs) - min(xs)) if len(xs) > 1 else step
        seg_info.append({"x_min": min(xs), "x_max": max(xs), "y_avg": sum(ys) / len(ys), "width": width})
    seg_info.sort(key=lambda s: s["x_min"])

    risky_segments = []
    n = len(seg_info)
    for i in range(n):
        seg = seg_info[i]
        if seg["width"] < min_flat_width_px:
            continue
        is_risky = False
        max_ratio = 0
        if i > 0:
            left = seg_info[i - 1]
            diff = abs(seg["y_avg"] - left["y_avg"])
            ratio = diff / container_y_span_px if container_y_span_px > 0 else 0
            if seg["y_avg"] > left["y_avg"] and ratio >= min_ratio:
                is_risky = True
                max_ratio = max(max_ratio, ratio)
        if i < n - 1:
            right = seg_info[i + 1]
            diff = abs(seg["y_avg"] - right["y_avg"])
            ratio = diff / container_y_span_px if container_y_span_px > 0 else 0
            if seg["y_avg"] > right["y_avg"] and ratio >= min_ratio:
                is_risky = True
                max_ratio = max(max_ratio, ratio)
        if is_risky:
            risky_segments.append({
                "x_min": seg["x_min"], "x_max": seg["x_max"],
                "y_min": seg["y_avg"], "y_max": container_ymax,
                "ratio": max_ratio,
            })

    risky_segments.sort(key=lambda r: r["x_min"])
    return risky_segments


def detect_step_down_regions_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start, container_bounds, cargo_extent):
    results = {"FRONT": [], "BACK": []}
    for view in ("FRONT", "BACK"):
        cb = container_bounds.get(view)
        ce = cargo_extent.get(view)
        if not cb or not ce:
            continue
        if layout == "TOP_BOTTOM":
            mid_y = crop_h // 2
            if view == "FRONT":
                view_img = diagram_crop.crop((0, 0, crop_w, mid_y))
                origin_x, origin_y = 0, crop_y_start
            else:
                view_img = diagram_crop.crop((0, mid_y, crop_w, crop_h))
                origin_x, origin_y = 0, crop_y_start + mid_y
        else:
            half_w = crop_w // 2
            if view == "FRONT":
                view_img = diagram_crop.crop((0, 0, half_w, crop_h))
                origin_x, origin_y = 0, crop_y_start
            else:
                view_img = diagram_crop.crop((half_w, 0, crop_w, crop_h))
                origin_x, origin_y = half_w, crop_y_start

        cb_rel_ymin = cb["ymin"] - origin_y
        cb_rel_ymax = cb["ymax"] - origin_y
        ce_rel_xmin = ce["xmin"] - origin_x
        ce_rel_xmax = ce["xmax"] - origin_x
        container_y_span_px = cb_rel_ymax - cb_rel_ymin
        if container_y_span_px <= 0:
            continue

        try:
            regions = _detect_step_down_regions(view_img, ce_rel_xmin, ce_rel_xmax, cb_rel_ymin, cb_rel_ymax,
                                                  cb_rel_ymax, container_y_span_px)
        except Exception as e:
            print(f"WARNING: Step-down detection failed for {view} ({e})")
            regions = []

        for r in regions:
            abs_region = {
                "x_min": origin_x + r["x_min"], "x_max": origin_x + r["x_max"],
                "y_min": origin_y + r["y_min"], "y_max": origin_y + r["y_max"],
                "ratio": r["ratio"],
            }
            print(f"Deterministic STEP_DOWN_RISK candidate ({view}): "
                  f"x=[{abs_region['x_min']:.0f}-{abs_region['x_max']:.0f}] "
                  f"y=[{abs_region['y_min']:.0f}-{abs_region['y_max']:.0f}] "
                  f"height_diff_ratio={abs_region['ratio']*100:.1f}% (threshold={MIN_STEP_DOWN_RATIO*100:.1f}%)")
            results[view].append(abs_region)
        if not regions:
            print(f"Deterministic STEP_DOWN_RISK: no discontinuity found for {view} (container appears uniform)")
    return results


def _box_iou_absolute(box_a, box_b):
    ax0, ay0, ax1, ay1 = box_a
    bx0, by0, bx1, by1 = box_b
    ix0 = max(ax0, bx0); ix1 = min(ax1, bx1)
    iy0 = max(ay0, by0); iy1 = min(ay1, by1)
    iw = max(0.0, ix1 - ix0); ih = max(0.0, iy1 - iy0)
    inter = iw * ih
    area_a = max(1.0, (ax1 - ax0) * (ay1 - ay0))
    return inter / area_a


def _step_down_claim_overlaps_detection(box_2d, crop_w, crop_h, crop_y_start, regions_for_view,
                                          overlap_threshold=STEP_DOWN_CLAIM_OVERLAP_THRESHOLD):
    if not regions_for_view:
        print("STEP_DOWN_RISK claim REJECTED - no deterministic discontinuity detected for this view at all "
              "(container appears uniform based on pixel measurement)")
        return False
    try:
        ymin, xmin, ymax, xmax = map(float, box_2d)
        if max(ymin, xmin, ymax, xmax) <= 1.0:
            ymin, xmin, ymax, xmax = ymin * 1000, xmin * 1000, ymax * 1000, xmax * 1000
        abs_xmin = (xmin / 1000.0) * crop_w
        abs_xmax = (xmax / 1000.0) * crop_w
        abs_ymin = crop_y_start + (ymin / 1000.0) * crop_h
        abs_ymax = crop_y_start + (ymax / 1000.0) * crop_h
    except Exception:
        return True

    claim_box = (abs_xmin, abs_ymin, abs_xmax, abs_ymax)
    for region in regions_for_view:
        region_box = (region["x_min"], region["y_min"], region["x_max"], region["y_max"])
        overlap = _box_iou_absolute(claim_box, region_box)
        if overlap >= overlap_threshold:
            print(f"STEP_DOWN_RISK claim ACCEPTED - overlaps with detected discontinuity (overlap={overlap:.2f})")
            return True
    print(f"STEP_DOWN_RISK claim REJECTED - box_2d does not overlap with any detected discontinuity "
          f"(claim_box={claim_box}, available_regions={len(regions_for_view)})")
    return False


# ---------------------------------------------------------------------------
# PER-BOX SEGMENTATION (v22, ปรับปรุงใน v23/v23.1)
#
# แนวคิด: สร้าง "stack-box model" (แบบจำลองตั้ง-กล่อง) จากพิกเซลในแต่ละ view
# (FRONT/BACK) โดยแบ่งเป็น 2 ขั้นตอน:
#
#   ขั้น 1 (แบ่ง "ตั้ง"/stack ตามแนวกว้าง): แยก "กลุ่มก้อนสินค้าจริง" (physical
#   cluster) ก่อนด้วยช่องว่างจริง แล้วหาเส้นแบ่งบางๆ (เส้นขอบ/เส้นแบ่งสี) ภายในแต่ละ
#   กลุ่มเพื่อแยกตั้งที่วางชิดติดกัน (v23.1: ใช้ "local floor" ต่อคอลัมน์แทนเส้นตรง
#   ทั่วโลก - ดู comment ในหัวข้อ v23.1 ของ changelog ด้านบนของไฟล์)
#
#   ขั้น 2 (แบ่ง "กล่อง" ในแต่ละตั้งตามแนวสูง): ในแต่ละตั้ง สแกนจากพื้นขึ้นไปจนถึง
#   ยอดสินค้า หาเส้นแบ่งแนวนอนระหว่างกล่องแต่ละใบที่ซ้อนกัน จากนั้น "วัดขอบซ้าย/ขวา
#   จริง" ของกล่องแต่ละใบแยกกัน (ใช้ median-of-multiple-rows แทนแถวเดียว - v23.1)
#
# นำแบบจำลองนี้ไปใช้กับ 3 risk type ที่เดิมพึ่ง AI 100% ใน v21:
#   - OVERHANG_RISK: เทียบขอบซ้าย/ขวาของกล่องที่อยู่ติดกันในตั้งเดียวกัน (บน vs ล่าง)
#   - TALL_UNSTABLE_RISK: เทียบความสูงรวมทั้งตั้ง (ผลรวมทุกกล่อง) กับตั้งข้างเคียง
#     ทั้งสองด้าน (ต้องมีเพื่อนบ้านทั้ง 2 ฝั่ง - v23.1 fix) ถ้าสูงกว่าทั้งคู่มากพอ
#     (ไม่มีตั้งข้างค้ำยัน) = เสี่ยง
#   - REAR_LATERAL_IMBALANCE: เทียบความสูงรวมทั้งตั้งระหว่างตั้งที่อยู่ติดกันเฉพาะ
#     ในโซนประตูท้ายตู้
#
# ข้อจำกัดที่ทราบและยอมรับ (สำคัญ - ต้องแจ้งผู้ใช้งานเสมอ):
#   Occlusion ในมุมมอง isometric - หากตั้งเตี้ยถูกตั้งสูงบังจนไม่เห็นขอบเลยในภาพ 2D
#   projection นี้ pixel analysis จะ "มองไม่เห็น" ตั้งนั้นเลย (ไม่มีข้อมูลความลึก/
#   depth ให้ประมวลผล) เป็นข้อจำกัดพื้นฐานที่แก้ไม่ได้ด้วย pixel heuristic ล้วนๆ
#   (นี่คือสาเหตุที่ v21 เลือกพึ่ง AI สำหรับเคส AC03 pattern 2,2,1 ที่ตั้งเตี้ยถูกบัง)
#
#   ดังนั้นใช้กลไก deterministic แบบ "FORCE + VETO" เสริมคู่กับ AI (ไม่ใช่แทนที่
#   AI ทั้งหมด):
#     * OVERHANG_RISK, TALL_UNSTABLE_RISK: ใช้ FORCE (deterministic เจอแต่ AI บอก
#       SAFE -> บังคับขึ้น) + VETO (AI claim มาแต่ deterministic ไม่เจอจุดทับซ้อน
#       เลย -> ปฏิเสธ) เหมือนกลไกของ STEP_DOWN_RISK ที่มีอยู่แล้ว
#     * REAR_LATERAL_IMBALANCE: ใช้ FORCE เท่านั้น (ไม่ veto AI) เพราะ AI อาจเห็น
#       ตั้งที่ถูกบังซึ่ง pixel-based มองไม่เห็น - deterministic ทำหน้าที่เป็น
#       "second opinion" เสริมความมั่นใจ/จับเคสที่ AI พลาดเฉพาะกรณีที่ไม่มี occlusion
#
# ผ่านการทดสอบกับไฟล์ PDF จริง 17 ไฟล์แล้ว (v22.1 -> v23 -> v23.1) พบและแก้บั๊ก
# หลายจุด (ดู CHANGELOG ที่หัวไฟล์สำหรับรายละเอียดทั้งหมด)
# ---------------------------------------------------------------------------

BOX_BOUNDARY_MIN_DROP = 22            # ความสว่างต้องลดลงอย่างน้อยเท่านี้ถึงจะนับเป็น
                                       # ผู้สมัคร "เส้นแบ่งกล่อง" (0-255 scale)
BOX_BOUNDARY_MAX_THICKNESS_PX = 6      # เส้นแบ่งกล่องต้องบาง (<=6px) ถ้าหนากว่านี้
                                       # ถือว่าเป็นพื้นที่ว่างจริง ไม่ใช่แค่เส้นขอบ
STACK_MIN_WIDTH_PX = 18                # ความกว้างต่ำสุดที่เป็นไปได้ของ 1 ตั้ง
BOX_MIN_HEIGHT_PX = 4                  # ความสูงต่ำสุดสัมบูรณ์ (px) ของ 1 กล่อง
BOX_MIN_HEIGHT_RATIO = 0.12             # v23: เกณฑ์ความบางสัมพัทธ์ - segment ที่บาง
                                        # กว่า 12% ของความสูงตั้งทั้งหมด ถือว่าเป็น
                                        # สัญญาณรบกวน (เช่น เส้นข้อความ SKU) ไม่ใช่
                                        # รอยต่อกล่องจริง จะถูก "รวม" เข้ากับเพื่อนบ้าน

# v22.1 SAFETY GATE: เกณฑ์ความครอบคลุมขั้นต่ำ - ถ้าผลรวมความกว้างของ "ตั้ง" ที่
# ตรวจพบทั้งหมดในหนึ่ง view น้อยกว่าสัดส่วนนี้ของความกว้าง cargo_extent จริง ให้ถือว่า
# การแบ่งกล่อง (per-box segmentation) ใน view นั้น "ล้มเหลว/ไม่น่าเชื่อถือ" หากล้มเหลว
# จะข้ามการ FORCE/VETO ทั้งหมดสำหรับ view นั้น (fallback กลับไปพึ่ง AI 100% เหมือน v21)
STACK_COVERAGE_MIN_RATIO = 0.60

OVERHANG_MIN_RATIO = 0.20              # กล่องบนยื่นพ้นกล่องล่าง >=20% ของความกว้าง
                                       # กล่องล่าง จึงนับเป็นความเสี่ยง (v23: เพิ่มจาก
                                       # 0.12 หลังพบว่าการวัดขอบซ้าย/ขวายังมี noise
                                       # ตกค้างระดับ ~15-20px แม้ใช้ median-of-rows
                                       # แล้ว - ดู comment ใน detect_boxes_in_stack)
OVERHANG_MIN_ABS_PX = 20               # v23: ต้องยื่นออกมาอย่างน้อย 20px (สัมบูรณ์)
                                       # ด้วย ไม่ใช่แค่ผ่านเกณฑ์สัดส่วนอย่างเดียว เพื่อ
                                       # ป้องกัน false positive จาก noise ระดับพิกเซล
                                       # เดียวกับที่พบในกล่องแคบ (ความกว้างกล่องน้อย)
TALL_UNSTABLE_MIN_HEIGHT_RATIO = 0.35  # ตั้งนี้ต้องสูงกว่าตั้งข้างเคียง (ที่สูงสุด)
                                       # อย่างน้อย 35% ของความสูงตัวเอง
TALL_UNSTABLE_NEIGHBOR_MAX_RATIO = 0.65  # เพื่อนบ้านต้องเตี้ยกว่า <=65% ของตั้งนี้
                                       # ถึงจะนับว่า "ไม่มีตั้งข้างค้ำยัน"
LATERAL_IMBALANCE_MIN_RATIO = 0.40     # เกณฑ์ FORCE ของ REAR_LATERAL_IMBALANCE
                                       # (สอดคล้องกับเกณฑ์ 40-50% ใน AI prompt เดิม)


# ---------------------------------------------------------------------------
# FLOOR LINE DETECTION (v23)
#
# ปัญหาที่พบจากการทดสอบไฟล์จริง: ภาพ diagram เป็นมุมมอง ISOMETRIC ซึ่งกล้องมองจาก
# มุมของตู้คอนเทนเนอร์ ทำให้ "พื้นตู้" ที่ปรากฏในภาพไม่ใช่เส้นแนวนอน แต่เป็นรูปตัว
# "V" (piecewise-linear 2 ท่อน มีจุดยอดตรงกลาง แล้วลาดขึ้นทั้ง 2 ข้าง)
#
# หมายเหตุ (v23.1): ฟังก์ชันนี้ยังคงเก็บไว้ในโค้ด (ใช้ได้ผลดีกับ BACK view เป็นข้อมูล
# อ้างอิงเสริม) แต่ "ไม่ได้" ถูกเรียกใช้ในเส้นทางหลักของ per-box segmentation อีก
# ต่อไป (build_stack_box_model_per_view เปลี่ยนไปใช้ LOCAL FLOOR แทน) เนื่องจากพบว่า
# FRONT view มีขอบคาร์โก้เป็น "คลื่น" จริง (ไม่ใช่สัญญาณรบกวน) จากการจัดวางกล่องแบบ
# สลับตำแหน่งความลึก ทำให้แบบจำลองเส้นตรงทั่วโลกไม่แม่นยำพอ - ดู CHANGELOG v23.1
# ---------------------------------------------------------------------------

FLOOR_LINE_SAMPLE_STEP_PX = 3           # v23: ใช้ step ละเอียด (3px แทน 6px เดิม) หลัง
                                        # พบว่า step หยาบทำให้ slope ที่ฟิตได้คลาดเคลื่อน
                                        # จากค่าจริงมากขึ้น (ยืนยันด้วยการทดสอบไฟล์จริง)
FLOOR_LINE_SMOOTH_WINDOW = 5
FLOOR_LINE_MIN_R2 = 0.85
FLOOR_LINE_MIN_POINTS_PER_SIDE = 4
FLOOR_LINE_MIN_SLOPE_ABS = 0.15
FLOOR_LINE_MAX_SLOPE_ABS = 1.5
FLOOR_LINE_SEARCH_TOP_RATIO = 0.12    # หน้าต่างค้นหาด้านบน (สัดส่วนของความสูงตู้)
FLOOR_LINE_SEARCH_BOTTOM_RATIO = 0.08  # หน้าต่างค้นหาด้านล่าง (สัดส่วนของความสูงตู้)
FLOOR_LINE_SEARCH_TOP_MIN_PX = 25
FLOOR_LINE_SEARCH_BOTTOM_MIN_PX = 15


def _median_smooth_points(pts, window=FLOOR_LINE_SMOOTH_WINDOW):
    ys = [y for _, y in pts]
    n = len(ys)
    out = []
    half = window // 2
    for i in range(n):
        lo = max(0, i - half); hi = min(n, i + half + 1)
        w = sorted(ys[lo:hi])
        out.append(w[len(w) // 2])
    return [(pts[i][0], out[i]) for i in range(n)]


def _linreg_simple(pts):
    n = len(pts)
    if n < 2:
        return None
    sx = sum(x for x, y in pts); sy = sum(y for x, y in pts)
    sxx = sum(x * x for x, y in pts); sxy = sum(x * y for x, y in pts)
    denom = n * sxx - sx * sx
    if denom == 0:
        return None
    slope = (n * sxy - sx * sy) / denom
    intercept = (sy - slope * sx) / n
    return slope, intercept


def _linreg_r2(pts, slope, intercept):
    ys = [y for _, y in pts]
    mean_y = sum(ys) / len(ys)
    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in pts)
    if ss_tot == 0:
        return 1.0 if ss_res == 0 else 0.0
    return 1 - ss_res / ss_tot


def detect_floor_line_v_shape(view_img, x_min, x_max, container_ymax, container_height_px):
    """
    ตรวจจับพื้นตู้เป็นรูปตัว "V" (piecewise-linear 2 ท่อน) จากขอบล่างสุดของพิกเซล
    "โครงสร้างตู้" (saturated color) ตามแนวกว้าง [x_min, x_max) โดยค้นหาในหน้าต่างแคบ
    รอบๆ container_ymax ที่ตรวจพบไว้แล้ว (v23.1: ไม่ได้ใช้ในเส้นทางหลักอีกต่อไป
    ดู comment ด้านบน - เก็บไว้เป็นข้อมูลอ้างอิง)

    คืนค่า dict: {"valid": bool, "floor_y_fn": callable(x)->float, "peak_x":, ...}
    หากคุณภาพการฟิตต่ำเกินไป คืนค่า {"valid": False} ให้ผู้เรียกใช้ fallback เอง
    """
    px = view_img.convert("RGB").load()
    w, h = view_img.size
    x_min = max(0, int(x_min)); x_max = min(w, int(x_max))
    if x_max - x_min < FLOOR_LINE_MIN_POINTS_PER_SIDE * 2 * FLOOR_LINE_SAMPLE_STEP_PX:
        return {"valid": False}

    top_margin = max(FLOOR_LINE_SEARCH_TOP_MIN_PX, int(container_height_px * FLOOR_LINE_SEARCH_TOP_RATIO))
    bottom_margin = max(FLOOR_LINE_SEARCH_BOTTOM_MIN_PX, int(container_height_px * FLOOR_LINE_SEARCH_BOTTOM_RATIO))
    y_search_top = max(0, int(container_ymax) - top_margin)
    y_search_bottom = min(h, int(container_ymax) + bottom_margin)

    xs = list(range(x_min, x_max, FLOOR_LINE_SAMPLE_STEP_PX))
    raw_pts = []
    for x in xs:
        last_y = None
        for y in range(y_search_top, y_search_bottom):
            if _is_saturated_color(px[x, y]):
                last_y = y
        if last_y is not None:
            raw_pts.append((x, last_y))

    if len(raw_pts) < FLOOR_LINE_MIN_POINTS_PER_SIDE * 2:
        return {"valid": False}

    # v23.1 FIX (FRONT view head-wall noise): พบจากการ debug ไฟล์จริงว่าเมื่อคาร์โก้
    # บดบังพื้นตู้บางส่วน (โดยเฉพาะ FRONT view ที่คาร์โก้สูงและอยู่ใกล้ผนังหัวตู้) จะ
    # เกิด "ช่องว่าง" (gap) ในลำดับจุดข้อมูลตามแนว x จากนั้นอาจมีจุดกระจัดกระจายที่ไม่
    # เกี่ยวข้องกับพื้นจริง ปรากฏขึ้นอีกครั้งหลังช่องว่างนั้น ทำให้การฟิตเส้นตรงทั้งเส้น
    # เสียหาย (ค่า R2 ต่ำ) ทั้งที่ส่วนข้อมูลก่อนช่องว่างมีคุณภาพดีมาก
    # แก้ไข: ตัดข้อมูลเป็น "กลุ่มก้อนต่อเนื่อง" (cluster) ตามช่องว่างของค่า x แล้วเลือก
    # ใช้เฉพาะกลุ่มก้อนที่มีจำนวนจุดมากที่สุด
    max_gap_x = FLOOR_LINE_SAMPLE_STEP_PX * 2
    clusters = []
    cur_cluster = [raw_pts[0]]
    for i in range(1, len(raw_pts)):
        if raw_pts[i][0] - raw_pts[i - 1][0] <= max_gap_x:
            cur_cluster.append(raw_pts[i])
        else:
            clusters.append(cur_cluster)
            cur_cluster = [raw_pts[i]]
    clusters.append(cur_cluster)
    largest_cluster = max(clusters, key=len)
    if len(clusters) > 1:
        print(f"Floor line: found {len(clusters)} point cluster(s) (gaps from cargo occlusion), "
              f"using largest cluster with {len(largest_cluster)}/{len(raw_pts)} points "
              f"(x=[{largest_cluster[0][0]}-{largest_cluster[-1][0]}])")
    raw_pts = largest_cluster

    if len(raw_pts) < FLOOR_LINE_MIN_POINTS_PER_SIDE * 2:
        return {"valid": False}

    pts = _median_smooth_points(raw_pts)
    max_y = max(y for _, y in pts)

    # v23 fix: จุดยอดของ "V" มักไม่ใช่จุดแหลมเดี่ยว แต่เป็น "แนวราบสั้นๆ" (plateau)
    # หากตัด peak แบบ argmax เฉยๆ จุด plateau ที่เหลือจะถูกปนเข้าไปในฝั่งใดฝั่งหนึ่ง
    # ทำให้ slope ที่ฟิตได้เพี้ยนไปทางค่าน้อยกว่าจริง จึงต้องหา "พิสัยของ plateau"
    # (จุดทั้งหมดที่ y อยู่ใกล้ max_y ภายใน tolerance) แล้วตัดพิสัยนี้ออกจากทั้ง 2 ฝั่ง
    plateau_tol_px = 2
    plateau_indices = [i for i, (x, y) in enumerate(pts) if (max_y - y) <= plateau_tol_px]
    plateau_lo, plateau_hi = min(plateau_indices), max(plateau_indices)
    peak_x = pts[(plateau_lo + plateau_hi) // 2][0]
    peak_y = max_y

    left_pts = pts[:plateau_lo]
    right_pts = pts[plateau_hi + 1:]
    if len(left_pts) < FLOOR_LINE_MIN_POINTS_PER_SIDE or len(right_pts) < FLOOR_LINE_MIN_POINTS_PER_SIDE:
        return {"valid": False}

    left_fit = _linreg_simple(left_pts)
    right_fit = _linreg_simple(right_pts)
    if not left_fit or not right_fit:
        return {"valid": False}

    left_r2 = _linreg_r2(left_pts, *left_fit)
    right_r2 = _linreg_r2(right_pts, *right_fit)
    if left_r2 < FLOOR_LINE_MIN_R2 or right_r2 < FLOOR_LINE_MIN_R2:
        print(f"Floor line detection REJECTED (low R2: left={left_r2:.2f}, right={right_r2:.2f}, "
              f"threshold={FLOOR_LINE_MIN_R2}) - falling back to flat floor_y")
        return {"valid": False}

    ls, li = left_fit
    rs, ri = right_fit
    if not (FLOOR_LINE_MIN_SLOPE_ABS <= abs(ls) <= FLOOR_LINE_MAX_SLOPE_ABS):
        return {"valid": False}
    if not (FLOOR_LINE_MIN_SLOPE_ABS <= abs(rs) <= FLOOR_LINE_MAX_SLOPE_ABS):
        return {"valid": False}
    if not (ls > 0 and rs < 0):
        return {"valid": False}

    def floor_y_fn(x):
        if x <= peak_x:
            return ls * x + li
        return rs * x + ri

    print(f"Floor line V-shape detected: peak=({peak_x},{peak_y:.0f}) "
          f"left_slope={ls:.3f}(r2={left_r2:.2f}) right_slope={rs:.3f}(r2={right_r2:.2f})")
    return {"valid": True, "peak_x": peak_x, "peak_y": peak_y,
            "left_slope": ls, "right_slope": rs, "floor_y_fn": floor_y_fn}


def _make_flat_floor_fn(floor_y_scalar):
    """Fallback: floor_y คงที่ (flat) ไม่ขึ้นกับ x - เก็บไว้เป็นข้อมูลอ้างอิง"""
    return lambda x: floor_y_scalar


def _luminance(rgb):
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


def _find_dark_boundary_lines_1d(profile, min_drop=BOX_BOUNDARY_MIN_DROP, max_thickness=BOX_BOUNDARY_MAX_THICKNESS_PX):
    """
    รับ list ของค่าความสว่างเฉลี่ยตามตำแหน่ง (index = แถว/คอลัมน์ตามลำดับ) แล้วหา
    "ร่อง" (dip) ที่ความสว่างลดฮวบแล้วกลับขึ้นภายในระยะสั้นๆ (<=max_thickness) ซึ่ง
    บ่งบอกว่าเป็นเส้นขอบบางๆ ระหว่างกล่อง 2 ใบ (ไม่ใช่พื้นที่ว่างจริงที่ความสว่างจะ
    เปลี่ยนแปลงต่อเนื่องเป็นระยะยาว ไม่ใช่แค่ dip แคบๆ)
    คืนค่า index ตำแหน่งกึ่งกลางของแต่ละเส้นแบ่งที่เจอ (relative ต่อ profile)
    """
    n = len(profile)
    boundaries = []
    i = 1
    while i < n - 1:
        base = profile[i - 1]
        if base - profile[i] >= min_drop:
            j = i
            while j < n and (base - profile[j]) >= min_drop * 0.5:
                j += 1
            thickness = j - i
            if 1 <= thickness <= max_thickness:
                boundaries.append((i + j) // 2)
            i = j
        else:
            i += 1
    return boundaries


def _local_bottom_cargo_y(px, x, y_top, y_bot):
    """หาตำแหน่ง y ของพิกเซลคาร์โก้ที่อยู่ล่างสุด (ใกล้พื้นที่สุด) ในคอลัมน์ x เดียว
    ภายในช่วง [y_top, y_bot) - ใช้เป็น "พื้นเฉพาะจุด" (local floor) ที่คำนวณจาก
    พิกเซลจริงโดยตรง แทนที่จะพึ่งพาแบบจำลองเส้นตรงทั่วโลก (global floor line)"""
    last_y = None
    for y in range(y_top, y_bot):
        if _is_vivid_cargo_color(px[x, y]):
            last_y = y
    return last_y


def _find_cargo_present_clusters(px, cargo_xmin, cargo_xmax, y_search_top, y_search_bottom):
    """
    หา "กลุ่มก้อนสินค้าจริง" (physical cluster) ตามแนว x โดยตรวจสอบว่ามีพิกเซล
    คาร์โก้อยู่ที่ใดก็ได้ภายในช่วง y ที่กำหนด (y_search_top, y_search_bottom) ซึ่ง
    ควรครอบคลุมทั้งช่วงความสูงที่คาร์โก้อาจปรากฏ (v23.1 FIX: เปลี่ยนจากการใช้แถบ
    แคบใกล้ floor_y_fn(x) เป็นการตรวจสอบ "ทั้งช่วง" แทน เนื่องจากพบจากการทดสอบไฟล์
    จริงว่าขอบล่างของคาร์โก้มีลักษณะเป็น "คลื่น" จริง ไม่ใช่เส้นตรงเดียว - เกิดจาก
    การจัดวางกล่องแบบสลับตำแหน่งความลึก (checker pattern เพื่อความมั่นคง) ทำให้แถบ
    แคบที่อิงกับเส้นตรงทั่วโลกพลาดคาร์โก้จริงไปมาก คำถามว่า "มีคาร์โก้ในคอลัมน์นี้
    หรือไม่" ไม่จำเป็นต้องพึ่งพาตำแหน่งพื้นที่แม่นยำเลย จึงปลอดภัยกว่ามาก)
    เว้นช่องว่างแท้จริง (ไม่มีสินค้าเลยตลอดคอลัมน์) ที่กว้างเกิน tolerance เป็นตัวแบ่ง
    """
    max_gap_tolerance_px = 3
    cargo_present = []
    for x in range(cargo_xmin, cargo_xmax):
        present = any(_is_vivid_cargo_color(px[x, y]) for y in range(y_search_top, y_search_bottom))
        cargo_present.append(present)

    clusters = []
    n = len(cargo_present)
    i = 0
    cluster_start = None
    while i < n:
        if cargo_present[i]:
            if cluster_start is None:
                cluster_start = i
            i += 1
        else:
            if cluster_start is None:
                i += 1
                continue
            gap_start = i
            while i < n and not cargo_present[i]:
                i += 1
            gap_width = i - gap_start
            if gap_width > max_gap_tolerance_px:
                clusters.append((cluster_start, gap_start))
                cluster_start = None
            # ถ้า gap เล็กกว่า tolerance ให้ถือว่ายังเป็นก้อนเดียวกัน (ข้าม gap ไปต่อ)
    if cluster_start is not None:
        clusters.append((cluster_start, n))
    return [(cargo_xmin + a, cargo_xmin + b) for a, b in clusters]


def detect_stack_columns(view_img, cargo_xmin, cargo_xmax, y_search_top, y_search_bottom, sample_band_px=6):
    """
    แบ่งความกว้างของสินค้า [cargo_xmin, cargo_xmax) ออกเป็น "ตั้ง" (stack) ด้วย 2
    ขั้นตอน:
      1) แยก "กลุ่มก้อนสินค้าจริง" (physical cluster) ก่อน โดยใช้ช่องว่างจริง (ไม่มี
         สินค้าเลย) เป็นตัวแบ่ง - ครอบคลุมกรณีตั้งที่วางห่างกันจริง (มี gap มองเห็น
         ได้ชัดเจน)
      2) ในแต่ละกลุ่มก้อน สแกนหาเส้นแบ่งบางๆ (เส้นขอบ/เส้นแบ่งสี) เพิ่มเติม เพื่อแยก
         ตั้งที่วางชิดติดกันสนิท (ไม่มีช่องว่างจริง แต่มีเส้นขอบคั่น) ออกจากกัน โดยใช้
         "พื้นเฉพาะจุด" (local floor) ของแต่ละคอลัมน์ที่คำนวณจากพิกเซลจริงโดยตรง
         (ไม่ใช่เส้นตรงทั่วโลก) เพื่อทนทานต่อ "คลื่น" ของขอบคาร์โก้จากการจัดวางแบบ
         สลับตำแหน่งความลึก (v23.1 - ดู comment ใน _find_cargo_present_clusters)
    """
    px = view_img.convert("RGB").load()
    w, h = view_img.size
    cargo_xmin = max(0, int(cargo_xmin))
    cargo_xmax = min(w, int(cargo_xmax))
    y_search_top = max(0, int(y_search_top))
    y_search_bottom = min(h, int(y_search_bottom))
    if cargo_xmax <= cargo_xmin or y_search_bottom <= y_search_top:
        return []

    clusters = _find_cargo_present_clusters(px, cargo_xmin, cargo_xmax, y_search_top, y_search_bottom)
    if not clusters:
        return [(cargo_xmin, cargo_xmax)]

    stacks = []
    for (cx0, cx1) in clusters:
        if cx1 - cx0 < STACK_MIN_WIDTH_PX:
            continue
        profile = []
        for x in range(cx0, cx1):
            local_floor = _local_bottom_cargo_y(px, x, y_search_top, y_search_bottom)
            if local_floor is None:
                profile.append(255.0)  # ไม่มีคาร์โก้ในคอลัมน์นี้ - ถือเป็นค่าสว่าง (background)
                continue
            y1 = local_floor
            y0 = max(0, y1 - sample_band_px)
            vals = [_luminance(px[x, y]) for y in range(y0, y1)]
            profile.append(sum(vals) / len(vals) if vals else 0)
        boundaries_rel = _find_dark_boundary_lines_1d(profile)
        boundaries_abs = sorted(cx0 + b for b in boundaries_rel)
        edges = [cx0] + boundaries_abs + [cx1]
        for i in range(len(edges) - 1):
            x0, x1 = edges[i], edges[i + 1]
            if x1 - x0 >= STACK_MIN_WIDTH_PX:
                stacks.append((x0, x1))
    if not stacks:
        stacks = [(cargo_xmin, cargo_xmax)]
    return stacks


def _merge_thin_edge_segments(edges, min_height):
    """
    รวม (merge) ขอบเขต (boundary) ที่สร้าง segment บางเกินไป (< min_height) เข้ากับ
    เพื่อนบ้านที่เล็กกว่า โดยลบขอบเขตที่เกี่ยวข้องออก ทำซ้ำจนไม่มี segment บางเกินไป
    เหลืออยู่ (หรือเหลือแค่ 1 segment) ป้องกันไม่ให้ boundary ปลอม (เช่น เส้นข้อความ
    SKU) แยกกล่องจริง 2 ใบออกจากกันผิดพลาด - ดู comment ใน detect_boxes_in_stack
    """
    edges = list(edges)
    changed = True
    while changed and len(edges) > 2:
        changed = False
        for i in range(len(edges) - 1):
            if edges[i + 1] - edges[i] < min_height:
                if i == 0:
                    del edges[i + 1]
                elif i == len(edges) - 2:
                    del edges[i]
                else:
                    left_seg = edges[i] - edges[i - 1]
                    right_seg = edges[i + 2] - edges[i + 1]
                    if left_seg <= right_seg:
                        del edges[i]
                    else:
                        del edges[i + 1]
                changed = True
                break
    return edges


def _seed_extent_in_range(px, x0, x1, y, step=1):
    """หาขอบซ้าย/ขวาสุดของพิกเซลสินค้าภายในช่วง [x0,x1) แถวเดียว (y คงที่)"""
    left, right = None, None
    for x in range(x0, x1, step):
        if _is_vivid_cargo_color(px[x, y]):
            if left is None:
                left = x
            right = x
    return left, right


def _median_of(values):
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _extend_edge_contiguous(px, seed_x, direction, y, img_w, limit_px, max_pixel_gap=2):
    """
    ขยายขอบเขตออกจากตำแหน่ง seed_x ไปทางซ้าย (direction=-1) หรือขวา (direction=+1)
    แบบ "ต่อเนื่อง" เท่านั้น (ยอมรับช่องว่างเล็กๆ จาก anti-aliasing ไม่เกิน
    max_pixel_gap พิกเซล) เพื่อป้องกันการกระโดดข้ามช่องว่างจริงไปจับสินค้าของตั้ง/
    กล่องข้างเคียงที่ไม่เกี่ยวข้องมาผิดพลาด (บั๊กที่พบระหว่างการทดสอบ)

    v23.1 FIX: คืนค่า (result, hit_limit) แทนแค่ result เดี่ยวๆ - hit_limit=True หาก
    การขยายไปถึง limit_px พอดีโดยไม่เจอขอบเขตจริง (ไม่ใช่หยุดเพราะเจอ gap) ซึ่งบ่งชี้
    ว่าอาจกำลัง "ขยายข้ามไปติดกับตั้ง/กล่องข้างเคียงที่มีสีเดียวกันสนิท ไม่มีเส้นแบ่ง"
    (พบจากการทดสอบไฟล์จริง AC09-02: กล่อง 2 ตั้งที่ติดกันสีเดียวกันในแถวเดียวกัน ทำให้
    การขยายวิ่งไปจนเกือบสุด limit_px ทั้ง 2 ด้าน แล้วเกิด OVERHANG_RISK ปลอมจากการ
    เปรียบเทียบกับกล่องล่างที่แคบกว่า) ผู้เรียกใช้ควรทิ้งค่าที่ hit_limit=True ออกจาก
    การคำนวณค่ามัธยฐาน เพราะถือว่าไม่น่าเชื่อถือ
    """
    result = seed_x
    x = seed_x + direction
    gap = 0
    steps = 0
    hit_limit = False
    while 0 <= x < img_w and steps < limit_px:
        if _is_vivid_cargo_color(px[x, y]):
            result = x
            gap = 0
        else:
            gap += 1
            if gap > max_pixel_gap:
                break
        x += direction
        steps += 1
    else:
        # while loop สิ้นสุดเพราะ steps>=limit_px (ไม่ใช่ break จาก gap) - หมายความว่า
        # ยังพบ cargo ต่อเนื่องอยู่จนถึงขอบเขตการค้นหา ไม่ได้เจอขอบเขตจริงของกล่อง
        if steps >= limit_px:
            hit_limit = True
    return result, hit_limit


def detect_boxes_in_stack(view_img, x0, x1, y_search_top, y_search_bottom, search_expand_px=25):
    """
    ในตั้ง [x0,x1) สแกนจากยอดสินค้าลงมาถึงพื้นตู้ หาเส้นแบ่งแนวนอนระหว่าง
    กล่องแต่ละใบที่ซ้อนกัน แล้ววัด "ขอบซ้าย/ขวาจริง" ของกล่องแต่ละใบแยกกัน โดยเริ่ม
    จาก seed ภายในช่วง [x0,x1) เดิมก่อน แล้วขยายออกทั้ง 2 ข้างแบบ "ต่อเนื่อง"
    (contiguous) เท่านั้น เพื่อจับ OVERHANG ที่กล่องยื่นออกนอกขอบตั้งเดิมได้ โดยไม่
    กระโดดข้ามช่องว่างจริงไปจับสินค้าของตั้งข้างเคียงมาผิดพลาด
    คืนค่า list ของกล่อง เรียงจาก "บนสุด" (ยอด, y น้อย) ไป "ล่างสุด" (พื้น, y มาก)

    v23.1 FIX: เดิมใช้ floor_y_fn(mid_x) จากแบบจำลองเส้นตรงทั่วโลก (global V-shape)
    เป็นตัวกำหนด floor_y ของทั้งตั้ง แต่พบจากการทดสอบไฟล์จริงว่าขอบล่างคาร์โก้มี
    ลักษณะเป็น "คลื่น" จริง (จากการจัดวางกล่องสลับตำแหน่งความลึกเพื่อความมั่นคง) ทำให้
    ตำแหน่งจากเส้นตรงทั่วโลกคลาดเคลื่อนจากตำแหน่งจริงของแต่ละตั้งได้มาก (โดยเฉพาะ
    FRONT view) จึงเปลี่ยนมาคำนวณ "พื้นเฉพาะของตั้งนี้" จากพิกเซลคาร์โก้จริงในช่วง
    x0:x1 โดยตรง (หาค่า y ล่างสุดที่พบคาร์โก้ ภายในช่วง y_search_top:y_search_bottom
    ที่กำหนดมาอย่างกว้างขวางพอ) ทำให้ทนทานต่อ "คลื่น" ของตำแหน่งความลึกได้เอง
    """
    px = view_img.convert("RGB").load()
    w, h = view_img.size
    x0 = max(0, int(x0)); x1 = min(w, int(x1))
    y_search_top = max(0, int(y_search_top)); y_search_bottom = min(h, int(y_search_bottom))
    if x1 <= x0 or y_search_bottom <= y_search_top:
        return []

    # คำนวณ "พื้นเฉพาะของตั้งนี้" จากค่ามัธยฐานของตำแหน่ง local floor ที่พบในแต่ละ
    # คอลัมน์ภายในช่วง x0:x1 (median แทน max เพื่อลดผลกระทบจาก outlier เดี่ยวๆ เช่น
    # SKU text ที่บังเอิญยื่นต่ำกว่าปกติในบางคอลัมน์)
    local_floors = []
    for x in range(x0, x1, max(1, (x1 - x0) // 20)):
        lf = _local_bottom_cargo_y(px, x, y_search_top, y_search_bottom)
        if lf is not None:
            local_floors.append(lf)
    if not local_floors:
        return []
    floor_y = int(round(_median_of(local_floors)))
    floor_y = max(1, min(h, floor_y))

    top_y = None
    for y in range(0, floor_y):
        row_has_cargo = any(_is_vivid_cargo_color(px[x, y]) for x in range(x0, x1, max(1, (x1 - x0) // 12)))
        if row_has_cargo:
            top_y = y
            break
    if top_y is None:
        return []

    profile = []
    for y in range(top_y, floor_y):
        vals = [_luminance(px[x, y]) for x in range(x0, x1, 2)]
        profile.append(sum(vals) / len(vals) if vals else 0)
    boundaries_rel = _find_dark_boundary_lines_1d(profile)
    boundaries_abs = sorted(top_y + b for b in boundaries_rel)
    edges = [top_y] + boundaries_abs + [floor_y]

    # v23 fix: เดิม (v22) แค่ "ข้าม" (skip) segment ที่บางเกินไปโดยไม่รวมขอบเขตเข้ากับ
    # เพื่อนบ้าน ทำให้ boundary ปลอม (มักเกิดจากข้อความ SKU/เส้นบางๆ ที่ไม่ใช่รอยต่อ
    # กล่องจริง) ยังคงแยกกล่องจริง 2 ใบออกจากกันผิดพลาด โดยกล่องที่อยู่ติดกับ segment
    # บางนั้นจะยังคงใช้ขอบเขตของตัวเองที่ (อาจ) วัดความกว้างผิดในบริเวณที่ถูกบัง/ปนกับ
    # ข้อความ ทำให้เกิด OVERHANG_RISK ปลอม (พบจากการทดสอบไฟล์จริง AC09-02: segment
    # สูงเพียง 12px ถูกนับเป็นกล่องแยก ทำให้วัดความกว้างผิดพลาดจนดูเหมือนยื่นออกมา)
    # แก้ไข: "รวม" (merge) boundary ที่สร้าง segment บางเกินไปเข้ากับเพื่อนบ้านที่เล็ก
    # กว่าแทนที่จะแค่ข้าม โดยเกณฑ์ความบางคิดเป็นสัดส่วนของความสูงตั้งทั้งหมด (ไม่ใช่
    # ค่าคงที่ตายตัว) เพื่อให้ปรับตามขนาด/DPI ของภาพที่ต่างกันได้
    stack_total_height = max(1, floor_y - top_y)
    min_segment_height = max(BOX_MIN_HEIGHT_PX, int(stack_total_height * BOX_MIN_HEIGHT_RATIO))
    edges = _merge_thin_edge_segments(edges, min_segment_height)

    boxes = []
    for i in range(len(edges) - 1):
        y0b, y1b = edges[i], edges[i + 1]
        if y1b - y0b < BOX_MIN_HEIGHT_PX:
            continue

        # v23 fix: เดิม (v22) วัดขอบซ้าย/ขวาจาก "แถวเดียว" (mid_y) เพียงแถวเดียว ซึ่ง
        # เสี่ยงถูกรบกวนจากข้อความ SKU/label ที่ปนอยู่บนกล่อง (ตัวอักษรมักไม่ใช่สี
        # cargo ที่ชัดเจน ทำให้ _extend_edge_contiguous หยุดขยายก่อนถึงขอบจริงถ้าบังเอิญ
        # ตัวอักษรอยู่ตรงแถวที่สุ่มวัดพอดี) พบจากการทดสอบไฟล์จริง (AC09-02) ว่าทำให้
        # เกิด OVERHANG_RISK ปลอมจากกล่องที่จัดเรียงตรงกันจริงๆ แต่วัดขอบผิดพลาด
        # แก้ไข: สุ่มวัดหลายแถว (กระจายในช่วงกลาง 60% ของความสูง segment เพื่อหลีกเลี่ยง
        # ขอบบน/ล่างที่อาจเป็นรอยต่อ) แล้วใช้ค่ามัธยฐาน (median) ของขอบซ้าย/ขวาที่วัดได้
        # เพื่อลดผลกระทบจากข้อความ/สัญญาณรบกวนเฉพาะจุด
        seg_height = y1b - y0b
        pad = max(1, int(seg_height * 0.2))
        sample_y0 = y0b + pad
        sample_y1 = y1b - pad
        if sample_y1 <= sample_y0:
            sample_ys = [(y0b + y1b) // 2]
        else:
            n_samples = min(7, max(3, seg_height // 15))
            step_y = max(1, (sample_y1 - sample_y0) // max(1, n_samples - 1))
            sample_ys = list(range(sample_y0, sample_y1 + 1, step_y))

        # v23.1 FIX: ทิ้งค่าที่ hit_limit=True (การขยายไปจนสุด search_expand_px โดยไม่
        # เจอขอบเขตจริง) ออกจากการคำนวณค่ามัธยฐาน เพราะบ่งชี้ว่าอาจกำลัง "ขยายข้ามไป
        # ติดกับตั้ง/กล่องข้างเคียงที่มีสีเดียวกันสนิท ไม่มีเส้นแบ่ง" (พบจากการทดสอบ
        # ไฟล์จริง AC09-02 - ดู comment ใน _extend_edge_contiguous)
        left_measurements, right_measurements = [], []
        for sy in sample_ys:
            seed_left, seed_right = _seed_extent_in_range(px, x0, x1, sy)
            if seed_left is None:
                continue
            l, l_hit_limit = _extend_edge_contiguous(px, seed_left, -1, sy, w, search_expand_px)
            r, r_hit_limit = _extend_edge_contiguous(px, seed_right, +1, sy, w, search_expand_px)
            if not l_hit_limit:
                left_measurements.append(l)
            if not r_hit_limit:
                right_measurements.append(r)

        # v23.1 FIX (เพิ่มเติม): เกณฑ์ "จำนวนตัวอย่างที่เชื่อถือได้ขั้นต่ำ" - หากจำนวน
        # ตัวอย่างที่ไม่ hit_limit เหลือน้อยกว่าครึ่งหนึ่งของจำนวนตัวอย่างทั้งหมด แสดง
        # ว่าขอบด้านนั้นมี "ความไม่แน่นอนสูง" (ส่วนใหญ่ชนกำแพง limit ซ้ำๆ) ไม่ควรเชื่อ
        # ค่ามัธยฐานจากตัวอย่างเพียงหยิบมือที่เหลือ - ให้ใช้ขอบเขตของตั้งเดิม (x0/x1)
        # แทนอย่างระมัดระวัง (พบจากการทดสอบไฟล์จริง AC09-02: เหลือตัวอย่างที่เชื่อถือ
        # ได้เพียง 1 จาก 7 ตัวอย่างฝั่งขวา ซึ่งไม่เพียงพอจะสรุปว่ากล่องยื่นออกจริง)
        min_valid_samples = max(1, len(sample_ys) // 2)
        if len(left_measurements) < min_valid_samples:
            left = x0
        else:
            left = _median_of(left_measurements)
        if len(right_measurements) < min_valid_samples:
            right = x1
        else:
            right = _median_of(right_measurements)
        boxes.append({"y_min": y0b, "y_max": y1b, "x_left": left, "x_right": right, "height_px": y1b - y0b})
    return boxes


def build_stack_box_model_for_view(view_img, y_search_top, y_search_bottom, cargo_xmin, cargo_xmax):
    stack_ranges = detect_stack_columns(view_img, cargo_xmin, cargo_xmax, y_search_top, y_search_bottom)
    stacks = []
    for (x0, x1) in stack_ranges:
        boxes = detect_boxes_in_stack(view_img, x0, x1, y_search_top, y_search_bottom)
        if boxes:
            top_y = boxes[0]["y_min"]
            floor_y_here = boxes[-1]["y_max"]
        else:
            top_y = y_search_bottom
            floor_y_here = y_search_bottom
        stacks.append({"x0": x0, "x1": x1, "top_y": top_y, "floor_y": floor_y_here, "boxes": boxes})
    stacks.sort(key=lambda s: s["x0"])
    return stacks


def build_stack_box_model_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start, container_bounds, cargo_extent):
    """
    สร้าง stack-box model สำหรับ FRONT และ BACK view โดยพิกัดผลลัพธ์ (x0,x1,top_y,
    floor_y และพิกัดกล่องแต่ละใบ) เป็นพิกัด "สัมบูรณ์บนภาพเต็ม" (เช่นเดียวกับ
    container_bounds/cargo_extent ที่คำนวณไว้ก่อนหน้า) เพื่อให้นำไปวาดกรอบและเทียบ
    ตำแหน่งกับผลจาก AI ได้โดยตรง

    v23.1 FIX (FRONT view head-wall/wave noise): เดิม (v23) ใช้ detect_floor_line_v_shape()
    สร้างแบบจำลอง "เส้นตรงทั่วโลก" (global piecewise-linear V-shape) เพื่อประมาณตำแหน่ง
    พื้นตู้ - ใช้ได้ผลดีกับ BACK view แต่ล้มเหลวกับ FRONT view เพราะพบจากการทดสอบไฟล์
    จริงว่าขอบล่างของคาร์โก้ใน FRONT view มีลักษณะเป็น "คลื่น" จริง (ไม่ใช่สัญญาณรบกวน)
    เกิดจากการจัดวางกล่องแบบสลับตำแหน่งความลึกเพื่อความมั่นคง (แต่ละตั้งมีตำแหน่งความ
    ลึกต่างกัน ทำให้ตำแหน่งขอบล่างที่มองเห็นในภาพ isometric ต่างกันไปด้วย) ทำให้เส้นตรง
    ทั่วโลกเส้นเดียวไม่สามารถแทนตำแหน่งพื้นจริงของทุกตั้งได้แม่นยำพอ

    จึงเปลี่ยนแนวทางเป็น "LOCAL FLOOR" - ให้แต่ละคอลัมน์/แต่ละตั้งคำนวณตำแหน่งพื้นของ
    ตัวเองจากพิกเซลคาร์โก้จริงในบริเวณนั้นโดยตรง (ดู _local_bottom_cargo_y,
    detect_boxes_in_stack) แทนที่จะพึ่งพาแบบจำลองเส้นตรงทั่วโลก วิธีนี้ทนทานต่อคลื่น
    ของตำแหน่งความลึกได้เองตามธรรมชาติ โดยไม่ต้องพยายามสร้างแบบจำลองเรขาคณิตที่ซับซ้อน
    ขึ้น ฟังก์ชัน detect_floor_line_v_shape() ยังคงเก็บไว้ในโค้ด (ใช้ได้ผลดีกับ BACK
    view เป็นข้อมูลอ้างอิงเสริม) แต่ไม่ใช่ตัวตัดสินหลักสำหรับการแบ่งตั้ง/กล่องอีกต่อไป

    ใช้ y_search_top = cargo_extent['ymin'] (ขอบบนสุดของคาร์โก้ทั้งหมด) และ
    y_search_bottom = max(cargo_extent['ymax'], container_bounds['ymax']) + margin
    เป็นขอบเขตการค้นหาที่กว้างพอจะครอบคลุมคลื่นของตำแหน่งความลึกทั้งหมด

    KNOWN LIMITATION ที่ยังคงเหลืออยู่: ยังมี "coverage sanity check" ด้านล่างเป็นชั้น
    ป้องกันสุดท้าย เผื่อกรณีที่ตั้ง (stack) ที่ตรวจพบครอบคลุมพื้นที่น้อยผิดปกติ (เช่น
    SKU สีเดียวกันหลายกล่องติดกันไม่มีเส้นแบ่งให้เห็นเลย) - ถ้าความกว้างรวมของตั้งที่
    ตรวจพบทั้งหมดน้อยกว่า STACK_COVERAGE_MIN_RATIO ของความกว้าง cargo_extent จริง จะ
    ทิ้งผลลัพธ์ของ view นั้น (fallback กลับไปพึ่ง AI 100% เหมือน v21)
    """
    result = {"FRONT": [], "BACK": []}
    for view in ("FRONT", "BACK"):
        cb = container_bounds.get(view)
        ce = cargo_extent.get(view)
        if not cb or not ce:
            print(f"WARNING: Per-box segmentation skipped for {view} (missing container/cargo bounds)")
            continue
        if layout == "TOP_BOTTOM":
            mid_y = crop_h // 2
            if view == "FRONT":
                view_img = diagram_crop.crop((0, 0, crop_w, mid_y))
                origin_x, origin_y = 0, crop_y_start
            else:
                view_img = diagram_crop.crop((0, mid_y, crop_w, crop_h))
                origin_x, origin_y = 0, crop_y_start + mid_y
        else:
            half_w = crop_w // 2
            if view == "FRONT":
                view_img = diagram_crop.crop((0, 0, half_w, crop_h))
                origin_x, origin_y = 0, crop_y_start
            else:
                view_img = diagram_crop.crop((half_w, 0, crop_w, crop_h))
                origin_x, origin_y = half_w, crop_y_start

        rel_cargo_xmin = ce["xmin"] - origin_x
        rel_cargo_xmax = ce["xmax"] - origin_x
        cargo_width = max(1, rel_cargo_xmax - rel_cargo_xmin)

        rel_cargo_ymin = ce["ymin"] - origin_y
        margin = max(20, int((cb["ymax"] - cb["ymin"]) * 0.08))
        rel_y_search_bottom = max(ce["ymax"], cb["ymax"]) - origin_y + margin
        rel_y_search_top = max(0, rel_cargo_ymin - 5)

        try:
            stacks_local = build_stack_box_model_for_view(view_img, rel_y_search_top, rel_y_search_bottom,
                                                            rel_cargo_xmin, rel_cargo_xmax)
        except Exception as e:
            print(f"WARNING: Per-box segmentation failed for {view} ({e})")
            stacks_local = []

        total_stack_width = sum(s["x1"] - s["x0"] for s in stacks_local)
        coverage_ratio = total_stack_width / cargo_width
        if coverage_ratio < STACK_COVERAGE_MIN_RATIO:
            print(f"Per-box segmentation ({view}) REJECTED - coverage_ratio={coverage_ratio:.2f} "
                  f"< threshold {STACK_COVERAGE_MIN_RATIO} (falling back to AI-only for this view, same as v21)")
            continue

        stacks_abs = []
        for s in stacks_local:
            abs_boxes = []
            for b in s["boxes"]:
                abs_boxes.append({
                    "y_min": b["y_min"] + origin_y, "y_max": b["y_max"] + origin_y,
                    "x_left": b["x_left"] + origin_x, "x_right": b["x_right"] + origin_x,
                    "height_px": b["height_px"],
                })
            stacks_abs.append({
                "x0": s["x0"] + origin_x, "x1": s["x1"] + origin_x,
                "top_y": s["top_y"] + origin_y, "floor_y": s["floor_y"] + origin_y,
                "boxes": abs_boxes,
            })
        result[view] = stacks_abs
        print(f"Per-box segmentation ({view}): coverage_ratio={coverage_ratio:.2f}, "
              f"{len(stacks_abs)} stack(s) detected, "
              f"box counts per stack = {[len(s['boxes']) for s in stacks_abs]}")
    return result


def detect_overhang_regions_for_view(stacks):
    """
    ในแต่ละตั้งที่มี >=2 กล่อง เทียบขอบซ้าย/ขวาของกล่องที่อยู่ติดกัน (บน vs ล่าง)
    ถ้ากล่องบนยื่นพ้นขอบกล่องล่างเกิน OVERHANG_MIN_RATIO ของความกว้างกล่องล่าง
    "และ" ยื่นเกิน OVERHANG_MIN_ABS_PX พิกเซล (ทั้ง 2 เกณฑ์ต้องผ่าน - v23: เพิ่มเกณฑ์
    absolute pixel เพื่อป้องกัน false positive จาก noise การวัดขอบที่ตกค้างอยู่แม้ใช้
    median-of-rows แล้ว โดยเฉพาะกับกล่องแคบที่ผ่านเกณฑ์ % ได้ง่ายด้วย noise เพียงเล็กน้อย)
    ถือว่าเป็น OVERHANG_RISK
    """
    regions = []
    for s in stacks:
        boxes = s["boxes"]
        for i in range(len(boxes) - 1):
            upper = boxes[i]      # y น้อยกว่า = อยู่สูงกว่าทางกายภาพ (ชั้นบน)
            lower = boxes[i + 1]  # y มากกว่า = อยู่ใกล้พื้นกว่า (ชั้นล่าง/รองรับ)
            lower_width = max(1, lower["x_right"] - lower["x_left"])
            left_overhang = lower["x_left"] - upper["x_left"]
            right_overhang = upper["x_right"] - lower["x_right"]
            overhang_px = max(left_overhang, right_overhang, 0)
            ratio = overhang_px / lower_width
            if ratio >= OVERHANG_MIN_RATIO and overhang_px >= OVERHANG_MIN_ABS_PX:
                x_min = min(upper["x_left"], lower["x_left"])
                x_max = max(upper["x_right"], lower["x_right"])
                regions.append({"x_min": x_min, "y_min": upper["y_min"], "x_max": x_max, "y_max": lower["y_max"], "ratio": ratio})
    return regions


def detect_tall_unstable_regions_for_view(stacks):
    """
    เทียบความสูงรวมทั้งตั้ง (floor_y - top_y) ระหว่างตั้งที่อยู่ติดกัน ถ้าตั้งใดตั้ง
    หนึ่งสูงกว่าตั้งข้างเคียงทั้ง 2 ฝั่ง (ซ้ายและขวา) มากพอ (ไม่มีตั้งข้างค้ำยันเลย)
    ถือว่าเป็น TALL_UNSTABLE_RISK

    v23 fix: เดิม (v22) พิจารณาตั้งที่อยู่ "ริมสุด" ของขอบเขตที่วิเคราะห์ (มีเพื่อนบ้าน
    แค่ฝั่งเดียว) ด้วย ทำให้เกิด false positive จากเงื่อนไข "ขอบเขต" ล้วนๆ (พบจากการ
    ทดสอบไฟล์จริง AB01-02: ตั้งที่ริมซ้ายสุดของพื้นที่วิเคราะห์ถูกตัดสินว่า "ไม่มีตั้ง
    ข้างค้ำยัน" ทั้งที่ในความเป็นจริงอาจมีคาร์โก้ต่ออีกฝั่งนอกขอบเขตที่ครอปมาวิเคราะห์
    ซึ่งเราไม่มีข้อมูลเพียงพอจะยืนยันได้) จึงเปลี่ยนให้ต้องมีเพื่อนบ้าน "ทั้ง 2 ฝั่ง"
    เท่านั้นจึงจะพิจารณา (ตั้งที่ริมขอบเขตจะถูกข้ามไปเสมอ - ยอมพลาดบางเคสเพื่อไม่ให้
    เกิด false positive จากข้อจำกัดของขอบเขตการวิเคราะห์)
    """
    regions = []
    n = len(stacks)
    if n < 3:
        return regions
    heights = [max(1, s["floor_y"] - s["top_y"]) if s["boxes"] else 0 for s in stacks]
    for i in range(1, n - 1):
        h_this = heights[i]
        if h_this <= 0:
            continue
        neighbor_heights = [heights[i - 1], heights[i + 1]]
        if all(nh <= h_this * TALL_UNSTABLE_NEIGHBOR_MAX_RATIO for nh in neighbor_heights):
            diff_ratio = 1 - (max(neighbor_heights) / h_this)
            if diff_ratio >= TALL_UNSTABLE_MIN_HEIGHT_RATIO:
                s = stacks[i]
                regions.append({"x_min": s["x0"], "y_min": s["top_y"], "x_max": s["x1"], "y_max": s["floor_y"], "ratio": diff_ratio})
    return regions


def detect_lateral_imbalance_regions_for_view(stacks, rear_x0, rear_x1):
    """
    เทียบความสูงรวมทั้งตั้งระหว่างตั้งที่อยู่ติดกัน "เฉพาะในโซนประตูท้ายตู้"
    (rear_x0, rear_x1) เพื่อเป็น deterministic corroboration ให้ REAR_LATERAL_IMBALANCE
    หมายเหตุ: ตรวจไม่ได้ในกรณีที่ตั้งเตี้ยถูกตั้งสูงบังจนไม่เห็นขอบเลย (ดูหัวข้อ
    ข้อจำกัดด้านบน) - ในกรณีนั้น AI (Gemini) ยังจำเป็นต้องเป็นตัวตรวจหลัก
    """
    relevant = [s for s in stacks if s["x1"] > rear_x0 and s["x0"] < rear_x1]
    relevant.sort(key=lambda s: s["x0"])
    regions = []
    for i in range(len(relevant) - 1):
        a, b = relevant[i], relevant[i + 1]
        ha = max(1, a["floor_y"] - a["top_y"]) if a["boxes"] else 0
        hb = max(1, b["floor_y"] - b["top_y"]) if b["boxes"] else 0
        if ha == 0 or hb == 0:
            continue
        taller, shorter = (ha, hb) if ha >= hb else (hb, ha)
        ratio = 1 - (shorter / taller)
        if ratio >= LATERAL_IMBALANCE_MIN_RATIO:
            x_min = min(a["x0"], b["x0"]); x_max = max(a["x1"], b["x1"])
            y_min = min(a["top_y"], b["top_y"]); y_max = max(a["floor_y"], b["floor_y"])
            regions.append({"x_min": x_min, "y_min": y_min, "x_max": x_max, "y_max": y_max, "ratio": ratio})
    return regions


def _ai_box_2d_to_absolute(box_2d, crop_w, crop_h, crop_y_start):
    try:
        ymin, xmin, ymax, xmax = map(float, box_2d)
        if max(ymin, xmin, ymax, xmax) <= 1.0:
            ymin, xmin, ymax, xmax = ymin * 1000, xmin * 1000, ymax * 1000, xmax * 1000
        abs_xmin = (xmin / 1000.0) * crop_w
        abs_xmax = (xmax / 1000.0) * crop_w
        abs_ymin = crop_y_start + (ymin / 1000.0) * crop_h
        abs_ymax = crop_y_start + (ymax / 1000.0) * crop_h
        return (abs_xmin, abs_ymin, abs_xmax, abs_ymax)
    except Exception:
        return None


def _claim_overlaps_regions(box_2d, crop_w, crop_h, crop_y_start, regions_for_view, overlap_threshold=0.10):
    """
    VETO gate ทั่วไป (ใช้แนวคิดเดียวกับ _step_down_claim_overlaps_detection): ปฏิเสธ
    claim จาก AI ถ้า deterministic segmentation ไม่เจอตำแหน่งที่ทับซ้อนกันเลย
    """
    if not regions_for_view:
        return False
    claim_box = _ai_box_2d_to_absolute(box_2d, crop_w, crop_h, crop_y_start)
    if not claim_box:
        return True
    for region in regions_for_view:
        region_box = (region["x_min"], region["y_min"], region["x_max"], region["y_max"])
        if _box_iou_absolute(claim_box, region_box) >= overlap_threshold:
            return True
    return False


# ---------------------------------------------------------------------------
# PDF text helpers
# ---------------------------------------------------------------------------

def extract_sku_from_pdf(pdf_bytes):
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_index = 1 if len(doc) >= 2 else 0
        page = doc[page_index]
        full_text = page.get_text("text")
        skus = set()
        in_load_summary = False
        for line in full_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if "Load Summary" in line or "load summary" in line.lower():
                in_load_summary = True
                continue
            if in_load_summary and ("Cut List" in line or "cut list" in line.lower()):
                break
            if in_load_summary:
                parts = line.split()
                if parts:
                    match = re.match(r"^([A-Z][A-Z0-9]{3,7})", parts[0])
                    if match:
                        prefix = match.group(1)
                        exclude = {"SKU", "TOTAL", "CUT", "LIST", "LOAD", "PRIOR", "QTY", "PAGE", "DATE"}
                        if prefix not in exclude:
                            skus.add(prefix)
        sku_list = sorted(skus)
        print(f"SKU extracted: {sku_list}")
        return sku_list
    except Exception as e:
        print(f"SKU extraction failed: {e}")
        return []


# ---------------------------------------------------------------------------
# Gemini calls
# ---------------------------------------------------------------------------

def _reset_genai_client():
    if hasattr(genai, "_client"):
        genai._client = None
    if hasattr(genai, "client") and hasattr(genai.client, "_client"):
        genai.client._client = None


def _call_gemini_json(prompt, image, api_keys):
    global GLOBAL_KEY_INDEX
    last_err = ""
    total_keys = len(api_keys)
    if total_keys == 0:
        return {"rear_zone_risk": "ERROR", "front_zone_risk": "ERROR", "reasoning": "No API keys", "confidence": "LOW"}
    for i in range(total_keys):
        current_index = (GLOBAL_KEY_INDEX + i) % total_keys
        current_key = api_keys[current_index]
        try:
            _reset_genai_client()
            genai.configure(api_key=current_key)
            model = genai.GenerativeModel(model_name="gemini-3.6-flash")
            response = model.generate_content([prompt, image])
            clean_text = clean_json_response(response.text if response.text else "{}")
            result = json.loads(clean_text)
            if isinstance(result, list):
                result = result[0] if result else {}
            GLOBAL_KEY_INDEX = current_index
            return result
        except Exception as e:
            last_err = str(e)
            print(f"API Key index {current_index} failed: {last_err[:100]}")
            time.sleep(1)
            continue
    return {"rear_zone_risk": "ERROR", "front_zone_risk": "ERROR", "reasoning": last_err[:120], "confidence": "LOW"}


def analyze_rear_zone_with_ai(rear_crop, api_keys, view_label="UNKNOWN"):
    """
    v21 IMPROVED PROMPT: เพิ่มความเจาะจงเรื่อง 'ความสูงรวมทั้งตั้ง' และให้ตัวอย่าง
    สถานการณ์ที่ตั้งหนึ่งซ้อนกล่องสูงกว่า (เช่น 2 ชั้น) อยู่ติดกับตั้งที่เตี้ยกว่า
    (เช่น 1 ชั้น) แม้จะดูเหมือนซ้อนทับ/บังกันบางส่วนในมุมมอง 3 มิติ ก็ต้องนับเป็น
    ความเสี่ยง (พบจากไฟล์ AC03 ที่ pattern ความสูง 2,2,1 ในตำแหน่งประตูท้ายตู้ ซึ่ง
    ตั้งเตี้ยอยู่คนละตำแหน่งความกว้าง/ลึกของตู้ ทำให้สังเกตยากกว่ากรณีปกติ)

    v22: ผลจาก AI นี้จะถูกนำไปเทียบ (corroborate) กับ deterministic per-box
    segmentation ใน process_request() - หาก deterministic เจอความไม่สมดุลชัดเจน
    (ไม่มี occlusion) แต่ AI ตอบ SAFE จะถูก FORCE เพิ่มเข้าไปโดยอัตโนมัติ
    """
    prompt = f"""
You are a Cargo Safety Inspector. This image is a cropped zoom of the DOOR END (REAR) zone of a container.
This is the {view_label} view.
YOUR TASK: Determine if there is a genuine safety risk at the door end.

RULES (numeric thresholds - apply consistently, do not be overly cautious):
1. REAR_EMPTY_RISK: Flag if there is empty floor space near the door of more than roughly 20% of
   the container height, OR cargo drops off sharply leaving a dangerous unsupported edge.
2. REAR_LATERAL_IMBALANCE: Flag if the TOTAL STACKED HEIGHT of cargo (adding up ALL boxes stacked
   in that column, from floor to top - not just a single box) on one side of the door zone differs
   from the total stacked height on an adjacent position by MORE than approximately 40-50% of the
   taller stack's total height. This is a real, measurable visual difference.

   IMPORTANT - look carefully at EVERY stack position, not just left-vs-right overall: in this
   isometric 3D view, a shorter stack (e.g. only 1 tier tall) sitting at a different depth/width
   position than a taller stack (e.g. 2 tiers tall) may appear to be PARTIALLY OVERLAPPED OR
   PARTIALLY HIDDEN BEHIND the taller stack from this viewing angle - it does NOT mean they are
   the same height. If you can see even a portion of a stack that is clearly shorter than its
   immediate neighbors (for example a pattern where two adjacent stacks are 2 tiers tall but a
   third stack right next to them, at a different depth, is only 1 tier tall), this IS a genuine
   REAR_LATERAL_IMBALANCE risk - the top box of the taller stack could slide/fall onto the shorter
   stack, or fall into the empty space above the shorter stack. Do not dismiss this just because
   the stacks appear to visually overlap or touch in the 2D projection.
3. The container wall/floor/frame structure itself is NOT cargo - never flag it.
4. If cargo reasonably fills the rear area and all stacks (including hidden/partially-visible ones)
   are close in total height (within ~1 small tier) -> SAFE.

IMPORTANT - if you flag a risk, you MUST also provide "box_2d" pinpointing EXACTLY where the
problem is visible in THIS image (the specific shorter stack, or the boundary between stacks with
different total heights). Use [ymin, xmin, ymax, xmax] format with values 0-1000 normalized to
this image's own size. The box must tightly enclose the actual shorter stack (or the height-
mismatch boundary) - not the whole image, not empty background.

Return ONLY this exact JSON:
{{"rear_zone_risk":"REAR_EMPTY_RISK"|"REAR_LATERAL_IMBALANCE"|"BOTH"|"SAFE","reasoning":"describe what you see, including approximate height difference if any, and specifically note if any stack appears partially hidden/overlapped by a taller neighbor","confidence":"HIGH"|"MEDIUM"|"LOW","box_2d":[ymin,xmin,ymax,xmax]}}
(box_2d is required whenever rear_zone_risk is not SAFE; omit or use null if SAFE)
"""
    return _call_gemini_json(prompt, rear_crop, api_keys)


def analyze_front_zone_with_ai(front_crop, api_keys, view_label="UNKNOWN"):
    prompt = f"""
You are a Cargo Safety Inspector. This image is a cropped zoom of the HEAD WALL (FRONT) zone of a container.
This is the {view_label} view. The solid colored panel (yellow/tan/brown/cyan) is the container head
wall/floor structure - it is NOT cargo.
YOUR TASK: Determine if there is a genuine FRONT_EMPTY_RISK.

RULES:
1. FRONT_EMPTY_RISK: Flag if there is a clearly visible empty gap between the front-most cargo and
   the head wall that is more than roughly half a box width (~30-40% of typical box width visible
   in the image). This should be an obvious, measurable gap you can point to.
2. If cargo is stacked against or reasonably close to the head wall (small natural gaps from
   packing are normal) -> SAFE.
3. When the gap is ambiguous or very small -> SAFE.

IMPORTANT - if you flag FRONT_EMPTY_RISK, you MUST also provide "box_2d" pinpointing EXACTLY where
the empty gap is visible in THIS image. Use [ymin, xmin, ymax, xmax] format with values 0-1000
normalized to this image's own size. The box should cover the actual gap area between cargo and wall.

Return ONLY this exact JSON:
{{"front_zone_risk":"FRONT_EMPTY_RISK"|"SAFE","reasoning":"describe the gap size you see, or why it's safe","confidence":"HIGH"|"MEDIUM"|"LOW","box_2d":[ymin,xmin,ymax,xmax]}}
(box_2d is required whenever front_zone_risk is not SAFE; omit or use null if SAFE)
"""
    return _call_gemini_json(prompt, front_crop, api_keys)


def analyze_diagram_image_with_ai(diagram_image, layout="TOP_BOTTOM"):
    global GLOBAL_KEY_INDEX
    api_keys = get_api_keys_pool()
    if not api_keys:
        return [{"risk_type": "ERROR", "description": "No Gemini API Keys found."}]

    front_rear = HARDCODED_REAR_SIDE["FRONT"]
    front_wall = "RIGHT" if front_rear == "LEFT" else "LEFT"
    back_rear = HARDCODED_REAR_SIDE["BACK"]
    back_wall = "RIGHT" if back_rear == "LEFT" else "LEFT"

    layout_desc = (
        "FRONT view is on the LEFT half; BACK view is on the RIGHT half."
        if layout == "LEFT_RIGHT"
        else "FRONT view is on the TOP half; BACK view is on the BOTTOM half."
    )

    prompt = f"""
You are an expert Cargo Loading Safety Inspector analyzing a 3D cargo load plan.

VIEW LAYOUT: {layout_desc}
FIXED ORIENTATION (a known fact about how this diagram type is always drawn - trust it completely):
- FRONT view: REAR/door side is {front_rear}; FRONT/head-wall side is {front_wall}.
- BACK view: REAR/door side is {back_rear}; FRONT/head-wall side is {back_wall}.

YOUR TASK: Find ONLY these 4 risk types (REAR_EMPTY_RISK, FRONT_EMPTY_RISK, and
REAR_LATERAL_IMBALANCE are analyzed separately elsewhere - do NOT report them here):

- STEP_DOWN_RISK: a sudden height drop between two ADJACENT cargo stacks. APPLY THIS NUMERIC RULE
  STRICTLY: if one stack is shorter than its immediate neighbor by MORE than approximately 40-50%
  of the taller stack's height, this IS a STEP_DOWN_RISK - flag it even if you are generally trying
  to be conservative, and EVEN IF the height difference happens to be located near the door/rear end
  of the container. Only skip flagging when the height difference is small, or when tall stacks
  gradually taper down over multiple positions toward the doors (that gradual tapering is normal).
  BE VERY CAREFUL: if the container appears fully and uniformly loaded (all stacks the same height),
  you MUST NOT invent a STEP_DOWN_RISK - only report what you can clearly and confidently see.
- LATERAL_GAP_RISK: an obvious empty gap between two side-by-side stacks in the middle of the load,
  OR cargo not spanning the full width of the container leaving visible empty floor on one side.
- TALL_UNSTABLE_RISK: a single tall stack with no lateral support from neighboring cargo.
- OVERHANG_RISK: upper-tier cargo clearly overhanging past the edge of the cargo below it.

Look carefully at EVERY pair of adjacent stacks in both views before concluding there are no risks.
A fully and evenly loaded container should return an EMPTY array [].

BOUNDING BOX RULES:
- box_2d must use [ymin, xmin, ymax, xmax] format, values 0-1000 normalized to image size.
- box_2d must tightly surround only the affected area, and MUST stay entirely within the half of
  the image belonging to its "view" (never cross from FRONT half into BACK half or vice versa).
- Box width and height must each be between 5% and 55% of that view's dimensions.
- "view" must be exactly "FRONT" or "BACK" - never "GENERAL".

Return ONLY a JSON array (empty array if no genuine risks found):
[
  {{"risk_type":"STEP_DOWN_RISK"|"LATERAL_GAP_RISK"|"TALL_UNSTABLE_RISK"|"OVERHANG_RISK","view":"FRONT"|"BACK","box_2d":[ymin,xmin,ymax,xmax],"description":"describe the height difference or gap you observed"}}
]
"""
    last_error_msg = ""
    for pass_round in range(2):
        for i in range(len(api_keys)):
            current_index = (GLOBAL_KEY_INDEX + i) % len(api_keys)
            current_key = api_keys[current_index]
            try:
                _reset_genai_client()
                genai.configure(api_key=current_key)
                model = genai.GenerativeModel(model_name="gemini-3.6-flash")
                response = model.generate_content([prompt, diagram_image])
                clean_text = clean_json_response(response.text if response.text else "[]")
                if not clean_text or clean_text in ('""', "[]"):
                    return []
                risks = json.loads(clean_text)
                if isinstance(risks, dict):
                    risks = [risks]
                GLOBAL_KEY_INDEX = current_index
                return risks
            except Exception as e:
                last_error_msg = str(e)
                print(f"API Key index {current_index} failed in diagram analysis: {last_error_msg[:100]}")
                time.sleep(1)
                continue
        if pass_round == 0:
            time.sleep(2)
    return [{"risk_type": "ERROR", "description": f"AI Error: {last_error_msg[:120]}"}]


# ---------------------------------------------------------------------------
# Fallback zone boxes
# ---------------------------------------------------------------------------

def _get_fallback_box(risk_type, view_label, layout, crop_w, crop_y_start, crop_h,
                       container_bounds=None, cargo_extent=None):
    vl = str(view_label).upper().strip()
    if vl not in ("FRONT", "BACK"):
        vl = "FRONT"
    rear_side = HARDCODED_REAR_SIDE[vl]

    view_container = container_bounds.get(vl) if container_bounds else None
    view_cargo = cargo_extent.get(vl) if cargo_extent else None

    if risk_type in ("REAR_EMPTY_RISK", "FRONT_EMPTY_RISK", "REAR_COMBINED_RISK") and view_container and view_cargo:
        c_xmin, c_xmax = view_container["xmin"], view_container["xmax"]
        g_xmin, g_xmax = view_cargo["xmin"], view_cargo["xmax"]
        y0 = min(view_container["ymin"], view_cargo["ymin"])
        y1 = max(view_container["ymax"], view_cargo["ymax"])
        y_pad = (y1 - y0) * 0.05
        box_y0, box_y1 = y0 - y_pad, y1 + y_pad

        MIN_GAP_WIDTH = max(20, (c_xmax - c_xmin) * 0.05)

        if risk_type == "FRONT_EMPTY_RISK":
            if rear_side == "LEFT":
                gap_x0 = g_xmax
                gap_x1 = c_xmax
            else:
                gap_x0 = c_xmin
                gap_x1 = g_xmin
            if gap_x1 - gap_x0 < MIN_GAP_WIDTH:
                if rear_side == "LEFT":
                    gap_x0, gap_x1 = max(c_xmin, c_xmax - MIN_GAP_WIDTH), c_xmax
                else:
                    gap_x0, gap_x1 = c_xmin, min(c_xmax, c_xmin + MIN_GAP_WIDTH)
            box = (gap_x0, box_y0, gap_x1, box_y1)
            print(f"Measured FRONT_EMPTY_RISK gap for {vl}: cargo=[{g_xmin}-{g_xmax}] container=[{c_xmin}-{c_xmax}] -> box_x=[{gap_x0}-{gap_x1}]")
            return tuple(map(int, box))
        else:
            if rear_side == "LEFT":
                gap_x0 = c_xmin
                gap_x1 = g_xmin
            else:
                gap_x0 = g_xmax
                gap_x1 = c_xmax
            if gap_x1 - gap_x0 < MIN_GAP_WIDTH:
                if rear_side == "LEFT":
                    gap_x0, gap_x1 = c_xmin, min(c_xmax, c_xmin + MIN_GAP_WIDTH)
                else:
                    gap_x0, gap_x1 = max(c_xmin, c_xmax - MIN_GAP_WIDTH), c_xmax
            box = (gap_x0, box_y0, gap_x1, box_y1)
            print(f"Measured {risk_type} gap for {vl}: cargo=[{g_xmin}-{g_xmax}] container=[{c_xmin}-{c_xmax}] -> box_x=[{gap_x0}-{gap_x1}]")
            return tuple(map(int, box))

    reference_bounds = view_cargo if view_cargo else view_container

    if reference_bounds:
        origin_x = reference_bounds["xmin"]
        origin_y = reference_bounds["ymin"]
        ref_w = max(1, reference_bounds["xmax"] - reference_bounds["xmin"])
        ref_h = max(1, reference_bounds["ymax"] - reference_bounds["ymin"])
        source_label = "cargo extent (prevents floating in empty space)" if view_cargo else "detected container bounds (percentage fallback)"
    else:
        if layout == "TOP_BOTTOM":
            half_h = crop_h // 2
            origin_x = 0
            origin_y = crop_y_start if vl == "FRONT" else crop_y_start + half_h
            ref_w = crop_w
            ref_h = half_h if vl == "FRONT" else crop_h - half_h
        else:
            half_w = crop_w // 2
            origin_x = 0 if vl == "FRONT" else half_w
            origin_y = crop_y_start
            ref_w = half_w if vl == "FRONT" else crop_w - half_w
            ref_h = crop_h
        source_label = "fixed-percentage fallback (no container/cargo bounds)"

    def pct(px, py):
        return origin_x + int(ref_w * px), origin_y + int(ref_h * py)

    y_pad = 0.08
    y0f, y1f = y_pad, 1.0 - y_pad
    mid_yf = y0f + (y1f - y0f) / 2

    if layout == "TOP_BOTTOM":
        rear_frac = 0.55 if view_cargo else 0.38
        wall_frac = 0.45 if view_cargo else 0.32
        if rear_side == "LEFT":
            rear_zone = (0.0, y0f, rear_frac, y1f)
            wall_zone = (1.0 - wall_frac, y0f, 1.0, y1f)
        else:
            rear_zone = (1.0 - rear_frac, y0f, 1.0, y1f)
            wall_zone = (0.0, y0f, wall_frac, y1f)
        zones_pct = {
            "REAR_EMPTY_RISK": (rear_zone[0], rear_zone[1], rear_zone[2], mid_yf),
            "REAR_LATERAL_IMBALANCE": (rear_zone[0], mid_yf, rear_zone[2], rear_zone[3]),
            "REAR_COMBINED_RISK": rear_zone,
            "FRONT_EMPTY_RISK": wall_zone,
            "STEP_DOWN_RISK": (0.15, y0f, 0.85, y1f),
            "LATERAL_GAP_RISK": (0.20, y0f, 0.80, y1f),
            "TALL_UNSTABLE_RISK": (0.25, y0f, 0.75, y1f),
            "OVERHANG_RISK": (0.15, y0f, 0.85, mid_yf),
        }
    else:
        if rear_side == "LEFT":
            rear_zone = (0.0, 0.50, 0.55, 1.0)
            wall_zone = (0.30, 0.0, 1.0, 0.50)
        else:
            rear_zone = (0.45, 0.0, 1.0, 0.50)
            wall_zone = (0.0, 0.50, 0.70, 1.0)
        rear_mid_yf = rear_zone[1] + (rear_zone[3] - rear_zone[1]) / 2
        zones_pct = {
            "REAR_EMPTY_RISK": (rear_zone[0], rear_zone[1], rear_zone[2], rear_mid_yf),
            "REAR_LATERAL_IMBALANCE": (rear_zone[0], rear_mid_yf, rear_zone[2], rear_zone[3]),
            "REAR_COMBINED_RISK": rear_zone,
            "FRONT_EMPTY_RISK": wall_zone,
            "STEP_DOWN_RISK": (0.08, 0.20, 0.88, 0.78),
            "LATERAL_GAP_RISK": (0.05, 0.20, 0.85, 0.80),
            "TALL_UNSTABLE_RISK": (0.05, 0.10, 0.85, 0.60),
            "OVERHANG_RISK": (0.05, 0.10, 0.85, 0.45),
        }

    zp = zones_pct.get(risk_type)
    if zp is None:
        return None
    x0, y0 = pct(zp[0], zp[1])
    x1, y1 = pct(zp[2], zp[3])
    box = (x0, y0, x1, y1)
    print(f"Fallback box for {risk_type} ({vl}, {layout}): using {source_label}, "
          f"HARDCODED rear_side={rear_side}, box={box}")
    return box


def _normalized_box(r):
    box = r.get("box_2d") or r.get("boundingBox") or r.get("box")
    if box and isinstance(box, list) and len(box) == 4:
        try:
            ymin, xmin, ymax, xmax = map(float, box)
            if max(ymin, xmin, ymax, xmax) <= 1.0:
                ymin, xmin, ymax, xmax = ymin * 1000, xmin * 1000, ymax * 1000, xmax * 1000
            return [ymin, xmin, ymax, xmax]
        except Exception:
            return None
    return None


def _box_iou(b1, b2):
    if not b1 or not b2:
        return 0.0
    y1a, x1a, y2a, x2a = b1
    y1b, x1b, y2b, x2b = b2
    iw = max(0.0, min(x2a, x2b) - max(x1a, x1b))
    ih = max(0.0, min(y2a, y2b) - max(y1a, y1b))
    inter = iw * ih
    area1 = max(0.0, x2a - x1a) * max(0.0, y2a - y1a)
    area2 = max(0.0, x2b - x1b) * max(0.0, y2b - y1b)
    union = area1 + area2 - inter
    return inter / union if union > 0 else 0.0


def _risk_color_for_type(risk_type):
    return RISK_COLORS.get(str(risk_type).upper().strip(), "red")


def _risk_area_key(r):
    rt = str(r.get("risk_type", "")).upper().strip()
    v = str(r.get("view", "")).upper().strip() or "GENERAL"
    if rt in ("REAR_EMPTY_RISK", "REAR_LATERAL_IMBALANCE", "REAR_COMBINED_RISK"):
        return (v, "REAR_ZONE")
    if rt in ("FRONT_EMPTY_RISK",):
        return (v, "FRONT_ZONE")
    box = _normalized_box(r)
    if box:
        ymin, xmin, ymax, xmax = box
        return (v, "BOX_ZONE", int(((xmin + xmax) / 2) // 100), int(((ymin + ymax) / 2) // 100))
    return (v, rt)


def _merge_same_area_risks(all_risks):
    groups = []
    for i, r in enumerate(all_risks):
        rt = str(r.get("risk_type", "")).upper().strip()
        if rt == "ERROR":
            groups.append({"key": ("ERROR", i), "items": [(i, r)]})
            continue
        key = _risk_area_key(r)
        box = _normalized_box(r)
        placed = False
        for g in groups:
            if g["key"] == key:
                g["items"].append((i, r))
                placed = True
                break
            if key[:2] == (g["key"][0], "BOX_ZONE") and len(g["items"]) > 0:
                g_first_box = _normalized_box(g["items"][0][1])
                if box and g_first_box and _box_iou(box, g_first_box) >= 0.35:
                    g["items"].append((i, r))
                    placed = True
                    break
        if not placed:
            groups.append({"key": key, "items": [(i, r)]})

    merged_result = []
    for g in groups:
        items = g["items"]
        if len(items) == 1:
            merged_result.append(items[0][1])
            continue
        key = g["key"]
        view_label = str(items[0][1].get("view", "GENERAL")).upper().strip() or "GENERAL"
        risk_types, colors, reason_parts, description_parts = [], [], [], []
        for _, r in items:
            rt = str(r.get("risk_type", "")).upper().strip()
            if rt not in risk_types:
                risk_types.append(rt)
            c = _risk_color_for_type(rt)
            if c not in colors:
                colors.append(c)
            if r.get("reasoning"):
                reason_parts.append(str(r.get("reasoning")))
            if r.get("description"):
                description_parts.append(str(r.get("description")))
        if len(colors) == 1:
            colors = [colors[0], colors[0]]
        elif len(colors) > 2:
            colors = colors[:2]
        area_name = key[1] if len(key) > 1 else ""
        if area_name == "REAR_ZONE":
            fallback_risk_type = "REAR_COMBINED_RISK"
        elif area_name == "FRONT_ZONE":
            fallback_risk_type = "FRONT_EMPTY_RISK"
        else:
            fallback_risk_type = risk_types[0]
        merged_box = None
        boxes = [b for b in (_normalized_box(r) for _, r in items) if b]
        if boxes and area_name == "BOX_ZONE":
            merged_box = [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]
        merged_result.append({
            "view": view_label,
            "risk_type": "COMBINED_AREA_RISK",
            "fallback_risk_type": fallback_risk_type,
            "merged_risk_types": risk_types,
            "draw_colors": colors,
            "box_2d": merged_box,
            "direction": "COMBINED",
            "lateral_side": "N/A",
            "reasoning": " | ".join(reason_parts),
            "description": " / ".join(description_parts) if description_parts else "พบหลายความเสี่ยงในบริเวณเดียวกัน จึงรวมเป็นกรอบเดียว",
        })
        print(f"Merged same-area risks {risk_types} -> COMBINED_AREA_RISK for {view_label}, colors={colors}, fallback={fallback_risk_type}")
    return merged_result


def _draw_single_or_dual_rectangle(draw, coords, outline_color, draw_colors=None):
    x0, y0, x1, y1 = map(int, coords)
    if draw_colors and len(draw_colors) >= 2:
        c1, c2 = draw_colors[0], draw_colors[1]
        draw.rectangle([x0, y0, x1, y1], outline=c1, width=8)
        inset = 9
        if x1 - x0 > inset * 2 and y1 - y0 > inset * 2:
            draw.rectangle([x0 + inset, y0 + inset, x1 - inset, y1 - inset], outline=c2, width=6)
    else:
        draw.rectangle([x0, y0, x1, y1], outline=outline_color, width=8)


def _convert_zoom_box_to_absolute(zoom_box_2d, crop_x0, crop_y0, crop_x1, crop_y1):
    try:
        ymin, xmin, ymax, xmax = map(float, zoom_box_2d)
        if max(ymin, xmin, ymax, xmax) <= 1.0:
            ymin, xmin, ymax, xmax = ymin * 1000, xmin * 1000, ymax * 1000, xmax * 1000
        crop_w = crop_x1 - crop_x0
        crop_h = crop_y1 - crop_y0
        abs_xmin = crop_x0 + (xmin / 1000.0) * crop_w
        abs_xmax = crop_x0 + (xmax / 1000.0) * crop_w
        abs_ymin = crop_y0 + (ymin / 1000.0) * crop_h
        abs_ymax = crop_y0 + (ymax / 1000.0) * crop_h
        if abs_xmax <= abs_xmin or abs_ymax <= abs_ymin:
            return None
        return (int(abs_xmin), int(abs_ymin), int(abs_xmax), int(abs_ymax))
    except Exception:
        return None


def _get_zoom_precise_box(zone_result, box_key, crop_rect, full_img, min_cargo_ratio=0.15):
    if not isinstance(zone_result, dict):
        return None
    zoom_box = zone_result.get(box_key)
    if not zoom_box or not isinstance(zoom_box, list) or len(zoom_box) != 4:
        return None
    crop_x0, crop_y0, crop_x1, crop_y1 = crop_rect
    abs_box = _convert_zoom_box_to_absolute(zoom_box, crop_x0, crop_y0, crop_x1, crop_y1)
    if not abs_box:
        return None
    cargo_ratio = _cargo_pixel_ratio_in_box(full_img, abs_box)
    if cargo_ratio < min_cargo_ratio:
        print(f"Zoom box_2d rejected (cargo_ratio={cargo_ratio:.2f} < {min_cargo_ratio}): {abs_box}")
        return None
    print(f"Zoom box_2d ACCEPTED (cargo_ratio={cargo_ratio:.2f}): {abs_box}")
    return abs_box


# ---------------------------------------------------------------------------
# Main HTTP handler
# ---------------------------------------------------------------------------

@functions_framework.http
def process_request(request):
    if request.method == "OPTIONS":
        headers = {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST",
            "Access-Control-Allow-Headers": "Content-Type, x-goog-api-key",
            "Access-Control-Max-Age": "3600",
        }
        return ("", 204, headers)
    headers = {"Access-Control-Allow-Origin": "*"}
    try:
        data = request.get_json(silent=True)
        if data is None:
            raw_data = request.get_data(as_text=True)
            data = json.loads(raw_data) if raw_data else {}
        if not data or "base64" not in data:
            print("DEBUG - RECEIVED DATA:", request.get_data(as_text=True)[:500])
            return ({"error": "No base64 data provided"}, 400, headers)
        base64_str = data.get("base64")
        if "," in base64_str:
            base64_str = base64_str.split(",", 1)[1]
        pdf_bytes = base64.b64decode(base64_str)

        layout = detect_page_layout_from_pdf(pdf_bytes)
        sku_list = extract_sku_from_pdf(pdf_bytes)
        sku_str = ", ".join(sku_list) if sku_list else ""
        container_length_mm = extract_container_length_mm(pdf_bytes)

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_index = 1 if len(doc) >= 2 else 0
        page = doc[page_index]
        pix = page.get_pixmap(dpi=180)
        mode = "RGBA" if pix.alpha else "RGB"
        img = PIL.Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        if mode == "RGBA":
            img = img.convert("RGB")
        width, height = img.size

        crop_y_start = int(height * 0.10)
        crop_y_end = int(height * 0.90)
        crop_w = int(width * 0.75)
        crop_h = crop_y_end - crop_y_start
        diagram_crop = img.crop((0, crop_y_start, crop_w, crop_y_end))

        container_bounds = detect_container_bounds_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start)
        cargo_extent = detect_cargo_extent_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start)

        step_down_regions = detect_step_down_regions_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start,
                                                                container_bounds, cargo_extent)

        # v22/v23.1: สร้าง per-box stack model (deterministic) สำหรับ OVERHANG_RISK,
        # TALL_UNSTABLE_RISK, REAR_LATERAL_IMBALANCE - ดูหัวข้อ "PER-BOX SEGMENTATION"
        # ด้านบนสำหรับรายละเอียดอัลกอริทึมและข้อจำกัด
        stack_box_model = build_stack_box_model_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start,
                                                          container_bounds, cargo_extent)
        overhang_regions = {}
        tall_unstable_regions = {}
        for view_label in ("FRONT", "BACK"):
            stacks = stack_box_model.get(view_label, [])
            overhang_regions[view_label] = detect_overhang_regions_for_view(stacks)
            tall_unstable_regions[view_label] = detect_tall_unstable_regions_for_view(stacks)
            for r in overhang_regions[view_label]:
                print(f"Deterministic OVERHANG_RISK candidate ({view_label}): "
                      f"x=[{r['x_min']:.0f}-{r['x_max']:.0f}] y=[{r['y_min']:.0f}-{r['y_max']:.0f}] "
                      f"overhang_ratio={r['ratio']*100:.1f}% (threshold={OVERHANG_MIN_RATIO*100:.0f}%)")
            for r in tall_unstable_regions[view_label]:
                print(f"Deterministic TALL_UNSTABLE_RISK candidate ({view_label}): "
                      f"x=[{r['x_min']:.0f}-{r['x_max']:.0f}] y=[{r['y_min']:.0f}-{r['y_max']:.0f}] "
                      f"height_diff_ratio={r['ratio']*100:.1f}% (threshold={TALL_UNSTABLE_MIN_HEIGHT_RATIO*100:.0f}%)")

        raw_ai_risks = analyze_diagram_image_with_ai(diagram_crop, layout=layout)
        if not isinstance(raw_ai_risks, list):
            raw_ai_risks = []

        all_risks = []
        for r in raw_ai_risks:
            rt = str(r.get("risk_type", "")).upper().strip()
            view_of_claim = str(r.get("view", "")).upper().strip()
            box_2d = r.get("box_2d")
            has_valid_box = view_of_claim in ("FRONT", "BACK") and box_2d and isinstance(box_2d, list) and len(box_2d) == 4

            if rt == "STEP_DOWN_RISK":
                if has_valid_box:
                    regions_for_view = step_down_regions.get(view_of_claim, [])
                    if _step_down_claim_overlaps_detection(box_2d, crop_w, crop_h, crop_y_start, regions_for_view):
                        all_risks.append(r)
                    else:
                        print(f"Gemini STEP_DOWN_RISK claim for {view_of_claim} view REJECTED by deterministic gate "
                              f"(description: {r.get('description', '')[:100]})")
                else:
                    print(f"Gemini STEP_DOWN_RISK claim REJECTED - missing valid view/box_2d for verification")
            elif rt == "OVERHANG_RISK":
                # VETO: ปฏิเสธ claim ถ้า deterministic per-box segmentation ไม่เจอ
                # ตำแหน่งกล่องยื่นที่ทับซ้อนกันเลยในตั้งใดๆ ของ view นี้
                if has_valid_box:
                    regions_for_view = overhang_regions.get(view_of_claim, [])
                    if _claim_overlaps_regions(box_2d, crop_w, crop_h, crop_y_start, regions_for_view):
                        all_risks.append(r)
                    else:
                        print(f"Gemini OVERHANG_RISK claim for {view_of_claim} view REJECTED by deterministic "
                              f"per-box gate (description: {r.get('description', '')[:100]})")
                else:
                    print("Gemini OVERHANG_RISK claim REJECTED - missing valid view/box_2d for verification")
            elif rt == "TALL_UNSTABLE_RISK":
                # VETO: เช่นเดียวกับ OVERHANG_RISK
                if has_valid_box:
                    regions_for_view = tall_unstable_regions.get(view_of_claim, [])
                    if _claim_overlaps_regions(box_2d, crop_w, crop_h, crop_y_start, regions_for_view):
                        all_risks.append(r)
                    else:
                        print(f"Gemini TALL_UNSTABLE_RISK claim for {view_of_claim} view REJECTED by deterministic "
                              f"per-box gate (description: {r.get('description', '')[:100]})")
                else:
                    print("Gemini TALL_UNSTABLE_RISK claim REJECTED - missing valid view/box_2d for verification")
            else:
                all_risks.append(r)

        # FORCE: เพิ่ม OVERHANG_RISK / TALL_UNSTABLE_RISK ที่ deterministic เจอ
        # แต่ AI ไม่ได้ claim มา (AI บอก SAFE หรือพลาดจุดนั้นไป)
        def _view_already_has_overlapping_claim(view_label, risk_type, region, existing_risks):
            for r in existing_risks:
                if str(r.get("risk_type", "")).upper().strip() != risk_type:
                    continue
                if str(r.get("view", "")).upper().strip() != view_label:
                    continue
                r_box = r.get("box_2d")
                if not r_box:
                    continue
                r_abs = _ai_box_2d_to_absolute(r_box, crop_w, crop_h, crop_y_start)
                if not r_abs:
                    continue
                region_box = (region["x_min"], region["y_min"], region["x_max"], region["y_max"])
                if _box_iou_absolute(r_abs, region_box) >= 0.15:
                    return True
            return False

        for view_label in ("FRONT", "BACK"):
            for region in overhang_regions.get(view_label, []):
                if region["ratio"] < OVERHANG_MIN_RATIO:
                    continue
                if _view_already_has_overlapping_claim(view_label, "OVERHANG_RISK", region, all_risks):
                    continue
                ymin_norm = ((region["y_min"] - crop_y_start) / crop_h) * 1000
                ymax_norm = ((region["y_max"] - crop_y_start) / crop_h) * 1000
                xmin_norm = (region["x_min"] / crop_w) * 1000
                xmax_norm = (region["x_max"] / crop_w) * 1000
                print(f"FORCED OVERHANG_RISK ({view_label}) from deterministic per-box segmentation "
                      f"(overhang_ratio={region['ratio']*100:.0f}%)")
                all_risks.append({
                    "view": view_label, "risk_type": "OVERHANG_RISK",
                    "box_2d": [ymin_norm, xmin_norm, ymax_norm, xmax_norm],
                    "reasoning": "FORCED_DETERMINISTIC_PER_BOX_OVERHANG",
                    "description": f"พบสินค้าชั้นบนยื่นพ้นขอบสินค้าชั้นล่างประมาณ {region['ratio']*100:.0f}% ของความกว้างกล่องล่าง (ตรวจจับจาก per-box segmentation)",
                })
            for region in tall_unstable_regions.get(view_label, []):
                if region["ratio"] < TALL_UNSTABLE_MIN_HEIGHT_RATIO:
                    continue
                if _view_already_has_overlapping_claim(view_label, "TALL_UNSTABLE_RISK", region, all_risks):
                    continue
                ymin_norm = ((region["y_min"] - crop_y_start) / crop_h) * 1000
                ymax_norm = ((region["y_max"] - crop_y_start) / crop_h) * 1000
                xmin_norm = (region["x_min"] / crop_w) * 1000
                xmax_norm = (region["x_max"] / crop_w) * 1000
                print(f"FORCED TALL_UNSTABLE_RISK ({view_label}) from deterministic per-box segmentation "
                      f"(height_diff_ratio={region['ratio']*100:.0f}%)")
                all_risks.append({
                    "view": view_label, "risk_type": "TALL_UNSTABLE_RISK",
                    "box_2d": [ymin_norm, xmin_norm, ymax_norm, xmax_norm],
                    "reasoning": "FORCED_DETERMINISTIC_PER_BOX_TALL_UNSTABLE",
                    "description": f"พบกองสินค้าสูงโดดเดี่ยวไม่มีตั้งข้างค้ำยัน (ต่างจากเพื่อนบ้านประมาณ {region['ratio']*100:.0f}%) (ตรวจจับจาก per-box segmentation)",
                })

        def _zoom_crop_ranges(view_bounds, rear_side, default_origin_x, default_ref_w):
            if view_bounds:
                ox, rw = view_bounds["xmin"], view_bounds["xmax"] - view_bounds["xmin"]
            else:
                ox, rw = default_origin_x, default_ref_w
            if rear_side == "LEFT":
                return (ox, ox + int(rw * 0.45)), (ox + int(rw * 0.55), ox + rw)
            return (ox + int(rw * 0.55), ox + rw), (ox, ox + int(rw * 0.45))

        front_rear_side = HARDCODED_REAR_SIDE["FRONT"]
        back_rear_side = HARDCODED_REAR_SIDE["BACK"]

        zoom_crop_rects = {}

        if layout == "TOP_BOTTOM":
            half_h = crop_h // 2
            (fr_x0, fr_x1), (fw_x0, fw_x1) = _zoom_crop_ranges(container_bounds.get("FRONT"), front_rear_side, 0, crop_w)
            (br_x0, br_x1), (bw_x0, bw_x1) = _zoom_crop_ranges(container_bounds.get("BACK"), back_rear_side, 0, crop_w)
            rear_crop_front = img.crop((fr_x0, crop_y_start, fr_x1, crop_y_start + half_h))
            front_crop_front = img.crop((fw_x0, crop_y_start, fw_x1, crop_y_start + half_h))
            rear_crop_back = img.crop((br_x0, crop_y_start + half_h, br_x1, crop_y_end))
            front_crop_back = img.crop((bw_x0, crop_y_start + half_h, bw_x1, crop_y_end))
            zoom_crop_rects["rear_FRONT"] = (fr_x0, crop_y_start, fr_x1, crop_y_start + half_h)
            zoom_crop_rects["front_FRONT"] = (fw_x0, crop_y_start, fw_x1, crop_y_start + half_h)
            zoom_crop_rects["rear_BACK"] = (br_x0, crop_y_start + half_h, br_x1, crop_y_end)
            zoom_crop_rects["front_BACK"] = (bw_x0, crop_y_start + half_h, bw_x1, crop_y_end)
            print(f"TOP_BOTTOM crop (HARDCODED) - FRONT rear={front_rear_side} ({fr_x0}-{fr_x1}) | BACK rear={back_rear_side} ({br_x0}-{br_x1})")
        else:
            half_w = crop_w // 2
            (fr_x0, fr_x1), (fw_x0, fw_x1) = _zoom_crop_ranges(container_bounds.get("FRONT"), front_rear_side, 0, half_w)
            (br_x0, br_x1), (bw_x0, bw_x1) = _zoom_crop_ranges(container_bounds.get("BACK"), back_rear_side, half_w, crop_w - half_w)
            mid_h = crop_y_start + int(crop_h * 0.50)
            if front_rear_side == "LEFT":
                rear_crop_front = img.crop((fr_x0, mid_h, fr_x1, crop_y_end))
                front_crop_front = img.crop((fw_x0, crop_y_start, fw_x1, mid_h))
                zoom_crop_rects["rear_FRONT"] = (fr_x0, mid_h, fr_x1, crop_y_end)
                zoom_crop_rects["front_FRONT"] = (fw_x0, crop_y_start, fw_x1, mid_h)
            else:
                rear_crop_front = img.crop((fr_x0, crop_y_start, fr_x1, mid_h))
                front_crop_front = img.crop((fw_x0, mid_h, fw_x1, crop_y_end))
                zoom_crop_rects["rear_FRONT"] = (fr_x0, crop_y_start, fr_x1, mid_h)
                zoom_crop_rects["front_FRONT"] = (fw_x0, mid_h, fw_x1, crop_y_end)
            if back_rear_side == "LEFT":
                rear_crop_back = img.crop((br_x0, mid_h, br_x1, crop_y_end))
                front_crop_back = img.crop((bw_x0, crop_y_start, bw_x1, mid_h))
                zoom_crop_rects["rear_BACK"] = (br_x0, mid_h, br_x1, crop_y_end)
                zoom_crop_rects["front_BACK"] = (bw_x0, crop_y_start, bw_x1, mid_h)
            else:
                rear_crop_back = img.crop((br_x0, crop_y_start, br_x1, mid_h))
                front_crop_back = img.crop((bw_x0, mid_h, bw_x1, crop_y_end))
                zoom_crop_rects["rear_BACK"] = (br_x0, crop_y_start, br_x1, mid_h)
                zoom_crop_rects["front_BACK"] = (bw_x0, mid_h, bw_x1, crop_y_end)
            print(f"LEFT_RIGHT crop (HARDCODED) - FRONT rear={front_rear_side} ({fr_x0}-{fr_x1}) | BACK rear={back_rear_side} ({br_x0}-{br_x1})")

        api_keys_pool = get_api_keys_pool()
        rear_result_front = analyze_rear_zone_with_ai(rear_crop_front, api_keys_pool, "FRONT")
        rear_result_back = analyze_rear_zone_with_ai(rear_crop_back, api_keys_pool, "BACK")
        front_result_from_front_view = analyze_front_zone_with_ai(front_crop_front, api_keys_pool, "FRONT")

        precise_boxes = {}
        for view_label, rear_result, key_prefix in (("FRONT", rear_result_front, "rear_FRONT"), ("BACK", rear_result_back, "rear_BACK")):
            if isinstance(rear_result, dict) and str(rear_result.get("rear_zone_risk", "")).upper() != "SAFE":
                pb = _get_zoom_precise_box(rear_result, "box_2d", zoom_crop_rects[key_prefix], img)
                if pb:
                    rear_zone_risk_val = str(rear_result.get("rear_zone_risk", "")).upper()
                    if rear_zone_risk_val in ("REAR_EMPTY_RISK", "BOTH"):
                        precise_boxes[(view_label, "REAR_EMPTY_RISK")] = pb
                    if rear_zone_risk_val in ("REAR_LATERAL_IMBALANCE", "BOTH"):
                        precise_boxes[(view_label, "REAR_LATERAL_IMBALANCE")] = pb

        if isinstance(front_result_from_front_view, dict) and str(front_result_from_front_view.get("front_zone_risk", "")).upper() == "FRONT_EMPTY_RISK":
            pb = _get_zoom_precise_box(front_result_from_front_view, "box_2d", zoom_crop_rects["front_FRONT"], img)
            if pb:
                precise_boxes[("FRONT", "FRONT_EMPTY_RISK")] = pb

        def _normalize_view(v):
            v = str(v).upper().strip()
            return "GENERAL" if v in ("", "GENERAL") else v

        def _existing_risk_views(risk_type_substr):
            views = set()
            for r in all_risks:
                if risk_type_substr in str(r.get("risk_type", "")).upper():
                    v = _normalize_view(r.get("view", ""))
                    views.add(v)
                    if v == "GENERAL":
                        views.update(["FRONT", "BACK"])
            return views

        gap_values_mm = {}
        gap_values_ratio = {}
        for view_label in ("FRONT", "BACK"):
            gap_values_mm[(view_label, "REAR_EMPTY_RISK")] = compute_empty_gap_mm(
                container_bounds.get(view_label), cargo_extent.get(view_label),
                HARDCODED_REAR_SIDE[view_label], "REAR_EMPTY_RISK", container_length_mm
            )
            gap_values_ratio[(view_label, "REAR_EMPTY_RISK")] = compute_empty_gap_ratio(
                container_bounds.get(view_label), cargo_extent.get(view_label),
                HARDCODED_REAR_SIDE[view_label], "REAR_EMPTY_RISK"
            )

        front_empty_gap_mm_from_front_view = compute_empty_gap_mm(
            container_bounds.get("FRONT"), cargo_extent.get("FRONT"),
            HARDCODED_REAR_SIDE["FRONT"], "FRONT_EMPTY_RISK", container_length_mm
        )
        front_empty_gap_ratio_from_front_view = compute_empty_gap_ratio(
            container_bounds.get("FRONT"), cargo_extent.get("FRONT"),
            HARDCODED_REAR_SIDE["FRONT"], "FRONT_EMPTY_RISK"
        )
        for view_label in ("FRONT", "BACK"):
            gap_values_mm[(view_label, "FRONT_EMPTY_RISK")] = front_empty_gap_mm_from_front_view
            gap_values_ratio[(view_label, "FRONT_EMPTY_RISK")] = front_empty_gap_ratio_from_front_view

        for k in gap_values_mm:
            mm_val = gap_values_mm[k]
            ratio_val = gap_values_ratio[k]
            if mm_val is not None:
                print(f"Deterministic gap for {k[1]} ({k[0]}): {mm_val:.0f}mm (threshold={MIN_EMPTY_GAP_MM}mm)")
            elif ratio_val is not None:
                print(f"Deterministic gap for {k[1]} ({k[0]}): {ratio_val*100:.1f}% (mm calibration unavailable, threshold={FALLBACK_MIN_EMPTY_GAP_RATIO*100:.0f}%)")

        def _passes_deterministic_gate(view_label, risk_type):
            mm_val = gap_values_mm.get((view_label, risk_type))
            if mm_val is not None:
                if mm_val < MIN_EMPTY_GAP_MM:
                    print(f"DETERMINISTIC OVERRIDE (mm-based): {risk_type} ({view_label}) rejected - "
                          f"measured gap={mm_val:.0f}mm < threshold {MIN_EMPTY_GAP_MM}mm (treated as SAFE)")
                    return False
                return True
            ratio_val = gap_values_ratio.get((view_label, risk_type))
            if ratio_val is not None:
                if ratio_val < FALLBACK_MIN_EMPTY_GAP_RATIO:
                    print(f"DETERMINISTIC OVERRIDE (ratio-fallback): {risk_type} ({view_label}) rejected - "
                          f"measured gap_ratio={ratio_val:.3f} < threshold {FALLBACK_MIN_EMPTY_GAP_RATIO}")
                    return False
                return True
            return True

        def _force_gate(view_label, risk_type):
            mm_val = gap_values_mm.get((view_label, risk_type))
            if mm_val is not None:
                return mm_val >= MIN_EMPTY_GAP_MM
            ratio_val = gap_values_ratio.get((view_label, risk_type))
            if ratio_val is not None:
                return ratio_val >= FALLBACK_MIN_EMPTY_GAP_RATIO
            return False

        # v21: ผ่อนเกณฑ์ confidence ของ REAR_LATERAL_IMBALANCE จาก "HIGH เท่านั้น" เป็น
        # "HIGH หรือ MEDIUM" (เดิมเข้มงวดกว่า REAR_EMPTY_RISK โดยไม่มีเหตุผลชัดเจน)
        for view_label, rear_result in (("FRONT", rear_result_front), ("BACK", rear_result_back)):
            rear_result = rear_result if isinstance(rear_result, dict) else {}
            rear_zone_risk = str(rear_result.get("rear_zone_risk", "")).upper()
            confidence = str(rear_result.get("confidence", "LOW")).upper()
            ai_empty = rear_zone_risk in ("REAR_EMPTY_RISK", "BOTH") and confidence in ("HIGH", "MEDIUM")
            forced_empty = _force_gate(view_label, "REAR_EMPTY_RISK")
            if (ai_empty or forced_empty) and view_label not in _existing_risk_views("REAR_EMPTY") and _passes_deterministic_gate(view_label, "REAR_EMPTY_RISK"):
                if forced_empty and not ai_empty:
                    print(f"FORCED REAR_EMPTY_RISK ({view_label}) from deterministic gap (AI said {rear_zone_risk or 'SAFE'})")
                reason = rear_result.get("reasoning", "") if ai_empty else "FORCED_DETERMINISTIC_GAP_MM"
                all_risks.append({"view": view_label, "risk_type": "REAR_EMPTY_RISK", "direction": "LONGITUDINAL", "lateral_side": "N/A", "reasoning": reason, "description": "พบความต่างระดับฝั่งประตูท้ายตู้ (วิเคราะห์จาก Zoom ท้ายตู้)" if ai_empty else "Measured rear-door gap exceeds threshold (deterministic)", "box_2d": None})
            elif ai_empty:
                print(f"Skipping REAR_EMPTY ({view_label}) - confidence={confidence} or gated out")
            # v21: เดิมเงื่อนไขนี้เช็คแค่ confidence=="HIGH" ปรับเป็น in ("HIGH","MEDIUM")
            if rear_zone_risk in ("REAR_LATERAL_IMBALANCE", "BOTH") and confidence in ("HIGH", "MEDIUM") and view_label not in _existing_risk_views("REAR_LATERAL"):
                all_risks.append({"view": view_label, "risk_type": "REAR_LATERAL_IMBALANCE", "direction": "LATERAL", "lateral_side": "N/A", "reasoning": rear_result.get("reasoning", ""), "description": "พบสินค้าท้ายตู้สูงต่ำไม่เท่ากัน (วิเคราะห์จาก Zoom ท้ายตู้)", "box_2d": None})
                print(f"REAR_LATERAL_IMBALANCE ({view_label}) accepted with confidence={confidence}")

        # v22 FORCE: deterministic corroboration สำหรับ REAR_LATERAL_IMBALANCE เฉพาะ
        # กรณีที่ AI บอก SAFE/ไม่ผ่านเกณฑ์ confidence แต่ per-box segmentation เจอ
        # ความไม่สมดุลชัดเจนในโซนประตูท้ายตู้ (ไม่ veto AI เพราะ AI อาจเห็นตั้งที่ถูก
        # บังซึ่ง pixel-based มองไม่เห็น - ดูข้อจำกัดในหัวข้อ PER-BOX SEGMENTATION)
        for view_label in ("FRONT", "BACK"):
            if view_label in _existing_risk_views("REAR_LATERAL"):
                continue
            rear_side = HARDCODED_REAR_SIDE[view_label]
            cb = container_bounds.get(view_label)
            if not cb:
                continue
            container_width = cb["xmax"] - cb["xmin"]
            if rear_side == "LEFT":
                rear_x0, rear_x1 = cb["xmin"], cb["xmin"] + int(container_width * 0.45)
            else:
                rear_x0, rear_x1 = cb["xmax"] - int(container_width * 0.45), cb["xmax"]
            det_regions = detect_lateral_imbalance_regions_for_view(stack_box_model.get(view_label, []), rear_x0, rear_x1)
            for region in det_regions:
                if region["ratio"] < LATERAL_IMBALANCE_MIN_RATIO:
                    continue
                print(f"FORCED REAR_LATERAL_IMBALANCE ({view_label}) from deterministic per-box segmentation "
                      f"(height_diff_ratio={region['ratio']*100:.0f}%, AI said SAFE or low-confidence)")
                all_risks.append({
                    "view": view_label, "risk_type": "REAR_LATERAL_IMBALANCE",
                    "direction": "LATERAL", "lateral_side": "N/A",
                    "reasoning": "FORCED_DETERMINISTIC_PER_BOX_LATERAL_IMBALANCE",
                    "description": f"พบสินค้าท้ายตู้สูงต่ำไม่เท่ากันประมาณ {region['ratio']*100:.0f}% (ตรวจจับจาก per-box segmentation, AI ไม่พบ)",
                    "box_2d": None,
                })
                break  # 1 กรอบต่อ view ก็เพียงพอสำหรับ zone-based risk นี้

        front_conf = str(front_result_from_front_view.get("confidence", "LOW")).upper() if isinstance(front_result_from_front_view, dict) else "LOW"
        ai_front = (isinstance(front_result_from_front_view, dict)
                    and str(front_result_from_front_view.get("front_zone_risk", "")).upper() == "FRONT_EMPTY_RISK"
                    and front_conf in ("HIGH", "MEDIUM"))
        for view_label in ("FRONT", "BACK"):
            forced_front = _force_gate(view_label, "FRONT_EMPTY_RISK")
            if (ai_front or forced_front) and view_label not in _existing_risk_views("FRONT_EMPTY") and _passes_deterministic_gate(view_label, "FRONT_EMPTY_RISK"):
                if forced_front and not ai_front:
                    print(f"FORCED FRONT_EMPTY_RISK ({view_label}) from deterministic gap measured via FRONT view (AI said SAFE)")
                reason = front_result_from_front_view.get("reasoning", "") if (ai_front and isinstance(front_result_from_front_view, dict)) else "FORCED_DETERMINISTIC_GAP_MM_FROM_FRONT_VIEW"
                all_risks.append({"view": view_label, "risk_type": "FRONT_EMPTY_RISK", "direction": "LONGITUDINAL", "lateral_side": "N/A", "reasoning": reason, "description": "พบสินค้าต่างระดับฝั่งผนังหัวตู้ (วิเคราะห์จาก Front view เป็นหลัก)" if ai_front else "Measured front-wall gap (via FRONT view) exceeds threshold (deterministic)", "box_2d": None})
            elif ai_front:
                print(f"Skipping FRONT_EMPTY ({view_label}) - gated out")

        for view_label in ("FRONT", "BACK"):
            lateral_gap_mm = compute_lateral_gap_mm(container_bounds.get(view_label), cargo_extent.get(view_label), container_length_mm)
            lateral_gap_ratio = compute_lateral_gap_ratio(container_bounds.get(view_label), cargo_extent.get(view_label))

            should_flag_lateral = False
            gap_display = ""
            if lateral_gap_mm is not None:
                print(f"Deterministic lateral gap for LATERAL_GAP_RISK ({view_label}): {lateral_gap_mm:.0f}mm (threshold={MIN_LATERAL_GAP_MM}mm)")
                should_flag_lateral = lateral_gap_mm >= MIN_LATERAL_GAP_MM
                gap_display = f"{lateral_gap_mm/10:.0f} ซม."
            elif lateral_gap_ratio is not None:
                print(f"Deterministic lateral gap for LATERAL_GAP_RISK ({view_label}): {lateral_gap_ratio*100:.1f}% "
                      f"(mm calibration unavailable, using ratio fallback, threshold={FALLBACK_MIN_LATERAL_GAP_RATIO*100:.0f}%)")
                should_flag_lateral = lateral_gap_ratio >= FALLBACK_MIN_LATERAL_GAP_RATIO
                gap_display = f"{lateral_gap_ratio*100:.0f}% ของความสูงโครงสร้างตู้"
            else:
                print(f"WARNING: Could not compute lateral gap for {view_label} (missing container_bounds or cargo_extent)")

            if should_flag_lateral and view_label not in _existing_risk_views("LATERAL_GAP"):
                print(f"FORCED LATERAL_GAP_RISK ({view_label}) from deterministic side-floor gap measurement")
                all_risks.append({"view": view_label, "risk_type": "LATERAL_GAP_RISK", "direction": "LATERAL", "lateral_side": "N/A", "reasoning": "FORCED_DETERMINISTIC_LATERAL_GAP", "description": f"พบพื้นที่ว่างด้านข้างบนพื้นตู้ประมาณ {gap_display} (เกินเกณฑ์ความปลอดภัย)", "box_2d": None})

        for view_label in ("FRONT", "BACK"):
            for region in step_down_regions.get(view_label, []):
                if region["ratio"] < MIN_STEP_DOWN_RATIO:
                    continue
                already_covered = False
                for r in all_risks:
                    if str(r.get("risk_type", "")).upper().strip() != "STEP_DOWN_RISK":
                        continue
                    if str(r.get("view", "")).upper().strip() != view_label:
                        continue
                    r_box = r.get("box_2d")
                    if not r_box:
                        continue
                    try:
                        ymin, xmin, ymax, xmax = map(float, r_box)
                        if max(ymin, xmin, ymax, xmax) <= 1.0:
                            ymin, xmin, ymax, xmax = ymin*1000, xmin*1000, ymax*1000, xmax*1000
                        abs_xmin = (xmin/1000.0)*crop_w; abs_xmax = (xmax/1000.0)*crop_w
                        abs_ymin = crop_y_start + (ymin/1000.0)*crop_h; abs_ymax = crop_y_start + (ymax/1000.0)*crop_h
                        overlap = _box_iou_absolute((region["x_min"], region["y_min"], region["x_max"], region["y_max"]),
                                                      (abs_xmin, abs_ymin, abs_xmax, abs_ymax))
                        if overlap >= 0.15:
                            already_covered = True
                            break
                    except Exception:
                        continue
                if already_covered:
                    continue
                x0, y0, x1, y1 = region["x_min"], region["y_min"], region["x_max"], region["y_max"]
                ymin_norm = ((y0 - crop_y_start) / crop_h) * 1000
                ymax_norm = ((y1 - crop_y_start) / crop_h) * 1000
                xmin_norm = (x0 / crop_w) * 1000
                xmax_norm = (x1 / crop_w) * 1000
                print(f"FORCED STEP_DOWN_RISK ({view_label}) from deterministic height-profile discontinuity "
                      f"(height_diff_ratio={region['ratio']*100:.1f}%)")
                all_risks.append({
                    "view": view_label, "risk_type": "STEP_DOWN_RISK",
                    "box_2d": [ymin_norm, xmin_norm, ymax_norm, xmax_norm],
                    "reasoning": "FORCED_DETERMINISTIC_HEIGHT_PROFILE_STEP",
                    "description": f"พบความต่างระดับระหว่างกองสินค้าประมาณ {region['ratio']*100:.0f}% ของความสูงตู้ (ตรวจจับจาก height-profile analysis)",
                })

        all_risks = _merge_same_area_risks(all_risks)

        draw = PIL.ImageDraw.Draw(img)
        detected_hazards = []
        reported_risk_keys = set()

        half_h_local = crop_h // 2
        mid_y_local = crop_y_start + half_h_local
        half_w_local = crop_w // 2

        for risk in all_risks:
            raw_risk_type = str(risk.get("risk_type", "")).upper().strip()
            view_name = _normalize_view(risk.get("view", "GENERAL"))

            if raw_risk_type in ("REAR_COMBINED_RISK", "COMBINED_AREA_RISK"):
                matched_type = raw_risk_type
            elif raw_risk_type == "ERROR":
                detected_hazards.append({"title": "ข้อผิดพลาด API", "detail": risk.get("description", "โปรดตรวจสอบโควตา Gemini API Keys"), "is_error": True})
                continue
            else:
                matched_type = next((vrt for vrt in VALID_RISK_TYPES if vrt not in ("REAR_COMBINED_RISK", "COMBINED_AREA_RISK") and (vrt.replace("_RISK", "") in raw_risk_type or raw_risk_type in vrt)), None)
            if not matched_type:
                continue

            risk_type = matched_type
            fallback_risk_type = risk.get("fallback_risk_type", risk_type)
            draw_colors = risk.get("draw_colors", None)
            outline_color = RISK_COLORS.get(risk_type, "red")

            resolved_view = view_name if view_name != "GENERAL" else "FRONT"
            box = risk.get("box_2d") or risk.get("boundingBox") or risk.get("box")
            if view_name == "GENERAL" and box and isinstance(box, list) and len(box) == 4:
                try:
                    _ymin, _xmin, _ymax, _xmax = map(float, box)
                    if max(_ymin, _xmin, _ymax, _xmax) <= 1.0:
                        _ymin, _xmin, _ymax, _xmax = _ymin * 1000, _xmin * 1000, _ymax * 1000, _xmax * 1000
                    _cx = (_xmin + _xmax) / 2 * crop_w / 1000.0
                    _cy = crop_y_start + (_ymin + _ymax) / 2 * crop_h / 1000.0
                    if layout == "LEFT_RIGHT":
                        resolved_view = "FRONT" if _cx < crop_w * 0.50 else "BACK"
                    else:
                        resolved_view = "FRONT" if _cy < mid_y_local else "BACK"
                except Exception:
                    pass

            drawn = False
            is_zone_based = fallback_risk_type in ZONE_BASED_RISK_TYPES or risk_type == "COMBINED_AREA_RISK"

            if is_zone_based and risk_type != "COMBINED_AREA_RISK":
                precise = precise_boxes.get((resolved_view, risk_type))
                if precise:
                    _draw_single_or_dual_rectangle(draw, precise, outline_color, draw_colors)
                    drawn = True

            if not drawn and not is_zone_based and box and isinstance(box, list) and len(box) == 4:
                try:
                    ymin, xmin, ymax, xmax = map(float, box)
                    if max(ymin, xmin, ymax, xmax) <= 1.0:
                        ymin, xmin, ymax, xmax = ymin * 1000, xmin * 1000, ymax * 1000, xmax * 1000
                    abs_xmin = max(0, min(int(xmin * crop_w / 1000.0), crop_w - 1))
                    abs_xmax = max(abs_xmin + 1, min(int(xmax * crop_w / 1000.0), crop_w))
                    abs_ymin = max(crop_y_start, min(int(crop_y_start + (ymin * crop_h / 1000.0)), crop_y_end - 1))
                    abs_ymax = max(abs_ymin + 1, min(int(crop_y_start + (ymax * crop_h / 1000.0)), crop_y_end))

                    if layout == "TOP_BOTTOM":
                        crosses_boundary = (abs_ymax > mid_y_local) if resolved_view == "FRONT" else (abs_ymin < mid_y_local)
                    else:
                        crosses_boundary = (abs_xmax > half_w_local) if resolved_view == "FRONT" else (abs_xmin < half_w_local)
                    if crosses_boundary:
                        raise ValueError("box crosses FRONT/BACK boundary - rejected")

                    box_w_ratio = (abs_xmax - abs_xmin) / crop_w
                    box_h_ratio = (abs_ymax - abs_ymin) / crop_h
                    box_too_small = box_w_ratio < 0.03 or box_h_ratio < 0.03
                    box_too_large = box_w_ratio > 0.55 or box_h_ratio > 0.55
                    if box_too_small or box_too_large:
                        raise ValueError(f"box size invalid (w={box_w_ratio:.2f}, h={box_h_ratio:.2f}) - rejected")

                    _draw_single_or_dual_rectangle(draw, [abs_xmin, abs_ymin, abs_xmax, abs_ymax], outline_color, draw_colors)
                    drawn = True
                except Exception as e:
                    print(f"box_2d rejected for {risk_type} ({resolved_view}): {e}")

            if not drawn:
                fallback = _get_fallback_box(fallback_risk_type, resolved_view, layout, crop_w, crop_y_start, crop_h,
                                              container_bounds=container_bounds, cargo_extent=cargo_extent)
                if fallback:
                    _draw_single_or_dual_rectangle(draw, fallback, outline_color, draw_colors)
                    drawn = True
            if not drawn:
                print(f"Could not draw box for {risk_type} ({resolved_view})")

            report_key = "+".join(risk.get("merged_risk_types", [risk_type])) if risk_type == "COMBINED_AREA_RISK" else risk_type
            if report_key not in reported_risk_keys:
                reported_risk_keys.add(report_key)
                if risk_type == "COMBINED_AREA_RISK":
                    merged_names = risk.get("merged_risk_types", [])
                    title = "ความเสี่ยงร่วม: " + " + ".join(merged_names)
                    parts = [generate_action_report(rt, "", sku_str) for rt in merged_names]
                    detail = "\n\n".join(parts) if parts else (risk.get("description", "") or "พบหลายความเสี่ยงในบริเวณเดียวกัน")
                elif risk_type == "REAR_COMBINED_RISK":
                    title = "ความเสี่ยง: REAR_EMPTY_RISK + REAR_LATERAL_IMBALANCE (บริเวณประตูท้ายตู้เดียวกัน)"
                    detail = generate_action_report(risk_type, risk.get("description", ""), sku_str)
                else:
                    title = f"ความเสี่ยง: {risk_type}"
                    detail = generate_action_report(risk_type, risk.get("description", ""), sku_str)
                detected_hazards.append({"title": title, "detail": detail, "is_error": False})

        real_hazards = [h for h in detected_hazards if not h.get("is_error")]
        error_hazards = [h for h in detected_hazards if h.get("is_error")]
        sep = "\n\n" + "-" * 50 + "\n\n"
        if real_hazards:
            status_text = f"พบจุดเสี่ยงอันตราย ({len(real_hazards)} จุด)"
            action_text = sep.join(f"[{h['title']}]\n{h['detail']}" for h in real_hazards)
        elif error_hazards:
            status_text = "เกิดข้อผิดพลาดในการวิเคราะห์ AI"
            action_text = sep.join(f"[{h['title']}]\n{h['detail']}" for h in error_hazards)
        else:
            status_text = "ปลอดภัย (SAFE)"
            action_text = generate_action_report("SAFE", "")

        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=80)
        processed_image_url = f"data:image/jpeg;base64,{base64.b64encode(buffered.getvalue()).decode('utf-8')}"
        gc.collect()
        return ({"status": status_text, "hazardCount": len(real_hazards), "layout": layout, "actionRequired": action_text, "processedImageUrl": processed_image_url}, 200, headers)
    except Exception as e:
        err_trace = traceback.format_exc()
        print("CRITICAL ERROR DETAILS:\n", err_trace)
        gc.collect()
        return ({"error": str(e), "trace": err_trace[-500:]}, 500, headers)
