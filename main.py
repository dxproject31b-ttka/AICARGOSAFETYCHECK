import base64
import io
import json
import os
import time
import gc
import traceback
from typing import List
from typing_extensions import TypedDict
from pdf2image import convert_from_bytes
import PIL.Image
import PIL.ImageDraw
import PIL.ImageStat
import functions_framework
import google.generativeai as genai

# ---------------------------------------------------------------------------
# Backend API สำหรับ AI Cargo Safety Checker ( High-Precision v4 )
# [v4] - แก้ไขชื่อโมเดลเป็น gemini-3.6-flash
# [v4] - ใช้ TypedDict และ response_schema เพื่อบังคับโครงสร้าง JSON 100%
# [v4] - เพิ่มระบบจัดการ Memory เพื่อความเสถียรบน Cloud Run
# ---------------------------------------------------------------------------

# ============================================================
# SECTION 1 — SCHEMAS สำหรับบังคับ OUTPUT JSON
# ============================================================

class RearZoneRiskSchema(TypedDict):
    rear_zone_risk: str
    reasoning: str
    confidence: str
    lateral_side: str

class DiagramRiskSchema(TypedDict):
    view: str
    risk_type: str
    direction: str
    lateral_side: str
    zone2_baseline: str
    reasoning: str
    description: str
    box_2d: List[float]


# ============================================================
# SECTION 2 — UTILITY: API KEYS
# ============================================================

def get_api_keys_pool():
    keys = []
    for env_k, env_v in os.environ.items():
        k_upper = env_k.upper().strip()
        if ("GEMINI" in k_upper or "API_KEY" in k_upper) and env_v and env_v.strip():
            extracted_keys = [k.strip() for k in env_v.split(",") if k.strip()]
            keys.extend(extracted_keys)
            
    keys = list(set(keys))
    if keys:
        print(f"✅ Loaded {len(keys)} unique API key(s) into the pool.")
        return keys
    
    print("❌ No Gemini API keys found.")
    return []


# ============================================================
# SECTION 3 — UTILITY: ACTION REPORTS (7 risk types)
# ============================================================

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


# ============================================================
# SECTION 4 — LAYOUT DETECTOR
# ============================================================

