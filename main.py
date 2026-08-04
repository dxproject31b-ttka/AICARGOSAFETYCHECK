import base64
import io
import json
import os
import time
import gc
import traceback
import random
import PIL.Image
import PIL.ImageDraw
import PIL.ImageStat
import PIL.PngImagePlugin
import fitz  # PyMuPDF สำหรับหาคำว่า "Back"
import functions_framework
import google.generativeai as genai

# ---------------------------------------------------------------------------
# Backend API สำหรับ AI Cargo Safety Checker ( High-Precision v5 )
# ---------------------------------------------------------------------------

GLOBAL_API_KEYS = []
GLOBAL_KEY_INDEX = 0

def get_api_keys_pool():
    global GLOBAL_API_KEYS
    if GLOBAL_API_KEYS:
        return GLOBAL_API_KEYS

    # อ่านค่าจากตัวแปรชื่อนี้ตัวเดียวเท่านั้น
    env_value = os.environ.get('GEMINI_API_KEYS', '')
    
    if env_value:
        # ตัดด้วยคอมมา และกรองค่าว่างออก
        keys = [k.strip() for k in env_value.split("|") if k.strip()]
        
        if keys:
            random.shuffle(keys)
            print(f"✅ Loaded {len(keys)} unique API key(s) into the pool.")
            GLOBAL_API_KEYS = keys
            return GLOBAL_API_KEYS

    print("❌ No Gemini API keys found.")
    return []

def generate_action_report(case_type, description):
    actions = {
        "STEP_DOWN_RISK": f"🚨 [ALERT] พบรอยต่างระดับระหว่างกองสินค้า (Step-Down)\n{description}\n🛠️ ACTION: ติดตั้งแผ่นไม้กั้นขวาง (Void Filler / Dunnage) ระหว่างกอง และรัดตรึงให้ครบทุกจุด",
        "REAR_EMPTY_RISK": f"🚨 [ALERT] พบพื้นที่โล่ง/สินค้าต่างระดับ ฝั่งประตูท้ายตู้ (REAR EMPTY)\n{description}\n🛠️ ACTION: ติดตั้งแผ่นไม้ค้ำแนวดิ่ง (Rear Tomming) + รัดตรึงป้องกันสินค้าไถลออกประตู",
        "REAR_LATERAL_IMBALANCE": f"🚨 [ALERT] พบสินค้าท้ายตู้สูงต่ำไม่เท่ากันในแนวกว้าง (Rear Lateral Imbalance)\n{description}\n🛠️ ACTION: เสริมด้านที่ต่ำกว่าด้วย Void Filler / Dunnage ให้ระดับเท่ากัน + รัดตรึงขวางป้องกันสินค้าล้มตะแคงเมื่อเปิดประตู",
        "FRONT_EMPTY_RISK": f"🚨 [ALERT] พบพื้นที่โล่ง/สินค้าต่างระดับ ฝั่งผนังหัวตู้ (FRONT EMPTY)\n{description}\n🛠️ ACTION: ติดตั้งแผ่นไม้ค้ำฝั่งหัวตู้ (Front Blocking) + รัดตรึงป้องกันสินค้าไถลหน้าเมื่อเบรก",
        "LATERAL_GAP_RISK": f"🚨 [ALERT] พบช่องว่างด้านข้างระหว่างกองสินค้า (Lateral Gap)\n{description}\n🛠️ ACTION: ใส่ Air Bag หรือ Void Filler ด้านข้าง + รัดตรึงป้องกันสินค้าเลื่อนตะแคงขณะเลี้ยว",
        "TALL_UNSTABLE_RISK": f"🚨 [ALERT] พบสินค้าสูงโดดเดี่ยว ไม่มีของข้างค้ำ (Tall / Unstable)\n{description}\n🛠️ ACTION: ค้ำยันด้านข้างกองสูง + รัดตรึงแนวขวาง ป้องกันล้มตะแคง",
        "OVERHANG_RISK": f"🚨 [ALERT] พบสินค้าชั้นบนยื่นพ้นขอบสินค้าชั้นล่าง (Overhang)\n{description}\n🛠️ ACTION: จัดเรียงใหม่ให้ชั้นบนไม่ยื่นพ้นฐาน หรือใส่แผ่นรองรับและรัดตรึง",
    }
    return actions.get(case_type, "🟢 [STATUS] ปลอดภัย (SAFE)\nไม่พบจุดเสี่ยงที่ต้องดำเนินการเพิ่มเติม")

def clean_json_response(text):
    text = text.strip()
    start_list = text.find('[')
    end_list   = text.rfind(']')
    start_dict = text.find('{')
    end_dict   = text.rfind('}')

    if start_list != -1 and end_list != -1:
        if start_dict == -1 or start_list < start_dict:
            return text[start_list:end_list + 1]

    if start_dict != -1 and end_dict != -1:
        return text[start_dict:end_dict + 1]

    return text

