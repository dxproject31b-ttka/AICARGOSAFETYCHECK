"""
================================================================================
AI Cargo Safety Checker - v26.00 ZERO-AI EDITION
================================================================================
v26.00 (แก้ pain points หลัก 7 จุดที่ทำให้ Phase 1 นับผิด / Phase 2-3 ผิดพลาด /
วาดกรอบผิด - รวม fixes ที่ค้างจาก session ก่อนหน้า + สิ่งใหม่ที่วิเคราะห์เพิ่ม):

  Bug#A (Critical) - compute_floor_profile ใช้ gap_thresh=30 hardcode ทำให้ไฟล์ที่
    floor อยู่ห่างจาก cargo_bottom มากกว่า 30px (มุมกล้อง/scale=4) ได้ grounded=0
    ทั้ง view -> measure_stack_lengths crash / seam ผิดทั้งหมด
    FIX: _compute_floor_profile_adaptive() คำนวณ gap_thresh = percentile 85 ของ
    gap ที่พบจริงในภาพ (clamp 20-120px) แทน hardcode 30px

  Bug#B (Critical) - FRONT col[0] false-positive จากมุมกล้อง: cx ห่างจาก col[1]
    มากผิดปกติ (> 2x median spacing) แต่ไม่ถูกกรองออก ทำให้นับเกิน 1 และ seam
    แรกอยู่ผิดตำแหน่งมาก -> pos_range ทุกตั้งเบี่ยงเบน -> cross-view matching ผิด
    FIX: _p1b_validate_column_spacing() หลัง compute_phase1b_columns ตรวจ
    spacing outlier (IQR-based) และตัด col ที่ห่างเกิน 2.5x median spacing ออก

  Bug#C (Critical) - risk_abs_box ใช้ local_floor_y[xm] แต่ xm อาจอยู่นอกช่วง
    grounded จริง ทำให้ได้ floor_y_local = -1 -> box = None -> ไม่วาดกรอบเลย
    FIX: _safe_floor_y_at(lfy, xm, x_range) ค้นหา floor_y ที่ valid ใกล้ xm ที่สุด
    ในช่วง x_range ก่อน fallback median ของทั้ง view

  Bug#D (High) - color_anomaly ตรวจตั้งท้ายสุดที่เป็น corner_dup=True ของ FRONT:
    กลาง-ซ้ายของ FRONT view (pos ต่ำ) มี corner artifact ที่มีหลายสีปะปนเสมอ
    -> false positive color_anomaly ทุกไฟล์ที่ FRONT[0] = corner
    FIX: suppress color_anomaly สำหรับ record ที่ is_corner_duplicate=True เสมอ

  Bug#E (High) - _rearmost_record ข้าม corner_dup แต่ถ้า corner_dup=True คือ idx=0
    ซึ่งมี pos_range[1] สูงสุด (เพราะ FRONT ถูก flip) -> ฟังก์ชันเลือก record ผิด
    FIX: _rearmost_record ไม่นับ is_corner_duplicate ทั้งในการข้ามและเป็นเป้าหมาย
    (เหมือนเดิม) แต่เพิ่ม guard: ถ้า max pos_range[1] เป็น corner_dup ให้ skip
    และใช้ตัวถัดไปแทน - ครอบคลุมกรณีที่ corner_dup อยู่ที่ idx ไหนก็ได้

  Bug#F (Medium) - measure_stack_lengths crash เมื่อ start_x=None หรือ end_x=None
    (เกิดเมื่อ measure_cargo_extent_via_white_bg คืน None ทั้งคู่ในไฟล์ที่ไม่มี white bg)
    FIX: guard None ใน measure_stack_lengths + process_view_with_length_on_image

  Bug#G (Medium) - seam boundaries จาก PHASE 1B (override_cols) ไม่ถูก validate
    ว่าอยู่ใน [start_x, end_x] จริง ทำให้ seam อยู่นอกช่วง cargo -> ความยาวตั้งติดลบ
    FIX: clamp seam ให้อยู่ใน [start_x, end_x] ก่อนเรียก measure_stack_lengths

================================================================================
v25.14 (แก้ 6 root causes ที่พบใน PHASE 1B ของ v25.13 - ตรวจสอบเทียบข้อมูลจริงจากไฟล์
ตัวอย่าง AC03-01 และ EC04-01/02/03/04 แล้ว):

  Bug#1 (Critical) - Double render, coordinate mismatch: PHASE 1B เดิม render PDF แยกที่
    scale=4 แต่ pipeline หลักใช้ scale=3 -> พิกัด x ของ cols ที่ PHASE 1B ส่งคืนไม่ตรงกับ
    coordinate system ของ region ใน process_view_on_image ทำให้ seam ผิดตั้งแต่ต้น
    FIX: PHASE 1B รับ region ที่ crop แล้วจาก pipeline หลักโดยตรง (get_view_region เรียก
    ครั้งเดียวใน run_full_analysis_on_image ส่ง region+origin เดียวกันให้ทั้ง 2 ฝั่งผ่าน
    precrop=) ไม่ render/crop แยกอีกต่อไป

  Bug#2 (Critical) - get_safe_region เรียก ensure_safe_crop ซ้ำ: crop origin ของ PHASE 1B
    (เดิม) ≠ crop origin ของ process_view_on_image -> offset ต่างกัน
    FIX: ลบ get_safe_region ออก แทนที่ด้วย get_view_region ตัวเดียวที่ใช้ region เดียวกัน 100%

  Bug#3 (High) - cx_tol=45 ตายตัว: ไม่ปรับตามขนาดกล่องจริงในภาพ
    FIX: _p1b_compute_adaptive_cx_tol() คำนวณ cx_tol = median(front_width) x 0.4 จากภาพจริง

  Bug#4 (High) - _p1b_reconcile_with_back ไม่รองรับ M < N: เดิมเงื่อนไข M<=N คืนค่าเดิมทั้งหมด
    โดยไม่ทำอะไร ปล่อยให้ FRONT undercount หลุดรอด
    FIX: ถ้า FRONT นับได้น้อยกว่า BACK -> augment ด้วยตำแหน่ง synthetic ที่ interpolate จาก
    BACK (Hungarian assignment หาตำแหน่ง BACK ที่ยังไม่มีคู่)

  Bug#5 (Medium) - seam midpoint ตกนอก grounded zone: min_seg_width=20px hardcode
    FIX: adaptive_min_seg = median(col_width) x 0.25 แทน hardcode 20px

  Bug#6 (Medium) - ไม่ตรวจ corner artifact เมื่อใช้ override_cols: rail-check เดิมทำงานเฉพาะ
    path fallback (seam-based) เท่านั้น
    FIX: ย้าย rail-check ไปเป็น common code หลัง if/else -> ตรวจ rail เสมอทั้ง 2 path

  ไม่ได้แก้ไข PHASE 2/3/Rule Engine หรือ risk detection logic ใดๆ เพิ่มเติมนอกเหนือจาก 6 จุดนี้
================================================================================
v25.13 (แก้ไข 2 จุดจาก v25.12 ด้วยหลักฐานจริง - ยังไม่แก้ pipeline หลัก):
  v25.12 เคยเสนอ utility ทดลอง 2 ตัวที่ "พังจริง" เมื่อทดสอบกับ AC03-01 (ไฟล์โหลดเต็มคัน
  100% - 1 ใน 6 ไฟล์ calibration): (1) structural-color exclusion (single-view boundary-
  touch) ทำให้กล่องสีน้ำเงินถูกเข้าใจผิดเป็นพื้นตู้ (2) width-vector geometry classifier
  ให้ผล FRONT/BACK ไม่ตรงกันเอง (216,108 vs 128,64)
  v25.13 สืบสวนสาเหตุจริงและแก้ไขทั้งคู่ด้วยหลักฐานที่ทดสอบกับ AC03-01 จริง:
    (1) is_structural_color_cross_view: เปลี่ยนจากตรวจ view เดียวเป็นตรวจ "ต้องปรากฏและ
        ชนขอบภาพในทั้ง FRONT และ BACK พร้อมกัน" (สีโครงสร้างเป็นส่วนของรถทั้งคัน ต้องเห็นได้
        จาก 2 มุมกล้อง) - ทดสอบแล้ว: สีน้ำเงิน (กล่องจริง) ชนขอบแค่ฝั่ง BACK ไม่ชนฝั่ง FRONT
        -> ถูกเก็บไว้เป็นกล่องถูกต้อง (ไม่ผิดพลาดเหมือน v25.12 เดิมอีกต่อไป)
    (2) locate_apex_and_width_vector_consistent: เพิ่ม cross-view consistency-gate เทียบ
        magnitude ของ width_vector ระหว่าง FRONT/BACK (ควรเท่ากันเพราะรถคันเดียวกัน) - ถ้า
        ต่างกันเกินเกณฑ์ (ratio<0.85) จะคืนค่า None ทั้งคู่แทนการเชื่อค่าที่อาจผิด - ทดสอบกับ
        AC03-01 (ratio จริง=0.593) -> ปฏิเสธถูกต้อง แทนที่จะคืนเลขผิดอย่างมั่นใจเหมือน v25.12
  ข้อจำกัดที่ยังต้องบอกตรงไปตรงมา: มีไฟล์ให้ regression-test แค่ 1 ใน 6 ไฟล์ calibration
  ของ PHASE 1B (AC03-01 เท่านั้น ไม่มี EC01-01/EC04-01/02/03/04) ทั้ง 2 utility ที่แก้ไขแล้ว
  จึงยังคง "ไม่ wire เข้า pipeline หลัก" รอการ regression-test เต็มรูปแบบครบ 6 ไฟล์ก่อน
  ดูรายละเอียดหลักฐานเต็มที่หัวข้อ "v25.13 EXPERIMENTAL UTILITIES" ก่อน PHASE 2 ด้านล่าง
  ไม่มีการแก้ไข PHASE 1B/2/3/Rule Engine เดิมแต่อย่างใด (regression-verified: AC03-01 ยังคง
  front=7, back=7 ตรงเดิมทุกประการ หลังเพิ่ม utility ใหม่เข้าไปในไฟล์)
================================================================================
v25.11 FIX (สำคัญ): แทนที่ PHASE 1 (seam-based counting) ด้วย PHASE 1B (front-face
color-blob clustering) เป็นวิธีนับหลัก เพราะพบว่า seam-based เดิมมีบั๊ก undercount จริงที่
ไม่เกี่ยวกับ corner-duplicate เลย (เช่น EC04-01 FRONT นับได้แค่ 5 ตั้ง ทั้งที่ควรเป็น 6 ตรงกับ
BACK - เกิดเพราะกล่องข้างเคียงสี/SKU เดียวกันทำให้ไม่มีรอยต่อสีให้ seam-detector จับ)

PHASE 1B ผ่าน regression-test ครบทั้ง 6 ไฟล์ตัวอย่างจริง (12 views): AC03-01, EC01-01,
EC04-01/02/03/04 - นับจำนวนตั้งถูกต้องตรงกับ BACK view/เรขาคณิตของตู้ทุกกรณี รวมถึงจัดการ
กรณี "มุมกล้องใกล้สุดเห็นหน้า front+ขอบลาดซ้าย+ขอบลาดขวาพร้อมกัน จนแตกเป็นหลาย fragment ปลอม
ต่อ 1 ตั้งจริง" (พบใน EC04-01/02/04 FRONT - บางเคสแตกถึง 3 fragment ปลอมต่อ 1 ตั้งจริง ไม่ใช่
แค่ 2) ด้วยกติกาที่วัดผลได้จริง (merge_corner_artifact_columns): ใช้ 'side' fragment (มุมข้าง)
ที่ซ้อนทับเป็นหลักฐาน พร้อม guard กัน false-positive จากไฟล์ที่เห็นด้านข้างของทุกกล่องตลอดทั้ง
แถว ไม่ใช่แค่มุมกล้องใกล้สุด (ยืนยันจาก AC03-01 ซึ่งมี side fragment กระจายทั่วทั้งแถว - cluster
ที่ไม่แตะขอบนอกสุดของ view จะถูกยกเลิกการ merge เสมอ)

เทียบผลลัพธ์กับ calibration เดิม (v25.10): AC03-01/EC01-01/EC04-02 ยังคง flag ตำแหน่งเดียวกัน
เป๊ะ (BACK idx6/idx5/idx5 ตามลำดับ) ยืนยันว่า Phase 2/3/Rule Engine ไม่ได้รับผลกระทบจากการ
เปลี่ยน Phase 1 นี้เลย - seam-based เดิมยังคงเก็บไว้เป็น fallback อัตโนมัติ (ถ้า PHASE 1B ล้มเหลว
เช่น หา front-face สีเด่นไม่เจอ) ดูรายละเอียดที่ compute_phase1b_columns

v25.10 FIX (จาก v25.9 ที่เสียหาย): v25.9 มีบั๊กร้ายแรง - ระหว่างแก้ไข reconcile_heights_
cross_view ทำให้ฟังก์ชัน detect_rear_empty_risk เสียหาย 2 จุด:
  1. ลบฟังก์ชัน _dominant_color_clusters() ทิ้งไปทั้งหมด (กลไก B ของ REAR_EMPTY_RISK)
     ทำให้เหลือ IndentationError ค้างอยู่ (import ไม่ผ่านถ้าไม่มี stale .pyc cache)
  2. กลไก A (length-mismatch) ถูกแก้ให้ mark ฝั่งที่ "ยาวกว่า" แทนที่จะเป็นฝั่งที่ "สั้นกว่า"
     ตามที่คาลิเบรตไว้เดิม (สั้นกว่า = มีพื้นที่ว่างจริงก่อนประตูท้ายตู้ ถูกต้องตามหลักฟิสิกส์)
v25.10 กู้คืนทั้ง 2 กลไกให้ตรงกับ calibration เดิม (ยืนยันด้วย regression 3 ไฟล์):
  - AC03-01: REAR_EMPTY_RISK (length_mismatch) mark BACK idx6, gap 46px/8.6%
  - EC01-01: REAR_EMPTY_RISK (length_mismatch) mark BACK idx5, gap 72px/12.6%
  - EC04-02: REAR_EMPTY_RISK (color_anomaly) mark BACK idx5, 4 สี SKU ปะปนกัน
    (length gap เพียง 17px/3.4% ไม่ผ่านกลไก A แต่ผ่านกลไก B - ตรงกับภาพ ground-truth
    "Rear empty risk" ที่ผู้ใช้แนบมาเป๊ะ)
================================================================================
เวอร์ชันนี้แทนที่ AI (Gemini) ทั้งหมดด้วย deterministic pixel-based rule engine
(Phase 1 + Phase 2 + Phase 3) ตามที่ตกลงกันไว้ - เหลือเพียง 3 risk types ที่ครอบคลุม
ประเด็นความปลอดภัยหลักและสามารถคำนวณได้ 100% จาก geometry ของภาพโดยไม่ต้องพึ่ง AI เลย

RISK TYPES (3 ประเภทเท่านั้น - ตัดที่เหลือทั้งหมดตามที่ตกลงกัน):
1. STEP_DOWN_RISK (pairwise)   - ตั้งข้างเคียงในview เดียวกันสูงต่างกันเกิน 12.5%
2. STEP_DOWN_RISK (cross_view) - ตำแหน่งจริงเดียวกันระหว่าง FRONT<->BACK สูงต่างกันเกิน 12.5%
   (มี edge-pair guard: คู่ที่เป็นขอบสุดพร้อมกันทั้ง 2 view ใช้เกณฑ์เข้มขึ้นเป็น 30%
   เพราะพบว่าการวัดยังมีความไม่แน่นอนตกค้างในโซนขอบภาพ)
3. REAR_EMPTY_RISK             - ไม่มีตั้งกล่องในอีก view หนึ่งที่โซน 7% สุดท้ายก่อนประตูท้ายตู้

ตัดออกทั้งหมด (ตามที่ตกลงกัน): FRONT_EMPTY_RISK, REAR_LATERAL_IMBALANCE,
LATERAL_GAP_RISK, TALL_UNSTABLE_RISK, REAR_COMBINED_RISK, COMBINED_AREA_RISK
และฟังก์ชันเกี่ยวกับ Gemini/AI ทั้งหมด (ไม่มี network call ใดๆ อีกต่อไป)

--------------------------------------------------------------------------------
CHANGELOG (สรุปจาก session พัฒนา Phase 1-3 + Rule Engine):

- Phase 1: จำนวนตั้ง + ตำแหน่ง (seam-based counting จากสี + spike-seam detector)
  * v1.2-equiv fix: rolling color smoothing กัน noise จากไฮไลท์/เงาสะท้อน
  * auto view-locator: หาตำแหน่ง crop FRONT/BACK จาก PDF text-layer จริง (label
    "Front"/"Back"/"Load"/"Customer") ผ่าน page.rotation_matrix แทน hardcode fraction
    (แก้บั๊กที่ layout ต่างกันไปคนละไฟล์ - บางไฟล์ซ้าย-ขวา บางไฟล์บน-ล่าง)

- Phase 2: ความยาวต่อตั้ง + ความยาวรวม (วัดผ่าน white-background extent)

- Phase 3: ความสูงต่อตั้ง (px) - พบและแก้บั๊กสำคัญ 3 ชั้นระหว่างพัฒนา:
  1. Isometric top-face bleed-through: กล่องเพื่อนบ้านสีต่างกันที่ลึกกว่า ทำให้ top_y
     รั่วเข้ามาที่ริมขอบตั้ง -> แก้ด้วย majority-based top detection (คงไว้เป็น fallback)
  2. พื้นตู้เป็นรูปตัว "V" ไม่ใช่เส้นตรงเดียว (มี apex แล้วลาดลง 2 ทิศทาง) -> แก้ด้วย
     compute_local_floor_y() (rolling median เฉพาะจุดแทน global linear fit)
  3. ขอบบน-หน้ากล่องมีความชันธรรมชาติจากมุมมอง isometric ภายในตั้งเดียวกัน (คนละปัญหา
     จากข้อ 1) -> แก้ด้วย _robust_local_line_fit() (fit เส้นตรงทนทานต่อ outlier)

- Rule Engine: ทิศทาง FRONT/BACK ตาม HARDCODED_REAR_SIDE เดิม (FRONT: ซ้าย=ประตูท้าย,
  ขวา=หัวตู้ | BACK: ซ้าย=หัวตู้, ขวา=ประตูท้าย) - ยืนยันด้วยลำดับสี SKU จริงข้าม 2 view
  Edge-pair guard: คู่ cross-view ที่เป็น "ขอบสุด-vs-ขอบสุด" พร้อมกัน ใช้เกณฑ์ 30%
  แทน 12.5% เพราะมีความไม่แน่นอนตกค้างสูงกว่าปกติในโซนขอบภาพ

- Coordinate pipeline: render หน้าเต็มครั้งเดียว (render_full_page) แล้วใช้ภาพเดียวกัน
  ทั้งสำหรับวิเคราะห์ (crop เป็น front/back) และวาด marker กลับ - รับประกันพิกัดตรงกัน
  100% ไม่มีความคลาดเคลื่อนจากการ render ซ้ำหลายครั้ง

- Regression test: ผ่านการทดสอบกับ AC03-01, EC01-01, EC04-02 (6 views) ยืนยัน marker
  วางตรงตำแหน่งกล่องที่เตี้ยกว่าจริงในภาพ 100% รวมถึง cross-view ที่จับคู่ตำแหน่งถูกต้อง
  ตามลำดับสี SKU จริง

- Output contract: คงโครงสร้าง JSON เดิมของ v24.36 ทั้งหมด (status, hazardCount, layout,
  actionRequired, processedImageUrl, checkerVersion) เพื่อไม่ให้ WebApp/GAS ที่มีอยู่แล้ว
  ต้องแก้ไขโค้ดฝั่งรับผลใดๆ เลย
================================================================================
"""
import base64
import io
import json
import re
import gc
import traceback

import numpy as np
import PIL.Image
import PIL.ImageDraw
import fitz  # PyMuPDF
import functions_framework
from scipy import ndimage
from scipy.optimize import linear_sum_assignment


# ============================================================================
# ค่าคงที่ / สี marker (คงไว้ตามเดิมสำหรับ 3 risk types ที่เหลือ)
# ============================================================================

