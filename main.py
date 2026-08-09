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
import PIL.ImageOps
import PIL.ImageColor
import fitz  # PyMuPDF
import functions_framework
import google.generativeai as genai

# ---------------------------------------------------------------------------
# AI Cargo Safety Checker - High Precision v24.15
#
# v24.15 - แก้ไขตามผลทดสอบใช้งานจริงเพิ่มเติม (v24.14) พบกรอบแดง (STEP_DOWN_RISK)
#   เท็จอีกรูปแบบหนึ่ง ("วงกลมสีส้ม คือที่เป็นกรอบแดงเกินมา หาสิ่งผิดปกติ และนำออกไป")
#   ยืนยันจากภาพผลลัพธ์จริง 3 ไฟล์ (EC12-01, EC15-01, EC20-02 - ทั้ง 3 ไฟล์กรอบแดง
#   เท็จปรากฏในตำแหน่ง BACK view เดียวกันเป๊ะกับกรอบ TALL_UNSTABLE_RISK สีม่วงแดง
#   (magenta) ที่ตรวจพบถูกต้องอยู่แล้ว)
#
#   ROOT CAUSE: เมื่อมี "ตั้งเดียวสูงโดดเด่นผิดปกติ" (isolated tall peak - เพื่อนบ้าน
#   ทั้ง 2 ฝั่งเตี้ยกว่ามาก, ตรงกับเงื่อนไขที่ detect_tall_unstable_regions_for_view ใช้
#   ตรวจจับ TALL_UNSTABLE_RISK อยู่แล้ว) detect_step_down_regions_from_stacks (v24.13/
#   v24.14) จะมองว่าเพื่อนบ้านทั้ง 2 ฝั่งของตั้งสูงนั้น "เตี้ยกว่าตั้งข้างเคียงที่สูงกว่า"
#   จึง flag เป็น STEP_DOWN_RISK ซ้ำซ้อน - แต่จริงๆ แล้วเป็นปรากฏการณ์เดียวกันกับที่
#   TALL_UNSTABLE_RISK อธิบายไปแล้ว (กล่องสูงโดดเดี่ยว 1 ตั้ง ไม่ใช่ "ที่ราบ/ขั้นบันได"
#   ของกล่องหลายใบที่ควรเป็น STEP_DOWN_RISK จริง)
#
#   วิธีแก้ (ฟังก์ชันใหม่ _is_isolated_tall_peak): ก่อนใช้ตั้งข้างเคียงเป็นฐานเปรียบเทียบ
#   ว่า "สูงกว่า" ในการตรวจสอบ STEP_DOWN_RISK ตรวจสอบก่อนว่าตั้งข้างเคียงนั้นเข้าเกณฑ์
#   "ตั้งสูงโดดเดี่ยว" หรือไม่ (สูงกว่าเพื่อนบ้านของมันเองทั้ง 2 ฝั่ง อย่างน้อย
#   TALL_UNSTABLE_NEIGHBOR_MAX_RATIO) - ถ้าใช่ ให้ข้ามเพื่อนบ้านนั้นไปเลย (ปล่อยให้
#   TALL_UNSTABLE_RISK เป็นผู้รายงานปรากฏการณ์นี้แต่เพียงผู้เดียว ไม่ซ้ำซ้อนกัน)
#
#   ผลลัพธ์ที่คาดหวัง: STEP_DOWN_RISK ยังคงตรวจจับ "ที่ราบ/ขั้นบันได" จริงที่มีตั้ง
#   หลายใบสูงต่อเนื่องกัน (เช่นกรณี ED85-02/EC20-02 ฝั่งอื่นที่ยืนยันถูกต้องแล้ว) แต่จะ
#   ไม่ flag ซ้ำกับกรณีที่เป็นตั้งสูงโดดเดี่ยวเดี่ยวๆ ซึ่งควรรายงานเป็น TALL_UNSTABLE_RISK
#   เพียงอย่างเดียวเท่านั้น
#
# v24.14 - แก้ไขตามผลทดสอบใช้งานจริงกับไฟล์หลากหลาย (v24.13) พบ 3 ปัญหา:
#   ("กรอบสีแดงส่วนหน้ารถ หาพื้นที่ต่ำ ไม่ต้องทำแล้ว ที่ไปหารูโบ๋ ภาพbackผมต้องการให้
#    หาตั้งสินค้าภาพback ที่ต่ำกว่าตั้งข้างเคียง เช่นที่ตีกรอบภาพfront-กรอบ rear empty
#    risk ท้ายรถ กรอบควรสั้นเหมือนกรอบสีเหลืองด้านหน้ารถอื่นๆถ้ามี")
#
#   ROOT CAUSE ที่พบจากภาพผลลัพธ์จริง 10 ไฟล์ (EC10-03, EC11-01, EC12-01, EC13-01,
#   EC15-01, EC18-01, EC20-02, EC26-02, ED85-02, ED85-03): กรอบ STEP_DOWN_RISK
#   (v24.13, เปรียบเทียบความสูงตั้งกล่องที่ติดกัน) ที่ "ถูกต้อง" (เช่น ED85-02,
#   EC20-02, EC15-01) มีขนาดแคบ/พอดีกับกล่องจริงเสมอ แต่ที่ "ผิด" (เช่น EC10-03,
#   EC13-01, EC18-01, EC26-02) กลับมีขนาดใหญ่ผิดปกติ ครอบคลุมกล่องหลายใบ/หลายสี
#   พร้อมกัน - ตรงกับที่ผู้ใช้ระบุว่าเหมือน "หาพื้นที่ต่ำ/รูโบ๋" (พฤติกรรมแบบเดิม)
#
#   สาเหตุที่แท้จริง: build_stack_box_model_for_view() (per-box segmentation, v22-v24)
#   บางครั้ง "รวมกล่องหลายใบสีเดียวกัน/ความสูงเท่ากันเป็นตั้งเดียว" (under-
#   segmentation) โดยเฉพาะเมื่อกล่องเรียงติดกันแนบสนิทไม่มีเส้นแบ่งชัดเจน - เมื่อตั้งที่
#   ถูกรวมผิดนี้ (กว้างผิดปกติ) ถูกนำไปเทียบความสูงกับตั้งข้างเคียงจริงที่มีความสูงต่างกัน
#   (แม้เพียงเล็กน้อย) detect_step_down_regions_from_stacks() (v24.13) จะสร้างกรอบ
#   ที่กว้างเท่าตั้งที่ถูกรวมผิดทั้งหมด (ครอบคลุมกล่องจริงหลายใบ) แทนที่จะเป็นกล่องเดียว
#
#   วิธีแก้ (3 ส่วน):
#
#   ส่วนที่ 1 - STACK-WIDTH SANITY GATE (ใหม่): เพิ่มการตรวจสอบว่าตั้งทั้ง 2 ฝั่งที่จะ
#   นำมาเปรียบเทียบกัน (ทั้งตั้งที่สงสัยว่าเตี้ยกว่า และตั้งข้างเคียงที่อ้างว่าสูงกว่า)
#   ต้องมีความกว้างไม่เกิน STEP_DOWN_STACK_MAX_WIDTH_RATIO (30%) ของความกว้างคาร์โก้
#   ทั้งหมดในมุมมองนั้น - หากตั้งใดตั้งหนึ่งกว้างเกินเกณฑ์นี้ (ส่อว่าเป็นการรวมกล่อง
#   หลายใบผิดพลาด ไม่ใช่กล่องเดียวจริง) จะข้ามการเปรียบเทียบคู่นั้นไปทันที (ถือว่า
#   ไม่น่าเชื่อถือพอจะตัดสิน) - นี่คือการแก้ไขหลักที่ทำให้กรอบใหญ่ผิดปกติหายไปทั้งหมด
#   ทั้งใน FRONT และ BACK (ยืนยันจากภาพจริงว่ากรณีที่ถูกต้อง เช่น ED85-02/EC20-02/
#   EC15-01 ล้วนมีตั้งที่แคบ/ขนาดกล่องเดียวเสมอ ต่างจากกรณีผิดที่ตั้งกว้างผิดปกติ)
#
#   ส่วนที่ 2 - RAW-STACK FALLBACK สำหรับ STEP_DOWN_RISK โดยเฉพาะ (ใหม่): ผู้ใช้ระบุว่า
#   "ภาพ back ต้องการให้หาตั้งสินค้าที่ต่ำกว่าตั้งข้างเคียง เช่นเดียวกับภาพ front" - พบว่า
#   เมื่อ per-box segmentation ของ view ใด view หนึ่ง (มักเป็น BACK เพราะมี occlusion
#   มากกว่า FRONT) มี coverage_ratio ต่ำกว่าเกณฑ์ STACK_COVERAGE_MIN_RATIO (60%) ระบบ
#   จะทิ้งผลการแบ่งกล่องของ view นั้นไปทั้งหมด (stacks=[]) ทำให้ STEP_DOWN_RISK ไม่มี
#   ทางตรวจพบอะไรเลยใน view นั้น แม้จะมีความเสี่ยงจริงอยู่ก็ตาม - วิธีแก้: เก็บผลการ
#   แบ่งกล่อง "แบบ raw" (ไม่ผ่านเกณฑ์ coverage) ไว้ในคีย์แยกต่างหาก (f"{view}_raw_stacks")
#   เสมอ ใช้เป็น fallback เฉพาะสำหรับ STEP_DOWN_RISK เท่านั้น (ไม่กระทบ OVERHANG/
#   TALL_UNSTABLE/REAR_LATERAL_IMBALANCE ซึ่งยังคงต้องใช้ high-confidence data เหมือนเดิม
#   ทุกประการ) พร้อมเกณฑ์ความสูงที่เข้มงวดขึ้น (40% แทน 30%) เพื่อชดเชยความไม่แน่นอน
#   ของข้อมูลคุณภาพต่ำ - ยังคงผ่าน STACK-WIDTH SANITY GATE (ส่วนที่ 1) เหมือนกันทุก
#   ประการ ไม่มีข้อยกเว้น
#
#   ส่วนที่ 3 - REAR_EMPTY_RISK กรอบใหญ่เกิน (ผู้ใช้: "กรอบควรสั้นเหมือนกรอบสีเหลือง
#   ด้านหน้ารถ"): ROOT CAUSE - กรอบ REAR_EMPTY_RISK ส่วนใหญ่มาจาก AI zoom analysis
#   (analyze_rear_zone_with_ai -> box_2d ที่ Gemini เลือกเองจากภาพซูมท้ายตู้) ซึ่งไม่ได้
#   ผ่านการตรวจสอบ/ตัดขอบเขตด้วยพิกเซลจริงเหมือนที่ LATERAL_GAP_RISK ทำ (v24.13) ทำให้
#   บางครั้งกรอบกว้าง/สูงเกินกว่าช่องว่างจริงที่วัดได้ วิธีแก้ (_tighten_zoom_box_to_gap):
#   หลังได้กรอบจาก AI แล้ว ตัด (intersect) ให้ไม่เกินขอบเขตช่องว่างที่วัดได้จริงแบบ
#   deterministic (จาก compute_empty_gap_pixels ซึ่งมีอยู่แล้ว, +padding เล็กน้อย) ก่อน
#   นำไปวาด - ใช้หลักการเดียวกับที่ทำให้ LATERAL_GAP_RISK แคบลงใน v24.13 ทำให้กรอบ
#   REAR_EMPTY_RISK/FRONT_EMPTY_RISK สั้นกระชับสอดคล้องกับขนาดช่องว่างจริงเสมอ ไม่ว่า
#   AI จะเลือกกรอบมาใหญ่แค่ไหนก็ตาม (ปลอดภัย - ถ้าตัดแล้วพื้นที่เหลือ 0 จะใช้กรอบเดิม
#   ของ AI แทน กันกรอบหายไปเลย)
#
# v24.13 - STEP_DOWN_RISK เปลี่ยนวิธีตรวจจับทั้งหมด จาก pixel/height-profile scan +
#   floor-hole scan + cross-view mirror/veto (v24.1-v24.11) ซึ่งไวต่อสัญญาณรบกวนมาก
#   ไปใช้การเปรียบเทียบ "ความสูงรวมของตั้งกล่องที่ติดกันโดยตรง" (per-box stack model
#   เดียวกับ OVERHANG_RISK/TALL_UNSTABLE_RISK/REAR_LATERAL_IMBALANCE) ตามคำขอผู้ใช้:
#   "ค้นหาแค่ตั้งของกล่องที่ต่ำกว่า ตั้งของกล่องด้านข้าง" - ลบฟังก์ชันเดิมที่ไม่ใช้แล้ว
#   ทั้งหมด (floor-hole, height-profile, cross-view, OCR-SKU matching) ออกจากโค้ด
#
#   นอกจากนี้ยังแก้ไข LATERAL_GAP_RISK (กรอบฟ้า) และ FRONT/REAR_EMPTY_RISK (กรอบเหลือง)
#   ที่ตีกรอบใหญ่เกินจริง: LATERAL_GAP_RISK เดิมใช้ x0,x1=คาร์โก้เต็มความยาวเสมอ แก้ไข
#   ด้วยการสแกน pixel หาช่วงที่ว่างจริงก่อน (_localize_lateral_gap_x_range) FRONT/
#   REAR_EMPTY_RISK (fallback box) เดิมคำนวณความสูงจาก container+cargo รวมกันทำให้ยืด
#   เต็มความสูงเสมอ แก้ไขให้ใช้เฉพาะความสูงคาร์โก้จริงเท่านั้น
#
# v24.12 - 3 การแก้ไขตามคำขอผู้ใช้หลังทดสอบ v24.11:
#
#   1) FLOOR-HOLE FALLBACK สำหรับ view ที่ per-box segmentation coverage ต่ำ (ผู้ใช้
#      สังเกต: "FRONT พบตั้งเตี้ยหัวตู้ แต่ BACK ไม่พบ - เพราะไม่ได้ค้นหาแบบเดียวกัน
#      หรือไม่") ROOT CAUSE ที่ยืนยันแล้ว: ตัวโค้ดค้นหาเหมือนกันทุกประการทั้ง 2 view
#      (loop เดียวกัน) แต่ build_stack_box_model_per_view() เดิมจะ "ทิ้ง" ผลการแบ่ง
#      กล่องทั้งหมดของ view ที่ coverage_ratio < 0.60 ไปเลย (result[view]=[] และไม่
#      เคยตั้งค่า coverage_ratio) ทำให้ floor-hole validation หาตั้งไม่เจอ จึงปฏิเสธ
#      ทุก candidate ของ view นั้นเสมอ (BACK มักมี occlusion มากกว่า FRONT ทำให้
#      coverage ต่ำกว่าบ่อยกว่า) วิธีแก้: เก็บผลการแบ่งกล่อง "แบบ raw" (ไม่ผ่านเกณฑ์
#      coverage) ไว้ในคีย์แยก (f"{view}_raw_stacks") เสมอ ให้ floor-hole validation ใช้
#      เป็น fallback (พร้อมเกณฑ์ความสูงที่เข้มงวดขึ้น 45% แทน 30% เพื่อชดเชยความไม่
#      แน่นอนของข้อมูล) โดยไม่กระทบ OVERHANG/TALL_UNSTABLE/LATERAL_IMBALANCE/cross-view
#      ที่ยังคงใช้เฉพาะ high-confidence data เหมือนเดิมทุกประการ
#
#   2) จำกัดขนาดกรอบทุกประเภทความเสี่ยงให้ใกล้เคียงขนาดจริงของกล่อง/บริเวณที่วิเคราะห์
#      ("เลยมาได้นิดหน่อย") - พบบั๊กที่ STEP_DOWN_RISK (height-profile method) เดิมใช้
#      y_max=container_ymax เสมอ (ยืดกรอบไปจนสุดพื้นตู้เต็มความสูง แม้กล่องจริงในบริเวณ
#      นั้นจะเตี้ยกว่ามาก) แก้ไขด้วยการวัด "พื้นเฉพาะจุด" (local floor) จากพิกเซลจริง
#      แทน เพิ่มฟังก์ชันกลาง _region_to_padded_normalized_box() (ขยายกรอบออกเล็กน้อย
#      ~6px จากขอบเขตจริง + clip ไม่ให้ล้ำเข้า view อื่น) แทนที่โค้ด normalize พิกัด
#      แบบ inline ที่กระจายอยู่ 5 จุด (OVERHANG, TALL_UNSTABLE, LATERAL_GAP x2,
#      STEP_DOWN) ให้ใช้หลักการเดียวกันทั้งหมด
#
#   3) รายงานคำอธิบายความเสี่ยงซ้ำประเภทเดียวกัน แค่ 1 ครั้ง (ผู้ใช้: "พบ
#      STEP_DOWN_RISK จำนวน 2 เคส ระบุตัวเลข 2 แต่คำอธิบายด้านล่างมีแค่ 1 อันพอ") -
#      แยกการนับ (instance_key ยังคง position-aware แบบ v24.8 ใช้กับ hazardCount) ออก
#      จากการแสดงข้อความ (group_key ใหม่ - จัดกลุ่มตาม risk_type อย่างเดียว ไม่รวม
#      ตำแหน่ง) แสดงคำอธิบายเพียง 1 ครั้งต่อประเภท พร้อมต่อท้ายชื่อเรื่องด้วย
#      "(พบ N จุด)" เมื่อ N > 1 - hazardCount ยังคงเป็นจำนวนจุดเสี่ยงจริงทั้งหมดเหมือนเดิม
#
# v24.11 - ROLLBACK ภาพ (ตัด v24.9 quad-corner/parallelogram + v24.10 halo effect
#   ออก กลับไปใช้สี่เหลี่ยมผืนผ้าตรง + สีชื่อมาตรฐานแบบ v24.8) และเพิ่มการตรวจสอบไขว้กับ
#   per-box stack model ก่อนยอมรับ floor-hole candidate (กันจับผนังตู้เปล่าผิดพลาด)
# v24.10 - [ROLLED BACK] เคยเพิ่ม halo/outline effect + hex-color scheme ให้กรอบ
# v24.9 - [REMOVED] เคยเปลี่ยนกรอบเป็น parallelogram เอียงตามมุมมอง isometric
# v24.8 - [REMOVED ใน v24.13] เคยเพิ่ม FLOOR-HOLE DETECTION (ตรวจจับ "รูโบ๋" จาก
#   ระยะห่างพื้น/ผนังตู้ที่โผล่ให้เห็น) เป็นสัญญาณเสริมสำหรับ STEP_DOWN_RISK
# v24.7 - [REMOVED ใน v24.13] เคยเพิ่ม OCR-BASED SKU MATCHING (Tesseract) เป็นชั้น
#   เสริมให้ cross-view verification - พบว่าอ่านฟอนต์ตกแต่งของ MaxLoad Pro ไม่ได้เลย
#   (0% success rate) จึงไม่มีผลใช้งานจริง
# v24.6 - [REMOVED ใน v24.13] เคยเพิ่ม CROSS-VIEW VERIFICATION (เปรียบเทียบตำแหน่ง
#   ทางกายภาพระหว่าง FRONT/BACK view ด้วย depth-ratio mapping) สำหรับ veto/mirror
#   STEP_DOWN_RISK - ทั้ง v24.6/v24.7/v24.8 ถูกแทนที่ด้วยวิธีเปรียบเทียบความสูงตั้งกล่อง
#   ที่ติดกันโดยตรง (detect_step_down_regions_from_stacks, v24.13) ซึ่งแม่นยำกว่าและ
#   ใช้โค้ดน้อยกว่ามาก - ดู CHANGELOG v24.13/v24.14 ด้านบนสำหรับรายละเอียดเต็ม
#
# v24.5/v24.4 - [REMOVED ใน v24.13] เคยปรับปรุง _detect_height_profile() (pixel/
#   color filtering) สำหรับ STEP_DOWN_RISK height-profile scan - แทนที่ทั้งหมดด้วย
#   detect_step_down_regions_from_stacks() ใน v24.13 (ดู CHANGELOG ด้านบน)
#
# v24.4 - เพิ่มการกรอง "สีโครงสร้างตู้" ออกจากการตรวจจับคาร์โก้แบบผ่อนปรน (lenient)
#   สำหรับ STEP_DOWN_RISK height-profile scan โดยเฉพาะ
#
# v24.3 - เพิ่ม LOCAL DEPTH-GAP SCAN ตรวจจับ "หลุมเฉพาะจุด" ที่ compute_lateral_gap_ratio
#   (whole-container average) พลาดไป - ยืนยันจาก EC50-01/EC51-02
#
# v24.2 - แก้บั๊กตำแหน่งกรอบผิดของ LATERAL_GAP_RISK (ED86-03) ด้วย
#   get_precise_lateral_gap_box() เปรียบเทียบช่องว่างบน-ล่างแยกกัน
#
# v24.1 - Majority-vote top-row (TOP_ROW_MAJORITY_RATIO), edge-based STEP_DOWN
#   comparison, extract_unused_floor_mm() จาก PDF โดยตรง
#
# v24 - แก้ปัญหา under-segmentation หลัก: เพิ่ม COLOR-STEP + FLOOR/EDGE-JUMP boundary
#   detection รวมกับ dark-dip เดิม (union) + VETO GATE สำหรับ REAR_LATERAL_IMBALANCE
#
# v23.1 - LOCAL FLOOR (พื้นเฉพาะจุด) แทน global floor-line V-shape
# v23 - PERSPECTIVE/ISOMETRIC FLOOR detection (พื้นตู้เป็นรูปตัว V)
# v22 - PER-BOX SEGMENTATION (deterministic) สำหรับ OVERHANG/TALL_UNSTABLE/
#   REAR_LATERAL_IMBALANCE
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