def detect_page_layout(img: PIL.Image.Image, crop_y_start: int, crop_y_end: int) -> str:
    try:
        crop_w = img.size[0]
        crop_h = crop_y_end - crop_y_start
        band_thickness_h = max(1, int(crop_h * 0.08))
        band_thickness_v = max(1, int(crop_w * 0.08))
        center_y = crop_y_start + crop_h // 2
        center_x = crop_w // 2

        h_band = img.crop((0, center_y - band_thickness_h // 2, crop_w, center_y + band_thickness_h // 2)).convert("L")
        h_brightness = PIL.ImageStat.Stat(h_band).mean[0]

        v_band = img.crop((center_x - band_thickness_v // 2, crop_y_start, center_x + band_thickness_v // 2, crop_y_end)).convert("L")
        v_brightness = PIL.ImageStat.Stat(v_band).mean[0]

        if v_brightness > h_brightness + 8:
            return "LEFT_RIGHT"
        elif h_brightness > v_brightness + 8:
            return "TOP_BOTTOM"
        return "TOP_BOTTOM"
    except Exception as e:
        print(f"⚠️ Layout detection failed ({e}), defaulting to TOP_BOTTOM")
        return "TOP_BOTTOM"


# ============================================================
# SECTION 5 — AI: REAR ZONE CROP ANALYSIS
# ============================================================

def analyze_rear_zone_with_ai(rear_crop: PIL.Image.Image, api_keys: list, view_label: str = "UNKNOWN") -> dict:
    rear_prompt = f"""
You are a Cargo Safety Inspector. This image is a ZOOMED-IN CROP of the DOOR END (REAR) zone of a 3D isometric container loading diagram. This is the {view_label} view.
Detect possible risks:
A: REAR_EMPTY_RISK (longitudinal shortage)
B: REAR_LATERAL_IMBALANCE (lateral height difference at rear)
CRITICAL: Color does NOT mean height difference. Normal stagger is NOT a risk.
"""
    last_err = ""
    for current_key in api_keys:
        try:
            genai.configure(api_key=current_key)
            model = genai.GenerativeModel(
                model_name="gemini-3.6-flash",
                generation_config={
                    "response_mime_type": "application/json",
                    "response_schema": RearZoneRiskSchema
                }
            )
            response = model.generate_content([rear_prompt, rear_crop])
            # ใช้ JSON loads โดยตรง ไม่ต้องผ่าน clean_json_response แล้ว
            return json.loads(response.text)
        except Exception as e:
            last_err = str(e)
            continue

    return {"rear_zone_risk": "ERROR", "reasoning": last_err[:120], "confidence": "LOW", "lateral_side": "N/A"}


# ============================================================
# SECTION 6 — AI: FULL DIAGRAM ANALYSIS
# ============================================================

def analyze_diagram_image_with_ai(diagram_image: PIL.Image.Image):
    api_keys = get_api_keys_pool()
    if not api_keys:
        return [{"risk_type": "ERROR", "description": "ไม่พบตัวแปร GEMINI_API_KEYS ในระบบ"}]

    prompt = """
You are an expert Cargo Loading Safety Inspector. Detect ALL physical risks of cargo shifting, sliding, tipping, or collapsing.
CRITICAL ANTI-FALSE-POSITIVE RULES:
1. Box color = SKU type identity ONLY. Do NOT report risk based on color.
2. Normal horizontal stagger/offset is NOT a risk.
SCAN FOR: REAR_EMPTY_RISK, REAR_LATERAL_IMBALANCE, FRONT_EMPTY_RISK, STEP_DOWN_RISK, LATERAL_GAP_RISK, TALL_UNSTABLE_RISK, OVERHANG_RISK.
Return an array of risks. If no risks, return an empty array [].
"""
    last_error_msg = ""
    for pass_round in range(2):
        for current_key in api_keys:
            try:
                genai.configure(api_key=current_key)
                model = genai.GenerativeModel(
                    model_name="gemini-3.6-flash",
                    generation_config={
                        "response_mime_type": "application/json",
                        "response_schema": list[DiagramRiskSchema]
                    }
                )
                response = model.generate_content([prompt, diagram_image])
                risks = json.loads(response.text)
                
                # ป้องกันกรณี AI ตอบเป็น null หรือ dict ตัวเดียว
                if not risks:
                    return []
                if isinstance(risks, dict):
                    return [risks]
                return risks

            except Exception as e:
                last_error_msg = str(e)
                if "429" in last_error_msg or "quota" in last_error_msg.lower():
                    continue # สลับ Key ถ้าติด Rate Limit
                continue
        if pass_round == 0:
            time.sleep(10)

    return [{"risk_type": "ERROR", "description": f"AI Error: {last_error_msg[:120]}"}]


# ============================================================
# SECTION 7 — MAIN CLOUD FUNCTION HANDLER
# ============================================================

@functions_framework.http
def process_request(request):
    if request.method == 'OPTIONS':
        headers = {'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'POST', 'Access-Control-Allow-Headers': 'Content-Type, x-goog-api-key', 'Access-Control-Max-Age': '3600'}
        return ('', 204, headers)

    headers = {'Access-Control-Allow-Origin': '*'}
    
    # ตัวแปรสำหรับการจัดการ Memory
    img = None
    diagram_crop = None
    rear_crop_front = None
    rear_crop_back = None

    try:
        data = request.get_json(silent=True) or {}
        if not data or 'base64' not in data:
            return ({"error": "No base64 data provided"}, 400, headers)

        base64_str = data.get('base64').split(",")[1] if "," in data.get('base64') else data.get('base64')
        pdf_bytes = base64.b64decode(base64_str)

        try:
            pages = convert_from_bytes(pdf_bytes, first_page=2, last_page=2, dpi=180)
        except Exception:
            try:
                pages = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=180)
            except Exception:
                pages = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=150)

        if not pages:
            return ({"error": "Cannot render PDF page data"}, 400, headers)

        img = pages[0]
        width, height = img.size

        crop_y_start, crop_y_end = int(height * 0.10), int(height * 0.90)
        crop_w, crop_h = width, crop_y_end - crop_y_start
        diagram_crop = img.crop((0, crop_y_start, crop_w, crop_y_end))

        all_risks = analyze_diagram_image_with_ai(diagram_crop)
        layout = detect_page_layout(img, crop_y_start, crop_y_end)

        if layout == "TOP_BOTTOM":
            half_h = crop_h // 2
            rear_crop_front = img.crop((0, crop_y_start, int(crop_w * 0.38), crop_y_start + half_h))
            rear_crop_back = img.crop((int(crop_w * 0.62), crop_y_start + half_h, crop_w, crop_y_end))
        else:
            rear_crop_front = img.crop((0, crop_y_start, int(crop_w * 0.22), crop_y_end))
            rear_crop_back = img.crop((int(crop_w * 0.78), crop_y_start, crop_w, crop_y_end))

        api_keys_for_rear = get_api_keys_pool()
        rear_result_front = analyze_rear_zone_with_ai(rear_crop_front, api_keys_for_rear, "FRONT")
        rear_result_back = analyze_rear_zone_with_ai(rear_crop_back, api_keys_for_rear, "BACK")

        if not isinstance(all_risks, list):
            all_risks = []

        def _existing_risk_views(risk_type_substr: str) -> set:
            return {str(r.get("view", "")).upper() for r in all_risks if risk_type_substr in str(r.get("risk_type", "")).upper()}

        for view_label, rear_result in [("FRONT", rear_result_front), ("BACK", rear_result_back)]:
            if not isinstance(rear_result, dict):
                continue

            rear_zone_risk = str(rear_result.get("rear_zone_risk", "")).upper()
            confidence = str(rear_result.get("confidence", "LOW")).upper()
            reasoning = rear_result.get("reasoning", "")

            if confidence not in ("HIGH", "MEDIUM"):
                continue

            if rear_zone_risk in ("REAR_EMPTY_RISK", "BOTH") and view_label not in _existing_risk_views("REAR_EMPTY"):
                all_risks.append({"view": view_label, "risk_type": "REAR_EMPTY_RISK", "direction": "LONGITUDINAL", "lateral_side": "N/A", "zone2_baseline": "Assessed from rear zone crop independently.", "reasoning": f"[Rear Crop Confirm] {reasoning}", "description": "พบสินค้าฝั่งประตูท้ายตู้ต่ำกว่ากลางตู้ หรือเห็นพื้นโล่ง (ยืนยันจากการวิเคราะห์ภาพ Zoom ท้ายตู้)", "box_2d": None})

            if rear_zone_risk in ("REAR_LATERAL_IMBALANCE", "BOTH") and view_label not in _existing_risk_views("REAR_LATERAL"):
                all_risks.append({"view": view_label, "risk_type": "REAR_LATERAL_IMBALANCE", "direction": "LATERAL", "lateral_side": rear_result.get("lateral_side", "N/A"), "zone2_baseline": "Assessed from rear zone crop independently.", "reasoning": f"[Rear Crop Confirm] {reasoning}", "description": "พบสินค้าท้ายตู้สูงต่ำไม่เท่ากันในแนวกว้าง (ยืนยันจากการวิเคราะห์ภาพ Zoom ท้ายตู้)", "box_2d": None})

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
            if matched_type is None:
                continue

            desc = risk.get("description", "พบความไม่สมดุลของสินค้า")
            box = risk.get("box_2d")

            if box and isinstance(box, list) and len(box) == 4:
                try:
                    ymin, xmin, ymax, xmax = map(float, box)
                    if max(ymin, xmin, ymax, xmax) <= 1.0 and max(ymin, xmin, ymax, xmax) > 0:
                        ymin, xmin, ymax, xmax = ymin * 1000, xmin * 1000, ymax * 1000, xmax * 1000
                    abs_xmin, abs_xmax = int(xmin * crop_w / 1000.0), int(xmax * crop_w / 1000.0)
                    abs_ymin, abs_ymax = int(crop_y_start + (ymin * crop_h / 1000.0)), int(crop_y_start + (ymax * crop_h / 1000.0))
                    draw.rectangle([abs_xmin, abs_ymin, abs_xmax, abs_ymax], outline=RISK_COLORS.get(matched_type, "red"), width=8)
                except Exception:
                    pass

            dir_label = f" [{risk.get('direction', '')}]" if risk.get("direction") else ""
            side_label = f" ({risk.get('lateral_side')})" if risk.get("lateral_side") and risk.get("lateral_side") != "N/A" else ""
            detected_hazards.append({"title": f"ความเสี่ยง ({view_name}){dir_label}{side_label}: {matched_type}", "detail": generate_action_report(matched_type, desc), "is_error": False})

        real_hazards = [h for h in detected_hazards if not h.get("is_error")]
        error_hazards = [h for h in detected_hazards if h.get("is_error")]
        sep = "\n\n" + "-" * 50 + "\n\n"

        if real_hazards:
            status_text, action_text, hazard_count = f"พบจุดเสี่ยงอันตราย ({len(real_hazards)} จุด)", sep.join(f"[{h['title']}]\n{h['detail']}" for h in real_hazards), len(real_hazards)
        elif error_hazards:
            status_text, action_text, hazard_count = "เกิดข้อผิดพลาดในการวิเคราะห์ AI", sep.join(f"[{h['title']}]\n{h['detail']}" for h in error_hazards), 0
        else:
            status_text, action_text, hazard_count = "ปลอดภัย (SAFE)", generate_action_report("SAFE", ""), 0

        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=80)
        processed_image_url = f"data:image/jpeg;base64,{base64.b64encode(buffered.getvalue()).decode('utf-8')}"

        # 🧹 เคลียร์ Memory ก่อนคืนค่า
        del img, diagram_crop, rear_crop_front, rear_crop_back, pages
        gc.collect()

        return ({"status": status_text, "hazardCount": hazard_count, "layout": layout, "actionRequired": action_text, "processedImageUrl": processed_image_url}, 200, headers)

    except Exception as e:
        # กรณีเกิด Error ให้เคลียร์ Memory ด้วยเช่นกัน
        if 'img' in locals() and img is not None: del img
        if 'diagram_crop' in locals() and diagram_crop is not None: del diagram_crop
        gc.collect()
        return ({"error": str(e), "trace": traceback.format_exc()[-500:]}, 500, headers)