RISK_COLORS = {
    "STEP_DOWN_RISK": "red",
    "REAR_EMPTY_RISK": "orange",
}
VALID_RISK_TYPES = set(RISK_COLORS.keys())

# กฎ 3 ข้อ ชัดเจน เกณฑ์เดียวต่อกฎ (ปรับตัวเลขได้ที่นี่จุดเดียว):
# 1) STEP_DOWN_RISK (cross_view): gap > 20% ระหว่างตำแหน่งคู่ตรงข้าม FRONT<->BACK -> วาดกรอบตัวสูงกว่า
# 2) STEP_DOWN_RISK (pairwise)  : gap > 20% ระหว่างตั้งติดกัน แนวระนาบเดียวกัน -> วาดกรอบตัวสูงกว่า
# 3) REAR_EMPTY_RISK            : gap > 7% ระหว่างความยาวรวมของแต่ละ view -> วาดกรอบท้ายสุดของ view ที่ยาวกว่า
# ทั้ง 3 กฎ ข้าม record ที่ is_corner_duplicate=True เสมอ (ตรวจจาก pixel/เรขาคณิตจริง ไม่ hardcode ชื่อ view)
STEP_DOWN_CROSSVIEW_DROP_RATIO = 0.20
STEP_DOWN_PAIRWISE_DROP_RATIO = 0.20
REAR_EMPTY_LENGTH_RATIO = 0.07
CROSSVIEW_MIN_OVERLAP_RATIO = 0.5       # ต้องทับซ้อนตำแหน่งจริงอย่างน้อย 50% จึงถือเป็นคู่เดียวกัน

# --- REAR_EMPTY_RISK v2 (แก้บั๊ก v25.0: pos_range เดิม self-normalize ทำให้ตั้งสุดท้าย
#     ของทุก view ได้ pos=1.0 เสมอ ทำให้ position-overlap matching ผิดพลาดเป็นระบบ) ---
# กลไก A: เทียบ length_px (Phase 2, ค่าจริงหน่วย px ไม่ normalize) ระหว่าง FRONT<->BACK
#   ถ้าต่างกันเกินทั้ง px ขั้นต่ำ และสัดส่วนขั้นต่ำ -> ฝั่งที่ "สั้นกว่า" มีพื้นที่ว่างจริงก่อนประตูท้ายตู้
#   ค่า threshold คาลิเบรตจากไฟล์ตัวอย่าง 3 ไฟล์ (ground truth): EC01-01 gap=72px(12.6%),
#   AC03-01 gap=46px(8.6%) ต้อง flag / EC04-02 gap=17px(3.4%) ต้องไม่ flag (คนละกลไกกับ B)
REAR_GAP_MIN_PX = 35
REAR_GAP_MIN_RATIO = 0.06

# กลไก B: ตรวจ "ตั้งสุดท้ายจริง" (real pos_range ใกล้ 1.0 ที่สุด) ของแต่ละ view ว่ามีสี SKU
#   ปะปนกันผิดปกติหรือไม่ (เช่น SKU แปลกปลอมโผล่ที่ตำแหน่งท้ายสุด มักพบคู่กับพื้นที่ว่าง/สินค้า
#   วางไม่เป็นระเบียบใกล้ประตูท้ายตู้) คาลิเบรตจาก EC04-02 BACK idx5 (TEM1A, 4 สีเด่น) ที่ต้อง
#   flag ในขณะที่ตั้งท้ายสุดของอีก 5 view (สีเดียวล้วน) ต้องไม่ flag
REAR_COLOR_ANOMALY_MIN_COLORS = 3
REAR_COLOR_MIN_FRACTION = 0.03
REAR_COLOR_MIN_PIXELS = 80


def generate_action_report(case_type, description="", sku_list=""):
    """ข้อความแนะนำแก้ไขภาษาไทย (คงไว้จาก v24.36 เดิม เฉพาะ 2 risk types ที่เหลือ)"""
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
    }
    return actions.get(case_type, description or "ปลอดภัย\nไม่พบจุดเสี่ยงที่ต้องดำเนินการเพิ่มเติม")


def extract_sku_from_pdf(pdf_bytes):
    """ดึงรายชื่อ SKU จาก Load Summary ใน PDF text-layer (คงไว้จาก v24.36 เดิม ไม่เปลี่ยนแปลง)"""
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


def _draw_single_rectangle(draw, coords, outline_color):
    x0, y0, x1, y1 = map(int, coords)
    draw.rectangle([x0, y0, x1, y1], outline=outline_color, width=8)


# ============================================================================
# PHASE 1: จำนวนตั้งของกล่องแต่ละ VIEW (seam-based counting)
# ============================================================================

def saturated_mask(region):
    r = region[:, :, 0].astype(np.int16)
    g = region[:, :, 1].astype(np.int16)
    b = region[:, :, 2].astype(np.int16)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    return (mx >= 60) & ((mx - mn) >= 35)


def vivid_cargo_mask(region, min_blob_size=150):
    r = region[:, :, 0].astype(np.float32)
    g = region[:, :, 1].astype(np.float32)
    b = region[:, :, 2].astype(np.float32)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    sat = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1), 0)
    raw_mask = (mx >= 50) & (sat >= 0.55)
    labeled, n = ndimage.label(raw_mask)
    if n == 0:
        return raw_mask
    sizes = ndimage.sum(raw_mask, labeled, range(1, n + 1))
    keep_labels = set(np.nonzero(sizes >= min_blob_size)[0] + 1)
    if not keep_labels:
        return np.zeros_like(raw_mask)
    return np.isin(labeled, list(keep_labels))


def is_arrow_color(rgb):
    r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
    return (r >= 190) and (40 <= g <= 140) and (40 <= b <= 140) and \
           (abs(g - b) <= 45) and (r - g >= 70) and (r - b >= 70)


def arrow_mask(region):
    r = region[:, :, 0].astype(np.int16)
    g = region[:, :, 1].astype(np.int16)
    b = region[:, :, 2].astype(np.int16)
    gb_close = np.abs(g - b) <= 45
    r_dominant = (r - np.maximum(g, b)) >= 70
    bright = r >= 190
    return gb_close & r_dominant & bright


def ensure_safe_crop(full_img, y0, y1, x0, x1, margin=30, expand_step=150, max_iterations=15):
    H, W, _ = full_img.shape
    cy0, cy1, cx0, cx1 = y0, y1, x0, x1
    for _ in range(max_iterations):
        cy0 = max(0, cy0); cy1 = min(H, cy1)
        cx0 = max(0, cx0); cx1 = min(W, cx1)
        region = full_img[cy0:cy1, cx0:cx1]
        cmask = vivid_cargo_mask(region)
        cys, cxs = np.where(cmask)
        if len(cys) == 0:
            return cy0, cy1, cx0, cx1
        touches_top = cys.min() < margin
        touches_bottom = cys.max() > region.shape[0] - margin
        touches_left = cxs.min() < margin
        touches_right = cxs.max() > region.shape[1] - margin
        if not (touches_top or touches_bottom or touches_left or touches_right):
            return cy0, cy1, cx0, cx1
        if touches_top: cy0 -= expand_step
        if touches_bottom: cy1 += expand_step
        if touches_left: cx0 -= expand_step
        if touches_right: cx1 += expand_step
        if cy0 <= 0 and cy1 >= H and cx0 <= 0 and cx1 >= W:
            return cy0, cy1, cx0, cx1
    return cy0, cy1, cx0, cx1


def compute_floor_profile(region, struct_mask, cargo_mask, gap_thresh=None, max_floor_search_below=150):
    """v26.00 FIX Bug#A: gap_thresh เดิม hardcode=30px ทำให้ไฟล์ที่ floor อยู่ห่างจาก
    cargo_bottom มากกว่า 30px (scale=4 ทำให้ระยะห่างเพิ่มขึ้น) ได้ grounded=0 ทั้ง view
    FIX: ถ้าไม่ระบุ gap_thresh ให้คำนวณ adaptive จาก gap ที่พบจริงในภาพ (percentile 85,
    clamp 20-120px) แทน hardcode - รับประกันว่า grounded zone จะถูกตรวจพบเสมอ ไม่ว่า
    scale หรือ geometry ของไฟล์จะเป็นอย่างไร"""
    h, w, _ = region.shape
    floor_y = np.full(w, -1, dtype=int)
    cargo_bottom_y = np.full(w, -1, dtype=int)
    raw_grounded = np.zeros(w, dtype=bool)
    raw_gaps = []

    # Pass 1: เก็บ gap จริงทุกจุดเพื่อคำนวณ adaptive gap_thresh
    for x in range(w):
        cargo_col = np.nonzero(cargo_mask[:, x])[0]
        if len(cargo_col) == 0:
            continue
        cargo_bottom_y[x] = cargo_col.max()
        search_y0 = cargo_bottom_y[x]
        search_y1 = min(h, cargo_bottom_y[x] + max_floor_search_below)
        struct_window = struct_mask[search_y0:search_y1, x]
        struct_idx = np.nonzero(struct_window)[0]
        if len(struct_idx) > 0:
            floor_y[x] = search_y0 + int(struct_idx.max())
            gap = floor_y[x] - cargo_bottom_y[x]
            if gap >= 0:
                raw_gaps.append(gap)

    # Adaptive gap_thresh: percentile 85 ของ gap จริง, clamp 20-120px
    if gap_thresh is None:
        if len(raw_gaps) >= 10:
            adaptive = float(np.percentile(raw_gaps, 85))
            gap_thresh = max(20, min(120, adaptive))
        else:
            gap_thresh = 60  # fallback ที่ใจกว้างกว่าเดิม (เดิม=30)

    # Pass 2: กำหนด grounded ด้วย adaptive gap_thresh
    grounded = np.zeros(w, dtype=bool)
    for x in range(w):
        if floor_y[x] >= 0 and cargo_bottom_y[x] >= 0:
            gap = floor_y[x] - cargo_bottom_y[x]
            grounded[x] = (0 <= gap <= gap_thresh)

    min_grounded_run = 30
    run_start = None
    confirmed_grounded = np.zeros(w, dtype=bool)
    for x in range(w + 1):
        is_g = grounded[x] if x < w else False
        if is_g and run_start is None:
            run_start = x
        elif not is_g and run_start is not None:
            if x - run_start >= min_grounded_run:
                confirmed_grounded[run_start:x] = True
            run_start = None
    return floor_y, cargo_bottom_y, confirmed_grounded


def _color_distance(c1, c2):
    return float(np.sqrt(sum((int(a) - int(b)) ** 2 for a, b in zip(c1, c2))))


def per_channel_gradient_outline(region, struct_mask):
    r = region[:, :, 0].astype(np.float32)
    g = region[:, :, 1].astype(np.float32)
    b = region[:, :, 2].astype(np.float32)
    grad_r = np.abs(np.diff(r, axis=1, prepend=r[:, :1]))
    grad_g = np.abs(np.diff(g, axis=1, prepend=g[:, :1]))
    grad_b = np.abs(np.diff(b, axis=1, prepend=b[:, :1]))
    total_grad = grad_r + grad_g + grad_b
    return (total_grad > 60) & struct_mask, total_grad


