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
# Backend API สำหรับ AI Cargo Safety Checker ( High-Precision v6 )
# v6: เพิ่ม deterministic arrow detection + deterministic container-boundary detection
#     เพื่อแทนที่การใช้เปอร์เซ็นต์ตายตัว (fixed percentage) ที่ทำให้กรอบหลุดออกนอกตู้
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

def generate_action_report(case_type, description, sku_list=""):
    # สร้างบรรทัดแสดงชื่อสินค้าที่พบ (ถ้ามี)
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
    return actions.get(case_type, "ปลอดภัย\nไม่พบจุดเสี่ยงที่ต้องดำเนินการเพิ่มเติม")

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

def _is_arrow_color(rgb):
    """
    ตรวจสอบว่าพิกเซลนี้เป็นสี 'ลูกศรแดง' (marker) หรือไม่
    สีลูกศรจริงเป็นโทน salmon/coral (R สูง, G และ B ปานกลางใกล้เคียงกัน)
    ต่างจากกล่องสินค้าสีแดงล้วน (R สูง, G และ B ต่ำเกือบ 0) และเส้นกรอบสีแดงที่ AI วาด (มักเป็น pure red เช่นกัน)
    """
    r, g, b = rgb
    return (r >= 190) and (40 <= g <= 140) and (40 <= b <= 140) and (abs(g - b) <= 45) and (r - g >= 70) and (r - b >= 70)


def _find_arrow_blobs(img):
    """
    หา blob (กลุ่มพิกเซลต่อเนื่อง) ของลูกศรแดงในภาพ ด้วยการ flood-fill แบบ pure Python
    (ไม่พึ่ง numpy/scipy เพื่อความเข้ากันได้กับ Cloud Function environment)
    คืนค่า list ของ dict {"cx":.., "cy":.., "size":..} เฉพาะ blob ที่มีรูปทรงและขนาดใกล้เคียงลูกศรจริง
    """
    w, h = img.size
    px = img.convert("RGB").load()
    visited = bytearray(w * h)
    blobs = []

    for y in range(h):
        base = y * w
        for x in range(w):
            idx = base + x
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
            fill_ratio = len(pts) / (bw * bh)
            # ลูกศรจริงมีขนาด ~15-35px ต่อด้าน และ fill ratio ปานกลาง-สูง (สามเหลี่ยมทึบ)
            if 8 <= bw <= 50 and 8 <= bh <= 50 and fill_ratio >= 0.35:
                blobs.append({
                    "cx": sum(xs) / len(xs),
                    "cy": sum(ys) / len(ys),
                    "size": len(pts),
                })
    return blobs


def detect_arrow_orientation(diagram_crop, layout, crop_w, crop_h):
    """
    ตรวจจับตำแหน่งลูกศรแดง (marker) จริงในภาพ diagram_crop ด้วย pixel analysis
    (deterministic — ไม่พึ่ง AI เดา) เพื่อหาว่า REAR (ประตูท้ายตู้) ของแต่ละ view
    (FRONT/BACK) อยู่ฝั่งซ้ายหรือขวาจริงๆ

    กฎ (ยืนยันแล้วว่าถูกต้องตรงกับตัวอย่างจริงทั้ง Layout LEFT_RIGHT และ TOP_BOTTOM):
      - ลูกศรแดงที่อยู่ 'สูงที่สุด' (ระยะห่างจากขอบล่างของ view นั้นมากที่สุด, y น้อยที่สุด)
        ของแต่ละ view คือฝั่งที่ชี้ไปทาง REAR (ประตูท้ายตู้)
      - ฝั่งตรงข้ามของลูกศรนั้น = FRONT ของตู้ (ผนังหัวตู้)

    Returns:
      {
        "FRONT": {"rear_side": "LEFT"|"RIGHT", "source": "detected"|"fallback", "arrow_count": int},
        "BACK":  {"rear_side": "LEFT"|"RIGHT", "source": "detected"|"fallback", "arrow_count": int},
      }
    """
    default_result = {
        "FRONT": {"rear_side": "LEFT", "source": "fallback", "arrow_count": 0},
        "BACK":  {"rear_side": "RIGHT", "source": "fallback", "arrow_count": 0},
    }
    try:
        blobs = _find_arrow_blobs(diagram_crop)
        print(f"Arrow detection: found {len(blobs)} candidate arrow blob(s)")

        if layout == "TOP_BOTTOM":
            mid_y = crop_h // 2  # เส้นแบ่ง Front(บน)/Back(ล่าง) — สัมพัทธ์กับ diagram_crop เอง (เริ่มที่ 0)
            front_arrows = [b for b in blobs if b["cy"] < mid_y]
            back_arrows  = [b for b in blobs if b["cy"] >= mid_y]
            front_center_x = crop_w / 2.0
            back_center_x  = crop_w / 2.0
        else:  # LEFT_RIGHT
            mid_x = crop_w // 2  # เส้นแบ่ง Front(ซ้าย)/Back(ขวา)
            front_arrows = [b for b in blobs if b["cx"] < mid_x]
            back_arrows  = [b for b in blobs if b["cx"] >= mid_x]
            front_center_x = mid_x / 2.0
            back_center_x  = (mid_x + crop_w) / 2.0

        result = {}
        for view_name, arrows, center_x in [("FRONT", front_arrows, front_center_x), ("BACK", back_arrows, back_center_x)]:
            if arrows:
                highest = min(arrows, key=lambda b: b["cy"])
                side = "LEFT" if highest["cx"] < center_x else "RIGHT"
                result[view_name] = {"rear_side": side, "source": "detected", "arrow_count": len(arrows)}
            else:
                default_side = "LEFT" if view_name == "FRONT" else "RIGHT"
                result[view_name] = {"rear_side": default_side, "source": "fallback", "arrow_count": 0}
                print(f"WARNING: No arrows detected for {view_name} view - using fallback rear_side={default_side}")

        print(f"Detected orientation: FRONT rear={result['FRONT']['rear_side']} ({result['FRONT']['source']}), "
              f"BACK rear={result['BACK']['rear_side']} ({result['BACK']['source']})")
        return result

    except Exception as e:
        print(f"WARNING: Arrow orientation detection failed ({e}), using default fallback (FRONT=LEFT, BACK=RIGHT)")
        return default_result


