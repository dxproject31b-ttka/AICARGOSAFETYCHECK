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
# AI Cargo Safety Checker - High Precision v20
#
# v20 - ทำให้ทุก risk type มี deterministic GATE (veto) ครบสมมาตรกัน ก่อนหน้านี้มี
#   เพียง REAR_EMPTY_RISK/FRONT_EMPTY_RISK/STEP_DOWN_RISK เท่านั้นที่มี GATE ส่วน
#   REAR_LATERAL_IMBALANCE, LATERAL_GAP_RISK (จาก AI claim), TALL_UNSTABLE_RISK,
#   OVERHANG_RISK ยังคงรับคำตอบจาก Gemini ตรงๆ โดยไม่มีการตรวจสอบพิกเซลจริงใดๆ เลย -
#   v20 นี้ปิดช่องโหว่ทั้งหมดให้ครบทุกตัว:
#
#   1) REAR_LATERAL_IMBALANCE - แก้บั๊กไม่มี "GATE" สำหรับ claim จาก Gemini
#   (บั๊กแบบเดียวกับที่ STEP_DOWN_RISK เจอใน v19 แต่ตอนนั้นแก้เฉพาะ STEP_DOWN_RISK
#   ยังไม่ได้แก้ REAR_LATERAL_IMBALANCE ด้วย)
#
#   พบจากไฟล์ EE06-01,04 (สินค้า SKU เดียวกันทั้งหมด 12 กล่อง เรียง 4x3 เต็มพอดี
#   ไม่มีงานสูง-ต่ำต่างกันจริงที่ฝั่งประตูท้ายตู้เลย) แต่ระบบกลับวาดกรอบสีชมพู
#   (deeppink) แจ้ง REAR_LATERAL_IMBALANCE ผิดพลาด โดยกรอบไปเกาะอยู่ที่ "รอยต่อ"
#   ของภาพ isometric (จุดที่หลังคากล่อง 2 ใบมาบรรจบกันเป็นรูปตัว V) ซึ่งเป็น
#   artifact ของการวาดภาพ 3D ไม่ใช่ช่องว่างหรือความสูงต่างกันจริง
#
#   Root cause: REAR_EMPTY_RISK และ FRONT_EMPTY_RISK มีทั้งกลไก FORCE (สร้างเองถ้า
#   deterministic พบแต่ Gemini พลาด) และ GATE (ปฏิเสธถ้า Gemini flag ผิด/หลอน) ผ่าน
#   _passes_deterministic_gate() ที่วัดระยะห่างจริงจากพิกเซล/มม. ก่อนยอมรับ claim
#   แต่ REAR_LATERAL_IMBALANCE รับ claim ของ Gemini ตรงๆ ทันทีที่ confidence เป็น
#   HIGH หรือ MEDIUM โดยไม่มีการตรวจสอบพิกเซลจริงใดๆ เลย (ไม่มี GATE) ทำให้เมื่อ
#   Gemini "เข้าใจผิด" ว่าซ้าย-ขวาสูงต่ำไม่เท่ากัน (ความไม่แน่นอนของ generative
#   model ตอบสนองต่อรอยต่อภาพ) ไม่มีกลไกใดมาตรวจสอบค้านเลย
#
#   วิธีแก้: เพิ่ม _measure_rear_lateral_height_diff_ratio() วัดความสูงกองสินค้า
#   จริงฝั่งซ้ายเทียบฝั่งขวาของภาพ zoom ประตูท้ายตู้ด้วย height-profile แบบเดียวกับ
#   ที่ใช้กับ STEP_DOWN_RISK แล้วเพิ่ม _passes_lateral_imbalance_gate() เป็น GATE
#   ปฏิเสธ claim ของ Gemini ทันทีถ้าความต่างของความสูงที่วัดได้จริงไม่ถึงเกณฑ์
#   MIN_REAR_LATERAL_IMBALANCE_RATIO (ไม่ว่า Gemini จะมั่นใจแค่ไหนก็ตาม) -
#   ตอนนี้ REAR_LATERAL_IMBALANCE มีทั้ง GATE สมมาตรกับ REAR_EMPTY_RISK/
#   FRONT_EMPTY_RISK/STEP_DOWN_RISK ครบทุกตัวแล้ว
#
#   2) LATERAL_GAP_RISK - claim ของ Gemini (จาก analyze_diagram_image_with_ai)
#   ก่อนหน้านี้ผ่านเข้า all_risks ตรงๆ ทันที (else-branch ของ filter loop) โดยไม่มี
#   GATE เลย ทั้งที่ระบบมีฟังก์ชัน compute_lateral_gap_mm/ratio อยู่แล้ว (เดิมใช้เป็น
#   FORCE เท่านั้น) - v20 ย้ายการคำนวณ lateral gap มาไว้ตั้งแต่ต้น (ก่อนเรียก Gemini)
#   แล้วใช้ค่าเดียวกันทั้งเป็น GATE (ปฏิเสธ claim ถ้าวัดจริงไม่ถึงเกณฑ์) และ FORCE
#   (single source of truth เดียวกัน ไม่ใช้เกณฑ์คนละชุด)
#
#   3) TALL_UNSTABLE_RISK - เดิมไม่มี deterministic detection ใดๆ เลย รับ claim
#   ของ Gemini ตรงๆ ทั้งหมด - v20 เพิ่ม _detect_tall_unstable_regions() ใช้
#   height-profile เดียวกับ STEP_DOWN_RISK แต่ตรวจหา "กองสูงโดดเดี่ยว" (สูงกว่า
#   เพื่อนบ้านทั้งสองฝั่งพร้อมกัน และแคบพอที่จะเป็นกองเดี่ยว ไม่ใช่แนวยาว) แล้วเพิ่ม
#   GATE ผ่าน _region_claim_overlaps_detection() ปฏิเสธ claim ที่ไม่ทับซ้อนกับจุดที่
#   ตรวจพบจริง พร้อม FORCE สร้างเองถ้า deterministic พบแต่ Gemini พลาด
#
#   4) OVERHANG_RISK - เดิมไม่มี deterministic detection ใดๆ เลยเช่นกัน - v20 เพิ่ม
#   _detect_overhang_regions() แบ่งพื้นที่สินค้าเป็นแถบแนวตั้ง (tier bands) วัดขอบเขต
#   ซ้าย-ขวาของแต่ละแถบ เปรียบเทียบแถบบนกับแถบล่างว่ายื่นล้ำเกินเกณฑ์หรือไม่ แล้วเพิ่ม
#   GATE + FORCE แบบเดียวกับ TALL_UNSTABLE_RISK
#
#   *** พบบั๊กจากการทดสอบจริงกับไฟล์ EE06-01,04 (โหลดเต็มตู้ปลอดภัย 100%) ***:
#   เวอร์ชันแรกของ _detect_overhang_regions เปรียบเทียบแถบที่ติดกันตรงๆ โดยไม่ได้
#   คำนึงถึง 'เส้นทแยงหลังคาตู้' (isometric roofline) ที่ทำให้ขอบเขตสินค้าเปลี่ยนแปลง
#   อย่างต่อเนื่องราบเรียบไปหลายแถบ (สูงสุดถึง 29.3% ratio) และ 'จุดยอด/จุดหักมุม'
#   ของทรงข้าวหลามตัดในภาพ isometric - ทำให้ตรวจพบ false positive 13 จุดในการ
#   ทดสอบครั้งแรก ก่อนแก้เป็น 4 จุด แล้วแก้จนเหลือ 0 จุด ด้วย 3 มาตรการร่วมกัน:
#   (ก) แยก 'จุดกระโดดเดี่ยว' (isolated spike, run<=2 แถบ) ออกจาก 'ความลาดเอียง
#   ต่อเนื่องจากมุมมอง 3D' (long taper run) ด้วย OVERHANG_MAX_TAPER_RUN_BANDS
#   (ข) ตัดแถบขอบบน-ล่างสุดทิ้ง (OVERHANG_EDGE_EXCLUSION_BANDS) เพราะเป็นจุดยอด
#   ตามธรรมชาติของทรงข้าวหลามตัด (ข) ปรับ MIN_OVERHANG_RATIO เป็น 0.32 (32%) ให้อยู่
#   เหนือ noise floor ที่วัดได้จริงสูงสุด (29.3%) พร้อม margin ปลอดภัย - ยืนยันด้วย
#   unit test สังเคราะห์ว่ายังตรวจจับกรณี overhang จริงที่รุนแรง (>=33%) ได้ถูกต้อง
#
# v19 - แก้ 2 บั๊กสำคัญที่พบจากการใช้งานจริง:
#
#   BUG 1 (สำคัญที่สุด): STEP_DOWN_RISK ไม่มี "GATE" (veto) สำหรับ claim จาก Gemini
#   พบจากไฟล์ EE07 (โหลดเต็มตู้ 95.1%, สินค้าสม่ำเสมอสมบูรณ์แบบ - ยืนยันด้วยการวัด
#   พิกเซลจริงว่า delta สูงสุดทั้งภาพคือ 3px เท่านั้น จากทั้งหมด ต่ำกว่า threshold
#   (~30px) มาก - ไม่มีจุดกระโดดใดๆ เลย) แต่ระบบกลับรายงาน STEP_DOWN_RISK ผิดพลาด
#
#   Root cause: ตอนออกแบบ v18 ผมเพิ่มกลไก FORCE (สร้างเองถ้า deterministic พบแต่
#   Gemini พลาด) ให้ STEP_DOWN_RISK แต่ลืมเพิ่มกลไก GATE (ปฏิเสธถ้า Gemini flag ผิด/
#   หลอน) ทำให้ไม่สมมาตรกับ FRONT_EMPTY_RISK/REAR_EMPTY_RISK ที่มีทั้ง FORCE+GATE
#   ครบ - เมื่อ Gemini วิเคราะห์ภาพรวมแล้ว "เข้าใจผิด" ว่ามีความต่างระดับ (ความไม่
#   แน่นอนของ generative model) ไม่มีกลไกใดมาตรวจสอบค้านเลย
#
#   วิธีแก้: เพิ่ม _step_down_claim_overlaps_detection() ตรวจสอบว่าตำแหน่งที่ Gemini
#   อ้างว่าเป็น STEP_DOWN_RISK (จาก box_2d) ทับซ้อนกับจุดกระโดดจริงที่ deterministic
#   height-profile ตรวจพบหรือไม่ - ถ้าไม่มี region ใดๆ ที่ deterministic ตรวจพบเลย
#   สำหรับ view นั้น (คือภาพนั้นไม่มีความต่างระดับจริงตามที่วัดได้) ให้ปฏิเสธ (veto)
#   claim ของ Gemini ทันที ไม่ว่า Gemini จะมั่นใจแค่ไหนก็ตาม
#
#   BUG 2: height-profile discontinuity ถูก merge ผิดพลาดเมื่อมี pattern แบบ 'บันได'
#   (เตี้ย -> กลาง -> สูง) พบจากไฟล์ RD09 ที่มี 2 จุดเสี่ยงแยกกันจริง (กองเตี้ยสุด
#   "ด้านนอก" และกองกลาง "ด้านใน" ที่เตี้ยกว่ากองสูงสุด) แต่ระบบเดิมรวมเป็นกรอบเดียว
#   ผิดๆ เพราะ merge ตามระยะห่าง x โดยไม่สนใจว่าเป็นกองเดียวกันจริงหรือไม่
#
#   วิธีแก้: เปลี่ยนจาก 'เปรียบเทียบทีละคู่ segment แล้ว merge ตามระยะห่าง' เป็น
#   'ตรวจสอบแต่ละ segment ว่าเตี้ยกว่าเพื่อนบ้านซ้าย/ขวาหรือไม่แยกกัน' - segment ใด
#   เตี้ยกว่าเพื่อนบ้านฝั่งใดฝั่งหนึ่งเกินเกณฑ์ จะกลายเป็นจุดเสี่ยงของตัวเองทันที ไม่
#   merge กับ segment อื่นอีกต่อไป (แต่ละกองที่เตี้ยกว่าเพื่อนบ้านคือจุดเสี่ยงแยกกันจริง)
#
# v18 - เพิ่มกลไก deterministic (height-profile) สำหรับ STEP_DOWN_RISK
# v17 - แก้บั๊ก LATERAL_GAP_RISK ไม่ทำงานเมื่อคาลิเบรต mm ไม่สำเร็จ (ratio fallback)
# v16 - เพิ่ม LATERAL_GAP_RISK deterministic + FIX FRONT_EMPTY_RISK ใช้ Front view
#   เป็นแหล่งข้อมูลเดียว
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
# v19: เกณฑ์ overlap ขั้นต่ำระหว่าง claim ของ Gemini กับ region ที่ deterministic
# ตรวจพบจริง เพื่อยอมรับ claim นั้น (ถ้าต่ำกว่านี้ = ปฏิเสธ เพราะถือว่าไม่มีหลักฐาน
# สนับสนุนตำแหน่งที่ Gemini อ้างเลย)
STEP_DOWN_CLAIM_OVERLAP_THRESHOLD = 0.10