# v24.11: ROLLBACK - กลับไปใช้สีชื่อมาตรฐาน (แบบ v24.8) ตามคำขอผู้ใช้ที่ต้องการรูปทรง
# กรอบสี่เหลี่ยมธรรมดา ไม่ใช้ halo/hex-color scheme ของ v24.10 อีกต่อไป
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
UNUSED_FLOOR_MIN_MM = 100
UNUSED_FLOOR_RELAXED_GAP_RATIO = 0.06

LOCAL_GAP_SAMPLE_STEP_PX = 5
LOCAL_GAP_SEARCH_MARGIN_PX = 20
LOCAL_GAP_SMOOTH_WINDOW = 11
LOCAL_GAP_MIN_PX = 15
LOCAL_GAP_MIN_WIDTH_PX = 60
LOCAL_GAP_MIN_RAW_COVERAGE = 0.65
LOCAL_GAP_RAW_LOWER_THRESH = 8
LOCAL_GAP_MAX_ROUGHNESS = 0.35
LOCAL_GAP_WALL_ZONE_MARGIN_RATIO = 0.20
LOCAL_GAP_DOOR_ZONE_MARGIN_RATIO = 0.15

# ---------------------------------------------------------------------------
# STEP_DOWN_RISK constants (v24.13/v24.14) - เปรียบเทียบความสูงตั้งกล่องที่ติดกัน
# ---------------------------------------------------------------------------

