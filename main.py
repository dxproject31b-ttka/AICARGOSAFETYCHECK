import base64
import io
import json
import os
import time
import gc
import traceback
import random
from pdf2image import convert_from_bytes
import PIL.Image
import PIL.ImageDraw
import PIL.ImageStat
import fitz  # PyMuPDF สำหรับหาคำว่า "Back"
import functions_framework
import google.generativeai as genai

# ---------------------------------------------------------------------------
# Backend API สำหรับ AI Cargo Safety Checker ( High-Precision v5 )
# [อัปเดตล่าสุด]
# 1. ใช้ PyMuPDF หาพิกัดคำว่า "Back" เพื่อระบุ Layout (TOP_BOTTOM / LEFT_RIGHT) อย่างแม่นยำ
# 2. ตัดตารางข้อความ (Load Summary) ทิ้งก่อนวิเคราะห์ ป้องกัน AI สับสน
# 3. แก้ไข Prompt เลิกบังคับให้ AI นับชั้น (Layer) เน้นหา Physical Height Drop (ขั้นบันได)
# 4. ลบกฎ Perspective / ห้ามดูสี ที่ตึงเกินไปออก
# 5. ขยายระยะ Crop ท้ายตู้ให้กว้างขึ้น และเพิ่มขอบ Margin ให้ Fallback Box
# ---------------------------------------------------------------------------

# ============================================================
# SECTION 1 — UTILITY: API KEYS 
# ============================================================

GLOBAL_API_KEYS = []
GLOBAL_KEY_INDEX = 0

def get_api_keys_pool():
    global GLOBAL_API_KEYS
    if GLOBAL_API_KEYS:
        return GLOBAL_API_KEYS

    keys = []
    for env_k, env_v in os.environ.items():
        k_upper = env_k.upper().strip()
        if ("GEMINI" in k_upper or "API_KEY" in k_upper) and env_v and env_v.strip():
            extracted_keys = [k.strip() for k in env_v.split(",") if k.strip()]
            keys.extend(extracted_keys)

    keys = list(set(keys))
    if keys:
        random.shuffle(keys)
        print(f"✅ Loaded {len(keys)} unique API key(s) into the pool.")
        GLOBAL_API_KEYS = keys
        return GLOBAL_API_KEYS

    print("❌ No Gemini API keys found.")
    return []

# ============================================================
# SECTION 2 — UTILITY: ACTION REPORTS 
# ============================================================

def generate_action_report(case_type, description):
    actions = {
        "STEP_DOWN_RISK":
            f"🚨 [ALERT] พบรอยต่างระดับระหว่างกองสินค้า (Step-Down)\n{description}\n"
            f"🛠️ ACTION: ติดตั้งแผ่นไม้กั้นขวาง (Void Filler / Dunnage) ระหว่างกอง "
            f"และรัดตรึงให้ครบทุกจุด",

        "REAR_EMPTY_RISK":
            f"🚨 [ALERT] พบพื้นที่โล่ง/สินค้าต่างระดับ ฝั่งประตูท้ายตู้ (REAR EMPTY)\n{description}\n"
            f"🛠️ ACTION: ติดตั้งแผ่นไม้ค้ำแนวดิ่ง (Rear Tomming) + "
            f"รัดตรึงป้องกันสินค้าไถลออกประตู",

        "REAR_LATERAL_IMBALANCE":
            f"🚨 [ALERT] พบสินค้าท้ายตู้สูงต่ำไม่เท่ากันในแนวกว้าง (Rear Lateral Imbalance)\n"
            f"{description}\n"
            f"🛠️ ACTION: เสริมด้านที่ต่ำกว่าด้วย Void Filler / Dunnage ให้ระดับเท่ากัน "
            f"+ รัดตรึงขวางป้องกันสินค้าล้มตะแคงเมื่อเปิดประตู",

        "FRONT_EMPTY_RISK":
            f"🚨 [ALERT] พบพื้นที่โล่ง/สินค้าต่างระดับ ฝั่งผนังหัวตู้ (FRONT EMPTY)\n{description}\n"
            f"🛠️ ACTION: ติดตั้งแผ่นไม้ค้ำฝั่งหัวตู้ (Front Blocking) + "
            f"รัดตรึงป้องกันสินค้าไถลหน้าเมื่อเบรก",

        "LATERAL_GAP_RISK":
            f"🚨 [ALERT] พบช่องว่างด้านข้างระหว่างกองสินค้า (Lateral Gap)\n{description}\n"
            f"🛠️ ACTION: ใส่ Air Bag หรือ Void Filler ด้านข้าง + "
            f"รัดตรึงป้องกันสินค้าเลื่อนตะแคงขณะเลี้ยว",

        "TALL_UNSTABLE_RISK":
            f"🚨 [ALERT] พบสินค้าสูงโดดเดี่ยว ไม่มีของข้างค้ำ (Tall / Unstable)\n{description}\n"
            f"🛠️ ACTION: ค้ำยันด้านข้างกองสูง + รัดตรึงแนวขวาง ป้องกันล้มตะแคง",

        "OVERHANG_RISK":
            f"🚨 [ALERT] พบสินค้าชั้นบนยื่นพ้นขอบสินค้าชั้นล่าง (Overhang)\n{description}\n"
            f"🛠️ ACTION: จัดเรียงใหม่ให้ชั้นบนไม่ยื่นพ้นฐาน "
            f"หรือใส่แผ่นรองรับและรัดตรึง",
    }
    return actions.get(
        case_type,
        "🟢 [STATUS] ปลอดภัย (SAFE)\nไม่พบจุดเสี่ยงที่ต้องดำเนินการเพิ่มเติม"
    )

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