# v20: เกณฑ์ความต่างของความสูงจริง (วัดจากพิกเซล) ระหว่างฝั่งซ้าย-ขวาของภาพ zoom
# ประตูท้ายตู้ ที่ต้องพบอย่างน้อยเท่านี้ ถึงจะยอมรับ claim REAR_LATERAL_IMBALANCE
# ของ Gemini (ถ้าต่ำกว่านี้ = ปฏิเสธ เพราะถือว่าไม่มีหลักฐานทางพิกเซลสนับสนุนเลย -
# นี่คือ GATE ที่ขาดหายไปสำหรับ REAR_LATERAL_IMBALANCE)
MIN_REAR_LATERAL_IMBALANCE_RATIO = 0.25

# v20: เกณฑ์สำหรับ TALL_UNSTABLE_RISK deterministic detection (กองสูงโดดเดี่ยว
# ไม่มีตัวประคองข้าง) - ใช้ height-profile เดียวกับ STEP_DOWN_RISK แต่ตรวจว่า
# segment หนึ่ง 'สูงกว่าเพื่อนบ้านทั้งสองฝั่ง' พร้อมกัน (ไม่ใช่แค่ฝั่งเดียวแบบ step-down)
# และต้องแคบพอ (ไม่เกิน MAX_TALL_UNSTABLE_WIDTH_RATIO ของความกว้างทั้งหมด) ถึงจะ
# ถือว่าเป็นกองโดดเดี่ยว ไม่ใช่แนวสินค้าสูงยาวปกติ
MIN_TALL_UNSTABLE_RATIO = 0.30
MAX_TALL_UNSTABLE_WIDTH_RATIO = 0.30
TALL_UNSTABLE_CLAIM_OVERLAP_THRESHOLD = 0.10