def detect_page_layout_from_pdf(pdf_bytes: bytes) -> str:
    """
    ตรวจจับรูปแบบการวางภาพในหน้า manifest:
      LEFT_RIGHT  = ภาพ Front (ซ้าย) และ Back (ขวา) วางเคียงกัน → พบใน PDF แนวนอน (Landscape)
      TOP_BOTTOM  = ภาพ Front (บน)   และ Back (ล่าง) วางซ้อนกัน → พบใน PDF แนวตั้ง (Portrait)

    หลักการ:
      1. ถ้าหน้า PDF เป็น Landscape (กว้าง > สูง) → LEFT_RIGHT เสมอ
         เหตุผล: manifest ที่ export แนวนอนจะวาง 2 view ซ้าย-ขวาเสมอ
                 ตำแหน่ง label "Back" อาจอยู่ซ้ายล่างของภาพขวา (x น้อย)
                 จึงไม่สามารถใช้ x > 40% เป็นเกณฑ์ได้
      2. ถ้า Portrait → ใช้ตำแหน่ง y ของ "Back" เป็น fallback (TOP_BOTTOM)
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_index = 1 if len(doc) >= 2 else 0
        page = doc[page_index]

        page_width  = page.rect.width
        page_height = page.rect.height
        is_landscape = page_width > page_height

        print(f"📄 Page size: {page_width:.0f}x{page_height:.0f} | Landscape={is_landscape}")

        # กฎหลัก: Landscape → LEFT_RIGHT เสมอ
        if is_landscape:
            print("📐 Layout detected: LEFT_RIGHT (Landscape page)")
            return "LEFT_RIGHT"

        # Portrait: ใช้ตำแหน่ง "Back" label เป็น fallback
        text_instances = page.search_for("Back")
        if text_instances:
            rect = text_instances[0]
            x_ratio = rect.x0 / page_width
            y_ratio = rect.y0 / page_height
            print(f"📍 Back label: x_ratio={x_ratio:.2f}, y_ratio={y_ratio:.2f}")

            if x_ratio > 0.40:
                print("📐 Layout detected: LEFT_RIGHT (Back label right half)")
                return "LEFT_RIGHT"

    except Exception as e:
        print(f"⚠️ Layout detection failed ({e}), defaulting to TOP_BOTTOM")

    print("📐 Layout detected: TOP_BOTTOM (default)")
    return "TOP_BOTTOM"

def analyze_rear_zone_with_ai(rear_crop: PIL.Image.Image, api_keys: list, view_label: str = "UNKNOWN") -> dict:
    global GLOBAL_KEY_INDEX 
    rear_prompt = f"""
You are a Cargo Safety Inspector. This image is a cropped zoom of the DOOR END (REAR) zone of a container.
This is the {view_label} view. The red arrows point to the floor at the open door.
YOUR ONLY TASK: Look for physical height drops ("Stair-Steps" or "Cliffs") at the end of the cargo.

CRITICAL RULES:
- Compare only CARGO heights. Do NOT include the container wall (solid yellow/tan panel) in your height comparison. The head wall is a fixed structure, not cargo.
- For REAR_LATERAL_IMBALANCE: only flag if cargo stacks on the LEFT side and RIGHT side of the door opening are visibly different heights. If cargo appears level across the width, it is SAFE.
- Consider total stack height (all tiers combined) when comparing left vs right sides.

Return ONLY this exact JSON format:
{{
  "rear_zone_risk": "REAR_EMPTY_RISK" | "REAR_LATERAL_IMBALANCE" | "BOTH" | "SAFE",
  "reasoning": "Explain the physical height difference you see.",
  "confidence": "HIGH" | "MEDIUM" | "LOW"
}}
"""
    return _call_gemini_json(rear_prompt, rear_crop, api_keys)
                                   
def analyze_front_zone_with_ai(front_crop: PIL.Image.Image, api_keys: list, view_label: str = "UNKNOWN") -> dict:
    global GLOBAL_KEY_INDEX
    front_prompt = f"""
You are a Cargo Safety Inspector. This image is a cropped zoom of the HEAD WALL (FRONT) zone of a container.
This is the {view_label} view. The yellow/tan solid panel is the container's head wall (a fixed structure).
YOUR TASK: Detect if there is a FRONT_EMPTY_RISK in this cropped area.

CRITICAL RULES:
- FRONT_EMPTY_RISK means there is a visible empty gap or significant height difference between the cargo and the head wall — cargo that could slide forward and hit the wall during braking.
- Do NOT flag the head wall itself as a risk. Only flag if cargo is clearly NOT touching or braced against the wall, leaving a dangerous void.
- If cargo fills the space up to the head wall evenly (even if the top surface of cargo is lower than the wall top), it is SAFE — no sliding risk.
- The yellow/tan colored solid panel IS the head wall. Do not mistake it for cargo height imbalance.