# ============================================================
# SECTION 3 — LAYOUT DETECTOR (PDF Text Search)
# ============================================================

def detect_page_layout_from_pdf(pdf_bytes: bytes) -> str:
    """
    อ่านพิกัดคำว่า "Back" เพื่อระบุ Layout (TOP_BOTTOM หรือ LEFT_RIGHT)
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_index = 1 if len(doc) >= 2 else 0
        page = doc[page_index]
        
        page_width = page.rect.width
        page_height = page.rect.height
        
        text_instances = page.search_for("Back")
        
        if text_instances:
            rect = text_instances[0]
            y_position = rect.y0
            x_position = rect.x0
            
            print(f"🔍 Found 'Back' at X: {x_position:.1f}, Y: {y_position:.1f} (Page: {page_width}x{page_height})")
            
            # ถ้า Y อยู่ครึ่งล่าง = TOP_BOTTOM
            if y_position > (page_height * 0.40):
                print("✅ Detected layout: TOP_BOTTOM")
                return "TOP_BOTTOM"
            # ถ้า X อยู่ครึ่งขวา = LEFT_RIGHT
            elif x_position > (page_width * 0.40):
                print("✅ Detected layout: LEFT_RIGHT")
                return "LEFT_RIGHT"
                
    except Exception as e:
        print(f"⚠️ Layout detection failed ({e}), defaulting to TOP_BOTTOM")
        
    return "TOP_BOTTOM"

# ============================================================
# SECTION 4 — AI: REAR & FRONT ZONE CROP ANALYSIS
# ============================================================

def analyze_rear_zone_with_ai(rear_crop: PIL.Image.Image, api_keys: list, view_label: str = "UNKNOWN") -> dict:
    global GLOBAL_KEY_INDEX 
    
    rear_prompt = f"""
You are a Cargo Safety Inspector. This image is a cropped zoom of the DOOR END (REAR) zone of a container.
This is the {view_label} view. The red arrows point to the floor at the open door.

YOUR ONLY TASK: Look for physical height drops ("Stair-Steps" or "Cliffs") at the end of the cargo.

HOW TO DETECT "REAR_EMPTY_RISK" (Longitudinal):
1. Look at the very last stack of cargo closest to the door (red arrows).
2. Look at the stack immediately behind it (deeper inside the container).
3. If there is a clear physical step-down (the last stack is physically shorter than the stack behind it), report "REAR_EMPTY_RISK".

HOW TO DETECT "REAR_LATERAL_IMBALANCE" (Side-to-Side):
1. Compare the left wall cargo to the right wall cargo at the door end.
2. If one side is physically taller than the other side, report "REAR_LATERAL_IMBALANCE".

CRITICAL RULE:
- Do NOT get confused by box colors or layer counts. Different SKUs have different box sizes. Focus ONLY on the overall physical block height.
- Color changes often happen exactly where the physical height drops. Do NOT ignore a physical height drop just because the color changed.