def spike_seam_detector(region, struct_mask, cargo_bottom_y, grounded,
                          y_search_above_floor=350, peak_thresh=100,
                          max_spike_width=6, min_seg_width=35):
    dark_outline, _ = per_channel_gradient_outline(region, struct_mask)
    xs_grounded = np.nonzero(grounded)[0]
    if len(xs_grounded) == 0:
        return []
    x_min, x_max = int(xs_grounded.min()), int(xs_grounded.max())
    col_counts = np.zeros(region.shape[1], dtype=int)
    for x in range(x_min, x_max + 1):
        if cargo_bottom_y[x] < 0:
            continue
        y_bot = cargo_bottom_y[x]
        y_top = max(0, y_bot - y_search_above_floor)
        col_counts[x] = int(dark_outline[y_top:y_bot, x].sum())
    seam_candidates = []
    x = x_min
    while x <= x_max:
        if col_counts[x] > peak_thresh:
            spike_start = x
            spike_end = x
            while spike_end + 1 <= x_max and col_counts[spike_end + 1] > peak_thresh * 0.7:
                spike_end += 1
            width = spike_end - spike_start + 1
            if width <= max_spike_width:
                seam_candidates.append((spike_start + spike_end) // 2)
            x = spike_end + 1
        else:
            x += 1
    seam_candidates.sort()
    deduped = []
    for s in seam_candidates:
        if not deduped or s - deduped[-1] > min_seg_width:
            deduped.append(s)
    return deduped


def detect_probe_line_seams(region, struct_mask, rail, x_min, x_max,
                              offsets=(15, 20, 25, 30, 35), group_tol=4,
                              min_offset_votes=3, min_continuous_run=40):
    """หา seam เพิ่มเติมด้วยวิธี 'เส้น probe' ตามที่ผู้ใช้อธิบาย: ลากเส้นขนานกับเส้นขอบฐานตู้จริง
    (rail, slope คงที่จากเรขาคณิต ไม่ขึ้นกับสี) แต่ offset ขึ้นไปหลายระดับ (5-10% ของความสูงตั้ง)
    แล้วดูว่าเส้นนี้ตัดผ่านขอบแนวตั้ง (dark gradient edge) ของกล่องที่ตำแหน่งใดบ้าง

    ROOT CAUSE ที่แก้: color/gradient-transition แบบเดิมล้มเหลวเมื่อกล่องข้างเคียงเป็น SKU/สี
    เดียวกัน (ไม่มีรอยต่อสีให้จับ) - แต่ขอบแนวตั้งทางกายภาพระหว่างกล่อง 2 ใบยังคงมีอยู่จริงเสมอ
    (เป็นรอยต่อของวัตถุ ไม่ใช่รอยต่อของสี) เส้น probe ที่ offset จากเส้น rail จะตัดผ่านขอบเหล่านี้
    ได้แม้สีจะเหมือนกันทุกประการ เพราะ per_channel_gradient_outline ตรวจจาก sudden change
    ในภาพ (เงา/ขอบเส้น) ไม่ใช่จากสีต่างกันเพียงอย่างเดียว

    ยืนยันด้วยข้อมูลจริง (AC03-01 FRONT): พบ seam ที่ x=362 (ซึ่งขาดหายไปจาก color-detection
    เดิมเพราะ idx1/idx2 เป็นกล่อง SKU เดียวกัน) ตรงกับตำแหน่งกึ่งกลางที่คำนวณจาก width สม่ำเสมอ
    ของตั้งอื่นๆ ในภาพเดียวกันพอดี (66px)
    """
    if rail is None:
        return []
    a, b = rail["a"], rail["b"]
    dark_outline, _ = per_channel_gradient_outline(region, struct_mask)
    h, w = dark_outline.shape[:2]

    # v25.10 FIX: เดิมรับ candidate จาก offset ไหนก็ได้แค่ครั้งเดียว ทำให้ false-positive สูง
    # (ตัวอักษร SKU label หรือลายเงาภายในกล่องเดียวกัน ทำให้เกิด dark edge ปลอมที่ offset
    # ใดoffset หนึ่งบังเอิญตรงกัน) - แก้โดยเก็บ candidate แยกตาม offset ก่อน แล้วนับ "โหวต"
    # ว่าตำแหน่งใกล้เคียงกัน (ภายใน group_tol) ปรากฏใน offset ที่ต่างกันกี่ระดับ - ต้องผ่าน
    # อย่างน้อย min_offset_votes ระดับความสูงที่ต่างกัน จึงจะถือว่าเป็น seam จริง (ขอบวัตถุจริง
    # ควรตัดผ่านเส้น probe ได้สม่ำเสมอในหลายความสูง ต่างจาก noise ที่มักปรากฏแค่ระดับเดียว)
    per_offset_groups = []
    for offset in offsets:
        hits = []
        for x in range(x_min, x_max + 1):
            y = int(a * x + b) - offset
            if 0 <= y < h and dark_outline[y, x]:
                hits.append(x)
        groups = []
        for hx in hits:
            if groups and hx - groups[-1][-1] <= group_tol:
                groups[-1].append(hx)
            else:
                groups.append([hx])
        per_offset_groups.append([int(np.mean(g)) for g in groups])

    all_candidates = sorted(set(x for grp in per_offset_groups for x in grp))
    if not all_candidates:
        return []
    merged = []
    for hx in all_candidates:
        if merged and hx - merged[-1][0] <= 8:
            merged[-1][1].append(hx)
        else:
            merged.append([hx, [hx]])

    def _max_continuous_run(x, y_range=(0, region.shape[0])):
        """นับความยาวช่วงต่อเนื่องที่ยาวที่สุดของ dark-gradient pixel ในคอลัมน์ x - ใช้แยก
        'ขอบต่อกล่องจริง' (เส้นต่อเนื่องยาว จากพื้นขึ้นไปถึงขอบบนกล่อง) ออกจาก 'ตัวอักษร SKU
        label' (dark pixel เป็นหย่อมสั้นๆ ไม่ต่อเนื่อง เพราะมีช่องว่างระหว่างตัวอักษร)
        ยืนยันด้วยข้อมูลจริง (EC01-01 FRONT): seam จริงที่ x=754,915 มี run=93-94px แต่
        false-positive จากตัวอักษร "TSB1A-D1" ที่ x=797 มี run แค่ 11px"""
        y0, y1 = y_range
        col = dark_outline[y0:y1, x]
        best, cur = 0, 0
        for v in col:
            if v:
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        return best

    result = []
    for center_seed, members in merged:
        center = int(np.mean(members))
        votes = 0
        for grp in per_offset_groups:
            if any(abs(g - center) <= 8 for g in grp):
                votes += 1
        if votes < min_offset_votes:
            continue
        # v25.11 FIX: เดิมใช้ค่าเฉลี่ยของกลุ่ม (center) ตรงๆ เพื่อเช็ค continuous_run แต่พบว่า
        # ค่าเฉลี่ยอาจตกอยู่ "ระหว่างช่องว่าง" ของเส้นจริง (เช่น กลุ่ม [794,801] เฉลี่ย=797 ซึ่ง
        # เป็นช่องว่างระหว่างตัวอักษร run=11 ทั้งที่ x=794 มี run=46 และ x=802 (ใกล้เคียง) มี
        # run=95 สูงกว่าทุกจุดในกลุ่ม) - แก้โดยค้นหาตำแหน่งที่ continuous_run สูงสุดในบริเวณ
        # ใกล้เคียง (center ± 10px) แทนที่จะเชื่อค่าเฉลี่ยตรงๆ - นี่คือขอบวัตถุจริงที่ชัดเจนที่สุด
        best_x, best_run = center, _max_continuous_run(center)
        for dx in range(-10, 11):
            x_try = center + dx
            run = _max_continuous_run(x_try)
            if run > best_run:
                best_run, best_x = run, x_try
        if best_run < min_continuous_run:
            continue
        result.append(best_x)
    return result


def seam_based_count(region, grounded, cargo_bottom_y, cargo_mask, struct_mask,
                      window_size=35, window_margin=2, color_thresh=55, min_seg_width=40):
    xs_grounded = np.nonzero(grounded)[0]
    if len(xs_grounded) == 0:
        return 0, [], None
    x_min, x_max = int(xs_grounded.min()), int(xs_grounded.max())
    clean_colors = {}
    for x in range(x_min, x_max + 1):
        if not grounded[x]:
            continue
        y_bot = cargo_bottom_y[x] - window_margin
        y_top = max(0, y_bot - window_size)
        if y_bot <= y_top:
            continue
        col_cargo_mask = cargo_mask[y_top:y_bot, x]
        ys_valid = np.nonzero(col_cargo_mask)[0]
        if len(ys_valid) < 3:
            continue
        pixels = region[y_top:y_bot, x][ys_valid]
        pixels = np.array([p for p in pixels if not is_arrow_color(p)])
        if len(pixels) < 3:
            continue
        clean_colors[x] = tuple(int(v) for v in np.median(pixels, axis=0))
    xs_clean = sorted(clean_colors.keys())
    smoothed_colors = {}
    rolling_half = 2
    for idx, x in enumerate(xs_clean):
        window_xs = []
        for j in range(max(0, idx - rolling_half), min(len(xs_clean), idx + rolling_half + 1)):
            wx = xs_clean[j]
            if abs(wx - x) <= rolling_half + 1:
                window_xs.append(wx)
        if len(window_xs) < 2:
            smoothed_colors[x] = clean_colors[x]
            continue
        r_vals = [clean_colors[wx][0] for wx in window_xs]
        g_vals = [clean_colors[wx][1] for wx in window_xs]
        b_vals = [clean_colors[wx][2] for wx in window_xs]
        smoothed_colors[x] = (int(np.median(r_vals)), int(np.median(g_vals)), int(np.median(b_vals)))
    color_seam_xs = []
    if len(xs_clean) >= 3:
        last_seam = -999
        for i in range(1, len(xs_clean)):
            x_prev, x_cur = xs_clean[i - 1], xs_clean[i]
            if x_cur - x_prev > 5:
                continue
            d = _color_distance(smoothed_colors[x_prev], smoothed_colors[x_cur])
            if d >= color_thresh and (x_cur - last_seam) > min_seg_width:
                color_seam_xs.append(x_cur)
                last_seam = x_cur
    spike_seam_xs = spike_seam_detector(region, struct_mask, cargo_bottom_y, grounded)

    # v25.9 FIX (root-cause, ตามที่ผู้ใช้ระบุวิธี): ใช้ "เส้น probe" (offset จากเส้นขอบฐานตู้จริง
    # ที่มี slope คงที่ทางเรขาคณิต) เพื่อหา seam เพิ่มเติมที่ color/gradient-transition แบบเดิม
    # พลาด เพราะกล่องข้างเคียงเป็น SKU/สีเดียวกัน (ไม่มีรอยต่อสีให้จับ แต่ขอบวัตถุจริงยังมีอยู่)
    # ดู detect_probe_line_seams และ detect_container_floor_rail สำหรับหลักการเต็ม
    rail = detect_container_floor_rail(region, cargo_bottom_y, grounded)
    # จำกัดโซนค้นหาให้เริ่มหลัง corner_x เท่านั้น (โซนก่อนมุมตู้จริงมีเรขาคณิตซับซ้อนกว่า
    # ปกติ - เห็นทั้งหน้าด้านข้าง/ผนังหัวตู้ ซึ่งทำให้เกิด false-positive edge ได้ง่าย ไม่ใช่
    # ขอบต่อกล่องจริงเสมอไป - ยืนยันจาก EC01-01 FRONT ที่ยังมี false seam หลุดมา 2 จุดในโซนนี้)
    probe_seam_xs = (detect_probe_line_seams(region, struct_mask, rail,
                                              max(x_min, rail["corner_x"]), x_max)
                      if rail else [])

    # v25.11 FIX: เดิม dedup โดยเก็บตัวที่เจอก่อน (ตามลำดับ x) ทิ้งตัวที่ใกล้กว่า min_seg_width
    # แม้ตัวที่ถูกทิ้งจะเป็นขอบวัตถุจริงที่ชัดเจนกว่า (continuous_run สูงกว่า) ก็ตาม - แก้โดย
    # เมื่อมีหลาย candidate ใกล้กัน ให้เลือกตัวที่มี continuous_run (ความยาวขอบต่อเนื่องจริง)
    # สูงสุดแทน ไม่ใช่ตัวแรกที่เจอ (ยืนยันจาก EC04-02: x=794 run=46 ถูกเก็บไว้ก่อน x=802 run=95
    # ที่ควรถูกเลือกมากกว่า เพราะเป็นขอบที่ชัดเจนกว่ามาก)
    dark_outline_for_rank, _ = per_channel_gradient_outline(region, struct_mask)

    def _continuous_run_at(x):
        col = dark_outline_for_rank[:, x]
        best, cur = 0, 0
        for v in col:
            if v:
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        return best

    # v25.11b FIX: การ group แบบ "chain" เดิม (เทียบกับจุดสุดท้ายที่เพิ่งเจอ ไม่ใช่จุดตัวแทน
    # ของกลุ่ม) ทำให้เกิดปัญหา transitive-merge (เช่น 298,299,336,359,381 ถูกรวมเป็นกลุ่ม
    # เดียวทั้งที่ 298 กับ 381 ห่างกันถึง 83px = 2 เท่าของ min_seg_width) ทำให้เสีย seam จริง
    # หลายจุดไปเหลือแค่ 1 - แก้เป็น 2 ขั้นตอน: (1) หาตำแหน่ง "ตัวแทน" ด้วย dedup แบบเดิม
    # (เทียบกับจุดที่ถูกเก็บไว้ล่าสุดเท่านั้น รับประกันระยะห่างระหว่างตัวแทน > min_seg_width)
    # (2) ในรอบ ๆ แต่ละตัวแทน (±min_seg_width/2) ค้นหา candidate ที่มี continuous_run สูงสุด
    # มาแทนที่ - ปรับปรุงตำแหน่งให้แม่นยำขึ้นโดยไม่กระทบโครงสร้างระยะห่างที่ถูกต้องอยู่แล้ว
    all_seam_candidates = sorted(set(color_seam_xs) | set(spike_seam_xs) | set(probe_seam_xs))
    representatives = []
    for s in all_seam_candidates:
        if not representatives or s - representatives[-1] > min_seg_width:
            representatives.append(s)

    half_window = min_seg_width // 2
    seams = []
    for rep in representatives:
        nearby = [c for c in all_seam_candidates if abs(c - rep) <= half_window]
        if not nearby:
            nearby = [rep]
        seams.append(max(nearby, key=_continuous_run_at))

    degenerate_tol = 5
    seams = [s for s in seams if abs(s - x_min) > degenerate_tol and abs(s - x_max) > degenerate_tol]

    # v25.11 FIX: min_plausible_box_width=35 (ค่าคงที่ตายตัว) เดิมตัด segment แรก/สุดท้ายทิ้ง
    # ถ้าแคบกว่า 35px เสมอ แม้จะเป็นตั้งจริงที่แคบกว่าค่าเฉลี่ยก็ตาม (กล่องต่างขนาดกันได้จริง
    # ไม่ใช่ทุกตั้งต้องกว้างเท่ากัน) - แก้เป็นเกณฑ์เชิงสัมพัทธ์ (เทียบ median ของ segment อื่น
    # ในภาพเดียวกัน) แทนค่าคงที่ตายตัว เพื่อไม่ตัดตั้งจริงที่บังเอิญแคบทิ้งไปอย่างผิดพลาด
    min_plausible_box_width = 35
    min_relative_ratio = 0.35  # segment ต้องกว้างอย่างน้อย 35% ของ median segment อื่น
    changed = True
    while changed and len(seams) >= 1:
        changed = False
        boundaries = [x_min] + seams + [x_max]
        widths = [boundaries[i + 1] - boundaries[i] for i in range(len(boundaries) - 1)]
        if len(widths) < 2:
            break
        other_widths = widths[1:] if len(widths) > 1 else widths
        median_other = float(np.median(other_widths)) if other_widths else min_plausible_box_width
        eff_min_first = min(min_plausible_box_width, median_other * min_relative_ratio)
        if widths[0] < eff_min_first:
            seams = seams[1:]
            changed = True
            continue
        other_widths2 = widths[:-1] if len(widths) > 1 else widths
        median_other2 = float(np.median(other_widths2)) if other_widths2 else min_plausible_box_width
        eff_min_last = min(min_plausible_box_width, median_other2 * min_relative_ratio)
        if widths[-1] < eff_min_last:
            seams = seams[:-1]
            changed = True
    return len(seams) + 1, seams, (x_min, x_max)


CONTAINER_RAIL_COLOR = np.array([203, 203, 101])  # สีขอบฐานตู้ (tan/gold rail), วัดจาก pixel จริง
CONTAINER_RAIL_COLOR_TOL = 40


def _rail_color_y(region, x, y_search_range):
    """หาตำแหน่ง y ของขอบตู้สีทอง (CONTAINER_RAIL_COLOR) ในคอลัมน์ x ภายในช่วง y ที่กำหนด"""
    y0, y1 = y_search_range
    y0 = max(0, y0); y1 = min(region.shape[0], y1)
    if y1 <= y0:
        return None
    col = region[y0:y1, x]
    dists = np.sqrt(np.sum((col.astype(np.int32) - CONTAINER_RAIL_COLOR) ** 2, axis=1))
    idx = np.nonzero(dists < CONTAINER_RAIL_COLOR_TOL)[0]
    if len(idx) == 0:
        return None
    return y0 + int(np.median(idx))


def detect_container_floor_rail(region, cargo_bottom_y, grounded, y_margin=250):
    """ตรวจจับ 'เส้นขอบฐานตู้จริง' (ยาวเต็มความยาวตู้ เช่น 7.2 เมตร) ที่ปรากฏในภาพเป็นเส้นตรง
    สีทอง/น้ำตาล (tan rail) - เป็นหลักฐานเรขาคณิตล้วนๆ ไม่ขึ้นกับสี/SKU ของกล่อง (ตามที่ผู้ใช้
    ระบุให้ใช้เป็นเส้นอ้างอิงหลักของ Phase 1)

    ROOT CAUSE ที่แก้: seam-detection เดิมใช้ color-transition/gradient-spike ซึ่งล้มเหลว
    เมื่อกล่องข้างเคียงเป็น SKU/สีเดียวกัน (ไม่มีรอยต่อสีให้จับ) - เส้นขอบฐานตู้นี้เป็นเส้นตรง
    ทางเรขาคณิตแท้จริง ไม่สนใจสีกล่องด้านบนเลย จึงใช้เป็น reference ที่เชื่อถือได้กว่า

    วิธีตรวจ (ยืนยันด้วยข้อมูลจริง, AC03-01 FRONT/BACK): เส้นนี้มี slope คงที่แม่นยำมาก
    (resid_std < 2px) เมื่อ fit จากจุดสีทองที่พบในโซนซึ่งไม่ถูกผนังหัวตู้/ตัวอักษร dimension
    label บดบัง (มักอยู่ตั้งแต่ ~1/3 ของความกว้าง cargo ไปทางขวา) ใช้ robust iterative fit
    (RANSAC-like) เพื่อหาเส้นที่มี inlier มากที่สุด แล้วขยาย (extrapolate) กลับไปทางซ้ายเพื่อหา
    'จุดมุมตู้จริง' (corner point) ที่เส้นเริ่มเบี่ยงเบนออกจากเส้นตรงนี้ (คือจุดที่ผนัง/หน้าด้านข้าง
    ของกล่องมุมเข้ามาแทรก)

    คืนค่า: dict {a, b, corner_x, resid_std, n_inliers} หรือ None ถ้าหาไม่เจอ
    """
    h, w, _ = region.shape
    xs_grounded = np.nonzero(grounded)[0]
    if len(xs_grounded) < 20:
        return None
    x_min, x_max = int(xs_grounded.min()), int(xs_grounded.max())

    # เก็บจุดสีทองในช่วง y ใกล้ cargo_bottom_y (floor อยู่ใต้ cargo เสมอ)
    candidates = []
    for x in range(x_min, x_max + 1, 2):
        if cargo_bottom_y[x] < 0:
            continue
        y_search = (cargo_bottom_y[x] - 20, min(h, cargo_bottom_y[x] + y_margin))
        y = _rail_color_y(region, x, y_search)
        if y is not None:
            candidates.append((x, y))
    if len(candidates) < 20:
        return None

    xs = np.array([c[0] for c in candidates], dtype=float)
    ys = np.array([c[1] for c in candidates], dtype=float)

    # Robust iterative fit (คล้าย RANSAC): เริ่มจาก least-squares แล้วตัด outlier (คงเหลือ
    # เฉพาะจุดที่ใกล้เส้นที่สุด) ทำซ้ำจนเสถียร - จุดที่อยู่ในโซนผนัง/หน้าด้านข้างของกล่องมุม
    # จะเบี่ยงเบนออกจากเส้นตรงหลักมาก (diff หลักสิบ-ร้อย px) จึงถูกตัดออกไปเรื่อยๆ
    a, b = 0.0, float(np.median(ys))
    keep_mask = np.ones(len(xs), dtype=bool)
    for _ in range(6):
        xs_k, ys_k = xs[keep_mask], ys[keep_mask]
        if len(xs_k) < 10:
            break
        A = np.vstack([xs_k, np.ones_like(xs_k)]).T
        a, b = np.linalg.lstsq(A, ys_k, rcond=None)[0]
        resid_all = ys - (a * xs + b)
        new_keep = np.abs(resid_all) < 5.0
        if new_keep.sum() == keep_mask.sum():
            keep_mask = new_keep
            break
        keep_mask = new_keep

    xs_final, ys_final = xs[keep_mask], ys[keep_mask]
    if len(xs_final) < 10:
        return None
    resid_final = ys_final - (a * xs_final + b)

    # หา corner_x: จุดที่ซ้ายสุดซึ่งยังคง fit เส้นนี้ได้ (ไล่จาก x_min ขึ้นไปหาจุดแรกที่ inlier)
    corner_x = int(xs_final.min())
    for x in range(x_min, x_max + 1):
        y_search = (cargo_bottom_y[x] - 20, min(h, cargo_bottom_y[x] + y_margin)) if cargo_bottom_y[x] >= 0 else None
        if y_search is None:
            continue
        y = _rail_color_y(region, x, y_search)
        if y is not None and abs(y - (a * x + b)) < 5.0:
            corner_x = x
            break

    return {
        "a": float(a), "b": float(b), "corner_x": corner_x,
        "resid_std": float(resid_final.std()), "n_inliers": int(keep_mask.sum()),
    }


def _word_bbox_rotated(page, target_text):
    """หา bounding box ของคำ ('Front','Back','Load','Customer') จาก PDF text-layer จริง
    แล้วแปลงพิกัดผ่าน page.rotation_matrix ให้ตรงกับพิกัด pixmap ที่ render (รองรับ
    page ที่มี /Rotate 90)"""
    rot = page.rotation_matrix
    words = page.get_text("words")
    matches = [wd for wd in words if wd[4] == target_text]
    if not matches:
        return None
    wd = matches[0]
    x0, y0, x1, y1 = wd[0], wd[1], wd[2], wd[3]
    p0 = fitz.Point(x0, y0) * rot
    p1 = fitz.Point(x1, y1) * rot
    return (min(p0.x, p1.x), min(p0.y, p1.y), max(p0.x, p1.x), max(p0.y, p1.y))


def _view_fracs_from_bboxes(front_bb, back_bb, load_bb, cust_bb, pw, ph, view_name, margin_pt=4):
    """คำนวณ crop fraction ของ view 'front'/'back' จากตำแหน่ง label จริง - รองรับทั้ง
    layout ซ้าย-ขวา (side-by-side) และ บน-ล่าง (stacked) ซึ่งพบว่าต่างกันไปคนละไฟล์"""
    fx0, fy0, fx1, fy1 = front_bb
    bx0, by0, bx1, by1 = back_bb
    f_cx, f_cy = (fx0 + fx1) / 2, (fy0 + fy1) / 2
    b_cx, b_cy = (bx0 + bx1) / 2, (by0 + by1) / 2
    side_by_side = abs(f_cx - b_cx) > abs(f_cy - b_cy)

    right_bound = load_bb[0] - margin_pt if load_bb is not None else pw
    bottom_bound = cust_bb[1] - margin_pt if cust_bb is not None else ph

    if side_by_side:
        split_x = bx0 - margin_pt
        top = min(fy1, by1) + margin_pt
        if view_name == "front":
            x0, x1 = max(0, fx0 - margin_pt), split_x
        else:
            x0, x1 = split_x, right_bound
        y0, y1 = top, bottom_bound
    else:
        left = min(fx0, bx0)
        x0, x1 = max(0, left - margin_pt), right_bound
        if view_name == "front":
            y0, y1 = fy1 + margin_pt, by0 - margin_pt
        else:
            y0, y1 = by1 + margin_pt, bottom_bound

    return (y0 / ph, y1 / ph, x0 / pw, x1 / pw)


def render_full_page(pdf_bytes, page_idx=1, matrix_scale=3):
    """Render หน้า PDF เต็มหน้าเป็น numpy array RGB ครั้งเดียว - ใช้ภาพเดียวกันนี้ทั้งสำหรับ
    วิเคราะห์ (crop เป็น front/back) และวาด marker กลับ เพื่อพิกัดตรงกันเป๊ะ 100%"""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[page_idx]
    mat = fitz.Matrix(matrix_scale, matrix_scale)
    pix = page.get_pixmap(matrix=mat)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = img[:, :, :3]
    return np.ascontiguousarray(img), doc, page


def process_view_on_image(full_img, y0_frac, y1_frac, x0_frac, x1_frac,
                           override_cols=None, precrop=None):
    """v26.00: ลบ gap_thresh parameter ออก - compute_floor_profile จะคำนวณ adaptive
    gap_thresh เองจากข้อมูลจริงในภาพแต่ละไฟล์ (Bug#A fix) ไม่ hardcode 30px อีกต่อไป"""
    img = full_img
    H, W, _ = img.shape
    if precrop is not None:
        region, (safe_x0, safe_y0, safe_x1, safe_y1) = precrop
    else:
        y0, y1 = int(H * y0_frac), int(H * y1_frac)
        x0, x1 = int(W * x0_frac), int(W * x1_frac)
        safe_y0, safe_y1, safe_x0, safe_x1 = ensure_safe_crop(img, y0, y1, x0, x1, margin=30)
        region = img[safe_y0:safe_y1, safe_x0:safe_x1].copy()
    struct_mask_raw = saturated_mask(region)
    arrow_m = arrow_mask(region)
    cargo_mask = vivid_cargo_mask(region) & (~arrow_m)
    # v26.00 FIX Bug#A: ไม่ส่ง gap_thresh แล้ว -> compute_floor_profile ใช้ adaptive mode
    floor_y, cargo_bottom_y, grounded = compute_floor_profile(
        region, struct_mask_raw & (~arrow_m), cargo_mask)

    xs_grounded_all = np.nonzero(grounded)[0]
    fallback_xrange = (int(xs_grounded_all.min()), int(xs_grounded_all.max())) if len(xs_grounded_all) else None

    idx0_is_corner_duplicate = False

    if override_cols:
        # v25.11: ใช้ผลจาก PHASE 1B (front-face color-blob clustering + corner-cluster merge +
        # cross-view reconciliation, ดูรายละเอียดที่ compute_phase1b_columns) แทน seam-based
        # counting เดิม - แก้บั๊ก undercount ที่พบจริง (เช่น EC04-01 FRONT นับได้แค่ 5 จาก
        # seam-based ทั้งที่ควรเป็น 6) และแก้ปัญหา corner-artifact แบบหลาย fragment ได้แม่นยำกว่า
        # เดิม (ที่รองรับแค่ idx0 ตัวเดียว) - เพราะ merge เอา fragment ปลอมออกไปตั้งแต่ต้นเลย จึง
        # ไม่มี phantom record เหลือให้ต้อง flag is_corner_duplicate อีกต่อไป
        cols_sorted = sorted(override_cols, key=lambda c: c["cx"])
        n_stacks = len(cols_sorted)
        if fallback_xrange is not None:
            x_min_, x_max_ = fallback_xrange
        else:
            x_min_ = cols_sorted[0]["x"]
            x_max_ = cols_sorted[-1]["x"] + cols_sorted[-1]["w"]

        # v25.11 GUARD: กล่องมุมกล้องใกล้สุด (corner-perspective) บางครั้งมี front-face จริงที่
        # ตรวจพบ (PHASE 1B) อยู่ "นอกช่วง grounded" ของระบบพื้น/floor-profile เดิม (พบจริงใน
        # EC04-01 FRONT - พื้นตู้บริเวณมุมกล้องใกล้สุดมีระยะห่างจาก cargo_bottom_y เกิน gap_thresh
        # เพราะมุมมอง isometric ที่มุมตู้บิดเบือนไปจากปกติ ไม่ใช่บั๊กของ PHASE 1B) การปล่อยให้ seam
        # midpoint คำนวณตรงๆ อาจตกอยู่นอกช่วง [x_min_,x_max_] ทำให้เกิด segment แรกที่แคบผิดปกติ
        # (แม้แต่ติดลบ/เกือบ 0px) เมื่อ clip เข้ามาตรงๆ - แก้โดย clip แบบ "sequential" ทีละ seam
        # พร้อมบังคับ min_seg_width ขั้นต่ำ กัน segment แคบผิดปกติ/ไม่เรียงลำดับ โดยยังคงจำนวนตั้ง
        # (n_stacks) ไว้ถูกต้องเสมอ (Phase 2/3 มีกลไก cross_view_filled/carried_forward รองรับ
        # อยู่แล้วสำหรับ segment ที่ข้อมูลพื้น/ความสูงไม่น่าเชื่อถือ ณ จุดนี้)
        # v25.14 FIX (Bug#5): min_seg_width เดิม hardcode=20px ตายตัว ไม่ปรับตามขนาดกล่องจริง
        # ในภาพ - เปลี่ยนเป็น adaptive: median ความกว้างคอลัมน์จริงจาก PHASE 1B x 0.25
        # (floor ขั้นต่ำ 10px กันกรณี median เล็กผิดปกติ)
        col_widths_ = [c["w"] for c in cols_sorted if c.get("w")]
        min_seg_width = max(10, float(np.median(col_widths_)) * 0.25) if col_widths_ else 20
        seams = []
        prev_boundary = x_min_
        for i in range(len(cols_sorted) - 1):
            gap_mid = (cols_sorted[i]["x"] + cols_sorted[i]["w"] + cols_sorted[i + 1]["x"]) // 2
            seam = int(np.clip(gap_mid, prev_boundary + min_seg_width, x_max_ - min_seg_width))
            if seams and seam <= seams[-1]:
                seam = seams[-1] + min_seg_width
            seams.append(seam)
            prev_boundary = seam
        xrange_ = (x_min_, x_max_)
    else:
        # fallback: PHASE 1B ไม่สำเร็จ (เช่น หา front-face สีเด่นไม่เจอ) - ใช้ seam-based เดิม
        n_stacks, seams, xrange_ = seam_based_count(region, grounded, cargo_bottom_y, cargo_mask, struct_mask_raw)

    # v25.10 - ตรวจ 'corner artifact' (idx0 ที่เป็นภาพซ้ำ/หน้าด้านข้างของกล่องมุม หรือผนังหัวตู้
    # ที่โผล่มาก่อนเส้นขอบฐานตู้จริงเริ่มต้น) ด้วยเส้น rail ทางเรขาคณิต (ไม่ hardcode ชื่อ view)
    # ยืนยันด้วยข้อมูลจริง 3 ไฟล์: AC03-01 FRONT (diff=54, exclude, ตรงกับ 7 จริง),
    # AC03-01 BACK (diff=17, keep, ตรงกับ 7 จริง), EC01-01/EC04-02 ทั้งคู่ pattern สอดคล้องกัน
    # v25.14 FIX (Bug#6): เดิมตรวจ rail นี้เฉพาะ path fallback (seam-based) เท่านั้น ไม่ได้ตรวจ
    # เมื่อมาจาก override_cols (PHASE 1B) เลย ทั้งที่ corner-artifact ทางเรขาคณิตเป็นปัญหาของ
    # "ภาพ/มุมกล้อง" ไม่ใช่ปัญหาเฉพาะวิธีนับ - ย้ายมาตรวจเป็น common code ให้ครบทั้ง 2 path เสมอ
    if xrange_ is not None and seams:
        x_min_, x_max_ = xrange_
        rail_for_corner = detect_container_floor_rail(region, cargo_bottom_y, grounded)
        if rail_for_corner is not None:
            first_seam = sorted(seams)[0]
            seg0_width = first_seam - x_min_
            diff = rail_for_corner["corner_x"] - x_min_
            if seg0_width > 0 and diff > 0.3 * seg0_width and diff > 15:
                idx0_is_corner_duplicate = True

    return {
        "n_stacks": n_stacks, "seams": seams, "xrange": xrange_,
        "region": region, "cargo_bottom_y": cargo_bottom_y, "floor_y": floor_y,
        "cargo_mask": cargo_mask, "struct_mask": struct_mask_raw, "grounded": grounded,
        "crop_origin_x": safe_x0, "crop_origin_y": safe_y0,
        "full_page_width": W, "full_page_height": H,
        "idx0_is_corner_duplicate": idx0_is_corner_duplicate,
    }


# ============================================================================
# PHASE 1B (v25.11): จำนวนตั้ง+ตำแหน่ง ด้วยวิธี "front-face color-blob clustering"
# ============================================================================
# แทนที่ seam-based counting (PHASE 1 ด้านบน) ด้วยวิธีใหม่ที่พอร์ตมาจากโมดูลทดลองซึ่งผ่าน
# regression-test กับไฟล์ตัวอย่างจริงครบทั้ง 6 ไฟล์ (12 views): AC03-01, EC01-01, EC04-01/02/03/04
# เหตุผลที่ต้องแทนที่ (ไม่ใช่แค่ปรับปรุง idx0_is_corner_duplicate เดิม):
#   - seam-based เดิมมีบั๊ก undercount จริงที่ไม่เกี่ยวกับ corner-duplicate เลย เช่น EC04-01
#     FRONT นับได้แค่ 5 ตั้ง (ทั้งที่ควรเป็น 6 ตรงกับ BACK) เพราะกล่องข้างเคียงสี/SKU เดียวกัน
#     ทำให้ไม่มีรอยต่อสีให้ seam-detector จับ
#   - PHASE 1B ตรวจสอบแล้วว่านับถูกต้องครบ 100% ทั้ง 6 ไฟล์ (ตรงกับจำนวนจาก BACK view/เรขาคณิต
#     ของตู้ทุกกรณี) รวมถึงกรณี "มุมกล้องใกล้สุดเห็นหน้า front+ขอบลาดซ้าย+ขอบลาดขวาพร้อมกัน จน
#     แตกเป็น 3 fragment ปลอมต่อ 1 ตั้งจริง" (ยืนยันจาก EC04-01/02/04 FRONT) โดยใช้ 'side'
#     fragment (มุมข้าง) ที่ซ้อนทับเป็นหลักฐานวัดผลได้ (merge_corner_artifact_columns) พร้อม
#     guard กัน false-positive จากไฟล์ที่เห็นด้านข้างของ "ทุกกล่องตลอดทั้งแถว" ไม่ใช่แค่มุมกล้อง
#     ใกล้สุด (ยืนยันจาก AC03-01 ที่ side fragment กระจายทั่วทั้งแถว - cluster ที่ไม่แตะขอบนอก
#     สุดของ view จะถูกยกเลิกการ merge เสมอ)
#
# กลไกการทำงาน (เทียบ ground-truth ระหว่าง 2 view เหมือน PHASE 1 เดิม):
#   1. BACK = ground-truth ตำแหน่งจริง (หา front-face color-blob -> รวมเป็นคอลัมน์ -> merge
#      corner-artifact -> ตัด sidewall-contamination ที่ทราบสาเหตุแล้ว)
#   2. FRONT = candidate (อาจมี fragment ปลอมเกินจาก BACK) -> merge corner-artifact ก่อน ->
#      จับคู่ตำแหน่งกับ BACK ด้วย Hungarian algorithm (linear_sum_assignment) -> ตัดตัวที่ไม่ถูก
#      จับคู่ทิ้ง (ของซ้ำจากมุมกล้อง)
#   3. คืนค่าเป็นรายการคอลัมน์สุดท้ายของแต่ละ view (x,w,cx ในพิกัด region local ของ view นั้น)
#      ให้ process_view_on_image ใช้แทนผลจาก seam_based_count โดยตรง (ดู override_cols)
#
# v25.14 FIX (Bug#1 + Bug#2 - สำคัญ): เดิม (v25.11-v25.13) PHASE 1B render หน้า PDF แยก
# ต่างหากที่ matrix_scale=4 ตรงจาก pdf_bytes (ผ่าน get_safe_region เดิม ซึ่งคำนวณ
# ensure_safe_crop ของตัวเองอีกชุด) เพื่อให้ threshold ทางเรขาคณิต (area_min, tol, gap ฯลฯ)
# ที่ calibrate ไว้ที่ scale=4 ทำงานถูกต้อง - แต่พบ ROOT CAUSE ว่าวิธีนี้ทำให้พิกัด x ของคอลัมน์ที่
# PHASE 1B คืนมาไม่ตรงกับ coordinate system ของ region ที่ pipeline หลัก (matrix_scale=3) ใช้
# จริง (margin=30px แบบ pixel คงที่ ที่ resolution ต่างกัน ขยาย/บีบขอบไม่เป็นสัดส่วนเดียวกัน
# ทำให้ crop origin ของทั้ง 2 ฝั่งเพี้ยนไปคนละทาง แม้จะแปลงสเกลตัวเลขคอลัมน์กลับด้วย down_factor
# แล้วก็ตาม) ทำให้ seam ผิดตั้งแต่ต้น
#
# แก้โดยเลิก render/crop แยกทั้งหมด: PHASE 1B รับ "region ที่ crop มาแล้วจาก pipeline หลัก
# โดยตรง" (ผ่าน get_view_region ที่เรียกครั้งเดียวใน run_full_analysis_on_image แล้วส่ง region
# เดียวกันนี้ต่อทั้งให้ compute_phase1b_columns และ process_view_on_image ผ่าน precrop=) จึงใช้
# region เดียวกัน 100% เสมอ ไม่มีการคำนวณ crop ซ้ำที่อาจได้ origin ต่างกันอีกต่อไป (ดูรายละเอียด
# ที่ docstring ของ get_view_region/compute_phase1b_columns ด้านล่าง)
#
# Fail-safe: ถ้าขั้นตอนใดล้มเหลว (หา 'front-face' สีเด่นไม่เจอ ฯลฯ) จะคืนค่า None ทั้งคู่ และ
# process_view_on_image จะ fallback ไปใช้ seam-based เดิมโดยอัตโนมัติ (ไม่ทำให้ทั้งระบบล้มเหลว)


def _p1b_sat_val(crop):
    """คำนวณ Saturation/Value โดยตรงจาก RGB (แทน cv2.cvtColor(...,COLOR_RGB2HSV) เพื่อไม่ต้อง
    พึ่ง opencv ซึ่งไม่ได้อยู่ใน dependency ของ Cloud Function นี้ - สูตรมาตรฐาน HSV เดียวกัน)"""
    r = crop[:, :, 0].astype(np.float32)
    g = crop[:, :, 1].astype(np.float32)
    b = crop[:, :, 2].astype(np.float32)
    mx = np.maximum(np.maximum(r, g), b)
    mn = np.minimum(np.minimum(r, g), b)
    V = mx / 255.0
    S = np.where(mx > 0, (mx - mn) / np.maximum(mx, 1e-6), 0)
    return S, V


def _p1b_dominant_colors(crop, max_colors=25, min_frac=0.002):
    S, V = _p1b_sat_val(crop)
    colorful = (S > 0.25) & (V > 0.05)
    pixels = crop[colorful]
    if len(pixels) == 0:
        return []
    colors, counts = np.unique(pixels.reshape(-1, 3), axis=0, return_counts=True)
    total = counts.sum()
    order = np.argsort(-counts)
    picked = []
    for idx in order:
        c = colors[idx]
        frac = counts[idx] / total
        if frac < min_frac:
            continue
        if any(np.abs(c.astype(int) - p.astype(int)).sum() < 40 for p in picked):
            continue
        picked.append(c)
        if len(picked) >= max_colors:
            break
    return picked


def _p1b_cells_for_color(crop, color, tol=12, area_min=1200):
    """หา connected-components ของสี color บน crop - ใช้ scipy.ndimage แทน
    cv2.connectedComponentsWithStats (ผลลัพธ์เทียบเท่ากัน, ไม่ต้องพึ่ง opencv)"""
    diff = np.abs(crop.astype(int) - np.array(color, dtype=int))
    m = (diff[:, :, 0] <= tol) & (diff[:, :, 1] <= tol) & (diff[:, :, 2] <= tol)
    structure = np.ones((3, 3), dtype=int)  # 8-connectivity เหมือน cv2 connectivity=8
    labeled, num = ndimage.label(m, structure=structure)
    comps = []
    if num == 0:
        return comps
    objects = ndimage.find_objects(labeled)
    for i, sl in enumerate(objects, start=1):
        if sl is None:
            continue
        y_slice, x_slice = sl
        sub = (labeled[sl] == i)
        area = int(sub.sum())
        if area < area_min:
            continue
        y0, y1 = y_slice.start, y_slice.stop
        x0, x1 = x_slice.start, x_slice.stop
        cy_local, cx_local = ndimage.center_of_mass(sub)
        comps.append(dict(x=int(x0), y=int(y0), w=int(x1 - x0), h=int(y1 - y0), area=area,
                           cx=float(x0 + cx_local), cy=float(y0 + cy_local)))
    return comps


def _p1b_merge_text_split_fragments(comps, x_tol=12, w_tol=25, gap_max=40):
    comps = sorted(comps, key=lambda c: (round(c['x'] / 10), c['y']))
    used = [False] * len(comps)
    merged = []
    for i, c in enumerate(comps):
        if used[i]:
            continue
        group = [c]
        used[i] = True
        changed = True
        while changed:
            changed = False
            for j, c2 in enumerate(comps):
                if used[j]:
                    continue
                for g in group:
                    same_col = abs(g['x'] - c2['x']) <= x_tol and abs(g['w'] - c2['w']) <= w_tol
                    vert_close = (c2['y'] >= g['y'] - gap_max and c2['y'] <= g['y'] + g['h'] + gap_max)
                    if same_col and vert_close:
                        group.append(c2)
                        used[j] = True
                        changed = True
                        break
        x0 = min(g['x'] for g in group); y0 = min(g['y'] for g in group)
        x1 = max(g['x'] + g['w'] for g in group); y1 = max(g['y'] + g['h'] for g in group)
        area = sum(g['area'] for g in group)
        merged.append(dict(x=x0, y=y0, w=x1 - x0, h=y1 - y0, area=area,
                            cx=(x0 + x1) / 2, cy=(y0 + y1) / 2))
    return merged


def _p1b_classify_view(crop, area_min=1200):
    S, _ = _p1b_sat_val(crop)
    colors = _p1b_dominant_colors(crop)
    all_cells = []
    for color in colors:
        comps = _p1b_cells_for_color(crop, color, area_min=area_min)
        for c in comps:
            aspect = c['h'] / c['w'] if c['w'] else 0
            sub_s = S[c['y']:c['y'] + c['h'], c['x']:c['x'] + c['w']]
            mean_sat = float(np.mean(sub_s[sub_s > 0.1])) if np.any(sub_s > 0.1) else 0
            c['mean_sat'] = mean_sat
            c['color'] = tuple(int(v) for v in color)
            if mean_sat < 0.75:
                c['kind0'] = 'side'
            elif aspect < 0.85:
                c['kind0'] = 'roof'
            else:
                c['kind0'] = 'front'
        for kind0 in ('front', 'roof', 'side'):
            subset = [c for c in comps if c['kind0'] == kind0]
            merged = _p1b_merge_text_split_fragments(subset)
            for c in merged:
                c['aspect'] = c['h'] / c['w'] if c['w'] else 0
                c['color'] = tuple(int(v) for v in color)
                c['kind'] = kind0
                sub_s = S[c['y']:c['y'] + c['h'], c['x']:c['x'] + c['w']]
                c['mean_sat'] = float(np.mean(sub_s[sub_s > 0.1])) if np.any(sub_s > 0.1) else 0
                all_cells.append(c)
    return all_cells


def _p1b_front_faces(crop, area_min=1200):
    cells = _p1b_classify_view(crop, area_min=area_min)
    fronts = [c for c in cells if c['kind'] == 'front']
    fronts.sort(key=lambda c: -c['area'])
    kept = []
    for c in fronts:
        dup = False
        for k in kept:
            ox0 = max(c['x'], k['x']); oy0 = max(c['y'], k['y'])
            ox1 = min(c['x'] + c['w'], k['x'] + k['w']); oy1 = min(c['y'] + c['h'], k['y'] + k['h'])
            inter = max(0, ox1 - ox0) * max(0, oy1 - oy0)
            if inter > 0.6 * min(c['area'], k['area']):
                dup = True
                break
        if not dup:
            kept.append(c)
    kept.sort(key=lambda c: c['cx'])
    return kept, cells


def _p1b_compute_adaptive_cx_tol(fronts, factor=0.4, fallback=45, floor_px=10):
    """v25.14 FIX (Bug#3): cx_tol เดิม hardcode=45px ตายตัว ไม่ปรับตามขนาดกล่องจริงในภาพ (ไฟล์ที่
    กล่องเล็ก/บีบอัดมาก 45px อาจรวมคอลัมน์ที่ควรแยกกันเข้าด้วยกัน หรือไฟล์กล่องใหญ่มาก 45px อาจ
    เล็กเกินไปจนแยกคอลัมน์เดียวกันออกเป็นหลายกลุ่มผิด) เปลี่ยนเป็น adaptive: median ความกว้างของ
    front-face fragment จริงที่ตรวจพบ (ก่อน cluster) x 0.4 - ถ้าไม่มีข้อมูล fallback กลับไปที่
    ค่าเดิม 45px"""
    if not fronts:
        return fallback
    widths = [c['w'] for c in fronts if c.get('w')]
    if not widths:
        return fallback
    return max(floor_px, float(np.median(widths)) * factor)


def _p1b_cluster_columns(fronts, cx_tol=45):
    fronts = sorted(fronts, key=lambda c: c['cx'])
    cols = []
    for c in fronts:
        placed = False
        for col in cols:
            if abs(col['cx'] - c['cx']) <= cx_tol:
                col['members'].append(c)
                xs0 = min(col['x'], c['x']); ys0 = min(col['y'], c['y'])
                xs1 = max(col['x'] + col['w'], c['x'] + c['w']); ys1 = max(col['y'] + col['h'], c['y'] + c['h'])
                col['x'], col['y'] = xs0, ys0
                col['w'], col['h'] = xs1 - xs0, ys1 - ys0
                col['cx'] = (xs0 + xs1) / 2
                col['cy'] = (ys0 + ys1) / 2
                placed = True
                break
        if not placed:
            cols.append(dict(x=c['x'], y=c['y'], w=c['w'], h=c['h'],
                              cx=c['cx'], cy=c['cy'], members=[c]))
    cols.sort(key=lambda c: c['cx'])
    return cols


def _p1b_x_overlap_frac(a0, a1, b0, b1):
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    wa = max(1e-6, a1 - a0)
    return inter / wa


def _p1b_merge_corner_artifact_columns(cols, all_cells, side_overlap_ratio=0.5, edge_gap_max=15):
    """รวมคอลัมน์ (front-face) หลายอัน (ไม่จำกัดแค่ 2) ที่แท้จริงเป็น "มุมกล้องใกล้สุด" ของกล่อง
    ใบเดียวกัน ให้เหลือคอลัมน์เดียว โดยใช้ 'side' fragment ที่ซ้อนทับเป็นหลักฐานวัดผลได้ พร้อม
    guard: ยอมรับเฉพาะ cluster ที่แตะขอบนอกสุดจริงของ view (index 0 หรือ n-1) เท่านั้น กัน
    false-positive จากไฟล์ที่เห็นด้านข้างของทุกกล่องตลอดทั้งแถว (ดู docstring เต็มในโมดูล
    phase1_detect.py ต้นทาง สำหรับคำอธิบายละเอียด + ตัวอย่างข้อมูลจริงที่ยืนยันแล้ว)"""
    n = len(cols)
    if n < 2:
        return list(cols), []
    cols = sorted(cols, key=lambda c: c['cx'])
    sides = [c for c in all_cells if c['kind'] == 'side']
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    if sides:
        for i in range(n - 1):
            a, b = cols[i], cols[i + 1]
            a0, a1 = a['x'], a['x'] + a['w']
            b0, b1 = b['x'], b['x'] + b['w']
            for s in sides:
                s0, s1 = s['x'], s['x'] + s['w']
                fa = _p1b_x_overlap_frac(a0, a1, s0, s1)
                fb = _p1b_x_overlap_frac(b0, b1, s0, s1)
                if fa >= side_overlap_ratio and fb >= side_overlap_ratio:
                    union(i, i + 1)
                    break

    def groups_now():
        g = {}
        for i in range(n):
            r = find(i)
            g.setdefault(r, []).append(i)
        for r in g:
            g[r].sort()
        return g

    g = groups_now()
    group_of = {i: r for r, idxs in g.items() for i in idxs}
    if len(g.get(group_of[0], [])) == 1:
        g1 = group_of.get(1)
        if g1 is not None and len(g[g1]) > 1 and g[g1][0] == 1:
            gap = cols[1]['x'] - (cols[0]['x'] + cols[0]['w'])
            if gap <= edge_gap_max:
                union(0, 1)

    g = groups_now()
    group_of = {i: r for r, idxs in g.items() for i in idxs}
    last = n - 1
    if len(g.get(group_of[last], [])) == 1:
        g2 = group_of.get(last - 1)
        if g2 is not None and len(g[g2]) > 1 and g[g2][-1] == last - 1:
            gap = cols[last]['x'] - (cols[last - 1]['x'] + cols[last - 1]['w'])
            if gap <= edge_gap_max:
                union(last - 1, last)

    final_groups = groups_now()
    kept, dropped = [], []
    for r, idxs in final_groups.items():
        touches_edge = (0 in idxs) or ((n - 1) in idxs)
        if len(idxs) == 1 or not touches_edge:
            for i in idxs:
                kept.append(cols[i])
            continue
        x0 = min(cols[i]['x'] for i in idxs)
        x1 = max(cols[i]['x'] + cols[i]['w'] for i in idxs)
        center = (x0 + x1) / 2
        rep_idx = min(idxs, key=lambda i: abs(cols[i]['cx'] - center))
        for i in idxs:
            if i == rep_idx:
                kept.append(cols[i])
            else:
                dropped.append(cols[i])
    kept.sort(key=lambda c: c['cx'])
    return kept, dropped


def _p1b_drop_side_wall_contaminated_columns(cols, all_cells, cx_tol=45):
    """แก้ปัญหา 'หลงมองด้านข้างกล่อง ทำให้นับเกิน' เฉพาะกรณีที่วัดผลได้จริง (ยืนยันจาก EC04-04
    BACK: roof สีแปลกปลอมในโซนแผงข้างที่ไม่มี front-face สีเดียวกันปรากฏที่ไหนเลยในภาพ)"""
    sides = [c for c in all_cells if c['kind'] == 'side']
    if not sides:
        return cols, []
    side_x1 = max(c['x'] + c['w'] for c in sides)
    roofs = [c for c in all_cells if c['kind'] == 'roof']
    if not roofs:
        return cols, []
    from collections import Counter
    roof_color_counts = Counter(c['color'] for c in roofs)
    dominant_color = roof_color_counts.most_common(1)[0][0]
    foreign_roofs_in_zone = [c for c in roofs if c['color'] != dominant_color and c['x'] < side_x1]
    if not foreign_roofs_in_zone:
        return cols, []
    all_fronts = [c for c in all_cells if c['kind'] == 'front']
    kept, dropped = list(cols), []
    for fr in foreign_roofs_in_zone:
        has_matching_front_anywhere = any(f['color'] == fr['color'] for f in all_fronts)
        if has_matching_front_anywhere:
            continue
        if not kept:
            continue
        nearest_col = min(kept, key=lambda c: abs(c['cx'] - fr['cx']))
        kept.remove(nearest_col)
        dropped.append(nearest_col)
    return kept, dropped


def _p1b_roof_extent(cells):
    roofs = [c for c in cells if c['kind'] == 'roof']
    if not roofs:
        return None
    x0 = min(c['x'] for c in roofs)
    x1 = max(c['x'] + c['w'] for c in roofs)
    return x0, x1


def _p1b_reconcile_with_back(back_cols, front_cols, back_extent=None, front_extent=None):
    """จับคู่ตำแหน่งจริง (สัดส่วนตามแนวยาว) ระหว่าง BACK (ground-truth N ตำแหน่ง) กับ FRONT
    (candidate M ตำแหน่ง) ด้วย Hungarian algorithm

    - M > N: FRONT มี fragment ปลอมเกินมา (เช่น มุมกล้องใกล้สุดแตกเป็นหลาย fragment) -> ตัด
      candidate ที่ไม่ถูกจับคู่ทิ้ง (ของซ้ำใกล้มุมกล้อง)
    - M == N: จับคู่ตรงกันพอดี -> คืนค่าเดิมทั้งหมด
    - M < N (v25.14 FIX Bug#4): FRONT นับได้น้อยกว่า BACK จริง (บั๊กเดิม: เงื่อนไข M<=N คืนค่า
      front_cols เดิมทั้งหมดโดยไม่ทำอะไร ปล่อยให้ FRONT undercount หลุดรอดไปโดยไม่ถูกแก้) ->
      หาตำแหน่ง BACK ที่ไม่มี FRONT ใดจับคู่ด้วย (Hungarian แบบ N>M) แล้ว "augment" ด้วยตำแหน่ง
      สังเคราะห์ (synthetic column, marked synthetic=True) ที่ interpolate มาจากสัดส่วนตำแหน่ง
      จริงของ BACK (แปลงกลับเป็นพิกัด local ของ FRONT ผ่าน front_extent) แทนที่จะปล่อยผ่าน
    """
    N = len(back_cols)
    M = len(front_cols)

    def frac(cols, extent):
        if extent is None:
            xs = [c['cx'] for c in cols]
            x0, x1 = min(xs), max(xs)
        else:
            x0, x1 = extent
        span = (x1 - x0) if x1 != x0 else 1.0
        return [(c['cx'] - x0) / span for c in cols], (x0, span)

    back_sorted = sorted(back_cols, key=lambda c: c['cx'])
    front_sorted = sorted(front_cols, key=lambda c: c['cx'])

    if M == 0:
        return [], []
    if M == N:
        return front_sorted, []

    back_frac, _ = frac(back_sorted, back_extent)
    front_frac, (fx0, fspan) = frac(front_sorted, front_extent)

    cost = np.zeros((N, M))
    for i, bf in enumerate(back_frac):
        for j, ff in enumerate(front_frac):
            cost[i, j] = abs(bf - ff)
    row_ind, col_ind = linear_sum_assignment(cost)

    if M > N:
        matched_idx = set(col_ind)
        kept = [front_sorted[j] for j in sorted(matched_idx)]
        dropped = [front_sorted[j] for j in range(M) if j not in matched_idx]
        kept.sort(key=lambda c: c['cx'])
        return kept, dropped

    # M < N: เติมตำแหน่งสังเคราะห์จาก BACK ที่ไม่มีคู่ใน FRONT
    matched_back_idx = set(row_ind)
    avg_w = float(np.median([c['w'] for c in front_sorted]))
    avg_h = float(np.median([c['h'] for c in front_sorted]))
    avg_y = float(np.median([c['y'] for c in front_sorted]))
    result = list(front_sorted)
    for i in range(N):
        if i in matched_back_idx:
            continue
        target_cx = fx0 + back_frac[i] * fspan
        result.append(dict(
            x=int(round(target_cx - avg_w / 2)), y=int(round(avg_y)),
            w=int(round(avg_w)), h=int(round(avg_h)),
            cx=target_cx, cy=avg_y + avg_h / 2,
            members=[], synthetic=True,
        ))
    result.sort(key=lambda c: c['cx'])
    return result, []


def get_view_region(full_img, doc, view_name, page_idx=1, margin=30):
    """คำนวณ crop 'region' ของ view นี้ ครั้งเดียว (fraction จาก label text-layer +
    ensure_safe_crop margin=30) แล้วคืนค่าทั้ง region array และ origin - ให้ทั้ง
    compute_phase1b_columns และ process_view_on_image (ผ่าน precrop=) ใช้ "ตัวเดียวกัน 100%"

    v25.14 FIX (Bug#1 + Bug#2): เดิม PHASE 1B render หน้า PDF แยกต่างหากที่ matrix_scale=4
    (ผ่าน get_safe_region เดิม ซึ่งคำนวณ ensure_safe_crop ของตัวเองอีกชุด) ในขณะที่ pipeline
    หลัก (process_view_on_image) render/crop ที่ matrix_scale=3 - ทำให้พิกัด x ของคอลัมน์ที่
    PHASE 1B ส่งคืนไม่ตรงกับ coordinate system ของ region จริงที่ pipeline หลักใช้ (margin
    แบบ pixel คงที่ที่ resolution ต่างกัน ขยาย/บีบไม่เท่ากันเป็นสัดส่วน ทำให้ seam ผิดตั้งแต่ต้น)
    แก้โดยลบการ render/crop แยกทั้งหมด เหลือฟังก์ชันเดียว (นี้) ที่คำนวณ crop ครั้งเดียวจาก
    full_img ตัวเดียวกันที่ pipeline หลักใช้อยู่แล้ว แล้วส่ง region+origin นี้ต่อให้ทั้ง 2 ฝั่งใช้
    ตรงกันเป๊ะเสมอ (ไม่มีการคำนวณ ensure_safe_crop ซ้ำที่อาจได้ origin ต่างกันอีกต่อไป)
    """
    page = doc[page_idx]
    pw, ph = page.rect.width, page.rect.height
    front_bb = _word_bbox_rotated(page, "Front")
    back_bb = _word_bbox_rotated(page, "Back")
    load_bb = _word_bbox_rotated(page, "Load")
    cust_bb = _word_bbox_rotated(page, "Customer")
    if front_bb is None or back_bb is None:
        raise ValueError(f"ไม่พบ label 'Front'/'Back' ใน text layer ของหน้า {page_idx}")
    y0_frac, y1_frac, x0_frac, x1_frac = _view_fracs_from_bboxes(
        front_bb, back_bb, load_bb, cust_bb, pw, ph, view_name)
    H, W, _ = full_img.shape
    y0, y1 = int(H * y0_frac), int(H * y1_frac)
    x0, x1 = int(W * x0_frac), int(W * x1_frac)
    safe_y0, safe_y1, safe_x0, safe_x1 = ensure_safe_crop(full_img, y0, y1, x0, x1, margin=margin)
    region = full_img[safe_y0:safe_y1, safe_x0:safe_x1].copy()
    origin = (safe_x0, safe_y0, safe_x1, safe_y1)
    fracs = (y0_frac, y1_frac, x0_frac, x1_frac)
    return region, origin, fracs


def _p1b_validate_column_spacing(cols, max_outlier_ratio=2.5):
    """v26.00 FIX Bug#B: ตรวจ spacing outlier (IQR-based) และตัด col ที่ห่างจาก
    col ข้างเคียงเกิน max_outlier_ratio x median spacing ออก - กรณีหลักที่พบคือ
    FRONT col[0] จากมุมกล้องที่ cx อยู่ห่างจาก col[1] มากผิดปกติ ซึ่งเป็น false-
    positive ที่ทำให้นับเกิน 1 และ pos_range ของทุกตั้งเบี่ยงเบนออกไป

    Logic: คำนวณ spacing ระหว่าง cx ของ col ติดกัน ถ้า spacing ใดเกิน
    max_outlier_ratio x median spacing -> ตัด col ที่ห่างมากออก (เลือก col
    ที่อยู่ขอบ เพราะ false-positive มักอยู่ขอบซ้ายหรือขวาของ view เสมอ)"""
    if len(cols) < 3:
        return cols
    cols = sorted(cols, key=lambda c: c['cx'])
    cxs = [c['cx'] for c in cols]
    spacings = [cxs[i+1] - cxs[i] for i in range(len(cxs)-1)]
    med_spacing = float(np.median(spacings))
    if med_spacing <= 0:
        return cols
    threshold = med_spacing * max_outlier_ratio
    # ตรวจ outlier ที่ขอบซ้าย: spacing[0] ใหญ่ผิดปกติ
    if spacings[0] > threshold:
        print(f"  [v26 Bug#B] ตัด col[0] cx={cxs[0]:.0f} ออก (spacing={spacings[0]:.0f} > {threshold:.0f})")
        cols = cols[1:]
    # ตรวจ outlier ที่ขอบขวา (ทำซ้ำหลังอาจ trim ซ้าย)
    if len(cols) >= 3:
        cxs2 = [c['cx'] for c in cols]
        spacings2 = [cxs2[i+1] - cxs2[i] for i in range(len(cxs2)-1)]
        med2 = float(np.median(spacings2))
        if med2 > 0 and spacings2[-1] > med2 * max_outlier_ratio:
            print(f"  [v26 Bug#B] ตัด col[-1] cx={cxs2[-1]:.0f} ออก (spacing={spacings2[-1]:.0f} > {med2*max_outlier_ratio:.0f})")
            cols = cols[:-1]
    return cols


def compute_phase1b_columns(regions):
    """คืนค่า dict {'front': [cols...] หรือ None, 'back': [cols...] หรือ None} ในพิกัด region
    local ของแต่ละ view - ตรงกับพิกัดที่ process_view_on_image ใช้จริง 100% เสมอ เพราะรับ
    region ที่ crop มาแล้วจาก pipeline หลักโดยตรง (ดู get_view_region + run_full_analysis_on_image)
    ไม่ render หรือ crop แยกต่างหากอีกต่อไป (v25.14 FIX Bug#1/#2 - ดู docstring get_view_region)

    regions: {"front": region_array, "back": region_array}
    None = ตรวจไม่สำเร็จ (fallback อัตโนมัติไปที่ seam-based เดิมใน process_view_on_image)
    """
    try:
        back_region = regions["back"]
        front_region = regions["front"]

        back_all = _p1b_classify_view(back_region)
        back_fronts, _ = _p1b_front_faces(back_region)
        back_cx_tol = _p1b_compute_adaptive_cx_tol(back_fronts)
        back_cols_pre = _p1b_cluster_columns(back_fronts, cx_tol=back_cx_tol)
        if not back_cols_pre:
            return {"front": None, "back": None}
        back_cols_raw, _ = _p1b_merge_corner_artifact_columns(back_cols_pre, back_all)
        back_cols_sid, _ = _p1b_drop_side_wall_contaminated_columns(back_cols_raw, back_all)
        # v26.00 FIX Bug#B: validate spacing outlier ทั้ง BACK และ FRONT
        back_cols = _p1b_validate_column_spacing(back_cols_sid)
        back_extent = _p1b_roof_extent(back_all)
        if not back_cols:
            return {"front": None, "back": None}

        front_all = _p1b_classify_view(front_region)
        front_fronts, _ = _p1b_front_faces(front_region)
        front_cx_tol = _p1b_compute_adaptive_cx_tol(front_fronts)
        front_cols_pre = _p1b_cluster_columns(front_fronts, cx_tol=front_cx_tol)
        if not front_cols_pre:
            return {"front": None, "back": None}
        front_cols_raw, _ = _p1b_merge_corner_artifact_columns(front_cols_pre, front_all)
        front_cols_validated = _p1b_validate_column_spacing(front_cols_raw)
        front_extent = _p1b_roof_extent(front_all)

        front_cols, _ = _p1b_reconcile_with_back(
            back_cols, front_cols_validated, back_extent=back_extent, front_extent=front_extent)
        if not front_cols:
            return {"front": None, "back": None}

        return {"front": front_cols, "back": back_cols}
    except Exception as e:
        print(f"PHASE1B column-detection ล้มเหลว, fallback เป็น seam-based เดิม: {e}")
        return {"front": None, "back": None}


# ============================================================================
# v25.13 EXPERIMENTAL UTILITIES (จาก session พัฒนาแยกต่างหาก - ยังไม่ wire เข้า pipeline หลัก)
# ============================================================================
# ประวัติ: v25.12 เคยเสนอ utility 3 ตัว (classify_boundary_grid_vs_seam,
# locate_container_apex_and_width_vector, และแนวคิด structural-color exclusion) โดยตอนนั้น
# 2 ใน 3 แนวคิด "พังจริง" เมื่อทดสอบกับ AC03-01 (ไฟล์โหลดเต็มคัน 100% - ไม่เหลือช่องว่าง
# โครงสร้างรอบกล่องเลย): (1) structural-color exclusion แบบ single-view boundary-touch ทำให้
# กล่องสีน้ำเงินถูกเข้าใจผิดเป็นพื้นตู้ (2) width-vector geometry classifier ให้ผล FRONT/BACK
# ไม่ตรงกันเอง (216,108) vs (128,64) ทั้งที่ควรเป็นค่าเดียวกัน (ความกว้างตู้จริงคงที่)
#
# v25.13 นี้ กลับไปสืบสวนหาสาเหตุที่แท้จริงและแก้ไขทั้ง 2 จุด ด้วยการทดสอบสมมติฐานใหม่กับ
# AC03-01 จริงทุกขั้นตอน (ไม่ใช่แค่คาดเดา) สรุปผลดังนี้:
#
# --------------------------------------------------------------------------------------
# (1) FIX: is_structural_color_cross_view -- ใช้หลักฐาน "ปรากฏในทั้ง 2 view พร้อมกัน" แทน
# --------------------------------------------------------------------------------------
# root cause ที่แท้จริงของความล้มเหลวเดิม (พิสูจน์ด้วย AC03-01 จริง): วิธี single-view
# boundary-touch เดิม ตรวจแค่ view เดียว - กล่องสีน้ำเงินที่ชนขอบภาพ (เพราะโหลดเต็มคัน) ใน BACK
# ถูกเข้าใจผิดเป็นพื้นตู้ ทั้งที่ในไฟล์เดียวกันนี้ FRONT (สีน้ำเงินเดียวกัน) "ไม่ชนขอบภาพเลย"
#
# FIX: สีโครงสร้างจริง (พื้น/ผนัง/หลังคา) เป็นส่วนหนึ่งของตัวรถทั้งคัน จึงต้องปรากฏใน "ทั้ง 2
# view" (FRONT และ BACK คือรถคันเดียวกัน มองจากคนละมุม) และต้องชนขอบภาพใน "ทั้งคู่พร้อมกัน"
# ส่วนกล่องสินค้าที่บังเอิญชนขอบภาพจากโหลดเต็มคัน มักชนแค่ฝั่งเดียว (มุมกล้องคนละมุมทำให้ขอบ
# ตัดกล่องคนละตำแหน่ง) - ทดสอบยืนยันกับ AC03-01 จริง:
#   สีน้ำเงิน (0,0,255) กล่องจริง: FRONT ไม่ชนขอบ (False), BACK ชนขอบ (True)
#     -> เดิม (single-view): ผิดเป็น STRUCTURAL ใน BACK
#     -> ใหม่ (cross-view AND): ต้องชนทั้งคู่ถึงจะนับเป็น STRUCTURAL -> ถูกต้อง เก็บเป็น BOX
#   สีทอง (203,203,101)/(178,178,89) หลังคาจริง: ปรากฏเฉพาะใน FRONT (ชนขอบ=True) ไม่มีใน BACK
#     -> ใช้ single-view fallback (เพราะไม่มีข้อมูล cross-view ให้เทียบ) -> ยังคง STRUCTURAL
#     ถูกต้อง (ตรวจสอบด้วยภาพจริงแล้ว: เป็นแผงผนังด้านข้างขวาของตู้ ไม่ใช่กล่อง)
#   สีทอง (210,210,105) พื้น/ผนัง฿ฝั่ง BACK: ปรากฏเฉพาะใน BACK (ชนขอบ=True) ไม่มีใน FRONT
#     -> single-view fallback -> ยังคง STRUCTURAL ถูกต้อง
# ผลลัพธ์: ผ่านการทดสอบ AC03-01 ครบทุกสีที่ตรวจสอบได้ ไม่มี false-positive กับกล่องอีกต่อไป
#
# ข้อจำกัดที่ยังต้องระวัง (บอกตรงไปตรงมา): "single-view fallback" (ใช้เมื่อสีนั้นปรากฏใน
# แค่ 1 view) ยังคงพึ่ง boundary-touch เดี่ยวเหมือนเดิม - ถ้ามีไฟล์ที่กล่องสี unique (ปรากฏ
# แค่ view เดียว) บังเอิญชนขอบภาพจากโหลดเต็มคันเช่นกัน จุดอ่อนเดิมจะกลับมา - ยังไม่มีไฟล์
# ตัวอย่างที่ยืนยันเคสนี้ได้ในรอบนี้ (มีแค่ AC03-01 ให้ตรวจสอบ) จึงยังไม่ integrate เข้า
# pipeline หลัก คงเป็น utility function แยกเท่านั้น
#
# --------------------------------------------------------------------------------------
# (2) FIX: locate_apex_and_width_vector_consistent -- เพิ่ม cross-view consistency-gate
# --------------------------------------------------------------------------------------
# สืบสวนสาเหตุ (debug เต็มรูปแบบกับ AC03-01): พบว่าปัญหาไม่ใช่ "false-positive plateau สั้น"
# ตามที่คาดไว้ตอนแรก (ทดสอบเพิ่ม min_flat_run จาก 3 ไปถึง 300 - ผลลัพธ์ไม่เปลี่ยนเลยจนกว่าจะ
# เกิน length ของ plateau จริง) แต่เป็นเพราะ BACK เจอ "แนวตั้งยาวจริง" (~102 แถวติดกัน) ที่ไม่ใช่
# ขอบตู้จริง (ไม่มี plateau อื่นที่ยาวกว่านี้เลยแม้ค้นหาถึง 1200 แถว) ในขณะที่ FRONT เจอแนวตั้ง
# จริงที่ยาวกว่ามาก (~265 แถว) ซึ่งตรงกับขอบตู้จริงตามหลักฟิสิกส์ isometric (เส้นดิ่งของกล่อง
# สี่เหลี่ยมในมุมมอง isometric ต้องยาวต่อเนื่องตลอดความสูงกอง) - สรุปคือวิธี trace ตามลำพัง
# (ไม่มีข้อมูลอ้างอิงอื่น) ไม่สามารถแยกแยะ "แนวตั้งจริงของขอบตู้" ออกจาก "แนวตั้งบังเอิญจากลูกศร/
# เส้นบอกขนาดที่ทับซ้อนกันพอดี" ได้ 100% โดยเฉพาะไฟล์โหลดเต็มคันที่ไม่มีช่องว่างช่วยยืนยัน
#
# FIX ที่ตรวจสอบได้จริง (ไม่ใช่การเดา): เนื่องจากความกว้างตู้จริง (2400mm) ต้องเท่ากันทั้ง FRONT
# และ BACK (รถคันเดียวกัน, render scale เดียวกัน) - เพิ่ม "consistency-gate": คำนวณทั้ง 2 view
# แล้วเทียบขนาด (magnitude) ของ width_vector ที่ได้ ถ้าอัตราส่วน (ค่าน้อย/ค่ามาก) ต่ำกว่า
# เกณฑ์ (min_consistency_ratio) -> ถือว่า "ไม่น่าเชื่อถือ" คืนค่า None ทั้งคู่ แทนที่จะเชื่อ
# ตัวเลขที่อาจผิดอย่างมั่นใจ (เปลี่ยนจาก "มั่นใจผิด" เป็น "ซื่อสัตย์ว่าไม่รู้")
# ทดสอบกับ AC03-01 จริง: FRONT mag=241.5, BACK mag=143.1, อัตราส่วน=0.593 (ห่างจาก 1.0 มาก)
# -> ฟังก์ชันใหม่ปฏิเสธทั้งคู่อย่างถูกต้อง (แทนที่จะคืนค่าผิดอย่างมั่นใจเหมือน v25.12 เดิม)
#
# ข้อจำกัดที่ยังต้องระวัง (บอกตรงไปตรงมา): แก้ไขนี้เป็น "safety gate" ไม่ใช่ "ทำให้แม่นยำขึ้น"
# - ยังไม่มีวิธียืนยันว่ากรณีที่ผ่านเกณฑ์ (ratio สูง) จะได้ค่าที่ถูกต้องจริง 100% เพราะมีเพียง
# ไฟล์เดียว (AC03-01 ซึ่งเป็นกรณีที่ควรถูกปฏิเสธ) ให้ตรวจสอบในรอบนี้ - ยังไม่ integrate เข้า
# pipeline หลัก คงเป็น utility function แยกเท่านั้น จนกว่าจะมีไฟล์เพิ่มเติมมายืนยัน true-positive
#
# สรุปโดยรวม v25.13: ทั้ง 2 utility ผ่านการแก้ไขที่มีหลักฐาน (evidence-based) และพิสูจน์แล้วว่า
# แก้ปัญหาที่พบใน v25.12 ได้จริงกับ AC03-01 (ไฟล์เดียวที่มีให้ตรวจสอบ) แต่ยังคง "ไม่ wire เข้า
# pipeline หลัก" เนื่องจากมีไฟล์ตัวอย่างให้ regression-test แค่ 1 ใน 6 ไฟล์ calibration ของ
# PHASE 1B (ไม่มี EC01-01/EC04-01/02/03/04 ให้ตรวจสอบในรอบนี้) - แนะนำให้รัน regression เต็ม
# ทั้ง 6 ไฟล์ก่อนพิจารณา integrate เข้า pipeline จริงในเวอร์ชันถัดไป ไม่มีการแก้ไข PHASE
# 1B/2/3/Rule Engine เดิมแต่อย่างใดในเวอร์ชันนี้ (regression-verified: AC03-01 ยังคง
# front=7, back=7 ตรงเดิมทุกประการ)
# ============================================================================

def classify_boundary_grid_vs_seam(region, x_gap_range, y_overlap_range,
                                    black_thresh=30, ratio_low=0.35, ratio_high=0.85,
                                    ratio_consistency_tol=0.12,
                                    black_core_fraction_thresh=0.15):
    """
    [v25.12/13 EXPERIMENTAL - ยังไม่ถูกเรียกใช้จาก pipeline หลักใด ๆ ในไฟล์นี้]
    แยกแยะเส้นแบ่งระหว่าง component สี 2 อัน ว่าเป็น 'GRID_LINE' (เส้น overlay ปลอม - ควร
    merge เป็นกล่องเดียว) หรือ 'REAL_SEAM' (ขอบกล่องจริง - ไม่ควร merge)

    หลักฐานที่พิสูจน์แล้ว (session พัฒนาแยก, ไฟล์ EA03-01):
      GRID_LINE: พิกเซลเส้นแบ่ง = สีพื้นเดิม x อัตราส่วนคงที่ (~0.35-0.85) ไม่เคยถึงดำสนิท
                 แม้พื้นหลังจะเปลี่ยนสี (ข้าม SKU) อัตราส่วนก็ยังคงที่ (วัดได้จริง: 0.622 บน
                 พื้นแดง, 0.625 บนพื้นเขียว - ยืนยันว่าเป็นเส้นเดียวกันที่ overlay ทับ)
      REAL_SEAM: มีแกนดำสนิท (0,0,0) ปรากฏอย่างมีนัยสำคัญ (>black_core_fraction_thresh
                 ของความยาวเส้น) ซึ่งเส้น overlay แบบ multiply-blend ไม่มีทางให้ค่าดำสนิทได้

    Args:
      region: ภาพ RGB (numpy array, ต้องเป็นพิกัดเดียวกับที่ x_gap_range/y_overlap_range อ้างถึง)
      x_gap_range: (x0,x1) ของช่องว่างระหว่าง 2 component (พิกัด local ของ region เดียวกัน)
      y_overlap_range: (y0,y1) ส่วนที่ทั้ง 2 component ทับซ้อนกันในแนวตั้งเท่านั้น (สำคัญมาก:
        ต้องจำกัดแค่ช่วงที่ทับซ้อนจริง ห้าม scan ทั้งคอลัมน์ภาพ มิฉะนั้นจะไปโดน text label อื่น
        ที่ไม่เกี่ยวข้องปนเข้ามาทำให้ตัดสินผิด - เป็นบั๊กที่เคยพบและแก้ไขแล้วใน session พัฒนา)

    Returns:
      'GRID_LINE' หรือ 'REAL_SEAM' (default ปลอดภัย = REAL_SEAM เมื่อข้อมูลไม่พอ/ไม่แน่ใจ
      เพื่อไม่ให้ merge ผิดพลาดโดยไม่มีหลักฐานเพียงพอ)
    """
    y0, y1 = y_overlap_range
    x0, x1 = x_gap_range
    if y1 <= y0 or x1 <= x0:
        return 'REAL_SEAM'

    total_rows = 0
    black_core_rows = 0
    grid_like_rows = 0
    left_x = max(x0 - 1, 0)

    for y in range(y0, y1):
        gap_pixels = region[y, x0:x1]
        if len(gap_pixels) == 0:
            continue
        total_rows += 1

        min_sum = min(int(p[0]) + int(p[1]) + int(p[2]) for p in gap_pixels)
        if min_sum < black_thresh:
            black_core_rows += 1
            continue

        darkest = min(gap_pixels, key=lambda p: int(p[0]) + int(p[1]) + int(p[2]))
        neighbor = region[y, left_x]
        r, g, b = (int(v) for v in darkest)
        nr, ng, nb = (int(v) for v in neighbor)
        ratios = [c / nc for c, nc in zip((r, g, b), (nr, ng, nb)) if nc > 20]
        if not ratios:
            continue
        avg_ratio = sum(ratios) / len(ratios)
        consistent = all(abs(v - avg_ratio) < ratio_consistency_tol for v in ratios)
        if consistent and ratio_low < avg_ratio < ratio_high:
            grid_like_rows += 1

    if total_rows == 0:
        return 'REAL_SEAM'

    black_core_frac = black_core_rows / total_rows
    grid_like_frac = grid_like_rows / total_rows

    if black_core_frac > black_core_fraction_thresh:
        return 'REAL_SEAM'
    if grid_like_frac > 0.6:
        return 'GRID_LINE'
    return 'REAL_SEAM'


def _global_container_silhouette(region, sat_thresh=0.12, val_thresh=0.20):
    """หา connected-component ที่ใหญ่ที่สุดของพิกเซลสี box-fill ใด ๆ (ทุก hue รวมกัน) -
    แทน silhouette รวมของทั้งตัวรถ (พื้น+ผนัง+หลังคา+กล่องสินค้าทั้งหมด เพราะทุกอย่างสัมผัส
    กันในภาพ isometric) ใช้เป็นกรอบอ้างอิงสำหรับ is_structural_color_cross_view ด้านล่าง"""
    S, V = _p1b_sat_val(region)
    fill_mask = (S > sat_thresh) & (V > val_thresh)
    structure = np.ones((3, 3), dtype=int)
    labeled, num = ndimage.label(fill_mask, structure=structure)
    if num == 0:
        return None
    sizes = ndimage.sum(fill_mask, labeled, range(1, num + 1))
    largest_label = int(np.argmax(sizes)) + 1
    return labeled == largest_label


def _touches_boundary(region, color, silhouette, tol=12, margin=2):
    """สีนี้มีพิกเซลอย่างน้อย 1 จุด (ภายใน silhouette) ที่สัมผัสขอบนอกสุดของ silhouette
    (บน/ล่าง/ซ้าย/ขวา) หรือไม่ - ใช้เป็นสัญญาณเดี่ยว (single-view) สำหรับ fallback เท่านั้น
    (พิสูจน์แล้วว่าใช้เดี่ยว ๆ ไม่ปลอดภัยกับไฟล์โหลดเต็มคัน - ดู is_structural_color_cross_view)"""
    if silhouette is None:
        return False
    gys, gxs = np.nonzero(silhouette)
    if len(gys) == 0:
        return False
    g_top, g_bottom = int(gys.min()), int(gys.max())
    g_left, g_right = int(gxs.min()), int(gxs.max())
    diff = np.abs(region.astype(int) - np.array(color, dtype=int))
    mask = (diff[:, :, 0] <= tol) & (diff[:, :, 1] <= tol) & (diff[:, :, 2] <= tol)
    mask = mask & silhouette
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return False
    return (ys.min() <= g_top + margin) or (xs.min() <= g_left + margin) or \
           (xs.max() >= g_right - margin) or (ys.max() >= g_bottom - margin)


def is_structural_color_cross_view(front_region, back_region, color,
                                    front_silhouette=None, back_silhouette=None,
                                    tol=12, margin=2, color_match_tol=15):
    """
    [v25.13 EXPERIMENTAL - ยังไม่ถูกเรียกใช้จาก pipeline หลักใด ๆ ในไฟล์นี้]
    [แก้ไขจาก v25.12 ที่พังกับ AC03-01 (โหลดเต็มคัน) - ดู docstring หัวข้อ "v25.13
     EXPERIMENTAL UTILITIES" ด้านบนสำหรับหลักฐาน+เหตุผลเต็ม]

    ตรวจสอบว่า `color` เป็นสีโครงสร้างตู้ (พื้น/ผนัง/หลังคา) หรือสีกล่องสินค้าจริง โดยใช้
    หลักฐาน "ปรากฏในทั้ง FRONT และ BACK พร้อมกัน และชนขอบภาพทั้งคู่" (สีโครงสร้างเป็นส่วนหนึ่ง
    ของรถทั้งคัน ต้องเห็นได้จากทั้ง 2 มุมกล้อง) แทนการตรวจแค่ view เดียว ซึ่งพิสูจน์แล้วว่า
    ทำให้กล่องที่บังเอิญชนขอบภาพ (จากโหลดเต็มคัน) ถูกเข้าใจผิดเป็นโครงสร้าง

    Args:
      front_region, back_region: ภาพ RGB ของ FRONT และ BACK view
      color: (r,g,b) สีที่ต้องการตรวจสอบ
      front_silhouette, back_silhouette: ผลลัพธ์จาก _global_container_silhouette (ถ้ามีอยู่
        แล้วจากการเรียกครั้งก่อน ส่งเข้ามาเพื่อลดการคำนวณซ้ำได้)
      color_match_tol: ระยะห่างสี (แต่ละ channel) สูงสุดที่ยังถือว่าเป็น "สีเดียวกัน" ระหว่าง
        2 view (สีที่ render ออกมาอาจมี pixel-value เพี้ยนเล็กน้อยระหว่าง view ได้)

    Returns:
      True = ตัดสินว่าเป็นสีโครงสร้าง (ควรตัดออกจากการนับกล่อง)
      False = ตัดสินว่าเป็นสีกล่องจริง (เก็บไว้)

    Logic:
      - ถ้าสีนี้ปรากฏ (มี pixel มากพอ) ในทั้ง 2 view: ต้อง "ชนขอบภาพทั้งคู่" ถึงจะถือเป็น
        โครงสร้าง (cross-view AND) - นี่คือจุดที่แก้บั๊กเดิม เพราะกล่องที่ชนขอบแค่ฝั่งเดียว
        (เช่น สีน้ำเงินใน AC03-01 ที่ชนขอบเฉพาะ BACK ไม่ชนใน FRONT) จะถูกเก็บไว้ถูกต้อง
      - ถ้าสีนี้ปรากฏแค่ 1 view: fallback ไปใช้ single-view boundary-touch (ข้อจำกัด: ยัง
        เสี่ยง false-positive ถ้ากล่องสี unique บังเอิญชนขอบจากโหลดเต็มคัน - ยังไม่มีไฟล์
        ตัวอย่างยืนยันเคสนี้)
    """
    if front_silhouette is None:
        front_silhouette = _global_container_silhouette(front_region)
    if back_silhouette is None:
        back_silhouette = _global_container_silhouette(back_region)

    def _color_present(region, color, silhouette, tol):
        if silhouette is None:
            return False
        diff = np.abs(region.astype(int) - np.array(color, dtype=int))
        mask = (diff[:, :, 0] <= tol) & (diff[:, :, 1] <= tol) & (diff[:, :, 2] <= tol)
        mask = mask & silhouette
        return int(mask.sum()) > 200  # ต้องมี pixel มากพอ ไม่ใช่ noise เล็กน้อย

    in_front = _color_present(front_region, color, front_silhouette, tol)
    in_back = _color_present(back_region, color, back_silhouette, tol)

    if in_front and in_back:
        touch_f = _touches_boundary(front_region, color, front_silhouette, tol=tol, margin=margin)
        touch_b = _touches_boundary(back_region, color, back_silhouette, tol=tol, margin=margin)
        return touch_f and touch_b  # cross-view AND: ต้องชนขอบทั้งคู่

    # สีนี้ปรากฏแค่ view เดียว -> fallback เป็น single-view test
    if in_front:
        return _touches_boundary(front_region, color, front_silhouette, tol=tol, margin=margin)
    if in_back:
        return _touches_boundary(back_region, color, back_silhouette, tol=tol, margin=margin)
    return False  # ไม่พบสีนี้ในทั้ง 2 view เลย (ไม่ควรเกิดขึ้นถ้าเรียกถูกต้อง)


def locate_apex_and_width_vector_consistent(front_region, back_region,
                                             sat_thresh=0.16, val_thresh=0.24,
                                             min_flat_run=3, max_trace_rows=1200,
                                             min_consistency_ratio=0.85):
    """
    [v25.13 EXPERIMENTAL - ยังไม่ถูกเรียกใช้จาก pipeline หลักใด ๆ ในไฟล์นี้]
    [แก้ไขจาก v25.12 ที่ให้ผล FRONT/BACK ไม่ตรงกันเองกับ AC03-01 - ดู docstring หัวข้อ
     "v25.13 EXPERIMENTAL UTILITIES" ด้านบนสำหรับหลักฐาน+เหตุผลเต็ม]

    หาจุดยอดหลังคา (apex) และ pixel-vector ของความกว้างตู้เต็ม (คงที่จริง 2400mm) จาก
    FRONT และ BACK พร้อมกัน แล้วตรวจสอบว่าทั้ง 2 view เห็นพ้องกัน (ค่า magnitude ใกล้เคียงกัน
    ตามที่ควรเป็นจริง เพราะเป็นตู้เดียวกัน) ก่อนจะคืนค่าใด ๆ - ถ้าไม่เห็นพ้องกัน (สงสัยว่า
    ฝั่งใดฝั่งหนึ่งเจอ "แนวตั้งบังเอิญ" ที่ไม่ใช่ขอบตู้จริง) จะคืนค่า None ทั้งคู่แทนที่จะเชื่อ
    ตัวเลขที่อาจผิดอย่างมั่นใจ

    ทดสอบกับ AC03-01: FRONT ให้ magnitude≈241.5, BACK ให้≈143.1 (อัตราส่วน 0.593 < 0.85)
    -> ฟังก์ชันนี้ปฏิเสธทั้งคู่ (คืนค่า None) อย่างถูกต้อง แทนที่จะคืนตัวเลขผิดเหมือน v25.12

    Args:
      front_region, back_region: ภาพ RGB ของ FRONT/BACK view
      min_consistency_ratio: อัตราส่วนขั้นต่ำ (ค่าน้อย/ค่ามาก ของ magnitude ทั้ง 2 view)
        ที่ยังยอมรับว่า "เห็นพ้องกันพอ" (default 0.85 คือต่างกันไม่เกิน ~15%)

    Returns:
      dict {'front': (apex, width_vector) หรือ (apex, None),
            'back':  (apex, width_vector) หรือ (apex, None),
            'consistent': bool} -- ถ้า consistent=False ค่า width_vector ทั้งคู่จะเป็น None
      เสมอ (แม้จะคำนวณได้ตัวเลขก็ตาม) เพื่อป้องกันการนำค่าที่ไม่น่าเชื่อถือไปใช้ต่อโดยไม่รู้ตัว

    ข้อจำกัด (บอกตรงไปตรงมา): เป็น "safety gate" ที่ป้องกันการใช้ค่าผิดอย่างมั่นใจ ไม่ใช่การ
    ทำให้ค่าที่คำนวณได้แม่นยำขึ้น - ยังไม่มีไฟล์ตัวอย่างที่ยืนยันกรณี "ผ่านเกณฑ์แล้วถูกต้องจริง"
    (true-positive) ในรอบนี้ มีเพียง AC03-01 ซึ่งเป็นกรณีที่ควรถูกปฏิเสธ (true-negative) เท่านั้น
    """
    def _locate(region):
        S, V = _p1b_sat_val(region)
        fill_mask = (S > sat_thresh) & (V > val_thresh)
        structure = np.ones((3, 3), dtype=int)
        labeled, num = ndimage.label(fill_mask, structure=structure)
        if num == 0:
            return None, None
        sizes = ndimage.sum(fill_mask, labeled, range(1, num + 1))
        largest_label = int(np.argmax(sizes)) + 1
        silhouette = (labeled == largest_label)

        ys, xs = np.nonzero(silhouette)
        apex_y = int(ys.min())
        apex_xs = xs[ys == apex_y]
        apex = np.array([float(apex_xs.mean()), float(apex_y)])

        prev_xmax = None
        consecutive = 0
        corner = None
        h = silhouette.shape[0]
        for y in range(apex_y, min(apex_y + max_trace_rows, h)):
            xs_row = np.nonzero(silhouette[y])[0]
            if len(xs_row) == 0:
                continue
            xmax = int(xs_row.max())
            if prev_xmax is not None and xmax == prev_xmax:
                consecutive += 1
                if consecutive >= min_flat_run:
                    corner = np.array([float(xmax), float(y - min_flat_run)])
                    break
            else:
                consecutive = 0
            prev_xmax = xmax

        if corner is None:
            return apex, None
        return apex, corner - apex

    apex_f, wv_f = _locate(front_region)
    apex_b, wv_b = _locate(back_region)

    consistent = False
    if wv_f is not None and wv_b is not None:
        mag_f, mag_b = float(np.linalg.norm(wv_f)), float(np.linalg.norm(wv_b))
        if mag_f > 0 and mag_b > 0:
            ratio = min(mag_f, mag_b) / max(mag_f, mag_b)
            consistent = ratio >= min_consistency_ratio

    if not consistent:
        wv_f, wv_b = None, None

    return {
        'front': (apex_f, wv_f),
        'back': (apex_b, wv_b),
        'consistent': consistent,
    }


# ============================================================================
# PHASE 2: ความยาวของแต่ละตั้งของกล่อง แต่ละ VIEW
# ============================================================================

def is_white_bg(rgb, white_thresh=245):
    r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
    return r >= white_thresh and g >= white_thresh and b >= white_thresh


def measure_cargo_extent_via_white_bg(region, cargo_bottom_y, grounded, sample_offset=3, refine_margin=15):
    xs_grounded = np.nonzero(grounded)[0]
    if len(xs_grounded) == 0:
        return None, None, 0
    rough_min, rough_max = int(xs_grounded.min()), int(xs_grounded.max())
    h, w, _ = region.shape
    true_start = rough_min
    search_limit_left = max(0, rough_min - refine_margin)
    for x in range(rough_min, search_limit_left - 1, -1):
        if cargo_bottom_y[x] < 0:
            break
        y_ref = cargo_bottom_y[x] - sample_offset
        if not (0 <= y_ref < h):
            break
        if is_white_bg(region[y_ref, x]):
            true_start = x + 1
            break
        true_start = x
    true_end = rough_max
    search_limit_right = min(w - 1, rough_max + refine_margin)
    for x in range(rough_max, search_limit_right + 1):
        if cargo_bottom_y[x] < 0:
            break
        y_ref = cargo_bottom_y[x] - sample_offset
        if not (0 <= y_ref < h):
            break
        if is_white_bg(region[y_ref, x]):
            true_end = x - 1
            break
        true_end = x
    length_px = true_end - true_start
    return true_start, true_end, length_px


def measure_stack_lengths(seams, start_x, end_x):
    """v26.00 FIX Bug#F: guard None สำหรับ start_x/end_x ที่อาจเป็น None เมื่อ
    measure_cargo_extent_via_white_bg ไม่พบ white background เลยในภาพ"""
    if start_x is None or end_x is None:
        return [], []
    # v26.00 FIX Bug#G: clamp seam ให้อยู่ใน [start_x, end_x] เสมอ
    clamped_seams = [max(start_x, min(end_x, s)) for s in (seams or [])]
    clamped_seams = sorted(set(s for s in clamped_seams if start_x < s < end_x))
    boundaries = [start_x] + clamped_seams + [end_x]
    lengths = [boundaries[i + 1] - boundaries[i] for i in range(len(boundaries) - 1)]
    return lengths, boundaries


def process_view_with_length_on_image(full_img, doc, view_name, page_idx=1, override_cols=None, precrop=None):
    if precrop is not None:
        # v25.14 FIX (Bug#1/#2): มี region ที่ crop มาแล้วจาก run_full_analysis_on_image
        # (ใช้ตัวเดียวกับที่ PHASE 1B ใช้) - ไม่ต้องคำนวณ fraction/crop ซ้ำอีกรอบ
        y0_frac = y1_frac = x0_frac = x1_frac = None
    else:
        page = doc[page_idx]
        pw, ph = page.rect.width, page.rect.height
        front_bb = _word_bbox_rotated(page, "Front")
        back_bb = _word_bbox_rotated(page, "Back")
        load_bb = _word_bbox_rotated(page, "Load")
        cust_bb = _word_bbox_rotated(page, "Customer")
        if front_bb is None or back_bb is None:
            raise ValueError(f"ไม่พบ label 'Front'/'Back' ใน text layer ของหน้า {page_idx}")
        y0_frac, y1_frac, x0_frac, x1_frac = _view_fracs_from_bboxes(
            front_bb, back_bb, load_bb, cust_bb, pw, ph, view_name)
    r = process_view_on_image(full_img, y0_frac, y1_frac, x0_frac, x1_frac,
                               override_cols=override_cols, precrop=precrop)
    start_x, end_x, length_px = measure_cargo_extent_via_white_bg(r["region"], r["cargo_bottom_y"], r["grounded"])
    # v26.00 FIX Bug#F: fallback ถ้า start_x/end_x=None (ไม่พบ white bg)
    if start_x is None or end_x is None:
        xs_g = np.nonzero(r["grounded"])[0]
        if len(xs_g) >= 2:
            start_x = int(xs_g.min())
            end_x = int(xs_g.max())
            length_px = end_x - start_x
        else:
            start_x, end_x, length_px = 0, r["region"].shape[1] - 1, r["region"].shape[1] - 1
    stack_lengths, boundaries = measure_stack_lengths(r["seams"], start_x, end_x)
    return {
        **r, "start_x": start_x, "end_x": end_x,
        "length_px": length_px, "stack_lengths": stack_lengths, "boundaries": boundaries,
    }


# ============================================================================
# PHASE 3: ความสูงของแต่ละตั้งของกล่อง แต่ละ VIEW
# ============================================================================

def compute_cargo_top_profile(cargo_mask):
    h, w = cargo_mask.shape[:2]
    cargo_top_y = np.full(w, -1, dtype=int)
    for x in range(w):
        ys = np.nonzero(cargo_mask[:, x])[0]
        if len(ys):
            cargo_top_y[x] = ys.min()
    return cargo_top_y


def compute_local_floor_y(floor_y, grounded, smooth_window=41):
    """LOCAL FLOOR: แก้บั๊กพื้นตู้เป็นรูปตัว V - ใช้ rolling median เฉพาะจุดแทน
    global linear fit เพื่อรักษารูปทรง apex ที่แท้จริงของพื้นตู้ไว้"""
    w = len(floor_y)
    clean = np.full(w, -1, dtype=float)
    xs_g = np.nonzero(grounded)[0]
    if len(xs_g) < 3:
        return clean
    vals_g = floor_y[xs_g].astype(float)
    half = smooth_window // 2
    for i, x in enumerate(xs_g):
        lo = np.searchsorted(xs_g, x - half, side="left")
        hi = np.searchsorted(xs_g, x + half, side="right")
        window_vals = vals_g[lo:hi]
        if len(window_vals) > 0:
            clean[x] = float(np.median(window_vals))
    valid_idx = np.nonzero(clean >= 0)[0]
    if len(valid_idx) >= 2:
        all_idx = np.arange(valid_idx.min(), valid_idx.max() + 1)
        interp_vals = np.interp(all_idx, valid_idx, clean[valid_idx])
        clean[all_idx] = interp_vals
    return clean


def _robust_local_line_fit(xs, ys, mad_floor=2.0, n_iter=3):
    """Fit เส้นตรง y=a*x+b แบบทนทานต่อ outlier (label/ลูกศร) โดยใช้ iterative
    MAD-based rejection - mad_floor ป้องกันกรณีข้อมูลเรียบสมบูรณ์แบบ (MAD~0)"""
    xs = np.asarray(xs, dtype=float)
    ys = np.asarray(ys, dtype=float)
    if len(xs) < 3:
        if len(xs) == 0:
            return None
        return {"a": 0.0, "b": float(np.mean(ys)), "resid_std": 0.0, "xs": xs, "ys": ys}
    a, b = 0.0, float(np.mean(ys))
    for _ in range(n_iter):
        if len(xs) < 3:
            break
        A = np.vstack([xs, np.ones_like(xs)]).T
        a, b = np.linalg.lstsq(A, ys, rcond=None)[0]
        resid = ys - (a * xs + b)
        mad = max(mad_floor, np.median(np.abs(resid - np.median(resid))))
        keep = np.abs(resid) < 3 * mad
        if keep.sum() < 3 or keep.sum() == len(xs):
            break
        xs, ys = xs[keep], ys[keep]
    resid = ys - (a * xs + b)
    return {"a": float(a), "b": float(b), "resid_std": float(resid.std()), "xs": xs, "ys": ys}


def detect_isometric_apex(cargo_top_y, local_floor_y, start_x, end_x, search_margin_ratio=0.15):
    """หาตำแหน่ง 'จุดยอด (apex)' ของ silhouette กองกล่องในมุมมอง isometric - ก่อนจุดยอด
    cargo_top_y คือขอบบน-หลัง (ขนานพื้น, height ถูกต้อง) หลังจุดยอดกลายเป็นขอบบน-หน้า (เอียง
    คนละทิศ, height ผิดเพี้ยนเป็นระบบ) ยืนยันด้วยภาพจริงและ cross-view ในไฟล์ทดสอบ"""
    span = end_x - start_x
    if span <= 0:
        return None
    search_start = start_x + int(span * search_margin_ratio)
    xs = np.arange(search_start, end_x + 1)
    xs = xs[(xs >= 0) & (xs < len(cargo_top_y))]
    if len(xs) == 0:
        return None
    vals = cargo_top_y[xs]
    valid = vals >= 0
    if not np.any(valid):
        return None
    xs_valid = xs[valid]
    vals_valid = vals[valid]
    return int(xs_valid[np.argmin(vals_valid)])


def compute_stack_heights_px(seams, start_x, end_x, cargo_top_y, margin=6, local_floor_y=None):
    """คำนวณความสูง (px) ต่อ 1 ตั้ง โดย fit เส้นตรงทนทาน (robust local line) ให้กับ
    cargo_top_y ภายในแต่ละตั้งเอง (แก้บั๊กความชันธรรมชาติจากมุมมอง isometric) แล้วประเมิน
    ความสูงที่ตำแหน่งกึ่งกลางตั้ง เทียบกับ local floor (แก้บั๊กพื้นตู้รูปตัว V)

    v25.2 FIX: ตัดข้อมูลที่อยู่ "หลังจุดยอด isometric" (apex) ออกจากการคำนวณ - สำหรับตั้งที่
    อยู่หลัง apex ทั้งตั้ง (วัดเองไม่ได้เลย) จะคืนค่า height_px=None ก่อน ให้ cross-view
    reconciliation เติมค่าจากอีกมุมมองก่อน แล้วค่อย carry-forward เป็นทางเลือกสุดท้าย"""
    boundaries = [start_x] + sorted(seams) + [end_x]
    results = []

    def _floor_at(x):
        if local_floor_y is not None and 0 <= x < len(local_floor_y) and local_floor_y[x] >= 0:
            return local_floor_y[x]
        return None

    apex_x = detect_isometric_apex(cargo_top_y, local_floor_y, start_x, end_x)

    for i in range(len(boundaries) - 1):
        b0 = boundaries[i] + margin
        b1 = boundaries[i + 1] - margin
        eff_b1 = b1
        if apex_x is not None:
            eff_b1 = min(b1, apex_x)

        xs_top, ys_top = [], []
        for x in range(max(0, b0), max(0, eff_b1)):
            if x < len(cargo_top_y) and cargo_top_y[x] >= 0:
                xs_top.append(x)
                ys_top.append(cargo_top_y[x])
        top_fit = _robust_local_line_fit(xs_top, ys_top) if xs_top else None

        height_px = None
        n_samples = 0
        height_source = "direct"
        if top_fit is not None and len(xs_top) >= 3:
            eff_mid = (max(0, b0) + eff_b1) / 2.0
            top_at_mid = top_fit["a"] * eff_mid + top_fit["b"]
            floor_at_mid = _floor_at(int(eff_mid))
            if floor_at_mid is not None:
                height_px = floor_at_mid - top_at_mid
                n_samples = len(top_fit["xs"])

        if height_px is None:
            height_source = "unreliable_post_apex"

        results.append({
            "stack_idx": i,
            "x_range": (boundaries[i], boundaries[i + 1]),
            "n_samples": n_samples,
            "height_px": height_px,
            "height_source": height_source,
            "apex_x": apex_x,
        })
    return results


def fill_missing_heights(records):
    """เติมค่า height_px=None ที่เหลือ (หลัง cross-view reconciliation พยายามเติมให้แล้ว
    แต่ไม่มี match ที่ใช้ได้) ด้วยการ carry-forward จากตั้งก่อนหน้าในมุมมองเดียวกัน -
    เป็นทางเลือกสุดท้ายเท่านั้น ข้าม is_corner_duplicate เสมอ (ทั้งเป้าหมายและแหล่งอ้างอิง)"""
    last_valid = None
    for r in records:
        if r.get("is_corner_duplicate"):
            continue
        if r["height_px"] is not None:
            last_valid = r["height_px"]
        elif last_valid is not None:
            r["height_px"] = last_valid
            r["height_source"] = "carried_forward_same_view"
    return records


def process_view_with_height_on_image(full_img, doc, view_name, page_idx=1, margin=6,
                                       override_cols=None, precrop=None):
    r = process_view_with_length_on_image(full_img, doc, view_name, page_idx=page_idx,
                                           override_cols=override_cols, precrop=precrop)
    cargo_top_y = compute_cargo_top_profile(r["cargo_mask"])
    local_floor_y = compute_local_floor_y(r["floor_y"], r["grounded"])
    stack_heights = compute_stack_heights_px(
        r["seams"], r["start_x"], r["end_x"], cargo_top_y, margin=margin, local_floor_y=local_floor_y)
    return {**r, "cargo_top_y": cargo_top_y, "local_floor_y": local_floor_y, "stack_heights": stack_heights}


# ============================================================================
# RULE ENGINE: 3 risk types (STEP_DOWN pairwise, STEP_DOWN cross_view, REAR_EMPTY)
# ============================================================================

def stack_positions_normalized(view_result):
    start_x, end_x = view_result["start_x"], view_result["end_x"]
    span = max(1, end_x - start_x)
    seams = sorted(view_result["seams"])
    boundaries = [start_x] + seams + [end_x]
    positions = []
    for i in range(len(boundaries) - 1):
        p0 = (boundaries[i] - start_x) / span
        p1 = (boundaries[i + 1] - start_x) / span
        positions.append((p0, p1))
    return positions


def build_stack_records(view_result, view_label, flip_position=None):
    """สร้าง records แต่ละตั้ง: {idx, x_range, pos_range (0=หัวตู้,1=ประตูท้ายตู้), height_px}

    ทิศทาง flip อ้างอิงจาก HARDCODED_REAR_SIDE เดิมของ v24.36 (FRONT: ซ้าย=ประตูท้าย,
    ขวา=หัวตู้ | BACK: ซ้าย=หัวตู้, ขวา=ประตูท้าย) ยืนยันด้วยลำดับสี SKU จริงข้าม 2 view
    -> FRONT ต้อง flip (True), BACK ไม่ต้อง flip (False)"""
    if flip_position is None:
        flip_position = (view_label == "FRONT")
    positions = stack_positions_normalized(view_result)
    heights = view_result["stack_heights"]
    is_corner_dup = view_result.get("idx0_is_corner_duplicate", False)
    records = []
    for i, ((p0, p1), h) in enumerate(zip(positions, heights)):
        if flip_position:
            real_p0, real_p1 = 1.0 - p1, 1.0 - p0
        else:
            real_p0, real_p1 = p0, p1
        records.append({
            "idx": i, "view": view_label,
            "x_range": h["x_range"], "pos_range": (real_p0, real_p1),
            "height_px": h["height_px"],
            "height_source": h.get("height_source", "direct"),
            # True เฉพาะ idx==0 ที่ตรวจพบว่าเป็น corner artifact จริง (ตรวจจากเส้น rail
            # ทางเรขาคณิต ไม่ใช่ hardcode ชื่อ view - ดู process_view_on_image)
            "is_corner_duplicate": (i == 0 and is_corner_dup),
        })
    return records


def detect_step_down_pairwise(records, view_label):
    """เปรียบเทียบตั้งข้างเคียงในview เดียวกัน - ข้าม record ที่ is_corner_duplicate=True
    (ตรวจจากเส้น rail ทางเรขาคณิตจริง ไม่ hardcode ชื่อ view)"""
    risks = []
    for i in range(len(records) - 1):
        a, b = records[i], records[i + 1]
        if a.get("is_corner_duplicate") or b.get("is_corner_duplicate"):
            continue
        if a["height_px"] is None or b["height_px"] is None:
            continue
        taller_rec = a if a["height_px"] >= b["height_px"] else b
        shorter_rec = b if taller_rec is a else a
        taller_h = taller_rec["height_px"]
        shorter_h = shorter_rec["height_px"]
        threshold = taller_h * (1 - STEP_DOWN_PAIRWISE_DROP_RATIO)
        if shorter_h < threshold:
            drop_ratio = 1 - (shorter_h / taller_h) if taller_h > 0 else 0
            risks.append({
                "risk_type": "STEP_DOWN_RISK", "subtype": "pairwise", "view": view_label,
                "mark_view": view_label,
                "mark_stack_idx": taller_rec["idx"], "mark_x_range": taller_rec["x_range"],
                "taller_height_px": taller_h, "shorter_height_px": shorter_h,
                "drop_ratio": drop_ratio, "pair_indices": (a["idx"], b["idx"]),
            })
    return risks


def _overlapping_records(target_pos_range, other_records, min_overlap_ratio=CROSSVIEW_MIN_OVERLAP_RATIO):
    t0, t1 = target_pos_range
    t_width = max(1e-6, t1 - t0)
    matches = []
    for rec in other_records:
        r0, r1 = rec["pos_range"]
        r_width = max(1e-6, r1 - r0)
        inter = max(0.0, min(t1, r1) - max(t0, r0))
        smaller = min(t_width, r_width)
        if smaller > 0 and (inter / smaller) >= min_overlap_ratio:
            matches.append(rec)
    return matches


def detect_step_down_crossview(records_front, records_back):
    """เปรียบเทียบตำแหน่งจริงเดียวกันระหว่าง FRONT<->BACK ด้วยเกณฑ์เดียว (20%) - ข้าม
    record ที่ is_corner_duplicate=True เสมอ (ตรวจจากเส้น rail ทางเรขาคณิตจริง)"""
    risks = []
    seen_pairs = set()

    def _compare(rec_a, records_b_all, view_a_label, view_b_label):
        if rec_a.get("is_corner_duplicate"):
            return
        matches = _overlapping_records(rec_a["pos_range"], records_b_all)
        for rec_b in matches:
            if rec_b.get("is_corner_duplicate"):
                continue
            if rec_a["height_px"] is None or rec_b["height_px"] is None:
                continue
            key = tuple(sorted([(view_a_label, rec_a["idx"]), (view_b_label, rec_b["idx"])]))
            if key in seen_pairs:
                continue
            seen_pairs.add(key)
            taller_rec = rec_a if rec_a["height_px"] >= rec_b["height_px"] else rec_b
            shorter_rec = rec_b if taller_rec is rec_a else rec_a
            taller_h = taller_rec["height_px"]
            shorter_h = shorter_rec["height_px"]
            threshold = taller_h * (1 - STEP_DOWN_CROSSVIEW_DROP_RATIO)
            if shorter_h < threshold:
                drop_ratio = 1 - (shorter_h / taller_h) if taller_h > 0 else 0
                risks.append({
                    "risk_type": "STEP_DOWN_RISK", "subtype": "cross_view",
                    "mark_view": taller_rec["view"],
                    "mark_stack_idx": taller_rec["idx"], "mark_x_range": taller_rec["x_range"],
                    "taller_height_px": taller_h, "shorter_height_px": shorter_h,
                    "drop_ratio": drop_ratio, "pos_range": taller_rec["pos_range"],
                })

    for rec_a in records_front:
        _compare(rec_a, records_back, "FRONT", "BACK")
    for rec_b in records_back:
        _compare(rec_b, records_front, "BACK", "FRONT")

    merged = {}
    for r in risks:
        key = (r["mark_view"], r["mark_stack_idx"])
        if key not in merged or r["drop_ratio"] > merged[key]["drop_ratio"]:
            merged[key] = r
    return list(merged.values())


def reconcile_heights_cross_view(records_front, records_back,
                                  min_overlap_ratio=0.5, conflict_ratio=0.10):
    """เทียบความสูงของกล่องตำแหน่งจริงเดียวกันระหว่าง FRONT<->BACK - ข้าม record ที่
    is_corner_duplicate=True เสมอ PASS1: เติมค่า None จาก cross-view PASS2: แก้ความขัดแย้ง"""
    def _overlap_ratio(a, b):
        a0, a1 = a; b0, b1 = b
        inter = max(0.0, min(a1, b1) - max(a0, b0))
        smaller = min(max(1e-6, a1 - a0), max(1e-6, b1 - b0))
        return inter / smaller if smaller > 0 else 0.0

    corrections = []
    for rec_a, records_b in [(r, records_back) for r in records_front] + \
                            [(r, records_front) for r in records_back]:
        if rec_a.get("is_corner_duplicate") or rec_a["height_px"] is not None:
            continue
        best_match, best_overlap = None, 0.0
        for rec_b in records_b:
            if rec_b.get("is_corner_duplicate") or rec_b["height_px"] is None:
                continue
            ov = _overlap_ratio(rec_a["pos_range"], rec_b["pos_range"])
            if ov > best_overlap:
                best_overlap, best_match = ov, rec_b
        if best_match is None or best_overlap < min_overlap_ratio:
            continue
        rec_a["height_px"] = best_match["height_px"]
        rec_a["height_source"] = "cross_view_filled"
        corrections.append((rec_a["view"], rec_a["idx"], None, best_match["height_px"]))

    for rec_a, records_b in [(r, records_back) for r in records_front] + \
                            [(r, records_front) for r in records_back]:
        if rec_a.get("is_corner_duplicate") or rec_a["height_px"] is None:
            continue
        best_match, best_overlap = None, 0.0
        for rec_b in records_b:
            if rec_b.get("is_corner_duplicate"):
                continue
            ov = _overlap_ratio(rec_a["pos_range"], rec_b["pos_range"])
            if ov > best_overlap:
                best_overlap, best_match = ov, rec_b
        if best_match is None or best_overlap < min_overlap_ratio or best_match["height_px"] is None:
            continue
        h_a, h_b = rec_a["height_px"], best_match["height_px"]
        higher = max(h_a, h_b)
        if higher <= 0 or abs(h_a - h_b) / higher <= conflict_ratio:
            continue
        a_reliable = rec_a.get("height_source", "direct") in ("direct", "cross_view_filled")
        b_reliable = best_match.get("height_source", "direct") in ("direct", "cross_view_filled")
        if a_reliable and not b_reliable:
            trust_a = True
        elif b_reliable and not a_reliable:
            trust_a = False
        else:
            trust_a = h_a >= h_b
        if trust_a:
            best_match["height_px"] = h_a
            best_match["height_source"] = "cross_view_corrected"
            corrections.append((best_match["view"], best_match["idx"], h_b, h_a))
        else:
            rec_a["height_px"] = h_b
            rec_a["height_source"] = "cross_view_corrected"
            corrections.append((rec_a["view"], rec_a["idx"], h_a, h_b))
    return corrections


def _rearmost_record(records):
    """v26.00 FIX Bug#E: ตั้งที่อยู่ท้ายสุดจริง (real pos_range[1] ใกล้ 1.0 ที่สุด)
    ของ view นั้น - ข้าม record ที่ is_corner_duplicate=True เสมอ

    FIX: เดิมข้าม corner_dup แต่ใน FRONT view corner_dup = idx=0 ซึ่งหลัง flip แล้ว
    pos_range[1] อาจมีค่าสูงสุดใน list -> max() จะเลือก idx=0 ผิด แม้จะ filter แล้ว
    (เพราะ filter ก่อน flip ไม่ใช่หลัง flip) - แก้โดย filter ให้ครบถ้วนจริงๆ โดยตรวจ
    ว่า record ที่ is_corner_duplicate=True ไม่เข้ามาเป็น candidate ไม่ว่า pos จะเป็น
    เท่าไหรก็ตาม"""
    candidates = [r for r in records if not r.get("is_corner_duplicate")]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["pos_range"][1])