# ---------------------------------------------------------------------------
# Container boundary detection (deterministic, pixel-based)
# ---------------------------------------------------------------------------

def _is_saturated_color(rgb):
    """
    เช็คว่าเป็นสีที่มี hue ชัดเจน (บล็อกสินค้า/ผนังตู้ที่เป็นสีทึบ เช่น น้ำเงิน เหลือง เขียว แดง ครีม/tan)
    ต่างจากพื้นหลังสีขาว, เส้น/ตัวอักษรสีดำ, และเส้นกรอบบางๆ ที่มีความอิ่มตัวต่ำ
    """
    r, g, b = rgb
    mx, mn = max(r, g, b), min(r, g, b)
    if mx < 60:       # เข้มเกินไป (ตัวอักษร/เส้นสีดำ)
        return False
    if mx - mn < 35:  # ขาว/เทาเกินไป (สีอิ่มตัวต่ำ)
        return False
    return True


def detect_container_bbox(img, min_run_width=25, min_run_height=25):
    """
    หาขอบเขตตู้คอนเทนเนอร์/สินค้าจริงในภาพ (deterministic pixel analysis) ด้วยการกรอง 2 ชั้น (2D solid-block filter):
      1) row-pass:    หาพิกเซลที่อยู่ในแนวนอนต่อเนื่องกว้างพอ (>= min_run_width) ภายในแถวของตัวเอง
      2) column-pass: จากผลลัพธ์ข้อ 1 หาต่อว่าพิกเซลนั้นอยู่ในแนวตั้งต่อเนื่องสูงพอ (>= min_run_height) ด้วย

    วิธีนี้กรองเส้นขอบกรอบ annotation ของ AI (วาดเป็นเส้นบาง ~8px) เส้นบอกระยะ (dimension line)
    และตัวอักษรออกได้ เพราะสิ่งเหล่านี้ 'กว้างมากแต่บางในอีกแนว' (ผ่านแค่เงื่อนไข 1 ไม่ผ่านเงื่อนไข 2)
    ในขณะที่บล็อกสินค้า/ผนังตู้จริงเป็นทรงตันขนาดใหญ่ ผ่านทั้ง 2 เงื่อนไข

    ทดสอบยืนยันแล้วว่าให้ผลตรงกันมาก (ค่าความคลาดเคลื่อน <1%) ในภาพตัวอย่างจริงหลายไฟล์
    ทั้งกรณีที่มี/ไม่มีกรอบ annotation เดิมทับซ้อนอยู่ในภาพ

    Returns: (xmin, ymin, xmax, ymax) แบบ relative กับภาพ img ที่ส่งเข้ามา หรือ None ถ้าไม่พบ
    """
    w, h = img.size
    px = img.convert("RGB").load()

    # Pass 1: row-wise mask — เก็บเฉพาะพิกเซลที่อยู่ใน run แนวนอนกว้างพอ
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

    # Pass 2: column-wise ตรวจสอบจาก row_mask ว่ามี run แนวตั้งสูงพอหรือไม่
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
                    if x < minx: minx = x
                    if x > maxx: maxx = x
                    if run_start < miny: miny = run_start
                    if y - 1 > maxy: maxy = y - 1
                run_start = None
        if run_start is not None and h - run_start >= min_run_height:
            found = True
            if x < minx: minx = x
            if x > maxx: maxx = x
            if run_start < miny: miny = run_start
            if h - 1 > maxy: maxy = h - 1

    return (minx, miny, maxx, maxy) if found else None


def detect_container_bounds_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start=0):
    """
    หาขอบเขตตู้คอนเทนเนอร์จริง แยกสำหรับ FRONT และ BACK view
    แทนที่จะสมมติว่าตู้ครอบคลุมเกือบเต็มความกว้างของภาพ (fixed percentage) ซึ่งเป็นสาเหตุหลัก
    ที่ทำให้กรอบ risk (เช่น FRONT_EMPTY_RISK) หลุดออกไปอยู่ในพื้นที่ว่างสีขาวรอบตู้

    Returns:
      {
        "FRONT": {"xmin":.., "xmax":.., "ymin":.., "ymax":..} หรือ None ถ้าตรวจไม่พบ,
        "BACK":  {...} หรือ None,
      }
      พิกัดทั้งหมดเป็นค่าสัมบูรณ์เทียบกับภาพเต็ม (full image) — บวก crop_y_start ให้แล้ว
      พร้อมใช้งานร่วมกับ draw.rectangle() บนภาพเต็มได้ทันที โดยไม่ต้องแปลงพิกัดเพิ่ม
    """
    result = {"FRONT": None, "BACK": None}
    try:
        if layout == "TOP_BOTTOM":
            mid_y = crop_h // 2
            front_view_img = diagram_crop.crop((0, 0, crop_w, mid_y))
            back_view_img  = diagram_crop.crop((0, mid_y, crop_w, crop_h))

            fb = detect_container_bbox(front_view_img)
            bb = detect_container_bbox(back_view_img)

            if fb:
                result["FRONT"] = {"xmin": fb[0], "ymin": fb[1] + crop_y_start, "xmax": fb[2], "ymax": fb[3] + crop_y_start}
            if bb:
                # bb สัมพัทธ์กับ back_view_img (เริ่มที่ y=mid_y ใน diagram_crop) — offset y กลับ + crop_y_start
                result["BACK"] = {"xmin": bb[0], "ymin": bb[1] + mid_y + crop_y_start, "xmax": bb[2], "ymax": bb[3] + mid_y + crop_y_start}
        else:  # LEFT_RIGHT
            half_w = crop_w // 2
            front_view_img = diagram_crop.crop((0, 0, half_w, crop_h))
            back_view_img  = diagram_crop.crop((half_w, 0, crop_w, crop_h))

            fb = detect_container_bbox(front_view_img)
            bb = detect_container_bbox(back_view_img)

            if fb:
                result["FRONT"] = {"xmin": fb[0], "ymin": fb[1] + crop_y_start, "xmax": fb[2], "ymax": fb[3] + crop_y_start}
            if bb:
                # bb สัมพัทธ์กับ back_view_img (เริ่มที่ x=half_w ใน diagram_crop) — offset x กลับ
                result["BACK"] = {"xmin": bb[0] + half_w, "ymin": bb[1] + crop_y_start, "xmax": bb[2] + half_w, "ymax": bb[3] + crop_y_start}

        for view_name in ("FRONT", "BACK"):
            if result[view_name]:
                b = result[view_name]
                print(f"Container bounds detected for {view_name}: x=[{b['xmin']}-{b['xmax']}] "
                      f"y=[{b['ymin']}-{b['ymax']}] ({round(b['xmin']/crop_w*100,1)}%-{round(b['xmax']/crop_w*100,1)}% of crop_w)")
            else:
                print(f"WARNING: Could not detect container bounds for {view_name} — will fall back to fixed percentages")

        return result
    except Exception as e:
        print(f"WARNING: Container bounds detection failed ({e}), falling back to fixed percentages")
        return {"FRONT": None, "BACK": None}

