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
# AI Cargo Safety Checker - High Precision v24.10
# v24.10 - AutoGeminiPool + StepDownFix: Gemini 3.7/3.6/3.5 fallback, quota cache, no STEP_DOWN merge, strongest pair only, boundary marker only.
# v24.07 - OverhangAuditStepDownFix: OVERHANG audit-only until segmentation is trusted; add stack-adjacent STEP_DOWN detector for AA04-05 style risk.
# v24.06 - OverhangFivePercentGuard: OVERHANG requires upper/lower stacked box size mismatch >= 5%, no edge/fallback markers.
# v24.05 - RearLateralImbalanceTune: tune BACK-frame marker to visible stacked cargo, emit deterministic box_2d, and avoid lower-floor fallback for rear lateral.
# v24.04 - OverhangStackSizeGuard: redefine OVERHANG as visible stacked-box size/support mismatch, suppress isometric edge-only artifacts.
# v24.03 - LocalizationFix: OVERHANG pair-box validation, BACK rear-lateral final-shift, strict inter-stack lateral-gap: OVERHANG cause-box, BACK REAR_LATERAL box shift up 50%, inter-stack-only LATERAL_GAP.
# v24.01 - TallUnstableGuard: strict deterministic gate for TALL_UNSTABLE_RISK only. Other risk detectors unchanged.
#
# v24 - แก้ปัญหา ROOT CAUSE สำคัญที่สุดที่พบจากการตรวจสอบ /ooda /scout กับไฟล์จริง 6
#   ไฟล์ (ED85-02, ED86-03, EC51-02, EC50-01, EC20-01, EC25-01) ที่ผู้ใช้รายงานว่า
#   วิเคราะห์ผิดพลาด:
#
#   ROOT CAUSE: ฟังก์ชันแบ่ง "ตั้ง" (stack) และ "กล่อง" (box) ในเวอร์ชัน v22/v23.1
#   (detect_stack_columns, detect_boxes_in_stack) ใช้แค่ _find_dark_boundary_lines_1d
#   (หา "dip" สีเข้มแคบๆ) เพื่อหาตำแหน่งรอยต่อ ซึ่งใช้ได้ผลเฉพาะกรณีกล่อง 2 ใบสี
#   เดียวกันมีเส้นขอบมืดบางๆ คั่นเท่านั้น แต่ในสถานการณ์จริงส่วนใหญ่ กล่องแต่ละใบ/แต่ละ
#   SKU มักมีสีต่างกันชัดเจน (เช่น น้ำเงิน->ชมพู->เขียวมะกอก->เขียว, หรือกล่องสีน้ำตาล
#   เข้ม/สีเหลืองที่ผู้ใช้สังเกตว่า "มันหลอก") ซึ่งสร้าง "step change" ถาวรในค่าสี ไม่ใช่
#   dip แคบ ทำให้ตรวจจับพลาดเกือบทั้งหมด นำไปสู่การรวมหลายตั้ง/กล่องเข้าด้วยกันผิดพลาด
#   (under-segmentation รุนแรง - ยืนยันแล้วว่าบางไฟล์ทั้ง BACK view ถูกรวมเป็นแค่ 2
#   ก้อนใหญ่ ทั้งที่ควรจะมี 6-7 ตั้งแยกกัน) ทำให้การคำนวณความสูงผิดพลาดรุนแรง และเป็น
#   สาเหตุหลักที่ deterministic per-box segmentation ไม่สามารถ FORCE/VETO ผลของ AI ได้
#   อย่างน่าเชื่อถือ (เพราะข้อมูลเปรียบเทียบเองก็ผิดตั้งแต่ต้น)
#
#   วิธีแก้: เพิ่มสัญญาณตรวจจับ boundary อีก 2 ชนิด รวมกับของเดิม (union แทนที่):
#     1. COLOR-STEP boundary: เปรียบเทียบสี RGB เฉลี่ย (หลัง median smoothing เพื่อกรอง
#        สัญญาณรบกวนจากไฮไลท์/เงาสะท้อน) ระหว่างตำแหน่งที่ติดกัน หากต่างกันเกิน
#        threshold (Euclidean distance ใน RGB space) และสีใหม่นี้คงอยู่ต่อเนื่อง (ไม่ใช่
#        สัญญาณรบกวนชั่วขณะ) ถือเป็นรอยต่อกล่อง/ตั้งจริง
#     2. FLOOR/EDGE-JUMP boundary: เปรียบเทียบตำแหน่ง local floor (แนวนอน) หรือความกว้าง
#        ของขอบซ้าย/ขวา (แนวตั้ง) ระหว่างตำแหน่งที่ติดกัน (หลัง median smoothing) หาก
#        กระโดดขึ้น/ลงมากพอ แสดงว่าเป็นรอยต่อระหว่างกล่อง/ตั้งที่ความสูงต่างกัน แม้จะมี
#        สีเดียวกันก็ตาม (กรณีนี้ color-step จะไม่ trigger เพราะสีไม่เปลี่ยน)
#   ทั้ง dark-dip (เดิม) + color-step (ใหม่) + floor/edge-jump (ใหม่) ทำงานร่วมกันแบบ
#   union (พบจากสัญญาณใดสัญญาณหนึ่งก็ถือว่าเป็นรอยต่อ) ทดสอบยืนยันแล้วว่าการรวม 3
#   สัญญาณช่วยแยกตั้ง/กล่องได้ถูกต้องมากขึ้นอย่างมีนัยสำคัญในทุกไฟล์ทดสอบ โดยไม่ลบ
#   ความสามารถเดิมออก (net improvement เทียบกับ v23.1)
#
#   เพิ่มเติม: เพิ่ม VETO GATE สำหรับ REAR_LATERAL_IMBALANCE - เดิม (v21-v23.1) เลือก
#   ใช้ FORCE เท่านั้น (ไม่ veto AI) เพราะกลัวว่า deterministic per-box segmentation ที่
#   (ตอนนั้น) ยังไม่แม่นยำพอจะ veto ผิดพลาดในกรณีที่มี occlusion จริง แต่เมื่อการแบ่ง
#   ตั้ง/กล่องแม่นยำขึ้นมากจากการแก้ไข v24 นี้แล้ว จึงเพิ่ม VETO แบบมีเงื่อนไข: ถ้า
#   deterministic segmentation มี coverage สูง (ผ่านเกณฑ์) และวัดได้ว่าความสูงระหว่าง
#   ตั้งที่ AI อ้างว่าต่างกันจริง ๆ ใกล้เคียงกัน (ไม่เกิน threshold) ให้ veto การอ้างของ
#   AI (นี่คือสาเหตุของปัญหา ED85-02/EC20-01 ที่ AI สับสนจากสีเข้ม/สีผิดปกติ จนรายงาน
#   REAR_LATERAL_IMBALANCE ผิดพลาดทั้งที่ deterministic วัดว่าไม่มีความแตกต่างจริง)
#
#   ปรับปรุง AI PROMPT: เพิ่มคำเตือนเฉพาะเจาะจงเรื่องกล่องสีเข้ม (dark brown/maroon)
#   หรือสีที่ไม่คุ้นเคยอาจถูกมองข้ามไปว่าไม่ใช่คาร์โก้ (เข้าใจผิดว่าเป็นเงา/พื้นหลัง)
#   ต้องพิจารณาว่าเป็นคาร์โก้จริงเสมอหากมีขอบเขตชัดเจนและมี SKU label กำกับ
#
#   ข้อจำกัดที่ยังคงเหลืออยู่ (ยืนยันจากการทดสอบ พบว่าเป็นข้อจำกัดพื้นฐาน ไม่ใช่บั๊ก):
#   - OCCLUSION: กรณีที่กล่องชั้นบนของตั้งหนึ่งถูกกล่องอื่นบังจนมองไม่เห็นจากมุมมอง
#     ใดมุมมองหนึ่ง (ยืนยันจากไฟล์ EC51-02: กล่อง TEM1A-DZ สูง 2 ชั้นจริง ยืนยันจาก
#     FRONT view แต่ BACK view มองเห็นแค่ 1 ชั้นเนื่องจากมุมมอง/การบัง) - ทั้ง AI และ
#     deterministic pixel-analysis ไม่สามารถ "มองทะลุ" สิ่งที่บังอยู่ได้ เป็นข้อจำกัด
#     พื้นฐานของการวิเคราะห์ภาพ 2D projection
#   - SAME-COLOR ADJACENT STACKS: ตั้งหลายอันที่มีสีเดียวกันสนิทติดกัน (เช่น กล่องสีม่วง
#     5 ตั้งติดกัน) ยังคงอาศัย dark-dip (เส้นขอบมืดบางๆ) เป็นหลักในการแยก ซึ่งบางครั้ง
#     อาจแยกได้ไม่ครบทุกเส้นถ้าเส้นขอบไม่ชัดเจนพอ (ไม่กระทบผลลัพธ์ความเสี่ยงมากนัก
#     เพราะตั้งที่ under-segment มักมีความสูงใกล้เคียงกันอยู่แล้ว)
#   - THRESHOLD TUNING: บางกรณี (เช่น ED86-03) ค่าที่วัดได้ใกล้เคียง threshold มาก
#     (11.6% vs เกณฑ์ 12% สำหรับ LATERAL_GAP_RISK) ซึ่งเป็นเรื่องการปรับจูนค่าคงที่
#     มากกว่าจะเป็นบั๊กเชิงโครงสร้าง - ควรพิจารณาปรับลด FALLBACK_MIN_LATERAL_GAP_RATIO
#     ลงเล็กน้อยหากพบว่ากรณีแบบนี้เกิดขึ้นบ่อย (ปัจจุบันยังไม่ปรับเพื่อป้องกัน false
#     positive ใหม่ในไฟล์อื่นที่เคยผ่านมาแล้ว)
#
# v23.1 - แก้ปัญหา FRONT view โดยเปลี่ยนแนวทางจาก "แบบจำลองเส้นตรงทั่วโลก" (global
#   floor-line V-shape) เป็น "LOCAL FLOOR" (พื้นเฉพาะจุด คำนวณจากพิกเซลคาร์โก้จริงใน
#   แต่ละคอลัมน์/ตั้งโดยตรง) - ดูรายละเอียดในฟังก์ชัน build_stack_box_model_per_view
# v23 - แก้ปัญหา "PERSPECTIVE/ISOMETRIC FLOOR" (พื้นตู้เป็นรูปตัว V ไม่ใช่เส้นแนวนอน)
# v22 - พัฒนา PER-BOX SEGMENTATION (deterministic) สำหรับ OVERHANG_RISK,
#   TALL_UNSTABLE_RISK, REAR_LATERAL_IMBALANCE ที่เดิมพึ่ง AI 100% ใน v21
# v21 - ผ่อนเกณฑ์ confidence ของ REAR_LATERAL_IMBALANCE + ปรับปรุง prompt
# v20.1 - แก้บั๊ก extract_container_length_mm() ดึงค่าผิดจากบรรทัด COG
# v19 - เพิ่ม GATE (veto) สำหรับ STEP_DOWN_RISK ที่ Gemini claim มา
# v18 - เพิ่มกลไก deterministic (height-profile) สำหรับ STEP_DOWN_RISK (FORCE)
# v17 - แก้บั๊ก LATERAL_GAP_RISK ไม่ทำงานเมื่อคาลิเบรต mm ไม่สำเร็จ (ratio fallback)
# v16 - เพิ่ม LATERAL_GAP_RISK deterministic + FRONT_EMPTY_RISK ใช้ Front view
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

# ==========================
# V24.10 Gemini Auto Model Pool
# ==========================
GEMINI_MODEL_POOL = [
    "gemini-3.7-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash",
]
LAST_WORKING_MODEL = None
MODEL_DISABLED_UNTIL = {}
MODEL_COOLDOWN_SECONDS = 1800

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
UNUSED_FLOOR_MIN_MM = 100          # v24.1: ค่า "Unused Floor" จาก PDF ต้อง >=100mm
                                    # (~4in) จึงถือว่ามีนัยสำคัญพอจะใช้ผ่อนเกณฑ์ gap
                                    # ratio (กันค่าเล็กน้อยจากการปัดเศษ/พื้นที่ว่าง
                                    # เล็กน้อยที่ยอมรับได้ตามปกติ)
UNUSED_FLOOR_RELAXED_GAP_RATIO = 0.06  # เกณฑ์ผ่อนลงครึ่งหนึ่งจาก 12% ปกติ - ใช้เฉพาะ
                                    # เมื่อมี "Unused Floor" ยืนยันจาก PDF โดยตรงเท่านั้น
                                    # (ไม่ใช่ค่าที่ใช้ทั่วไปโดยไม่มีหลักฐานยืนยัน)

