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
# Backend API สำหรับ AI Cargo Safety Checker (High-Precision v8)
# v8: รวม risk ทุกประเภทที่อยู่บริเวณเดียวกันเป็น COMBINED_AREA_RISK และวาดกรอบเดียว 2 สี
# v7: แก้ fallback box BACK view ใน TOP_BOTTOM + รวม REAR_EMPTY/REAR_LATERAL
# v6: deterministic red-arrow orientation + deterministic container-boundary detection
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


def get_api_keys_pool():
    global GLOBAL_API_KEYS
    if GLOBAL_API_KEYS:
        return GLOBAL_API_KEYS
    env_value = os.environ.get("GEMINI_API_KEYS", "")
    if env_value:
        keys = [k.strip() for k in env_value.split("|") if k.strip()]
        if keys:
            random.shuffle(keys)
            print(f"✅ Loaded {len(keys)} unique API key(s) into the pool.")
            GLOBAL_API_KEYS = keys
            return GLOBAL_API_KEYS
    print("❌ No Gemini API keys found.")
    return []


def generate_action_report(case_type, description="", sku_list=""):
    sku_line = f"\n   สินค้าที่พบบริเวณนี้: {sku_list}" if sku_list else ""
    actions = {
        "STEP_DOWN_RISK": (
            f"แจ้งเตือน: พบรอยต่างระดับระหว่างกองสินค้า{sku_line}\n"
            f"วิธีแก้ไข:\n"
            f"  • ติดตั้งแผ่นไม้กั้นขวางระหว่างกองสินค้าที่ต่างระดับ\n"
            f"  • รัดตรึงสินค้าให้ครบทุกจุด ป้องกันการล้มตะแคง"
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
            f"  • เสริมด้านที่ต่ำกว่าด้วยแผ่นรองหรือไม้อัดให้ระดับเท่ากัน\n"
            f"  • รัดตรึงแนวขวางป้องกันสินค้าล้มตะแคงเมื่อเปิดประตู"
        ),
        "REAR_COMBINED_RISK": (
            f"แจ้งเตือน: บริเวณประตูท้ายตู้พบทั้งพื้นที่ว่างหน้าประตู และสินค้าสูงต่ำไม่เท่ากันในแนวกว้างในจุดเดียวกัน{sku_line}\n"
            f"วิธีแก้ไข:\n"
            f"  • นำไม้อัดกั้นวางตั้งแนวตั้งชิดท้ายกองสินค้า เพื่ออุดช่องว่างหน้าประตู\n"
            f"  • เสริมด้านที่ต่ำกว่าด้วยแผ่นรองหรือไม้อัดให้ระดับเท่ากันทั้งซ้ายและขวา\n"
            f"  • รัดด้วยสายเบลท์หรือเชือกให้สินค้าอยู่กับที่ ป้องกันไถลออกและล้มตะแคงเมื่อเปิดประตู"
        ),
        "FRONT_EMPTY_RISK": (
            f"แจ้งเตือน: บริเวณผนังหัวตู้มีช่องว่าง สินค้าวางไม่ชิดผนัง{sku_line}\n"
            f"วิธีแก้ไข:\n"
            f"  • นำไม้อัดกั้นวางชิดผนังหัวตู้ เพื่ออุดช่องว่างระหว่างสินค้ากับผนัง\n"
            f"  • ตรวจสอบว่าสินค้าแต่ละกองชิดกันแน่น ไม่มีช่องให้สินค้าเลื่อน\n"
            f"  • รัดด้วยสายเบลท์หรือเชือกป้องกันสินค้าไถลมาข้างหน้าตอนเบรก"
        ),
        "LATERAL_GAP_RISK": (
            f"แจ้งเตือน: พบช่องว่างด้านข้างระหว่างกองสินค้า{sku_line}\n"
            f"วิธีแก้ไข:\n"
            f"  • ใส่ถุงลมหรือแผ่นรองกั้นด้านข้างระหว่างกองสินค้า\n"
            f"  • รัดตรึงป้องกันสินค้าเลื่อนตะแคงขณะเลี้ยว"
        ),
        "TALL_UNSTABLE_RISK": (
            f"แจ้งเตือน: พบสินค้าสูงโดดเดี่ยว ไม่มีของข้างค้ำยัน{sku_line}\n"
            f"วิธีแก้ไข:\n"
            f"  • ค้ำยันด้านข้างกองสูงด้วยไม้อัดหรือแผ่นรอง\n"
            f"  • รัดตรึงแนวขวาง ป้องกันล้มตะแคงระหว่างขนส่ง"
        ),
        "OVERHANG_RISK": (
            f"แจ้งเตือน: พบสินค้าชั้นบนยื่นพ้นขอบสินค้าชั้นล่าง{sku_line}\n"
            f"วิธีแก้ไข:\n"
            f"  • จัดเรียงใหม่ให้สินค้าชั้นบนไม่ยื่นพ้นฐานชั้นล่าง\n"
            f"  • ใส่แผ่นรองรับและรัดตรึงให้มั่นคง"
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
        is_landscape = page_width > page_height
        print(f"📄 Page size: {page_width:.0f}x{page_height:.0f} | Landscape={is_landscape}")
        if is_landscape:
            print("📐 Layout detected: LEFT_RIGHT (Landscape page)")
            return "LEFT_RIGHT"
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


# ---------------------------------------------------------------------------
# Arrow orientation detection
# ---------------------------------------------------------------------------

def _is_arrow_color(rgb):
    r, g, b = rgb
    return (r >= 190) and (40 <= g <= 140) and (40 <= b <= 140) and (abs(g - b) <= 45) and (r - g >= 70) and (r - b >= 70)


def _find_arrow_blobs(img):
    w, h = img.size
    px = img.convert("RGB").load()
    visited = bytearray(w * h)
    blobs = []
    for y in range(h):
        for x in range(w):
            idx = y * w + x
            if visited[idx]:
                continue
            if not _is_arrow_color(px[x, y]):
                visited[idx] = 1
                continue
            stack = [(x, y)]
            visited[idx] = 1
            pts = []
            while stack:
                cx, cy = stack.pop()
                pts.append((cx, cy))
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < w and 0 <= ny < h:
                        nidx = ny * w + nx
                        if not visited[nidx]:
                            visited[nidx] = 1
                            if _is_arrow_color(px[nx, ny]):
                                stack.append((nx, ny))
            if len(pts) < 30:
                continue
            xs = [p[0] for p in pts]
            ys = [p[1] for p in pts]
            bw = max(xs) - min(xs) + 1
            bh = max(ys) - min(ys) + 1
            fill_ratio = len(pts) / max(1, bw * bh)
            if 8 <= bw <= 50 and 8 <= bh <= 50 and fill_ratio >= 0.35:
                blobs.append({"cx": sum(xs) / len(xs), "cy": sum(ys) / len(ys), "size": len(pts)})
    return blobs


def detect_arrow_orientation(diagram_crop, layout, crop_w, crop_h):
    default_result = {
        "FRONT": {"rear_side": "LEFT", "source": "fallback", "arrow_count": 0},
        "BACK": {"rear_side": "RIGHT", "source": "fallback", "arrow_count": 0},
    }
    try:
        blobs = _find_arrow_blobs(diagram_crop)
        print(f"Arrow detection: found {len(blobs)} candidate arrow blob(s)")
        if layout == "TOP_BOTTOM":
            mid_y = crop_h // 2
            front_arrows = [b for b in blobs if b["cy"] < mid_y]
            back_arrows = [b for b in blobs if b["cy"] >= mid_y]
            front_center_x = crop_w / 2.0
            back_center_x = crop_w / 2.0
        else:
            mid_x = crop_w // 2
            front_arrows = [b for b in blobs if b["cx"] < mid_x]
            back_arrows = [b for b in blobs if b["cx"] >= mid_x]
            front_center_x = mid_x / 2.0
            back_center_x = (mid_x + crop_w) / 2.0
        result = {}
        for view_name, arrows, center_x in (("FRONT", front_arrows, front_center_x), ("BACK", back_arrows, back_center_x)):
            if arrows:
                highest = min(arrows, key=lambda b: b["cy"])
                side = "LEFT" if highest["cx"] < center_x else "RIGHT"
                result[view_name] = {"rear_side": side, "source": "detected", "arrow_count": len(arrows)}
            else:
                default_side = "LEFT" if view_name == "FRONT" else "RIGHT"
                result[view_name] = {"rear_side": default_side, "source": "fallback", "arrow_count": 0}
                print(f"WARNING: No arrows detected for {view_name} view - using fallback rear_side={default_side}")
        print(f"Detected orientation: FRONT rear={result['FRONT']['rear_side']} ({result['FRONT']['source']}), BACK rear={result['BACK']['rear_side']} ({result['BACK']['source']})")
        return result
    except Exception as e:
        print(f"WARNING: Arrow orientation detection failed ({e}), using default fallback (FRONT=LEFT, BACK=RIGHT)")
        return default_result


# ---------------------------------------------------------------------------
# Container boundary detection
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
                print(f"Container bounds detected for {view_name}: x=[{b['xmin']}-{b['xmax']}] y=[{b['ymin']}-{b['ymax']}] ({round(b['xmin']/crop_w*100,1)}%-{round(b['xmax']/crop_w*100,1)}% of crop_w)")
            else:
                print(f"WARNING: Could not detect container bounds for {view_name} - will fall back to fixed percentages")
        return result
    except Exception as e:
        print(f"WARNING: Container bounds detection failed ({e}), falling back to fixed percentages")
        return {"FRONT": None, "BACK": None}


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
        print(f"📦 SKU extracted: {sku_list}")
        return sku_list
    except Exception as e:
        print(f"⚠️ SKU extraction failed: {e}")
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
            print(f"⚠️ API Key index {current_index} failed: {last_err[:100]}")
            time.sleep(1)
            continue
    return {"rear_zone_risk": "ERROR", "front_zone_risk": "ERROR", "reasoning": last_err[:120], "confidence": "LOW"}


def analyze_rear_zone_with_ai(rear_crop, api_keys, view_label="UNKNOWN"):
    prompt = f"""
You are a Cargo Safety Inspector. This image is a cropped zoom of the DOOR END (REAR) zone of a container.
This is the {view_label} view.
YOUR ONLY TASK: Determine if there is a GENUINE safety risk at the door end.

STRICT RULES:
1. REAR_EMPTY_RISK: Flag ONLY if there is visibly significant empty floor space near the container door, OR cargo drops sharply leaving a dangerous gap.
2. REAR_LATERAL_IMBALANCE: Flag ONLY if cargo on left and right sides at the door zone is clearly and significantly uneven.
3. Do NOT flag the container wall as cargo.
4. If cargo fills the rear area reasonably well and is roughly level across width -> SAFE.
5. When in doubt, return SAFE.

Return ONLY JSON:
{{"rear_zone_risk":"REAR_EMPTY_RISK"|"REAR_LATERAL_IMBALANCE"|"BOTH"|"SAFE","reasoning":"...","confidence":"HIGH"|"MEDIUM"|"LOW"}}
"""
    return _call_gemini_json(prompt, rear_crop, api_keys)


def analyze_front_zone_with_ai(front_crop, api_keys, view_label="UNKNOWN"):
    prompt = f"""
You are a Cargo Safety Inspector. This image is a cropped zoom of the HEAD WALL (FRONT) zone of a container.
This is the {view_label} view. The solid panel is the container head wall and is NOT cargo.
YOUR TASK: Determine if there is a genuine FRONT_EMPTY_RISK.

STRICT RULES:
1. FRONT_EMPTY_RISK means a clearly visible large empty gap between front-most cargo and the head wall.
2. If cargo is stacked against or very close to the head wall -> SAFE.
3. If cargo heights vary but cargo is present and near the wall -> SAFE.
4. When in doubt, return SAFE.

Return ONLY JSON:
{{"front_zone_risk":"FRONT_EMPTY_RISK"|"SAFE","reasoning":"...","confidence":"HIGH"|"MEDIUM"|"LOW"}}
"""
    return _call_gemini_json(prompt, front_crop, api_keys)


def analyze_diagram_image_with_ai(diagram_image, layout="TOP_BOTTOM", orientation=None):
    global GLOBAL_KEY_INDEX
    api_keys = get_api_keys_pool()
    if not api_keys:
        return [{"risk_type": "ERROR", "description": "No Gemini API Keys found."}]
    orientation = orientation or {"FRONT": {"rear_side": "LEFT"}, "BACK": {"rear_side": "RIGHT"}}
    front_rear = orientation["FRONT"]["rear_side"]
    front_wall = "RIGHT" if front_rear == "LEFT" else "LEFT"
    back_rear = orientation["BACK"]["rear_side"]
    back_wall = "RIGHT" if back_rear == "LEFT" else "LEFT"
    layout_desc = "FRONT view is on the LEFT half; BACK view is on the RIGHT half." if layout == "LEFT_RIGHT" else "FRONT view is on the TOP half; BACK view is on the BOTTOM half."
    prompt = f"""
You are an expert Cargo Loading Safety Inspector analyzing a 3D cargo load plan.

CRITICAL DEFINITIONS:
- STEP_DOWN_RISK: Flag only sudden sharp unstable height drops between adjacent cargo stacks. Do not label the height drop at the very door end as STEP_DOWN_RISK.
- REAR_EMPTY_RISK: empty/dangerous gap near the door end.
- FRONT_EMPTY_RISK: empty/dangerous gap near the head wall.

VIEW LAYOUT: {layout_desc}
GROUND TRUTH ORIENTATION from deterministic pixel analysis:
- FRONT view: REAR/door side is {front_rear}; FRONT/head-wall side is {front_wall}.
- BACK view: REAR/door side is {back_rear}; FRONT/head-wall side is {back_wall}.

PLACEMENT RULES:
- REAR_EMPTY_RISK must be on the REAR/door side of that view.
- FRONT_EMPTY_RISK must be on the FRONT/head-wall side of that view.
- Never let any box_2d cross outside the actual cargo/container silhouette.
- MANDATORY: view must be FRONT or BACK only; never GENERAL.

Return ONLY a JSON array:
[
  {{"risk_type":"STEP_DOWN_RISK"|"REAR_EMPTY_RISK"|"REAR_LATERAL_IMBALANCE"|"FRONT_EMPTY_RISK"|"LATERAL_GAP_RISK"|"TALL_UNSTABLE_RISK"|"OVERHANG_RISK","view":"FRONT"|"BACK","box_2d":[ymin,xmin,ymax,xmax],"description":"..."}}
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
                print(f"⚠️ API Key index {current_index} failed in diagram analysis: {last_error_msg[:100]}")
                time.sleep(1)
                continue
        if pass_round == 0:
            time.sleep(2)
    return [{"risk_type": "ERROR", "description": f"AI Error: {last_error_msg[:120]}"}]


# ---------------------------------------------------------------------------
# Fallback boxes and same-area merge
# ---------------------------------------------------------------------------

def _mirror_box_in_range(box, lo, hi):
    x0, y0, x1, y1 = box
    return (lo + (hi - x1), y0, lo + (hi - x0), y1)


def _get_fallback_box(risk_type, view_label, layout, crop_w, crop_y_start, crop_h, orientation=None, container_bounds=None):
    vl = str(view_label).upper().strip()
    view_bounds = container_bounds.get(vl) if container_bounds else None
    default_rear_side = "LEFT" if vl == "FRONT" else "RIGHT"
    actual_rear_side = (orientation or {}).get(vl, {}).get("rear_side", default_rear_side)
    if view_bounds:
        origin_x = view_bounds["xmin"]
        origin_y = view_bounds["ymin"]
        ref_w = max(1, view_bounds["xmax"] - view_bounds["xmin"])
        ref_h = max(1, view_bounds["ymax"] - view_bounds["ymin"])
        using_detected_bounds = True
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
        using_detected_bounds = False

    def pct(px, py):
        return origin_x + int(ref_w * px), origin_y + int(ref_h * py)

    if layout == "TOP_BOTTOM":
        rear_frac, wall_frac = 0.38, 0.32
        y_pad = 0.08
        y0f, y1f = y_pad, 1.0 - y_pad
        mid_yf = y0f + (y1f - y0f) / 2
        if default_rear_side == "LEFT":
            rear_x0f, rear_x1f = 0.0, rear_frac
            wall_x0f, wall_x1f = 1.0 - wall_frac, 1.0
        else:
            rear_x0f, rear_x1f = 1.0 - rear_frac, 1.0
            wall_x0f, wall_x1f = 0.0, wall_frac
        zones_pct = {
            "REAR_EMPTY_RISK": (rear_x0f, y0f, rear_x1f, mid_yf),
            "REAR_LATERAL_IMBALANCE": (rear_x0f, mid_yf, rear_x1f, y1f),
            "REAR_COMBINED_RISK": (rear_x0f, y0f, rear_x1f, y1f),
            "FRONT_EMPTY_RISK": (wall_x0f, y0f, wall_x1f, y1f),
            "STEP_DOWN_RISK": (0.15, y0f, 0.85, y1f),
            "LATERAL_GAP_RISK": (0.20, y0f, 0.80, y1f),
            "TALL_UNSTABLE_RISK": (0.25, y0f, 0.75, y1f),
            "OVERHANG_RISK": (0.15, y0f, 0.85, mid_yf),
        }
        zp = zones_pct.get(risk_type)
        if zp is None:
            return None
        x0, y0 = pct(zp[0], zp[1])
        x1, y1 = pct(zp[2], zp[3])
        box = (x0, y0, x1, y1)
        if actual_rear_side != default_rear_side:
            box = _mirror_box_in_range(box, origin_x, origin_x + ref_w)
    else:
        mid_yf = 0.50
        if default_rear_side == "LEFT":
            rear_zone = (0.0, mid_yf, 0.55, 1.0)
            wall_zone = (0.30, 0.0, 1.0, mid_yf)
        else:
            rear_zone = (0.45, 0.0, 1.0, mid_yf)
            wall_zone = (0.0, mid_yf, 0.70, 1.0)
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
        if actual_rear_side != default_rear_side:
            box = _mirror_box_in_range(box, origin_x, origin_x + ref_w)
    source_label = "detected container bounds" if using_detected_bounds else "fixed-percentage fallback"
    print(f"Fallback box for {risk_type} ({vl}, {layout}): using {source_label}, default_rear_side={default_rear_side}, actual_rear_side={actual_rear_side}, box={box}")
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
    inter_x1 = max(x1a, x1b)
    inter_y1 = max(y1a, y1b)
    inter_x2 = min(x2a, x2b)
    inter_y2 = min(y2a, y2b)
    iw = max(0.0, inter_x2 - inter_x1)
    ih = max(0.0, inter_y2 - inter_y1)
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
        cx_bucket = int(((xmin + xmax) / 2) // 100)
        cy_bucket = int(((ymin + ymax) / 2) // 100)
        return (v, "BOX_ZONE", cx_bucket, cy_bucket)
    return (v, rt)


def _merge_same_area_risks(all_risks):
    """Merge any risks that belong to the same area into one COMBINED_AREA_RISK with one 2-color box."""
    groups = []  # each item: {key, items[(idx, risk)]}
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
            # Extra merge rule for BOX_ZONE: same view and sufficiently overlapping boxes.
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
        risk_types = []
        colors = []
        reason_parts = []
        description_parts = []
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
        boxes = [_normalized_box(r) for _, r in items]
        boxes = [b for b in boxes if b]
        if boxes and area_name == "BOX_ZONE":
            merged_box = [
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            ]
        merged_result.append({
            "view": view_label,
            "risk_type": "COMBINED_AREA_RISK",
            "fallback_risk_type": fallback_risk_type,
            "merged_risk_types": risk_types,
            "draw_colors": colors,
            "box_2d": merged_box,  # use union box for real overlapping BOX_ZONE; use fallback for semantic zones
            "direction": "COMBINED",
            "lateral_side": "N/A",
            "reasoning": " | ".join(reason_parts),
            "description": " / ".join(description_parts) if description_parts else "พบหลายความเสี่ยงในบริเวณเดียวกัน จึงรวมเป็นกรอบเดียว",
        })
        print(f"🔗 Merged same-area risks {risk_types} -> COMBINED_AREA_RISK for {view_label}, colors={colors}, fallback={fallback_risk_type}")
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
            print("🚨 DEBUG - RECEIVED DATA:", request.get_data(as_text=True)[:500])
            return ({"error": "No base64 data provided"}, 400, headers)
        base64_str = data.get("base64")
        if "," in base64_str:
            base64_str = base64_str.split(",", 1)[1]
        pdf_bytes = base64.b64decode(base64_str)

        layout = detect_page_layout_from_pdf(pdf_bytes)
        sku_list = extract_sku_from_pdf(pdf_bytes)
        sku_str = ", ".join(sku_list) if sku_list else ""

        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        page_index = 1 if len(doc) >= 2 else 0
        page = doc[page_index]
        pix = page.get_pixmap(dpi=180)
        mode = "RGBA" if pix.alpha else "RGB"
        img = PIL.Image.frombytes(mode, [pix.width, pix.height], pix.samples)
        width, height = img.size

        crop_y_start = int(height * 0.10)
        crop_y_end = int(height * 0.90)
        crop_w = int(width * 0.75)
        crop_h = crop_y_end - crop_y_start
        diagram_crop = img.crop((0, crop_y_start, crop_w, crop_y_end))

        orientation = detect_arrow_orientation(diagram_crop, layout, crop_w, crop_h)
        container_bounds = detect_container_bounds_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start)
        all_risks = analyze_diagram_image_with_ai(diagram_crop, layout=layout, orientation=orientation)
        if not isinstance(all_risks, list):
            all_risks = []

        front_rear_side = orientation["FRONT"]["rear_side"]
        back_rear_side = orientation["BACK"]["rear_side"]

        def _zoom_crop_ranges(view_bounds, rear_side, default_origin_x, default_ref_w):
            if view_bounds:
                ox, rw = view_bounds["xmin"], view_bounds["xmax"] - view_bounds["xmin"]
            else:
                ox, rw = default_origin_x, default_ref_w
            if rear_side == "LEFT":
                return (ox, ox + int(rw * 0.45)), (ox + int(rw * 0.55), ox + rw)
            return (ox + int(rw * 0.55), ox + rw), (ox, ox + int(rw * 0.45))

        if layout == "TOP_BOTTOM":
            half_h = crop_h // 2
            (fr_x0, fr_x1), (fw_x0, fw_x1) = _zoom_crop_ranges(container_bounds.get("FRONT"), front_rear_side, 0, crop_w)
            (br_x0, br_x1), (bw_x0, bw_x1) = _zoom_crop_ranges(container_bounds.get("BACK"), back_rear_side, 0, crop_w)
            rear_crop_front = img.crop((fr_x0, crop_y_start, fr_x1, crop_y_start + half_h))
            front_crop_front = img.crop((fw_x0, crop_y_start, fw_x1, crop_y_start + half_h))
            rear_crop_back = img.crop((br_x0, crop_y_start + half_h, br_x1, crop_y_end))
            front_crop_back = img.crop((bw_x0, crop_y_start + half_h, bw_x1, crop_y_end))
            print(f"TOP_BOTTOM crop - FRONT rear={front_rear_side} ({fr_x0}-{fr_x1}) | BACK rear={back_rear_side} ({br_x0}-{br_x1})")
        else:
            half_w = crop_w // 2
            (fr_x0, fr_x1), (fw_x0, fw_x1) = _zoom_crop_ranges(container_bounds.get("FRONT"), front_rear_side, 0, half_w)
            (br_x0, br_x1), (bw_x0, bw_x1) = _zoom_crop_ranges(container_bounds.get("BACK"), back_rear_side, half_w, crop_w - half_w)
            mid_h = crop_y_start + int(crop_h * 0.50)
            if front_rear_side == "LEFT":
                rear_crop_front = img.crop((fr_x0, mid_h, fr_x1, crop_y_end))
                front_crop_front = img.crop((fw_x0, crop_y_start, fw_x1, mid_h))
            else:
                rear_crop_front = img.crop((fr_x0, crop_y_start, fr_x1, mid_h))
                front_crop_front = img.crop((fw_x0, mid_h, fw_x1, crop_y_end))
            if back_rear_side == "LEFT":
                rear_crop_back = img.crop((br_x0, mid_h, br_x1, crop_y_end))
                front_crop_back = img.crop((bw_x0, crop_y_start, bw_x1, mid_h))
            else:
                rear_crop_back = img.crop((br_x0, crop_y_start, br_x1, mid_h))
                front_crop_back = img.crop((bw_x0, mid_h, bw_x1, crop_y_end))
            print(f"LEFT_RIGHT crop - FRONT rear={front_rear_side} ({fr_x0}-{fr_x1}) | BACK rear={back_rear_side} ({br_x0}-{br_x1})")

        api_keys_pool = get_api_keys_pool()
        rear_result_front = analyze_rear_zone_with_ai(rear_crop_front, api_keys_pool, "FRONT")
        rear_result_back = analyze_rear_zone_with_ai(rear_crop_back, api_keys_pool, "BACK")
        front_result_front = analyze_front_zone_with_ai(front_crop_front, api_keys_pool, "FRONT")
        front_result_back = analyze_front_zone_with_ai(front_crop_back, api_keys_pool, "BACK")

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

        for view_label, rear_result in (("FRONT", rear_result_front), ("BACK", rear_result_back)):
            if not isinstance(rear_result, dict):
                continue
            rear_zone_risk = str(rear_result.get("rear_zone_risk", "")).upper()
            confidence = str(rear_result.get("confidence", "LOW")).upper()
            if rear_zone_risk in ("REAR_EMPTY_RISK", "BOTH"):
                if confidence in ("HIGH", "MEDIUM") and view_label not in _existing_risk_views("REAR_EMPTY"):
                    all_risks.append({"view": view_label, "risk_type": "REAR_EMPTY_RISK", "direction": "LONGITUDINAL", "lateral_side": "N/A", "reasoning": rear_result.get("reasoning", ""), "description": "พบความต่างระดับฝั่งประตูท้ายตู้ (วิเคราะห์จาก Zoom ท้ายตู้)", "box_2d": None})
                else:
                    print(f"⚠️ Skipping REAR_EMPTY ({view_label}) - confidence={confidence}")
            if rear_zone_risk in ("REAR_LATERAL_IMBALANCE", "BOTH"):
                if confidence == "HIGH" and view_label not in _existing_risk_views("REAR_LATERAL"):
                    all_risks.append({"view": view_label, "risk_type": "REAR_LATERAL_IMBALANCE", "direction": "LATERAL", "lateral_side": "N/A", "reasoning": rear_result.get("reasoning", ""), "description": "พบสินค้าท้ายตู้สูงต่ำไม่เท่ากัน (วิเคราะห์จาก Zoom ท้ายตู้)", "box_2d": None})
                else:
                    print(f"⚠️ Skipping REAR_LATERAL ({view_label}) - confidence={confidence}")

        for view_label, front_result in (("FRONT", front_result_front), ("BACK", front_result_back)):
            if not isinstance(front_result, dict):
                continue
            confidence = str(front_result.get("confidence", "LOW")).upper()
            if confidence != "HIGH":
                print(f"⚠️ Skipping front zoom ({view_label}) - confidence={confidence} (need HIGH)")
                continue
            if front_result.get("front_zone_risk", "").upper() == "FRONT_EMPTY_RISK" and view_label not in _existing_risk_views("FRONT_EMPTY"):
                all_risks.append({"view": view_label, "risk_type": "FRONT_EMPTY_RISK", "direction": "LONGITUDINAL", "lateral_side": "N/A", "reasoning": front_result.get("reasoning", ""), "description": "พบสินค้าต่างระดับฝั่งผนังหัวตู้ (วิเคราะห์จาก Zoom หัวตู้)", "box_2d": None})

        all_risks = _merge_same_area_risks(all_risks)

        draw = PIL.ImageDraw.Draw(img)
        detected_hazards = []
        reported_risk_keys = set()

        for risk in all_risks:
            raw_risk_type = str(risk.get("risk_type", "")).upper().strip()
            view_name = _normalize_view(risk.get("view", "GENERAL"))
            if raw_risk_type in ("REAR_COMBINED_RISK", "COMBINED_AREA_RISK"):
                matched_type = raw_risk_type
            elif raw_risk_type == "ERROR":
                detected_hazards.append({"title": "⚠️ ข้อผิดพลาด API", "detail": risk.get("description", "โปรดตรวจสอบโควตา Gemini API Keys"), "is_error": True})
                continue
            else:
                matched_type = next((vrt for vrt in VALID_RISK_TYPES if vrt not in ("REAR_COMBINED_RISK", "COMBINED_AREA_RISK") and (vrt.replace("_RISK", "") in raw_risk_type or raw_risk_type in vrt)), None)
            if not matched_type:
                continue

            risk_type = matched_type
            fallback_risk_type = risk.get("fallback_risk_type", risk_type)
            draw_colors = risk.get("draw_colors", None)
            outline_color = RISK_COLORS.get(risk_type, "red")
            box = risk.get("box_2d") or risk.get("boundingBox") or risk.get("box")
            resolved_view = view_name if view_name != "GENERAL" else "FRONT"
            drawn = False

            if box and isinstance(box, list) and len(box) == 4:
                try:
                    ymin, xmin, ymax, xmax = map(float, box)
                    if max(ymin, xmin, ymax, xmax) <= 1.0:
                        ymin, xmin, ymax, xmax = ymin * 1000, xmin * 1000, ymax * 1000, xmax * 1000
                    abs_xmin = max(0, min(int(xmin * crop_w / 1000.0), crop_w - 1))
                    abs_xmax = max(abs_xmin + 1, min(int(xmax * crop_w / 1000.0), crop_w))
                    abs_ymin = max(crop_y_start, min(int(crop_y_start + (ymin * crop_h / 1000.0)), crop_y_end - 1))
                    abs_ymax = max(abs_ymin + 1, min(int(crop_y_start + (ymax * crop_h / 1000.0)), crop_y_end))
                    box_center_x = (abs_xmin + abs_xmax) / 2
                    box_center_y = (abs_ymin + abs_ymax) / 2

                    half_w_local = crop_w // 2
                    half_h_local = crop_h // 2
                    mid_y_local = crop_y_start + half_h_local
                    resolved_view = view_name
                    if view_name == "GENERAL":
                        if layout == "LEFT_RIGHT":
                            resolved_view = "FRONT" if box_center_x < crop_w * 0.50 else "BACK"
                        else:
                            resolved_view = "FRONT" if box_center_y < mid_y_local else "BACK"
                        print(f"GENERAL -> resolved to {resolved_view} ({layout}, box_center=({box_center_x:.0f},{box_center_y:.0f}))")

                    default_rear_side = "LEFT" if resolved_view == "FRONT" else "RIGHT"
                    actual_rear_side = orientation.get(resolved_view, {}).get("rear_side", default_rear_side)
                    view_bounds = container_bounds.get(resolved_view)
                    if view_bounds:
                        vb_xmin, vb_xmax = view_bounds["xmin"], view_bounds["xmax"]
                        vb_ymin, vb_ymax = view_bounds["ymin"], view_bounds["ymax"]
                        vb_w = max(1, vb_xmax - vb_xmin)
                        vb_h = max(1, vb_ymax - vb_ymin)
                        margin_x = vb_w * 0.10
                        margin_y = vb_h * 0.10
                        cargo_zone_ymin = vb_ymin - margin_y
                        cargo_zone_ymax = vb_ymax + margin_y
                        if fallback_risk_type in ("REAR_EMPTY_RISK", "REAR_COMBINED_RISK"):
                            if actual_rear_side == "LEFT":
                                cargo_zone_xmin, cargo_zone_xmax = vb_xmin - margin_x, vb_xmin + vb_w * 0.45
                            else:
                                cargo_zone_xmin, cargo_zone_xmax = vb_xmax - vb_w * 0.45, vb_xmax + margin_x
                        elif fallback_risk_type == "FRONT_EMPTY_RISK":
                            if actual_rear_side == "LEFT":
                                cargo_zone_xmin, cargo_zone_xmax = vb_xmax - vb_w * 0.40, vb_xmax + margin_x
                            else:
                                cargo_zone_xmin, cargo_zone_xmax = vb_xmin - margin_x, vb_xmin + vb_w * 0.40
                        else:
                            cargo_zone_xmin, cargo_zone_xmax = vb_xmin - margin_x, vb_xmax + margin_x
                    else:
                        if layout == "TOP_BOTTOM":
                            if resolved_view == "FRONT":
                                cargo_zone_ymin = crop_y_start + crop_h * 0.03
                                cargo_zone_ymax = mid_y_local
                            else:
                                cargo_zone_ymin = mid_y_local
                                cargo_zone_ymax = crop_y_end - crop_h * 0.03
                        else:
                            cargo_zone_ymin = crop_y_start + crop_h * 0.05
                            cargo_zone_ymax = crop_y_end - crop_h * 0.05
                        if layout == "TOP_BOTTOM":
                            if fallback_risk_type in ("REAR_EMPTY_RISK", "REAR_COMBINED_RISK"):
                                if actual_rear_side == "LEFT":
                                    cargo_zone_xmin, cargo_zone_xmax = 0, crop_w * 0.45
                                else:
                                    cargo_zone_xmin, cargo_zone_xmax = crop_w * 0.55, crop_w * 0.97
                            elif fallback_risk_type == "FRONT_EMPTY_RISK":
                                if actual_rear_side == "LEFT":
                                    cargo_zone_xmin, cargo_zone_xmax = crop_w * 0.55, crop_w * 0.97
                                else:
                                    cargo_zone_xmin, cargo_zone_xmax = 0, crop_w * 0.45
                            else:
                                cargo_zone_xmin, cargo_zone_xmax = 0, crop_w * 0.97
                        else:
                            if fallback_risk_type == "FRONT_EMPTY_RISK":
                                if resolved_view == "FRONT":
                                    d_xmin, d_xmax = crop_w * 0.28, crop_w * 0.50
                                else:
                                    d_xmin, d_xmax = crop_w * 0.50, crop_w * 0.75
                            elif fallback_risk_type in ("REAR_EMPTY_RISK", "REAR_COMBINED_RISK"):
                                if resolved_view == "FRONT":
                                    d_xmin, d_xmax = 0, crop_w * 0.28
                                else:
                                    d_xmin, d_xmax = crop_w * 0.72, crop_w * 0.97
                            else:
                                d_xmin, d_xmax = 0, crop_w * 0.97
                            if actual_rear_side != default_rear_side:
                                lo, hi = (0, half_w_local) if resolved_view == "FRONT" else (half_w_local, crop_w)
                                cargo_zone_xmin, cargo_zone_xmax = lo + (hi - d_xmax), lo + (hi - d_xmin)
                            else:
                                cargo_zone_xmin, cargo_zone_xmax = d_xmin, d_xmax

                    if not (cargo_zone_xmin <= box_center_x <= cargo_zone_xmax) or not (cargo_zone_ymin < box_center_y < cargo_zone_ymax):
                        print(f"⚠️ box_2d center ({box_center_x:.0f}, {box_center_y:.0f}) out of cargo zone - fallback for {risk_type}")
                        raise ValueError("box out of cargo zone")
                    box_w_ratio = (abs_xmax - abs_xmin) / crop_w
                    box_h_ratio = (abs_ymax - abs_ymin) / crop_h
                    box_too_small = box_w_ratio < 0.03 or box_h_ratio < 0.03
                    if not box_too_small and box_w_ratio < 0.80 and box_h_ratio < 0.80:
                        _draw_single_or_dual_rectangle(draw, [abs_xmin, abs_ymin, abs_xmax, abs_ymax], outline_color, draw_colors)
                        drawn = True
                    else:
                        raise ValueError("box too small or too large")
                except Exception:
                    pass

            if not drawn:
                fallback = _get_fallback_box(fallback_risk_type, resolved_view, layout, crop_w, crop_y_start, crop_h, orientation=orientation, container_bounds=container_bounds)
                if fallback:
                    _draw_single_or_dual_rectangle(draw, fallback, outline_color, draw_colors)
                    drawn = True
            if not drawn:
                print(f"⚠️ Could not draw box for {risk_type} ({resolved_view}) - no valid coords or fallback")

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
        print("🚨 CRITICAL ERROR DETAILS:\n", err_trace)
        gc.collect()
        return ({"error": str(e), "trace": err_trace[-500:]}, 500, headers)