STEP_DOWN_STACK_MIN_RATIO = 0.30          # ตั้งข้างเคียงต้องสูงกว่าตั้งที่พิจารณาอยู่
                                            # อย่างน้อย 30% ของความสูงตั้งที่สูงกว่า
                                            # จึงจะถือว่าเป็น step-down จริง
STEP_DOWN_STACK_MIN_HEIGHT_PX = 15         # ตั้งที่เตี้ยเกินไป (วัดความสูงไม่น่าเชื่อถือ
                                            # พอ) จะไม่ถูกนำมาเปรียบเทียบเลย

# v24.14 NEW: STACK-WIDTH SANITY GATE - ดู CHANGELOG หัวไฟล์สำหรับรายละเอียด root
# cause เต็มรูปแบบ (ยืนยันจากภาพผลลัพธ์จริง 10 ไฟล์) - ป้องกันกรอบใหญ่ผิดปกติที่เกิด
# จาก per-box segmentation รวมกล่องหลายใบเป็นตั้งเดียวผิดพลาด (under-segmentation)
STEP_DOWN_STACK_MAX_WIDTH_RATIO = 0.30    # ตั้งทั้ง 2 ฝั่งที่นำมาเปรียบเทียบกัน (ทั้งตั้ง
                                            # เตี้ยและตั้งข้างเคียงที่สูงกว่า) ต้องกว้างไม่
                                            # เกิน 30% ของความกว้างคาร์โก้ทั้งหมด มิฉะนั้น
                                            # ถือว่าน่าจะเป็นการรวมกล่องหลายใบผิดพลาด
                                            # ไม่ใช่กล่องเดียวจริง - ข้ามคู่นั้นไปทันที

# v24.14 NEW: RAW-STACK FALLBACK เฉพาะสำหรับ STEP_DOWN_RISK - ใช้เมื่อ view ใด view
# หนึ่ง (มักเป็น BACK) มี per-box segmentation coverage ต่ำกว่าเกณฑ์ปกติ
# (STACK_COVERAGE_MIN_RATIO) จนถูกทิ้งไปทั้งหมด - ทำให้ STEP_DOWN_RISK ไม่มีทาง
# ตรวจพบอะไรเลยใน view นั้น (ผู้ใช้ระบุปัญหานี้ตรงๆ: "ภาพ back ต้องการให้หาตั้งสินค้าที่
# ต่ำกว่าตั้งข้างเคียง เช่นเดียวกับภาพ front") - ใช้เกณฑ์ที่เข้มงวดกว่าปกติ (สูงกว่า)
# เพื่อชดเชยความไม่น่าเชื่อถือของข้อมูลคุณภาพต่ำ ยังคงผ่าน STACK-WIDTH SANITY GATE
# เหมือนกันทุกประการ ไม่มีข้อยกเว้น - ไม่กระทบ OVERHANG/TALL_UNSTABLE/
# REAR_LATERAL_IMBALANCE ซึ่งยังคงต้องใช้ high-confidence data เหมือนเดิมทุกประการ
STEP_DOWN_STACK_MIN_RATIO_FALLBACK = 0.40

STEP_DOWN_CLAIM_OVERLAP_THRESHOLD = 0.10  # gate สำหรับตรวจสอบว่า Gemini AI claim
                                            # ทับซ้อนกับ deterministic region หรือไม่


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


def _is_probable_structure_color(rgb):
    """
    v24.4/v24.5 NEW: ตรวจจับ 'ลายนิ้วมือสี' ของพื้น/ผนัง/ขอบหลังคาตู้ (container
    structure) - สีเหล่านี้มี R≈G ในขณะที่ B ต่ำกว่าอย่างชัดเจน (โทนเหลือง/เขียวมะกอก)
    และมี SATURATION ปานกลาง (0.25-0.62) ต่างจากคาร์โก้จริงที่มัก saturation สูงมาก
    """
    r, g, b = rgb
    if abs(r - g) > 10:
        return False
    if not (r > b and g > b):
        return False
    sat = _hsv_saturation(rgb)
    return 0.25 <= sat <= 0.62


def _is_grayscale_color(rgb, tol=25):
    """v24.5 NEW: ตรวจจับสีเทา (R≈G≈B) ซึ่งมักเป็น anti-aliasing ของตัวอักษร/ป้าย
    บอกระยะทาง ไม่ใช่คาร์โก้ (คาร์โก้ใช้สีสันชัดเจนเสมอในไดอะแกรมนี้)"""
    r, g, b = rgb
    return (max(r, g, b) - min(r, g, b)) <= tol


def _is_cargo_pixel_lenient(rgb, min_brightness=40, white_thresh=245):
    """v24.4/v24.5 NEW: เกณฑ์ตรวจจับคาร์โก้แบบผ่อนปรน (ไม่บังคับ saturation>=0.75)
    สำหรับ STEP_DOWN_RISK height-profile scan - กรองโครงสร้างตู้/ข้อความ/ลูกศร/
    พื้นหลังขาวออกอย่างรัดกุมก่อน"""
    r, g, b = rgb
    if r >= white_thresh and g >= white_thresh and b >= white_thresh:
        return False
    if max(r, g, b) < min_brightness:
        return False
    if _is_grayscale_color(rgb):
        return False
    if _is_probable_structure_color(rgb):
        return False
    if _is_arrow_color(rgb):
        return False
    return True


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


LATERAL_GAP_BOX_MIN_WIDTH_PX = 40   # ความกว้างขั้นต่ำของช่วง x ที่ยอมรับว่าเป็น "ช่วงว่าง
                                     # จริง" ที่หาเจอจาก pixel scan - กันสัญญาณรบกวน
                                     # (เช่น เส้นขอบบางๆ ระหว่างกล่อง 2 ใบ) ที่แคบเกินไป