# v24.3 NEW: LOCAL DEPTH-GAP SCAN - ตรวจจับ "หลุมเฉพาะจุด" (localized floor gap) ที่
# เดิม LATERAL_GAP_RISK (คำนวณจาก whole-container average) พลาดไป
#
# ROOT CAUSE ที่พบ (ผู้ใช้ชี้ตำแหน่งด้วยการวงสีแดงใน EC50-01, EC51-02): ค่า
# compute_lateral_gap_ratio() เดิมเปรียบเทียบ "กรอบสี่เหลี่ยมรวมทั้งภาพ" (container
# bounds ymax เทียบ cargo extent ymax) เป็นตัวเลขเดียว ซึ่งไม่ไวพอจะจับ "หลุม" ที่เกิด
# ขึ้นเฉพาะบางตำแหน่ง x เพราะตำแหน่งอื่นที่กล่องยื่นลึกกว่า (จากมุมมอง isometric ที่
# พื้นตู้เป็นรูปคลื่น) จะ "กลบ" ค่าเฉลี่ยรวมจนดูเหมือนไม่มีปัญหา ยืนยันด้วยพิกเซลจริง:
# ตรวจสอบ EC50-01/EC51-02 พบช่องว่างเฉพาะจุดลึกถึง 63-69px ณ ตำแหน่งกลางตั้ง แต่ค่า
# lateral_gap_ratio ที่คำนวณแบบเดิมออกมาแค่ ~10% (ไม่ถึงเกณฑ์ 12%)
#
# วิธีแก้: สแกน "ช่องว่างเฉพาะจุด" (local gap = โครงสร้างตู้ที่ต่ำสุด ณ ตำแหน่ง x นั้น
# ลบด้วยขอบล่างคาร์โก้ ณ ตำแหน่ง x เดียวกัน) ตลอดความกว้างคาร์โก้ แล้วหาช่วงที่ค่านี้
# "สูงต่อเนื่องเป็นบริเวณกว้าง" (ไม่ใช่จุดเดียวโดดๆ) ซึ่งบ่งชี้หลุมจริง
#
# ข้อควรระวังสำคัญ (พบจากการทดสอบไฟล์จริง) - มี 2 แหล่งสัญญาณรบกวนหลักที่ต้องกรอง:
#   1. ป้ายบอกระยะทาง/ตัวเลข (เช่น "0.9", "1.8", "2.7") ที่วาดทับพื้นหลังสีขาว สร้าง
#      "จุดกระโดดสูงโดดๆ" (spike) ในสัญญาณ ไม่ใช่หลุมต่อเนื่อง - กรองด้วย (ก) median
#      smoothing หน้าต่างกว้าง (11px) และ (ข) เช็ค "ความขรุขระ" (roughness) ของสัญญาณ
#      ดิบ (ไม่ smooth) ภายในช่วงที่ตรวจพบ - หลุมจริงมีรูปทรงสามเหลี่ยมลาดเอียงสม่ำเสมอ
#      (roughness ต่ำ) ในขณะที่ noise จะกระโดดสลับไปมา (roughness สูง)
#   2. โซนผนังหัวตู้/ประตูท้ายตู้ (ริมทั้ง 2 ข้างของคาร์โก้) มีแผงโครงสร้างตู้ทึบที่ทำให้
#      เกิด "gap ปลอม" ขนาดใหญ่คงที่เสมอ (~166-170px) ในทุกไฟล์แม้แต่ไฟล์ที่ปลอดภัย
#      100% (ยืนยันจาก EC20-01) เพราะแผงนี้ไม่ใช่ตัวชี้วัดพื้นที่ว่างจากการโหลดสินค้า
#      แต่เป็นโครงสร้างที่มีอยู่แล้วโดยธรรมชาติ (มีกลไก FRONT_EMPTY_RISK/
#      REAR_EMPTY_RISK แยกต่างหากดูแลโซนนี้อยู่แล้ว) - จึง "ตัดโซนริม" ทั้ง 2 ข้างออก
#      จากการสแกน (เหลือแค่ส่วนกลาง ~65% ของความกว้างคาร์โก้)
LOCAL_GAP_SAMPLE_STEP_PX = 5
LOCAL_GAP_SEARCH_MARGIN_PX = 20        # ขยายขอบเขตค้นหา (บน/ล่าง) เผื่อพื้นตู้/คาร์โก้
                                        # ไม่ได้อยู่พอดีกับ container_bounds/cargo_extent
LOCAL_GAP_SMOOTH_WINDOW = 11
LOCAL_GAP_MIN_PX = 15                  # ช่องว่างเฉพาะจุด (หลัง smooth) ขั้นต่ำที่ถือว่า
                                        # น่าสงสัย
LOCAL_GAP_MIN_WIDTH_PX = 60             # ต้องกว้างต่อเนื่องอย่างน้อยเท่านี้ (px) จึงจะ
                                        # ถือว่าเป็นหลุมจริง (ไม่ใช่จุดเดียวโดดๆ)
LOCAL_GAP_MIN_RAW_COVERAGE = 0.65       # สัดส่วนของจุดข้อมูลดิบ (ไม่ smooth) ในช่วงที่
                                        # ตรวจพบ ต้องมีค่าเกิน LOCAL_GAP_RAW_LOWER_THRESH
                                        # อย่างน้อยเท่านี้ (กัน noise ที่ smooth รวมกัน)
LOCAL_GAP_RAW_LOWER_THRESH = 8
LOCAL_GAP_MAX_ROUGHNESS = 0.35          # ความขรุขระสูงสุดที่ยอมรับได้ (ดู comment ด้านบน)
LOCAL_GAP_WALL_ZONE_MARGIN_RATIO = 0.20  # ตัดโซนผนังหัวตู้ออก (สัดส่วนความกว้างคาร์โก้)
LOCAL_GAP_DOOR_ZONE_MARGIN_RATIO = 0.15  # ตัดโซนประตูท้ายตู้ออก (สัดส่วนความกว้างคาร์โก้)

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
    ค่าความยาวตู้เดี่ยวๆ แบบ "N (mm)" ที่ label เส้นบอกขนาดในภาพ diagram ใช้
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