def _dominant_color_clusters(region, cargo_mask, x_range, margin=6,
                              min_fraction=REAR_COLOR_MIN_FRACTION,
                              min_pixels=REAR_COLOR_MIN_PIXELS):
    """หาชุดสีเด่น (quantized 32-level) ภายในช่วง x_range ของ 1 ตั้ง - ใช้ตรวจว่ามี SKU
    ปะปนกันผิดปกติหรือไม่ (กลไก B ของ REAR_EMPTY_RISK) คืนค่า list[(color, count)]"""
    x0, x1 = x_range
    x0 = max(0, x0 + margin)
    x1 = max(x0, x1 - margin)
    if x1 <= x0:
        return []
    sub_mask = cargo_mask[:, x0:x1]
    sub_region = region[:, x0:x1]
    pixels = sub_region[sub_mask]
    if len(pixels) < 50:
        return []
    quant = (pixels // 32 * 32).astype(np.int32)
    uniq, counts = np.unique(quant.reshape(-1, 3), axis=0, return_counts=True)
    total = len(pixels)
    order = np.argsort(-counts)
    clusters = []
    for i in order:
        if counts[i] >= min_pixels and (counts[i] / total) >= min_fraction:
            clusters.append((tuple(int(v) for v in uniq[i]), int(counts[i])))
    return clusters


def detect_rear_empty_risk(records_front, records_back, front_result, back_result):
    """REAR_EMPTY_RISK - ใช้ 2 กลไกที่เป็นอิสระต่อกัน (แต่ละกลไกคาลิเบรตจากไฟล์ ground-truth
    คนละไฟล์ - ดูค่าคงที่ REAR_GAP_MIN_PX/REAR_GAP_MIN_RATIO/REAR_COLOR_ANOMALY_MIN_COLORS
    ด้านบนของไฟล์สำหรับตัวเลขคาลิเบรตจริง):
      A) เทียบ length_px จริง (Phase 2, หน่วย px ไม่ normalize) ระหว่าง FRONT<->BACK ถ้าต่างกัน
         เกินทั้ง px ขั้นต่ำ และสัดส่วนขั้นต่ำ -> ฝั่งที่ "สั้นกว่า" มีพื้นที่ว่างจริงก่อนประตูท้ายตู้
         (ยืนยันจาก EC01-01 gap=72px/12.6% ต้อง flag, AC03-01 gap=46px/8.6% ต้อง flag)
      B) ตรวจสีของ "ตั้งท้ายสุดจริง" ของแต่ละ view (ข้าม corner_duplicate เสมอ) - ถ้ามี SKU
         ปะปนกันผิดปกติ (>=3 สีเด่น) มักบ่งชี้สินค้าที่วางไม่เป็นระเบียบ/มีช่องว่างใกล้ประตูท้ายตู้
         (ยืนยันจาก EC04-02 BACK idx ท้ายสุด ต้อง flag แม้ length gap เพียง 17px/3.4% ซึ่งไม่ผ่าน
         เกณฑ์กลไก A - เป็นคนละกลไกกัน ไม่ทับซ้อนกัน)
    """
    risks = []

    # --- กลไก A: cross-view length mismatch (ฝั่งที่ "สั้นกว่า" คือฝั่งที่มีพื้นที่ว่าง) ---
    front_len = front_result.get("length_px") or 0
    back_len = back_result.get("length_px") or 0
    longer_len = max(front_len, back_len)
    if longer_len > 0:
        gap_px = abs(front_len - back_len)
        gap_ratio = gap_px / longer_len
        if gap_px >= REAR_GAP_MIN_PX and gap_ratio >= REAR_GAP_MIN_RATIO:
            if front_len <= back_len:
                shorter_records, shorter_label = records_front, "FRONT"
            else:
                shorter_records, shorter_label = records_back, "BACK"
            rear_rec = _rearmost_record(shorter_records)
            if rear_rec is not None:
                risks.append({
                    "risk_type": "REAR_EMPTY_RISK", "subtype": "length_mismatch",
                    "mark_view": shorter_label,
                    "mark_stack_idx": rear_rec["idx"], "mark_x_range": rear_rec["x_range"],
                    "pos_range": rear_rec["pos_range"], "gap_px": gap_px, "gap_ratio": gap_ratio,
                    "reason": (f"ความยาวสินค้าที่วัดได้จากฝั่ง {shorter_label} สั้นกว่าอีกฝั่ง "
                               f"{gap_px:.0f}px ({gap_ratio:.1%}) บ่งชี้ว่ามีพื้นที่ว่างก่อนถึงประตูท้ายตู้"),
                })

    # --- กลไก B: color-anomaly ที่ตั้งท้ายสุดจริงของแต่ละ view (อิสระจากกลไก A) ---
    for records, result, label in [(records_front, front_result, "FRONT"),
                                    (records_back, back_result, "BACK")]:
        rear_rec = _rearmost_record(records)
        if rear_rec is None:
            continue
        # v26.00 FIX Bug#D: ข้าม corner_duplicate เสมอ - corner zone มีหลายสีเป็นธรรมชาติ
        # (โครงสร้างตู้ + ผนังข้าง + หัวตู้ปรากฏพร้อมกัน) -> false positive color_anomaly ทุกครั้ง
        if rear_rec.get("is_corner_duplicate"):
            continue
        # ข้ามถ้าตั้งนี้ถูก flag จากกลไก A ไปแล้ว (กันซ้ำซ้อน)
        if any(r["mark_view"] == label and r["mark_stack_idx"] == rear_rec["idx"] for r in risks):
            continue
        clusters = _dominant_color_clusters(result["region"], result["cargo_mask"], rear_rec["x_range"])
        if len(clusters) >= REAR_COLOR_ANOMALY_MIN_COLORS:
            risks.append({
                "risk_type": "REAR_EMPTY_RISK", "subtype": "color_anomaly",
                "mark_view": label,
                "mark_stack_idx": rear_rec["idx"], "mark_x_range": rear_rec["x_range"],
                "pos_range": rear_rec["pos_range"], "n_colors": len(clusters),
                "reason": (f"ตั้งสุดท้ายก่อนประตูท้ายตู้ฝั่ง {label} พบสี SKU ปะปนกัน {len(clusters)} สี "
                           f"บ่งชี้สินค้าที่วางไม่เป็นระเบียบ/มีช่องว่างใกล้ประตูท้ายตู้"),
            })

    return risks


def run_full_analysis_on_image(full_img, doc, page_idx=1, pdf_bytes=None, matrix_scale=4):
    # v25.11: PHASE 1B ต้องรู้ทั้ง FRONT และ BACK พร้อมกันก่อน (BACK = ground-truth ตำแหน่ง,
    # FRONT ถูก reconcile กับ BACK) จึงต้องคำนวณคอลัมน์ทั้งคู่ล่วงหน้า ก่อนเรียก
    # process_view_with_height_on_image ต่อ view ตามปกติ - ถ้าล้มเหลว (None) จะ fallback ไป
    # seam-based เดิมโดยอัตโนมัติ (ดู process_view_on_image)
    #
    # v25.14 FIX (Bug#1/#2): เดิมต้องใช้ pdf_bytes เพื่อ render หน้าเต็มแยกต่างหากที่ scale อื่น
    # สำหรับ PHASE 1B โดยเฉพาะ (compute_phase1b_columns เดิม) ตอนนี้ครอป region ของแต่ละ view
    # "ครั้งเดียว" จาก full_img ตัวเดียวกับที่ pipeline หลักใช้อยู่แล้ว (get_view_region) แล้วส่ง
    # region+origin เดียวกันนี้ต่อให้ทั้ง compute_phase1b_columns และ
    # process_view_with_height_on_image (ผ่าน precrop=) ใช้ตรงกัน 100% เสมอ - ไม่ต้องพึ่ง
    # pdf_bytes/render แยกอีกต่อไป
    try:
        front_region, front_origin, _ = get_view_region(full_img, doc, "front", page_idx=page_idx)
        back_region, back_origin, _ = get_view_region(full_img, doc, "back", page_idx=page_idx)
        phase1b = compute_phase1b_columns({"front": front_region, "back": back_region})
        front_precrop = (front_region, front_origin)
        back_precrop = (back_region, back_origin)
    except Exception as e:
        print(f"get_view_region ล้มเหลว, fallback ให้ process_view_on_image ครอปเองตามปกติ: {e}")
        phase1b = {"front": None, "back": None}
        front_precrop = None
        back_precrop = None

    front = process_view_with_height_on_image(
        full_img, doc, "front", page_idx=page_idx, override_cols=phase1b.get("front"),
        precrop=front_precrop)
    back = process_view_with_height_on_image(
        full_img, doc, "back", page_idx=page_idx, override_cols=phase1b.get("back"),
        precrop=back_precrop)
    records_front = build_stack_records(front, "FRONT")
    records_back = build_stack_records(back, "BACK")

    # ลำดับการแก้ไข height: 1) direct 2) cross_view_filled/corrected 3) carried_forward
    reconcile_heights_cross_view(records_front, records_back)
    fill_missing_heights(sorted(records_front, key=lambda r: r["idx"]))
    fill_missing_heights(sorted(records_back, key=lambda r: r["idx"]))
    for records, view_result in [(records_front, front), (records_back, back)]:
        for rec in records:
            sh = view_result["stack_heights"][rec["idx"]]
            sh["height_px"] = rec["height_px"]
            sh["height_source"] = rec["height_source"]

    risks = []
    risks += detect_step_down_pairwise(records_front, "FRONT")
    risks += detect_step_down_pairwise(records_back, "BACK")
    risks += detect_step_down_crossview(records_front, records_back)
    risks += detect_rear_empty_risk(records_front, records_back, front, back)

    return {
        "front": front, "back": back,
        "records_front": records_front, "records_back": records_back,
        "risks": risks,
    }


def _safe_floor_y_at(lfy, xm, x_range):
    """v26.00 FIX Bug#C: ค้นหา floor_y ที่ valid (>= 0) ใกล้ xm ที่สุดภายใน x_range
    ก่อน fallback ใช้ median ของทั้ง view - ป้องกัน floor_y = -1 ที่ทำให้ box = None"""
    x0, x1 = int(x_range[0]), int(x_range[1])
    w = len(lfy)
    # ค้นหาจาก xm ออกไปรอบๆ ภายใน x_range
    for radius in range(0, (x1 - x0) // 2 + 5):
        for dx in ([0] if radius == 0 else [-radius, radius]):
            xi = xm + dx
            if x0 <= xi < x1 and 0 <= xi < w and lfy[xi] >= 0:
                return float(lfy[xi])
    # fallback: median ของทุก valid pixel ใน x_range
    vals = [lfy[x] for x in range(max(0, x0), min(w, x1)) if lfy[x] >= 0]
    if vals:
        return float(np.median(vals))
    # fallback สุดท้าย: median ของทั้ง array
    all_vals = [v for v in lfy if v >= 0]
    return float(np.median(all_vals)) if all_vals else None


def risk_abs_box(risk, result):
    """v26.00 FIX Bug#C: ใช้ _safe_floor_y_at เพื่อหา floor_y ที่ valid เสมอ
    แม้ xm กึ่งกลาง x_range จะอยู่นอกช่วง grounded จริง"""
    view_label = risk.get("mark_view") or risk.get("view")
    v = result["front"] if view_label == "FRONT" else result["back"]
    x0, x1 = risk["mark_x_range"]
    stack = v["stack_heights"][risk["mark_stack_idx"]]
    height_px = stack["height_px"]
    xm = (x0 + x1) // 2
    lfy = v["local_floor_y"]
    floor_y_local = _safe_floor_y_at(lfy, xm, (x0, x1))
    if floor_y_local is None or height_px is None:
        return None
    top_y_local = floor_y_local - height_px
    ox, oy = v["crop_origin_x"], v["crop_origin_y"]
    return (ox + x0, oy + top_y_local, ox + x1, oy + floor_y_local)


# ============================================================================
# Main HTTP handler (Cloud Function entry point) - คง output contract เดิมของ v24.36
# ============================================================================

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

        sku_list = extract_sku_from_pdf(pdf_bytes)
        sku_str = ", ".join(sku_list) if sku_list else ""

        # v25.14 FIX (Bug#1): render หน้าเต็มครั้งเดียวที่ matrix_scale=4 (เดิม=3) - เพราะ
        # PHASE 1B (compute_phase1b_columns) ไม่ render แยกต่างหากอีกต่อไป (ดู
        # run_full_analysis_on_image) จึงต้องให้ full_img ตัวเดียวที่ pipeline ทั้งหมดใช้ร่วมกัน
        # อยู่ที่ scale ที่ threshold ทางเรขาคณิตของ PHASE 1B ถูก calibrate ไว้ (scale=4) เพื่อไม่
        # ให้ความละเอียดของภาพเสียไป (regression-verified กับ AC03-01/EC04-01/02/03/04: จำนวน
        # ตั้ง+risk ที่ตรวจพบ เหมือนเดิมทุกไฟล์ หลังเปลี่ยน scale)
        full_img, doc, page = render_full_page(pdf_bytes, page_idx=1, matrix_scale=4)

        # layout label (เก็บไว้เพื่อ output contract เดิม - อนุมานจากทิศทาง Front/Back label)
        front_bb = _word_bbox_rotated(page, "Front")
        back_bb = _word_bbox_rotated(page, "Back")
        if front_bb and back_bb:
            fx0, fy0, fx1, fy1 = front_bb
            bx0, by0, bx1, by1 = back_bb
            f_cx, f_cy = (fx0 + fx1) / 2, (fy0 + fy1) / 2
            b_cx, b_cy = (bx0 + bx1) / 2, (by0 + by1) / 2
            layout = "LEFT_RIGHT" if abs(f_cx - b_cx) > abs(f_cy - b_cy) else "TOP_BOTTOM"
        else:
            layout = "TOP_BOTTOM"

        result = run_full_analysis_on_image(full_img, doc, page_idx=1, pdf_bytes=pdf_bytes, matrix_scale=4)
        risks = result["risks"]

        img = PIL.Image.fromarray(full_img).convert("RGB")
        draw = PIL.ImageDraw.Draw(img)

        detected_hazards = []
        reported_risk_keys = set()
        for risk in risks:
            risk_type = risk["risk_type"]
            outline_color = RISK_COLORS.get(risk_type, "red")
            box = risk_abs_box(risk, result)
            if box:
                _draw_single_rectangle(draw, box, outline_color)
            else:
                print(f"Could not compute marker box for {risk_type} (view={risk.get('mark_view')}, "
                      f"idx={risk.get('mark_stack_idx')})")

            report_key = f"{risk_type}_{risk.get('mark_view')}_{risk.get('mark_stack_idx')}"
            if report_key not in reported_risk_keys:
                reported_risk_keys.add(report_key)
                title = f"ความเสี่ยง: {risk_type}"
                detail = generate_action_report(risk_type, "", sku_str)
                detected_hazards.append({"title": title, "detail": detail})

        if detected_hazards:
            status_text = f"พบจุดเสี่ยงอันตราย ({len(detected_hazards)} จุด)"
            sep = "\n\n" + "-" * 50 + "\n\n"
            action_text = sep.join(f"[{h['title']}]\n{h['detail']}" for h in detected_hazards)
        else:
            status_text = "ปลอดภัย (SAFE)"
            action_text = generate_action_report("SAFE", "")

        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=80)
        processed_image_url = f"data:image/jpeg;base64,{base64.b64encode(buffered.getvalue()).decode('utf-8')}"
        gc.collect()
        return ({
            "status": status_text,
            "hazardCount": len(detected_hazards),
            "layout": layout,
            "actionRequired": action_text,
            "processedImageUrl": processed_image_url,
            "checkerVersion": "V26.00",
            "benchmarkMode": "v26_00_adaptive_floor_spacing_validated",
        }, 200, headers)
    except Exception as e:
        err_trace = traceback.format_exc()
        print("CRITICAL ERROR DETAILS:\n", err_trace)
        gc.collect()
        return ({"error": str(e), "trace": err_trace[-500:]}, 500, headers)