Return ONLY this exact JSON object:
{{
  "front_zone_risk": "FRONT_EMPTY_RISK" | "SAFE",
  "reasoning": "Describe exactly what you see near the solid wall.",
  "confidence": "HIGH" | "MEDIUM" | "LOW"
}}
"""
    return _call_gemini_json(front_prompt, front_crop, api_keys)

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
            # 🛑 1. เพิ่มโค้ด 3 บรรทัดนี้ เพื่อบังคับล้างการเชื่อมต่อเก่าทิ้งให้เกลี้ยง
            if hasattr(genai, '_client'): 
                genai._client = None
            if hasattr(genai, 'client') and hasattr(genai.client, '_client'): 
                genai.client._client = None
            
            # 2. ตั้งค่า Key ใหม่ (มันจะบังคับสร้างท่อการเชื่อมต่อใหม่ด้วย Key นี้)
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
            print(f"⚠️ API Key index {current_index} failed: {last_err[:100]}")
            time.sleep(1) # หน่วงเวลา 1 วินาทีก่อนหมุน Key ถัดไป
            continue # หมุนไปใช้ Key ถัดไป
            
    return {"rear_zone_risk": "ERROR", "front_zone_risk": "ERROR", "reasoning": last_err[:120], "confidence": "LOW"}

def analyze_diagram_image_with_ai(diagram_image: PIL.Image.Image):
    global GLOBAL_KEY_INDEX 
    
    api_keys = get_api_keys_pool()
    if not api_keys:
        return [{"risk_type": "ERROR", "description": "No Gemini API Keys found."}]

    prompt = """
You are an expert Cargo Loading Safety Inspector analyzing a 3D cargo load plan.

CRITICAL DEFINITIONS & RULES:
1. STEP_DOWN_RISK: Refers ONLY to significant height drops BETWEEN cargo stacks inside the container.
   - IMPORTANT: When comparing stack heights, always count the TOTAL height of the entire stack including ALL layers/tiers stacked on top of each other. A stack that has cargo on top of another cargo must have its COMBINED height compared to adjacent stacks.
   - If stack A appears shorter at the base but has additional cargo layers on top that bring its total height equal to or close to adjacent stack B, it is NOT a STEP_DOWN_RISK.
   - Only flag STEP_DOWN_RISK when the total combined height of one stack is clearly and significantly lower than an adjacent stack, with no cargo bridging the gap.
2. DO NOT label the height drop at the very end of the cargo near the container doors as STEP_DOWN_RISK. That area must be evaluated for REAR_EMPTY_RISK instead.