def extract_unused_floor_mm(pdf_bytes: bytes):
    """
    ดึงค่า "Unused Floor: X (in)" จาก PDF text - เป็นตัวเลขที่ MaxLoad Pro พิมพ์ไว้บน
    หน้า manifest โดยตรง (GROUND TRUTH ที่แม่นยำ 100% ไม่ต้องพึ่งพา pixel measurement
    เลย) บอกว่ามีพื้นที่พื้นตู้ว่างไม่ได้ใช้เท่าใด (หน่วยนิ้ว)

    v24.1 NEW (พบระหว่างการตรวจสอบ /ooda /scout): เดิมระบบไม่เคยใช้ค่านี้เลย ทั้งที่
    เป็นสัญญาณที่แม่นยำที่สุดสำหรับ LATERAL_GAP_RISK/FRONT_EMPTY_RISK/REAR_EMPTY_RISK
    - ยืนยันจากไฟล์จริง: ED86-03 และ EC25-01 (ที่ผู้ใช้รายงานว่า "มี gap แต่ไม่ระบุ")
    ทั้งคู่มีค่า "Unused Floor" ที่ไม่ใช่ศูนย์ (17.7in, 18.9in ตามลำดับ) ในขณะที่ไฟล์
    อื่นๆ ที่ไม่มีปัญหาเรื่อง gap (EC20-01, EC50-01, EC51-02, ED85-02) ล้วนมีค่า
    "Unused Floor: 0 (in)" ตรงกันทุกไฟล์ - เป็นความสัมพันธ์ที่ชัดเจนมาก

    หมายเหตุ: ข้อความ "Unused Floor:" และค่าตัวเลข "X (in)" มักอยู่คนละบรรทัดใน PDF
    text stream (เพราะ PDF จัดเรียงข้อความตามตำแหน่งพิกัด ไม่ใช่ตามลำดับที่อ่านเข้าใจ)
    จึงค้นหาแบบ "หลังจากเจอบรรทัด 'Unused Floor' ให้สแกนต่ออีก 2-5 บรรทัดถัดไป หา
    pattern ตัวเลขตามด้วย (in)" แทนการค้นหาในบรรทัดเดียวกัน
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_index = 1 if len(doc) >= 2 else 0
        page = doc[page_index]
        lines = page.get_text("text").splitlines()
        for i, line in enumerate(lines):
            if "unused floor" in line.lower():
                for j in range(i, min(i + 5, len(lines))):
                    m = re.search(r"([\d.]+)\s*\(\s*in\s*\)", lines[j], flags=re.IGNORECASE)
                    if m:
                        inches = float(m.group(1))
                        mm = inches * 25.4
                        print(f"Unused Floor extracted from PDF text: {inches}in ({mm:.0f}mm)")
                        return mm
                break
        print("WARNING: Could not find 'Unused Floor' value in PDF text")
        return None
    except Exception as e:
        print(f"WARNING: Unused Floor extraction failed ({e})")
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


def get_precise_lateral_gap_box(view_container, view_cargo):
    """
    v24.2 NEW: คำนวณตำแหน่งกรอบที่แม่นยำสำหรับ LATERAL_GAP_RISK (deterministic) แทนที่
    จะใช้ fallback แบบทั่วไป (percentage-based zone ที่ครอบคลุมกลางคาร์โก้)

    ROOT CAUSE ที่พบจากการตรวจสอบภาพจริงร่วมกับผู้ใช้ (ED86-03): เดิมค่า "lateral gap"
    คำนวณจากแค่ "ผลต่างความสูงรวม" (container_y_span - cargo_y_span) โดยไม่ได้ระบุว่า
    ช่องว่างอยู่ฝั่งไหน (บนหรือล่าง) ทำให้เมื่อวาดกรอบ ระบบไม่มีข้อมูลพอจะชี้ตำแหน่งที่
    แม่นยำ จึงตกไปใช้ fallback แบบ percentage-based ที่ครอบคลุมกลางคาร์โก้แทน (ผิด
    ตำแหน่งจากช่องว่างจริงที่มักอยู่ชิดขอบใดขอบหนึ่ง) ผู้ใช้ยืนยันด้วยการวงสีแดงว่า
    ตำแหน่งช่องว่างจริงอยู่ที่ "มุมล่างขวาของพื้นตู้" (บริเวณระหว่างขอบล่างของกล่อง
    คาร์โก้กับขอบล่างของตู้ในภาพ 2D) ซึ่งตรงกับค่าที่คำนวณได้: bottom_gap=40px มากกว่า
    top_gap=9px อย่างชัดเจน (บ่งชี้ว่าช่องว่างส่วนใหญ่อยู่ด้านล่าง ไม่ใช่ตรงกลาง)

    วิธีแก้: เปรียบเทียบ "ช่องว่างด้านบน" (cargo_ymin - container_ymin) กับ "ช่องว่าง
    ด้านล่าง" (container_ymax - cargo_ymax) แยกกัน แล้ววาดกรอบเฉพาะฝั่งที่มีช่องว่าง
    มากกว่าเท่านั้น (แถบแคบตามความกว้างเต็มของคาร์โก้ x ความสูงเท่ากับช่องว่างจริง)
    """
    if not view_container or not view_cargo:
        return None
    top_gap = view_cargo["ymin"] - view_container["ymin"]
    bottom_gap = view_container["ymax"] - view_cargo["ymax"]
    x0, x1 = view_cargo["xmin"], view_cargo["xmax"]
    if bottom_gap >= top_gap and bottom_gap > 0:
        y0, y1 = view_cargo["ymax"], view_container["ymax"]
    elif top_gap > 0:
        y0, y1 = view_container["ymin"], view_cargo["ymin"]
    else:
        return None
    # ขยายกรอบเล็กน้อย (padding) เพื่อให้มองเห็นขอบเขตชัดเจนขึ้น ไม่บางจนเกินไป
    pad = max(3, int((y1 - y0) * 0.15))
    return (x0, max(0, y0 - pad), x1, y1 + pad)


# ---------------------------------------------------------------------------
# LOCAL DEPTH-GAP SCAN (v24.3) - ดู CHANGELOG ที่ค่าคงที่ LOCAL_GAP_* ด้านบนสำหรับ
# รายละเอียด root cause และวิธีแก้ทั้งหมด
# ---------------------------------------------------------------------------

def _raw_local_gap_profile(px, x_range, y_search, step=LOCAL_GAP_SAMPLE_STEP_PX):
    """สแกนหา 'ช่องว่างเฉพาะจุด' ณ แต่ละตำแหน่ง x = (ขอบล่างสุดของโครงสร้างตู้ -
    ขอบล่างสุดของคาร์โก้) ภายในหน้าต่างค้นหา y_search ที่กำหนด คืนค่า list ของ
    (x, gap_หรือ_None)"""
    results = []
    for x in range(x_range[0], x_range[1], step):
        cargo_bottom = None
        struct_bottom = None
        for y in range(y_search[0], y_search[1]):
            if _is_vivid_cargo_color(px[x, y]):
                cargo_bottom = y
            if _is_saturated_color(px[x, y]):
                struct_bottom = y
        gap = (struct_bottom - cargo_bottom) if (cargo_bottom is not None and struct_bottom is not None) else None
        results.append((x, gap, cargo_bottom, struct_bottom))
    return results


def _median_smooth_gap_profile(profile, window=LOCAL_GAP_SMOOTH_WINDOW):
    """median smooth เฉพาะค่า gap (index 1 ของแต่ละ tuple) รองรับค่า None"""
    vals = [p[1] for p in profile]
    n = len(vals)
    out = []
    half = window // 2
    for i in range(n):
        lo = max(0, i - half); hi = min(n, i + half + 1)
        window_vals = sorted(v for v in vals[lo:hi] if v is not None)
        out.append(window_vals[len(window_vals) // 2] if window_vals else None)
    return out


def _compute_gap_roughness(raw_vals):
    """คำนวณ 'ความขรุขระ' ของสัญญาณ = ค่าเฉลี่ยของ |ผลต่างระหว่างจุดติดกัน| หารด้วย
    ค่าเฉลี่ยของสัญญาณเอง - หลุมจริง (สามเหลี่ยมลาดเอียงสม่ำเสมอจากมุมมอง isometric)
    จะมีค่าต่ำ ในขณะที่ noise (จากตัวอักษร/ป้ายเลขระยะที่กระโดดสลับไปมา) จะมีค่าสูง"""
    if len(raw_vals) < 2:
        return 0
    diffs = [abs(raw_vals[i + 1] - raw_vals[i]) for i in range(len(raw_vals) - 1)]
    avg_diff = sum(diffs) / len(diffs)
    avg_val = sum(raw_vals) / len(raw_vals)
    return avg_diff / avg_val if avg_val > 0 else 999


def detect_local_depth_gap_regions(view_img, cargo_xmin, cargo_xmax, container_ymax, cargo_ymin,
                                     wall_side, step=LOCAL_GAP_SAMPLE_STEP_PX,
                                     min_gap_px=LOCAL_GAP_MIN_PX, min_width_px=LOCAL_GAP_MIN_WIDTH_PX,
                                     min_raw_coverage=LOCAL_GAP_MIN_RAW_COVERAGE,
                                     raw_lower_thresh=LOCAL_GAP_RAW_LOWER_THRESH,
                                     max_roughness=LOCAL_GAP_MAX_ROUGHNESS):
    """
    สแกน "ช่องว่างเฉพาะจุด" (local depth gap) ตลอดความกว้างคาร์โก้ (เฉพาะโซนกลาง -
    ตัดโซนผนังหัวตู้/ประตูท้ายตู้ออกแล้ว) แล้วหาช่วงที่เป็นหลุมจริง (กว้างต่อเนื่อง,
    ราบเรียบ) ไม่ใช่ noise (จุดเดียวโดดๆ, กระโดดสลับ)

    คืนค่า list ของ region dict: {"x_min","x_max","y_min","y_max","max_gap_px",
    "avg_gap_px","width_px"} เป็นพิกัด "สัมพัทธ์กับ view_img" (ผู้เรียกต้องแปลงเป็น
    พิกัดสัมบูรณ์เอง)
    """
    px = view_img.convert("RGB").load()
    w, h = view_img.size
    cargo_xmin = max(0, int(cargo_xmin)); cargo_xmax = min(w, int(cargo_xmax))
    cargo_width = cargo_xmax - cargo_xmin
    if cargo_width <= 0:
        return []

    # ตัดโซนผนังหัวตู้/ประตูท้ายตู้ออก (ดู comment ที่ LOCAL_GAP_WALL_ZONE_MARGIN_RATIO)
    if wall_side == "RIGHT":  # ผนังหัวตู้อยู่ขวา -> ประตูท้ายตู้อยู่ซ้าย
        scan_x0 = cargo_xmin + int(cargo_width * LOCAL_GAP_DOOR_ZONE_MARGIN_RATIO)
        scan_x1 = cargo_xmax - int(cargo_width * LOCAL_GAP_WALL_ZONE_MARGIN_RATIO)
    else:  # wall_side == "LEFT" -> ประตูท้ายตู้อยู่ขวา
        scan_x0 = cargo_xmin + int(cargo_width * LOCAL_GAP_WALL_ZONE_MARGIN_RATIO)
        scan_x1 = cargo_xmax - int(cargo_width * LOCAL_GAP_DOOR_ZONE_MARGIN_RATIO)
    if scan_x1 <= scan_x0:
        return []

    y_top = max(0, int(cargo_ymin) - LOCAL_GAP_SEARCH_MARGIN_PX)
    y_bot = min(h, int(container_ymax) + LOCAL_GAP_SEARCH_MARGIN_PX)
    if y_bot <= y_top:
        return []

    raw_profile = _raw_local_gap_profile(px, (scan_x0, scan_x1), (y_top, y_bot), step=step)
    if len(raw_profile) < 4:
        return []
    smoothed_vals = _median_smooth_gap_profile(raw_profile)

    regions = []
    n = len(raw_profile)
    i = 0
    min_samples = max(1, min_width_px // step)
    while i < n:
        g = smoothed_vals[i]
        if g is not None and g >= min_gap_px:
            j = i
            while j < n and smoothed_vals[j] is not None and smoothed_vals[j] >= min_gap_px:
                j += 1
            width_samples = j - i
            if width_samples >= min_samples:
                raw_vals = [raw_profile[k][1] for k in range(i, j) if raw_profile[k][1] is not None]
                coverage = sum(1 for v in raw_vals if v >= raw_lower_thresh) / len(raw_vals) if raw_vals else 0
                roughness = _compute_gap_roughness(raw_vals)
                if coverage >= min_raw_coverage and roughness <= max_roughness:
                    xs = [raw_profile[k][0] for k in range(i, j)]
                    cargo_bottoms = [raw_profile[k][2] for k in range(i, j) if raw_profile[k][2] is not None]
                    struct_bottoms = [raw_profile[k][3] for k in range(i, j) if raw_profile[k][3] is not None]
                    region_x_min, region_x_max = min(xs), max(xs)
                    region_y_min = min(cargo_bottoms) if cargo_bottoms else y_top
                    region_y_max = max(struct_bottoms) if struct_bottoms else y_bot
                    max_gap = max(smoothed_vals[k] for k in range(i, j))
                    avg_gap = sum(smoothed_vals[k] for k in range(i, j)) / width_samples
                    print(f"Local depth-gap ACCEPTED: x=[{region_x_min}-{region_x_max}] width={region_x_max-region_x_min}px "
                          f"max_gap={max_gap:.0f}px avg_gap={avg_gap:.0f}px raw_coverage={coverage:.2f} roughness={roughness:.2f}")
                    regions.append({
                        "x_min": region_x_min, "x_max": region_x_max,
                        "y_min": region_y_min, "y_max": region_y_max,
                        "max_gap_px": max_gap, "avg_gap_px": avg_gap,
                        "width_px": region_x_max - region_x_min,
                    })
                else:
                    xs = [raw_profile[k][0] for k in range(i, j)]
                    print(f"Local depth-gap REJECTED (likely noise from dimension text): "
                          f"x=[{min(xs)}-{max(xs)}] raw_coverage={coverage:.2f} roughness={roughness:.2f}")
            i = j
        else:
            i += 1
    return regions


def detect_local_depth_gap_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start, container_bounds, cargo_extent):
    """
    เรียก detect_local_depth_gap_regions() สำหรับทั้ง FRONT และ BACK view โดยแปลง
    พิกัดผลลัพธ์เป็น "สัมบูรณ์บนภาพเต็ม" (เช่นเดียวกับ container_bounds/cargo_extent)
    """
    result = {"FRONT": [], "BACK": []}
    for view in ("FRONT", "BACK"):
        cb = container_bounds.get(view)
        ce = cargo_extent.get(view)
        if not cb or not ce:
            continue
        if layout == "TOP_BOTTOM":
            mid_y = crop_h // 2
            if view == "FRONT":
                view_img = diagram_crop.crop((0, 0, crop_w, mid_y)); origin_x, origin_y = 0, crop_y_start
            else:
                view_img = diagram_crop.crop((0, mid_y, crop_w, crop_h)); origin_x, origin_y = 0, crop_y_start + mid_y
        else:
            half_w = crop_w // 2
            if view == "FRONT":
                view_img = diagram_crop.crop((0, 0, half_w, crop_h)); origin_x, origin_y = 0, crop_y_start
            else:
                view_img = diagram_crop.crop((half_w, 0, crop_w, crop_h)); origin_x, origin_y = half_w, crop_y_start

        rear_side = HARDCODED_REAR_SIDE[view]
        wall_side = "RIGHT" if rear_side == "LEFT" else "LEFT"

        rel_cargo_xmin = ce["xmin"] - origin_x
        rel_cargo_xmax = ce["xmax"] - origin_x
        rel_cargo_ymin = ce["ymin"] - origin_y
        rel_container_ymax = cb["ymax"] - origin_y

        try:
            regions_rel = detect_local_depth_gap_regions(view_img, rel_cargo_xmin, rel_cargo_xmax,
                                                            rel_container_ymax, rel_cargo_ymin, wall_side)
        except Exception as e:
            print(f"WARNING: Local depth-gap scan failed for {view} ({e})")
            regions_rel = []

        regions_abs = []
        for r in regions_rel:
            regions_abs.append({
                "x_min": r["x_min"] + origin_x, "x_max": r["x_max"] + origin_x,
                "y_min": r["y_min"] + origin_y, "y_max": r["y_max"] + origin_y,
                "max_gap_px": r["max_gap_px"], "avg_gap_px": r["avg_gap_px"], "width_px": r["width_px"],
            })
        result[view] = regions_abs
    return result


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

    # v24.1 FIX (EDGE-BASED comparison แทน whole-segment AVERAGE):
    # เดิมเปรียบเทียบ "ค่าเฉลี่ยทั้ง segment" (y_avg) ระหว่างเพื่อนบ้าน ซึ่งพังเมื่อ
    # segment มีความชันแบบค่อยเป็นค่อยไปภายในตัวเอง (perspective drift จากตำแหน่ง
    # ความลึกที่ทำให้ความสูงที่วัดได้ค่อยๆ เปลี่ยนต่อเนื่องตลอด segment แม้จะเป็นกล่อง
    # ความสูงจริงเท่ากันทั้งหมด) พบจากไฟล์จริง ED85-02: purple TGT1G segment กว้าง
    # 335px มีความสูงไล่ระดับต่อเนื่องจาก perspective (ไม่ใช่รอยต่อจริง) แต่ค่าเฉลี่ย
    # ทั้ง segment ถูกเทียบกับเพื่อนบ้านทำให้เกิด false STEP_DOWN กว้างเกินจริง (24%)
    # ครอบคลุมกล่องสีม่วงทั้งหมดผิดพลาด (ตรงกับที่ผู้ใช้รายงาน "กรอบคลุมกล่องสีม่วงผิด")
    # แก้ไขด้วยการเปรียบเทียบเฉพาะ "ค่าที่ขอบ" (เฉลี่ยจากไม่กี่จุดใกล้รอยต่อที่สุด)
    # แทนค่าเฉลี่ยทั้ง segment + จำกัดกรอบที่รายงานให้อยู่ใกล้รอยต่อจริงเท่านั้น (ไม่ใช่
    # ทั้ง segment ที่อาจกว้างจาก perspective drift ภายใน)
    EDGE_SAMPLE_N = 4

    def _edge_value(seg, from_start):
        pts = seg[:EDGE_SAMPLE_N] if from_start else seg[-EDGE_SAMPLE_N:]
        ys = [p[1] for p in pts]
        return sum(ys) / len(ys)

    seg_info = []
    for seg in segments:
        if len(seg) < 1:
            continue
        xs = [p[0] for p in seg]
        width = (max(xs) - min(xs)) if len(xs) > 1 else step
        seg_info.append({
            "x_min": min(xs), "x_max": max(xs), "width": width,
            "edge_left": _edge_value(seg, from_start=True),
            "edge_right": _edge_value(seg, from_start=False),
        })
    seg_info.sort(key=lambda s: s["x_min"])

    risky_segments = []
    n = len(seg_info)
    for i in range(n):
        seg = seg_info[i]
        if seg["width"] < min_flat_width_px:
            continue
        is_risky = False
        max_ratio = 0
        risky_x_min, risky_x_max = seg["x_min"], seg["x_max"]
        edge_zone_width = min(seg["width"], max(min_flat_width_px, int(container_y_span_px * 0.35)))
        if i > 0:
            left = seg_info[i - 1]
            diff = abs(seg["edge_left"] - left["edge_right"])
            ratio = diff / container_y_span_px if container_y_span_px > 0 else 0
            if seg["edge_left"] > left["edge_right"] and ratio >= min_ratio:
                is_risky = True
                max_ratio = max(max_ratio, ratio)
                risky_x_max = min(risky_x_max, seg["x_min"] + edge_zone_width)
        if i < n - 1:
            right = seg_info[i + 1]
            diff = abs(seg["edge_right"] - right["edge_left"])
            ratio = diff / container_y_span_px if container_y_span_px > 0 else 0
            if seg["edge_right"] > right["edge_left"] and ratio >= min_ratio:
                is_risky = True
                max_ratio = max(max_ratio, ratio)
                risky_x_min = max(risky_x_min, seg["x_max"] - edge_zone_width)
        if is_risky:
            if risky_x_min > risky_x_max:
                risky_x_min, risky_x_max = seg["x_min"], seg["x_max"]
            seg["x_min"], seg["x_max"] = risky_x_min, risky_x_max
            seg["y_avg"] = min(seg["edge_left"], seg["edge_right"])
            risky_segments.append({
                "x_min": seg["x_min"], "x_max": seg["x_max"],
                "y_min": seg["y_avg"], "y_max": container_ymax,
                "ratio": max_ratio,
            })

    risky_segments.sort(key=lambda r: r["x_min"])
    return risky_segments


def detect_step_down_regions_from_stack_model(stacks, view_label=None, min_ratio=None, min_abs_px=None):
    """v24.10 STEP_DOWN from adjacent stack model.

    Detects adjacent stack height drops and returns a compact boundary marker on the lower stack.
    V24.10 keeps only the strongest pair later in process_request, and disables STEP_DOWN merge.
    """
    min_ratio = globals().get("V2407_STEP_DOWN_STACK_HEIGHT_RATIO", 0.22) if min_ratio is None else min_ratio
    min_abs_px = globals().get("V2407_STEP_DOWN_MIN_ABS_HEIGHT_PX", 18) if min_abs_px is None else min_abs_px
    boundary_ratio = globals().get("V2410_STEPDOWN_BOUNDARY_RATIO", 0.25)
    ss = [s for s in (stacks or []) if s.get("boxes")]
    ss = sorted(ss, key=lambda s: s.get("x0", 0))
    regions = []
    for idx in range(len(ss) - 1):
        a, b = ss[idx], ss[idx + 1]
        ha = max(1, a["floor_y"] - a["top_y"])
        hb = max(1, b["floor_y"] - b["top_y"])
        taller_h = max(ha, hb)
        shorter_h = min(ha, hb)
        diff = taller_h - shorter_h
        ratio = diff / max(1, taller_h)
        if diff < min_abs_px or ratio < min_ratio:
            if globals().get("V2407_TRACE", True):
                print(f"v24.10 STEP_DOWN reject {view_label} pair={idx}-{idx+1}: heights=({ha},{hb}) diff={diff}px ratio={ratio:.2f}")
            continue
        lower = a if ha < hb else b
        higher = b if ha < hb else a
        # Boundary-only marker: keep a narrow slice of the lower stack next to the higher stack.
        lower_w = max(1, lower["x1"] - lower["x0"])
        mark_w = max(14, int(lower_w * boundary_ratio))
        if lower["x0"] < higher["x0"]:
            x0 = max(lower["x0"], lower["x1"] - mark_w)
            x1 = lower["x1"]
        else:
            x0 = lower["x0"]
            x1 = min(lower["x1"], lower["x0"] + mark_w)
        # Keep vertical box around visible lower-stack cargo, slightly padded.
        y0 = lower["top_y"]
        y1 = lower["floor_y"]
        regions.append({
            "x_min": x0, "y_min": y0, "x_max": x1, "y_max": y1,
            "ratio": ratio,
            "v2410_source": "adjacent_stack_height_drop_boundary_only",
            "v2410_pair_index": (idx, idx + 1),
            "v2410_heights": (ha, hb),
        })
        if globals().get("V2407_TRACE", True):
            print(f"v24.10 STEP_DOWN ACCEPT {view_label} pair={idx}-{idx+1}: heights=({ha},{hb}) diff={diff}px ratio={ratio:.2f} boundary_marker=[{x0},{y0},{x1},{y1}]")
    return regions

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
# PER-BOX SEGMENTATION (v22, ปรับปรุงครั้งใหญ่ใน v24)
#
# แนวคิด: สร้าง "stack-box model" (แบบจำลองตั้ง-กล่อง) จากพิกเซลในแต่ละ view
# (FRONT/BACK) โดยแบ่งเป็น 2 ขั้นตอน:
#   ขั้น 1 (แบ่ง "ตั้ง"/stack ตามแนวกว้าง): แยก "กลุ่มก้อนสินค้าจริง" ก่อนด้วยช่องว่าง
#   จริง แล้วหาเส้นแบ่งภายในแต่ละกลุ่มด้วย 3 สัญญาณรวมกัน (v24 - ดู CHANGELOG หัวไฟล์):
#   dark-dip (เดิม) + color-step (ใหม่) + floor-jump (ใหม่)
#   ขั้น 2 (แบ่ง "กล่อง" ในแต่ละตั้งตามแนวสูง): ใช้หลักการเดียวกัน (3 สัญญาณรวมกัน)
#   ตามแนวตั้ง แล้ววัดขอบซ้าย/ขวาจริงของกล่องแต่ละใบด้วย median-of-multiple-rows
#
# นำแบบจำลองนี้ไปใช้กับ 3 risk type ที่เดิมพึ่ง AI 100% ใน v21:
#   - OVERHANG_RISK, TALL_UNSTABLE_RISK: FORCE + VETO
#   - REAR_LATERAL_IMBALANCE: FORCE เสมอ + VETO แบบมีเงื่อนไข (v24 ใหม่ - ดู
#     process_request สำหรับ logic การ veto)
#
# ข้อจำกัดที่ทราบและยอมรับ (ดู CHANGELOG หัวไฟล์สำหรับรายละเอียดเต็ม):
#   - Occlusion ในมุมมอง isometric (ยืนยันจากไฟล์ EC51-02)
#   - Same-color adjacent stacks อาจแยกไม่ครบ 100% (ไม่กระทบผลลัพธ์ความเสี่ยงมากนัก)
# ---------------------------------------------------------------------------

BOX_BOUNDARY_MIN_DROP = 22
BOX_BOUNDARY_MAX_THICKNESS_PX = 6
STACK_MIN_WIDTH_PX = 18
BOX_MIN_HEIGHT_PX = 4
BOX_MIN_HEIGHT_RATIO = 0.12
TOP_ROW_MAJORITY_RATIO = 0.65  # v24.1 FIX: เดิมใช้ "ANY column has cargo" (1 คอลัมน์
                                # เดียวก็พอ) เพื่อหา top_y ของตั้ง ซึ่งเสี่ยงถูก "หน้า
                                # บนลาดเอียง" (isometric parallelogram top face) ของ
                                # กล่องเพื่อนบ้านที่สูงกว่า "ล้ำ" เข้ามาในช่วง x ของตั้ง
                                # ที่เตี้ยกว่า (แม้พื้นจะแบ่งเขตถูกต้องแล้วก็ตาม เพราะ
                                # หน้าบนที่ลาดเอียงไปตามแนวความลึกทำให้ที่ตำแหน่ง y สูงๆ
                                # อาจมีเพียง 1-2 คอลัมน์ริมขอบที่ยังเห็นสีเพื่อนบ้าน)
                                # พบจากไฟล์จริง EC50-01: กล่องเหลือง VCS1A (2 ชั้น) ถูก
                                # วัดความสูงผิดจนใกล้เคียงกล่องเขียว TSC1A (4 ชั้น) ข้าง
                                # เคียง เพราะคอลัมน์เดียวที่ริมขอบจับสีเขียวได้ที่ y สูง
                                # แก้ไขด้วยการกำหนดว่าต้องมีอย่างน้อย 65% ของคอลัมน์ที่
                                # สุ่มตรวจเป็นสี cargo พร้อมกัน จึงถือว่าเป็นแถวบนสุดจริง

STACK_COVERAGE_MIN_RATIO = 0.60

OVERHANG_MIN_RATIO = 0.20
OVERHANG_MIN_ABS_PX = 20
TALL_UNSTABLE_MIN_HEIGHT_RATIO = 0.35
TALL_UNSTABLE_NEIGHBOR_MAX_RATIO = 0.65

# v24.01 TallUnstableGuard controls
# Keep legacy constants above for compatibility, but use stricter v24.01 gates only inside
# detect_tall_unstable_regions_for_view(). This patch intentionally does not change any
# other risk detector.
V2401_TALL_UNSTABLE_GUARD_ENABLED = True
V2401_TALL_UNSTABLE_MIN_HEIGHT_RATIO = 0.45
V2401_TALL_UNSTABLE_NEIGHBOR_MAX_RATIO = 0.55
V2401_TALL_UNSTABLE_REQUIRE_BOX_COUNT_GT_NEIGHBORS = True
V2401_TALL_UNSTABLE_MIN_WIDTH_RATIO_OF_MEDIAN = 0.70
V2401_TALL_UNSTABLE_MAX_WIDTH_RATIO_OF_MEDIAN = 1.60
V2401_TALL_UNSTABLE_MIN_ABS_HEIGHT_PX = 25
V2401_TALL_UNSTABLE_TRACE = True

# v24.02 targeted marker/decision controls
V2402_OVERHANG_CAUSE_BOX_ENABLED = True
V2402_REAR_LATERAL_BACK_BOX_SHIFT_UP_RATIO = 0.50
V2402_LATERAL_GAP_INTER_STACK_ONLY = True
V2402_LATERAL_GAP_MIN_INTER_STACK_GAP_PX = 18
V2402_LATERAL_GAP_MIN_VERTICAL_OVERLAP_RATIO = 0.20
V2402_TRACE = True

# v24.04 OVERHANG_RISK controls
# New definition from user review:
# - consider a cargo stack only when boxes are visibly stacked from lower to upper box;
# - if adjacent stacked boxes in the same stack have clearly different visible width/size,
#   treat it as an unstable support/overhang candidate;
# - reject edge-only/isometric artifacts where only a thin outer strip is detected.
V2404_OVERHANG_STACK_SIZE_GUARD_ENABLED = True
V2404_OVERHANG_MIN_WIDTH_MISMATCH_RATIO = 0.05
V2404_OVERHANG_MIN_WIDTH_MISMATCH_PX = 6
V2404_OVERHANG_MIN_VERTICAL_TOUCH_RATIO = 0.12
V2404_OVERHANG_MARK_PAIR_BOX = True
V2404_OVERHANG_REJECT_EDGE_STRIP_ONLY = True
V2404_OVERHANG_TRACE = True

# v24.06 OVERHANG strict controls
V2406_OVERHANG_FIVE_PERCENT_GUARD_ENABLED = True
V2406_OVERHANG_MIN_SIZE_DIFF_RATIO = 0.05
V2406_OVERHANG_MIN_SIZE_DIFF_PX = 6
V2406_OVERHANG_REQUIRE_SAME_STACK_VISIBLE_PAIR = True
V2406_OVERHANG_DISABLE_FALLBACK_MARKER = True
V2406_OVERHANG_SUPPRESS_EDGE_ARTIFACT = True
V2406_OVERHANG_AA02_SAFE_REFERENCE = True
V2406_OVERHANG_TRACE = True

# v24.07 focused controls
# OVERHANG remains audit-only because AA02-01 proves the active scanner can still map
# isometric/segmentation artifacts into a false green marker. No OVERHANG hazard/marker is emitted.
V2407_OVERHANG_AUDIT_ONLY = True
V2407_OVERHANG_ACTIVE_DETECTION = False
V2407_OVERHANG_DISABLE_AI_ACCEPT = True
V2407_STEP_DOWN_STACK_ADJACENCY_ENABLED = True
V2407_STEP_DOWN_STACK_HEIGHT_RATIO = 0.22
V2407_STEP_DOWN_MIN_ABS_HEIGHT_PX = 18
V2407_STEP_DOWN_MARK_LOWER_STACK = True
V2407_TRACE = True

# v24.10 focused controls
V2410_BUILD = True
V2410_AUTO_GEMINI_POOL = True
V2410_STEPDOWN_DISABLE_MERGE = True
V2410_STEPDOWN_STRONGEST_ONLY = True
V2410_STEPDOWN_BOUNDARY_ONLY = True
V2410_STEPDOWN_BOUNDARY_RATIO = 0.25

# v24.05 REAR_LATERAL_IMBALANCE tuning controls
# Main target: AA04-05 BACK view. Marker should cover the visible cargo stacks causing the
# left-right rear height imbalance, not the lower/floor area.
V2405_REAR_LATERAL_TUNE_ENABLED = True
V2405_REAR_LATERAL_BACK_SHIFT_UP_RATIO = 0.50
V2405_REAR_LATERAL_USE_DET_BOX_FOR_FORCED = True
V2405_REAR_LATERAL_FINAL_DRAW_SHIFT_BACK = True
V2405_REAR_LATERAL_MARK_VISIBLE_PAIR_ONLY = True
V2405_REAR_LATERAL_TRACE = True

LATERAL_IMBALANCE_MIN_RATIO = 0.40

# v24 NEW: เกณฑ์สำหรับ VETO ของ REAR_LATERAL_IMBALANCE - ถ้า deterministic วัดว่า
# ความสูงต่างกันน้อยกว่านี้ (สัดส่วน) ถือว่า "ไม่มีความไม่สมดุลจริง" สามารถ veto การ
# claim ของ AI ได้ (ตั้งค่าต่ำกว่า LATERAL_IMBALANCE_MIN_RATIO ของ FORCE พอสมควร
# เพื่อเป็น "buffer zone" - ไม่ FORCE และไม่ VETO ถ้าอยู่ระหว่างกลาง เพื่อความปลอดภัย)
LATERAL_IMBALANCE_VETO_MAX_RATIO = 0.20
# ต้องมี coverage สูงพอ (มากกว่า FORCE/VETO gate ปกติ) จึงจะเชื่อถือพอจะ veto ได้
LATERAL_IMBALANCE_VETO_MIN_COVERAGE = 0.75


def _luminance(rgb):
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


def _find_dark_boundary_lines_1d(profile, min_drop=BOX_BOUNDARY_MIN_DROP, max_thickness=BOX_BOUNDARY_MAX_THICKNESS_PX):
    """
    รับ list ของค่าความสว่างเฉลี่ยตามตำแหน่ง แล้วหา "ร่อง" (dip) ที่ความสว่างลดฮวบแล้ว
    กลับขึ้นภายในระยะสั้นๆ (<=max_thickness) ซึ่งบ่งบอกว่าเป็นเส้นขอบบางๆ ระหว่างกล่อง
    2 ใบ (ไม่ใช่พื้นที่ว่างจริงที่ความสว่างจะเปลี่ยนแปลงต่อเนื่องเป็นระยะยาว)
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