# v20: เกณฑ์สำหรับ OVERHANG_RISK deterministic detection - แบ่งพื้นที่สินค้าตาม
# แนวตั้งเป็นแถบ (band) แล้ววัดว่าขอบเขตซ้าย/ขวาของแถบบนยื่นล้ำออกไปเกินขอบเขตของ
# แถบล่าง (ชั้นรองรับ) เกินสัดส่วนความกว้างตู้เท่าใด ถึงจะถือว่าเป็นการยื่นล้ำจริง
#
# v20 IMPORTANT FIX (พบจากการทดสอบจริงกับไฟล์ EE06-01,04): เวอร์ชันแรกของ
# _detect_overhang_regions เปรียบเทียบ x_min/x_max ของแถบที่ติดกันตรงๆ โดยไม่ได้
# คำนึงถึง 'เส้นทแยงหลังคาตู้' (isometric roofline) ของภาพ isometric ที่ทำให้ขอบเขต
# ซ้าย-ขวาของสินค้าค่อยๆ เปลี่ยนแปลงอย่างต่อเนื่องและราบเรียบไปหลายแถบติดกัน (5-8
# แถบ) ตามธรรมชาติของมุมมอง 3D - ไม่ใช่การยื่นล้ำจริง (เหมือนบั๊ก REAR_LATERAL_
# IMBALANCE เดิมที่สับสนรอยต่อภาพ isometric กับความเสี่ยงจริง) ส่วนการยื่นล้ำจริง
# ระหว่างชั้นสินค้าจะปรากฏเป็น 'จุดกระโดดเดี่ยว' (isolated spike) ในช่วงสั้นๆ
# (1-2 แถบ) ไม่ใช่แนวโน้มต่อเนื่องยาว - จึงเพิ่ม OVERHANG_MAX_TAPER_RUN_BANDS เป็น
# เกณฑ์แยกแยะ 'จุดกระโดดเดี่ยวจริง' ออกจาก 'ความลาดเอียงต่อเนื่องจากมุมมอง 3D'
OVERHANG_BAND_STEP_PX = 25
# v20 FIX (หลังทดสอบกับไฟล์จริง EE06-01,04): เดิมตั้ง 0.08 (8%) ต่ำเกินไป ทำให้ตรวจ
# พบ false positive จากรอยต่อธรรมชาติของภาพ isometric (จุดยอด/จุดหักมุมของทรง
# ข้าวหลามตัดที่เกิดจากมุมมอง 3D) ซึ่งวัดได้สูงสุดถึง 29.3% ในไฟล์ทดสอบจริงที่โหลด
# เต็มตู้ปลอดภัย 100% - ปรับเป็น 0.32 (32%) เพื่อให้อยู่เหนือ noise floor ที่วัดได้
# จริงทุกจุด (สูงสุด 29.3%) พร้อม margin ปลอดภัย
MIN_OVERHANG_RATIO = 0.32
OVERHANG_CLAIM_OVERLAP_THRESHOLD = 0.10
OVERHANG_MAX_TAPER_RUN_BANDS = 2
# v20 NEW: จำนวนแถบที่ตัดทิ้งจากขอบบน-ล่างสุดของช่วงที่สแกน (ไม่นำมาพิจารณา) เพราะ
# เป็นจุดยอด/จุดหักมุมตามธรรมชาติของทรงข้าวหลามตัดในภาพ isometric (ไม่ใช่รอยต่อ
# ระหว่างชั้นสินค้าจริง) - พบจากการทดสอบจริงว่า false positive มักอยู่ที่ขอบเหล่านี้
OVERHANG_EDGE_EXCLUSION_BANDS = 2

# v20: เกณฑ์ GATE สำหรับ LATERAL_GAP_RISK ที่ Gemini claim มาจากการวิเคราะห์ภาพรวม
# (แยกจาก FORCE mechanism เดิมที่มีอยู่แล้ว) - ใช้ค่าเดียวกับที่ใช้ FORCE
# (MIN_LATERAL_GAP_MM / FALLBACK_MIN_LATERAL_GAP_RATIO) เป็นเกณฑ์ยอมรับ claim ด้วย


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
    v20.1 FIX: แก้บั๊กร้ายแรงที่พบจากไฟล์ AB01-01.pdf จริง - เดิมฟังก์ชันนี้ค้นหา
    ตัวเลขที่ตามด้วย "(mm)" ในข้อความทั้งหน้าแบบไม่แยกแยะบริบท ทำให้ในไฟล์จริงที่
    ตัวเลขขนาดตู้ (เช่น "7200 (mm)") ถูกวาดเป็น vector graphics ในภาพ diagram (ไม่ใช่
    text layer ที่ get_text() ดึงได้เลย) กลับไปจับค่าจากบรรทัด
    "COG : 4261 x 966 x 1425 (mm)" แทน (ซึ่งเป็นพิกัดจุดศูนย์ถ่วง ไม่ใช่ขนาดตู้เลย)
    ทำให้ได้ค่า 1425mm ผิดพลาด (ควรจะเป็น 7200mm) - คลาดเคลื่อนประมาณ 5 เท่า ทำให้
    ทุกระยะทางที่คำนวณเป็น "มิลลิเมตรจริง" เล็กกว่าความเป็นจริงถึง 5 เท่า และไม่มีทาง
    ผ่านเกณฑ์ threshold ใดๆ ได้เลย (สาเหตุที่แท้จริงที่ AB01 ไม่พบจุดเสี่ยงใน v19)

    วิธีแก้: ประมวลผลทีละบรรทัด (ไม่ใช่ full-text regex) แล้ว "ข้ามบรรทัดที่มีคำว่า
    COG โดยเด็ดขาด" เพราะรูปแบบ "N x N x N (mm)" ของ COG ไม่ใช่ค่าความยาวตู้เดี่ยวๆ
    แบบ "N (mm)" ที่ label เส้นบอกขนาดในภาพ diagram ใช้
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        all_values = []
        for page_idx in range(len(doc)):
            page = doc[page_idx]
            full_text = page.get_text("text")
            for line in full_text.splitlines():
                if "cog" in line.lower():
                    # ข้ามบรรทัด COG (Center of Gravity) โดยเด็ดขาด - รูปแบบ
                    # "N x N x N (mm)" ของ COG ไม่ใช่ความยาวตู้เดี่ยวๆ
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