Return ONLY this exact JSON format:
{{
  "rear_zone_risk": "REAR_EMPTY_RISK" | "REAR_LATERAL_IMBALANCE" | "BOTH" | "SAFE",
  "reasoning": "Explain the physical height difference you see. (e.g., The stack at the door is clearly shorter than the stack behind it).",
  "confidence": "HIGH" | "MEDIUM" | "LOW"
}}
"""
    return _call_gemini_json(rear_prompt, rear_crop, api_keys)
                                   
def analyze_front_zone_with_ai(front_crop: PIL.Image.Image, api_keys: list, view_label: str = "UNKNOWN") -> dict:
    global GLOBAL_KEY_INDEX
    front_prompt = f"""
You are a Cargo Safety Inspector. This image is a cropped zoom of the HEAD WALL (FRONT) zone of a container.
This is the {view_label} view. The yellow/tan solid wall is the head wall.

YOUR TASK: Detect if there is a FRONT_EMPTY_RISK in this cropped area.

SIGNALS FOR FRONT_EMPTY_RISK:
1. Visible empty floor space between the solid yellow head wall and the first cargo column.
2. A clear physical height drop (stair-step) where the first cargo touching the wall is shorter than the cargo behind it.

CRITICAL RULE: Focus on physical overall height, not box layer counts.

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
    if total_keys == 0: return {"rear_zone_risk": "ERROR", "front_zone_risk": "ERROR", "reasoning": "No API keys", "confidence": "LOW"}

    for i in range(total_keys):
        current_index = (GLOBAL_KEY_INDEX + i) % total_keys
        current_key = api_keys[current_index]
        try:
            if hasattr(genai, '_client'): genai._client = None
            genai.configure(api_key=current_key)
            model = genai.GenerativeModel(model_name="gemini-1.5-flash", generation_config={"response_mime_type": "application/json"})
            response = model.generate_content([prompt, image]) 
            clean_text = clean_json_response(response.text if response.text else "{}")
            result = json.loads(clean_text)
            if isinstance(result, list): result = result[0] if result else {}
            GLOBAL_KEY_INDEX = current_index 
            return result
        except Exception as e:
            last_err = str(e)
            if "404" in last_err or "not found" in last_err.lower(): continue
            break
    return {"rear_zone_risk": "ERROR", "front_zone_risk": "ERROR", "reasoning": last_err[:120], "confidence": "LOW"}

# ============================================================
# SECTION 5 — AI: FULL DIAGRAM ANALYSIS
# ============================================================

def analyze_diagram_image_with_ai(diagram_image: PIL.Image.Image):
    global GLOBAL_KEY_INDEX 
    
    api_keys = get_api_keys_pool()
    if not api_keys: return [{"risk_type": "ERROR", "description": "No Gemini API Keys found."}]

    prompt = """
You are an expert Cargo Loading Safety Inspector. Your mission is to detect ALL physical risks of cargo shifting or tipping.
This image shows a 3D cargo loading diagram with two views labeled "Front" and "Back".

=======================================================================
PART 0 — CRITICAL RULES (read FIRST, apply ALWAYS)
=======================================================================
⛔ COLOR RULE — Box color = SKU type. Color alone is NOT a risk. HOWEVER, physical height drops often occur exactly where box colors change. Do NOT ignore a physical height drop just because the color changed. Focus purely on the PHYSICAL BLOCK HEIGHT.
⛔ STAGGER/OFFSET RULE — Boxes that are offset horizontally but remain at the SAME PHYSICAL HEIGHT are NOT a risk.

=======================================================================
PART 1 — IDENTIFY PHYSICAL ORIENTATION
=======================================================================
• DOOR END (Physical Rear): Open side with visible FLOOR GRID and TWO RED ARROWS.
• HEAD WALL (Physical Front): SOLID YELLOW/TAN WALL.

=======================================================================
PART 2 — SYSTEMATIC RISK SCAN (Focus on Physical Heights, not box counts)
=======================================================================
--- RISK 1: REAR_EMPTY_RISK ---
Trigger: Near the DOOR END. A clear physical height drop (stair-step) where the last stack is shorter than the stack behind it, OR visible empty floor.

--- RISK 2: REAR_LATERAL_IMBALANCE ---
Trigger: Near the DOOR END. The cargo block on the LEFT side is physically taller OR shorter than the RIGHT side.

--- RISK 3: FRONT_EMPTY_RISK ---
Trigger: Near the HEAD WALL. Visible empty floor space OR a physical height drop at the wall.

--- RISK 4: STEP_DOWN_RISK ---
Trigger: In the MIDDLE section. A clear physical height drop (staircase/cliff shape) between adjacent columns.

--- RISK 5: LATERAL_GAP_RISK ---
Trigger: Side-to-side (WIDTH direction). Visible empty space between cargo groups in width direction.

--- RISK 6: TALL_UNSTABLE_RISK ---
Trigger: A stack is physically taller than ALL surrounding columns on BOTH sides (unsupported).

--- RISK 7: OVERHANG_RISK ---
Trigger: A box on TOP extends BEYOND the footprint of the boxes below it.

=======================================================================
OUTPUT FORMAT — Strict JSON array. No markdown.
=======================================================================
Return ONLY a JSON array. If SAFE, return: []

Schema:
{
  "view": "FRONT" | "BACK",
  "risk_type": "REAR_EMPTY_RISK" | "REAR_LATERAL_IMBALANCE" | "FRONT_EMPTY_RISK" | "STEP_DOWN_RISK" | "LATERAL_GAP_RISK" | "TALL_UNSTABLE_RISK" | "OVERHANG_RISK",
  "direction": "LONGITUDINAL" | "LATERAL" | "VERTICAL",
  "lateral_side": "LEFT_HIGHER" | "RIGHT_HIGHER" | "N/A",
  "reasoning": "Describe the PHYSICAL height drop or gap you see.",
  "description": "<Thai language: อธิบายความเสี่ยง>",
  "box_2d": [ymin, xmin, ymax, xmax]
}
"""
    last_error_msg = ""
    for pass_round in range(2):
        for i in range(len(api_keys)):
            current_index = (GLOBAL_KEY_INDEX + i) % len(api_keys)
            current_key = api_keys[current_index]
            try:
                if hasattr(genai, '_client'): genai._client = None
                genai.configure(api_key=current_key)
                model = genai.GenerativeModel(model_name="gemini-1.5-flash", generation_config={"response_mime_type": "application/json"})
                response = model.generate_content([prompt, diagram_image])
                clean_text = clean_json_response(response.text if response.text else "[]")
                if not clean_text or clean_text in ('""', '[]'): return []
                risks = json.loads(clean_text)
                if isinstance(risks, dict): risks = [risks]
                GLOBAL_KEY_INDEX = current_index
                return risks
            except Exception as e:
                last_error_msg = str(e)
                if "429" in last_error_msg.lower() or "quota" in last_error_msg.lower(): break 
        if pass_round == 0: time.sleep(2)
    return [{"risk_type": "ERROR", "description": f"AI Error: {last_error_msg[:120]}"}]