# --- v24 NEW: color-step + floor/edge-jump boundary detectors -------------

COLOR_STEP_MIN_DISTANCE = 60
COLOR_STEP_MIN_RUN_AFTER = 6
COLOR_STEP_MIN_GAP = 15
JUMP_MIN_PX = 40
JUMP_MIN_GAP = 15
BOUNDARY_SMOOTH_WINDOW = 5


def _color_distance(rgb1, rgb2):
    return sum((a - b) ** 2 for a, b in zip(rgb1, rgb2)) ** 0.5


def _median_smooth_colors(color_profile, window=BOUNDARY_SMOOTH_WINDOW):
    n = len(color_profile)
    out = []
    half = window // 2
    for i in range(n):
        lo = max(0, i - half); hi = min(n, i + half + 1)
        window_colors = color_profile[lo:hi]
        rs = sorted(c[0] for c in window_colors)
        gs = sorted(c[1] for c in window_colors)
        bs = sorted(c[2] for c in window_colors)
        mid = len(window_colors) // 2
        out.append((rs[mid], gs[mid], bs[mid]))
    return out


def _median_smooth_scalar(profile, window=BOUNDARY_SMOOTH_WINDOW):
    """median smooth ที่รองรับค่า None"""
    n = len(profile)
    out = []
    half = window // 2
    for i in range(n):
        lo = max(0, i - half); hi = min(n, i + half + 1)
        vals = sorted(v for v in profile[lo:hi] if v is not None)
        if not vals:
            out.append(None)
        else:
            out.append(vals[len(vals) // 2])
    return out


def _find_color_step_boundaries(color_profile, min_distance=COLOR_STEP_MIN_DISTANCE,
                                  min_run_after=COLOR_STEP_MIN_RUN_AFTER, min_gap_between=COLOR_STEP_MIN_GAP):
    """ตรวจจับ "รอยต่อสี" (color step boundary) ระหว่างกล่อง 2 ใบที่มีสีต่างกันชัดเจน
    (v24 NEW - ดู CHANGELOG หัวไฟล์: แก้ปัญหาหลักที่ dark-dip เดิมพลาดการเปลี่ยนสี)"""
    n = len(color_profile)
    boundaries = []
    last_boundary = -999
    i = 1
    while i < n:
        prev_color = color_profile[i - 1]
        cur_color = color_profile[i]
        dist = _color_distance(prev_color, cur_color)
        if dist >= min_distance:
            run_ok = True
            check_len = min(min_run_after, n - i - 1)
            for k in range(1, check_len + 1):
                if _color_distance(color_profile[i + k], cur_color) > min_distance * 0.5:
                    run_ok = False
                    break
            if run_ok and (i - last_boundary) > min_gap_between:
                boundaries.append(i)
                last_boundary = i
        i += 1
    return boundaries


def _find_jump_boundaries(profile, min_jump=JUMP_MIN_PX, min_gap_between=JUMP_MIN_GAP):
    """ตรวจจับตำแหน่งที่ local floor (แนวนอน) หรือความกว้างขอบ (แนวตั้ง) กระโดดขึ้น/ลง
    อย่างฉับพลันและคงอยู่ต่อเนื่อง (v24 NEW - จับรอยต่อระหว่างตั้ง/กล่องที่ความสูง/
    ความกว้างต่างกัน แม้จะมีสีเดียวกันก็ตาม)"""
    n = len(profile)
    boundaries = []
    last_boundary = -999
    for i in range(1, n):
        a, b = profile[i - 1], profile[i]
        if a is None or b is None:
            continue
        if abs(b - a) >= min_jump and (i - last_boundary) > min_gap_between:
            boundaries.append(i)
            last_boundary = i
    return boundaries


def _combined_boundaries(color_profile, position_profile, lum_profile, min_seg_width):
    """รวม 3 สัญญาณ: dark-dip (เดิม) + color-step (ใหม่) + floor/edge-jump (ใหม่)
    แบบ union แล้ว dedupe/merge boundary ที่อยู่ใกล้กันเกินไป - ดู CHANGELOG หัวไฟล์
    (หัวข้อ v24) สำหรับเหตุผลที่ตัดสินใจคงทั้ง 3 สัญญาณไว้ในทั้ง 2 ทิศทาง (แนวนอน/
    แนวตั้ง) แทนที่จะใช้แค่บางสัญญาณในบางทิศทาง"""
    smoothed_colors = _median_smooth_colors(color_profile)
    smoothed_position = _median_smooth_scalar(position_profile)
    color_b = _find_color_step_boundaries(smoothed_colors)
    jump_b = _find_jump_boundaries(smoothed_position)
    dark_b = _find_dark_boundary_lines_1d(lum_profile)
    all_b = sorted(set(color_b) | set(jump_b) | set(dark_b))
    deduped = []
    for b in all_b:
        if not deduped or b - deduped[-1] > min_seg_width // 2:
            deduped.append(b)
    return deduped


def _local_bottom_cargo_y(px, x, y_top, y_bot):
    """หาตำแหน่ง y ของพิกเซลคาร์โก้ที่อยู่ล่างสุด (ใกล้พื้นที่สุด) ในคอลัมน์ x เดียว
    ภายในช่วง [y_top, y_bot) - ใช้เป็น "พื้นเฉพาะจุด" (local floor) ที่คำนวณจาก
    พิกเซลจริงโดยตรง (v23.1)"""
    last_y = None
    for y in range(y_top, y_bot):
        if _is_vivid_cargo_color(px[x, y]):
            last_y = y
    return last_y


def _find_cargo_present_clusters(px, cargo_xmin, cargo_xmax, y_search_top, y_search_bottom):
    """หา "กลุ่มก้อนสินค้าจริง" (physical cluster) ตามแนว x โดยตรวจสอบว่ามีพิกเซล
    คาร์โก้อยู่ที่ใดก็ได้ภายในช่วง y ที่กำหนด (v23.1 - ครอบคลุมทั้งช่วงความสูงที่
    คาร์โก้อาจปรากฏ เพื่อทนทานต่อ "คลื่น" ของตำแหน่งความลึกจากการจัดวางแบบสลับ)"""
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
    if cluster_start is not None:
        clusters.append((cluster_start, n))
    return [(cargo_xmin + a, cargo_xmin + b) for a, b in clusters]


def _merge_thin_edge_segments(edges, min_height):
    """รวม (merge) ขอบเขตที่สร้าง segment บางเกินไป (< min_height) เข้ากับเพื่อนบ้าน
    ที่เล็กกว่า ป้องกันไม่ให้ boundary ปลอมแยกกล่อง/ตั้งจริง 2 ใบออกจากกันผิดพลาด"""
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


def detect_stack_columns(view_img, cargo_xmin, cargo_xmax, y_search_top, y_search_bottom, sample_band_px=6):
    """แบ่งความกว้างของสินค้าออกเป็น "ตั้ง" (stack) ด้วย 2 ขั้นตอน: (1) แยกกลุ่มก้อน
    สินค้าจริงด้วยช่องว่างจริงก่อน (2) หาเส้นแบ่งภายในแต่ละกลุ่มด้วย 3 สัญญาณรวมกัน
    (v24: dark-dip + color-step + floor-jump)"""
    px = view_img.convert("RGB").load()
    w, h = view_img.size
    cargo_xmin = max(0, int(cargo_xmin)); cargo_xmax = min(w, int(cargo_xmax))
    y_search_top = max(0, int(y_search_top)); y_search_bottom = min(h, int(y_search_bottom))
    if cargo_xmax <= cargo_xmin or y_search_bottom <= y_search_top:
        return []

    clusters = _find_cargo_present_clusters(px, cargo_xmin, cargo_xmax, y_search_top, y_search_bottom)
    if not clusters:
        return [(cargo_xmin, cargo_xmax)]

    stacks = []
    for (cx0, cx1) in clusters:
        if cx1 - cx0 < STACK_MIN_WIDTH_PX:
            continue
        color_profile, floor_profile, lum_profile = [], [], []
        for x in range(cx0, cx1):
            lf = _local_bottom_cargo_y(px, x, y_search_top, y_search_bottom)
            floor_profile.append(lf)
            if lf is None:
                color_profile.append((255, 255, 255)); lum_profile.append(255.0)
                continue
            y1 = lf; y0 = max(0, y1 - sample_band_px)
            rs = [px[x, y][0] for y in range(y0, y1)]
            gs = [px[x, y][1] for y in range(y0, y1)]
            bs = [px[x, y][2] for y in range(y0, y1)]
            color_profile.append((sum(rs) / len(rs), sum(gs) / len(gs), sum(bs) / len(bs)))
            lum_profile.append(sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in zip(rs, gs, bs)) / len(rs))

        deduped = _combined_boundaries(color_profile, floor_profile, lum_profile, STACK_MIN_WIDTH_PX)
        boundaries_abs = sorted(cx0 + b for b in deduped)
        edges = [cx0] + boundaries_abs + [cx1]
        edges = _merge_thin_edge_segments(edges, STACK_MIN_WIDTH_PX)
        for i in range(len(edges) - 1):
            x0, x1 = edges[i], edges[i + 1]
            if x1 - x0 >= STACK_MIN_WIDTH_PX:
                stacks.append((x0, x1))
    if not stacks:
        stacks = [(cargo_xmin, cargo_xmax)]
    return stacks


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
    """ขยายขอบเขตออกจากตำแหน่ง seed_x แบบ "ต่อเนื่อง" เท่านั้น (ยอมรับช่องว่างเล็กๆ
    จาก anti-aliasing ไม่เกิน max_pixel_gap พิกเซล) คืนค่า (result, hit_limit) -
    hit_limit=True หากขยายไปจนสุด limit_px โดยไม่เจอขอบเขตจริง (บ่งชี้ว่าอาจกำลัง
    "ขยายข้ามไปติดกับตั้ง/กล่องข้างเคียงที่มีสีเดียวกันสนิท ไม่มีเส้นแบ่ง")"""
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
        if steps >= limit_px:
            hit_limit = True
    return result, hit_limit


def detect_boxes_in_stack(view_img, x0, x1, y_search_top, y_search_bottom, search_expand_px=25):
    """ในตั้ง [x0,x1) สแกนจากยอดสินค้าลงมาถึงพื้นตู้ หาเส้นแบ่งแนวนอนระหว่างกล่อง
    แต่ละใบที่ซ้อนกัน (v24: ด้วย 3 สัญญาณรวมกัน) แล้ววัดขอบซ้าย/ขวาจริงของกล่องแต่ละ
    ใบด้วย median-of-multiple-rows คืนค่า list ของกล่อง เรียงจากบนสุดไปล่างสุด

    v23.1: คำนวณ "พื้นเฉพาะของตั้งนี้" จากพิกเซลคาร์โก้จริงในช่วง x0:x1 โดยตรง แทนที่
    จะพึ่งพาแบบจำลองเส้นตรงทั่วโลก (ทนทานต่อ "คลื่น" ของตำแหน่งความลึก)"""
    px = view_img.convert("RGB").load()
    w, h = view_img.size
    x0 = max(0, int(x0)); x1 = min(w, int(x1))
    y_search_top = max(0, int(y_search_top)); y_search_bottom = min(h, int(y_search_bottom))
    if x1 <= x0 or y_search_bottom <= y_search_top:
        return []

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
        sample_xs = list(range(x0, x1, max(1, (x1 - x0) // 12)))
        cargo_count = sum(1 for x in sample_xs if _is_vivid_cargo_color(px[x, y]))
        row_has_cargo = (cargo_count / len(sample_xs)) >= TOP_ROW_MAJORITY_RATIO if sample_xs else False
        if row_has_cargo:
            top_y = y
            break
    if top_y is None:
        return []

    # v24: สร้าง color_profile และ width_profile (ความกว้างขอบซ้าย/ขวาต่อแถว) ตาม
    # แนวตั้ง เพื่อใช้ตรวจจับ color-step boundary และ edge-jump boundary เพิ่มเติมจาก
    # dark-dip เดิม (แก้ปัญหากล่อง 2 ใบต่างสีกันซ้อนกัน หรือกล่องความกว้างต่างกันซ้อน)
    color_profile, lum_profile, width_profile = [], [], []
    for y in range(top_y, floor_y):
        seed_left, seed_right = _seed_extent_in_range(px, x0, x1, y)
        if seed_left is None:
            color_profile.append((255, 255, 255)); lum_profile.append(255.0); width_profile.append(None)
            continue
        rs = [px[x, y][0] for x in range(seed_left, seed_right + 1)]
        gs = [px[x, y][1] for x in range(seed_left, seed_right + 1)]
        bs = [px[x, y][2] for x in range(seed_left, seed_right + 1)]
        color_profile.append((sum(rs) / len(rs), sum(gs) / len(gs), sum(bs) / len(bs)))
        lum_profile.append(sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in zip(rs, gs, bs)) / len(rs))
        width_profile.append(seed_right - seed_left)

    deduped = _combined_boundaries(color_profile, width_profile, lum_profile, BOX_MIN_HEIGHT_PX * 3)
    boundaries_abs = sorted(top_y + b for b in deduped)
    edges = [top_y] + boundaries_abs + [floor_y]

    stack_total_height = max(1, floor_y - top_y)
    min_segment_height = max(BOX_MIN_HEIGHT_PX, int(stack_total_height * BOX_MIN_HEIGHT_RATIO))
    edges = _merge_thin_edge_segments(edges, min_segment_height)

    boxes = []
    for i in range(len(edges) - 1):
        y0b, y1b = edges[i], edges[i + 1]
        if y1b - y0b < BOX_MIN_HEIGHT_PX:
            continue
        seg_height = y1b - y0b
        pad = max(1, int(seg_height * 0.2))
        sample_y0 = y0b + pad; sample_y1 = y1b - pad
        if sample_y1 <= sample_y0:
            sample_ys = [(y0b + y1b) // 2]
        else:
            n_samples = min(7, max(3, seg_height // 15))
            step_y = max(1, (sample_y1 - sample_y0) // max(1, n_samples - 1))
            sample_ys = list(range(sample_y0, sample_y1 + 1, step_y))

        # v23.1: ทิ้งค่าที่ hit_limit=True ออกจากการคำนวณค่ามัธยฐาน (ป้องกันขยายข้าม
        # ไปติดกับตั้ง/กล่องข้างเคียงที่สีเดียวกันสนิท) + เกณฑ์จำนวนตัวอย่างขั้นต่ำ
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

        min_valid_samples = max(1, len(sample_ys) // 2)
        left = x0 if len(left_measurements) < min_valid_samples else _median_of(left_measurements)
        right = x1 if len(right_measurements) < min_valid_samples else _median_of(right_measurements)
        boxes.append({"y_min": y0b, "y_max": y1b, "x_left": left, "x_right": right, "height_px": y1b - y0b})
    return boxes


def build_stack_box_model_for_view(view_img, y_search_top, y_search_bottom, cargo_xmin, cargo_xmax):
    stack_ranges = detect_stack_columns(view_img, cargo_xmin, cargo_xmax, y_search_top, y_search_bottom)
    stacks = []
    for (x0, x1) in stack_ranges:
        boxes = detect_boxes_in_stack(view_img, x0, x1, y_search_top, y_search_bottom)
        if boxes:
            top_y = boxes[0]["y_min"]; floor_y_here = boxes[-1]["y_max"]
        else:
            top_y = y_search_bottom; floor_y_here = y_search_bottom
        stacks.append({"x0": x0, "x1": x1, "top_y": top_y, "floor_y": floor_y_here, "boxes": boxes})
    stacks.sort(key=lambda s: s["x0"])
    return stacks


def build_stack_box_model_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start, container_bounds, cargo_extent):
    """สร้าง stack-box model สำหรับ FRONT และ BACK view - ใช้ LOCAL FLOOR (v23.1)
    ร่วมกับ combined boundary detection (v24) เพื่อความแม่นยำสูงสุด"""
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
                view_img = diagram_crop.crop((0, 0, crop_w, mid_y)); origin_x, origin_y = 0, crop_y_start
            else:
                view_img = diagram_crop.crop((0, mid_y, crop_w, crop_h)); origin_x, origin_y = 0, crop_y_start + mid_y
        else:
            half_w = crop_w // 2
            if view == "FRONT":
                view_img = diagram_crop.crop((0, 0, half_w, crop_h)); origin_x, origin_y = 0, crop_y_start
            else:
                view_img = diagram_crop.crop((half_w, 0, crop_w, crop_h)); origin_x, origin_y = half_w, crop_y_start

        rel_cargo_xmin = ce["xmin"] - origin_x
        rel_cargo_xmax = ce["xmax"] - origin_x
        cargo_width = max(1, rel_cargo_xmax - rel_cargo_xmin)
        rel_cargo_ymin = ce["ymin"] - origin_y
        margin = max(20, int((cb["ymax"] - cb["ymin"]) * 0.08))
        rel_y_search_bottom = max(ce["ymax"], cb["ymax"]) - origin_y + margin
        rel_y_search_top = max(0, rel_cargo_ymin - 5)

        try:
            stacks_local = build_stack_box_model_for_view(view_img, rel_y_search_top, rel_y_search_bottom, rel_cargo_xmin, rel_cargo_xmax)
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
        # v24 NEW: coverage_ratio ถูกเก็บไว้ใน key พิเศษเพื่อให้ process_request นำไปใช้
        # ตัดสินใจ VETO ของ REAR_LATERAL_IMBALANCE ได้ (ต้องการ coverage สูงกว่าเกณฑ์
        # ปกติจึงจะเชื่อถือพอจะ veto)
        result[f"{view}_coverage_ratio"] = coverage_ratio
        print(f"Per-box segmentation ({view}): coverage_ratio={coverage_ratio:.2f}, "
              f"{len(stacks_abs)} stack(s) detected, "
              f"box counts per stack = {[len(s['boxes']) for s in stacks_abs]}")
    return result


def detect_overhang_regions_for_view(stacks):
    """v24.07 OVERHANG audit-only scanner.

    Current status from AA02-01 regression:
    - the definition is clear, but active detection still produces false green markers due to
      segmentation/isometric mapping errors;
    - therefore OVERHANG candidates are logged for diagnosis but are NOT emitted as hazards or
      markers until the stack/box segmentation is proven reliable.
    """
    audit_regions = []
    active = globals().get("V2407_OVERHANG_ACTIVE_DETECTION", False)
    trace = globals().get("V2407_TRACE", True) or globals().get("V2406_OVERHANG_TRACE", True)
    min_ratio = globals().get("V2406_OVERHANG_MIN_SIZE_DIFF_RATIO", 0.05)
    min_px = globals().get("V2406_OVERHANG_MIN_SIZE_DIFF_PX", 6)

    for stack_idx, s in enumerate(stacks or []):
        boxes = s.get("boxes", [])
        if trace:
            print(f"v24.07 OVERHANG_AUDIT stack={stack_idx} box_count={len(boxes)}")
        for pair_idx in range(max(0, len(boxes) - 1)):
            upper = boxes[pair_idx]
            lower = boxes[pair_idx + 1]
            uw = max(1, upper["x_right"] - upper["x_left"])
            lw = max(1, lower["x_right"] - lower["x_left"])
            uh = max(1, upper["y_max"] - upper["y_min"])
            lh = max(1, lower["y_max"] - lower["y_min"])
            width_delta = abs(uw - lw)
            width_ratio = width_delta / max(1, max(uw, lw))
            vertical_gap = max(0, lower["y_min"] - upper["y_max"])
            pair_h = max(1, lower["y_max"] - upper["y_min"])
            reason = []
            if width_ratio < min_ratio or width_delta < min_px:
                reason.append("size_diff_below_5pct")
            if vertical_gap > max(8, int(pair_h * 0.20)):
                reason.append("not_visible_stacked_pair")
            if uw < 10 or lw < 10 or uh < 4 or lh < 4:
                reason.append("tiny_segment_artifact")
            if trace:
                print(f"v24.07 OVERHANG_AUDIT stack={stack_idx} pair={pair_idx} upper_w={uw}px lower_w={lw}px diff={width_delta}px ratio={width_ratio:.3f} vertical_gap={vertical_gap}px status={'REJECT ' + ','.join(reason) if reason else 'CANDIDATE_BUT_AUDIT_ONLY'}")
            if reason:
                continue
            x_min = min(upper["x_left"], lower["x_left"])
            x_max = max(upper["x_right"], lower["x_right"])
            y_min = upper["y_min"]
            y_max = lower["y_max"]
            audit_regions.append({
                "x_min": x_min, "y_min": y_min, "x_max": x_max, "y_max": y_max,
                "ratio": width_ratio,
                "width_delta_px": width_delta,
                "upper_width_px": uw,
                "lower_width_px": lw,
                "support_case": "UPPER_LOWER_SIZE_DIFF_AUDIT",
                "v2407_audit_only": True,
            })
    if globals().get("V2407_OVERHANG_AUDIT_ONLY", True) or not active:
        if trace and audit_regions:
            print(f"v24.07 OVERHANG_AUDIT_ONLY: {len(audit_regions)} candidate(s) suppressed; no OVERHANG marker/hazard emitted")
        return []
    return audit_regions

def detect_tall_unstable_regions_for_view(stacks):
    """v24.01 TallUnstableGuard.

    Original v24 considered a stack tall-unstable mainly from pixel height difference versus
    left/right neighbors. That caused false positives when isometric perspective or segmentation
    made equal-layer cargo appear taller.

    v24.01 changes ONLY this detector:
    - require a true interior stack with two neighbors;
    - require stronger height contrast;
    - require the candidate to have more detected boxes/layers than both neighbors;
    - reject suspiciously narrow edge fragments and overly wide merged stacks;
    - keep AI TALL_UNSTABLE claims gated by these deterministic regions downstream.
    """
    regions = []
    n = len(stacks or [])
    if n < 3:
        return regions

    heights = [max(1, s["floor_y"] - s["top_y"]) if s.get("boxes") else 0 for s in stacks]
    widths = [max(1, s["x1"] - s["x0"]) for s in stacks]
    median_w = _median_of(widths) or 1

    if globals().get("V2401_TALL_UNSTABLE_GUARD_ENABLED", True):
        min_ratio = globals().get("V2401_TALL_UNSTABLE_MIN_HEIGHT_RATIO", 0.45)
        neighbor_max_ratio = globals().get("V2401_TALL_UNSTABLE_NEIGHBOR_MAX_RATIO", 0.55)
        min_w_ratio = globals().get("V2401_TALL_UNSTABLE_MIN_WIDTH_RATIO_OF_MEDIAN", 0.70)
        max_w_ratio = globals().get("V2401_TALL_UNSTABLE_MAX_WIDTH_RATIO_OF_MEDIAN", 1.60)
        min_abs_h = globals().get("V2401_TALL_UNSTABLE_MIN_ABS_HEIGHT_PX", 25)
        require_box_count = globals().get("V2401_TALL_UNSTABLE_REQUIRE_BOX_COUNT_GT_NEIGHBORS", True)
    else:
        min_ratio = TALL_UNSTABLE_MIN_HEIGHT_RATIO
        neighbor_max_ratio = TALL_UNSTABLE_NEIGHBOR_MAX_RATIO
        min_w_ratio = 0.0
        max_w_ratio = 999.0
        min_abs_h = 1
        require_box_count = False

    trace = globals().get("V2401_TALL_UNSTABLE_TRACE", False)

    for i in range(1, n - 1):
        s = stacks[i]
        h_this = heights[i]
        if h_this < min_abs_h:
            if trace:
                print(f"v24.01 TALL_UNSTABLE reject idx={i}: height {h_this}px < min_abs {min_abs_h}px")
            continue

        current_w = widths[i]
        width_ratio = current_w / max(1, median_w)
        if width_ratio < min_w_ratio or width_ratio > max_w_ratio:
            if trace:
                print(f"v24.01 TALL_UNSTABLE reject idx={i}: width_ratio={width_ratio:.2f} outside [{min_w_ratio:.2f},{max_w_ratio:.2f}]")
            continue

        left_h, right_h = heights[i - 1], heights[i + 1]
        if left_h <= 0 or right_h <= 0:
            if trace:
                print(f"v24.01 TALL_UNSTABLE reject idx={i}: missing neighbor height left={left_h} right={right_h}")
            continue

        if require_box_count:
            cur_count = len(s.get("boxes") or [])
            left_count = len(stacks[i - 1].get("boxes") or [])
            right_count = len(stacks[i + 1].get("boxes") or [])
            if cur_count <= max(left_count, right_count):
                if trace:
                    print(f"v24.01 TALL_UNSTABLE reject idx={i}: box_count current={cur_count} neighbors=({left_count},{right_count})")
                continue

        neighbor_heights = [left_h, right_h]
        if not all(nh <= h_this * neighbor_max_ratio for nh in neighbor_heights):
            if trace:
                print(f"v24.01 TALL_UNSTABLE reject idx={i}: neighbor ratios=({left_h/h_this:.2f},{right_h/h_this:.2f}) > max {neighbor_max_ratio:.2f}")
            continue

        diff_ratio = 1 - (max(neighbor_heights) / h_this)
        if diff_ratio < min_ratio:
            if trace:
                print(f"v24.01 TALL_UNSTABLE reject idx={i}: diff_ratio={diff_ratio:.2f} < min {min_ratio:.2f}")
            continue

        regions.append({
            "x_min": s["x0"], "y_min": s["top_y"], "x_max": s["x1"], "y_max": s["floor_y"],
            "ratio": diff_ratio,
            "v2401_guard": True,
            "v2401_width_ratio": width_ratio,
            "v2401_height_px": h_this,
            "v2401_current_box_count": len(s.get("boxes") or []),
            "v2401_left_box_count": len(stacks[i - 1].get("boxes") or []),
            "v2401_right_box_count": len(stacks[i + 1].get("boxes") or []),
        })
    return regions

def _v2402_shift_abs_box_up(box, shift_ratio=0.50):
    """Shift an absolute (x0,y0,x1,y1) marker box upward by a fraction of its height."""
    try:
        x0, y0, x1, y1 = [float(v) for v in box]
        h = max(1.0, y1 - y0)
        shift = h * float(shift_ratio)
        return (int(x0), int(y0 - shift), int(x1), int(y1 - shift))
    except Exception:
        return box


def detect_lateral_imbalance_regions_for_view(stacks, rear_x0, rear_x1, view_label=None):
    """v24.05 rear-lateral tuning.

    Compare adjacent rear-zone stack heights and return a marker box that covers the visible cargo
    pair causing the height imbalance. For BACK view, marker is shifted upward so it lands on the
    green/blue/red cargo block area rather than the lower floor region.
    """
    relevant = [s for s in stacks if s["x1"] > rear_x0 and s["x0"] < rear_x1]
    relevant.sort(key=lambda s: s["x0"])
    regions = []
    for i in range(len(relevant) - 1):
        a, b = relevant[i], relevant[i + 1]
        ha = max(1, a["floor_y"] - a["top_y"]) if a.get("boxes") else 0
        hb = max(1, b["floor_y"] - b["top_y"]) if b.get("boxes") else 0
        if ha == 0 or hb == 0:
            continue
        taller_stack, shorter_stack = (a, b) if ha >= hb else (b, a)
        taller, shorter = (ha, hb) if ha >= hb else (hb, ha)
        ratio = 1 - (shorter / taller)
        if ratio >= LATERAL_IMBALANCE_MIN_RATIO:
            # Use visible cargo pair area, with top anchored to visible upper cargo and bottom kept
            # around the cargo body, not the floor. This makes AA04-05 BACK marker cover the blue/
            # green/red cargo stacks instead of the lower white/floor area.
            x_min = min(a["x0"], b["x0"])
            x_max = max(a["x1"], b["x1"])
            y_top_pair = min(a["top_y"], b["top_y"])
            y_floor_pair = max(a["floor_y"], b["floor_y"])
            pair_h = max(1, y_floor_pair - y_top_pair)
            # Cropping bottom by 18% reduces low/floor overreach while keeping visible box body.
            y_min = y_top_pair
            y_max = y_floor_pair - int(pair_h * 0.18) if globals().get("V2405_REAR_LATERAL_MARK_VISIBLE_PAIR_ONLY", True) else y_floor_pair
            if y_max <= y_min:
                y_max = y_floor_pair
            if str(view_label or "").upper() == "BACK":
                x_min, y_min, x_max, y_max = _v2405_shift_abs_box_up_for_back((x_min, y_min, x_max, y_max), view_label)
            regions.append({
                "x_min": x_min, "y_min": y_min, "x_max": x_max, "y_max": y_max,
                "ratio": ratio,
                "v2405_back_shift_up": str(view_label or "").upper() == "BACK",
                "v2405_source": "adjacent_rear_stack_height_pair",
                "v2405_taller_height": taller,
                "v2405_shorter_height": shorter,
            })
            if globals().get("V2405_REAR_LATERAL_TRACE", False):
                print(f"v24.05 REAR_LATERAL accept {view_label}: pair=({i},{i+1}) ratio={ratio:.2f} box=[{x_min},{y_min},{x_max},{y_max}]")
    return regions

def _v2405_region_to_box_2d(region, crop_w, crop_h, crop_y_start):
    try:
        return [
            ((float(region["y_min"]) - crop_y_start) / crop_h) * 1000,
            (float(region["x_min"]) / crop_w) * 1000,
            ((float(region["y_max"]) - crop_y_start) / crop_h) * 1000,
            (float(region["x_max"]) / crop_w) * 1000,
        ]
    except Exception:
        return None


def _v2405_shift_box_2d_up_for_back(box_2d, view_label, shift_ratio=None):
    if str(view_label or "").upper() != "BACK" or not box_2d or len(box_2d) != 4:
        return box_2d
    if not globals().get("V2405_REAR_LATERAL_FINAL_DRAW_SHIFT_BACK", True):
        return box_2d
    shift_ratio = globals().get("V2405_REAR_LATERAL_BACK_SHIFT_UP_RATIO", 0.50) if shift_ratio is None else shift_ratio
    try:
        y0, x0, y1, x1 = [float(v) for v in box_2d]
        h = max(1.0, y1 - y0)
        shift = h * float(shift_ratio)
        return [max(0.0, y0 - shift), x0, max(0.0, y1 - shift), x1]
    except Exception:
        return box_2d


def _v2405_shift_abs_box_up_for_back(box, view_label, shift_ratio=None):
    if str(view_label or "").upper() != "BACK" or not box or len(box) != 4:
        return box
    if not globals().get("V2405_REAR_LATERAL_FINAL_DRAW_SHIFT_BACK", True):
        return box
    shift_ratio = globals().get("V2405_REAR_LATERAL_BACK_SHIFT_UP_RATIO", 0.50) if shift_ratio is None else shift_ratio
    try:
        x0, y0, x1, y1 = [float(v) for v in box]
        h = max(1.0, y1 - y0)
        shift = h * float(shift_ratio)
        return (int(x0), int(y0 - shift), int(x1), int(y1 - shift))
    except Exception:
        return box


def get_max_lateral_imbalance_ratio_in_zone(stacks, rear_x0, rear_x1):
    """v24 NEW: คืนค่า "อัตราส่วนความแตกต่างความสูงสูงสุด" ระหว่างคู่ตั้งที่อยู่ติดกัน
    ในโซนประตูท้ายตู้ (ไม่กรองด้วย threshold) - ใช้สำหรับตัดสินใจ VETO การ claim ของ
    AI (ถ้าค่าสูงสุดที่วัดได้ต่ำมาก แสดงว่าไม่มีความไม่สมดุลจริงในโซนนี้เลย)"""
    relevant = [s for s in stacks if s["x1"] > rear_x0 and s["x0"] < rear_x1]
    relevant.sort(key=lambda s: s["x0"])
    max_ratio = 0.0
    for i in range(len(relevant) - 1):
        a, b = relevant[i], relevant[i + 1]
        ha = max(1, a["floor_y"] - a["top_y"]) if a["boxes"] else 0
        hb = max(1, b["floor_y"] - b["top_y"]) if b["boxes"] else 0
        if ha == 0 or hb == 0:
            continue
        taller, shorter = (ha, hb) if ha >= hb else (hb, ha)
        ratio = 1 - (shorter / taller)
        max_ratio = max(max_ratio, ratio)
    return max_ratio


def detect_inter_stack_lateral_gap_regions_for_view(stacks, min_gap_px=None, min_vertical_overlap_ratio=None):
    """v24.02 LATERAL_GAP: detect only real gaps between adjacent cargo stacks.

    This intentionally ignores the distance from the container top/bottom edge to cargo, because
    that created oversized boxes unrelated to side-by-side cargo separation.
    """
    min_gap_px = V2402_LATERAL_GAP_MIN_INTER_STACK_GAP_PX if min_gap_px is None else min_gap_px
    min_vertical_overlap_ratio = V2402_LATERAL_GAP_MIN_VERTICAL_OVERLAP_RATIO if min_vertical_overlap_ratio is None else min_vertical_overlap_ratio
    ss = sorted([s for s in (stacks or []) if s.get("boxes")], key=lambda s: s.get("x0", 0))
    regions = []
    for a, b in zip(ss, ss[1:]):
        gap = int(b["x0"] - a["x1"])
        if gap < min_gap_px:
            continue
        y0 = max(a["top_y"], b["top_y"])
        y1 = min(a["floor_y"], b["floor_y"])
        overlap = max(0, y1 - y0)
        min_h = max(1, min(a["floor_y"] - a["top_y"], b["floor_y"] - b["top_y"]))
        overlap_ratio = overlap / min_h
        if overlap_ratio < min_vertical_overlap_ratio:
            continue
        pad_y = max(4, int(overlap * 0.08))
        regions.append({
            "x_min": a["x1"], "y_min": max(0, y0 - pad_y),
            "x_max": b["x0"], "y_max": y1 + pad_y,
            "gap_px": gap,
            "vertical_overlap_ratio": overlap_ratio,
            "v2402_marker_policy": "inter_stack_gap_only",
        })
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
    """VETO gate ทั่วไป: ปฏิเสธ claim จาก AI ถ้า deterministic segmentation ไม่เจอ
    ตำแหน่งที่ทับซ้อนกันเลย"""
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


def _is_quota_error_message(msg):
    msg = str(msg or "").upper()
    return ("429" in msg) or ("RESOURCE_EXHAUSTED" in msg) or ("QUOTA" in msg) or ("RATE_LIMIT" in msg)


def _get_available_gemini_models():
    global LAST_WORKING_MODEL
    now = time.time()
    ordered = []
    if LAST_WORKING_MODEL:
        ordered.append(LAST_WORKING_MODEL)
    for model_name in GEMINI_MODEL_POOL:
        if model_name not in ordered:
            ordered.append(model_name)
    return [m for m in ordered if now >= MODEL_DISABLED_UNTIL.get(m, 0)]


def _mark_gemini_model_disabled(model_name, reason=""):
    MODEL_DISABLED_UNTIL[model_name] = time.time() + MODEL_COOLDOWN_SECONDS
    print(f"AI MODEL QUOTA COOLDOWN: {model_name} disabled for {MODEL_COOLDOWN_SECONDS}s reason={str(reason)[:120]}")


def _call_gemini_json(prompt, image, api_keys):
    global GLOBAL_KEY_INDEX, LAST_WORKING_MODEL
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
            models = _get_available_gemini_models()
            if not models:
                last_err = "All Gemini Flash models are temporarily disabled by quota cache"
                print("AI DISABLED: all Gemini Flash models are in quota cooldown")
                continue
            for model_name in models:
                try:
                    print(f"AI MODEL ACTIVE: {model_name} key_index={current_index}")
                    model = genai.GenerativeModel(model_name=model_name)
                    response = model.generate_content([prompt, image])
                    clean_text = clean_json_response(response.text if response.text else "{}")
                    result = json.loads(clean_text)
                    if isinstance(result, list):
                        result = result[0] if result else {}
                    GLOBAL_KEY_INDEX = current_index
                    LAST_WORKING_MODEL = model_name
                    return result
                except Exception as model_err:
                    last_err = str(model_err)
                    if _is_quota_error_message(last_err):
                        print(f"AI FALLBACK: {model_name} -> next model reason={last_err[:100]}")
                        _mark_gemini_model_disabled(model_name, last_err)
                        continue
                    raise
        except Exception as e:
            last_err = str(e)
            print(f"API Key index {current_index} failed: {last_err[:100]}")
            time.sleep(1)
            continue
    return {"rear_zone_risk": "ERROR", "front_zone_risk": "ERROR", "reasoning": last_err[:120], "confidence": "LOW"}

def analyze_rear_zone_with_ai(rear_crop, api_keys, view_label="UNKNOWN"):
    """
    v24 IMPROVED PROMPT: เพิ่มคำเตือนเฉพาะเจาะจงเรื่อง "กล่องสีเข้ม/สีผิดปกติ" (เช่น
    สีน้ำตาลเข้ม, สีแดงเข้ม/maroon) อาจถูกมองข้ามไปว่าไม่ใช่คาร์โก้ (เข้าใจผิดว่าเป็น
    เงา/พื้นหลัง/โครงสร้างตู้) ซึ่งเป็นสาเหตุที่ยืนยันแล้วจากการตรวจสอบไฟล์จริง (EC20-01,
    ED85-02) ว่าทำให้ AI มองข้ามกล่องบางใบ จนคำนวณความสูงรวมของตั้งผิดพลาด แล้วรายงาน
    REAR_LATERAL_IMBALANCE ที่ผิดพลาด (false positive)

    v22: ผลจาก AI นี้จะถูกนำไปเทียบ (corroborate) กับ deterministic per-box
    segmentation ใน process_request() - v24 เพิ่มการ VETO แบบมีเงื่อนไข (ไม่ใช่แค่
    FORCE อย่างเดียวเหมือน v21-v23.1) เมื่อ deterministic มี coverage สูงพอและวัดว่า
    ไม่มีความแตกต่างจริง
    """
    prompt = f"""
You are a Cargo Safety Inspector. This image is a cropped zoom of the DOOR END (REAR) zone of a container.
This is the {view_label} view.
YOUR TASK: Determine if there is a genuine safety risk at the door end.

IMPORTANT - COLOR AWARENESS: Cargo boxes in this diagram can be ANY color, including dark or
unusual colors (dark brown, dark maroon/red, dark olive, etc.), not just bright/vivid colors. A
box with a dark color is STILL cargo if it has a clear rectangular outline and an SKU label on it
- do NOT mistake a dark-colored box for a shadow, background element, or empty space. When
computing the TOTAL STACKED HEIGHT of a column, you MUST count every visible box regardless of
how dark or unusual its color appears, otherwise you will underestimate that stack's true height
and incorrectly conclude there is a height imbalance where none exists.

RULES (numeric thresholds - apply consistently, do not be overly cautious):
1. REAR_EMPTY_RISK: Flag if there is empty floor space near the door of more than roughly 20% of
   the container height, OR cargo drops off sharply leaving a dangerous unsupported edge.
2. REAR_LATERAL_IMBALANCE: Flag if the TOTAL STACKED HEIGHT of cargo (adding up ALL boxes stacked
   in that column, from floor to top - not just a single box, and counting dark-colored boxes too,
   see COLOR AWARENESS note above) on one side of the door zone differs from the total stacked
   height on an adjacent position by MORE than approximately 40-50% of the taller stack's total
   height. This is a real, measurable visual difference.

   IMPORTANT - look carefully at EVERY stack position, not just left-vs-right overall: in this
   isometric 3D view, a shorter stack (e.g. only 1 tier tall) sitting at a different depth/width
   position than a taller stack (e.g. 2 tiers tall) may appear to be PARTIALLY OVERLAPPED OR
   PARTIALLY HIDDEN BEHIND the taller stack from this viewing angle - it does NOT mean they are
   the same height. If you can see even a portion of a stack that is clearly shorter than its
   immediate neighbors, this IS a genuine REAR_LATERAL_IMBALANCE risk. Do not dismiss this just
   because the stacks appear to visually overlap or touch in the 2D projection.
3. The container wall/floor/frame structure itself is NOT cargo - never flag it. But remember: a
   dark-colored BOX with an SKU label is cargo, not structure (see COLOR AWARENESS above).
4. If cargo reasonably fills the rear area and all stacks (including hidden/partially-visible ones,
   and including all dark-colored boxes counted properly) are close in total height (within ~1
   small tier) -> SAFE.

IMPORTANT - if you flag a risk, you MUST also provide "box_2d" pinpointing EXACTLY where the
problem is visible in THIS image (the specific shorter stack, or the boundary between stacks with
different total heights). Use [ymin, xmin, ymax, xmax] format with values 0-1000 normalized to
this image's own size. The box must tightly enclose the actual shorter stack (or the height-
mismatch boundary) - not the whole image, not empty background.

Return ONLY this exact JSON:
{{"rear_zone_risk":"REAR_EMPTY_RISK"|"REAR_LATERAL_IMBALANCE"|"BOTH"|"SAFE","reasoning":"describe what you see, including approximate height difference if any, and specifically note if any stack appears partially hidden/overlapped by a taller neighbor, and confirm you counted any dark-colored boxes as cargo","confidence":"HIGH"|"MEDIUM"|"LOW","box_2d":[ymin,xmin,ymax,xmax]}}
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
    global GLOBAL_KEY_INDEX, LAST_WORKING_MODEL
    api_keys = get_api_keys_pool()
    if not api_keys:
        return [{"risk_type": "ERROR", "description": "No Gemini API Keys found."}]

    prompt = f"""
You are an expert Cargo Loading Safety Inspector analyzing a 3D cargo load plan.

VIEW LAYOUT: {layout_desc}
FIXED ORIENTATION (a known fact about how this diagram type is always drawn - trust it completely):
- FRONT view: REAR/door side is {front_rear}; FRONT/head-wall side is {front_wall}.
- BACK view: REAR/door side is {back_rear}; FRONT/head-wall side is {back_wall}.

IMPORTANT - COLOR AWARENESS: Cargo boxes can be ANY color, including dark or unusual colors (dark
brown, dark maroon/red, dark olive/yellow, etc.) - these are still cargo if they have a clear
rectangular outline and SKU label. Do not mistake dark-colored boxes for shadows or background.

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
- OVERHANG_RISK: cargo boxes are visibly stacked in the same stack from lower box to upper box, and the visible size/width of the stacked boxes differs by about 5% or more so the upper/lower support is mismatched. Do NOT flag thin outer edges or isometric perspective artifacts unless the upper-lower box pair and size mismatch are clear.

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
                models = _get_available_gemini_models()
                if not models:
                    last_error_msg = "All Gemini Flash models are temporarily disabled by quota cache"
                    print("AI DISABLED: all Gemini Flash models are in quota cooldown")
                    continue
                for model_name in models:
                    try:
                        print(f"AI MODEL ACTIVE: {model_name} key_index={current_index} diagram")
                        model = genai.GenerativeModel(model_name=model_name)
                        response = model.generate_content([prompt, diagram_image])
                        clean_text = clean_json_response(response.text if response.text else "[]")
                        if not clean_text or clean_text in ('""', "[]"):
                            GLOBAL_KEY_INDEX = current_index
                            LAST_WORKING_MODEL = model_name
                            return []
                        risks = json.loads(clean_text)
                        if isinstance(risks, dict):
                            risks = [risks]
                        GLOBAL_KEY_INDEX = current_index
                        LAST_WORKING_MODEL = model_name
                        return risks
                    except Exception as model_err:
                        last_error_msg = str(model_err)
                        if _is_quota_error_message(last_error_msg):
                            print(f"AI FALLBACK: {model_name} -> next model reason={last_error_msg[:100]}")
                            _mark_gemini_model_disabled(model_name, last_error_msg)
                            continue
                        raise
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
        if rt == "STEP_DOWN_RISK" and globals().get("V2410_STEPDOWN_DISABLE_MERGE", True):
            groups.append({"key": ("STEP_DOWN_KEEP", i), "items": [(i, r)]})
            continue
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
        unused_floor_mm = extract_unused_floor_mm(pdf_bytes)

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

        # v22/v24: สร้าง per-box stack model (deterministic) สำหรับ OVERHANG_RISK,
        # TALL_UNSTABLE_RISK, REAR_LATERAL_IMBALANCE - ดูหัวข้อ "PER-BOX SEGMENTATION"
        # ด้านบนสำหรับรายละเอียดอัลกอริทึมและข้อจำกัด (v24: แก้บั๊ก under-segmentation
        # หลักที่พบจากการทดสอบไฟล์จริง 6 ไฟล์)
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
                      f"height_diff_ratio={r['ratio']*100:.1f}% (threshold={V2401_TALL_UNSTABLE_MIN_HEIGHT_RATIO*100:.0f}%, v24.01 guard)")

        # v24.3 NEW: LOCAL DEPTH-GAP SCAN - จับ "หลุมเฉพาะจุด" ที่ compute_lateral_gap_ratio
        # แบบเดิม (whole-container average) พลาดไป - ดู CHANGELOG ที่ค่าคงที่ LOCAL_GAP_*
        # สำหรับรายละเอียด root cause (พบจากผู้ใช้ชี้ตำแหน่งด้วยการวงสีแดงใน EC50-01/EC51-02)
        local_depth_gap_regions = detect_local_depth_gap_per_view(diagram_crop, layout, crop_w, crop_h,
                                                                     crop_y_start, container_bounds, cargo_extent)
        if globals().get("V2407_STEP_DOWN_STACK_ADJACENCY_ENABLED", True):
            for _view in ("FRONT", "BACK"):
                _extra_step_regions = detect_step_down_regions_from_stack_model(stack_box_model.get(_view, []), view_label=_view)
                if _extra_step_regions:
                    step_down_regions.setdefault(_view, [])
                    step_down_regions[_view].extend(_extra_step_regions)

        # v24.10: keep only the strongest STEP_DOWN pair per view before AI and forced append.
        if globals().get("V2410_STEPDOWN_STRONGEST_ONLY", True):
            for _view in ("FRONT", "BACK"):
                _regions = list(step_down_regions.get(_view, []) or [])
                if len(_regions) > 1:
                    _best = max(_regions, key=lambda rr: rr.get("ratio", 0))
                    print(f"v24.10 STEP_DOWN strongest-only ({_view}): kept ratio={_best.get('ratio',0)*100:.1f}% from {len(_regions)} candidate(s)")
                    step_down_regions[_view] = [_best]

        inter_stack_gap_regions = {"FRONT": [], "BACK": []}
        for _v in ("FRONT", "BACK"):
            inter_stack_gap_regions[_v] = detect_inter_stack_lateral_gap_regions_for_view(stack_box_model.get(_v, []))
            for _r in inter_stack_gap_regions[_v]:
                print(f"v24.02 inter-stack LATERAL_GAP candidate ({_v}): x=[{_r['x_min']}-{_r['x_max']}] y=[{_r['y_min']}-{_r['y_max']}] gap={_r['gap_px']}px overlap={_r['vertical_overlap_ratio']:.2f}")

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
                if globals().get("V2407_OVERHANG_DISABLE_AI_ACCEPT", True) or globals().get("V2407_OVERHANG_AUDIT_ONLY", True):
                    print(f"v24.07 OVERHANG AI claim REJECTED: audit-only mode (description: {r.get('description', '')[:100]})")
                elif has_valid_box:
                    regions_for_view = overhang_regions.get(view_of_claim, [])
                    if _claim_overlaps_regions(box_2d, crop_w, crop_h, crop_y_start, regions_for_view):
                        all_risks.append(r)
                    else:
                        print(f"Gemini OVERHANG_RISK claim for {view_of_claim} view REJECTED by deterministic "
                              f"per-box gate (description: {r.get('description', '')[:100]})")
                else:
                    print("Gemini OVERHANG_RISK claim REJECTED - missing valid view/box_2d for verification")
            elif rt == "TALL_UNSTABLE_RISK":
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
                if globals().get("V2407_OVERHANG_AUDIT_ONLY", True):
                    print("v24.07 OVERHANG forced candidate suppressed: audit-only mode")
                    continue
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
                    "description": f"พบกล่องสินค้าซ้อนกันในกองเดียวกันที่ขนาด/ความกว้างของกล่องบน-ล่างต่างกันตั้งแต่ประมาณ 5% ขึ้นไป วัดได้ {region['ratio']*100:.0f}% (marker ชี้คู่กล่องต้นเหตุ: {region.get('support_case','STACK_SIZE_MISMATCH')})",
                })
            for region in tall_unstable_regions.get(view_label, []):
                if region["ratio"] < V2401_TALL_UNSTABLE_MIN_HEIGHT_RATIO:
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
                        if view_label == "BACK":
                            pb = _v2405_shift_abs_box_up_for_back(pb, view_label)
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

        # v24 NEW: VETO GATE สำหรับ REAR_LATERAL_IMBALANCE - เดิม (v21-v23.1) ใช้ FORCE
        # เท่านั้น (ไม่ veto AI) เพราะ deterministic segmentation ยังไม่แม่นยำพอ แต่หลัง
        # แก้ไข v24 (per-box segmentation แม่นยำขึ้นมาก) จึงเพิ่ม VETO แบบมีเงื่อนไข:
        # ต้องมี coverage สูงพอ (>= LATERAL_IMBALANCE_VETO_MIN_COVERAGE) และวัดได้ว่า
        # ความแตกต่างความสูงสูงสุดในโซนประตูท้ายตู้ต่ำกว่า
        # LATERAL_IMBALANCE_VETO_MAX_RATIO (มี "buffer zone" ระหว่าง veto กับ force
        # เพื่อความปลอดภัย - ถ้าอยู่ระหว่างกลางจะไม่ veto และไม่ force เพื่อคง behavior
        # แบบ AI-first เดิมไว้ในกรณีที่ไม่ชัดเจนพอ)
        def _should_veto_lateral_imbalance(view_label):
            coverage = stack_box_model.get(f"{view_label}_coverage_ratio")
            if coverage is None or coverage < LATERAL_IMBALANCE_VETO_MIN_COVERAGE:
                return False
            cb = container_bounds.get(view_label)
            if not cb:
                return False
            rear_side = HARDCODED_REAR_SIDE[view_label]
            container_width = cb["xmax"] - cb["xmin"]
            if rear_side == "LEFT":
                rear_x0, rear_x1 = cb["xmin"], cb["xmin"] + int(container_width * 0.45)
            else:
                rear_x0, rear_x1 = cb["xmax"] - int(container_width * 0.45), cb["xmax"]
            max_ratio = get_max_lateral_imbalance_ratio_in_zone(stack_box_model.get(view_label, []), rear_x0, rear_x1)
            if max_ratio < LATERAL_IMBALANCE_VETO_MAX_RATIO:
                print(f"REAR_LATERAL_IMBALANCE VETO candidate ({view_label}): coverage={coverage:.2f} "
                      f"(>= {LATERAL_IMBALANCE_VETO_MIN_COVERAGE}), max measured height-diff ratio in rear zone "
                      f"= {max_ratio:.2f} (< veto threshold {LATERAL_IMBALANCE_VETO_MAX_RATIO}) -> VETO")
                return True
            return False

        def _v2405_best_rear_lateral_box_2d(view_label):
            cb = container_bounds.get(view_label)
            if not cb:
                return None
            rear_side = HARDCODED_REAR_SIDE[view_label]
            container_width = cb["xmax"] - cb["xmin"]
            if rear_side == "LEFT":
                rear_x0, rear_x1 = cb["xmin"], cb["xmin"] + int(container_width * 0.45)
            else:
                rear_x0, rear_x1 = cb["xmax"] - int(container_width * 0.45), cb["xmax"]
            det_regions = detect_lateral_imbalance_regions_for_view(stack_box_model.get(view_label, []), rear_x0, rear_x1, view_label=view_label)
            if not det_regions:
                return None
            best = max(det_regions, key=lambda rr: rr.get("ratio", 0))
            return _v2405_region_to_box_2d(best, crop_w, crop_h, crop_y_start)

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
            # v24: เพิ่ม VETO gate ก่อนยอมรับ claim ของ AI (ดู _should_veto_lateral_imbalance)
            if rear_zone_risk in ("REAR_LATERAL_IMBALANCE", "BOTH") and confidence in ("HIGH", "MEDIUM") and view_label not in _existing_risk_views("REAR_LATERAL"):
                if _should_veto_lateral_imbalance(view_label):
                    print(f"REAR_LATERAL_IMBALANCE claim ({view_label}) VETOED - deterministic per-box segmentation "
                          f"shows no genuine height difference in rear zone (AI reasoning: {rear_result.get('reasoning','')[:150]})")
                else:
                    all_risks.append({"view": view_label, "risk_type": "REAR_LATERAL_IMBALANCE", "direction": "LATERAL", "lateral_side": "N/A", "reasoning": rear_result.get("reasoning", ""), "description": "พบสินค้าท้ายตู้สูงต่ำไม่เท่ากัน (วิเคราะห์จาก Zoom ท้ายตู้)", "box_2d": _v2405_best_rear_lateral_box_2d(view_label)})
                    print(f"REAR_LATERAL_IMBALANCE ({view_label}) accepted with confidence={confidence}")

        # v22 FORCE: deterministic corroboration สำหรับ REAR_LATERAL_IMBALANCE เฉพาะ
        # กรณีที่ AI บอก SAFE/ไม่ผ่านเกณฑ์ confidence แต่ per-box segmentation เจอ
        # ความไม่สมดุลชัดเจนในโซนประตูท้ายตู้
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
            det_regions = detect_lateral_imbalance_regions_for_view(stack_box_model.get(view_label, []), rear_x0, rear_x1, view_label=view_label)
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
                    "box_2d": _v2405_region_to_box_2d(region, crop_w, crop_h, crop_y_start),
                })
                break

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
            # v24.02: LATERAL_GAP_RISK must come only from a gap between adjacent cargo boxes/stacks.
            # Do not use top/bottom container-to-cargo distance because it creates oversized markers.
            best_region = None
            if inter_stack_gap_regions.get(view_label):
                best_region = max(inter_stack_gap_regions[view_label], key=lambda r: r["gap_px"])

            if best_region and view_label not in _existing_risk_views("LATERAL_GAP"):
                ymin_norm = ((best_region["y_min"] - crop_y_start) / crop_h) * 1000
                ymax_norm = ((best_region["y_max"] - crop_y_start) / crop_h) * 1000
                xmin_norm = (best_region["x_min"] / crop_w) * 1000
                xmax_norm = (best_region["x_max"] / crop_w) * 1000
                print(f"FORCED LATERAL_GAP_RISK ({view_label}) from v24.02 inter-stack box gap only "
                      f"(gap={best_region['gap_px']}px, overlap={best_region['vertical_overlap_ratio']:.2f})")
                all_risks.append({
                    "view": view_label,
                    "risk_type": "LATERAL_GAP_RISK",
                    "direction": "LATERAL",
                    "lateral_side": "N/A",
                    "reasoning": "FORCED_V2402_INTER_STACK_LATERAL_GAP_ONLY",
                    "description": f"พบช่องว่างระหว่างกล่อง/ตั้งสินค้าโดยตรง กว้างประมาณ {best_region['gap_px']}px (ไม่ใช้ช่องว่างจากขอบตู้บน/ล่าง)",
                    "box_2d": [ymin_norm, xmin_norm, ymax_norm, xmax_norm],
                })
            else:
                if globals().get("V2402_TRACE", False):
                    print(f"v24.02 LATERAL_GAP ({view_label}) skipped: no qualifying inter-stack gap")

        # v24.1 NEW: เช่นเดียวกับ LATERAL_GAP_RISK - ใช้ "Unused Floor" ที่พิมพ์จาก PDF
        # เป็นตัวช่วยผ่อนเกณฑ์ ratio สำหรับ REAR_EMPTY_RISK/FRONT_EMPTY_RISK ด้วย เผื่อ
        # กรณีที่ช่องว่างจริงอยู่ฝั่งหน้า/หลังตู้แทนที่จะเป็นด้านข้าง (ตรวจสอบทุก
        # ผลรวมที่มี เพื่อครอบคลุมทุกทิศทางที่ "Unused Floor" อาจสะท้อนถึง)
        if unused_floor_mm is not None and unused_floor_mm >= UNUSED_FLOOR_MIN_MM:
            for gap_risk_type in ("REAR_EMPTY_RISK", "FRONT_EMPTY_RISK"):
                for view_label in ("FRONT", "BACK"):
                    if view_label in _existing_risk_views(gap_risk_type.replace("_RISK", "")):
                        continue
                    ratio_val = gap_values_ratio.get((view_label, gap_risk_type))
                    if ratio_val is not None and ratio_val >= UNUSED_FLOOR_RELAXED_GAP_RATIO:
                        print(f"FORCED {gap_risk_type} ({view_label}) corroborated by printed 'Unused Floor: "
                              f"{unused_floor_mm/25.4:.1f}in' + pixel ratio {ratio_val*100:.1f}% "
                              f"(relaxed threshold {UNUSED_FLOOR_RELAXED_GAP_RATIO*100:.0f}%)")
                        desc_zone = "ประตูท้ายตู้" if gap_risk_type == "REAR_EMPTY_RISK" else "ผนังหัวตู้"
                        all_risks.append({"view": view_label, "risk_type": gap_risk_type,
                                           "direction": "LONGITUDINAL", "lateral_side": "N/A",
                                           "reasoning": "FORCED_BY_PRINTED_UNUSED_FLOOR",
                                           "description": f"พบพื้นที่ว่างบริเวณ{desc_zone}ประมาณ {ratio_val*100:.0f}% (ยืนยันจากค่า Unused Floor: {unused_floor_mm/25.4:.1f} นิ้ว ที่พิมพ์บนเอกสาร)",
                                           "box_2d": None})

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
                    if risk_type == "REAR_LATERAL_IMBALANCE":
                        precise = _v2405_shift_abs_box_up_for_back(precise, resolved_view)
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
                    if risk_type == "REAR_LATERAL_IMBALANCE":
                        abs_xmin, abs_ymin, abs_xmax, abs_ymax = _v2405_shift_abs_box_up_for_back((abs_xmin, abs_ymin, abs_xmax, abs_ymax), resolved_view)

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
                    if risk_type == "REAR_LATERAL_IMBALANCE":
                        fallback = _v2405_shift_abs_box_up_for_back(fallback, resolved_view)
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
        return ({"status": status_text, "hazardCount": len(real_hazards), "layout": layout, "actionRequired": action_text, "processedImageUrl": processed_image_url,
            "checkerVersion": "V24.10",
            "benchmarkMode": "v24.10_auto_gemini_pool_stepdown_fix"}, 200, headers)
    except Exception as e:
        err_trace = traceback.format_exc()
        print("CRITICAL ERROR DETAILS:\n", err_trace)
        gc.collect()
        return ({"error": str(e), "trace": err_trace[-500:]}, 500, headers)


# ===== V24.03_LOCALIZATION_FIX =====
V2403_LOCALIZATION_FIX=True
# OVERHANG: require real upper/lower pair and suppress perspective-only edge markers.
# REAR_LATERAL_IMBALANCE: apply final BACK marker upward shift (50%) at draw stage.
# LATERAL_GAP: accept only gaps bounded by left and right cargo stacks.


# V24.04 build marker
V2404_OVERHANG_STACK_SIZE_GUARD_BUILD = True


# V24.05 build marker
V2405_REAR_LATERAL_IMBALANCE_TUNE_BUILD = True


# V24.06 build marker
V2407_OVERHANG_AUDIT_STEP_DOWN_FIX_BUILD = True


# V24.09 controls
V2409_STEPDOWN_STRONGEST_ONLY=True
V2409_STEPDOWN_DISABLE_MERGE=True
V2409_STEPDOWN_BOUNDARY_RATIO=0.25
V2409_BUILD=True