def _localize_lateral_gap_x_range(full_img, cargo_xmin, cargo_xmax, gap_y0, gap_y1):
    """
    v24.13 NEW: หาช่วง x (พิกัดสัมบูรณ์บนภาพเต็ม) ที่ "ว่างจริง" ภายในแถบความสูง
    gap_y0-gap_y1 แทนที่จะสมมติว่าช่องว่างนี้กว้างเท่ากับคาร์โก้ทั้งหมดเสมอ (แก้บั๊กที่
    กรอบ LATERAL_GAP_RISK ยืดเต็มความยาวคาร์โก้เสมอ - ตามคำขอผู้ใช้ "กรอบฟ้าใหญ่เกิน")

    สแกนทีละคอลัมน์ x ภายในช่วงคาร์โก้ ตรวจสอบว่ามี pixel สีคาร์โก้ปรากฏอยู่ภายในแถบ
    gap_y0-gap_y1 หรือไม่ - คอลัมน์ที่ "ไม่มีคาร์โก้อยู่ในแถบนั้นเลย" ถือเป็นส่วนหนึ่งของ
    ช่องว่างจริง แล้วหา run ต่อเนื่องที่ยาวที่สุด คืนค่า (x_min, x_max) หรือ None
    """
    try:
        px = full_img.convert("RGB").load()
        w, h = full_img.size
        x0 = max(0, int(cargo_xmin)); x1 = min(w, int(cargo_xmax))
        y0 = max(0, int(gap_y0)); y1 = min(h, int(gap_y1))
        if x1 <= x0 or y1 <= y0:
            return None

        best_start, best_len = None, 0
        cur_start, cur_len = None, 0
        for x in range(x0, x1):
            has_cargo = any(_is_vivid_cargo_color(px[x, y]) for y in range(y0, y1))
            is_empty = not has_cargo
            if is_empty:
                if cur_start is None:
                    cur_start = x
                cur_len += 1
                if cur_len > best_len:
                    best_len = cur_len
                    best_start = cur_start
            else:
                cur_start, cur_len = None, 0

        if best_start is None or best_len < LATERAL_GAP_BOX_MIN_WIDTH_PX:
            return None
        return (best_start, best_start + best_len)
    except Exception as e:
        print(f"WARNING: Lateral-gap x-range localization failed ({e}) - falling back to full cargo width")
        return None


def get_precise_lateral_gap_box(view_container, view_cargo, full_img=None):
    """v24.2: คำนวณตำแหน่งกรอบแม่นยำสำหรับ LATERAL_GAP_RISK โดยเปรียบเทียบช่องว่าง
    บน-ล่างแยกกัน แล้ววาดกรอบเฉพาะฝั่งที่มีช่องว่างจริงมากกว่า"""
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
    pad = max(3, int((y1 - y0) * 0.15))
    # v24.13 FIX: เดิม x0,x1 = คาร์โก้ทั้งหมด (เต็มความยาว) เสมอ ทำให้กรอบใหญ่เกินจริง
    # พยายามหาช่วง x เฉพาะจุดที่ว่างจริงก่อน (pixel-verified) มีเพียงเมื่อหาไม่พบ
    # เท่านั้นจึง fallback กลับไปใช้เต็มความยาวคาร์โก้เหมือนเดิม (ปลอดภัย)
    if full_img is not None:
        localized = _localize_lateral_gap_x_range(full_img, x0, x1, y0, y1)
        if localized:
            print(f"LATERAL_GAP_RISK box localized (pixel-verified): x=[{localized[0]}-{localized[1]}] "
                  f"(was full cargo width x=[{x0}-{x1}])")
            x0, x1 = localized
    return (x0, max(0, y0 - pad), x1, y1 + pad)


# ---------------------------------------------------------------------------
# LOCAL DEPTH-GAP SCAN (v24.3)
# ---------------------------------------------------------------------------

def _raw_local_gap_profile(px, x_range, y_search, step=LOCAL_GAP_SAMPLE_STEP_PX):
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
    px = view_img.convert("RGB").load()
    w, h = view_img.size
    cargo_xmin = max(0, int(cargo_xmin)); cargo_xmax = min(w, int(cargo_xmax))
    cargo_width = cargo_xmax - cargo_xmin
    if cargo_width <= 0:
        return []

    if wall_side == "RIGHT":
        scan_x0 = cargo_xmin + int(cargo_width * LOCAL_GAP_DOOR_ZONE_MARGIN_RATIO)
        scan_x1 = cargo_xmax - int(cargo_width * LOCAL_GAP_WALL_ZONE_MARGIN_RATIO)
    else:
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


# NOTE (v24.13): FLOOR-HOLE DETECTION and the old pixel/height-profile STEP_DOWN_RISK
# scan were REMOVED here - replaced by detect_step_down_regions_from_stacks()
# (per-box stack-height comparison, see CHANGELOG v24.13/v24.14 above).


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
# ---------------------------------------------------------------------------

BOX_BOUNDARY_MIN_DROP = 22
BOX_BOUNDARY_MAX_THICKNESS_PX = 6
STACK_MIN_WIDTH_PX = 18
BOX_MIN_HEIGHT_PX = 4
BOX_MIN_HEIGHT_RATIO = 0.12
TOP_ROW_MAJORITY_RATIO = 0.65

STACK_COVERAGE_MIN_RATIO = 0.60

OVERHANG_MIN_RATIO = 0.20
OVERHANG_MIN_ABS_PX = 20
TALL_UNSTABLE_MIN_HEIGHT_RATIO = 0.35
TALL_UNSTABLE_NEIGHBOR_MAX_RATIO = 0.65
LATERAL_IMBALANCE_MIN_RATIO = 0.40

LATERAL_IMBALANCE_VETO_MAX_RATIO = 0.20
LATERAL_IMBALANCE_VETO_MIN_COVERAGE = 0.75


def _luminance(rgb):
    r, g, b = rgb
    return 0.299 * r + 0.587 * g + 0.114 * b


def _find_dark_boundary_lines_1d(profile, min_drop=BOX_BOUNDARY_MIN_DROP, max_thickness=BOX_BOUNDARY_MAX_THICKNESS_PX):
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
    """รวม 3 สัญญาณ: dark-dip + color-step + floor/edge-jump แบบ union"""
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
    last_y = None
    for y in range(y_top, y_bot):
        if _is_vivid_cargo_color(px[x, y]):
            last_y = y
    return last_y