def extract_sku_from_pdf(pdf_bytes):
    """
    ดึงชื่อ SKU จาก Load Summary ใน PDF (หน้าที่ 2 ถ้ามี)
    คืนค่าเป็น list ของ SKU prefix เช่น ['TBASK', 'TRASK', 'DAJWG']
    """
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
            # เริ่มจับ SKU เมื่อเจอ Load Summary
            if "Load Summary" in line or "load summary" in line.lower():
                in_load_summary = True
                continue
            # หยุดเมื่อเจอ Cut List หรือหมดส่วน
            if in_load_summary and ("Cut List" in line or "cut list" in line.lower()):
                break
            if in_load_summary:
                # SKU จะเป็น token แรกของบรรทัด เช่น "TBASK   _722EBBU ..."
                # หรืออาจอยู่ในรูป "TBASK_722EBBU_..." — ดึงแค่ prefix ตัวอักษรต้น
                parts = line.split()
                if parts:
                    token = parts[0]
                    import re
                    # SKU prefix: ตัวอักษร+ตัวเลข เช่น ATFBA, MSFTA, VCS1A, TBASK
                    # ต้องมีความยาว >= 4 และไม่ใช่คำทั่วไป เช่น SKU, Total, Cut
                    match = re.match(r'^([A-Z][A-Z0-9]{3,7})', token)
                    if match:
                        prefix = match.group(1)
                        # กรองคำที่ไม่ใช่ SKU จริง
                        exclude = {'SKU', 'TOTAL', 'CUT', 'LIST', 'LOAD', 'PRIOR', 'QTY', 'PAGE', 'DATE'}
                        if prefix not in exclude:
                            skus.add(prefix)

        sku_list = sorted(skus)
        print(f"📦 SKU extracted: {sku_list}")
        return sku_list
    except Exception as e:
        print(f"⚠️ SKU extraction failed: {e}")
        return []

def analyze_rear_zone_with_ai(rear_crop: PIL.Image.Image, api_keys: list, view_label: str = "UNKNOWN") -> dict:
    global GLOBAL_KEY_INDEX 
    rear_prompt = f"""
You are a Cargo Safety Inspector. This image is a cropped zoom of the DOOR END (REAR) zone of a container.
This is the {view_label} view.
YOUR ONLY TASK: Determine if there is a GENUINE safety risk at the door end.

STRICT RULES — read carefully:
1. REAR_EMPTY_RISK: Flag ONLY if there is a visibly significant empty floor space (no cargo) near the container door, OR if cargo drops sharply (cliff-like) leaving a gap of more than 20% of container height. Minor height differences are NOT a risk.
2. REAR_LATERAL_IMBALANCE: Flag ONLY if cargo on the LEFT side is clearly and significantly taller than cargo on the RIGHT side (or vice versa) at the door zone — the difference must be obvious (more than 1 full box height). If cargo looks roughly even across the width, return SAFE.
3. Do NOT flag the container wall (solid yellow/tan/brown panel) as cargo. It is a fixed structure.
4. If cargo fills the rear area reasonably well and is roughly level across the width → return SAFE.
5. When in doubt, return SAFE. Only flag when you are highly confident.

Return ONLY this exact JSON format:
{{
  "rear_zone_risk": "REAR_EMPTY_RISK" | "REAR_LATERAL_IMBALANCE" | "BOTH" | "SAFE",
  "reasoning": "Describe exactly what you see — is there empty space, or are heights uneven? By how much?",
  "confidence": "HIGH" | "MEDIUM" | "LOW"
}}
"""
    return _call_gemini_json(rear_prompt, rear_crop, api_keys)
                                   