def _measure_rear_lateral_height_diff_ratio(rear_crop_img, step=STEP_DOWN_PROFILE_STEP_PX,
                                             min_consistent_run=STEP_DOWN_MIN_CONSISTENT_RUN):
    """
    v20 NEW: วัดความสูงจริง (พิกเซล) ของกองสินค้าฝั่งซ้ายเทียบกับฝั่งขวาของภาพ
    zoom บริเวณประตูท้ายตู้ (rear_crop) แบบ deterministic เพื่อใช้เป็น GATE
    ตรวจสอบ claim REAR_LATERAL_IMBALANCE ของ Gemini - ถ้าความต่างของความสูงจริง
    ที่วัดได้ไม่ถึงเกณฑ์ ให้ถือว่า Gemini หลอน (hallucinate) และปฏิเสธ claim นั้น
    (เช่นกรณีรอยต่อของภาพ isometric ที่ทำให้ดูเหมือนมีขั้นบันไดทั้งที่จริงแล้ว
    สินค้าสูงเท่ากันทั้งสองฝั่ง)

    คืนค่า ratio = |height_left - height_right| / max(height_left, height_right)
    หรือ None ถ้าวัดไม่ได้ (เช่น หา profile ไม่เจอฝั่งใดฝั่งหนึ่งเลย)
    """
    if rear_crop_img is None:
        return None
    w, h = rear_crop_img.size
    if w < 10 or h < 10:
        return None
    mid_x = w // 2
    left_profile = _detect_height_profile(rear_crop_img, 0, mid_x, 0, h, step, min_consistent_run)
    right_profile = _detect_height_profile(rear_crop_img, mid_x, w, 0, h, step, min_consistent_run)
    if not left_profile or not right_profile:
        return None
    # top_y ยิ่งน้อย = กองยิ่งสูง ใช้ค่า top_y ที่ต่ำสุด (สูงสุด) ของแต่ละฝั่งเป็นตัวแทน
    left_top = min(y for _, y in left_profile)
    right_top = min(y for _, y in right_profile)
    left_height = h - left_top
    right_height = h - right_top
    if left_height <= 0 or right_height <= 0:
        return None
    taller = max(left_height, right_height)
    diff = abs(left_height - right_height)
    return diff / taller if taller > 0 else None


def _passes_lateral_imbalance_gate(view_label, rear_crop_img,
                                    min_ratio=MIN_REAR_LATERAL_IMBALANCE_RATIO):
    """
    v20 NEW: GATE ที่ขาดหายไปสำหรับ REAR_LATERAL_IMBALANCE (สมมาตรกับ
    _passes_deterministic_gate ของ REAR_EMPTY_RISK/FRONT_EMPTY_RISK และ
    _step_down_claim_overlaps_detection ของ STEP_DOWN_RISK) - ปฏิเสธ claim ของ
    Gemini ทันทีถ้าวัดพิกเซลจริงแล้วไม่พบความต่างของความสูงซ้าย-ขวาเกินเกณฑ์
    """
    ratio = _measure_rear_lateral_height_diff_ratio(rear_crop_img)
    if ratio is None:
        print(f"REAR_LATERAL_IMBALANCE gate ({view_label}): could not measure height profile for "
              f"either side - passing through (no pixel evidence available to reject)")
        return True
    if ratio < min_ratio:
        print(f"REAR_LATERAL_IMBALANCE claim REJECTED ({view_label}) - measured left/right height "
              f"diff ratio={ratio:.3f} < threshold {min_ratio} (both sides appear the same height "
              f"based on pixel measurement; Gemini claim treated as hallucination, likely triggered "
              f"by an isometric-drawing seam artifact rather than a real height difference)")
        return False
    print(f"REAR_LATERAL_IMBALANCE claim ACCEPTED ({view_label}) - measured left/right height "
          f"diff ratio={ratio:.3f} >= threshold {min_ratio}")
    return True