# ============================================================
# SECTION 6 — FALLBACK BOX HELPER
# ============================================================

def _get_fallback_box(risk_type: str, view_label: str, layout: str, crop_w: int, crop_y_start: int, crop_h: int):
    vl = view_label.upper()
    crop_y_end = crop_y_start + crop_h
                          
    if layout == "TOP_BOTTOM":
        half_h = crop_h // 2
        front_y0 = crop_y_start + int(half_h * 0.50)
        front_y1 = crop_y_start + half_h
        back_y0  = crop_y_start + half_h + int(half_h * 0.50)
        back_y1  = crop_y_end

        margin_left = int(crop_w * 0.10)
        margin_right = int(crop_w * 0.90)

        zones = {
            ("REAR_EMPTY_RISK",        "FRONT"): (margin_left, front_y0, int(crop_w * 0.45), front_y1),
            ("REAR_LATERAL_IMBALANCE", "FRONT"): (margin_left, front_y0, int(crop_w * 0.45), front_y1),
            ("REAR_EMPTY_RISK",        "BACK"):  (int(crop_w * 0.55), back_y0, margin_right, back_y1),
            ("REAR_LATERAL_IMBALANCE", "BACK"):  (int(crop_w * 0.55), back_y0, margin_right, back_y1),
            ("FRONT_EMPTY_RISK",       "FRONT"): (int(crop_w * 0.55), front_y0, margin_right, front_y1),
            ("FRONT_EMPTY_RISK",       "BACK"):  (margin_left, back_y0, int(crop_w * 0.45), back_y1),
        }
    else:  # LEFT_RIGHT
        y0 = crop_y_start + int(crop_h * 0.30)
        y1 = crop_y_start + int(crop_h * 0.80)
        margin_left = int(crop_w * 0.10)
        margin_right = int(crop_w * 0.90)

        zones = {
            ("REAR_EMPTY_RISK",        "FRONT"): (margin_left, y0, int(crop_w * 0.35), y1),
            ("REAR_LATERAL_IMBALANCE", "FRONT"): (margin_left, y0, int(crop_w * 0.35), y1),
            ("REAR_EMPTY_RISK",        "BACK"):  (int(crop_w * 0.65), y0, margin_right, y1),
            ("REAR_LATERAL_IMBALANCE", "BACK"):  (int(crop_w * 0.65), y0, margin_right, y1),
            ("FRONT_EMPTY_RISK",       "FRONT"): (int(crop_w * 0.65), y0, margin_right, y1),
            ("FRONT_EMPTY_RISK",       "BACK"):  (margin_left, y0, int(crop_w * 0.35), y1),
        }

    return zones.get((risk_type, vl))