def _find_cargo_present_clusters(px, cargo_xmin, cargo_xmax, y_search_top, y_search_bottom):
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
    sample_step = max(1, (x1 - x0) // 12)
    for y in range(0, floor_y):
        sample_xs = list(range(x0, x1, sample_step))
        cargo_count = sum(1 for x in sample_xs if _is_vivid_cargo_color(px[x, y]))
        row_has_cargo = (cargo_count / len(sample_xs)) >= TOP_ROW_MAJORITY_RATIO if sample_xs else False
        if row_has_cargo:
            top_y = y
            break
    if top_y is None:
        return []

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

        # v24.14 NEW: FALLBACK สำหรับ view ที่ coverage ต่ำ (เช่น BACK view ที่มักมี
        # occlusion มากกว่า FRONT ทำให้แบ่งกล่องได้ไม่ครอบคลุมพอ) - ROOT CAUSE ที่ผู้ใช้
        # ระบุตรงๆ: "ภาพ back ต้องการให้หาตั้งสินค้าที่ต่ำกว่าตั้งข้างเคียง เช่นเดียวกับ
        # ภาพ front" - เดิมเมื่อ coverage_ratio < STACK_COVERAGE_MIN_RATIO จะ "continue"
        # ทิ้งผลการแบ่งกล่องของ view นั้นไปทั้งหมด (result[view] ค้างเป็น []) ทำให้
        # STEP_DOWN_RISK ไม่มีทางตรวจพบอะไรเลยใน view นั้น แม้จะมีความเสี่ยงจริงอยู่ก็ตาม
        #
        # วิธีแก้: เก็บผลการแบ่งกล่อง "แบบ raw" (ไม่ผ่านเกณฑ์ coverage) ไว้ในคีย์แยก
        # ต่างหาก (f"{view}_raw_stacks") เสมอ ใช้เป็น fallback เฉพาะสำหรับ STEP_DOWN_RISK
        # เท่านั้น (detect_step_down_regions_from_stack_model_per_view) พร้อมเกณฑ์ความสูง
        # ที่เข้มงวดขึ้น (STEP_DOWN_STACK_MIN_RATIO_FALLBACK=40%) เพื่อชดเชยความไม่แน่นอน
        # ของข้อมูลคุณภาพต่ำ - ยังคงผ่าน STACK-WIDTH SANITY GATE เหมือนกันทุกประการ
        #
        # สำคัญ: result[view] หลัก (ที่ OVERHANG_RISK/TALL_UNSTABLE_RISK/
        # REAR_LATERAL_IMBALANCE ใช้) ยังคงพฤติกรรมเดิมทุกประการ (ว่างเปล่าเมื่อ
        # coverage ต่ำ) - ไม่ได้รับผลกระทบจากการแก้ไขนี้เลย
        result[f"{view}_raw_stacks"] = stacks_abs
        result[f"{view}_coverage_ratio"] = coverage_ratio

        if coverage_ratio < STACK_COVERAGE_MIN_RATIO:
            print(f"Per-box segmentation ({view}) REJECTED for high-confidence risk types "
                  f"(OVERHANG/TALL_UNSTABLE/LATERAL_IMBALANCE) - coverage_ratio={coverage_ratio:.2f} "
                  f"< threshold {STACK_COVERAGE_MIN_RATIO} (raw segmentation still saved as "
                  f"'{view}_raw_stacks' - used ONLY as best-effort fallback for STEP_DOWN_RISK)")
            continue

        result[view] = stacks_abs
        print(f"Per-box segmentation ({view}): coverage_ratio={coverage_ratio:.2f}, "
              f"{len(stacks_abs)} stack(s) detected, "
              f"box counts per stack = {[len(s['boxes']) for s in stacks_abs]}")
    return result


def detect_overhang_regions_for_view(stacks):
    regions = []
    for s in stacks:
        boxes = s["boxes"]
        for i in range(len(boxes) - 1):
            upper = boxes[i]; lower = boxes[i + 1]
            lower_width = max(1, lower["x_right"] - lower["x_left"])
            left_overhang = lower["x_left"] - upper["x_left"]
            right_overhang = upper["x_right"] - lower["x_right"]
            overhang_px = max(left_overhang, right_overhang, 0)
            ratio = overhang_px / lower_width
            if ratio >= OVERHANG_MIN_RATIO and overhang_px >= OVERHANG_MIN_ABS_PX:
                x_min = min(upper["x_left"], lower["x_left"]); x_max = max(upper["x_right"], lower["x_right"])
                regions.append({"x_min": x_min, "y_min": upper["y_min"], "x_max": x_max, "y_max": lower["y_max"], "ratio": ratio})
    return regions


def detect_tall_unstable_regions_for_view(stacks):
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


def get_max_lateral_imbalance_ratio_in_zone(stacks, rear_x0, rear_x1):
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


# ---------------------------------------------------------------------------
# STEP_DOWN_RISK - v24.13/v24.14: DETERMINISTIC STACK-HEIGHT COMPARISON
# ตามคำขอผู้ใช้ตรงตัว: "ค้นหาแค่ตั้งของกล่องที่ต่ำกว่า ตั้งของกล่องด้านข้าง" - ใช้
# per-box stack model เดียวกับ OVERHANG_RISK/TALL_UNSTABLE_RISK/REAR_LATERAL_IMBALANCE
# แทนที่วิธีเดิมทั้งหมด (height-profile scan, floor-hole scan, cross-view mirror/veto)
# v24.14 เพิ่ม STACK-WIDTH SANITY GATE + RAW-STACK FALLBACK - ดู CHANGELOG หัวไฟล์
# ---------------------------------------------------------------------------

def _stack_width(s):
    return max(1, s["x1"] - s["x0"])


def _is_isolated_tall_peak(idx, heights, min_height_px,
                            neighbor_max_ratio=TALL_UNSTABLE_NEIGHBOR_MAX_RATIO):
    """
    v24.15 NEW: ตรวจสอบว่าตั้งที่ตำแหน่ง idx เป็น "ตั้งสูงโดดเดี่ยว" (isolated tall
    peak) หรือไม่ - คือกรณีที่ตั้งนี้สูงกว่าตั้งข้างเคียง "ทั้ง 2 ฝั่ง" อย่างมีนัยสำคัญ
    (เกณฑ์เดียวกับ detect_tall_unstable_regions_for_view ที่ใช้กับ TALL_UNSTABLE_RISK
    อยู่แล้ว) - ใช้แยกแยะระหว่าง "ตั้งเดียวที่สูงโดดเด่นผิดปกติ" (ซึ่งควรถูกจัดเป็น
    TALL_UNSTABLE_RISK เท่านั้น) กับ "ที่ราบสูง/ขั้นบันไดจริง" (ตั้งหลายตั้งที่สูง
    ต่อเนื่องกัน ซึ่งเป็น STEP_DOWN_RISK ที่แท้จริง)

    ดู CHANGELOG v24.15 หัวไฟล์สำหรับรายละเอียด root cause (ยืนยันจากภาพผลลัพธ์จริง:
    EC12-01/EC15-01/EC20-02 - กรอบแดง STEP_DOWN_RISK เท็จซ้อนทับ/อยู่ติดกับกรอบม่วงแดง
    TALL_UNSTABLE_RISK ที่ถูกต้องอยู่แล้วเสมอ)
    """
    h = heights[idx]
    if h is None or h < min_height_px:
        return False
    neighbor_heights = []
    if idx > 0:
        neighbor_heights.append(heights[idx - 1])
    if idx < len(heights) - 1:
        neighbor_heights.append(heights[idx + 1])
    neighbor_heights = [nh for nh in neighbor_heights if nh is not None]
    if not neighbor_heights:
        return False
    return all(nh <= h * neighbor_max_ratio for nh in neighbor_heights)


def detect_step_down_regions_from_stacks(stacks, cargo_width_px,
                                          min_ratio=STEP_DOWN_STACK_MIN_RATIO,
                                          min_height_px=STEP_DOWN_STACK_MIN_HEIGHT_PX,
                                          max_width_ratio=STEP_DOWN_STACK_MAX_WIDTH_RATIO):
    """
    v24.13 NEW / v24.14 FIX / v24.15 FIX: ตรวจจับ STEP_DOWN_RISK จากการเปรียบเทียบ
    "ความสูงรวมของตั้งกล่อง" (จาก per-box stack model) ระหว่างตั้งที่ติดกันโดยตรง
    เท่านั้น (ซ้ายหรือขวา) - ไม่ใช้ pixel/height-profile scan หรือ floor-hole scan อีก

    v24.14 - STACK-WIDTH SANITY GATE: ปฏิเสธคู่ใดๆ ที่มีตั้งฝั่งใดฝั่งหนึ่งกว้างเกิน
    max_width_ratio ของความกว้างคาร์โก้ทั้งหมด (ป้องกัน per-box segmentation ที่รวม
    กล่องหลายใบผิดพลาดเป็นตั้งเดียว - ดู CHANGELOG v24.14)

    v24.15 - ISOLATED-PEAK EXCLUSION (ใหม่): ผู้ใช้ทดสอบพบว่ากรอบแดง STEP_DOWN_RISK
    เท็จปรากฏซ้ำซ้อน/ติดกับกรอบ TALL_UNSTABLE_RISK ที่ถูกต้องอยู่แล้วเสมอ (ยืนยันจาก
    ภาพจริง EC12-01/EC15-01/EC20-02 - วงกลมส้มชี้ตำแหน่งเดียวกับกรอบม่วงแดง) ROOT
    CAUSE: เมื่อมีตั้งเดียวสูงโดดเด่นผิดปกติ (isolated tall peak - เพื่อนบ้านทั้ง 2
    ฝั่งเตี้ยกว่ามาก) การเปรียบเทียบแบบเดิมจะมองว่าเพื่อนบ้านทั้ง 2 ฝั่งนั้น "เตี้ยกว่า
    ตั้งสูงข้างเคียง" และ flag เป็น STEP_DOWN_RISK ซ้ำซ้อนกับที่ TALL_UNSTABLE_RISK
    ตรวจพบไปแล้ว (ซึ่งเป็นการอธิบายปรากฏการณ์เดียวกันคนละมุม ไม่ใช่ปัญหาที่แยกจากกัน)
    วิธีแก้: ก่อนใช้ตั้งข้างเคียง (neighbor) เป็นฐานเปรียบเทียบว่า "สูงกว่า" ตรวจสอบ
    ก่อนว่าตั้งข้างเคียงนั้นเป็น isolated tall peak หรือไม่ (_is_isolated_tall_peak) -
    ถ้าใช่ ให้ข้ามเพื่อนบ้านนั้นไปเลย (ถือว่าเป็นกรณีของ TALL_UNSTABLE_RISK ไม่ใช่
    STEP_DOWN_RISK) ตั้งเตี้ยยังคงถูกตรวจพบได้ปกติหากมีเพื่อนบ้านอีกฝั่งที่สูงกว่าแบบ
    เป็นที่ราบ/หลายตั้งต่อเนื่องกันจริง (ไม่ใช่ตั้งโดดเดี่ยว)

    กรอบผลลัพธ์ (region) ใช้ขอบเขตของ "ตั้งที่เตี้ยกว่า" เท่านั้น (x0-x1 ของตั้งนั้น,
    y จาก top_y ถึง floor_y ของตั้งนั้นจริง) - ไม่ยืดไปคลุมตั้งข้างเคียงหรือพื้นตู้เต็ม
    ความสูงเหมือนวิธีเดิม ทำให้กรอบที่วาดออกมาแม่นยำและไม่ใหญ่เกินจริง
    """
    regions = []
    if not stacks or len(stacks) < 2:
        return regions
    sorted_stacks = sorted(stacks, key=lambda s: s["x0"])
    heights = [(_stack_total_height(s) if s.get("boxes") else None) for s in sorted_stacks]
    max_width_px = max(1, cargo_width_px) * max_width_ratio
    n = len(sorted_stacks)
    for i in range(n):
        h_this = heights[i]
        if h_this is None or h_this < min_height_px:
            continue
        s_this = sorted_stacks[i]
        if _stack_width(s_this) > max_width_px:
            # ตั้งนี้กว้างผิดปกติ (น่าจะเป็นการรวมกล่องหลายใบผิดพลาด) - ไม่นำมาพิจารณา
            # เป็น "ตั้งเตี้ย" เลย ไม่ว่าจะเทียบกับเพื่อนบ้านฝั่งใดก็ตาม
            continue
        neighbor_idxs = []
        if i > 0:
            neighbor_idxs.append(i - 1)
        if i < n - 1:
            neighbor_idxs.append(i + 1)
        best_ratio = 0.0
        for j in neighbor_idxs:
            h_neighbor = heights[j]
            if h_neighbor is None or h_neighbor < min_height_px:
                continue
            s_neighbor = sorted_stacks[j]
            if _stack_width(s_neighbor) > max_width_px:
                # เพื่อนบ้านกว้างผิดปกติเช่นกัน - ไม่น่าเชื่อถือพอจะใช้เทียบความสูง
                # (อาจเป็นค่าเฉลี่ยจากกล่องหลายใบที่ความสูงจริงต่างกัน) ข้ามคู่นี้ไป
                continue
            if h_neighbor <= h_this:
                continue  # เพื่อนบ้านไม่ได้สูงกว่า -> ตั้งนี้ไม่ใช่ตั้งเตี้ยเทียบตั้งนั้น
            # v24.15 NEW: ถ้าเพื่อนบ้านที่ "สูงกว่า" นี้เป็น isolated tall peak (สูงโดด
            # เด่นผิดปกติจากเพื่อนบ้านทั้ง 2 ฝั่งของมันเอง) แสดงว่านี่คือกรณีเดียวกับที่
            # TALL_UNSTABLE_RISK ตรวจพบไปแล้ว - ไม่ใช่ step-down/ที่ราบจริง ข้ามไป
            if _is_isolated_tall_peak(j, heights, min_height_px):
                continue
            ratio = 1 - (h_this / h_neighbor)
            best_ratio = max(best_ratio, ratio)
        if best_ratio >= min_ratio:
            regions.append({
                "x_min": s_this["x0"], "y_min": s_this["top_y"],
                "x_max": s_this["x1"], "y_max": s_this["floor_y"],
                "ratio": best_ratio,
                "source": "FORCED_DETERMINISTIC_STACK_HEIGHT_STEP_DOWN",
            })
    return regions


def detect_step_down_regions_from_stack_model_per_view(stack_box_model, cargo_extent):
    """เรียก detect_step_down_regions_from_stacks() สำหรับทั้ง FRONT และ BACK view -
    stacks ใน stack_box_model เก็บพิกัดแบบ "สัมบูรณ์บนภาพเต็ม" อยู่แล้ว จึงไม่ต้องแปลง
    พิกัดเพิ่มเติม

    v24.14 NEW: หาก view ใด view หนึ่งไม่มี high-confidence stacks (coverage ต่ำกว่า
    เกณฑ์ปกติ, stack_box_model[view] ว่างเปล่า) จะ fallback ไปใช้ "raw stacks"
    (f"{view}_raw_stacks", เก็บไว้เสมอโดย build_stack_box_model_per_view) แทน พร้อม
    เกณฑ์ความสูงที่เข้มงวดขึ้น (STEP_DOWN_STACK_MIN_RATIO_FALLBACK) เพื่อชดเชยความไม่
    แน่นอนของข้อมูลคุณภาพต่ำ - ยังคงผ่าน STACK-WIDTH SANITY GATE เหมือนกันทุกประการ
    (ดู CHANGELOG v24.14 - แก้ปัญหาที่ผู้ใช้ระบุ: "ภาพ back ไม่พบตั้งเตี้ยเหมือน front")
    """
    results = {"FRONT": [], "BACK": []}
    for view in ("FRONT", "BACK"):
        ce = cargo_extent.get(view)
        cargo_width_px = (ce["xmax"] - ce["xmin"]) if ce else 1

        stacks = stack_box_model.get(view, [])
        using_fallback = False
        if not stacks:
            raw_stacks = stack_box_model.get(f"{view}_raw_stacks", [])
            if raw_stacks:
                stacks = raw_stacks
                using_fallback = True

        min_ratio = STEP_DOWN_STACK_MIN_RATIO_FALLBACK if using_fallback else STEP_DOWN_STACK_MIN_RATIO
        regions = detect_step_down_regions_from_stacks(stacks, cargo_width_px, min_ratio=min_ratio)
        results[view] = regions
        for r in regions:
            print(f"Deterministic STEP_DOWN_RISK candidate ({view}, fallback_stacks={using_fallback}) "
                  f"[STACK-HEIGHT COMPARISON]: x=[{r['x_min']:.0f}-{r['x_max']:.0f}] "
                  f"y=[{r['y_min']:.0f}-{r['y_max']:.0f}] height_diff_ratio={r['ratio']*100:.1f}% "
                  f"(threshold={min_ratio*100:.0f}%)")
        if not regions:
            print(f"Deterministic STEP_DOWN_RISK: no adjacent-stack height difference found for {view} "
                  f"(fallback_stacks={using_fallback}) (container appears uniform based on per-box stack comparison)")
    return results


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


# v24.12 NEW: จำกัดขนาดกรอบความเสี่ยงทุกประเภทให้ "ใกล้เคียงขนาดจริงของกล่อง/บริเวณ
# ที่วิเคราะห์ว่ามีความเสี่ยง" (ไม่ใช่ขยายเกินจำเป็นแบบที่เคยเกิดกับ STEP_DOWN_RISK ที่
# เคยยืดกรอบไปจนสุดพื้นตู้เต็มความสูง) ตามคำขอผู้ใช้ - ขยายออกเล็กน้อยเท่านั้น
# ("เลยมาได้นิดหน่อย") เพื่อไม่ให้กรอบแนบชิดขอบกล่องจนบังรายละเอียดขอบภาพ
REGION_BOX_PAD_PX = 6


def _region_to_padded_normalized_box(x_min, y_min, x_max, y_max, crop_w, crop_h, crop_y_start,
                                       view_label, layout, pad_px=REGION_BOX_PAD_PX):
    """
    v24.12 NEW: แปลง region พิกัดสัมบูรณ์ (x_min,y_min,x_max,y_max) เป็น box_2d
    normalized (0-1000) พร้อม 'ขยายออกเล็กน้อย' (pad_px) จากขอบเขตที่วัดได้จริง - ใช้
    แทนที่การแปลงพิกัดแบบ inline ที่เคยกระจายอยู่หลายจุดใน process_request() เพื่อให้
    ทุกประเภทความเสี่ยง (STEP_DOWN, OVERHANG, TALL_UNSTABLE, LATERAL_GAP ฯลฯ) ใช้
    หลักการเดียวกัน: กรอบต้อง "จำกัดแค่ความสูง/ความกว้างของบริเวณที่วิเคราะห์จริง"
    ไม่ขยายเกินความจำเป็น (ดู CHANGELOG - แก้ไข STEP_DOWN_RISK ที่เคยยืดกรอบไปจนสุด
    พื้นตู้เต็มความสูงด้วย) โดยยอมให้ขยายออกเล็กน้อยเพื่อความสวยงาม/มองเห็นขอบชัดเจน

    จะจำกัด (clip) ไม่ให้กรอบที่ขยายแล้วล้ำเข้าไปในครึ่งภาพของอีก view (FRONT/BACK)
    หรือล้ำออกนอกขอบเขตภาพทั้งหมด
    """
    x_min = x_min - pad_px
    x_max = x_max + pad_px
    y_min = y_min - pad_px
    y_max = y_max + pad_px

    if layout == "TOP_BOTTOM":
        mid_y = crop_y_start + crop_h // 2
        if view_label == "FRONT":
            y_min = max(crop_y_start, y_min)
            y_max = min(mid_y, y_max)
        else:
            y_min = max(mid_y, y_min)
            y_max = min(crop_y_start + crop_h, y_max)
        x_min = max(0, x_min)
        x_max = min(crop_w, x_max)
    else:
        mid_x = crop_w // 2
        if view_label == "FRONT":
            x_min = max(0, x_min)
            x_max = min(mid_x, x_max)
        else:
            x_min = max(mid_x, x_min)
            x_max = min(crop_w, x_max)
        y_min = max(crop_y_start, y_min)
        y_max = min(crop_y_start + crop_h, y_max)

    ymin_norm = ((y_min - crop_y_start) / crop_h) * 1000
    ymax_norm = ((y_max - crop_y_start) / crop_h) * 1000
    xmin_norm = (x_min / crop_w) * 1000
    xmax_norm = (x_max / crop_w) * 1000
    return [ymin_norm, xmin_norm, ymax_norm, xmax_norm]


def _claim_overlaps_regions(box_2d, crop_w, crop_h, crop_y_start, regions_for_view, overlap_threshold=0.10):
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


def _stack_total_height(s):
    if not s.get("boxes"):
        return None
    h = s["floor_y"] - s["top_y"]
    return h if h > 0 else None



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
{{"rear_zone_risk":"REAR_EMPTY_RISK"|"REAR_LATERAL_IMBALANCE"|"BOTH"|"SAFE","reasoning":"describe what you see, including approximate height difference if any, and specifically note if any stack appears partially hidden/overlapped by a taller neighbor, and confirm you counted any dark-colored boxes as cargo","confidence":"HIGH"|"MEDIUM","box_2d":[ymin,xmin,ymax,xmax]}}
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
{{"front_zone_risk":"FRONT_EMPTY_RISK"|"SAFE","reasoning":"describe the gap size you see, or why it's safe","confidence":"HIGH"|"MEDIUM","box_2d":[ymin,xmin,ymax,xmax]}}
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
        # v24.13 FIX: เดิมใช้ min/max ระหว่างขอบเขตตู้ (container) กับขอบเขตคาร์โก้
        # (cargo) รวมกัน ทำให้กรอบยืดเต็มความสูงของภาพเสมอ (ตามที่ผู้ใช้ระบุ "กรอบ
        # เหลืองใหญ่เกิน") - เปลี่ยนไปใช้เฉพาะขอบเขตความสูงของคาร์โก้จริง (view_cargo)
        # เท่านั้น + padding เล็กน้อย ทำให้กรอบจำกัดเฉพาะบริเวณที่คาร์โก้ปรากฏจริง
        y0 = view_cargo["ymin"]
        y1 = view_cargo["ymax"]
        y_pad = max(4, (y1 - y0) * 0.06)
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


# ---------------------------------------------------------------------------
# v24.11 ROLLBACK: กลับไปใช้ "สี่เหลี่ยมผืนผ้าตรง" (axis-aligned rectangle) แบบ v24.8
# ตามคำขอผู้ใช้ - ตัดฟีเจอร์ quad-corner/parallelogram (v24.9) และ halo effect (v24.10)
# ออกทั้งหมด เนื่องจากผู้ใช้ทดสอบแล้วเห็นว่ารูปทรงสี่เหลี่ยมธรรมดาดูดีกว่า/อ่านง่ายกว่า
# ---------------------------------------------------------------------------

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


def _get_deterministic_gap_x_range(view_container, view_cargo, rear_side, risk_type):
    """v24.14 NEW: คำนวณช่วง x ของ "ช่องว่างจริง" (ระหว่างขอบเขตคาร์โก้กับขอบเขตตู้)
    แบบ deterministic เดียวกับที่ _get_fallback_box ใช้ - แยกออกมาเป็นฟังก์ชันกลาง
    เพื่อนำไปใช้ "ตัดขอบเขต" กรอบที่ได้จาก AI zoom analysis ด้วย (ดู
    _tighten_zoom_box_to_gap) ป้องกันไม่ให้กรอบ REAR_EMPTY_RISK/FRONT_EMPTY_RISK
    กว้าง/สูงเกินกว่าช่องว่างจริงที่วัดได้ (ตามคำขอผู้ใช้: "กรอบควรสั้นเหมือนกรอบสีเหลือง
    ด้านหน้ารถ")"""
    if not view_container or not view_cargo:
        return None
    c_xmin, c_xmax = view_container["xmin"], view_container["xmax"]
    g_xmin, g_xmax = view_cargo["xmin"], view_cargo["xmax"]
    if risk_type == "FRONT_EMPTY_RISK":
        if rear_side == "LEFT":
            return (g_xmax, c_xmax)
        else:
            return (c_xmin, g_xmin)
    else:  # REAR_EMPTY_RISK / REAR_COMBINED_RISK
        if rear_side == "LEFT":
            return (c_xmin, g_xmin)
        else:
            return (g_xmax, c_xmax)


def _tighten_zoom_box_to_gap(abs_box, view_container, view_cargo, rear_side, risk_type, pad_ratio=0.25):
    """
    v24.14 NEW: ตัด (intersect) กรอบที่ได้จาก AI zoom analysis (analyze_rear_zone_with_ai/
    analyze_front_zone_with_ai) ให้ไม่เกินขอบเขตช่องว่างที่วัดได้จริงแบบ deterministic
    (จาก _get_deterministic_gap_x_range) - ROOT CAUSE: Gemini เลือกกรอบเองจากภาพซูม
    โดยไม่ได้ผ่านการตรวจสอบพิกเซลแบบ deterministic เหมือน LATERAL_GAP_RISK (v24.13)
    ทำให้บางครั้งกรอบกว้างเกินกว่าช่องว่างจริงมาก (ผู้ใช้ระบุ: "กรอบควรสั้นเหมือนกรอบ
    สีเหลืองด้านหน้ารถอื่นๆ")

    เพิ่ม padding เล็กน้อย (pad_ratio ของความกว้างช่องว่างจริง) รอบขอบเขตที่วัดได้ เพื่อ
    ไม่ให้กรอบแนบชิดขอบจนบังรายละเอียดภาพ - หากตัดแล้วไม่เหลือพื้นที่เลย (กรอบ AI ไม่
    ทับซ้อนกับช่องว่างจริงเลย) จะคืนค่ากรอบเดิมของ AI แทน (ปลอดภัย ไม่ทำให้กรอบหายไป)
    """
    if not abs_box:
        return abs_box
    gap_range = _get_deterministic_gap_x_range(view_container, view_cargo, rear_side, risk_type)
    if not gap_range:
        return abs_box
    gap_x0, gap_x1 = gap_range
    if gap_x1 <= gap_x0:
        return abs_box
    pad = max(10, (gap_x1 - gap_x0) * pad_ratio)
    allowed_x0, allowed_x1 = gap_x0 - pad, gap_x1 + pad

    x0, y0, x1, y1 = abs_box
    new_x0 = max(x0, allowed_x0)
    new_x1 = min(x1, allowed_x1)
    if new_x1 - new_x0 < 10:
        print(f"WARNING: Zoom box for {risk_type} does not overlap deterministic gap range "
              f"x=[{allowed_x0:.0f}-{allowed_x1:.0f}] - keeping original AI box x=[{x0:.0f}-{x1:.0f}] unchanged")
        return abs_box
    if (new_x0, new_x1) != (x0, x1):
        print(f"Tightened {risk_type} zoom box to deterministic gap range: "
              f"x=[{x0:.0f}-{x1:.0f}] -> x=[{new_x0:.0f}-{new_x1:.0f}]")
    return (new_x0, y0, new_x1, y1)


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

        stack_box_model = build_stack_box_model_per_view(diagram_crop, layout, crop_w, crop_h, crop_y_start,
                                                          container_bounds, cargo_extent)

        # v24.13/v24.14: STEP_DOWN_RISK ใช้ "การเปรียบเทียบความสูงรวมของตั้งกล่องที่
        # ติดกัน" (per-box stack model เดียวกับ OVERHANG_RISK/TALL_UNSTABLE_RISK/
        # REAR_LATERAL_IMBALANCE) เป็นแหล่งข้อมูลเดียวเท่านั้น ตามคำขอผู้ใช้ตรงตัว:
        # "ค้นหาแค่ตั้งของกล่องที่ต่ำกว่า ตั้งของกล่องด้านข้าง" - แทนที่วิธีเดิมทั้งหมด
        # (height-profile pixel scan, floor-hole scan, cross-view mirror/veto + OCR-SKU
        # matching) ซึ่งอ่านค่าจาก pixel โดยตรงและไวต่อสัญญาณรบกวนจนสร้างจุดเสี่ยงเท็จ
        # จำนวนมาก v24.14 เพิ่ม STACK-WIDTH SANITY GATE + RAW-STACK FALLBACK (ดู
        # CHANGELOG หัวไฟล์สำหรับรายละเอียด root cause ครบถ้วน)
        step_down_regions = detect_step_down_regions_from_stack_model_per_view(stack_box_model, cargo_extent)

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

        local_depth_gap_regions = detect_local_depth_gap_per_view(diagram_crop, layout, crop_w, crop_h,
                                                                     crop_y_start, container_bounds, cargo_extent)

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
                # v24.13/v24.14: gate เดียวกับ OVERHANG_RISK/TALL_UNSTABLE_RISK ด้านล่าง
                # - ต้อง overlap กับ deterministic region ที่มาจาก per-box stack-height
                # comparison เท่านั้น (ผ่าน STACK-WIDTH SANITY GATE แล้ว) ไม่มี
                # cross-view veto/mirror อีกต่อไป เพราะแหล่งข้อมูลนี้เชื่อถือได้ในตัวเอง
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
                if region["ratio"] < OVERHANG_MIN_RATIO:
                    continue
                if _view_already_has_overlapping_claim(view_label, "OVERHANG_RISK", region, all_risks):
                    continue
                box_2d = _region_to_padded_normalized_box(region["x_min"], region["y_min"], region["x_max"], region["y_max"],
                                                            crop_w, crop_h, crop_y_start, view_label, layout)
                print(f"FORCED OVERHANG_RISK ({view_label}) from deterministic per-box segmentation "
                      f"(overhang_ratio={region['ratio']*100:.0f}%)")
                all_risks.append({
                    "view": view_label, "risk_type": "OVERHANG_RISK",
                    "box_2d": box_2d,
                    "reasoning": "FORCED_DETERMINISTIC_PER_BOX_OVERHANG",
                    "description": f"พบสินค้าชั้นบนยื่นพ้นขอบสินค้าชั้นล่างประมาณ {region['ratio']*100:.0f}% ของความกว้างกล่องล่าง (ตรวจจับจาก per-box segmentation)",
                })
            for region in tall_unstable_regions.get(view_label, []):
                if region["ratio"] < TALL_UNSTABLE_MIN_HEIGHT_RATIO:
                    continue
                if _view_already_has_overlapping_claim(view_label, "TALL_UNSTABLE_RISK", region, all_risks):
                    continue
                box_2d = _region_to_padded_normalized_box(region["x_min"], region["y_min"], region["x_max"], region["y_max"],
                                                            crop_w, crop_h, crop_y_start, view_label, layout)
                print(f"FORCED TALL_UNSTABLE_RISK ({view_label}) from deterministic per-box segmentation "
                      f"(height_diff_ratio={region['ratio']*100:.0f}%)")
                all_risks.append({
                    "view": view_label, "risk_type": "TALL_UNSTABLE_RISK",
                    "box_2d": box_2d,
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
                        # v24.14 NEW: ตัดกรอบ AI zoom ให้ไม่เกินช่องว่างที่วัดได้จริงแบบ
                        # deterministic (ตามคำขอผู้ใช้: "กรอบควรสั้นเหมือนกรอบสีเหลือง
                        # ด้านหน้ารถ") - ไม่ใช้กับ REAR_LATERAL_IMBALANCE เพราะเป็นโซน
                        # เปรียบเทียบความสูงจริง ไม่ใช่แค่ช่องว่างเปล่าๆ
                        pb_tight = _tighten_zoom_box_to_gap(
                            pb, container_bounds.get(view_label), cargo_extent.get(view_label),
                            HARDCODED_REAR_SIDE[view_label], "REAR_EMPTY_RISK")
                        precise_boxes[(view_label, "REAR_EMPTY_RISK")] = pb_tight
                    if rear_zone_risk_val in ("REAR_LATERAL_IMBALANCE", "BOTH"):
                        precise_boxes[(view_label, "REAR_LATERAL_IMBALANCE")] = pb

        if isinstance(front_result_from_front_view, dict) and str(front_result_from_front_view.get("front_zone_risk", "")).upper() == "FRONT_EMPTY_RISK":
            pb = _get_zoom_precise_box(front_result_from_front_view, "box_2d", zoom_crop_rects["front_FRONT"], img)
            if pb:
                pb_tight = _tighten_zoom_box_to_gap(
                    pb, container_bounds.get("FRONT"), cargo_extent.get("FRONT"),
                    HARDCODED_REAR_SIDE["FRONT"], "FRONT_EMPTY_RISK")
                precise_boxes[("FRONT", "FRONT_EMPTY_RISK")] = pb_tight

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
                if _should_veto_lateral_imbalance(view_label):
                    print(f"REAR_LATERAL_IMBALANCE claim ({view_label}) VETOED - deterministic per-box segmentation "
                          f"shows no genuine height difference in rear zone (AI reasoning: {rear_result.get('reasoning','')[:150]})")
                else:
                    all_risks.append({"view": view_label, "risk_type": "REAR_LATERAL_IMBALANCE", "direction": "LATERAL", "lateral_side": "N/A", "reasoning": rear_result.get("reasoning", ""), "description": "พบสินค้าท้ายตู้สูงต่ำไม่เท่ากัน (วิเคราะห์จาก Zoom ท้ายตู้)", "box_2d": None})
                    print(f"REAR_LATERAL_IMBALANCE ({view_label}) accepted with confidence={confidence}")

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

            precise_abs_box = get_precise_lateral_gap_box(container_bounds.get(view_label), cargo_extent.get(view_label),
                                                            full_img=img)
            precise_lateral_box_2d = None
            if precise_abs_box:
                px0, py0, px1, py1 = precise_abs_box
                precise_lateral_box_2d = _region_to_padded_normalized_box(px0, py0, px1, py1,
                                                                            crop_w, crop_h, crop_y_start, view_label, layout)

            if should_flag_lateral and view_label not in _existing_risk_views("LATERAL_GAP"):
                print(f"FORCED LATERAL_GAP_RISK ({view_label}) from deterministic side-floor gap measurement")
                all_risks.append({"view": view_label, "risk_type": "LATERAL_GAP_RISK", "direction": "LATERAL", "lateral_side": "N/A", "reasoning": "FORCED_DETERMINISTIC_LATERAL_GAP", "description": f"พบพื้นที่ว่างด้านข้างบนพื้นตู้ประมาณ {gap_display} (เกินเกณฑ์ความปลอดภัย)", "box_2d": precise_lateral_box_2d})
            elif (unused_floor_mm is not None and unused_floor_mm >= UNUSED_FLOOR_MIN_MM
                  and view_label not in _existing_risk_views("LATERAL_GAP")
                  and lateral_gap_ratio is not None and lateral_gap_ratio >= UNUSED_FLOOR_RELAXED_GAP_RATIO):
                print(f"FORCED LATERAL_GAP_RISK ({view_label}) corroborated by printed 'Unused Floor: "
                      f"{unused_floor_mm/25.4:.1f}in' + pixel ratio {lateral_gap_ratio*100:.1f}% "
                      f"(relaxed threshold {UNUSED_FLOOR_RELAXED_GAP_RATIO*100:.0f}%)")
                all_risks.append({"view": view_label, "risk_type": "LATERAL_GAP_RISK", "direction": "LATERAL", "lateral_side": "N/A",
                                   "reasoning": "FORCED_BY_PRINTED_UNUSED_FLOOR",
                                   "description": f"พบพื้นที่ว่างด้านข้างบนพื้นตู้ประมาณ {lateral_gap_ratio*100:.0f}% (ยืนยันจากค่า Unused Floor: {unused_floor_mm/25.4:.1f} นิ้ว ที่พิมพ์บนเอกสาร)",
                                   "box_2d": precise_lateral_box_2d})
            elif (local_depth_gap_regions.get(view_label) and view_label not in _existing_risk_views("LATERAL_GAP")):
                best_region = max(local_depth_gap_regions[view_label], key=lambda r: r["max_gap_px"])
                box_2d = _region_to_padded_normalized_box(best_region["x_min"], best_region["y_min"],
                                                            best_region["x_max"], best_region["y_max"],
                                                            crop_w, crop_h, crop_y_start, view_label, layout)
                print(f"FORCED LATERAL_GAP_RISK ({view_label}) from LOCAL DEPTH-GAP SCAN "
                      f"(x=[{best_region['x_min']:.0f}-{best_region['x_max']:.0f}], "
                      f"max_local_gap={best_region['max_gap_px']:.0f}px, width={best_region['width_px']:.0f}px)")
                all_risks.append({"view": view_label, "risk_type": "LATERAL_GAP_RISK", "direction": "LATERAL", "lateral_side": "N/A",
                                   "reasoning": "FORCED_BY_LOCAL_DEPTH_GAP_SCAN",
                                   "description": f"พบหลุมเฉพาะจุดบนพื้นตู้ (ตำแหน่งเดียว ไม่ใช่ทั้งโหลด) ลึกประมาณ {best_region['max_gap_px']:.0f}px กว้าง {best_region['width_px']:.0f}px (ตรวจจับจาก local depth-gap scan)",
                                   "box_2d": box_2d})

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
                # v24.13/v24.14: threshold ใช้ STEP_DOWN_STACK_MIN_RATIO (per-box
                # stack-height comparison) - region ที่มาถึงจุดนี้ผ่านเกณฑ์นี้อยู่แล้ว
                # จาก detect_step_down_regions_from_stacks() แต่เก็บเช็คซ้ำไว้เป็น
                # safety net (ใช้เกณฑ์ต่ำสุดระหว่าง 2 ค่า เผื่อมาจาก raw-stack fallback)
                if region["ratio"] < min(STEP_DOWN_STACK_MIN_RATIO, STEP_DOWN_STACK_MIN_RATIO_FALLBACK):
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
                box_2d = _region_to_padded_normalized_box(region["x_min"], region["y_min"], region["x_max"], region["y_max"],
                                                            crop_w, crop_h, crop_y_start, view_label, layout)
                source_tag = region.get("source", "FORCED_DETERMINISTIC_HEIGHT_PROFILE_STEP")
                print(f"FORCED STEP_DOWN_RISK ({view_label}) from {source_tag} "
                      f"(height_diff_ratio={region['ratio']*100:.1f}%)")
                all_risks.append({
                    "view": view_label, "risk_type": "STEP_DOWN_RISK",
                    "box_2d": box_2d,
                    "reasoning": source_tag,
                    "description": f"พบความต่างระดับระหว่างกองสินค้าประมาณ {region['ratio']*100:.0f}% ของความสูงตู้ (ตรวจจับจาก height-profile analysis / cross-view verification)",
                })

        all_risks = _merge_same_area_risks(all_risks)

        draw = PIL.ImageDraw.Draw(img)
        detected_hazards = []
        reported_risk_keys = set()
        # v24.12 NEW: risk_groups ใช้จัดกลุ่มคำอธิบายข้อความตาม "ประเภทความเสี่ยง"
        # เท่านั้น (ไม่รวมตำแหน่ง/view) เพื่อแสดงคำอธิบายเพียงครั้งเดียวแม้จะพบความ
        # เสี่ยงประเภทเดียวกันหลายจุด (แยกจาก reported_risk_keys ที่ใช้นับจำนวนจุดจริง)
        risk_groups = {}
        group_order = []

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

            # v24.8: instance-level key (position-aware) - ป้องกันการนับจุดเดียวกัน
            # ซ้ำ (เช่น ถ้า merge-dedup พลาดไปบ้าง) ใช้สำหรับ "นับจำนวนจุดเสี่ยงจริง"
            # (hazardCount) เท่านั้น - ไม่เกี่ยวกับการจัดกลุ่มข้อความ (ดู v24.12 ด้านล่าง)
            if risk_type == "COMBINED_AREA_RISK":
                instance_key = "+".join(risk.get("merged_risk_types", [risk_type]))
                if box and isinstance(box, list) and len(box) == 4:
                    try:
                        _y0, _x0, _y1, _x1 = map(float, box)
                        instance_key += f"_{round(_x0/50)}_{round(_y0/50)}"
                    except Exception:
                        pass
            elif risk_type in BOX_BASED_RISK_TYPES:
                pos_tag = ""
                if box and isinstance(box, list) and len(box) == 4:
                    try:
                        _y0, _x0, _y1, _x1 = map(float, box)
                        pos_tag = f"_{round(_x0/50)}_{round(_y0/50)}"
                    except Exception:
                        pos_tag = ""
                instance_key = f"{risk_type}_{resolved_view}{pos_tag}"
            else:
                instance_key = f"{risk_type}_{resolved_view}"

            if instance_key in reported_risk_keys:
                continue  # จุดเดียวกันซ้ำ (duplicate instance) - ข้ามไปเลย ไม่นับซ้ำ
            reported_risk_keys.add(instance_key)

            # v24.12 NEW: GROUP KEY (ไม่รวมตำแหน่ง/view) - ใช้จัดกลุ่มสำหรับคำอธิบาย
            # ข้อความเท่านั้น ตามคำขอผู้ใช้: "ระบุรายงานอธิบายความเสี่ยง แค่อันเดียว
            # แม้ว่าจะมากกว่า 1 เคส เช่น พบ STEP_DOWN_RISK จำนวน 2 เคส ระบุตัวเลข 2
            # แต่คำอธิบายด้านล่างมีแค่ 1 อันพอ ไม่ต้องเขียนซ้ำตามจำนวนเคสที่เหมือนกัน"
            # - แยก "การนับจำนวนจุดเสี่ยง" (instance_key ด้านบน, ใช้กับ hazardCount)
            # ออกจาก "การแสดงคำอธิบาย" (group_key นี้, ใช้กับ action_text) โดยเจตนา
            if risk_type == "COMBINED_AREA_RISK":
                merged_names_for_group = risk.get("merged_risk_types", [])
                group_key = "COMBINED:" + "+".join(sorted(merged_names_for_group))
            elif risk_type == "REAR_COMBINED_RISK":
                group_key = "REAR_COMBINED_RISK"
            else:
                group_key = risk_type

            if group_key not in risk_groups:
                if risk_type == "COMBINED_AREA_RISK":
                    merged_names = risk.get("merged_risk_types", [])
                    title_base = "ความเสี่ยงร่วม: " + " + ".join(merged_names)
                    parts = [generate_action_report(rt, "", sku_str) for rt in merged_names]
                    detail = "\n\n".join(parts) if parts else (risk.get("description", "") or "พบหลายความเสี่ยงในบริเวณเดียวกัน")
                elif risk_type == "REAR_COMBINED_RISK":
                    title_base = "ความเสี่ยง: REAR_EMPTY_RISK + REAR_LATERAL_IMBALANCE (บริเวณประตูท้ายตู้เดียวกัน)"
                    detail = generate_action_report(risk_type, risk.get("description", ""), sku_str)
                else:
                    title_base = f"ความเสี่ยง: {risk_type}"
                    detail = generate_action_report(risk_type, risk.get("description", ""), sku_str)
                risk_groups[group_key] = {"title_base": title_base, "detail": detail, "count": 0}
                group_order.append(group_key)
            else:
                print(f"Grouped duplicate description for '{group_key}' (instance #{risk_groups[group_key]['count']+1}) "
                      f"- description text shown only once, count will be incremented")
            risk_groups[group_key]["count"] += 1

        for group_key in group_order:
            info = risk_groups[group_key]
            title = f"{info['title_base']} (พบ {info['count']} จุด)" if info["count"] > 1 else info["title_base"]
            detected_hazards.append({"title": title, "detail": info["detail"], "is_error": False})

        total_instance_count = sum(g["count"] for g in risk_groups.values())
        real_hazards = [h for h in detected_hazards if not h.get("is_error")]
        error_hazards = [h for h in detected_hazards if h.get("is_error")]
        sep = "\n\n" + "-" * 50 + "\n\n"
        if real_hazards:
            status_text = f"พบจุดเสี่ยงอันตราย ({total_instance_count} จุด)"
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
        return ({"status": status_text, "hazardCount": total_instance_count, "layout": layout, "actionRequired": action_text, "processedImageUrl": processed_image_url}, 200, headers)
    except Exception as e:
        err_trace = traceback.format_exc()
        print("CRITICAL ERROR DETAILS:\n", err_trace)
        gc.collect()
        return ({"error": str(e), "trace": err_trace[-500:]}, 500, headers)