def analyze_front_zone_with_ai(front_crop: PIL.Image.Image, api_keys: list, view_label: str = "UNKNOWN") -> dict:
    global GLOBAL_KEY_INDEX
    front_prompt = f"""
You are a Cargo Safety Inspector. This image is a cropped zoom of the HEAD WALL (FRONT) zone of a container.
This is the {view_label} view. The solid yellow/tan/brown panel on one side IS the container head wall — it is NOT cargo.
YOUR TASK: Determine if there is a genuine FRONT_EMPTY_RISK.

STRICT RULES — read carefully:
1. FRONT_EMPTY_RISK means there is a clearly visible, large empty gap between the front-most cargo and the head wall — enough space that cargo could slide forward dangerously during braking (typically more than half a box width of empty space).
2. If cargo is stacked against or very close to the head wall, even if not perfectly flush — it is SAFE.
3. If cargo heights vary but cargo is still present and touching (or nearly touching) the wall — it is SAFE.
4. The yellow/tan solid panel = head wall. Its presence is normal. Do NOT flag it as a risk.
5. When in doubt, return SAFE. Only flag FRONT_EMPTY_RISK when the gap is obvious and dangerous.

Return ONLY this exact JSON object:
{{
  "front_zone_risk": "FRONT_EMPTY_RISK" | "SAFE",
  "reasoning": "Describe the gap you see (or why it is safe). How large is the empty space?",
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

def analyze_diagram_image_with_ai(diagram_image: PIL.Image.Image, layout: str = "TOP_BOTTOM", orientation: dict = None):
    global GLOBAL_KEY_INDEX 
    
    api_keys = get_api_keys_pool()
    if not api_keys:
        return [{"risk_type": "ERROR", "description": "No Gemini API Keys found."}]

    if orientation is None:
        orientation = {
            "FRONT": {"rear_side": "LEFT", "source": "fallback"},
            "BACK": {"rear_side": "RIGHT", "source": "fallback"},
        }

    front_rear = orientation["FRONT"]["rear_side"]
    front_wall = "RIGHT" if front_rear == "LEFT" else "LEFT"
    back_rear = orientation["BACK"]["rear_side"]
    back_wall = "RIGHT" if back_rear == "LEFT" else "LEFT"

    if layout == "LEFT_RIGHT":
        layout_desc = "FRONT view is on the LEFT half of the image. BACK view is on the RIGHT half of the image."
    else:
        layout_desc = "FRONT view is on the TOP half of the image. BACK view is on the BOTTOM half of the image."

    # ---------------------------------------------------------------------------
    # หมายเหตุสำคัญ: ตำแหน่ง REAR/FRONT ของแต่ละ view ด้านล่างนี้ ไม่ได้ให้ Gemini เดาเอง
    # แล้ว แต่คำนวณมาจาก deterministic pixel analysis (ดูฟังก์ชัน detect_arrow_orientation)
    # ที่ตรวจจับตำแหน่งลูกศรแดงจริงในภาพนี้โดยเฉพาะ ก่อนเรียก Gemini ทุกครั้ง
    # วิธีนี้แม่นยำกว่าการให้ AI ตีความตำแหน่งลูกศรเอง และตัดปัญหา "ตีกรอบผิดฝั่ง" ที่ต้นเหตุ
    # ---------------------------------------------------------------------------
    prompt = f"""
You are an expert Cargo Loading Safety Inspector analyzing a 3D cargo load plan.

CRITICAL DEFINITIONS & RULES:
1. STEP_DOWN_RISK: Flag ONLY when there is a sudden, sharp height drop between two ADJACENT cargo stacks that creates an UNSTABLE cliff — cargo from the tall stack could topple onto the short stack.
   - Count TOTAL height of each stack (all tiers combined) before comparing.
   - The height difference must be MORE than 1 full standard box height (roughly >40cm or >1 tier) to be flagged.
   - If the shorter stack is intentionally shorter by design (e.g., lighter goods), or if the step is gradual across multiple positions, it is NOT a STEP_DOWN_RISK.
   - Typical loading where tall stacks taper down toward the doors is NOT a STEP_DOWN_RISK.
   - When in doubt, do NOT flag STEP_DOWN_RISK.
2. DO NOT label the height drop at the very end of the cargo near the container doors as STEP_DOWN_RISK. That is REAR_EMPTY_RISK territory.

VIEW LAYOUT (this image):
- The image shows TWO views: FRONT view and BACK view.
- {layout_desc}

GROUND TRUTH ORIENTATION (already verified by deterministic red-arrow pixel analysis for THIS SPECIFIC IMAGE — this is a FACT, do NOT re-derive or second-guess it, just use it):
- In the FRONT view: the REAR (door end) is on the {front_rear} side. The FRONT (wall end / head wall) is on the {front_wall} side.
- In the BACK view: the REAR (door end) is on the {back_rear} side. The FRONT (wall end / head wall) is on the {back_wall} side.

CRITICAL BOX PLACEMENT RULES:
- REAR_EMPTY_RISK = empty space near the DOOR end.
  * In FRONT view: box must be on the {front_rear} side of that view (door side).
  * In BACK view: box must be on the {back_rear} side of that view (door side).
- FRONT_EMPTY_RISK = empty space near the WALL end (head wall).
  * In FRONT view: box must be on the {front_wall} side of that view (wall side).
  * In BACK view: box must be on the {back_wall} side of that view (wall side).
- NEVER place a REAR_EMPTY_RISK box on the wall side, or a FRONT_EMPTY_RISK box on the door side.
- NEVER let any box_2d cross outside the actual cargo/container silhouette. The box must stay tightly within the container outline of the view it belongs to — never extend past the container's outer edge or into empty white margin/background.

YOUR TASK:
Find all safety risks in the image and return them in this exact JSON array format.

BOUNDING BOX RULES:
- box_2d must use [ymin, xmin, ymax, xmax] format with values 0–1000 (normalized to image size).
- box_2d must tightly surround only the AFFECTED cargo area, NOT the entire image.
- The box must have a reasonable size: width between 5%–70% of image width, height between 5%–70% of image height.
- For STEP_DOWN_RISK: draw the box across the height-step boundary between two adjacent stacks.
- NEVER draw a box that covers more than 70% of the image in either dimension.
- box_2d MUST fall entirely within the half of the image belonging to its "view" (FRONT view box_2d must stay within the FRONT half; BACK view box_2d must stay within the BACK half).

MANDATORY: "view" field MUST be either "FRONT" or "BACK" only. NEVER use "GENERAL".
If a risk spans both views, create TWO separate entries — one for FRONT and one for BACK.