# ============================================================
# SECTION 7 — MAIN CLOUD FUNCTION HANDLER
# ============================================================

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
        data = request.get_json(silent=True) or {}
        if not data or 'base64' not in data:
            return ({"error": "No base64 data provided"}, 400, headers)

        base64_str = data.get('base64')
        if "," in base64_str:
            base64_str = base64_str.split(",")[1]
        pdf_bytes = base64.b64decode(base64_str)

        # ------------------------------------------------------------------
        # 1. Detect Layout ก่อนแปลงรูป (ใช้ Text PDF)
        # ------------------------------------------------------------------
        layout = detect_page_layout_from_pdf(pdf_bytes)

        # ------------------------------------------------------------------
        # 2. Render PDF to Image
        # ------------------------------------------------------------------
        try:
            pages = convert_from_bytes(pdf_bytes, first_page=2, last_page=2, dpi=180)
        except Exception:
            pages = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=180)

        img = pages[0]
        width, height = img.size

        # ------------------------------------------------------------------
        # 3. Crop Area & ตัดตารางข้อความทิ้ง
        # ------------------------------------------------------------------
        crop_y_start = int(height * 0.10)
        crop_y_end   = int(height * 0.90)
        
        # ตัดตารางข้อความด้านขวาทิ้ง เหลือ 75% ของหน้ากระดาษ
        crop_w       = int(width * 0.75) 
        crop_h       = crop_y_end - crop_y_start

        diagram_crop = img.crop((0, crop_y_start, crop_w, crop_y_end))

        # ------------------------------------------------------------------
        # 4. Full diagram analysis 
        # ------------------------------------------------------------------
        all_risks = analyze_diagram_image_with_ai(diagram_crop)

        # ------------------------------------------------------------------
        # 5. Rear&Front Zone Crop 
        # ------------------------------------------------------------------
        if layout == "TOP_BOTTOM":
            half_h = crop_h // 2
            # ขยายระยะการซูมเป็น 45% (จากเดิม 38%)
            rear_crop_front = img.crop((0, crop_y_start, int(crop_w * 0.45), crop_y_start + half_h))
            rear_crop_back = img.crop((int(crop_w * 0.55), crop_y_start + half_h, crop_w, crop_y_end))
            front_crop_front = img.crop((int(crop_w * 0.55), crop_y_start, crop_w, crop_y_start + half_h))
            front_crop_back = img.crop((0, crop_y_start + half_h, int(crop_w * 0.45), crop_y_end))
        else:  # LEFT_RIGHT
            # ปรับสัดส่วนซูมให้สัมพันธ์กัน
            rear_crop_front = img.crop((0, crop_y_start, int(crop_w * 0.35), crop_y_end))
            rear_crop_back = img.crop((int(crop_w * 0.65), crop_y_start, crop_w, crop_y_end))
            front_crop_front = img.crop((int(crop_w * 0.65), crop_y_start, crop_w, crop_y_end))
            front_crop_back = img.crop((0, crop_y_start, int(crop_w * 0.35), crop_y_end))

        # ------------------------------------------------------------------
        # 6. Zone AI analysis
        # ------------------------------------------------------------------
        api_keys_pool = get_api_keys_pool()
        rear_result_front = analyze_rear_zone_with_ai(rear_crop_front, api_keys_pool, "FRONT")
        rear_result_back = analyze_rear_zone_with_ai(rear_crop_back, api_keys_pool, "BACK")
        front_result_front = analyze_front_zone_with_ai(front_crop_front, api_keys_pool, "FRONT")
        front_result_back = analyze_front_zone_with_ai(front_crop_back, api_keys_pool, "BACK")

        # ------------------------------------------------------------------
        # 7. Merge Results
        # ------------------------------------------------------------------
        if not isinstance(all_risks, list): all_risks = []
        def _existing_risk_views(risk_type_substr: str) -> set:
            return {str(r.get("view", "")).upper() for r in all_risks if risk_type_substr in str(r.get("risk_type", "")).upper()}

        for view_label, rear_result in [("FRONT", rear_result_front), ("BACK",  rear_result_back)]:
            if not isinstance(rear_result, dict): continue
            rear_zone_risk = str(rear_result.get("rear_zone_risk", "")).upper()
            confidence = str(rear_result.get("confidence", "LOW")).upper()
            
            # ยอมรับ Confidence ทั้ง HIGH, MEDIUM, LOW 
            if confidence in ("HIGH", "MEDIUM", "LOW"):
                if rear_zone_risk in ("REAR_EMPTY_RISK", "BOTH") and view_label not in _existing_risk_views("REAR_EMPTY"):
                    all_risks.append({"view": view_label, "risk_type": "REAR_EMPTY_RISK", "direction": "LONGITUDINAL", "lateral_side": "N/A", "reasoning": rear_result.get("reasoning", ""), "description": "พบความต่างระดับฝั่งประตูท้ายตู้ (วิเคราะห์จาก Zoom ท้ายตู้)", "box_2d": None})
                if rear_zone_risk in ("REAR_LATERAL_IMBALANCE", "BOTH") and view_label not in _existing_risk_views("REAR_LATERAL"):
                    all_risks.append({"view": view_label, "risk_type": "REAR_LATERAL_IMBALANCE", "direction": "LATERAL", "lateral_side": "N/A", "reasoning": rear_result.get("reasoning", ""), "description": "พบสินค้าท้ายตู้สูงต่ำไม่เท่ากัน (วิเคราะห์จาก Zoom ท้ายตู้)", "box_2d": None})

        for view_label, front_result in [("FRONT", front_result_front), ("BACK", front_result_back)]:
            if not isinstance(front_result, dict): continue
            if front_result.get("front_zone_risk", "").upper() == "FRONT_EMPTY_RISK" and view_label not in _existing_risk_views("FRONT_EMPTY"):
                all_risks.append({"view": view_label, "risk_type": "FRONT_EMPTY_RISK", "direction": "LONGITUDINAL", "lateral_side": "N/A", "reasoning": front_result.get("reasoning", ""), "description": "พบสินค้าต่างระดับฝั่งผนังหัวตู้ (วิเคราะห์จาก Zoom หัวตู้)", "box_2d": None})

        # ------------------------------------------------------------------
        # 8. Draw Boxes
        # ------------------------------------------------------------------
        draw = PIL.ImageDraw.Draw(img)
        detected_hazards = []
        RISK_COLORS = {"STEP_DOWN_RISK": "red", "REAR_EMPTY_RISK": "orange", "REAR_LATERAL_IMBALANCE": "deeppink", "FRONT_EMPTY_RISK": "yellow", "LATERAL_GAP_RISK": "cyan", "TALL_UNSTABLE_RISK": "magenta", "OVERHANG_RISK": "lime"}
        VALID_RISK_TYPES = set(RISK_COLORS.keys())

        for risk in all_risks:
            raw_risk_type = str(risk.get("risk_type", "")).upper().strip()
            view_name = str(risk.get("view", "GENERAL")).upper()
            matched_type = next((vrt for vrt in VALID_RISK_TYPES if vrt.replace("_RISK", "") in raw_risk_type or raw_risk_type in vrt), None)

            if raw_risk_type == "ERROR":
                detected_hazards.append({"title": "⚠️ ข้อผิดพลาด API", "detail": risk.get("description", "โปรดตรวจสอบโควตา Gemini API Keys"), "is_error": True})
                continue
            if not matched_type: continue

            risk_type = matched_type
            box = risk.get("box_2d") or risk.get("boundingBox") or risk.get("box")
            outline_color = RISK_COLORS.get(risk_type, "red")

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

                    if (abs_xmax - abs_xmin) / crop_w < 0.80 and (abs_ymax - abs_ymin) / crop_h < 0.80:
                        draw.rectangle([abs_xmin, abs_ymin, abs_xmax, abs_ymax], outline=outline_color, width=8)
                        drawn = True
                except Exception: pass

            if not drawn:
                fallback = _get_fallback_box(risk_type, view_name, layout, crop_w, crop_y_start, crop_h)
                if fallback: draw.rectangle(fallback, outline=outline_color, width=8)

            detected_hazards.append({"title": f"ความเสี่ยง ({view_name}): {risk_type}", "detail": generate_action_report(risk_type, risk.get("description", "")), "is_error": False})

        # ------------------------------------------------------------------
        # 9. Return Response
        # ------------------------------------------------------------------
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