YOUR TASK:
Find all safety risks and return them in this exact JSON array format:
[
  {
    "risk_type": "STEP_DOWN_RISK" | "REAR_EMPTY_RISK" | "...",
    "box_2d": [ymin, xmin, ymax, xmax],
    ...
  }
]
(MANDATORY JSON ARRAY RETURN)
"""
    last_error_msg = ""
    for pass_round in range(2):
        for i in range(len(api_keys)):
            current_index = (GLOBAL_KEY_INDEX + i) % len(api_keys)
            current_key = api_keys[current_index]
            try:
                # 🛑 ทำแบบเดียวกันในฟังก์ชันนี้
                if hasattr(genai, '_client'): 
                    genai._client = None
                if hasattr(genai, 'client') and hasattr(genai.client, '_client'): 
                    genai.client._client = None
                
                genai.configure(api_key=current_key)
                model = genai.GenerativeModel(model_name="gemini-3.6-flash")
                response = model.generate_content([prompt, diagram_image])
                clean_text = clean_json_response(response.text if response.text else "[]")
                
                if not clean_text or clean_text in ('""', '[]'):
                    return []
                    
                risks = json.loads(clean_text)
                if isinstance(risks, dict):
                    risks = [risks]
                    
                GLOBAL_KEY_INDEX = current_index
                return risks
            except Exception as e:
                last_error_msg = str(e)
                print(f"⚠️ API Key index {current_index} failed in diagram analysis: {last_error_msg[:100]}")
                time.sleep(1)
                continue 
                
        if pass_round == 0:
            time.sleep(2)
            
    return [{"risk_type": "ERROR", "description": f"AI Error: {last_error_msg[:120]}"}]

def _get_fallback_box(risk_type: str, view_label: str, layout: str, crop_w: int, crop_y_start: int, crop_h: int):
    vl = view_label.upper()
    if layout == "TOP_BOTTOM":
        half_h = crop_h // 2
        front_y0 = crop_y_start + int(half_h * 0.25)
        front_y1 = crop_y_start + int(half_h * 0.75)
        back_y0  = crop_y_start + half_h + int(half_h * 0.25)
        back_y1  = crop_y_start + half_h + int(half_h * 0.75)

        left_x0, left_x1   = int(crop_w * 0.20), int(crop_w * 0.45)
        right_x0, right_x1 = int(crop_w * 0.60), int(crop_w * 0.92)

        # FIX A: แยก REAR_EMPTY vs REAR_LATERAL ไม่ให้ซ้อนทับกัน
        #        REAR_EMPTY  → ครึ่งบนของโซน (ประตูท้าย)
        #        REAR_LATERAL → ครึ่งล่างของโซน (ด้านข้างประตู)
        front_mid_y = front_y0 + (front_y1 - front_y0) // 2
        back_mid_y  = back_y0  + (back_y1  - back_y0)  // 2

        # FIX B: เพิ่ม GENERAL — วาดคลุมทั้ง FRONT และ BACK zone รวมกัน
        gen_y0 = crop_y_start + int(crop_h * 0.15)
        gen_y1 = crop_y_start + int(crop_h * 0.85)

        zones = {
            # FRONT view (ครึ่งบนของภาพ)
            ("REAR_EMPTY_RISK",        "FRONT"):   (left_x0,  front_y0,   left_x1,  front_mid_y),
            ("REAR_LATERAL_IMBALANCE", "FRONT"):   (left_x0,  front_mid_y, left_x1, front_y1),
            ("FRONT_EMPTY_RISK",       "FRONT"):   (right_x0, front_y0,   right_x1, front_y1),
            # BACK view (ครึ่งล่างของภาพ)
            ("REAR_EMPTY_RISK",        "BACK"):    (right_x0, back_y0,    right_x1, back_mid_y),
            ("REAR_LATERAL_IMBALANCE", "BACK"):    (right_x0, back_mid_y, right_x1, back_y1),
            ("FRONT_EMPTY_RISK",       "BACK"):    (left_x0,  back_y0,    left_x1,  back_y1),
            # GENERAL — คลุมทั้งภาพในแนว Y แต่จำกัดแนว X ตามประเภท
            ("REAR_EMPTY_RISK",        "GENERAL"): (left_x0,  gen_y0,     left_x1,  gen_y0 + (gen_y1 - gen_y0) // 2),
            ("REAR_LATERAL_IMBALANCE", "GENERAL"): (left_x0,  gen_y0 + (gen_y1 - gen_y0) // 2, left_x1, gen_y1),
            ("FRONT_EMPTY_RISK",       "GENERAL"): (right_x0, gen_y0,     right_x1, gen_y1),
            ("STEP_DOWN_RISK",         "GENERAL"): (int(crop_w * 0.20), crop_y_start + int(crop_h * 0.20), int(crop_w * 0.75), crop_y_start + int(crop_h * 0.80)),
            ("STEP_DOWN_RISK",         "FRONT"):   (int(crop_w * 0.20), front_y0, int(crop_w * 0.75), front_y1),
            ("STEP_DOWN_RISK",         "BACK"):    (int(crop_w * 0.15), back_y0,  int(crop_w * 0.85), back_y1),
            # ✅ เพิ่มใหม่
            ("LATERAL_GAP_RISK",       "GENERAL"): (int(crop_w * 0.20), gen_y0,   int(crop_w * 0.75), gen_y1),
            ("LATERAL_GAP_RISK",       "FRONT"):   (int(crop_w * 0.20), front_y0, int(crop_w * 0.75), front_y1),
            ("LATERAL_GAP_RISK",       "BACK"):    (int(crop_w * 0.20), back_y0,  int(crop_w * 0.75), back_y1),
            ("TALL_UNSTABLE_RISK",     "GENERAL"): (int(crop_w * 0.25), gen_y0,   int(crop_w * 0.65), gen_y1),
            ("TALL_UNSTABLE_RISK",     "FRONT"):   (int(crop_w * 0.25), front_y0, int(crop_w * 0.65), front_y1),
            ("TALL_UNSTABLE_RISK",     "BACK"):    (int(crop_w * 0.25), back_y0,  int(crop_w * 0.65), back_y1),
            ("OVERHANG_RISK",          "GENERAL"): (int(crop_w * 0.20), gen_y0,   int(crop_w * 0.75), gen_y0 + (gen_y1 - gen_y0) // 2),
            ("OVERHANG_RISK",          "FRONT"):   (int(crop_w * 0.20), front_y0, int(crop_w * 0.75), front_mid_y),
            ("OVERHANG_RISK",          "BACK"):    (int(crop_w * 0.20), back_y0,  int(crop_w * 0.75), back_mid_y),
        }
    else:
        # Layout แบบ LEFT_RIGHT (Isometric)

        # Front View (ซ้ายของภาพ)
        # Front View (ซ้ายของภาพ)
        f_door_y0,  f_door_y1  = crop_y_start + int(crop_h * 0.25), crop_y_start + int(crop_h * 0.65)
        f_door_x0,  f_door_x1  = int(crop_w * 0.05), int(crop_w * 0.25)
        f_wall_y0,  f_wall_y1  = crop_y_start + int(crop_h * 0.15), crop_y_start + int(crop_h * 0.50)
        # FIX: x1 ไม่เกิน 0.46 เพื่อไม่ให้กล่องหลุดออกไปฝั่งขวาของ Front view
        f_wall_x0,  f_wall_x1  = int(crop_w * 0.28), int(crop_w * 0.46)
        f_door_mid_y = f_door_y0 + (f_door_y1 - f_door_y0) // 2

        # Back View (ขวาของภาพ)
        b_wall_y0,  b_wall_y1  = crop_y_start + int(crop_h * 0.50), crop_y_start + int(crop_h * 0.85)
        b_wall_x0,  b_wall_x1  = int(crop_w * 0.50), int(crop_w * 0.70)
        b_door_y0,  b_door_y1  = crop_y_start + int(crop_h * 0.15), crop_y_start + int(crop_h * 0.50)
        b_door_x0,  b_door_x1  = int(crop_w * 0.75), int(crop_w * 0.95)
        b_door_mid_y = b_door_y0 + (b_door_y1 - b_door_y0) // 2

        zones = {
            # FRONT view
            ("REAR_EMPTY_RISK",        "FRONT"):   (f_door_x0, f_door_y0,    f_door_x1, f_door_mid_y),
            ("REAR_LATERAL_IMBALANCE", "FRONT"):   (f_door_x0, f_door_mid_y, f_door_x1, f_door_y1),
            ("FRONT_EMPTY_RISK",       "FRONT"):   (f_wall_x0, f_wall_y0,    f_wall_x1, f_wall_y1),
            # BACK view
            ("REAR_EMPTY_RISK",        "BACK"):    (b_door_x0, b_door_y0,    b_door_x1, b_door_mid_y),
            ("REAR_LATERAL_IMBALANCE", "BACK"):    (b_door_x0, b_door_mid_y, b_door_x1, b_door_y1),
            ("FRONT_EMPTY_RISK",       "BACK"):    (b_wall_x0, b_wall_y0,    b_wall_x1, b_wall_y1),
            # GENERAL
            ("REAR_EMPTY_RISK",        "GENERAL"): (f_door_x0, f_door_y0,    f_door_x1, f_door_mid_y),
            ("REAR_LATERAL_IMBALANCE", "GENERAL"): (f_door_x0, f_door_mid_y, f_door_x1, f_door_y1),
            ("FRONT_EMPTY_RISK",       "GENERAL"): (f_wall_x0, f_wall_y0,    f_wall_x1, f_wall_y1),
            ("STEP_DOWN_RISK",         "GENERAL"): (int(crop_w * 0.10), crop_y_start + int(crop_h * 0.20), int(crop_w * 0.45), crop_y_start + int(crop_h * 0.80)),
            ("STEP_DOWN_RISK",         "FRONT"):   (int(crop_w * 0.10), crop_y_start + int(crop_h * 0.20), int(crop_w * 0.45), crop_y_start + int(crop_h * 0.80)),
            ("STEP_DOWN_RISK",         "BACK"):    (int(crop_w * 0.50), crop_y_start + int(crop_h * 0.20), int(crop_w * 0.90), crop_y_start + int(crop_h * 0.80)),
            # ✅ เพิ่มใหม่
            ("LATERAL_GAP_RISK",       "GENERAL"): (int(crop_w * 0.05), crop_y_start + int(crop_h * 0.20), int(crop_w * 0.45), crop_y_start + int(crop_h * 0.80)),
            ("LATERAL_GAP_RISK",       "FRONT"):   (int(crop_w * 0.05), crop_y_start + int(crop_h * 0.20), int(crop_w * 0.45), crop_y_start + int(crop_h * 0.80)),
            ("LATERAL_GAP_RISK",       "BACK"):    (int(crop_w * 0.50), crop_y_start + int(crop_h * 0.20), int(crop_w * 0.90), crop_y_start + int(crop_h * 0.80)),
            ("TALL_UNSTABLE_RISK",     "GENERAL"): (int(crop_w * 0.05), crop_y_start + int(crop_h * 0.10), int(crop_w * 0.45), crop_y_start + int(crop_h * 0.60)),
            ("TALL_UNSTABLE_RISK",     "FRONT"):   (int(crop_w * 0.05), crop_y_start + int(crop_h * 0.10), int(crop_w * 0.45), crop_y_start + int(crop_h * 0.60)),
            ("TALL_UNSTABLE_RISK",     "BACK"):    (int(crop_w * 0.50), crop_y_start + int(crop_h * 0.10), int(crop_w * 0.90), crop_y_start + int(crop_h * 0.60)),
            ("OVERHANG_RISK",          "GENERAL"): (int(crop_w * 0.05), crop_y_start + int(crop_h * 0.10), int(crop_w * 0.45), crop_y_start + int(crop_h * 0.45)),
            ("OVERHANG_RISK",          "FRONT"):   (int(crop_w * 0.05), crop_y_start + int(crop_h * 0.10), int(crop_w * 0.45), crop_y_start + int(crop_h * 0.45)),
            ("OVERHANG_RISK",          "BACK"):    (int(crop_w * 0.50), crop_y_start + int(crop_h * 0.10), int(crop_w * 0.90), crop_y_start + int(crop_h * 0.45)),
        }

    return zones.get((risk_type, vl))

# ฟังก์ชันหลัก (Entry Point) ที่รับ HTTP Request
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
        # 1. พยายามดึง JSON ด้วยคำสั่งมาตรฐาน
        data = request.get_json(silent=True)
        
        # 2. ถ้าดึงไม่ได้ (data เป็น None) ให้บังคับแปลงจากข้อความดิบ (Raw Data)
        if data is None:
            import json
            raw_data = request.get_data(as_text=True)
            if raw_data:
                data = json.loads(raw_data)
            else:
                data = {}
                
        # 3. ตรวจสอบว่าได้ข้อมูล base64 มาหรือไม่
        if not data or 'base64' not in data:
            # พ่น Log ข้อความ 500 ตัวอักษรแรกที่รับมา เพื่อตรวจสอบว่าเกิดอะไรขึ้น
            print("🚨 DEBUG - RECEIVED DATA:", request.get_data(as_text=True)[:500])
            return ({"error": "No base64 data provided"}, 400, headers)

        base64_str = data.get('base64')
        if "," in base64_str:
            base64_str = base64_str.split(",")[1]
            
        pdf_bytes = base64.b64decode(base64_str)

        layout = detect_page_layout_from_pdf(pdf_bytes)

        # ใช้ PyMuPDF (fitz) แปลง PDF เป็นรูปภาพแทน pdf2image
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        
        # เลือกหน้าที่ 2 (index 1) ถ้ามี ถ้าไม่มีให้ใช้หน้าที่ 1 (index 0)
        page_index = 1 if len(doc) >= 2 else 0 
        page = doc[page_index]
        
        # เรนเดอร์หน้า PDF เป็นภาพความละเอียด 180 DPI
        pix = page.get_pixmap(dpi=180)
        mode = "RGBA" if pix.alpha else "RGB"
        img = PIL.Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        width, height = img.size

        crop_y_start = int(height * 0.10)
        crop_y_end   = int(height * 0.90)
        crop_w       = int(width * 0.75) 
        crop_h       = crop_y_end - crop_y_start

        diagram_crop = img.crop((0, crop_y_start, crop_w, crop_y_end))
        all_risks = analyze_diagram_image_with_ai(diagram_crop)

        if layout == "TOP_BOTTOM":
            # TOP_BOTTOM: ภาพ Front อยู่ครึ่งบน, Back อยู่ครึ่งล่าง
            # ในแต่ละครึ่ง: ประตูท้าย = ซ้าย, หัวตู้ = ขวา
            half_h = crop_h // 2
            rear_crop_front  = img.crop((0,                  crop_y_start,          int(crop_w * 0.45), crop_y_start + half_h))
            front_crop_front = img.crop((int(crop_w * 0.55), crop_y_start,          crop_w,             crop_y_start + half_h))
            front_crop_back  = img.crop((0,                  crop_y_start + half_h, int(crop_w * 0.45), crop_y_end))
            rear_crop_back   = img.crop((int(crop_w * 0.55), crop_y_start + half_h, crop_w,             crop_y_end))
        else:
            # LEFT_RIGHT: ภาพ Front อยู่ซีกซ้าย, Back อยู่ซีกขวา
            # มุมมอง 3D Isometric จริง:
            #   Front view (ซ้าย): ประตูท้ายตู้ = มุมซ้ายล่าง | หัวตู้ = มุมขวาบน
            #   Back view  (ขวา):  หัวตู้        = มุมซ้ายล่าง | ประตูท้ายตู้ = มุมขวาบน
            half_w = crop_w // 2
            mid_h  = crop_y_start + int(crop_h * 0.50)  # เส้นแบ่งแนวนอนกลางภาพ

            # Front view — ซีกซ้าย
            rear_crop_front  = img.crop((0,                         mid_h,        int(half_w * 0.55),        crop_y_end))   # ประตูท้าย: มุมซ้ายล่าง
            front_crop_front = img.crop((int(half_w * 0.45),        crop_y_start, half_w,                   mid_h))        # หัวตู้:    มุมขวาบน

            # Back view — ซีกขวา
            front_crop_back  = img.crop((half_w,                    mid_h,        half_w + int(half_w * 0.55), crop_y_end)) # หัวตู้:    มุมซ้ายล่าง
            rear_crop_back   = img.crop((half_w + int(half_w * 0.45), crop_y_start, crop_w,                  mid_h))       # ประตูท้าย: มุมขวาบน

            print(f"📐 LEFT_RIGHT crop — "
                  f"rear_F=({0},{mid_h},{int(half_w*0.55)},{crop_y_end}) | "
                  f"front_F=({int(half_w*0.45)},{crop_y_start},{half_w},{mid_h}) | "
                  f"front_B=({half_w},{mid_h},{half_w+int(half_w*0.55)},{crop_y_end}) | "
                  f"rear_B=({half_w+int(half_w*0.45)},{crop_y_start},{crop_w},{mid_h})")

        api_keys_pool = get_api_keys_pool()
        rear_result_front = analyze_rear_zone_with_ai(rear_crop_front, api_keys_pool, "FRONT")
        rear_result_back = analyze_rear_zone_with_ai(rear_crop_back, api_keys_pool, "BACK")
        front_result_front = analyze_front_zone_with_ai(front_crop_front, api_keys_pool, "FRONT")
        front_result_back = analyze_front_zone_with_ai(front_crop_back, api_keys_pool, "BACK")

        if not isinstance(all_risks, list):
            all_risks = []

        # ---------------------------------------------------------------------------
        # FIX 1: normalize view และ dedup โดยใช้ risk_type เป็นหลัก
        # GENERAL ที่มาจาก analyze_diagram ถือว่าครอบคลุม FRONT+BACK ของ risk นั้นแล้ว
        # ---------------------------------------------------------------------------
        def _normalize_view(v: str) -> str:
            v = str(v).upper().strip()
            return "GENERAL" if v in ("", "GENERAL") else v

        def _existing_risk_types() -> set:
            """คืน set ของ risk_type ที่มีอยู่แล้วใน all_risks (ไม่สนใจ view)"""
            return {str(r.get("risk_type", "")).upper().strip() for r in all_risks}

        def _existing_risk_views(risk_type_substr: str) -> set:
            """คืน set ของ view ที่มีอยู่แล้วสำหรับ risk_type นั้น
            ถ้า GENERAL เจอแล้ว → ถือว่าครอบคลุม FRONT และ BACK ไปเลย"""
            views = set()
            for r in all_risks:
                if risk_type_substr in str(r.get("risk_type", "")).upper():
                    v = _normalize_view(r.get("view", ""))
                    views.add(v)
                    if v == "GENERAL":
                        views.update(["FRONT", "BACK"])
            return views

        # ---------------------------------------------------------------------------
        # FIX 2: กรอง LOW confidence ออก — เฉพาะ HIGH/MEDIUM เท่านั้นที่ผ่าน
        # ---------------------------------------------------------------------------
        for view_label, rear_result in [("FRONT", rear_result_front), ("BACK", rear_result_back)]:
            if not isinstance(rear_result, dict):
                continue
                
            rear_zone_risk = str(rear_result.get("rear_zone_risk", "")).upper()
            confidence = str(rear_result.get("confidence", "LOW")).upper()

            if confidence not in ("HIGH", "MEDIUM"):
                print(f"⚠️ Skipping rear zoom ({view_label}) — confidence={confidence}")
                continue

            if rear_zone_risk in ("REAR_EMPTY_RISK", "BOTH") and view_label not in _existing_risk_views("REAR_EMPTY"):
                all_risks.append({"view": view_label, "risk_type": "REAR_EMPTY_RISK", "direction": "LONGITUDINAL", "lateral_side": "N/A", "reasoning": rear_result.get("reasoning", ""), "description": "พบความต่างระดับฝั่งประตูท้ายตู้ (วิเคราะห์จาก Zoom ท้ายตู้)", "box_2d": None})
            if rear_zone_risk in ("REAR_LATERAL_IMBALANCE", "BOTH") and view_label not in _existing_risk_views("REAR_LATERAL"):
                all_risks.append({"view": view_label, "risk_type": "REAR_LATERAL_IMBALANCE", "direction": "LATERAL", "lateral_side": "N/A", "reasoning": rear_result.get("reasoning", ""), "description": "พบสินค้าท้ายตู้สูงต่ำไม่เท่ากัน (วิเคราะห์จาก Zoom ท้ายตู้)", "box_2d": None})

        for view_label, front_result in [("FRONT", front_result_front), ("BACK", front_result_back)]:
            if not isinstance(front_result, dict):
                continue
                
            confidence = str(front_result.get("confidence", "LOW")).upper()

            if confidence not in ("HIGH", "MEDIUM"):
                print(f"⚠️ Skipping front zoom ({view_label}) — confidence={confidence}")
                continue

            if front_result.get("front_zone_risk", "").upper() == "FRONT_EMPTY_RISK" and view_label not in _existing_risk_views("FRONT_EMPTY"):
                all_risks.append({"view": view_label, "risk_type": "FRONT_EMPTY_RISK", "direction": "LONGITUDINAL", "lateral_side": "N/A", "reasoning": front_result.get("reasoning", ""), "description": "พบสินค้าต่างระดับฝั่งผนังหัวตู้ (วิเคราะห์จาก Zoom หัวตู้)", "box_2d": None})

        # ---------------------------------------------------------------------------
        # วาดกล่องและสร้าง report
        # หลักการ:
        #   - dedup ด้วย risk_type อย่างเดียว (GENERAL/FRONT/BACK ของ risk เดิม = 1 รายการ)
        #   - วาดกล่องทุกจุดที่ทำได้ (อาจมีหลายกล่องต่อ risk_type)
        #   - append hazard เสมอ ไม่ขึ้นกับว่าวาดกล่องได้หรือไม่
        # ---------------------------------------------------------------------------
        draw = PIL.ImageDraw.Draw(img)
        detected_hazards = []
        reported_risk_types = set()  # FIX 3: dedup report ด้วย risk_type เพียงอย่างเดียว

        RISK_COLORS = {"STEP_DOWN_RISK": "red", "REAR_EMPTY_RISK": "orange", "REAR_LATERAL_IMBALANCE": "deeppink", "FRONT_EMPTY_RISK": "yellow", "LATERAL_GAP_RISK": "cyan", "TALL_UNSTABLE_RISK": "magenta", "OVERHANG_RISK": "lime"}
        VALID_RISK_TYPES = set(RISK_COLORS.keys())

        for risk in all_risks:
            raw_risk_type = str(risk.get("risk_type", "")).upper().strip()
            view_name = _normalize_view(risk.get("view", "GENERAL"))
            matched_type = next((vrt for vrt in VALID_RISK_TYPES if vrt.replace("_RISK", "") in raw_risk_type or raw_risk_type in vrt), None)

            if raw_risk_type == "ERROR":
                detected_hazards.append({"title": "⚠️ ข้อผิดพลาด API", "detail": risk.get("description", "โปรดตรวจสอบโควตา Gemini API Keys"), "is_error": True})
                continue
            if not matched_type:
                continue

            risk_type = matched_type
            outline_color = RISK_COLORS.get(risk_type, "red")
            box = risk.get("box_2d") or risk.get("boundingBox") or risk.get("box")

            # --- วาดกล่อง (แยกออกจาก logic report) ---
            drawn = False
            if box and isinstance(box, list) and len(box) == 4:
                try:
                    ymin, xmin, ymax, xmax = map(float, box)
                    if max(ymin, xmin, ymax, xmax) <= 1.0:
                        ymin, xmin, ymax, xmax = ymin*1000, xmin*1000, ymax*1000, xmax*1000
                    abs_xmin = max(0, min(int(xmin * crop_w / 1000.0), crop_w - 1))
                    abs_xmax = max(abs_xmin + 1, min(int(xmax * crop_w / 1000.0), crop_w))
                    abs_ymin = max(crop_y_start, min(int(crop_y_start + (ymin * crop_h / 1000.0)), crop_y_end - 1))
                    abs_ymax = max(abs_ymin + 1, min(int(crop_y_start + (ymax * crop_h / 1000.0)), crop_y_end))
                    
                    # ✅ เพิ่มตรงนี้ — validate ก่อนวาด
                    box_center_x = (abs_xmin + abs_xmax) / 2
                    box_center_y = (abs_ymin + abs_ymax) / 2
                    # LEFT_RIGHT: Front view อยู่ซีกซ้าย (< 50%) ป้องกันกล่องหลุดไปซีกขวา
                    cargo_zone_xmax = crop_w * 0.50 if layout == "LEFT_RIGHT" else crop_w * 0.95
                    cargo_zone_ymin = crop_y_start + crop_h * 0.05
                    cargo_zone_ymax = crop_y_end   - crop_h * 0.05

                    if box_center_x > cargo_zone_xmax or not (cargo_zone_ymin < box_center_y < cargo_zone_ymax):
                        print(f"⚠️ box_2d center ({box_center_x:.0f}, {box_center_y:.0f}) out of cargo zone — falling back to fallback box for {risk_type}")
                        raise ValueError("box out of cargo zone")  # กระโดดไป except → drawn=False → ใช้ fallback

                    box_w_ratio = (abs_xmax - abs_xmin) / crop_w
                    box_h_ratio = (abs_ymax - abs_ymin) / crop_h

                    if box_w_ratio < 0.80 and box_h_ratio < 0.80:
                        # กล่องขนาดปกติ — วาดตามพิกัดจริงจาก Gemini
                        draw.rectangle([abs_xmin, abs_ymin, abs_xmax, abs_ymax], outline=outline_color, width=8)
                        drawn = True
                    else:
                        # FIX 4: กล่องใหญ่เกิน 80% — clamp ให้แคบลงแต่ยังอยู่ในบริเวณที่ Gemini ชี้
                        # แทนที่จะ reject ทิ้ง ให้ clamp และวาด
                        pad_x = int(crop_w * 0.10)
                        pad_y = int(crop_h * 0.10)
                        clamped_xmin = max(abs_xmin, pad_x)
                        clamped_xmax = min(abs_xmax, crop_w - pad_x)
                        clamped_ymin = max(abs_ymin, crop_y_start + pad_y)
                        clamped_ymax = min(abs_ymax, crop_y_start + crop_h - pad_y)
                        
                        if clamped_xmax > clamped_xmin and clamped_ymax > clamped_ymin:
                            draw.rectangle([clamped_xmin, clamped_ymin, clamped_xmax, clamped_ymax], outline=outline_color, width=8)
                            drawn = True
                            print(f"📦 Clamped oversized box for {risk_type} ({view_name})")
                except Exception:
                    pass

            if not drawn:
                # ใช้ fallback zone ตามตำแหน่งที่กำหนดไว้
                fallback = _get_fallback_box(risk_type, view_name, layout, crop_w, crop_y_start, crop_h)
                if fallback:
                    draw.rectangle(fallback, outline=outline_color, width=8)
                    drawn = True

            if not drawn:
                print(f"⚠️ Could not draw box for {risk_type} ({view_name}) — no valid coords or fallback")

            # --- FIX 3: append report ครั้งเดียวต่อ risk_type (ไม่ขึ้นกับ view และไม่ขึ้นกับ drawn) ---
            if risk_type not in reported_risk_types:
                reported_risk_types.add(risk_type)
                detected_hazards.append({
                    "title": f"ความเสี่ยง: {risk_type}",
                    "detail": generate_action_report(risk_type, risk.get("description", "")),
                    "is_error": False
                })

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
        print("🚨 CRITICAL ERROR DETAILS:\n", err_trace) 
        gc.collect()
        return ({"error": str(e), "trace": err_trace[-500:]}, 500, headers)