def _detect_step_down_regions(view_img, x_start, x_end, y_start, y_end, container_ymax, container_y_span_px,
                               step=STEP_DOWN_PROFILE_STEP_PX, min_ratio=MIN_STEP_DOWN_RATIO,
                               min_flat_width_px=STEP_DOWN_MIN_FLAT_WIDTH_PX):
    """
    v19 FIX: ตรวจจับความต่างระดับด้วยการหา 'จุดกระโดด' ระหว่างจุดที่ติดกันบน
    height-profile แล้วตรวจสอบแต่ละ segment ว่า 'เตี้ยกว่าเพื่อนบ้านซ้าย/ขวา' หรือไม่
    แยกกันเป็นอิสระ (ไม่ใช่เปรียบเทียบทีละคู่แล้ว merge ตามระยะห่าง แบบ v18 เดิมที่มี
    บั๊กเมื่อเจอ pattern บันได 'เตี้ย->กลาง->สูง' ทำให้ 2 จุดเสี่ยงจริงถูกรวมเป็นกรอบ
    เดียวผิดๆ) - segment ใดเตี้ยกว่าเพื่อนบ้านฝั่งใดฝั่งหนึ่งเกินเกณฑ์ จะกลายเป็นจุด
    เสี่ยงแยกของตัวเองทันที
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
    """ตรวจจับ STEP_DOWN_RISK แบบ deterministic แยกต่อ view - Returns dict
    {"FRONT": [...], "BACK": [...]} พิกัดใน 'ภาพเต็ม' (absolute)"""
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
    """คำนวณ intersection-over-area ของ box_a (ไม่ใช่ IoU มาตรฐาน แต่เป็นสัดส่วน
    พื้นที่ทับซ้อนเทียบกับพื้นที่ของ box_a เอง - ใช้ตรวจว่า claim ของ AI ตกอยู่ในขอบเขต
    ของ region ที่ deterministic ตรวจพบมากน้อยแค่ไหน)"""
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
    """
    v19 NEW: ตรวจสอบว่า STEP_DOWN_RISK ที่ Gemini อ้างมา (box_2d) ทับซ้อนกับจุดที่
    deterministic height-profile ตรวจพบจริงหรือไม่ - ถ้า regions_for_view ว่างเปล่า
    (deterministic ไม่พบความต่างระดับใดๆ เลยสำหรับ view นี้) ให้ปฏิเสธ claim ทันที
    เพราะถือว่าไม่มีหลักฐานทางพิกเซลสนับสนุนเลย (นี่คือ GATE ที่ขาดหายไปใน v18)
    """
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
        return True  # คำนวณพิกัดไม่ได้ - ปล่อยผ่านโดยไม่ block (ไม่มีเหตุผลจะปฏิเสธ)

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
# v20 NEW: TALL_UNSTABLE_RISK deterministic detection - isolated tall peak
# ---------------------------------------------------------------------------

def _detect_tall_unstable_regions(view_img, x_start, x_end, y_start, y_end, container_ymax, container_y_span_px,
                                   step=STEP_DOWN_PROFILE_STEP_PX, min_ratio=MIN_TALL_UNSTABLE_RATIO,
                                   min_flat_width_px=STEP_DOWN_MIN_FLAT_WIDTH_PX,
                                   max_width_ratio=MAX_TALL_UNSTABLE_WIDTH_RATIO):
    """
    v20 NEW: ตรวจจับ 'กองสูงโดดเดี่ยวไม่มีตัวประคองข้าง' แบบ deterministic โดยใช้
    height-profile เดียวกับ STEP_DOWN_RISK แต่เกณฑ์ต่างกัน: STEP_DOWN_RISK มองหา
    segment ที่เตี้ยกว่าเพื่อนบ้านฝั่งใดฝั่งหนึ่ง ส่วน TALL_UNSTABLE_RISK มองหา segment
    ที่ 'สูงกว่าเพื่อนบ้านทั้งสองฝั่งพร้อมกัน' (เป็นยอดโดดเดี่ยวจริง ไม่ใช่ขั้นบันได)
    และต้องแคบพอ (ไม่เกิน max_width_ratio ของความกว้างทั้งหมด) มิฉะนั้นจะเป็นแนว
    สินค้าสูงยาวปกติซึ่งไม่ถือว่าเสี่ยง
    """
    profile = _detect_height_profile(view_img, x_start, x_end, y_start, y_end, step)
    if len(profile) < 6:
        return []
    total_width = max(1, x_end - x_start)
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
    for i in range(1, n - 1):
        seg = seg_info[i]
        if seg["width"] < min_flat_width_px or seg["width"] > total_width * max_width_ratio:
            continue
        left, right = seg_info[i - 1], seg_info[i + 1]
        left_diff = left["y_avg"] - seg["y_avg"]
        right_diff = right["y_avg"] - seg["y_avg"]
        left_ratio = left_diff / container_y_span_px if container_y_span_px > 0 else 0
        right_ratio = right_diff / container_y_span_px if container_y_span_px > 0 else 0
        if left_ratio >= min_ratio and right_ratio >= min_ratio:
            risky_segments.append({
                "x_min": seg["x_min"], "x_max": seg["x_max"],
                "y_min": seg["y_avg"], "y_max": container_ymax,
                "ratio": min(left_ratio, right_ratio),
            })

    risky_segments.sort(key=lambda r: r["x_min"])
    return risky_segments


def detect_tall_unstable_regions_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start, container_bounds, cargo_extent):
    """ตรวจจับ TALL_UNSTABLE_RISK แบบ deterministic แยกต่อ view - Returns dict
    {"FRONT": [...], "BACK": [...]} พิกัดใน 'ภาพเต็ม' (absolute), รูปแบบเดียวกับ
    detect_step_down_regions_per_view"""
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
            regions = _detect_tall_unstable_regions(view_img, ce_rel_xmin, ce_rel_xmax, cb_rel_ymin, cb_rel_ymax,
                                                      cb_rel_ymax, container_y_span_px)
        except Exception as e:
            print(f"WARNING: Tall-unstable detection failed for {view} ({e})")
            regions = []

        for r in regions:
            abs_region = {
                "x_min": origin_x + r["x_min"], "x_max": origin_x + r["x_max"],
                "y_min": origin_y + r["y_min"], "y_max": origin_y + r["y_max"],
                "ratio": r["ratio"],
            }
            print(f"Deterministic TALL_UNSTABLE_RISK candidate ({view}): "
                  f"x=[{abs_region['x_min']:.0f}-{abs_region['x_max']:.0f}] "
                  f"y=[{abs_region['y_min']:.0f}-{abs_region['y_max']:.0f}] "
                  f"isolation_ratio={abs_region['ratio']*100:.1f}% (threshold={MIN_TALL_UNSTABLE_RATIO*100:.1f}%)")
            results[view].append(abs_region)
        if not regions:
            print(f"Deterministic TALL_UNSTABLE_RISK: no isolated tall peak found for {view}")
    return results


# ---------------------------------------------------------------------------
# v20 NEW: OVERHANG_RISK deterministic detection - upper tier extends past
# the support tier below it
# ---------------------------------------------------------------------------

def _detect_overhang_regions(view_img, x_start, x_end, y_start, y_end,
                              band_step=OVERHANG_BAND_STEP_PX, min_overhang_ratio=MIN_OVERHANG_RATIO,
                              max_taper_run=OVERHANG_MAX_TAPER_RUN_BANDS,
                              edge_exclusion=OVERHANG_EDGE_EXCLUSION_BANDS):
    """
    v20 NEW (FIXED after real-file testing): แบ่งพื้นที่สินค้าตามแนวตั้งเป็นแถบ
    (bands) จากบนลงล่าง แล้ววัดขอบเขตซ้าย-ขวาของสินค้าในแต่ละแถบ - หากแถบบนยื่นล้ำ
    ออกไปเกินขอบเขตของแถบล่างเกิน min_overhang_ratio ถือว่าเป็นผู้สมัคร (candidate)

    สำคัญ: ต้องแยกแยะ 'จุดกระโดดเดี่ยวจริง' (ชั้นสินค้าจริงยื่นล้ำ) ออกจาก 'ความลาด
    เอียงต่อเนื่องจากเส้นทแยงหลังคาตู้ในภาพ isometric' (perspective taper) ซึ่งจะ
    ปรากฏเป็นการเปลี่ยนแปลงทิศทางเดียวกันต่อเนื่องหลายแถบติดกัน (5-8 แถบขึ้นไป) -
    วิธีแก้คือจัดกลุ่ม (run-length) แถบที่มี overhang ทิศทางเดียวกันติดกัน แล้วยอมรับ
    เฉพาะ run ที่สั้น (<= max_taper_run แถบ) เท่านั้นว่าเป็นจุดกระโดดเดี่ยวจริง - ถ้า
    เป็น run ยาวต่อเนื่อง ให้ถือว่าเป็น isometric roofline taper ตามธรรมชาติ ไม่ใช่
    ความเสี่ยง (พบบั๊กนี้จากการทดสอบจริงกับไฟล์ EE06-01,04 ที่โหลดเต็มตู้ปลอดภัย
    100% แต่เวอร์ชันแรกกลับ flag เป็น OVERHANG_RISK ผิดพลาดหลายจุด)
    """
    px = view_img.convert("RGB").load()
    w, h = view_img.size
    x_start = max(0, int(x_start)); x_end = min(w, int(x_end))
    y_start = max(0, int(y_start)); y_end = min(h, int(y_end))
    if x_end <= x_start or y_end <= y_start:
        return []
    total_width = max(1, x_end - x_start)
    band_h = max(6, int(band_step))

    bands = []
    y = y_start
    while y < y_end:
        y2 = min(y + band_h, y_end)
        y_mid = (y + y2) // 2
        xs_with_cargo = [x for x in range(x_start, x_end) if _is_vivid_cargo_color(px[x, y_mid])]
        if xs_with_cargo:
            bands.append({"y_min": y, "y_max": y2, "x_min": min(xs_with_cargo), "x_max": max(xs_with_cargo)})
        y = y2
    # v20 NEW: ตัดแถบขอบบน-ล่างสุดทิ้ง (จุดยอด/จุดหักมุมตามธรรมชาติของทรงข้าวหลามตัด
    # ในภาพ isometric - พิสูจน์แล้วจากการทดสอบจริงว่าเป็นจุดที่มักเกิด false positive)
    if edge_exclusion > 0 and len(bands) > edge_exclusion * 2 + 2:
        bands = bands[edge_exclusion:-edge_exclusion]

    if len(bands) < 2 * max_taper_run + 2:
        return []

    # คำนวณ per-boundary overhang ทั้งด้านซ้ายและขวาแยกกัน พร้อมทิศทาง (sign)
    boundary_info = []
    for i in range(len(bands) - 1):
        upper, lower = bands[i], bands[i + 1]
        left_overhang = lower["x_min"] - upper["x_min"]     # บวก = แถบบนยื่นล้ำซ้าย
        right_overhang = upper["x_max"] - lower["x_max"]    # บวก = แถบบนยื่นล้ำขวา
        boundary_info.append({
            "i": i, "left": left_overhang, "right": right_overhang,
            "upper": upper, "lower": lower,
        })

    def _find_isolated_spikes(values, sign_fn):
        """หา run สั้นๆ (<=max_taper_run) ของ boundary ที่มีค่า overhang ทิศทางเดียวกัน
        เกินเกณฑ์ติดต่อกัน - ปฏิเสธ run ที่ยาวกว่านั้น (ถือเป็น perspective taper)"""
        threshold_px = total_width * min_overhang_ratio
        n = len(values)
        i = 0
        spikes = []
        while i < n:
            v = values[i]
            if abs(v) >= threshold_px:
                sign = 1 if v > 0 else -1
                j = i
                while j < n and abs(values[j]) >= threshold_px * 0.5 and sign_fn(values[j]) == sign:
                    j += 1
                run_len = j - i
                if run_len <= max_taper_run:
                    # run สั้น = จุดกระโดดเดี่ยวจริง - เลือก boundary ที่มี |overhang| มากที่สุดในกลุ่มนี้
                    best_idx = max(range(i, j), key=lambda k: abs(values[k]))
                    spikes.append(best_idx)
                i = j if j > i else i + 1
            else:
                i += 1
        return spikes

    def _sign(v):
        return 1 if v > 0 else -1

    left_spikes = _find_isolated_spikes([b["left"] for b in boundary_info], _sign)
    right_spikes = _find_isolated_spikes([b["right"] for b in boundary_info], _sign)

    risky = []
    seen_boundaries = set()
    for idx in sorted(set(left_spikes) | set(right_spikes)):
        if idx in seen_boundaries:
            continue
        seen_boundaries.add(idx)
        b = boundary_info[idx]
        overhang_px = max(abs(b["left"]), abs(b["right"]))
        ratio = overhang_px / total_width if total_width > 0 else 0
        upper, lower = b["upper"], b["lower"]
        x0 = min(upper["x_min"], lower["x_min"])
        x1 = max(upper["x_max"], lower["x_max"])
        risky.append({"x_min": x0, "x_max": x1, "y_min": upper["y_min"], "y_max": lower["y_max"], "ratio": ratio})

    risky.sort(key=lambda r: r["y_min"])
    return risky


def detect_overhang_regions_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start, container_bounds, cargo_extent):
    """ตรวจจับ OVERHANG_RISK แบบ deterministic แยกต่อ view - Returns dict
    {"FRONT": [...], "BACK": [...]} พิกัดใน 'ภาพเต็ม' (absolute), รูปแบบเดียวกับ
    detect_step_down_regions_per_view"""
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

        try:
            regions = _detect_overhang_regions(view_img, ce_rel_xmin, ce_rel_xmax, cb_rel_ymin, cb_rel_ymax)
        except Exception as e:
            print(f"WARNING: Overhang detection failed for {view} ({e})")
            regions = []

        for r in regions:
            abs_region = {
                "x_min": origin_x + r["x_min"], "x_max": origin_x + r["x_max"],
                "y_min": origin_y + r["y_min"], "y_max": origin_y + r["y_max"],
                "ratio": r["ratio"],
            }
            print(f"Deterministic OVERHANG_RISK candidate ({view}): "
                  f"x=[{abs_region['x_min']:.0f}-{abs_region['x_max']:.0f}] "
                  f"y=[{abs_region['y_min']:.0f}-{abs_region['y_max']:.0f}] "
                  f"overhang_ratio={abs_region['ratio']*100:.1f}% (threshold={MIN_OVERHANG_RATIO*100:.1f}%)")
            results[view].append(abs_region)
        if not regions:
            print(f"Deterministic OVERHANG_RISK: no tier overhang found for {view}")
    return results


def _region_claim_overlaps_detection(box_2d, crop_w, crop_h, crop_y_start, regions_for_view,
                                      overlap_threshold, risk_name):
    """
    v20 NEW: เวอร์ชัน generic ของ _step_down_claim_overlaps_detection ใช้ร่วมกันได้
    กับทุก risk type ที่ต้องการ GATE แบบ 'ตรวจสอบ overlap กับ region ที่ deterministic
    ตรวจพบจริง' (ตอนนี้ใช้กับ TALL_UNSTABLE_RISK และ OVERHANG_RISK)
    """
    if not regions_for_view:
        print(f"{risk_name} claim REJECTED - no deterministic evidence detected for this view at all "
              f"(measured pixel profile shows nothing matching this risk pattern)")
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
        return True  # คำนวณพิกัดไม่ได้ - ปล่อยผ่านโดยไม่ block (ไม่มีเหตุผลจะปฏิเสธ)

    claim_box = (abs_xmin, abs_ymin, abs_xmax, abs_ymax)
    for region in regions_for_view:
        region_box = (region["x_min"], region["y_min"], region["x_max"], region["y_max"])
        overlap = _box_iou_absolute(claim_box, region_box)
        if overlap >= overlap_threshold:
            print(f"{risk_name} claim ACCEPTED - overlaps with detected region (overlap={overlap:.2f})")
            return True
    print(f"{risk_name} claim REJECTED - box_2d does not overlap with any detected region "
          f"(claim_box={claim_box}, available_regions={len(regions_for_view)})")
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
    prompt = f"""