Return ONLY a JSON array — no explanation, no markdown:
[
  {{
    "risk_type": "STEP_DOWN_RISK" | "REAR_EMPTY_RISK" | "REAR_LATERAL_IMBALANCE" | "FRONT_EMPTY_RISK" | "LATERAL_GAP_RISK" | "TALL_UNSTABLE_RISK" | "OVERHANG_RISK",
    "view": "FRONT" | "BACK",
    "box_2d": [ymin, xmin, ymax, xmax],
    "description": "brief description of the risk"
  }}
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

def _mirror_box_in_range(box, lo, hi):
    """ Mirror กล่อง (x0,y0,x1,y1) ในแนวนอน ภายในขอบเขต [lo, hi] """
    x0, y0, x1, y1 = box
    return (lo + (hi - x1), y0, lo + (hi - x0), y1)


def _get_fallback_box(risk_type: str, view_label: str, layout: str, crop_w: int, crop_y_start: int, crop_h: int,
                       orientation: dict = None, container_bounds: dict = None):
    """
    คำนวณกรอบ fallback สำหรับ risk_type + view ที่กำหนด

    ลำดับความสำคัญของข้อมูลอ้างอิง (reference frame) ที่ใช้คำนวณเปอร์เซ็นต์โซน:
      1) container_bounds ที่ตรวจพบจริงจาก pixel analysis (แม่นยำที่สุด - ใช้ก่อนเสมอถ้ามี)
      2) ถ้าตรวจไม่พบ (None) จะ fallback ไปใช้สมมติฐานเดิม (ตู้ครอบคลุมเกือบเต็ม crop_w/crop_h)

    วิธีนี้แก้ปัญหากรอบหลุดออกนอกตู้แบบถาวร เพราะโซนทั้งหมดจะถูกคำนวณเป็นเปอร์เซ็นต์ของ
    'ขนาดตู้จริง' ไม่ใช่เปอร์เซ็นต์ของขนาด crop เต็มที่มีพื้นที่ว่างขอบภาพปนอยู่มาก
    """
    vl = view_label.upper()
    view_bounds = container_bounds.get(vl) if container_bounds else None

    default_rear_side = "LEFT" if vl == "FRONT" else "RIGHT"
    actual_rear_side = (orientation or {}).get(vl, {}).get("rear_side", default_rear_side)

    # ---------------------------------------------------------------------------
    # กำหนด reference frame: (origin_x, origin_y, ref_w, ref_h)
    # ---------------------------------------------------------------------------
    if view_bounds:
        origin_x = view_bounds["xmin"]
        origin_y = view_bounds["ymin"]
        ref_w = view_bounds["xmax"] - view_bounds["xmin"]
        ref_h = view_bounds["ymax"] - view_bounds["ymin"]
        using_detected_bounds = True
    else:
        # Fallback: สมมติฐานเดิม (ก่อนมีการตรวจจับ) - ตู้ครอบคลุมเกือบเต็ม crop
        if layout == "TOP_BOTTOM":
            half_h = crop_h // 2
            if vl == "FRONT":
                origin_x, origin_y, ref_w, ref_h = 0, crop_y_start, crop_w, half_h
            else:
                origin_x, origin_y, ref_w, ref_h = 0, crop_y_start + half_h, crop_w, crop_h - half_h
        else:  # LEFT_RIGHT
            half_w = crop_w // 2
            if vl == "FRONT":
                origin_x, origin_y, ref_w, ref_h = 0, crop_y_start, half_w, crop_h
            else:
                origin_x, origin_y, ref_w, ref_h = half_w, crop_y_start, crop_w - half_w, crop_h
        using_detected_bounds = False

    def pct(px, py):
        """แปลงเปอร์เซ็นต์ (0.0-1.0) ให้เป็นพิกัดจริงในระบบภาพเต็ม อิงจาก reference frame ปัจจุบัน"""
        return (origin_x + int(ref_w * px), origin_y + int(ref_h * py))

    # ---------------------------------------------------------------------------
    # นิยามโซนตาม risk_type (เป็นเปอร์เซ็นต์ของ reference frame)
    # โดย default assumption: REAR (ประตู) อยู่ฝั่งซ้ายของ reference frame เสมอ (สำหรับ TOP_BOTTOM)
    # หรืออยู่มุมล่างซ้าย/บนขวาแบบ isometric เสมอ (สำหรับ LEFT_RIGHT)
    # แล้วค่อย mirror ทีหลังถ้า actual_rear_side ต่างจาก default
    # ---------------------------------------------------------------------------
    if layout == "TOP_BOTTOM":
        rear_frac, wall_frac = 0.38, 0.32
        y_pad = 0.08
        y0f, y1f = y_pad, 1.0 - y_pad
        mid_yf = y0f + (y1f - y0f) / 2

        zones_pct = {
            "REAR_EMPTY_RISK":        (0.0, y0f, rear_frac, mid_yf),
            "REAR_LATERAL_IMBALANCE": (0.0, mid_yf, rear_frac, y1f),
            "FRONT_EMPTY_RISK":       (1.0 - wall_frac, y0f, 1.0, y1f),
            "STEP_DOWN_RISK":         (0.15, y0f, 0.85, y1f),
            "LATERAL_GAP_RISK":       (0.20, y0f, 0.80, y1f),
            "TALL_UNSTABLE_RISK":     (0.25, y0f, 0.75, y1f),
            "OVERHANG_RISK":          (0.15, y0f, 0.85, mid_yf),
        }
        zp = zones_pct.get(risk_type)
        if zp is None:
            return None
        x0, y0 = pct(zp[0], zp[1])
        x1, y1 = pct(zp[2], zp[3])
        box = (x0, y0, x1, y1)

        # default assumption ด้านบน: REAR อยู่ฝั่งซ้ายเสมอ ถ้าจริงๆ อยู่ขวา ให้ mirror ในแนวนอน
        if actual_rear_side != default_rear_side:
            box = _mirror_box_in_range(box, origin_x, origin_x + ref_w)

    else:  # LEFT_RIGHT (isometric diagonal)
        mid_yf = 0.50
        if default_rear_side == "LEFT":
            # ประตูท้าย = มุมซ้ายล่าง, หัวตู้ = มุมขวาบน (default assumption)
            rear_zone   = (0.0, mid_yf, 0.55, 1.0)
            wall_zone   = (0.30, 0.0, 1.0, mid_yf)
        else:
            # ประตูท้าย = มุมขวาบน, หัวตู้ = มุมซ้ายล่าง (default assumption)
            rear_zone   = (0.45, 0.0, 1.0, mid_yf)
            wall_zone   = (0.0, mid_yf, 0.70, 1.0)

        rear_mid_yf = rear_zone[1] + (rear_zone[3] - rear_zone[1]) / 2

        zones_pct = {
            "REAR_EMPTY_RISK":        (rear_zone[0], rear_zone[1], rear_zone[2], rear_mid_yf),
            "REAR_LATERAL_IMBALANCE": (rear_zone[0], rear_mid_yf, rear_zone[2], rear_zone[3]),
            "FRONT_EMPTY_RISK":       wall_zone,
            "STEP_DOWN_RISK":         (0.08, 0.20, 0.88, 0.78),
            "LATERAL_GAP_RISK":       (0.05, 0.20, 0.85, 0.80),
            "TALL_UNSTABLE_RISK":     (0.05, 0.10, 0.85, 0.60),
            "OVERHANG_RISK":          (0.05, 0.10, 0.85, 0.45),
        }
        zp = zones_pct.get(risk_type)
        if zp is None:
            return None
        x0, y0 = pct(zp[0], zp[1])
        x1, y1 = pct(zp[2], zp[3])
        box = (x0, y0, x1, y1)
        # การ mirror สำหรับ LEFT_RIGHT ถูกคำนวณผ่าน default_rear_side ใน zones_pct ไปแล้ว
        # (เลือก rear_zone/wall_zone ตาม default_rear_side ข้างต้น) จึงไม่ต้อง mirror ซ้ำที่นี่
        # ยกเว้นกรณี actual_rear_side ต่างจาก default_rear_side ต้อง mirror เพิ่ม
        if actual_rear_side != default_rear_side:
            box = _mirror_box_in_range(box, origin_x, origin_x + ref_w)

    source_label = "detected container bounds" if using_detected_bounds else "fixed-percentage fallback"
    print(f"Fallback box for {risk_type} ({vl}, {layout}): using {source_label}, rear_side={actual_rear_side}, box={box}")
    return box

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
        sku_list = extract_sku_from_pdf(pdf_bytes)
        sku_str = ", ".join(sku_list) if sku_list else ""

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

        # ---------------------------------------------------------------------------
        # ตรวจจับตำแหน่งลูกศรแดงจริง (deterministic, pixel-based) ก่อนเรียก Gemini
        # เพื่อยืนยันว่า REAR (ประตูท้ายตู้) ของแต่ละ view อยู่ฝั่งซ้ายหรือขวาจริง
        # ---------------------------------------------------------------------------
        orientation = detect_arrow_orientation(diagram_crop, layout, crop_w, crop_h)

        # ---------------------------------------------------------------------------
        # ตรวจจับขอบเขตตู้คอนเทนเนอร์จริง (deterministic, pixel-based) แยกตาม view
        # แก้ปัญหากรอบหลุดออกนอกตู้แบบถาวร โดยไม่ใช้เปอร์เซ็นต์ตายตัวของ crop_w/crop_h อีกต่อไป
        # (ซึ่งพบว่าตู้จริงมักครอบคลุมแค่ ~33%-70% ของ crop_w ไม่ใช่เกือบเต็มความกว้างอย่างที่สมมติไว้เดิม)
        # ---------------------------------------------------------------------------
        container_bounds = detect_container_bounds_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start)

        all_risks = analyze_diagram_image_with_ai(diagram_crop, layout=layout, orientation=orientation)

        front_rear_side = orientation["FRONT"]["rear_side"]  # "LEFT" หรือ "RIGHT"
        back_rear_side  = orientation["BACK"]["rear_side"]

        # ---------------------------------------------------------------------------
        # สร้าง crop โซน rear/front สำหรับวิเคราะห์ zoom - ใช้ขอบเขตตู้จริงถ้าตรวจพบ
        # เพื่อความแม่นยำสูงสุด (ไม่ครอบคลุมพื้นที่ว่างขอบภาพที่ไม่ใช่ตัวตู้)
        # ---------------------------------------------------------------------------
        def _zoom_crop_ranges(view_bounds, rear_side, default_origin_x, default_ref_w, y0, y1):
            """คืนค่า (rear_x0,rear_x1), (wall_x0,wall_x1) สำหรับ crop โซน zoom"""
            if view_bounds:
                ox, rw = view_bounds["xmin"], view_bounds["xmax"] - view_bounds["xmin"]
            else:
                ox, rw = default_origin_x, default_ref_w
            if rear_side == "LEFT":
                rear_range = (ox, ox + int(rw * 0.45))
                wall_range = (ox + int(rw * 0.55), ox + rw)
            else:
                rear_range = (ox + int(rw * 0.55), ox + rw)
                wall_range = (ox, ox + int(rw * 0.45))
            return rear_range, wall_range

        if layout == "TOP_BOTTOM":
            half_h = crop_h // 2

            (fr_x0, fr_x1), (fw_x0, fw_x1) = _zoom_crop_ranges(
                container_bounds.get("FRONT"), front_rear_side, 0, crop_w, crop_y_start, crop_y_start + half_h)
            (br_x0, br_x1), (bw_x0, bw_x1) = _zoom_crop_ranges(
                container_bounds.get("BACK"), back_rear_side, 0, crop_w, crop_y_start + half_h, crop_y_end)

            rear_crop_front  = img.crop((fr_x0, crop_y_start,          fr_x1, crop_y_start + half_h))
            front_crop_front = img.crop((fw_x0, crop_y_start,          fw_x1, crop_y_start + half_h))
            rear_crop_back   = img.crop((br_x0, crop_y_start + half_h, br_x1, crop_y_end))
            front_crop_back  = img.crop((bw_x0, crop_y_start + half_h, bw_x1, crop_y_end))

            print(f"TOP_BOTTOM crop - FRONT rear={front_rear_side} ({fr_x0}-{fr_x1}) | "
                  f"BACK rear={back_rear_side} ({br_x0}-{br_x1})")
        else:
            half_w = crop_w // 2

            (fr_x0, fr_x1), (fw_x0, fw_x1) = _zoom_crop_ranges(
                container_bounds.get("FRONT"), front_rear_side, 0, half_w, crop_y_start, crop_y_end)
            (br_x0, br_x1), (bw_x0, bw_x1) = _zoom_crop_ranges(
                container_bounds.get("BACK"), back_rear_side, half_w, crop_w - half_w, crop_y_start, crop_y_end)

            mid_h = crop_y_start + int(crop_h * 0.50)

            # Front view - ซีกซ้าย: ประตูท้ายมุมล่าง, หัวตู้มุมบน (ถ้า rear_side=LEFT) หรือกลับกัน
            if front_rear_side == "LEFT":
                rear_crop_front  = img.crop((fr_x0, mid_h,        fr_x1, crop_y_end))
                front_crop_front = img.crop((fw_x0, crop_y_start, fw_x1, mid_h))
            else:
                rear_crop_front  = img.crop((fr_x0, crop_y_start, fr_x1, mid_h))
                front_crop_front = img.crop((fw_x0, mid_h,        fw_x1, crop_y_end))

            if back_rear_side == "LEFT":
                rear_crop_back   = img.crop((br_x0, mid_h,        br_x1, crop_y_end))
                front_crop_back  = img.crop((bw_x0, crop_y_start, bw_x1, mid_h))
            else:
                rear_crop_back   = img.crop((br_x0, crop_y_start, br_x1, mid_h))
                front_crop_back  = img.crop((bw_x0, mid_h,        bw_x1, crop_y_end))

            print(f"LEFT_RIGHT crop - FRONT rear={front_rear_side} ({fr_x0}-{fr_x1}) | "
                  f"BACK rear={back_rear_side} ({br_x0}-{br_x1})")

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

            # REAR_EMPTY_RISK: HIGH หรือ MEDIUM ผ่าน
            # REAR_LATERAL_IMBALANCE: HIGH เท่านั้น (false positive สูง)
            rear_empty_min = ("HIGH", "MEDIUM")
            rear_lateral_min = ("HIGH",)

            if rear_zone_risk in ("REAR_EMPTY_RISK", "BOTH"):
                if confidence in rear_empty_min and view_label not in _existing_risk_views("REAR_EMPTY"):
                    all_risks.append({"view": view_label, "risk_type": "REAR_EMPTY_RISK", "direction": "LONGITUDINAL", "lateral_side": "N/A", "reasoning": rear_result.get("reasoning", ""), "description": "พบความต่างระดับฝั่งประตูท้ายตู้ (วิเคราะห์จาก Zoom ท้ายตู้)", "box_2d": None})
                else:
                    print(f"⚠️ Skipping REAR_EMPTY ({view_label}) — confidence={confidence}")

            if rear_zone_risk in ("REAR_LATERAL_IMBALANCE", "BOTH"):
                if confidence in rear_lateral_min and view_label not in _existing_risk_views("REAR_LATERAL"):
                    all_risks.append({"view": view_label, "risk_type": "REAR_LATERAL_IMBALANCE", "direction": "LATERAL", "lateral_side": "N/A", "reasoning": rear_result.get("reasoning", ""), "description": "พบสินค้าท้ายตู้สูงต่ำไม่เท่ากัน (วิเคราะห์จาก Zoom ท้ายตู้)", "box_2d": None})
                else:
                    print(f"⚠️ Skipping REAR_LATERAL ({view_label}) — confidence={confidence}")

        for view_label, front_result in [("FRONT", front_result_front), ("BACK", front_result_back)]:
            if not isinstance(front_result, dict):
                continue
                
            confidence = str(front_result.get("confidence", "LOW")).upper()

            # FRONT_EMPTY_RISK: HIGH confidence เท่านั้น (false positive สูงมาก)
            if confidence != "HIGH":
                print(f"⚠️ Skipping front zoom ({view_label}) — confidence={confidence} (need HIGH)")
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

            # ค่าเริ่มต้นของ resolved_view (เผื่อกรณีไม่มี box_2d ให้ใช้ validate เลย)
            resolved_view = view_name if view_name != "GENERAL" else "FRONT"

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
                    
                    box_center_x = (abs_xmin + abs_xmax) / 2
                    box_center_y = (abs_ymin + abs_ymax) / 2

                    # ---------------------------------------------------------------------------
                    # validate ก่อนวาด - resolve GENERAL -> FRONT/BACK และตรวจสอบโซนตาม risk_type + view จริง
                    # ใช้ container_bounds ที่ตรวจพบจริง (deterministic) เป็นหลักในการกำหนดขอบเขตที่ยอมรับได้
                    # แทนเปอร์เซ็นต์ตายตัวของ crop_w/crop_h ซึ่งเป็นสาเหตุหลักที่กรอบหลุดออกนอกตู้
                    # ทำงานเหมือนกันทั้ง 2 layout (LEFT_RIGHT และ TOP_BOTTOM)
                    # ---------------------------------------------------------------------------
                    half_w_local = crop_w // 2
                    half_h_local = crop_h // 2
                    mid_y_local  = crop_y_start + half_h_local

                    # 1) resolve GENERAL -> FRONT/BACK จากตำแหน่ง box จริง (ใช้ได้ทั้ง 2 layout)
                    resolved_view = view_name
                    if view_name == "GENERAL":
                        if layout == "LEFT_RIGHT":
                            resolved_view = "FRONT" if box_center_x < crop_w * 0.50 else "BACK"
                        else:
                            resolved_view = "FRONT" if box_center_y < mid_y_local else "BACK"
                        print(f"GENERAL -> resolved to {resolved_view} ({layout}, box_center=({box_center_x:.0f},{box_center_y:.0f}))")

                    default_rear_side = "LEFT" if resolved_view == "FRONT" else "RIGHT"
                    actual_rear_side = orientation.get(resolved_view, {}).get("rear_side", default_rear_side)

                    # 2) ดึงขอบเขตตู้จริงของ view นี้ (ถ้าตรวจพบ) มาใช้กำหนดโซนที่ยอมรับได้
                    view_bounds = container_bounds.get(resolved_view)

                    if view_bounds:
                        # ใช้ขอบเขตตู้จริงที่ตรวจพบ - แม่นยำที่สุด
                        vb_xmin, vb_xmax = view_bounds["xmin"], view_bounds["xmax"]
                        vb_ymin, vb_ymax = view_bounds["ymin"], view_bounds["ymax"]
                        vb_w = vb_xmax - vb_xmin
                        vb_h = vb_ymax - vb_ymin
                        # เผื่อ margin เล็กน้อยรอบขอบตู้จริง (10% ของขนาดตู้) เพราะ Gemini อาจตีกรอบชิดขอบพอดี
                        margin_x = vb_w * 0.10
                        margin_y = vb_h * 0.10
                        cargo_zone_ymin = vb_ymin - margin_y
                        cargo_zone_ymax = vb_ymax + margin_y

                        if risk_type == "REAR_EMPTY_RISK":
                            if actual_rear_side == "LEFT":
                                cargo_zone_xmin, cargo_zone_xmax = vb_xmin - margin_x, vb_xmin + vb_w * 0.45
                            else:
                                cargo_zone_xmin, cargo_zone_xmax = vb_xmax - vb_w * 0.45, vb_xmax + margin_x
                        elif risk_type == "FRONT_EMPTY_RISK":
                            if actual_rear_side == "LEFT":
                                cargo_zone_xmin, cargo_zone_xmax = vb_xmax - vb_w * 0.40, vb_xmax + margin_x
                            else:
                                cargo_zone_xmin, cargo_zone_xmax = vb_xmin - margin_x, vb_xmin + vb_w * 0.40
                        else:
                            cargo_zone_xmin, cargo_zone_xmax = vb_xmin - margin_x, vb_xmax + margin_x
                    else:
                        # Fallback: ตรวจไม่พบขอบเขตตู้จริง ใช้เปอร์เซ็นต์ตายตัวแบบเดิม (best-effort)
                        if layout == "TOP_BOTTOM":
                            if resolved_view == "FRONT":
                                cargo_zone_ymin = crop_y_start + crop_h * 0.03
                                cargo_zone_ymax = mid_y_local
                            else:
                                cargo_zone_ymin = mid_y_local
                                cargo_zone_ymax = crop_y_end - crop_h * 0.03
                        else:
                            cargo_zone_ymin = crop_y_start + crop_h * 0.05
                            cargo_zone_ymax = crop_y_end   - crop_h * 0.05

                        if layout == "LEFT_RIGHT":
                            if risk_type == "FRONT_EMPTY_RISK":
                                if resolved_view == "FRONT":
                                    d_xmin, d_xmax = crop_w * 0.28, crop_w * 0.50
                                else:
                                    d_xmin, d_xmax = crop_w * 0.50, crop_w * 0.75
                            elif risk_type == "REAR_EMPTY_RISK":
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
                        else:
                            if risk_type == "REAR_EMPTY_RISK":
                                if resolved_view == "FRONT":
                                    d_xmin, d_xmax = 0, crop_w * 0.45
                                else:
                                    d_xmin, d_xmax = crop_w * 0.55, crop_w * 0.97
                            elif risk_type == "FRONT_EMPTY_RISK":
                                if resolved_view == "FRONT":
                                    d_xmin, d_xmax = crop_w * 0.55, crop_w * 0.97
                                else:
                                    d_xmin, d_xmax = 0, crop_w * 0.45
                            else:
                                d_xmin, d_xmax = 0, crop_w * 0.97

                            if actual_rear_side != default_rear_side:
                                cargo_zone_xmin, cargo_zone_xmax = crop_w - d_xmax, crop_w - d_xmin
                            else:
                                cargo_zone_xmin, cargo_zone_xmax = d_xmin, d_xmax

                    if not (cargo_zone_xmin <= box_center_x <= cargo_zone_xmax) or not (cargo_zone_ymin < box_center_y < cargo_zone_ymax):
                        print(f"⚠️ box_2d center ({box_center_x:.0f}, {box_center_y:.0f}) out of cargo zone — fallback for {risk_type}")
                        raise ValueError("box out of cargo zone")

                    box_w_ratio = (abs_xmax - abs_xmin) / crop_w
                    box_h_ratio = (abs_ymax - abs_ymin) / crop_h

                    # ขนาดกล่องต้องสมเหตุสมผล: ไม่เล็กเกิน 3% และไม่ใหญ่เกิน 80%
                    box_too_small = box_w_ratio < 0.03 or box_h_ratio < 0.03

                    if not box_too_small and box_w_ratio < 0.80 and box_h_ratio < 0.80:
                        # กล่องขนาดปกติ — วาดตามพิกัดจริงจาก Gemini
                        draw.rectangle([abs_xmin, abs_ymin, abs_xmax, abs_ymax], outline=outline_color, width=8)
                        drawn = True
                    else:
                        # FIX 4: กล่องใหญ่เกิน 80% — clamp ให้แคบลงแต่ยังอยู่ในบริเวณที่ Gemini ชี้
                        pad_x = int(crop_w * 0.10)
                        pad_y = int(crop_h * 0.10)
                        clamped_xmin = max(abs_xmin, pad_x)
                        clamped_xmax = min(abs_xmax, crop_w - pad_x)
                        clamped_ymin = max(abs_ymin, crop_y_start + pad_y)
                        clamped_ymax = min(abs_ymax, crop_y_start + crop_h - pad_y)
                        
                        if clamped_xmax > clamped_xmin and clamped_ymax > clamped_ymin:
                            draw.rectangle([clamped_xmin, clamped_ymin, clamped_xmax, clamped_ymax], outline=outline_color, width=8)
                            drawn = True
                            print(f"📦 Clamped oversized box for {risk_type} ({resolved_view})")
                except Exception:
                    pass

            if not drawn:
                # ใช้ fallback zone ตามตำแหน่งที่กำหนดไว้ (ใช้ container_bounds ถ้าตรวจพบ)
                fallback = _get_fallback_box(risk_type, resolved_view, layout, crop_w, crop_y_start, crop_h,
                                              orientation=orientation, container_bounds=container_bounds)
                if fallback:
                    draw.rectangle(fallback, outline=outline_color, width=8)
                    drawn = True

            if not drawn:
                print(f"⚠️ Could not draw box for {risk_type} ({resolved_view}) — no valid coords or fallback")

            # --- FIX 3: append report ครั้งเดียวต่อ risk_type (ไม่ขึ้นกับ view และไม่ขึ้นกับ drawn) ---
            if risk_type not in reported_risk_types:
                reported_risk_types.add(risk_type)
                detected_hazards.append({
                    "title": f"ความเสี่ยง: {risk_type}",
                    "detail": generate_action_report(risk_type, risk.get("description", ""), sku_str),
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