You are a Cargo Safety Inspector. This image is a cropped zoom of the DOOR END (REAR) zone of a container.
This is the {view_label} view.
YOUR TASK: Determine if there is a genuine safety risk at the door end.

RULES (numeric thresholds - apply consistently, do not be overly cautious):
1. REAR_EMPTY_RISK: Flag if there is empty floor space near the door of more than roughly 20% of
   the container height, OR cargo drops off sharply leaving a dangerous unsupported edge.
2. REAR_LATERAL_IMBALANCE: Flag if cargo height on the left vs right side at the door zone differs
   by MORE than approximately 40-50% of the taller stack's height (a clear, visible step, not just
   minor natural variation from box packing). This is a real, measurable visual difference - if you
   can clearly see one side is noticeably shorter than the other by roughly half a box or more,
   you SHOULD flag it. Do not dismiss a clearly visible height difference just to be cautious.
3. The container wall/floor/frame structure itself is NOT cargo - never flag it.
4. If cargo reasonably fills the rear area and both sides are close in height (within ~1 small tier) -> SAFE.

IMPORTANT - if you flag a risk, you MUST also provide "box_2d" pinpointing EXACTLY where the
problem is visible in THIS image (the specific stack, or the boundary between the two stacks with
different heights). Use [ymin, xmin, ymax, xmax] format with values 0-1000 normalized to this
image's own size. The box must tightly enclose the actual shorter stack (or the height-mismatch
boundary) - not the whole image, not empty background.

Return ONLY this exact JSON:
{{"rear_zone_risk":"REAR_EMPTY_RISK"|"REAR_LATERAL_IMBALANCE"|"BOTH"|"SAFE","reasoning":"describe what you see, including approximate height difference if any","confidence":"HIGH"|"MEDIUM"|"LOW","box_2d":[ymin,xmin,ymax,xmax]}}
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

        # v19: คำนวณ step_down_regions ตั้งแต่ต้น (ก่อนเรียก Gemini วิเคราะห์ภาพรวม)
        # เพื่อใช้เป็น GATE ตรวจสอบ claim ของ Gemini ทันทีที่ได้ผลลัพธ์กลับมา
        step_down_regions = detect_step_down_regions_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start,
                                                                container_bounds, cargo_extent)

        # v20: เพิ่ม deterministic detection ตั้งแต่ต้นให้ครบทุก risk type ที่เหลือซึ่ง
        # ก่อนหน้านี้พึ่งพา Gemini ล้วนๆ โดยไม่มี GATE เลย (TALL_UNSTABLE_RISK,
        # OVERHANG_RISK) - ให้สมมาตรกับ STEP_DOWN_RISK ที่มี GATE อยู่แล้ว
        tall_unstable_regions = detect_tall_unstable_regions_per_view(diagram_crop, layout, crop_w, crop_h,
                                                                        crop_y_start, container_bounds, cargo_extent)
        overhang_regions = detect_overhang_regions_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start,
                                                              container_bounds, cargo_extent)

        # v20: คำนวณ lateral gap (ใช้กับ LATERAL_GAP_RISK) ตั้งแต่ต้นด้วยเช่นกัน เพื่อ
        # นำไปใช้เป็น GATE สำหรับ claim ของ Gemini (ก่อนหน้านี้ค่านี้ถูกคำนวณช้าเกินไป -
        # ใช้เป็น FORCE เท่านั้น ไม่เคยถูกใช้ GATE claim จาก Gemini เลย) ค่าที่คำนวณนี้จะ
        # ถูกใช้ซ้ำสำหรับ FORCE mechanism ด้านล่างด้วย (single source of truth)
        lateral_gap_should_flag = {}
        lateral_gap_display = {}
        for _vl in ("FRONT", "BACK"):
            _mm = compute_lateral_gap_mm(container_bounds.get(_vl), cargo_extent.get(_vl), container_length_mm)
            _ratio = compute_lateral_gap_ratio(container_bounds.get(_vl), cargo_extent.get(_vl))
            if _mm is not None:
                print(f"Deterministic lateral gap for LATERAL_GAP_RISK ({_vl}): {_mm:.0f}mm (threshold={MIN_LATERAL_GAP_MM}mm)")
                lateral_gap_should_flag[_vl] = _mm >= MIN_LATERAL_GAP_MM
                lateral_gap_display[_vl] = f"{_mm/10:.0f} ซม."
            elif _ratio is not None:
                print(f"Deterministic lateral gap for LATERAL_GAP_RISK ({_vl}): {_ratio*100:.1f}% "
                      f"(mm calibration unavailable, using ratio fallback, threshold={FALLBACK_MIN_LATERAL_GAP_RATIO*100:.0f}%)")
                lateral_gap_should_flag[_vl] = _ratio >= FALLBACK_MIN_LATERAL_GAP_RATIO
                lateral_gap_display[_vl] = f"{_ratio*100:.0f}% ของความสูงโครงสร้างตู้"
            else:
                print(f"WARNING: Could not compute lateral gap for {_vl} (missing container_bounds or cargo_extent)")
                lateral_gap_should_flag[_vl] = False
                lateral_gap_display[_vl] = ""

        raw_ai_risks = analyze_diagram_image_with_ai(diagram_crop, layout=layout)
        if not isinstance(raw_ai_risks, list):
            raw_ai_risks = []

        # v19/v20: กรองทุก risk type ที่ Gemini claim มา ผ่าน deterministic GATE ก่อน
        # นำเข้า all_risks - ถ้าตำแหน่ง/หลักฐานที่อ้างไม่ตรงกับสิ่งที่ deterministic
        # ตรวจพบจริง (หรือไม่พบหลักฐานใดๆ เลยสำหรับ view นั้น) จะถูกปฏิเสธทันที ไม่ว่า
        # Gemini จะมั่นใจแค่ไหนก็ตาม - ตอนนี้ครบทุก risk type แล้ว (REAR_EMPTY_RISK/
        # FRONT_EMPTY_RISK/REAR_LATERAL_IMBALANCE มี GATE แยกอยู่ในขั้นตอนถัดไปด้วย)
        all_risks = []
        for r in raw_ai_risks:
            rt = str(r.get("risk_type", "")).upper().strip()
            if rt == "STEP_DOWN_RISK":
                view_of_claim = str(r.get("view", "")).upper().strip()
                box_2d = r.get("box_2d")
                if view_of_claim in ("FRONT", "BACK") and box_2d and isinstance(box_2d, list) and len(box_2d) == 4:
                    regions_for_view = step_down_regions.get(view_of_claim, [])
                    if _step_down_claim_overlaps_detection(box_2d, crop_w, crop_h, crop_y_start, regions_for_view):
                        all_risks.append(r)
                    else:
                        print(f"Gemini STEP_DOWN_RISK claim for {view_of_claim} view REJECTED by deterministic gate "
                              f"(description: {r.get('description', '')[:100]})")
                else:
                    # ไม่มี view/box_2d ชัดเจนพอจะตรวจสอบได้ - ปฏิเสธเพื่อความปลอดภัย
                    # (ป้องกัน hallucination ที่ไม่มีพิกัดชัดเจนให้ตรวจสอบ)
                    print(f"Gemini STEP_DOWN_RISK claim REJECTED - missing valid view/box_2d for verification")
            elif rt == "TALL_UNSTABLE_RISK":
                view_of_claim = str(r.get("view", "")).upper().strip()
                box_2d = r.get("box_2d")
                if view_of_claim in ("FRONT", "BACK") and box_2d and isinstance(box_2d, list) and len(box_2d) == 4:
                    regions_for_view = tall_unstable_regions.get(view_of_claim, [])
                    if _region_claim_overlaps_detection(box_2d, crop_w, crop_h, crop_y_start, regions_for_view,
                                                         TALL_UNSTABLE_CLAIM_OVERLAP_THRESHOLD, "TALL_UNSTABLE_RISK"):
                        all_risks.append(r)
                    else:
                        print(f"Gemini TALL_UNSTABLE_RISK claim for {view_of_claim} view REJECTED by deterministic gate "
                              f"(description: {r.get('description', '')[:100]})")
                else:
                    print(f"Gemini TALL_UNSTABLE_RISK claim REJECTED - missing valid view/box_2d for verification")
            elif rt == "OVERHANG_RISK":
                view_of_claim = str(r.get("view", "")).upper().strip()
                box_2d = r.get("box_2d")
                if view_of_claim in ("FRONT", "BACK") and box_2d and isinstance(box_2d, list) and len(box_2d) == 4:
                    regions_for_view = overhang_regions.get(view_of_claim, [])
                    if _region_claim_overlaps_detection(box_2d, crop_w, crop_h, crop_y_start, regions_for_view,
                                                         OVERHANG_CLAIM_OVERLAP_THRESHOLD, "OVERHANG_RISK"):
                        all_risks.append(r)
                    else:
                        print(f"Gemini OVERHANG_RISK claim for {view_of_claim} view REJECTED by deterministic gate "
                              f"(description: {r.get('description', '')[:100]})")
                else:
                    print(f"Gemini OVERHANG_RISK claim REJECTED - missing valid view/box_2d for verification")
            elif rt == "LATERAL_GAP_RISK":
                view_of_claim = str(r.get("view", "")).upper().strip()
                if view_of_claim in ("FRONT", "BACK") and lateral_gap_should_flag.get(view_of_claim, False):
                    all_risks.append(r)
                else:
                    print(f"Gemini LATERAL_GAP_RISK claim for {view_of_claim or 'UNKNOWN'} view REJECTED by "
                          f"deterministic gate - measured side-floor gap does not exceed threshold "
                          f"(description: {r.get('description', '')[:100]})")
            else:
                all_risks.append(r)

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
            if rear_zone_risk in ("REAR_LATERAL_IMBALANCE", "BOTH") and confidence in ("HIGH", "MEDIUM") and view_label not in _existing_risk_views("REAR_LATERAL"):
                rear_crop_for_measure = rear_crop_front if view_label == "FRONT" else rear_crop_back
                if _passes_lateral_imbalance_gate(view_label, rear_crop_for_measure):
                    all_risks.append({"view": view_label, "risk_type": "REAR_LATERAL_IMBALANCE", "direction": "LATERAL", "lateral_side": "N/A", "reasoning": rear_result.get("reasoning", ""), "description": "พบสินค้าท้ายตู้สูงต่ำไม่เท่ากัน (วิเคราะห์จาก Zoom ท้ายตู้)", "box_2d": None})
                else:
                    print(f"Skipping REAR_LATERAL_IMBALANCE ({view_label}) - rejected by deterministic pixel gate")

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

        # v20: ใช้ค่า lateral_gap_should_flag / lateral_gap_display ที่คำนวณไว้ตั้งแต่
        # ต้น (single source of truth เดียวกับที่ใช้ GATE claim ของ Gemini ด้านบน)
        # แทนการคำนวณซ้ำ เพื่อไม่ให้ GATE กับ FORCE ใช้เกณฑ์/ค่าคนละชุดกัน
        for view_label in ("FRONT", "BACK"):
            should_flag_lateral = lateral_gap_should_flag.get(view_label, False)
            gap_display = lateral_gap_display.get(view_label, "")

            if should_flag_lateral and view_label not in _existing_risk_views("LATERAL_GAP"):
                print(f"FORCED LATERAL_GAP_RISK ({view_label}) from deterministic side-floor gap measurement")
                all_risks.append({"view": view_label, "risk_type": "LATERAL_GAP_RISK", "direction": "LATERAL", "lateral_side": "N/A", "reasoning": "FORCED_DETERMINISTIC_LATERAL_GAP", "description": f"พบพื้นที่ว่างด้านข้างบนพื้นตู้ประมาณ {gap_display} (เกินเกณฑ์ความปลอดภัย)", "box_2d": None})

        # FORCE สร้าง STEP_DOWN_RISK เองสำหรับ region ที่ deterministic ตรวจพบ แต่
        # Gemini ไม่ได้ flag มา (dedup: ถ้า all_risks มี STEP_DOWN_RISK ของ view นี้
        # ที่ผ่าน gate มาแล้วและตำแหน่งซ้อนทับกับ region นี้อยู่แล้ว จะไม่เพิ่มซ้ำ)
        for view_label in ("FRONT", "BACK"):
            for region in step_down_regions.get(view_label, []):
                if region["ratio"] < MIN_STEP_DOWN_RATIO:
                    continue
                already_covered = False
                region_box = [region["y_min"], region["x_min"], region["y_max"], region["x_max"]]
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

        # v20: FORCE สร้าง TALL_UNSTABLE_RISK เองสำหรับ region ที่ deterministic
        # ตรวจพบ แต่ Gemini ไม่ได้ flag มา (สมมาตรกับ STEP_DOWN_RISK ด้านบน - dedup
        # ด้วยวิธีเดียวกัน คือเช็ค overlap กับ claim ที่ผ่าน gate มาแล้วของ view เดียวกัน)
        for view_label in ("FRONT", "BACK"):
            for region in tall_unstable_regions.get(view_label, []):
                if region["ratio"] < MIN_TALL_UNSTABLE_RATIO:
                    continue
                already_covered = False
                for r in all_risks:
                    if str(r.get("risk_type", "")).upper().strip() != "TALL_UNSTABLE_RISK":
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
                print(f"FORCED TALL_UNSTABLE_RISK ({view_label}) from deterministic isolated-peak height-profile "
                      f"(isolation_ratio={region['ratio']*100:.1f}%)")
                all_risks.append({
                    "view": view_label, "risk_type": "TALL_UNSTABLE_RISK",
                    "box_2d": [ymin_norm, xmin_norm, ymax_norm, xmax_norm],
                    "reasoning": "FORCED_DETERMINISTIC_ISOLATED_PEAK",
                    "description": f"พบกองสินค้าสูงโดดเดี่ยวไม่มีตัวประคองข้าง สูงกว่าเพื่อนบ้านทั้งสองฝั่งประมาณ {region['ratio']*100:.0f}% ของความสูงตู้ (ตรวจจับจาก height-profile analysis)",
                })

        # v20: FORCE สร้าง OVERHANG_RISK เองสำหรับ region ที่ deterministic ตรวจพบ
        # แต่ Gemini ไม่ได้ flag มา (สมมาตรกับ STEP_DOWN_RISK/TALL_UNSTABLE_RISK)
        for view_label in ("FRONT", "BACK"):
            for region in overhang_regions.get(view_label, []):
                if region["ratio"] < MIN_OVERHANG_RATIO:
                    continue
                already_covered = False
                for r in all_risks:
                    if str(r.get("risk_type", "")).upper().strip() != "OVERHANG_RISK":
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
                print(f"FORCED OVERHANG_RISK ({view_label}) from deterministic tier-boundary measurement "
                      f"(overhang_ratio={region['ratio']*100:.1f}%)")
                all_risks.append({
                    "view": view_label, "risk_type": "OVERHANG_RISK",
                    "box_2d": [ymin_norm, xmin_norm, ymax_norm, xmax_norm],
                    "reasoning": "FORCED_DETERMINISTIC_TIER_OVERHANG",
                    "description": f"พบชั้นบนยื่นล้ำออกไปเกินขอบเขตของชั้นรองรับด้านล่างประมาณ {region['ratio']*100:.0f}% ของความกว้างตู้ (ตรวจจับจาก tier-band analysis)",
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
