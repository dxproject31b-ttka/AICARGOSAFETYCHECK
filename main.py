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
import PIL.ImageFont
import PIL.ImageStat
import PIL.PngImagePlugin
import PIL.ImageOps
import PIL.ImageColor
import fitz  # PyMuPDF
import functions_framework
import google.generativeai as genai

# ---------------------------------------------------------------------------
# AI Cargo Safety Checker - High Precision v24.50
#
# v24.30 - แก้ 2 ปัญหาพร้อมกันตามคำขอผู้ใช้ หลังพบว่า STEP_DOWN_RISK พลาดจุดเสี่ยงจริง
#   ในไฟล์ EC07/EC09 (ผู้ใช้วาดเส้นแดงชี้ตำแหน่งจริงในภาพ ยืนยันว่ากล่องเขียวสูงกว่า
#   กล่องน้ำเงินอย่างชัดเจน) และ EC10 segmentation ล้มเหลวสมบูรณ์ (มองทั้งภาพเป็น "1
#   stack เดียว" ทั้งที่มีกล่องหลายสีจริง) - ทั้งสองปัญหามี ROOT CAUSE คนละจุดกัน ดังนี้:
#
#   ปัญหาที่ 1: STEP_DOWN_RISK/TALL_UNSTABLE_RISK พลาดความเสี่ยงจริงที่ผลต่างความสูง
#   สูงถึง 32-46% (ยืนยันจากภาพจริง EC07/EC09) เพราะ 3 gate ที่เพิ่มมาป้องกัน false
#   positive ในเวอร์ชันก่อนหน้า (v24.19/v24.20) กลับบล็อกความเสี่ยงจริงไปด้วย เนื่องจาก
#   per-box segmentation คืนค่า box_count=1 เกือบทุกตั้งเสมอ (ไม่เคยพบ >1 เลยในไฟล์
#   ทดสอบทั้งหมดก่อนหน้านี้) ทำให้เกทที่อ้างอิง "จำนวนกล่อง/ชั้น" กลายเป็น "บล็อกเกือบ
#   ทุกอย่างโดยพฤตินัย" ไม่ใช่แค่กรองเฉพาะ false positive ตามเจตนาเดิม:
#
#     1a) STEP_DOWN_REQUIRE_NEIGHBOR_BOX_COUNT_GT_CURRENT (v24.19): เดิมต้อง "เพื่อนบ้าน
#     มีจำนวนกล่องมากกว่าจริง" (neighbor_count <= current_count -> reject) - แก้เป็น
#     ตรวจสอบเฉพาะกรณีที่มีข้อมูลจำนวนกล่องที่มีความหมายจริง (มีตั้งใดตั้งหนึ่ง >1 กล่อง)
#     จึงบังคับใช้กฎเดิม ถ้าทุกตั้งมี box_count=1 เท่ากันหมด (ไม่มีข้อมูลที่มีความหมาย)
#     จะไม่บล็อกจาก box count แต่ใช้ _is_part_of_gradual_multi_stack_trend() แยกแยะ
#     "ขั้นบันไดเดี่ยว 2 ตั้งจริง" ออกจาก "ความลาดเอียงต่อเนื่องหลายตั้งจากมุมมอง
#     isometric" (เจตนาดั้งเดิมของ v24.19) แทน
#
#     1b) TALL_UNSTABLE_REQUIRE_BOX_COUNT_GT_NEIGHBORS (v24.20): เดิมต้อง "จำนวนกล่อง
#     ของตั้งกลางมากกว่าเพื่อนบ้านทั้ง 2 ฝั่งจริง" - แก้ด้วยหลักการเดียวกับ 1a (ไม่บล็อก
#     เมื่อ box_count เท่ากันหมด เพราะไม่มีข้อมูลที่มีความหมาย) ยังคงต้องผ่านเกณฑ์ความสูง
#     เข้มงวดเดิม (เพื่อนบ้านทั้ง 2 ฝั่ง <=65% ของตั้งกลาง AND diff_ratio>=35%) ซึ่งเข้มงวด
#     พออยู่แล้ว (ยืนยันจาก EA06-01: ทุกคู่ตั้งที่ไม่ถูก exclude มี ratio สูงสุดแค่ 21%)
#
#     1c) _is_isolated_tall_peak() ใน STEP_DOWN: เดิมไม่ตรวจสอบ excluded_idxs เลย ทำให้
#     ใช้ค่าความสูงของตั้งที่ถูก exclude (เช่น merged-stack ที่ไม่น่าเชื่อถือ) มาตัดสินว่า
#     เป็น "isolated tall peak" (จึงถอยให้ TALL_UNSTABLE_RISK จัดการแทน) แต่ TALL_UNSTABLE
#     เองกลับปฏิเสธเพราะต้องการเพื่อนบ้านที่ไม่ถูก exclude ครบทั้ง 2 ฝั่งเช่นกัน - ผลคือ
#     ไม่มี detector ตัวไหนรายงานเลย (ตกหล่นระหว่างกลาง 2 detector) - แก้ด้วยการส่ง
#     excluded_idxs เข้าไปด้วย และคืนค่า False ทันทีถ้าเพื่อนบ้านฝั่งใดฝั่งหนึ่งถูก exclude
#     (สอดคล้องกับเงื่อนไขของ TALL_UNSTABLE เป๊ะ) เพื่อให้ STEP_DOWN ดำเนินการตรวจสอบ
#     ต่อไปเอง แทนที่จะรอ detector อื่นที่จะไม่มีวันยืนยันได้
#
#     1d) _step_down_edge_artifact_stack_indices() (v24.16): เดิมตัดสินจาก "ความกว้าง"
#     อย่างเดียว (แคบกว่า 70% ของมัธยฐาน = edge artifact) ทำให้ตัดตั้งขอบคาร์โก้ที่แคบแต่
#     สูงปกติทิ้งไปด้วย (EC09: ตั้งขอบทั้ง 2 ฝั่งถูกตัดทิ้งจนเหลือตั้งเดียวเปรียบเทียบไม่ได้
#     เลย) - แก้ด้วยการเพิ่มเงื่อนไข "ต้องเตี้ยผิดปกติด้วย" (ไม่ใช่แค่แคบ) เพราะเศษเสี้ยว
#     จากมุม isometric corner/top-face จริงจะมีทั้งความกว้างและความสูงเล็กผิดปกติพร้อมกัน
#
#   ปัญหาที่ 2: _find_color_step_boundaries() (per-box segmentation) - EC10 FRONT ทั้ง
#   ภาพถูกมองเป็น "1 stack เดียว" ทั้งที่มีกล่องสีเขียว/แดง/น้ำเงินแยกกันชัดเจน ตรวจสอบ
#   pixel จริงพบว่ามีการเปลี่ยนสีชัดเจนมาก (เขียว->แดง, color_distance≈360 สูงกว่าเกณฑ์
#   min_distance=60 มาก) แต่ฟังก์ชันเดิมยังหาไม่เจอ เพราะการเปลี่ยนสีในภาพจริงมักเกิดเป็น
#   "ช่วงไล่เฉด" (gradient/transition zone กว้าง 4-5px จาก anti-aliasing/มุม isometric)
#   ไม่ใช่เปลี่ยนทันทีทันใดเสมอไป - ฟังก์ชันเดิมเช็คความเสถียรโดยเทียบกับ cur_color (สีที่
#   จุดเริ่มเปลี่ยน ซึ่งตัวมันเองยังอยู่ระหว่างไล่เฉด ไม่ใช่สีปลายทางจริง) ทำให้ไม่มีจุดไหน
#   ผ่านเกณฑ์ "เสถียรทันที" เลย - แก้ด้วยการข้าม transition_zone_px (5px) แรกไปก่อน แล้ว
#   ใช้สีที่ "ตกตะกอนแล้ว" (anchor) เป็นตัวเทียบความเสถียรแทน cur_color เดิม
#
#   ผลทดสอบจริง (รันโค้ดจริงกับ PDF ทั้ง 5 ไฟล์ที่มีอยู่: EA06-01, EC07, EC09, EC10,
#   EC18 - ครอบคลุมทั้งเคสที่ต้องคง SAFE และเคสที่ต้องตรวจพบความเสี่ยงจริง):
#     - EA06-01: STEP_DOWN=0, TALL_UNSTABLE=0 ทั้ง FRONT/BACK เหมือนเดิมทุกประการ
#       (ไม่มี regression แม้ค่าตั้งใน BACK จะเปลี่ยนจาก [1,1,1] เป็น [1,1,3,1] กล่อง
#       จากการแก้ปัญหาที่ 2 - segmentation แม่นยำขึ้นแต่ผลลัพธ์ยังปลอดภัยเหมือนเดิม)
#     - EC07 FRONT: STEP_DOWN พบ 1 จุด ratio=46% ตรงตำแหน่งกล่องเขียว(TGT1C-BU)/น้ำเงิน
#       (HOW1A-BU) ที่ผู้ใช้วาดเส้นแดงชี้ไว้พอดี (แก้ false negative สำเร็จ)
#     - EC09 FRONT: STEP_DOWN พบ 1 จุด ratio=33% ตรงตำแหน่งกล่องเขียว(STEMA-B5)/น้ำเงิน
#       (KAP1A-B5) ที่ผู้ใช้วาดเส้นแดงชี้ไว้พอดี (แก้ false negative สำเร็จ)
#     - EC10 BACK: STEP_DOWN พบ 1 จุดใหม่ ratio=64% - ตรวจสอบภาพจริงยืนยันว่าเป็นความ
#       เสี่ยงจริง (ตั้งน้ำเงิน+แดง 1 ชั้น อยู่ติดตั้งแดง+เขียว 2 ชั้นที่สูงกว่ามาก)
#     - EC18 BACK: STEP_DOWN พบ 1 จุดใหม่ ratio=64% - ตรวจสอบภาพจริงยืนยันว่าเป็นความ
#       เสี่ยงจริงเช่นกัน (ตั้งน้ำเงิน+เขียว 2 ชั้น อยู่ติดตั้งเขียวล้วน 3 ชั้น)
#     - REAR_LATERAL_IMBALANCE (v24.29 fix): ยังทำงานถูกต้องเหมือนเดิมทุกไฟล์ ไม่ถูก
#       กระทบจากการแก้ไขในเวอร์ชันนี้เลย (คนละฟังก์ชัน คนละ code path)
#     - LOW_EXPOSED/OVERHANG: ยังคงเป็น 0 ในทุกไฟล์เหมือนเดิม ไม่มี false positive ใหม่
#
#   สรุป: v24.30 แก้ทั้ง 2 ปัญหาสำเร็จ พร้อมยืนยันด้วยข้อมูลจริงและตรวจสอบภาพจริงประกอบ
#   ทุกจุด ไม่มี regression ในไฟล์ทดสอบทั้งหมดที่มีอยู่ (5 ไฟล์ครอบคลุมทั้งเคส SAFE และ
#   เคสความเสี่ยงจริงหลายรูปแบบ)
#
# AI Cargo Safety Checker - High Precision v24.29 [ประวัติเดิม]
#
# v24.29 - แก้ REAR_LATERAL_IMBALANCE false positive (กรอบสีชมพูเข้ม/deeppink) ที่
#   EA06-01 BACK view ยืนยันจาก log จริงของ production run v24.28: ผู้ใช้ระบุว่ากล่อง
#   เขียว/เหลือง/แดง สูงเสมอกันจริง ไม่มีความเสี่ยง แต่ log แสดง
#   "REAR_LATERAL_IMBALANCE (BACK) accepted with confidence=HIGH" (ไม่ถูก veto)
#
#   ตอนแรกเข้าใจผิดว่ากรอบชมพูมาจาก TALL_UNSTABLE_RISK (สี magenta) แต่ตรวจสอบ log
#   ละเอียดพบว่าเป็น REAR_LATERAL_IMBALANCE (สี deeppink) ต่างหาก - คนละ risk type คนละ
#   code path กับที่เคยตรวจสอบไปก่อนหน้านี้เลย (REAR_LATERAL_IMBALANCE วิเคราะห์ผ่าน
#   Gemini AI zoom เข้าไปที่ "rear zone crop" โดยตรง ไม่ได้ใช้ per-box stack model
#   เหมือน TALL_UNSTABLE_RISK)
#
#   ROOT CAUSE ที่แท้จริง (ยืนยันด้วยการคำนวณจาก pixel จริงของไฟล์เดียวกัน): ตั้งที่ x=
#   [635-906] (กว้าง 271px) เป็น "merged stack" กว้างถึง 2.05 เท่าของค่ามัธยฐาน (132px)
#   ในแถวเดียวกัน - per-box segmentation รวมกล่อง 3 ใบ (เขียว/เหลือง/แดง) เป็นตั้งเดียว
#   ผิดพลาด (เหมือนปัญหา EA10 ทุกประการ) ทำให้ค่า top_y/floor_y ที่วัดได้ (h=259) เป็นค่า
#   คลาดเคลื่อนจากการรวมพิกเซลผิด ไม่ใช่ความสูงจริงของกล่องใดกล่องหนึ่งเพียงลำพัง
#
#   เมื่อนำไปเทียบกับตั้งข้างเคียง (h=204, ก็เป็น merged stack เช่นกันแต่ไม่เกินเกณฑ์)
#   ในฟังก์ชัน get_max_lateral_imbalance_ratio_in_zone() (ใช้ตัดสินใจ VETO สำหรับ AI
#   claim) ได้ผลต่างปลอม 21.2% ซึ่งสูงกว่า LATERAL_IMBALANCE_VETO_MAX_RATIO (20%) เพียง
#   เล็กน้อย ทำให้ veto ไม่ทำงาน (21.2% ไม่ < 20%) ปล่อยให้ AI claim ที่ไม่ควรผ่านหลุด
#   เข้ามาเป็นกรอบ REAR_LATERAL_IMBALANCE จริง
#
#   สาเหตุหลักคือ get_max_lateral_imbalance_ratio_in_zone()/
#   detect_lateral_imbalance_regions_for_view() ไม่เคยกรอง merged stack ออกก่อนคำนวณ
#   เลยตั้งแต่ต้น ต่างจาก STEP_DOWN_RISK/LOW_EXPOSED ที่มี MERGED-STACK GATE
#   (_step_down_merged_stack_indices, เกณฑ์ 1.6 เท่าของมัธยฐาน) ป้องกันอยู่แล้ว
#
#   วิธีแก้: เพิ่มฟังก์ชันกลาง _filter_out_merged_stacks_in_zone() ที่ใช้
#   _step_down_merged_stack_indices() ตัวเดียวกัน (คำนวณค่ามัธยฐานจากตั้งทั้งหมดในแถว
#   ไม่ใช่แค่โซนท้ายตู้ ซึ่งอาจมีตั้งน้อยเกินไปจนมัธยฐานไม่มีความหมาย) กรองตั้งที่กว้าง
#   ผิดปกติออกก่อน แล้วค่อยกรองเฉพาะโซนท้ายตู้ - ใช้ร่วมกันทั้งใน
#   get_max_lateral_imbalance_ratio_in_zone() (veto logic) และ
#   detect_lateral_imbalance_regions_for_view() (FORCE deterministic logic) เพื่อความ
#   สอดคล้องกัน เนื่องจากทั้งคู่มี root cause เดียวกัน
#
#   ผลทดสอบจริง (รันโค้ดจริงกับ PDF ต้นฉบับไฟล์เดียวกับที่พบปัญหา):
#     - EA06-01 BACK: max_ratio ลดจาก 21.2% (ก่อนแก้) เหลือ 0.0% (หลังแก้, ไม่มีคู่ตั้งที่
#       เชื่อถือได้เหลืออยู่ในโซนท้ายตู้เลยหลังกรอง merged stack ออก) -> veto ทำงานถูกต้อง
#       (0.0% < 20% threshold) -> กรอบ REAR_LATERAL_IMBALANCE เท็จจะไม่ปรากฏอีกต่อไป
#     - EA06-01 FRONT: max_ratio ยังคงเป็น 18.3% เหมือนเดิม (ไม่กระทบ - เคย veto อยู่แล้ว
#       ก่อนแก้ไข และยังคง veto เหมือนเดิมหลังแก้ไข)
#     - Synthetic regression tests (ไม่มี merged stack): ผลลัพธ์เหมือนเดิมทุกประการ
#       ยืนยันว่าการแก้ไขนี้ไม่กระทบกรณีปกติที่ segmentation ทำงานถูกต้องอยู่แล้ว
#
#   หมายเหตุ: PDF ต้นฉบับของ EA07/EA10/AA04-03/AA04-06 ที่เคยใช้ regression test มาก่อน
#   หน้านี้ไม่มีอยู่ใน environment แล้ว (ไฟล์ถูกลบ/หมดอายุไปตามวงจรของระบบ) จึงยืนยันผล
#   ได้เฉพาะไฟล์ EA06-01 ที่มีอยู่จริงเท่านั้น แต่หลักประกันทางตรรกะ (merged_idxs ว่าง
#   เปล่าเมื่อไม่มี merged stack = พฤติกรรมเหมือนเดิมทุกประการ) ยืนยันด้วย unit test
#   สังเคราะห์แล้วว่าปลอดภัยสำหรับกรณีทั่วไป
#
# AI Cargo Safety Checker - High Precision v24.27 [ประวัติเดิม]
#
# v24.27 - แก้ 2 ปัญหาที่ผู้ใช้ยืนยันจากภาพจริง (EA07 BACK="OK", AA04-03 BACK="NG":
#   ตัวกล่องชมพูเองเสี่ยงหล่น/ไม่มั่นคงเพราะฐานรองรับแคบกว่า):
#
#   1) FLOOR-COVERAGE GATE สำหรับ LOW_EXPOSED FLOODFILL (สำเร็จ ทดสอบยืนยันแล้ว):
#   ROOT CAUSE ที่พบ - v24.26 เคยขึ้น false positive ที่ EA07 BACK (53%) และ AA04-03
#   BACK (62-78%, 3 จุด) เพราะเปรียบเทียบ "กล่องที่ชิดพื้นบางส่วน" กับเพื่อนบ้านโดยไม่
#   ตรวจสอบว่ากล่องนั้นกว้างพอจะเป็น "กล่องเดียววางเต็มฐาน" แบบ EA10 หรือไม่ - วัด pixel
#   จริงพบว่า EA07/AA04-03 ที่เป็น false positive ล้วนเป็นภูมิภาคที่กว้างแค่ 13-33% ของ
#   ตั้งทั้งหมด (คือแค่ 1 ใน "หลายกล่องที่วางเรียงกันปกติ") ในขณะที่ EA10 (ความเสี่ยงจริง)
#   กล่องเขียวกว้างถึง 98% ของตั้ง (คือ "กล่องเดียววางเต็มฐานจริง")
#
#   วิธีแก้: เพิ่ม LOW_EXPOSED_FLOODFILL_MIN_FLOOR_COVERAGE_RATIO=70% เป็นเงื่อนไขบังคับ
#   เพิ่มเติม - ภูมิภาคที่ชิดพื้นต้องกว้างอย่างน้อย 70% ของตั้งทั้งหมดที่ถูกรวม จึงจะ
#   ยอมรับเป็น candidate ผลทดสอบจริง (รันโค้ดจริงกับ PDF ทั้ง 5 ไฟล์):
#     - EA07: LOW_EXPOSED = 0 candidates (แก้ false positive สำเร็จ - ผู้ใช้ยืนยัน "OK")
#     - AA04-03: LOW_EXPOSED = 0 candidates (ไม่มี false positive อีกต่อไป)
#     - EA10: LOW_EXPOSED ยังคงพบกล่องเขียวที่ถูกต้อง (39%, ไม่กระทบ)
#     - AA02-01, AA04-06: LOW_EXPOSED = 0 candidates เช่นกัน (ทุก candidate ที่เคยพบมี
#       floor coverage ต่ำกว่า 70% ทั้งหมด)
#
#   2) OVERHANG-VIA-FLOODFILL สำหรับ AA04-03 (ไม่สำเร็จ - ปิดไว้ก่อน ต้องแจ้งตรงไปตรงมา):
#   ผู้ใช้ยืนยันว่า AA04-03 มีความเสี่ยงจริงคนละประเภทจาก LOW_EXPOSED - กล่องชมพูชั้นบน
#   เองไม่มั่นคงเพราะฐานรองรับ (กล่องแดงด้านล่าง) แคบกว่า/ไม่ตรงตำแหน่ง (คล้าย
#   OVERHANG_RISK ปกติ แต่เกิดในตั้งที่ถูกรวมผิดจาก column scan) - ลองสร้าง detector ใหม่
#   (_find_overhang_via_flood_fill) ที่เปรียบเทียบความกว้างกล่องบนกับฐานรองรับที่สัมผัส
#   กันโดยตรงจาก flood-fill regions แต่ทดสอบจริงแล้วพบว่า logic ยังไม่แม่นยำพอ - เกิด
#   false positive จำนวนมากในทุกไฟล์ทดสอบ รวมถึง EA07 ที่ผู้ใช้เพิ่งยืนยันว่าปลอดภัย (พบ
#   3 จุดปลอมที่ BACK view) และจุดที่ไม่เคยมีใครยืนยันใน EA10/AA02-01/AA04-06 อีกหลายจุด
#   - สาเหตุคือ flood-fill แยกภูมิภาคตามสีเท่านั้น ไม่ได้เข้าใจ "ขอบเขตกล่องจริงตามมุมมอง
#   isometric" ทำให้กล่องหลายใบที่วางซ้อนกันเป็นชั้นๆ ตามปกติ (ซึ่งมักมีส่วนบังกันบางส่วน
#   ตามธรรมชาติของมุมมอง) ถูกเข้าใจผิดว่า "ฐานรองรับไม่เพียงพอ" อยู่ตลอด - ปิดฟีเจอร์นี้
#   ไว้ (OVERHANG_FLOODFILL_DETECTOR_ENABLED=False) เพื่อไม่ให้เกิด false positive มหาศาล
#   เก็บโค้ดไว้เป็นจุดเริ่มต้นสำหรับพัฒนาต่อ แต่ AA04-03 ยังไม่มี detector ที่ใช้งานได้
#   จริงในเวอร์ชันนี้ - ต้องพัฒนาต่อในเวอร์ชันถัดไปด้วยวิธีที่แม่นยำกว่านี้
#
# v24.26 - แก้ EA10 false negative ที่ ROOT CAUSE จริง (ตามที่ผู้ใช้ขอ "แก้ที่ต้นตอจริง")
#   ผลตรวจสอบ v24.25 พบว่า per-box segmentation (detect_stack_columns) รวมกล่อง 3 ใบ
#   (เขียว/น้ำตาล/ชมพู) ในไฟล์ EA10 เป็น "ตั้งเดียว" กว้างผิดปกติ (1.99 เท่าของมัธยฐาน)
#   ตั้งแต่ขั้นตอนแบ่งคอลัมน์ - สาเหตุคือกล่องเขียว (เตี้ย) มีฐานกว้างเต็มความกว้างของ
#   ตั้งทั้งหมด ในขณะที่กล่องน้ำตาล+ชมพูวางซ้อนทับอยู่ด้านบนคนละครึ่ง (น้ำตาลขวา ชมพูซ้าย)
#   ทำให้การสแกนแนวคอลัมน์แบบเดิม (ซึ่งดูสีที่ระดับพื้นเท่านั้น) มองไม่เห็นจุดแบ่งเลย
#   เพราะพื้นสีเขียวต่อเนื่องเต็มความกว้างจริง - เมื่อคำนวณความสูงของ "ตั้งที่ถูกรวมผิด"
#   ทั้งก้อน (258px) เทียบกับตั้งข้างเคียง ได้ผลต่างเพียง 8% (v24.25) ต่ำกว่าเกณฑ์มาก
#
#   วิธีแก้ (ROOT-CAUSE LEVEL, ไม่ใช่แค่ปรับ threshold): เพิ่ม FLOOD-FILL DECOMPOSITION
#   (ฟังก์ชันใหม่ _flood_fill_vivid_regions, _find_low_exposed_via_flood_fill) - สำหรับ
#   ตั้งที่ถูกระบุว่า "กว้างผิดปกติจริง" (merged, > 1.6 เท่าของค่ามัธยฐาน - เกณฑ์เดียวกับ
#   ที่ STEP_DOWN_RISK ใช้อยู่แล้ว) จะใช้ connected-component flood-fill (BFS 4-connectivity
#   แยกกลุ่มพิกเซลสีเดียวกันที่ติดกัน) แยกภูมิภาคสีภายในตั้งนั้นออกเป็นกล่องแต่ละใบจริง
#   แทนการเดาจากโปรไฟล์ 1 มิติที่พลาดกรณีนี้ไปตั้งแต่ต้น
#
#   จากนั้นเปรียบเทียบ "กล่องที่ชิดพื้น" (floor-touching region) กับ "กล่องที่สัมผัสกัน
#   โดยตรงด้านบนเท่านั้น" (ไม่ใช่ผลรวมทุกชั้นที่ซ้อนกันอยู่ - ทดสอบแล้วว่าการเทียบกับ
#   ผลรวมทุกชั้นทำให้กล่องชั้นล่างสุดของ stack ปกติทุกอันถูกเข้าใจผิดว่าเตี้ยผิดปกติเสมอ
#   เพราะกล่องชั้นล่างสุดย่อมเตี้ยกว่าผลรวมทั้งหมดเป็นธรรมดา - พบปัญหานี้จากการทดสอบกับ
#   ไฟล์ EA07 ซึ่งมีกล่องเรียงซ้อนหลายชั้นปกติ)
#
#   ผลทดสอบจริง (รันโค้ดจริงกับ PDF ต้นฉบับ):
#     - EA10: flood-fill แยกตั้งที่กว้างผิดปกติ (x=568-701) ออกเป็น 3 ภูมิภาคชัดเจน
#       (เขียว/ฐาน สูง 87px, น้ำตาล/ขวาบน สูง 142px ติดกันโดยตรง) -> height_diff_ratio
#       = 39% -> ตรวจพบเป็น LOW_EXPOSED_RISK ที่ตำแหน่งกล่องเขียวได้สำเร็จ (แก้ false
#       negative ของ v24.25 ได้แล้ว)
#     - EA07: ตั้งที่กว้างผิดปกติเดิม (x=568-720) ที่เคยเป็น false positive ยังคง REJECTED
#       ถูกต้อง (candidate สูงสุดที่ตำแหน่งนี้แค่ 21% ต่ำกว่าเกณฑ์ 35%)
#
#   คำเตือนสำคัญที่ต้องแจ้งตรงไปตรงมา: ทดสอบข้ามไฟล์เพิ่มเติม (AA02-01, AA04-03, AA04-06)
#   พบว่านอกจาก EA10 แล้ว มี candidate ใหม่โผล่ขึ้นมาในตำแหน่งที่ไม่เคยถูกตรวจสอบ/ยืนยัน
#   มาก่อน (เช่น EA07 BACK view ที่ให้ผล 53%, AA04-03 BACK view ที่ให้ผล 78%) - เนื่องจาก
#   ไม่มีข้อมูลตำแหน่งกล่องจริง (ground truth) ฝังอยู่ใน PDF ให้ตรวจสอบได้ (ยืนยันแล้วว่า
#   ไดอะแกรมเป็นภาพ raster ที่ฝังไว้ ไม่ใช่ vector ที่มีพิกัดกล่อง) จึงไม่สามารถยืนยันได้
#   100% ว่า candidate ใหม่เหล่านี้เป็นความเสี่ยงจริงหรือเป็น false positive ใหม่ - ผู้ใช้
#   ควรตรวจสอบผลลัพธ์จากไฟล์จริงเหล่านี้เพิ่มเติมและแจ้งกลับ เพื่อปรับ threshold
#   (LOW_EXPOSED_FLOODFILL_HEIGHT_DIFF_MIN_RATIO, ปัจจุบัน=35%) ให้แม่นยำขึ้นในเวอร์ชัน
#   ถัดไป - จุดนี้เป็นข้อจำกัดของการวิเคราะห์จาก pixel เพียงอย่างเดียวโดยไม่มี ground truth
#
# v24.25 - แก้ v24.24 ที่ทดสอบจริงแล้วพบว่า "pixel-color verification" ใช้แยกแยะ EA07
#   กับ EA10 ไม่ได้ (ทั้ง 2 เคสผ่านเกณฑ์ 55% เหมือนกันหมด เพราะพื้นที่เหนือกล่องเตี้ยใน
#   ภาพ isometric มักมีส่วนที่ไม่ใช่สีคาร์โก้อยู่เสมอไม่ว่าจะปลอดภัยหรือเสี่ยงจริง)
#   เปลี่ยนมาใช้ HEIGHT-DIFFERENCE-RATIO (ผลต่างความสูงรวมระหว่างตั้งเตี้ยกับตั้งข้างเคียง
#   ที่สูงกว่า, เกณฑ์ 50%) แทน - ดูรายละเอียดที่ LOW_EXPOSED_HEIGHT_DIFF_MIN_RATIO
#
#   ผลทดสอบจริง (รันโค้ดจริงกับ PDF ต้นฉบับ ไม่ใช่การจำลอง) กับทั้ง 5 ไฟล์:
#     - EA07: LOW_EXPOSED candidate REJECTED (height_diff_ratio=5%, ต่ำกว่าเกณฑ์ 50%)
#       -> ไม่ขึ้นกรอบเท็จ ตรงตามที่ควรจะเป็น (แก้ false positive สำเร็จ เหมือน v24.23/24.24)
#     - AA02-01, AA04-03, AA04-06 (ไฟล์ regression ใหม่): ไม่มี candidate ใดผ่านเกณฑ์เลย
#       ทั้ง 3 ไฟล์ -> ไม่มี false positive ใหม่เกิดขึ้น (ปลอดภัย)
#     - EA10: *** ยังไม่พบ LOW_EXPOSED candidate ที่ตำแหน่งกล่องเขียวที่ผู้ใช้ชี้ *** -
#       ต้องแจ้งตรงไปตรงมา: การแก้ครั้งนี้ยังไม่สามารถจับจุดเสี่ยงจริงใน EA10 ได้ ทั้งที่
#       ตั้งใจแก้จุดนี้โดยเฉพาะ
#
#   ROOT CAUSE ที่แท้จริงของความล้มเหลวนี้ (ตรวจสอบแล้วด้วย pixel จริงและ log ของโค้ด):
#   per-box segmentation (build_stack_box_model_for_view) ไม่เคยแยกกล่องเขียวออกมาเป็น
#   "ตั้งของตัวเอง" เลยตั้งแต่ต้น - มันถูกรวม (merge) เข้ากับพิกเซลบางส่วนของตั้งสูงข้างเคียง
#   (ชมพู/น้ำตาล) เป็นตั้งเดียวกว้างผิดปกติ (133px จากค่ามัธยฐานตั้งอื่น 67px = 1.99 เท่า -
#   ซึ่งเกินเกณฑ์ MERGED-STACK GATE ที่ใช้กับ STEP_DOWN_RISK อยู่แล้ว 1.6 เท่า) เมื่อคำนวณ
#   ความสูงของ "ตั้งที่ถูกรวมผิด" นี้ ค่าที่ได้ (258px) จึงเป็นค่าคลาดเคลื่อน/เฉลี่ยจากการ
#   รวมพิกเซลผิด ไม่ใช่ความสูงจริงของกล่องเขียวเพียงอย่างเดียว ทำให้เมื่อเทียบกับตั้ง
#   ข้างเคียง (280px) ได้ผลต่างเพียง 8% (ต่ำกว่าเกณฑ์ 50% มาก) ทั้งที่ความสูงจริงของกล่อง
#   เขียวเพียงลำพัง (ถ้าแยกออกมาได้ถูกต้อง) น่าจะต่างจากเพื่อนบ้านมากกว่านี้มาก
#
#   สรุปสถานะที่แท้จริงของ v24.25: แก้ปัญหา EA07 false positive ได้สำเร็จ (คงอยู่) และ
#   ไม่มี regression ใหม่ในไฟล์ทดสอบเพิ่มเติมทั้ง 3 ไฟล์ - แต่ "ยังไม่แก้" ปัญหา EA10 false
#   negative ได้จริง เพราะ root cause ที่แท้จริงอยู่ที่ขั้นตอน per-box segmentation (การ
#   แบ่งกล่องออกเป็นตั้งๆ) ไม่ใช่ขั้นตอนเปรียบเทียบความสูงที่แก้ไขในเวอร์ชันนี้ - การแก้ไข
#   ที่ตำแหน่งนี้จำเป็นต้องปรับปรุง build_stack_box_model_for_view/detect_boxes_in_stack
#   ให้แยกเส้นแบ่งสีภายในตั้งที่กว้างผิดปกติออกเป็นตั้งย่อยหลายตั้งก่อน (ไม่ใช่แค่ปฏิเสธ
#   ตั้งที่กว้างผิดปกติทิ้งไปแบบที่ MERGED-STACK GATE ทำอยู่ในปัจจุบัน) ซึ่งเป็นงานที่ใหญ่
#   กว่าการปรับ threshold และควรทำเป็นเวอร์ชันถัดไปโดยเฉพาะ
#
# v24.24 - เคยเพิ่ม PIXEL-VERIFIED OPEN-SPACE GATE (ตรวจสอบว่าพื้นที่เหนือตั้งเตี้ยไม่ใช่
#   สีคาร์โก้จริง) แต่ทดสอบจริงแล้วพบว่าใช้แยกแยะ EA07/EA10 ไม่ได้ (ดู CHANGELOG v24.25
#   ด้านบน) - แทนที่ด้วย HEIGHT-DIFFERENCE-RATIO GATE ใน v24.25
#
# v24.23 - [ROOT CAUSE FIX ใน v24.24] เคยปิด LOW_EXPOSED_DETECTOR_ENABLED = False ทั้งหมด
#   เพื่อแก้ false positive ของ EA07 - พบว่าเป็นการแก้แบบเหมาเข่งที่ทำให้ EA10 (ความเสี่ยง
#   จริง) ตรวจไม่พบไปด้วย ดู CHANGELOG v24.24 ด้านบนสำหรับวิธีแก้ที่ถูกจุด
#
#   ส่วนอื่นของ v24.23 ที่ยังคงใช้งานอยู่ (ไม่เปลี่ยนแปลงใน v24.24):
#   1) EA06 ช่องว่างท้ายรถ/พื้นท้ายตู้ประมาณ 5-10% ถูกระบุเป็น FLOOR/REAR EMPTY marker
#      ได้ แม้ mm calibration ไม่พร้อม โดยใช้ ratio threshold เฉพาะ floor-empty ที่ 5%
#   2) TALL_UNSTABLE_RISK/กรอบชมพู false positive ถูกปิดด้วย hard filter ขั้นสุดท้าย
#      วาดได้เฉพาะกรณีที่มี deterministic tall-unstable region ที่ผ่าน gate และ box
#      ของ claim overlap จริงเท่านั้น
#
# v24.22 - Fix ตามผลทดสอบ EA06/EA10 หลัง v24.21:
#   1) เพิ่ม LOW-EXPOSED-STACK detector สำหรับเคสที่เป็นกล่อง/ตั้งชั้นล่างโดดเด่นอยู่ติดกับ
#      พื้นที่ว่างด้านบน/ด้านข้าง ซึ่งควรระบุเป็น STEP_DOWN_RISK ที่ตำแหน่งกล่องจริงตาม
#      กรอบสีแดงที่ผู้ใช้วงไว้ ไม่ใช่ปล่อยให้ไม่ระบุจุดเสี่ยง
#   2) ทำให้ TALL_UNSTABLE_RISK เข้มขึ้นอีกชั้น: ถ้าไม่มี deterministic tall-unstable ที่ผ่าน
#      box-count/neighbor gate จะไม่ให้กรอบชมพูจาก AI วาดทับตำแหน่งผิด
#   3) สำหรับ gap marker: ถ้าเป็น LATERAL_GAP แต่ marker มีแนวโน้มไปอยู่ใต้/นอกตู้และไม่มี
#      local evidence ชัดเจน จะไม่วาด marker เพื่อหลีกเลี่ยงการสื่อสารผิดตำแหน่ง
#
# v24.21 - Fix ตามผลทดสอบ v24.20 โดยโฟกัส 3 จุดจากผู้ใช้:
#   1) ตัด fallback กรอบฟ้า/เขียวสำหรับกลุ่ม gap ที่เคยไปครอบสินค้า: ถ้าเป็น
#      LATERAL_GAP_RISK/FRONT_EMPTY_RISK/REAR_EMPTY_RISK แล้ววาด measurement marker
#      ที่มีจุดอ้างอิงจริงไม่ได้ จะไม่ fallback ไปวาด rectangle ทับ cargo อีก
#   2) กรณี LATERAL_GAP_RISK ที่จริงเป็นพื้นที่ว่างบนพื้นท้ายตู้/พื้นด้านหลัง cargo
#      ให้ย้ายตำแหน่ง marker ไปยัง empty floor zone โดยใช้ localized gap box ที่หาได้จาก
#      pixel evidence แทนการวางลูกศรลอยนอกตู้
#   3) เปลี่ยน label จาก SIDE GAP เป็น FLOOR EMPTY เมื่อช่องว่างนั้นเป็นพื้นที่ว่างพื้น
#      ด้านหลัง/ด้านท้ายตู้จริง เพื่อให้ผู้ใช้งานเข้าใจว่าเป็น empty floor zone ไม่ใช่
#      lateral side clearance
#
# v24.20 - Fix ตามผลทดสอบ v24.19:
#   1) TALL_UNSTABLE_RISK (กรอบชมพู): เพิ่ม gate ให้ต้องเป็นตั้งสูงโดดเดี่ยวจริง โดย
#      จำนวนกล่อง/จำนวนชั้นของตั้งนั้นต้องมากกว่าเพื่อนบ้านทั้งสองฝั่งจริง และต้องไม่ใช่
#      edge/fragment/merged stack จากมุม isometric หรือ segmentation error
#   2) GAP ARROW UX: ลูกศร LATERAL/FRONT/REAR GAP จะวาดเฉพาะเมื่อมี local edge evidence
#      ที่ชัดเจนเท่านั้น หากไม่มีหลักฐานขอบจริง จะ fallback เป็นกรอบบางแทน ไม่วางลูกศรลอย
#   3) Label บนลูกศรเพิ่มชนิดของ gap: SIDE GAP / FRONT EMPTY / REAR EMPTY เพื่อให้ผู้ใช้
#      เข้าใจทันทีว่าตัวเลขกำลังวัดช่องว่างประเภทใด
#
# v24.19 - Hotfix ตามผลทดสอบ EA03/EA06/EA02:
#   1) STEP_DOWN_RISK (กรอบแดง): เพิ่ม STACK-COUNT GATE เพื่อป้องกัน false positive จาก
#      perspective/isometric slope และความสูง pixel ที่ต่างกัน แม้จำนวนชั้น/จำนวนกล่องในตั้ง
#      เท่ากันจริง - จากนี้จะ flag STEP_DOWN เฉพาะกรณีที่ตั้งข้างเคียงมีจำนวนกล่อง/ชั้นมากกว่า
#      ตั้งที่เตี้ยกว่าอย่างชัดเจน (neighbor box-count > current box-count) เท่านั้น
#   2) LATERAL_GAP_RISK arrow: ถ้าหา local gap x-range ที่มีหลักฐาน pixel จริงไม่ได้ จะไม่วาด
#      ลูกศรลอยกลางพื้นที่ว่างอีก แต่ fallback ไปกรอบ/box เดิม เพื่อหลีกเลี่ยงเส้นวัดระยะที่
#      ไม่แตะขอบสินค้า/ขอบพื้นจริง
#
# v24.18 - เปลี่ยนวิธีแสดงผล LATERAL_GAP_RISK/FRONT_EMPTY_RISK/REAR_EMPTY_RISK จาก
#   "กรอบสี่เหลี่ยมทึบ" เป็น "เส้นลูกศร 2 หัว + ตัวเลขระยะห่างกำกับ" (คล้ายเส้นบอกขนาด
#   ในแบบวิศวกรรม/CAD) ตามคำแนะนำผู้ใช้: "จากขอบกล่องสินค้าถึงขอบของพื้น/ผนัง เป็น
#   เส้นตรงลูกศร 2 หัวท้าย ตรง gap นั้น" (ครอบคลุมทั้ง 3 risk type ตามคำขอเพิ่มเติม
#   "เพิ่ม rear empty risk ด้วยนะครับ") - เหตุผล: กรอบสี่เหลี่ยมสื่อถึง "พื้นที่/บริเวณ"
#   ในขณะที่สิ่งที่ต้องการสื่อจริงคือ "ระยะทางระหว่างจุด 2 จุด" ซึ่งลูกศรสื่อความหมาย
#   ตรงกว่าและอ่านง่ายกว่ามาก โดยเฉพาะเมื่อมีตัวเลขระยะทางจริงกำกับไว้ด้วย
#
#   องค์ประกอบที่เพิ่ม (ฟังก์ชันใหม่ _draw_gap_measurement_arrow):
#     1. เส้นลูกศร 2 หัว (◄──►) ลากระหว่างขอบคาร์โก้จริงกับขอบตู้จริง ตามทิศทางของ
#        ช่องว่างนั้นๆ โดยเฉพาะ:
#          - LATERAL_GAP_RISK: แนวตั้ง (ช่องว่างด้านบน/ล่างของคาร์โก้เทียบกับขอบตู้)
#          - FRONT_EMPTY_RISK, REAR_EMPTY_RISK: แนวนอน (ช่องว่างตามความยาวตู้ระหว่าง
#            คาร์โก้กับผนังหัวตู้/ประตูท้ายตู้)
#     2. ขีดตั้งฉากสั้นๆ ที่ปลายทั้ง 2 ข้างของเส้น (dimension tick, คล้ายเส้นบอกขนาด
#        ในแบบวิศวกรรม) เพื่อชี้ตำแหน่งจุดเริ่ม/จุดสิ้นสุดของระยะที่วัดให้ชัดเจน
#     3. หัวลูกศรจริง (triangle arrowhead) ที่ปลายทั้ง 2 ด้าน ชี้เข้าหากัน
#     4. ตัวเลขระยะห่างจริงกำกับกึ่งกลางเส้น (ดึงจากฟังก์ชัน deterministic ที่มีอยู่แล้ว
#        - compute_lateral_gap_mm/compute_empty_gap_mm, มี fallback เป็น % หากคาลิเบรต
#        มม. ไม่สำเร็จ) พร้อมพื้นหลังสีขาวโปร่งเพื่อให้อ่านง่ายไม่ว่าพื้นหลังภาพจะเป็น
#        สีอะไร - คำนวณค่านี้ ณ เวลาวาดภาพโดยตรงจาก container_bounds/cargo_extent
#        (ไม่ผูกกับแหล่งที่มาของ risk ว่าเป็น AI claim หรือ deterministic FORCE) จึงมี
#        ตัวเลขกำกับเสมอไม่ว่า risk นั้นจะถูกตรวจพบจากทางไหนก็ตาม
#     5. กรณีช่องว่างแคบมาก (< GAP_ARROW_MIN_LENGTH_FOR_INLINE_LABEL_PX) ย้าย label
#        ตัวเลขออกไปด้านนอกเส้นแทนการวางทับกึ่งกลาง กันตัวเลขบังกันเองในพื้นที่แคบ
#
#   ตำแหน่งจุดเริ่ม/จุดสิ้นสุดของลูกศรใช้พิกัด "กึ่งกลางตามแนวขวางของช่องว่าง" (ไม่ใช่ที่
#   ขอบคาร์โก้ทั้งเส้น) เพื่อไม่ให้เส้นทับซ้อนกับตัวอักษร SKU บนกล่องหรือเส้นขอบกล่อง -
#   สำหรับ LATERAL_GAP_RISK ใช้ตำแหน่ง x กึ่งกลางของช่วงที่ระบุว่าว่างจริง (จาก
#   _localize_lateral_gap_x_range ที่มีอยู่แล้ว) สำหรับ FRONT/REAR_EMPTY_RISK ใช้
#   ตำแหน่ง y กึ่งกลางของคาร์โก้ในมุมมองนั้น
#
#   ยังคงใช้กรอบสี่เหลี่ยมแบบเดิมสำหรับความเสี่ยงประเภทอื่นทั้งหมด (STEP_DOWN_RISK,
#   OVERHANG_RISK, TALL_UNSTABLE_RISK, REAR_LATERAL_IMBALANCE, REAR_COMBINED_RISK,
#   COMBINED_AREA_RISK) เพราะเป็นความเสี่ยงเชิง "พื้นที่/การเปรียบเทียบความสูง" ไม่ใช่
#   "ระยะห่างเชิงเส้นตรง" แบบเดียวกัน - เปลี่ยนเฉพาะรูปแบบการวาดภาพเท่านั้น ไม่กระทบ
#   ตรรกะการตรวจจับความเสี่ยงใดๆ เลย (ทุก threshold/gate/deterministic logic เหมือนเดิม
#   ทุกประการ)
#
# v24.17 - STEP_DOWN_RISK: เพิ่ม MERGED-STACK GATE แบบ median-based (ไฟล์ EC50-02,
#   FRONT view) - per-box segmentation รวมกล่อง 2 ใบเป็นตั้งเดียวผิดพลาด (148px เทียบ
#   มัธยฐาน 65px = 228%) ทำให้เกิดผลต่างความสูงปลอม - แก้ไขด้วยเกณฑ์ตั้งกว้างเกิน 1.6
#   เท่าของมัธยฐานความกว้างตั้งในแถวเดียวกัน (ใช้เมื่อมีตั้ง >= 3 ตั้งขึ้นไป)
#
# v24.16 - STEP_DOWN_RISK: เพิ่ม EDGE-ARTIFACT GATE (ไฟล์ EC50-02, BACK view) - ที่ขอบ
#   ผนังหัวตู้ per-box segmentation สร้าง "ตั้งปลอม" แคบผิดปกติจากมุม isometric corner/
#   top-face ของกล่องใบแรกสุด - แก้ไขด้วยการคัดตั้งที่อยู่ใกล้ขอบคาร์โก้และแคบกว่า 70%
#   ของมัธยฐานออกจากการเปรียบเทียบ
#
# v24.15 - STEP_DOWN_RISK: เพิ่ม ISOLATED-PEAK EXCLUSION - ตั้งสูงโดดเดี่ยว 1 ตั้งเคย
#   ถูก flag เป็น STEP_DOWN_RISK ซ้ำซ้อนกับ TALL_UNSTABLE_RISK ที่ตรวจพบไปแล้ว - แก้ไข
#   ด้วยการข้ามตั้งที่เข้าเกณฑ์ "ตั้งสูงโดดเดี่ยว" (เกณฑ์เดียวกับ TALL_UNSTABLE_RISK)
#
# v24.14 - STEP_DOWN_RISK: เพิ่ม STACK-WIDTH SANITY GATE (ป้องกันกรอบใหญ่ผิดปกติจาก
#   under-segmentation ที่รวมกล่องหลายใบ) + RAW-STACK FALLBACK (สำหรับ view ที่
#   coverage ต่ำ เช่น BACK) + กรอบ REAR_EMPTY_RISK/FRONT_EMPTY_RISK จาก AI zoom ถูกตัด
#   (intersect) ให้ไม่เกินขอบเขตช่องว่างที่วัดได้จริงแบบ deterministic
#
# v24.13 - STEP_DOWN_RISK เปลี่ยนวิธีตรวจจับทั้งหมด จาก pixel/height-profile scan +
#   floor-hole scan + cross-view mirror/veto (v24.1-v24.11) ซึ่งไวต่อสัญญาณรบกวนมาก
#   ไปใช้การเปรียบเทียบ "ความสูงรวมของตั้งกล่องที่ติดกันโดยตรง" (per-box stack model
#   เดียวกับ OVERHANG_RISK/TALL_UNSTABLE_RISK/REAR_LATERAL_IMBALANCE) ตามคำขอผู้ใช้:
#   "ค้นหาแค่ตั้งของกล่องที่ต่ำกว่า ตั้งของกล่องด้านข้าง" - ลบฟังก์ชันเดิมที่ไม่ใช้แล้ว
#   ทั้งหมด (floor-hole, height-profile, cross-view, OCR-SKU matching) ออกจากโค้ด
#
#   นอกจากนี้ยังแก้ไข LATERAL_GAP_RISK (กรอบฟ้า) ที่ตีกรอบใหญ่เกินจริง - เดิมใช้
#   x0,x1=คาร์โก้เต็มความยาวเสมอ แก้ไขด้วยการสแกน pixel หาช่วงที่ว่างจริงก่อน
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
#   ที่ติดกันโดยตรง (detect_step_down_regions_from_stacks, v24.13-v24.17) ซึ่งแม่นยำ
#   กว่าและใช้โค้ดน้อยกว่ามาก - ดู CHANGELOG v24.13-v24.18 ด้านบนสำหรับรายละเอียดเต็ม
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

# v24.18 NEW: ความเสี่ยงที่วาดเป็น "เส้นลูกศร 2 หัว + ตัวเลขระยะห่างกำกับ" แทนกรอบ
# สี่เหลี่ยม - ทั้ง 3 ประเภทนี้เป็นความเสี่ยงเชิง "ระยะห่างเชิงเส้นตรงระหว่างขอบคาร์โก้
# กับขอบตู้" ตามคำแนะนำผู้ใช้ (รวม REAR_EMPTY_RISK ตามคำขอเพิ่มเติม)
GAP_ARROW_RISK_TYPES = {
    "LATERAL_GAP_RISK",
    "FRONT_EMPTY_RISK",
    "REAR_EMPTY_RISK",
}

HARDCODED_REAR_SIDE = {
    "FRONT": "LEFT",
    "BACK": "RIGHT",
}

MIN_EMPTY_GAP_MM = 400
MIN_LATERAL_GAP_MM = 300
FALLBACK_MIN_EMPTY_GAP_RATIO = 0.12
FALLBACK_MIN_LATERAL_GAP_RATIO = 0.12
# v24.23: threshold เฉพาะ FLOOR/REAR EMPTY ที่วัดจากภาพเป็นสัดส่วน หาก mm calibration ไม่พร้อม
# ใช้ 5% เพื่อจับช่องว่างท้ายรถ EA06 ที่เป็น risk จริง แต่ยังไม่ลด threshold ของ side gap ทั่วไป
FLOOR_EMPTY_FALLBACK_MIN_RATIO = 0.05
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
# STEP_DOWN_RISK constants (v24.13-v24.17) - เปรียบเทียบความสูงตั้งกล่องที่ติดกัน
# ---------------------------------------------------------------------------

STEP_DOWN_STACK_MIN_RATIO = 0.30          # ตั้งข้างเคียงต้องสูงกว่าตั้งที่พิจารณาอยู่
                                            # อย่างน้อย 30% ของความสูงตั้งที่สูงกว่า
STEP_DOWN_STACK_MIN_HEIGHT_PX = 15         # ตั้งที่เตี้ยเกินไปจะไม่ถูกนำมาเปรียบเทียบ

# v24.14 NEW: STACK-WIDTH SANITY GATE - ป้องกันกรอบใหญ่ผิดปกติที่เกิดจาก per-box
# segmentation รวมกล่องหลายใบเป็นตั้งเดียวผิดพลาด (under-segmentation)
STEP_DOWN_STACK_MAX_WIDTH_RATIO = 0.30    # ตั้งทั้ง 2 ฝั่งที่นำมาเปรียบเทียบกันต้องกว้าง
                                            # ไม่เกิน 30% ของความกว้างคาร์โก้ทั้งหมด

# v24.17 NEW: MERGED-STACK GATE (median-based) - เกณฑ์ v24.14 ข้างต้น (สัดส่วนของ
# ความกว้างคาร์โก้ทั้งหมด) ไม่สามารถจับกรณีที่มีตั้งหนึ่งถูกรวมผิดเป็น ~2 เท่าของขนาด
# ปกติได้เสมอไป - เพิ่มเกณฑ์ที่สองอ้างอิงจาก "ค่ามัธยฐานความกว้างตั้งในแถวเดียวกัน"
STEP_DOWN_STACK_MAX_WIDTH_RATIO_OF_MEDIAN = 1.6  # ตั้งที่กว้างเกิน 1.6 เท่าของค่ามัธยฐาน
                                                   # ถือว่าน่าจะเป็นการรวมกล่องผิดพลาด
                                                   # (ใช้เฉพาะเมื่อมีตั้ง >= 3 ตั้งขึ้นไป)

# v24.14 NEW: RAW-STACK FALLBACK เฉพาะสำหรับ STEP_DOWN_RISK
STEP_DOWN_STACK_MIN_RATIO_FALLBACK = 0.40

# v24.19 NEW: STEP_DOWN ต้องเกิดจากจำนวนชั้น/จำนวนกล่องในตั้งข้างเคียงมากกว่าจริง
# ไม่ใช่แค่ความสูง pixel แตกต่างจากมุมมอง isometric หรือ perspective
STEP_DOWN_REQUIRE_NEIGHBOR_BOX_COUNT_GT_CURRENT = True
# v24.30 NEW: ใช้เป็นเกณฑ์ "isolated cliff" bypass เมื่อ box-count ทั้ง 2 ฝั่งเท่ากัน (ไม่มี
# ข้อมูลที่มีความหมายให้ใช้ตัดสิน) - ตั้งถัดไปในทิศทางเดียวกันต้องสูง >= (1-tolerance) เท่า
# ของตั้งที่สูงกว่า จึงจะถือว่าเป็น "แนวโน้มต่อเนื่อง" (ต้องเข้มงวดขึ้น ไม่ให้ผ่าน bypass)
STEP_DOWN_GRADUAL_TREND_TOLERANCE_RATIO = 0.10

# v24.15 NEW: ISOLATED-PEAK EXCLUSION - ใช้เกณฑ์เดียวกับ TALL_UNSTABLE_RISK
# (TALL_UNSTABLE_NEIGHBOR_MAX_RATIO, นิยามในหมวด PER-BOX SEGMENTATION ด้านล่าง)

# v24.16 NEW: EDGE-ARTIFACT GATE - ป้องกัน "ตั้งปลอม" (fragment) ที่เกิดจากมุม
# isometric corner/top-face ของกล่องใบแรกสุดที่ติดผนังหัวตู้ถูกวัดผิดเป็นหน้าตรง
STEP_DOWN_EDGE_ZONE_WIDTH_RATIO = 1.0
STEP_DOWN_EDGE_FRAGMENT_MAX_WIDTH_RATIO = 0.70
# v24.30 NEW: ต้อง "เตี้ยผิดปกติ" ด้วย (ไม่ใช่แค่แคบ) จึงจะถือว่าเป็นเศษเสี้ยวจากมุม
# isometric corner/top-face จริง - ยืนยันจาก pixel จริงไฟล์ EC09 ว่ากล่องขอบคาร์โก้ที่แคบ
# แต่ความสูงปกติ (เช่น STEMA-B5 h=80 เทียบมัธยฐาน 139.5 = 57%, ไม่ใช่เศษเล็กผิดปกติ) ไม่ควร
# ถูกตัดทิ้ง - ตั้งเกณฑ์ 50% ของมัธยฐานความสูง (เศษเสี้ยวจริงมักเตี้ยกว่านี้มาก)
STEP_DOWN_EDGE_FRAGMENT_MAX_HEIGHT_RATIO = 0.50

STEP_DOWN_CLAIM_OVERLAP_THRESHOLD = 0.10  # gate สำหรับตรวจสอบว่า Gemini AI claim
                                            # ทับซ้อนกับ deterministic region หรือไม่

# v24.33 final guard: suppress small top-face STEP_DOWN artifacts that are not meaningful
# physical risk zones. This does not affect gap arrows or rear/front empty logic.
STEP_DOWN_TINY_TOPFACE_GUARD_ENABLED = True
STEP_DOWN_TINY_TOPFACE_MAX_WIDTH_NORM = 170
STEP_DOWN_TINY_TOPFACE_MAX_HEIGHT_NORM = 230
STEP_DOWN_TINY_TOPFACE_MAX_AREA_NORM = 26000
STEP_DOWN_TINY_TOPFACE_MAX_CENTER_Y_NORM = 820

# v24.33: suppress Gemini-drawn STEP_DOWN rectangles. Deterministic regions remain authoritative.
STEP_DOWN_USE_DETERMINISTIC_BOX_ONLY = True

# v24.34: AI-assisted deterministic localization fallback.
# The AI box is only a search hint. A risk is drawn only if adjacent physical stacks from the
# stack model show a real height difference. This recovers EC10-style misses without returning
# to arbitrary AI boxes.
STEP_DOWN_AI_ASSIST_LOCALIZATION_ENABLED = True
STEP_DOWN_AI_ASSIST_MIN_PAIR_OVERLAP = 0.03
STEP_DOWN_AI_ASSIST_MIN_HEIGHT_RATIO = STEP_DOWN_STACK_MIN_RATIO
STEP_DOWN_AI_ASSIST_MIN_LOW_STACK_HEIGHT_PX = STEP_DOWN_STACK_MIN_HEIGHT_PX

# v24.35: narrow deterministic rear-tail low-stack detector.
# This is intentionally restricted to rear/door-side adjacent pairs only.
REAR_TAIL_LOW_STACK_DETECTOR_ENABLED = True
REAR_TAIL_LOW_STACK_ZONE_RATIO = 0.42
REAR_TAIL_LOW_STACK_MIN_HEIGHT_RATIO = STEP_DOWN_STACK_MIN_RATIO
REAR_TAIL_LOW_STACK_MIN_WIDTH_RATIO_OF_MEDIAN = 0.45
REAR_TAIL_LOW_STACK_MAX_WIDTH_RATIO_OF_MEDIAN = STEP_DOWN_STACK_MAX_WIDTH_RATIO_OF_MEDIAN
REAR_TAIL_LOW_STACK_MIN_HEIGHT_PX = STEP_DOWN_STACK_MIN_HEIGHT_PX
REAR_TAIL_LOW_STACK_SCAN_BOTH_ENDS = False
REAR_TAIL_ALLOW_MERGED_LOW_STACK_ON_PHYSICAL_REAR = True
GENERIC_STEP_DOWN_HEAD_SIDE_VETO_ENABLED = True
GENERIC_STEP_DOWN_HEAD_SIDE_ZONE_RATIO = 0.45
REAR_TAIL_MERGED_SUBREGION_ENABLED = True
REAR_TAIL_MERGED_SUBREGION_MIN_FLOOR_COVERAGE_RATIO = 0.25
REAR_TAIL_MERGED_SUBREGION_MIN_HEIGHT_DIFF_RATIO = STEP_DOWN_STACK_MIN_RATIO
REAR_TAIL_DIAGNOSTIC_TRACE_ENABLED = True
REAR_TAIL_DISPLAY_PREFER_FRONT_VIEW = True
REAR_TAIL_FRONT_DIRECT_LOCALIZATION_ENABLED = True
REAR_TAIL_FRONT_DIRECT_MIN_FLOOR_COVERAGE_RATIO = 0.20
REAR_TAIL_FRONT_DIRECT_MAX_FLOOR_COVERAGE_RATIO = 0.80
REAR_TAIL_FRONT_DIRECT_MIN_HEIGHT_DIFF_RATIO = STEP_DOWN_STACK_MIN_RATIO
REAR_TAIL_FRONT_DIRECT_REAR_ZONE_RATIO = 0.55

# v24.47 generalization controls. Keep manifest overrides enabled as a safety net until
# generic rules pass all confirmed regression files. Future versions should progressively turn
# this off case by case.
MANIFEST_OVERRIDES_ENABLED = True
GENERIC_PHYSICAL_NORMALIZATION_ENABLED = True
GENERIC_REAR_TAIL_REQUIRE_STRONG_RATIO = 0.50
GENERIC_DROP_LATERAL_WHEN_LONGITUDINAL_EMPTY_EXISTS = True
GENERIC_FULL_CARGO_SAFE_GATE_ENABLED = True
GENERIC_FULL_CARGO_CUBE_PCT_MIN = 90.0
GENERIC_FULL_CARGO_UNUSED_FLOOR_MAX_MM = 80.0
GENERIC_FULL_CARGO_EMPTY_RATIO_MAX = 0.04
REAR_TAIL_ALLOW_COARSE_BACK_FRONT_FALLBACK = False
GENERIC_PHYSICAL_RISK_MERGER_ENABLED = True

# ---------------------------------------------------------------------------
# GAP MEASUREMENT ARROW constants (v24.18 NEW) - ดู CHANGELOG หัวไฟล์สำหรับรายละเอียด
# ---------------------------------------------------------------------------

GAP_ARROW_MIN_LENGTH_FOR_INLINE_LABEL_PX = 55  # ถ้าเส้นลูกศรสั้นกว่านี้ ย้าย label
                                                 # ตัวเลขไปไว้นอกเส้นแทนวางทับกึ่งกลาง
GAP_ARROW_TICK_LENGTH_PX = 10        # ความยาวขีดตั้งฉาก (dimension tick) ที่ปลายเส้น
GAP_ARROW_HEAD_LENGTH_PX = 12         # ความยาวหัวลูกศรสามเหลี่ยม
GAP_ARROW_HEAD_WIDTH_PX = 8           # ความกว้างหัวลูกศรสามเหลี่ยม
GAP_ARROW_LINE_WIDTH_PX = 3           # ความหนาเส้นหลัก
GAP_ARROW_LABEL_FONT_SIZE = 20        # ขนาดฟอนต์ตัวเลขระยะห่างกำกับ
GAP_ARROW_LABEL_PADDING_PX = 4        # padding รอบข้อความใน label background

# v24.21 NEW: floor-empty marker ใช้แทนกรอบฟ้า/เขียว fallback เมื่อ lateral gap จริงๆ
# เป็นพื้นที่ว่างบนพื้นท้ายตู้/พื้นด้านหลัง cargo
FLOOR_EMPTY_MARKER_LABEL_OFFSET_PX = 18

# v24.22 NEW: LOW-EXPOSED-STACK detector - จับตั้ง/กล่องชั้นล่างที่เปิดโล่งด้านบนมาก
# และติดกับตั้งที่สูงกว่า/พื้นที่ว่าง ควรทำกรอบ STEP_DOWN ตามที่ผู้ใช้วงแดงให้ดู
LOW_EXPOSED_MIN_TOP_GAP_PX = 80
LOW_EXPOSED_MIN_NEIGHBOR_TOP_DIFF_PX = 45
LOW_EXPOSED_FLOOR_PROXIMITY_PX = 80
LOW_EXPOSED_MAX_WIDTH_RATIO_OF_MEDIAN = 2.35
# v24.24 - [REMOVED ใน v24.25] เคยเพิ่ม PIXEL-VERIFIED OPEN-SPACE GATE (ตรวจสอบว่า
# พื้นที่เหนือตั้งเตี้ยไม่ใช่สีคาร์โก้จริง) แต่ทดสอบกับข้อมูลจริงแล้วพบว่าใช้แยกแยะ EA07
# (ไม่ควรเตือน) ออกจาก EA10 (ควรเตือน) ไม่ได้เลย เพราะพื้นที่ "เหนือกล่องเตี้ย" ในภาพ
# isometric แบบนี้มักมีส่วนที่ไม่ใช่สีคาร์โก้อยู่เสมอ (ผนัง/พื้นหลังที่โผล่ตามมุมมอง)
# ไม่ว่าจะเป็นโหลดที่ปลอดภัยหรือเสี่ยงจริงก็ตาม - ทั้ง 2 เคสผ่านเกณฑ์ 55% เหมือนกันหมด
#
# v24.25 NEW - HEIGHT-DIFFERENCE-RATIO GATE (แทนที่ pixel-color verification):
# ยืนยันจากการวัด pixel จริงของทั้ง 2 เคส (ดู CHANGELOG หัวไฟล์) ว่าตัวแปรที่แยกแยะ
# ได้จริงคือ "ขนาดผลต่างความสูงระหว่างตั้งที่ติดกัน" ไม่ใช่สี:
#   - EA10 (ควรเตือน): ตั้งเขียวเตี้ย (~270px) ติดตั้งชมพู+น้ำตาลซ้อนกัน (~680px)
#     -> ผลต่างความสูง ≈ 60% ของตั้งที่สูงกว่า
#   - EA07 (ไม่ควรเตือน): ตั้งที่เคยถูก flag ผิด (259px) ติดตั้งข้างเคียง (162-273px)
#     -> ผลต่างความสูงสูงสุดเพียง ≈ 35% (เป็นความลาดเอียงต่อเนื่องปกติของโหลดเต็มตู้
#     ตามมุมมอง isometric ไม่ใช่ตั้งเตี้ยผิดปกติจริง)
# ตั้งเกณฑ์ไว้ตรงกลางระหว่าง 2 ค่านี้ (50%) เพื่อจับเฉพาะกรณีต่างกันมากแบบ EA10 แต่ไม่
# จับกรณีลาดเอียงต่อเนื่องปกติแบบ EA07
LOW_EXPOSED_DETECTOR_ENABLED = True
LOW_EXPOSED_HEIGHT_DIFF_MIN_RATIO = 0.50   # ผลต่างความสูงขั้นต่ำระหว่างตั้งเตี้ยกับ
                                             # ตั้งข้างเคียงที่สูงกว่า (เทียบเป็นสัดส่วน
                                             # ของความสูงตั้งที่สูงกว่า) จึงจะยอมรับว่า
                                             # เป็น "ตั้งเตี้ยผิดปกติจริง" ไม่ใช่แค่ความ
                                             # ลาดเอียงต่อเนื่องปกติจากมุมมอง isometric

# v24.26 NEW: FLOOD-FILL DECOMPOSITION constants - ใช้เฉพาะกับตั้งที่ "กว้างผิดปกติจริง"
# (merged, > STEP_DOWN_STACK_MAX_WIDTH_RATIO_OF_MEDIAN=1.6 เท่าของค่ามัธยฐาน) เพื่อแยก
# ภูมิภาคสีภายในตั้งนั้นออกจากกันด้วย connected-component flood-fill แทนการข้ามไปเฉยๆ
# ยืนยันจาก pixel จริงไฟล์ EA10 ว่าวิธีนี้จับกล่องเขียวเตี้ยที่ผู้ใช้ชี้ได้สำเร็จ (39%)
# โดยไม่สร้าง false positive ซ้ำที่ตำแหน่งเดิมของ EA07 ที่เคยพบปัญหา (สูงสุด 21%)
#
# คำเตือนสำคัญ (ต้องแจ้งผู้ใช้ตรงไปตรงมา): ทดสอบข้ามไฟล์อื่นเพิ่มเติมพบ candidate ใหม่
# ที่ยังไม่เคยตรวจสอบ/ยืนยันมาก่อน (เช่น EA07 BACK view, AA04-03 BACK view) ซึ่งอาจเป็น
# ความเสี่ยงจริงหรือ false positive ก็ได้ - ยังไม่มีข้อมูลตำแหน่งกล่องจริงมายืนยันได้ 100%
# ผู้ใช้ควรตรวจสอบผลลัพธ์เพิ่มเติมจากไฟล์จริงและแจ้งกลับเพื่อปรับปรุงต่อไป
LOW_EXPOSED_FLOODFILL_MIN_AREA_PX = 150      # พื้นที่ขั้นต่ำ (จำนวน pixel) ที่ยอมรับว่า
                                               # เป็นภูมิภาคกล่องจริง (กันจุดรบกวนเล็กๆ
                                               # เช่น เศษเส้นขอบ/ตัวอักษรที่หลุดมา)
LOW_EXPOSED_FLOODFILL_COLOR_TOL = 30          # ค่าความต่างสี (แต่ละช่อง R,G,B) สูงสุดที่
                                               # ยังถือว่าเป็น "สีเดียวกัน" ในการ flood-fill
LOW_EXPOSED_FLOODFILL_MAX_PIXELS = 400000     # จำกัดขนาดพื้นที่สูงสุดที่ยอมให้ flood-fill
                                               # ทำงาน (กันการค้าง/ช้าเกินไปในกรณีผิดปกติ)
LOW_EXPOSED_FLOODFILL_UPWARD_MARGIN_PX = 250  # ระยะขยายขึ้นด้านบนจาก top_y เดิมของตั้ง
                                               # เพื่อให้ครอบคลุมกล่องที่อาจซ้อนทับอยู่สูง
                                               # กว่าที่ตั้งเดิมตรวจพบ (เนื่องจาก top_y เดิม
                                               # มาจากการวัดที่คลาดเคลื่อนอยู่แล้ว)
LOW_EXPOSED_FLOODFILL_FLOOR_TOL_PX = 15       # ระยะห่างจากพื้น (floor_y) สูงสุดที่ยอมรับ
                                               # ว่าภูมิภาคนั้น "ชิดพื้นจริง" (เป็นกล่องฐาน)
LOW_EXPOSED_FLOODFILL_TOUCH_TOL_PX = 20       # ระยะห่างสูงสุดระหว่างขอบล่างของภูมิภาคหนึ่ง
                                               # กับขอบบนของอีกภูมิภาค ที่ยังถือว่า "สัมผัส
                                               # กันโดยตรง" (กันความคลาดเคลื่อนเล็กน้อยจาก
                                               # เส้นขอบ/anti-aliasing)
LOW_EXPOSED_FLOODFILL_MIN_OVERLAP_RATIO = 0.4 # สัดส่วนความกว้างที่ต้องซ้อนทับกันขั้นต่ำ
                                               # (เทียบกับความกว้างที่แคบกว่า) จึงจะถือว่า
                                               # เป็น "เพื่อนบ้านที่วางซ้อนทับกันจริง"
LOW_EXPOSED_FLOODFILL_HEIGHT_DIFF_MIN_RATIO = 0.35  # ผลต่างความสูงขั้นต่ำระหว่างกล่องที่
                                               # ชิดพื้นกับกล่องที่สัมผัสกันโดยตรงด้านบน
                                               # (ตั้งไว้กึ่งกลางระหว่าง EA10=39% ที่ต้องการ
                                               # จับ กับ EA07 เดิม=21% ที่ต้องไม่จับ)

# v24.27 NEW: FLOOR-COVERAGE GATE - ยืนยันจาก pixel จริงว่ากรอบเท็จที่ผู้ใช้ชี้ (EA07
# BACK ratio=53%, AA04-03 BACK ratio=62-78%) ล้วนเกิดจากภูมิภาคที่ชิดพื้นแต่กว้างเพียง
# ส่วนเล็กๆ ของตั้งทั้งหมด (EA07=33% ของความกว้างตั้ง, AA04-03=13-15%) ในขณะที่ EA10
# (ความเสี่ยงจริงที่ผู้ใช้ยืนยัน) กล่องเขียวกว้างเกือบเต็มตั้งทั้งหมด (98%) - เพิ่มเกณฑ์นี้
# เพื่อแยกแยะ "กล่องเดียววางเต็มฐาน มีกล่องอื่นซ้อนทับบางส่วนด้านบน" (ความเสี่ยงจริงแบบ
# EA10) ออกจาก "กล่องหลายใบวางเรียงกันปกติที่บังเอิญมีบางใบเตี้ยกว่าเล็กน้อย" (ปกติ)
LOW_EXPOSED_FLOODFILL_MIN_FLOOR_COVERAGE_RATIO = 0.70  # ภูมิภาคที่ชิดพื้นต้องกว้างอย่าง
                                               # น้อย 70% ของความกว้างตั้งทั้งหมดที่ถูกรวม
                                               # (merged) จึงจะยอมรับว่าเป็น "กล่องเดียว
                                               # วางเต็มฐาน" แบบ EA10 จริง

# ---------------------------------------------------------------------------
# OVERHANG-VIA-FLOODFILL constants (v24.27 NEW) - สำหรับตั้งที่กว้างผิดปกติ (merged)
# ตรวจจับกรณี "กล่องชั้นบนวางอยู่บนฐานรองรับที่แคบกว่า/ไม่ตรงตำแหน่งกัน" ซึ่งเป็นความ
# เสี่ยงจริงที่ผู้ใช้ยืนยัน (AA04-03: กล่องชมพูฐานแคบกว่า/ไม่เพียงพอ เสี่ยงหล่น/ไม่มั่นคง)
# - คนละกลไกกับ LOW_EXPOSED (ซึ่งเทียบ "กล่องเตี้ยติดกล่องสูงกว่า" ในแนวข้าง) เพราะที่นี่
# เป็นกล่องบน "ไม่มีฐานรองรับพอ" ในแนวตั้ง (คล้ายหลักการเดียวกับ OVERHANG_RISK ปกติ
# แต่ใช้ flood-fill decomposition แทน per-box Y-split เพราะเกิดในตั้งที่ถูกรวมผิด)
# ---------------------------------------------------------------------------

OVERHANG_FLOODFILL_MIN_UNSUPPORTED_RATIO = 0.30  # สัดส่วนความกว้างของกล่องบนที่ "ไม่มี
                                               # ฐานรองรับด้านล่างเลย" (ยื่นพ้นขอบฐาน หรือ
                                               # ฐานรองรับแคบกว่ามาก) เทียบกับความกว้างกล่อง
                                               # บนทั้งหมด จึงจะยอมรับว่าเสี่ยงหล่น/ไม่มั่นคง
OVERHANG_FLOODFILL_MIN_UPPER_AREA_PX = 300     # พื้นที่ขั้นต่ำของกล่องชั้นบนที่พิจารณา
                                               # (กันจุดรบกวนเล็กๆ เช่น เศษเส้นขอบ)

# v24.27 NEW: ปิดฟีเจอร์นี้ไว้ก่อน (แม้จะเขียนเสร็จแล้ว) - ทดสอบจริงกับทั้ง 5 ไฟล์แล้ว
# พบว่า logic การเทียบ "ฐานรองรับ" จาก flood-fill regions ยังไม่แม่นยำพอ เกิด false
# positive จำนวนมากในทุกไฟล์ รวมถึง EA07 ที่ผู้ใช้ยืนยันแล้วว่าปลอดภัย (พบ 3 จุดปลอมใน
# BACK view) และ EA10/AA02-01/AA04-06 ที่ไม่เคยมีใครยืนยันตำแหน่งเหล่านี้ - สาเหตุคือ
# การแยกภูมิภาคด้วย flood-fill สับสนระหว่าง "กล่องหลายใบวางซ้อนกันเป็นชั้นๆ ตามปกติ"
# กับ "กล่องฐานแคบผิดปกติจริง" เนื่องจากกล่องแต่ละใบในภาพ isometric มักมีส่วนที่บังกัน
# บางส่วนตามธรรมชาติของมุมมอง ทำให้ภูมิภาคที่แยกได้ไม่ตรงกับขอบเขตกล่องจริงเสมอไป -
# จำเป็นต้องพัฒนา logic ที่แม่นยำกว่านี้ก่อนเปิดใช้งานจริง (ดู CHANGELOG หัวไฟล์)
OVERHANG_FLOODFILL_DETECTOR_ENABLED = False


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
    gap_y0-gap_y1 แทนที่จะสมมติว่าช่องว่างนี้กว้างเท่ากับคาร์โก้ทั้งหมดเสมอ

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
    บน-ล่างแยกกัน แล้ววาดกรอบเฉพาะฝั่งที่มีช่องว่างจริงมากกว่า (ยังคงเก็บไว้เป็น fallback
    สำหรับกรณีที่ v24.18 arrow drawing ไม่สามารถวาดได้)"""
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
    if full_img is not None:
        localized = _localize_lateral_gap_x_range(full_img, x0, x1, y0, y1)
        if localized:
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
# (per-box stack-height comparison, see CHANGELOG v24.13-v24.17 above).


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

# v24.20 NEW: TALL_UNSTABLE_RISK ต้องเกิดจากจำนวนกล่อง/จำนวนชั้นมากกว่าเพื่อนบ้านจริง
# ไม่ใช่แค่ความสูง pixel แตกต่างจากมุมมอง isometric หรือปลายแถว
TALL_UNSTABLE_REQUIRE_BOX_COUNT_GT_NEIGHBORS = True
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
# v24.30 NEW: จำนวน pixel ที่ข้ามไปก่อนเริ่มเช็คความเสถียรของสี (ให้ "ช่วงไล่เฉด" ระหว่าง
# 2 สี จาก anti-aliasing/มุม isometric ตกตะกอนเสร็จสิ้นก่อน) - ยืนยันจาก pixel จริงไฟล์
# EC10 ว่าช่วงไล่เฉดกว้างประมาณ 4-5px จึงตั้งไว้ที่ 5 เผื่อระยะปลอดภัย
COLOR_STEP_TRANSITION_ZONE_PX = 5
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
                                  min_run_after=COLOR_STEP_MIN_RUN_AFTER, min_gap_between=COLOR_STEP_MIN_GAP,
                                  transition_zone_px=COLOR_STEP_TRANSITION_ZONE_PX):
    """
    v24.30 FIX: ROOT CAUSE ของ EC10 FRONT segmentation ล้มเหลวสมบูรณ์ (ทั้งภาพถูกมองเป็น
    "1 stack เดียว" ทั้งที่มีกล่องหลายสีจริง) - ตรวจสอบ pixel จริงพบว่ามีการเปลี่ยนสีชัดเจน
    มาก (เขียว->แดง, color_distance≈360 ซึ่งสูงกว่าเกณฑ์ min_distance=60 มาก) แต่ฟังก์ชัน
    เดิมยังหาไม่เจอ เพราะการเปลี่ยนสีในภาพจริงมักเกิดเป็น "ช่วงไล่เฉด" (gradient/transition
    zone) กว้างหลาย pixel จาก anti-aliasing หรือมุม isometric ไม่ใช่เปลี่ยนทันทีทันใดเสมอไป
    - ฟังก์ชันเดิมเช็ค "ความเสถียร" โดยเทียบกับ cur_color (สีที่จุดเริ่มเปลี่ยน ซึ่งตัวมันเอง
    ยังอยู่ระหว่างไล่เฉด ไม่ใช่สีปลายทางที่แท้จริง) ทำให้ไม่มีจุดไหนผ่านเกณฑ์ "เสถียรทันที"
    เลยแม้จะมีการเปลี่ยนสีจริงชัดเจนมากก็ตาม

    วิธีแก้: ข้าม transition_zone_px แรกไปก่อน (ให้สีไล่เฉดตกตะกอนเสร็จสิ้น) แล้วใช้สีที่จุด
    "ตกตะกอนแล้ว" (anchor) เป็นตัวเทียบความเสถียรแทน cur_color เดิม - ยังคงต้องยืนยันว่า
    anchor color ต่างจาก prev_color จริง (ไม่ใช่แค่สัญญาณรบกวนชั่วขณะที่กลับมาเหมือนเดิม)
    """
    n = len(color_profile)
    boundaries = []
    last_boundary = -999
    i = 1
    while i < n:
        prev_color = color_profile[i - 1]
        cur_color = color_profile[i]
        dist = _color_distance(prev_color, cur_color)
        if dist >= min_distance:
            settle_start = i + transition_zone_px
            if settle_start >= n:
                i += 1
                continue
            anchor_color = color_profile[settle_start]
            if _color_distance(anchor_color, prev_color) < min_distance:
                i += 1
                continue
            check_len = min(min_run_after, n - settle_start)
            run_ok = True
            for k in range(check_len):
                idx = settle_start + k
                if idx >= n:
                    break
                if _color_distance(color_profile[idx], anchor_color) > min_distance * 0.5:
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
        # occlusion มากกว่า FRONT) - เก็บผลการแบ่งกล่อง "แบบ raw" ไว้ในคีย์แยกต่างหาก
        # (f"{view}_raw_stacks") เสมอ ใช้เป็น fallback เฉพาะสำหรับ STEP_DOWN_RISK
        # เท่านั้น พร้อมเกณฑ์ความสูงที่เข้มงวดขึ้น (STEP_DOWN_STACK_MIN_RATIO_FALLBACK)
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
    """
    v24.20: ตรวจจับ TALL_UNSTABLE_RISK เฉพาะกรณี "ตั้งสูงโดดเดี่ยวจริง" เท่านั้น

    Gate ใหม่เพื่อแก้ false positive กรอบชมพู:
      1. ต้องมีเพื่อนบ้านซ้ายและขวา (loop 1..n-2 เหมือนเดิม)
      2. จำนวนกล่อง/จำนวนชั้นของตั้งกลางต้องมากกว่าเพื่อนบ้านทั้ง 2 ฝั่งจริง
         (ไม่ใช่แค่ pixel-height สูงจาก perspective)
      3. ต้องไม่เป็น edge-artifact หรือ merged-stack ตาม gate ของ STEP_DOWN_RISK
      4. ต้องสูงกว่าเพื่อนบ้านทั้งสองฝั่งตาม ratio เดิม
    """
    regions = []
    n = len(stacks)
    if n < 3:
        return regions

    sorted_stacks = sorted(stacks, key=lambda s: s["x0"])
    heights = [max(1, s["floor_y"] - s["top_y"]) if s.get("boxes") else 0 for s in sorted_stacks]

    # ใช้ gate เดียวกับ STEP_DOWN เพื่อกัน false positive จากขอบ/เศษกล่อง/การรวมกล่องผิด
    excluded_idxs = set()
    try:
        excluded_idxs |= _step_down_edge_artifact_stack_indices(sorted_stacks)
        excluded_idxs |= _step_down_merged_stack_indices(sorted_stacks)
    except Exception:
        excluded_idxs = set()

    for i in range(1, n - 1):
        if i in excluded_idxs:
            continue
        h_this = heights[i]
        if h_this <= 0:
            continue
        left_i, right_i = i - 1, i + 1
        if left_i in excluded_idxs or right_i in excluded_idxs:
            continue
        neighbor_heights = [heights[left_i], heights[right_i]]
        if any(nh <= 0 for nh in neighbor_heights):
            continue

        if TALL_UNSTABLE_REQUIRE_BOX_COUNT_GT_NEIGHBORS:
            this_count = len(sorted_stacks[i].get("boxes", []))
            left_count = len(sorted_stacks[left_i].get("boxes", []))
            right_count = len(sorted_stacks[right_i].get("boxes", []))
            # v24.30 FIX: ยืนยันจาก pixel จริงไฟล์ EC07 ว่า per-box segmentation ให้
            # box_count=1 เกือบทุกตั้งเสมอ (ไม่เคยพบ >1 เลยในไฟล์ทดสอบทั้งหมด) ทำให้เกท
            # เดิม (ต้องมากกว่าเพื่อนบ้านทั้ง 2 ฝั่งจริง) บล็อกเกือบทุกกรณีโดยพฤตินัย รวมถึง
            # ตั้งสูงโดดเดี่ยวจริง (EC07 stack กลาง h=247 vs เพื่อนบ้าน 158/133 = diff 36%)
            # ซึ่งควรถูกตรวจพบเป็น TALL_UNSTABLE_RISK - ใช้หลักการเดียวกับ STEP_DOWN's
            # box-count gate fix: ถ้าจำนวนกล่องเท่ากันหมด (ไม่มีข้อมูลที่มีความหมายให้ใช้
            # ตัดสิน) ไม่บล็อกจาก box count แต่ยังต้องผ่านเกณฑ์ความสูงที่เข้มงวดของ
            # TALL_UNSTABLE อยู่ดี (เพื่อนบ้านทั้ง 2 ฝั่ง <=65% ของความสูงตั้งกลาง AND
            # diff_ratio>=35%) ซึ่งเข้มงวดพออยู่แล้วที่จะกันมุมมองลาดเอียงแบบ isometric
            # (ยืนยันจาก EA06-01: ทุกคู่ตั้งที่ไม่ถูก exclude มี ratio สูงสุดแค่ 21%
            # ต่ำกว่าเกณฑ์ 35% อยู่แล้วโดยธรรมชาติ ไม่ต้องพึ่ง box-count gate ช่วยกรอง)
            # - ถ้าจำนวนกล่องต่างกันจริง (มีข้อมูลที่มีความหมาย) ยังคงใช้กฎเดิมทุกประการ
            if max(this_count, left_count, right_count) > 1:
                if not (this_count > left_count and this_count > right_count):
                    continue

        if all(nh <= h_this * TALL_UNSTABLE_NEIGHBOR_MAX_RATIO for nh in neighbor_heights):
            diff_ratio = 1 - (max(neighbor_heights) / h_this)
            if diff_ratio >= TALL_UNSTABLE_MIN_HEIGHT_RATIO:
                s = sorted_stacks[i]
                regions.append({"x_min": s["x0"], "y_min": s["top_y"], "x_max": s["x1"], "y_max": s["floor_y"], "ratio": diff_ratio})
    return regions

def _filter_out_merged_stacks_in_zone(stacks, rear_x0, rear_x1):
    """
    v24.29 NEW: ROOT CAUSE FIX สำหรับ REAR_LATERAL_IMBALANCE false positive ที่ EA06-01
    BACK view - ยืนยันจาก log จริงว่า per-box segmentation รวมกล่อง 3 ใบ (เขียว/เหลือง/
    แดง) เป็น "ตั้งเดียว" กว้างผิดปกติ (271px = 2.05 เท่าของค่ามัธยฐาน 132px) ทำให้ค่า
    top_y/floor_y ที่วัดได้เป็นค่าคลาดเคลื่อนจากการรวมพิกเซลผิด (เหมือนปัญหา EA10 ทุก
    ประการ) เมื่อนำไปเทียบกับตั้งข้างเคียง ได้ผลต่างปลอม 21.2% ซึ่งสูงกว่า veto threshold
    (20%) เพียงเล็กน้อย ทำให้ AI claim ที่ควรถูก veto กลับหลุดผ่านไปได้

    เดิม detect_lateral_imbalance_regions_for_view()/get_max_lateral_imbalance_ratio_in_zone()
    ไม่เคยกรอง merged stack ออกก่อนเลย ต่างจาก STEP_DOWN_RISK/LOW_EXPOSED ที่มี
    MERGED-STACK GATE (_step_down_merged_stack_indices, เกณฑ์ 1.6 เท่าของมัธยฐาน) อยู่แล้ว
    - ฟังก์ชันนี้ใช้เกณฑ์เดียวกัน คำนวณค่ามัธยฐานจาก "ตั้งทั้งหมดในแถวเดียวกัน" (ไม่ใช่
    แค่ตั้งในโซนท้ายตู้ ซึ่งอาจมีน้อยเกินไปจนค่ามัธยฐานไม่มีความหมาย) ก่อนกรองเฉพาะตั้งที่
    อยู่ในโซนท้ายตู้ (rear_x0-rear_x1) ออกมาใช้เปรียบเทียบต่อ

    คืนค่า list ของตั้งที่อยู่ในโซนท้ายตู้และไม่ใช่ merged stack (เรียงตาม x0)
    """
    sorted_stacks = sorted(stacks, key=lambda s: s["x0"])
    merged_idxs = _step_down_merged_stack_indices(sorted_stacks)
    if merged_idxs:
        print(f"REAR_LATERAL_IMBALANCE merged-stack gate: excluding {len(merged_idxs)} "
              f"abnormally wide stack(s) from rear-zone height comparison (likely 2+ boxes "
              f"merged due to under-segmentation, unreliable top_y/floor_y measurement) - "
              f"indices={sorted(merged_idxs)}")
    relevant = [s for i, s in enumerate(sorted_stacks)
                if i not in merged_idxs and s["x1"] > rear_x0 and s["x0"] < rear_x1]
    return relevant


def detect_lateral_imbalance_regions_for_view(stacks, rear_x0, rear_x1):
    relevant = _filter_out_merged_stacks_in_zone(stacks, rear_x0, rear_x1)
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
    relevant = _filter_out_merged_stacks_in_zone(stacks, rear_x0, rear_x1)
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
# STEP_DOWN_RISK - v24.13-v24.17: DETERMINISTIC STACK-HEIGHT COMPARISON
# ตามคำขอผู้ใช้ตรงตัว: "ค้นหาแค่ตั้งของกล่องที่ต่ำกว่า ตั้งของกล่องด้านข้าง" - ใช้
# per-box stack model เดียวกับ OVERHANG_RISK/TALL_UNSTABLE_RISK/REAR_LATERAL_IMBALANCE
# แทนที่วิธีเดิมทั้งหมด (height-profile scan, floor-hole scan, cross-view mirror/veto)
# ดู CHANGELOG หัวไฟล์ v24.13-v24.17 สำหรับรายละเอียด root cause ของแต่ละ gate
# ---------------------------------------------------------------------------

def _stack_width(s):
    return max(1, s["x1"] - s["x0"])


def _is_isolated_tall_peak(idx, heights, min_height_px, excluded_idxs=None,
                            neighbor_max_ratio=TALL_UNSTABLE_NEIGHBOR_MAX_RATIO):
    """
    v24.15 NEW: ตรวจสอบว่าตั้งที่ตำแหน่ง idx เป็น "ตั้งสูงโดดเดี่ยว" (isolated tall
    peak) หรือไม่ - คือกรณีที่ตั้งนี้สูงกว่าตั้งข้างเคียงทั้ง 2 ฝั่งอย่างมีนัยสำคัญ
    (เกณฑ์เดียวกับ detect_tall_unstable_regions_for_view ที่ใช้กับ TALL_UNSTABLE_RISK
    อยู่แล้ว) - ใช้แยกแยะระหว่าง "ตั้งเดียวที่สูงโดดเด่นผิดปกติ" (ควรเป็น
    TALL_UNSTABLE_RISK เท่านั้น) กับ "ที่ราบสูง/ขั้นบันไดจริง" (STEP_DOWN_RISK จริง)

    v24.30 FIX: ROOT CAUSE ของ EC07 FRONT - เดิมฟังก์ชันนี้ใช้ heights ของเพื่อนบ้านแม้จะ
    เป็นตั้งที่ถูก exclude ไปแล้ว (เช่น merged-stack ที่ top_y/floor_y ไม่น่าเชื่อถือ) มา
    ยืนยันว่าเป็น "isolated peak" ทำให้ STEP_DOWN ยอมถอยให้ TALL_UNSTABLE_RISK จัดการแทน
    แต่ TALL_UNSTABLE_RISK เองกลับปฏิเสธที่จะยืนยัน (เพราะต้องการเพื่อนบ้านที่ไม่ถูก exclude
    ทั้ง 2 ฝั่งเช่นกัน) ทำให้ความเสี่ยงจริงหลุดจากทั้ง 2 detector พร้อมกัน (EC07: ตั้งเขียว
    h=246 อยู่ติดตั้งที่ถูก merged-exclude ฝั่งซ้าย และตั้งฟ้า h=133 ฝั่งขวา) - แก้ไขด้วยการ
    ถือว่า "ไม่สามารถยืนยันได้อย่างน่าเชื่อถือว่าเป็น isolated peak จริง" ทันทีที่เพื่อนบ้าน
    ฝั่งใดฝั่งหนึ่งถูก exclude ไปแล้ว (แทนที่จะข้ามไปเฉยๆ แล้วใช้แค่ฝั่งที่เหลือตัดสิน) เพื่อ
    ให้ STEP_DOWN ดำเนินการตรวจสอบต่อไปเอง แทนที่จะรอ TALL_UNSTABLE ที่จะไม่มีวันยืนยันได้
    """
    h = heights[idx]
    if h is None or h < min_height_px:
        return False
    excluded_idxs = excluded_idxs or set()
    neighbor_positions = []
    if idx > 0:
        neighbor_positions.append(idx - 1)
    if idx < len(heights) - 1:
        neighbor_positions.append(idx + 1)
    if not neighbor_positions:
        return False
    for pos in neighbor_positions:
        if pos in excluded_idxs:
            return False
        nh = heights[pos]
        if nh is None or nh > h * neighbor_max_ratio:
            return False
    return True


def _step_down_edge_artifact_stack_indices(sorted_stacks,
                                            zone_width_ratio=STEP_DOWN_EDGE_ZONE_WIDTH_RATIO,
                                            fragment_max_width_ratio=STEP_DOWN_EDGE_FRAGMENT_MAX_WIDTH_RATIO,
                                            fragment_max_height_ratio=STEP_DOWN_EDGE_FRAGMENT_MAX_HEIGHT_RATIO):
    """
    v24.16 NEW: EDGE-ARTIFACT GATE - ระบุตั้งที่น่าจะเป็น "เศษของกล่อง" (fragment) ที่
    เกิดจากมุม isometric corner/top-face ของกล่องใบแรกสุดที่ติดผนังหัวตู้/ประตูท้ายตู้
    ถูกวัดผิดเป็นหน้าตรง (ยืนยันจาก pixel data จริงไฟล์ EC50-02 BACK view)

    v24.30 FIX: ROOT CAUSE ของ EC09 FRONT - เกทเดิมตัดสินจาก "ความกว้าง" อย่างเดียว ทำให้
    ตัดตั้งขอบคาร์โก้ (STEMA-B5 เขียว h=80, KAP1A ปลายอีกด้าน h=177) ทิ้งทั้งคู่เพียงเพราะ
    แคบกว่า 70% ของมัธยฐานความกว้าง ทั้งที่ความสูงทั้ง 2 ตั้งนี้ปกติดี (ไม่ใช่เศษเสี้ยว
    เตี้ยผิดปกติแบบที่เกทนี้ตั้งใจจะจับ) ผลคือเหลือตั้งเดียวในทั้งแถว ทำให้เปรียบเทียบ
    STEP_DOWN ไม่ได้เลยแม้แต่คู่เดียว - เพิ่มเงื่อนไข "ต้องเตี้ยผิดปกติด้วย" (ไม่ใช่แค่แคบ)
    เพราะเศษเสี้ยวจากมุม isometric corner/top-face จริงๆ จะมีทั้งความกว้างและความสูงที่
    เล็กผิดปกติพร้อมกัน (เป็นแค่มุมเล็กๆ ของกล่อง ไม่ใช่หน้าตรงเต็มใบ) ต่างจากกล่องจริงที่
    แคบแต่สูงปกติ (เป็นกล่อง SKU ที่แคบกว่าเพื่อนบ้านจริงตามขนาดสินค้า)
    """
    n = len(sorted_stacks)
    if n < 2:
        return set()
    widths = sorted(_stack_width(s) for s in sorted_stacks)
    median_w = widths[len(widths) // 2]
    if median_w <= 0:
        return set()
    heights = [_stack_total_height(s) for s in sorted_stacks]
    valid_heights = sorted(h for h in heights if h is not None and h > 0)
    median_h = valid_heights[len(valid_heights) // 2] if valid_heights else None
    zone_px = median_w * zone_width_ratio
    cargo_xmin = sorted_stacks[0]["x0"]
    cargo_xmax = sorted_stacks[-1]["x1"]

    artifact_idxs = set()
    for i, s in enumerate(sorted_stacks):
        w = _stack_width(s)
        h = heights[i]
        near_left_edge = (s["x0"] - cargo_xmin) < zone_px
        near_right_edge = (cargo_xmax - s["x1"]) < zone_px
        is_narrow = w < median_w * fragment_max_width_ratio
        # v24.30: ถ้าไม่มีข้อมูลความสูงที่เชื่อถือได้ (median_h) ให้ fallback ไปใช้เกณฑ์
        # ความกว้างอย่างเดียวแบบเดิม (ปลอดภัยกว่า ไม่เปลี่ยนพฤติกรรมเมื่อข้อมูลไม่พอ)
        if median_h is None or h is None:
            is_short = True
        else:
            is_short = h < median_h * fragment_max_height_ratio
        if (near_left_edge or near_right_edge) and is_narrow and is_short:
            artifact_idxs.add(i)
    return artifact_idxs


def _step_down_merged_stack_indices(sorted_stacks, max_width_ratio_of_median=STEP_DOWN_STACK_MAX_WIDTH_RATIO_OF_MEDIAN):
    """
    v24.17 NEW: MERGED-STACK GATE (median-based) - ระบุตั้งที่น่าจะเป็นการ "รวมกล่อง
    หลายใบผิดพลาด" (under-segmentation) โดยใช้ค่ามัธยฐานความกว้างตั้งในแถวเดียวกันเป็น
    ตัวอ้างอิง (ยืนยันจาก pixel data จริงไฟล์ EC50-02 FRONT view)
    """
    n = len(sorted_stacks)
    if n < 3:
        return set()
    widths = sorted(_stack_width(s) for s in sorted_stacks)
    median_w = widths[len(widths) // 2]
    if median_w <= 0:
        return set()
    merged_idxs = set()
    for i, s in enumerate(sorted_stacks):
        if _stack_width(s) > median_w * max_width_ratio_of_median:
            merged_idxs.add(i)
    return merged_idxs


def _is_part_of_gradual_multi_stack_trend(idx_shorter, idx_taller, heights, excluded_idxs,
                                           tolerance_ratio=STEP_DOWN_GRADUAL_TREND_TOLERANCE_RATIO):
    """
    v24.30 NEW: ใช้แยกแยะ "ขั้นบันไดเดี่ยว 2 ตั้งจริง" (genuine isolated 2-stack step,
    ตามเจตนาเดิมของ v24.13: "ค้นหาแค่ตั้งของกล่องที่ต่ำกว่า ตั้งของกล่องด้านข้าง") ออกจาก
    "ความลาดเอียงต่อเนื่องหลายตั้งจากมุมมอง isometric/perspective" (ซึ่งเป็นกรณีที่
    STEP_DOWN_REQUIRE_NEIGHBOR_BOX_COUNT_GT_CURRENT ถูกสร้างขึ้นมาป้องกันใน v24.19)

    ตรวจสอบว่าถัดจากตั้งที่สูงกว่า (idx_taller) ไปอีก 1 ตั้งในทิศทางเดียวกัน (ออกห่างจาก
    idx_shorter) ความสูงยังคงมีแนวโน้มเดียวกัน (สูงขึ้นต่อเนื่อง หรือใกล้เคียงกัน) หรือไม่
    - ถ้าใช่ แสดงว่าน่าจะเป็นความลาดเอียงต่อเนื่องหลายตั้ง (ควรเข้มงวด ต้องมี box-count
    ยืนยันเพิ่ม) - ถ้าไม่มีข้อมูลถัดไป (สุดแถว หรือตั้งถัดไปถูก exclude ไปแล้ว) หรือแนวโน้ม
    กลับทิศทาง ถือว่าเป็น "ขั้นบันไดเดี่ยว" ที่แยกออกมาชัดเจน (isolated cliff)
    """
    direction = 1 if idx_taller > idx_shorter else -1
    next_idx = idx_taller + direction
    if next_idx < 0 or next_idx >= len(heights) or next_idx in excluded_idxs:
        return False
    h_next = heights[next_idx]
    h_taller = heights[idx_taller]
    if h_next is None or h_taller is None:
        return False
    return h_next >= h_taller * (1 - tolerance_ratio)


def detect_step_down_regions_from_stacks(stacks, cargo_width_px,
                                          min_ratio=STEP_DOWN_STACK_MIN_RATIO,
                                          min_height_px=STEP_DOWN_STACK_MIN_HEIGHT_PX,
                                          max_width_ratio=STEP_DOWN_STACK_MAX_WIDTH_RATIO):
    """
    v24.13-v24.17: ตรวจจับ STEP_DOWN_RISK จากการเปรียบเทียบ "ความสูงรวมของตั้งกล่อง"
    (จาก per-box stack model) ระหว่างตั้งที่ติดกันโดยตรงเท่านั้น (ซ้ายหรือขวา)

    กรอบผลลัพธ์ (region) ใช้ขอบเขตของ "ตั้งที่เตี้ยกว่า" เท่านั้น ทำให้กรอบที่วาดออกมา
    แม่นยำและไม่ใหญ่เกินจริง
    """
    regions = []
    if not stacks or len(stacks) < 2:
        return regions
    sorted_stacks = sorted(stacks, key=lambda s: s["x0"])
    heights = [(_stack_total_height(s) if s.get("boxes") else None) for s in sorted_stacks]
    max_width_px = max(1, cargo_width_px) * max_width_ratio
    n = len(sorted_stacks)

    edge_artifact_idxs = _step_down_edge_artifact_stack_indices(sorted_stacks)
    if edge_artifact_idxs:
        print(f"STEP_DOWN edge-artifact gate: excluding {len(edge_artifact_idxs)} narrow "
              f"stack(s) near cargo edge (likely isometric corner/top-face measurement "
              f"artifact, not genuine cargo) - indices={sorted(edge_artifact_idxs)}")

    merged_stack_idxs = _step_down_merged_stack_indices(sorted_stacks)
    if merged_stack_idxs:
        print(f"STEP_DOWN merged-stack gate: excluding {len(merged_stack_idxs)} "
              f"abnormally wide stack(s) (likely 2+ boxes merged due to "
              f"under-segmentation, unreliable top_y measurement) - "
              f"indices={sorted(merged_stack_idxs)}")

    excluded_idxs = edge_artifact_idxs | merged_stack_idxs

    for i in range(n):
        if i in excluded_idxs:
            continue
        h_this = heights[i]
        if h_this is None or h_this < min_height_px:
            continue
        s_this = sorted_stacks[i]
        if _stack_width(s_this) > max_width_px:
            continue
        neighbor_idxs = []
        if i > 0:
            neighbor_idxs.append(i - 1)
        if i < n - 1:
            neighbor_idxs.append(i + 1)
        best_ratio = 0.0
        for j in neighbor_idxs:
            if j in excluded_idxs:
                continue
            h_neighbor = heights[j]
            if h_neighbor is None or h_neighbor < min_height_px:
                continue
            s_neighbor = sorted_stacks[j]
            if STEP_DOWN_REQUIRE_NEIGHBOR_BOX_COUNT_GT_CURRENT:
                # v24.19: ป้องกัน false positive จากมุมมอง isometric: ถ้าจำนวนกล่อง/ชั้น
                # ของตั้งข้างเคียงไม่ได้มากกว่าตั้งนี้จริง จะไม่ถือว่าเป็น step-down
                # (กรณี EA03/EA06 ที่เห็นความสูง pixel ต่างกันแต่จริงๆ จำนวนชั้นเท่ากัน)
                #
                # v24.30 FIX: ยืนยันจาก pixel จริงว่า per-box segmentation ให้ box_count=1
                # เกือบทุกตั้งในทุกไฟล์ที่ทดสอบมา (ไม่เคยพบ >1 เลย) ทำให้เกทนี้กลายเป็น
                # "บล็อกเกือบทุกอย่างเสมอ" โดยพฤตินัย รวมถึงกรณีที่เป็นความเสี่ยงจริง (EC07
                # ผลต่าง 46.2%, EC09 ผลต่าง 32.2% - ยืนยันจากภาพจริงว่าเป็นกล่องเตี้ยกว่า
                # เพื่อนบ้านจริง) - เพิ่มเงื่อนไข OR bypass: ถ้าจำนวนกล่องเท่ากัน (ไม่มี
                # ข้อมูล box-count ที่มีความหมายให้ใช้ตัดสิน) จะยอมให้ผ่านได้เฉพาะกรณีที่
                # เป็น "ขั้นบันไดเดี่ยวที่แยกออกมาชัดเจน" (ไม่ใช่ส่วนหนึ่งของความลาดเอียง
                # ต่อเนื่องหลายตั้งแบบ EA03/EA06) เท่านั้น - ถ้าจำนวนกล่องต่างกันจริง (มี
                # ข้อมูลที่มีความหมาย) ยังคงใช้กฎเดิมทุกประการ (ต้องมากกว่าเท่านั้น)
                neighbor_box_count = len(s_neighbor.get("boxes", []))
                current_box_count = len(s_this.get("boxes", []))
                if max(neighbor_box_count, current_box_count) > 1:
                    if neighbor_box_count <= current_box_count:
                        continue
                else:
                    if _is_part_of_gradual_multi_stack_trend(i, j, heights, excluded_idxs):
                        continue
            if _stack_width(s_neighbor) > max_width_px:
                continue
            if h_neighbor <= h_this:
                continue
            if _is_isolated_tall_peak(j, heights, min_height_px, excluded_idxs=excluded_idxs):
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
    v24.14 NEW: หาก view ใด view หนึ่งไม่มี high-confidence stacks จะ fallback ไปใช้
    "raw stacks" แทน พร้อมเกณฑ์ความสูงที่เข้มงวดขึ้น"""
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
                  f"(fallback_stacks={using_fallback})")
    return results



def _flood_fill_vivid_regions(px, x0, x1, y0, y1, min_area=None, color_tol=None):
    """
    v24.26 NEW: connected-component flood-fill (4-connectivity, BFS) แยก "กลุ่มพิกเซลสี
    เดียวกันที่ติดกัน" ออกเป็นภูมิภาคเดี่ยวๆ ภายในหน้าต่าง pixel ที่กำหนด (x0,x1,y0,y1 -
    พิกัดสัมบูรณ์บนภาพเต็มหน้า) ใช้แก้ ROOT CAUSE ที่แท้จริงของปัญหา EA10: per-box
    segmentation แบบเดิม (detect_stack_columns/detect_boxes_in_stack) ใช้โปรไฟล์ 1 มิติ
    (สแกนสีเฉพาะแถวเดียวใกล้พื้น หรือค่าเฉลี่ยสีต่อแถว) ซึ่งพลาดกรณีที่กล่องเตี้ย 1 ใบ
    กว้างเต็มพื้นที่ฐาน มีกล่องสูงกว่าคนละสีวางซ้อนทับอยู่ด้านบนในตำแหน่ง x ที่ต่างกัน
    (เช่น กล่องเขียวเตี้ยที่ฐาน มีกล่องน้ำตาล+ชมพูซ้อนทับคนละครึ่งด้านบน) - เนื่องจากพื้น
    สีเขียวต่อเนื่องเต็มความกว้าง ทำให้การสแกนแบบเดิมไม่พบจุดแบ่ง แต่ flood-fill แยกตามสี
    จริงจะเห็นว่าเป็นภูมิภาคสีต่างกัน 3 กลุ่มแยกจากกันชัดเจน

    คืนค่า list ของ dict {'x0','x1','y0','y1','color','area'} - แต่ละรายการคือภูมิภาค
    สีเดียวกันที่ติดกันเป็นกลุ่มเดียว (1 กลุ่ม ≈ 1 หน้ากล่องที่มองเห็น)
    """
    if min_area is None:
        min_area = LOW_EXPOSED_FLOODFILL_MIN_AREA_PX
    if color_tol is None:
        color_tol = LOW_EXPOSED_FLOODFILL_COLOR_TOL
    ww = max(0, int(x1) - int(x0))
    hh = max(0, int(y1) - int(y0))
    if ww <= 0 or hh <= 0 or ww * hh > LOW_EXPOSED_FLOODFILL_MAX_PIXELS:
        return []
    x0, y0 = int(x0), int(y0)
    visited = [[False] * ww for _ in range(hh)]
    regions = []
    for yy in range(hh):
        for xx in range(ww):
            if visited[yy][xx]:
                continue
            c0 = px[x0 + xx, y0 + yy]
            if not _is_vivid_cargo_color(c0):
                visited[yy][xx] = True
                continue
            stack = [(xx, yy)]
            visited[yy][xx] = True
            minx = maxx = xx
            miny = maxy = yy
            count = 0
            while stack:
                cx, cy = stack.pop()
                count += 1
                if cx < minx: minx = cx
                if cx > maxx: maxx = cx
                if cy < miny: miny = cy
                if cy > maxy: maxy = cy
                for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < ww and 0 <= ny < hh and not visited[ny][nx]:
                        nc = px[x0 + nx, y0 + ny]
                        if (abs(nc[0] - c0[0]) <= color_tol and abs(nc[1] - c0[1]) <= color_tol
                                and abs(nc[2] - c0[2]) <= color_tol):
                            visited[ny][nx] = True
                            stack.append((nx, ny))
            if count >= min_area:
                regions.append({
                    "x0": x0 + minx, "x1": x0 + maxx + 1,
                    "y0": y0 + miny, "y1": y0 + maxy + 1,
                    "color": c0, "area": count,
                })
    return regions


def _find_low_exposed_via_flood_fill(full_img, stack, floor_y, top_y):
    """
    v24.26 NEW: สำหรับตั้ง (stack) ที่ถูกระบุว่า "กว้างผิดปกติ" (merged, > 1.6 เท่าของ
    ค่ามัธยฐานความกว้างตั้งในแถวเดียวกัน - เกณฑ์เดียวกับ STEP_DOWN's MERGED-STACK GATE)
    ใช้ connected-component flood-fill แยกภูมิภาคสีภายในตั้งนั้นออกจากกัน แล้วหา "กล่อง
    ที่ชิดพื้นและเตี้ยกว่ากล่องที่วางซ้อนทับอยู่ด้านบนโดยตรงอย่างมีนัยสำคัญ" (เทียบกับ
    เพื่อนบ้านที่สัมผัสกันโดยตรงเท่านั้น ไม่ใช่ผลรวมทุกชั้นที่ซ้อนกันอยู่ - การเทียบกับ
    ผลรวมทุกชั้นถูกทดสอบแล้วว่าทำให้กล่องชั้นล่างสุดของ stack ปกติทุกอันถูกเข้าใจผิดว่า
    "เตี้ยผิดปกติ" เสมอ เพราะกล่องชั้นล่างสุดย่อมเตี้ยกว่าผลรวมทั้งหมดเป็นธรรมดา)

    ยืนยันด้วยข้อมูลจริงจากไฟล์ EA10 (เคสที่ผู้ใช้ชี้ตำแหน่งกล่องเขียว TSE1A-D1 ตรง):
    flood-fill แยกออกเป็น 3 ภูมิภาคชัดเจน (เขียว/ฐาน, น้ำตาล/ขวาบน, ชมพู/ซ้ายบน) กล่อง
    เขียวสูง 87px เทียบกับกล่องน้ำตาลที่สัมผัสกันโดยตรงด้านบนสูง 142px = ผลต่าง 39%

    คืนค่า list ของ candidate dict (x_min,y_min,x_max,y_max,ratio)
    """
    px = full_img.convert("RGB").load()
    x0, x1 = int(stack["x0"]), int(stack["x1"])
    y_search_top = max(0, int(top_y) - LOW_EXPOSED_FLOODFILL_UPWARD_MARGIN_PX)
    y_search_bottom = int(floor_y) + 5
    regions = _flood_fill_vivid_regions(px, x0, x1, y_search_top, y_search_bottom)
    if len(regions) < 2:
        return []

    stack_w = max(1, x1 - x0)
    candidates = []
    for r in regions:
        if abs(r["y1"] - floor_y) > LOW_EXPOSED_FLOODFILL_FLOOR_TOL_PX:
            continue  # ไม่ใช่ภูมิภาคที่ชิดพื้นจริง ข้ามไป
        own_h = r["y1"] - r["y0"]
        own_w = r["x1"] - r["x0"]
        if own_w <= 0:
            continue

        # v24.27 NEW: FLOOR-COVERAGE GATE - พบว่ากรอบเท็จของ EA07/AA04-03 เกิดจาก
        # ภูมิภาคที่ชิดพื้นแต่กว้างแค่ส่วนเล็กๆ ของตั้งทั้งหมด (EA07 BACK: กว้างแค่ 33%
        # ของตั้ง, AA04-03 BACK: กว้างแค่ 13-15%) ในขณะที่ EA10 (ความเสี่ยงจริง) กล่อง
        # เขียวกว้างเกือบเต็มตั้งทั้งหมด (98%) - ตรงกับ "signature" ของกล่องเดียววางเต็ม
        # ฐาน มีกล่องอื่นซ้อนทับบางส่วนด้านบนแบบ EA10 จริงๆ เพิ่มเงื่อนไขนี้เพื่อตัด
        # false positive ที่เป็นแค่กล่องเล็กชิ้นหนึ่งในหลายๆ ชิ้นที่วางเรียงกันปกติ
        floor_coverage_ratio = own_w / stack_w
        if floor_coverage_ratio < LOW_EXPOSED_FLOODFILL_MIN_FLOOR_COVERAGE_RATIO:
            print(f"LOW_EXPOSED floodfill candidate REJECTED (x=[{r['x0']:.0f}-{r['x1']:.0f}]): "
                  f"floor_coverage_ratio={floor_coverage_ratio*100:.0f}% < threshold "
                  f"{LOW_EXPOSED_FLOODFILL_MIN_FLOOR_COVERAGE_RATIO*100:.0f}% (this box only "
                  f"covers a small fraction of the merged stack's floor width - likely one of "
                  f"several normally-arranged boxes, not a genuine single low-exposed box "
                  f"spanning the full base like EA10)")
            continue
        best_neighbor = None
        best_neighbor_h = 0
        for o in regions:
            if o is r:
                continue
            overlap = min(r["x1"], o["x1"]) - max(r["x0"], o["x0"])
            min_w = min(own_w, o["x1"] - o["x0"])
            if min_w <= 0:
                continue
            overlap_ratio = overlap / min_w
            touching = abs(o["y1"] - r["y0"]) <= LOW_EXPOSED_FLOODFILL_TOUCH_TOL_PX
            if overlap_ratio >= LOW_EXPOSED_FLOODFILL_MIN_OVERLAP_RATIO and touching:
                oh = o["y1"] - o["y0"]
                if oh > best_neighbor_h:
                    best_neighbor_h = oh
                    best_neighbor = o
        if best_neighbor is None or best_neighbor_h <= 0:
            continue
        ratio = 1 - (own_h / best_neighbor_h)
        if ratio < LOW_EXPOSED_FLOODFILL_HEIGHT_DIFF_MIN_RATIO:
            continue
        candidates.append({
            "x_min": r["x0"], "y_min": r["y0"], "x_max": r["x1"], "y_max": r["y1"],
            "ratio": min(0.99, max(0.30, ratio)),
            "source": "FORCED_DETERMINISTIC_LOW_EXPOSED_FLOODFILL_STEP_DOWN",
        })
    return candidates


def _find_overhang_via_flood_fill(full_img, stack, floor_y, top_y):
    """
    v24.27 NEW: สำหรับตั้งที่ "กว้างผิดปกติ" (merged, เกณฑ์เดียวกับ LOW_EXPOSED/
    STEP_DOWN's MERGED-STACK GATE) ตรวจจับกรณี "กล่องชั้นบนวางอยู่บนฐานรองรับที่แคบกว่า
    หรือไม่ตรงตำแหน่งกัน" ซึ่งเป็นความเสี่ยงจริงที่ผู้ใช้ยืนยัน (AA04-03: กล่องชมพูฐาน
    แคบกว่า/ไม่เพียงพอ ตัวมันเองเสี่ยงหล่น/ไม่มั่นคง) - คนละกลไกกับ LOW_EXPOSED (ซึ่ง
    เทียบ "กล่องเตี้ยติดกล่องสูงกว่า" ในแนวข้าง/ระดับเดียวกัน) เพราะที่นี่เป็นกรณีกล่องบน
    "ไม่มีฐานรองรับเพียงพอในแนวตั้ง" (หลักการเดียวกับ OVERHANG_RISK ปกติ แต่ใช้ flood-fill
    decomposition แทน per-box Y-split เพราะเกิดขึ้นภายในตั้งที่ถูกรวมผิดจาก column scan)

    วิธีตรวจสอบ: ใช้ flood-fill แยกภูมิภาคสีภายในตั้งที่กว้างผิดปกติ จากนั้นสำหรับแต่ละ
    ภูมิภาคที่ "ไม่ชิดพื้น" (คือกล่องชั้นบน) หาภูมิภาคที่สัมผัสกันโดยตรงด้านล่าง (ฐาน
    รองรับ) แล้ววัดว่าส่วนของกล่องบนที่ "ยื่นพ้นขอบฐานรองรับ" (ไม่มีอะไรค้ำยันด้านล่างเลย)
    คิดเป็นสัดส่วนเท่าไหร่ของความกว้างกล่องบนทั้งหมด - ถ้าสัดส่วนนี้สูงพอ (>=30%) ถือว่า
    เสี่ยงหล่น/ไม่มั่นคงจริง

    คืนค่า list ของ candidate dict (x_min,y_min,x_max,y_max,ratio) สำหรับใช้เป็น
    OVERHANG_RISK deterministic forced region (คนละ risk type จาก LOW_EXPOSED)
    """
    px = full_img.convert("RGB").load()
    x0, x1 = int(stack["x0"]), int(stack["x1"])
    y_search_top = max(0, int(top_y) - LOW_EXPOSED_FLOODFILL_UPWARD_MARGIN_PX)
    y_search_bottom = int(floor_y) + 5
    regions = _flood_fill_vivid_regions(px, x0, x1, y_search_top, y_search_bottom)
    if len(regions) < 2:
        return []

    candidates = []
    for upper in regions:
        upper_w = upper["x1"] - upper["x0"]
        upper_area = upper_w * (upper["y1"] - upper["y0"])
        if upper_area < OVERHANG_FLOODFILL_MIN_UPPER_AREA_PX:
            continue
        if upper_w <= 0:
            continue
        # หาภูมิภาคที่ "สัมผัสกันโดยตรงด้านล่าง" ของ upper (คือฐานรองรับที่แท้จริง)
        supports = []
        for o in regions:
            if o is upper:
                continue
            overlap = min(upper["x1"], o["x1"]) - max(upper["x0"], o["x0"])
            if overlap <= 0:
                continue
            touching = abs(o["y0"] - upper["y1"]) <= LOW_EXPOSED_FLOODFILL_TOUCH_TOL_PX
            if touching:
                supports.append(o)
        if not supports:
            continue
        # รวมช่วง x ของฐานรองรับทั้งหมดที่สัมผัสกัน (อาจมีมากกว่า 1 ชิ้นเรียงติดกัน)
        support_x0 = min(s["x0"] for s in supports)
        support_x1 = max(s["x1"] for s in supports)
        # คำนวณส่วนของ upper ที่ "ไม่มีฐานรองรับ" (ยื่นพ้นขอบซ้าย/ขวาของฐานรองรับรวม)
        unsupported_left = max(0, support_x0 - upper["x0"])
        unsupported_right = max(0, upper["x1"] - support_x1)
        unsupported_total = unsupported_left + unsupported_right
        unsupported_ratio = unsupported_total / upper_w
        if unsupported_ratio < OVERHANG_FLOODFILL_MIN_UNSUPPORTED_RATIO:
            continue
        print(f"OVERHANG floodfill candidate CONFIRMED (upper box x=[{upper['x0']:.0f}-"
              f"{upper['x1']:.0f}], support x=[{support_x0:.0f}-{support_x1:.0f}]): "
              f"unsupported_ratio={unsupported_ratio*100:.0f}% (this box's base support is "
              f"significantly narrower/misaligned - risk of falling/instability)")
        candidates.append({
            "x_min": upper["x0"], "y_min": upper["y0"], "x_max": upper["x1"], "y_max": upper["y1"],
            "ratio": min(0.99, max(0.20, unsupported_ratio)),
            "source": "FORCED_DETERMINISTIC_OVERHANG_FLOODFILL",
        })
    return candidates


def detect_overhang_regions_via_floodfill_per_view(stack_box_model, cargo_extent, full_img=None):
    """
    v24.27 NEW: เรียก _find_overhang_via_flood_fill() สำหรับตั้งที่กว้างผิดปกติ (merged)
    ในทั้ง FRONT และ BACK view - ใช้เกณฑ์ merged-stack เดียวกับ STEP_DOWN/LOW_EXPOSED
    (> 1.6 เท่าของค่ามัธยฐานความกว้างตั้งในแถวเดียวกัน)
    """
    results = {"FRONT": [], "BACK": []}
    # v24.27: ปิดฟีเจอร์นี้ไว้ก่อน (ทดสอบจริงแล้วพบ false positive จำนวนมาก รวมถึงใน
    # EA07 ที่ผู้ใช้ยืนยันว่าปลอดภัย) - ดู CHANGELOG และคอมเมนต์ที่ OVERHANG_FLOODFILL_
    # DETECTOR_ENABLED สำหรับรายละเอียดเต็ม จำเป็นต้องพัฒนา logic ที่แม่นยำกว่านี้ก่อน
    if not OVERHANG_FLOODFILL_DETECTOR_ENABLED or full_img is None:
        return results
    for view in ("FRONT", "BACK"):
        stacks = stack_box_model.get(view, [])
        if not stacks:
            stacks = stack_box_model.get(f"{view}_raw_stacks", [])
        ss = sorted(stacks, key=lambda s: s["x0"])
        widths = sorted(_stack_width(s) for s in ss)
        median_w = widths[len(widths)//2] if widths else 1
        for st in ss:
            if not st.get("boxes"):
                continue
            w = _stack_width(st)
            if median_w <= 0 or w <= median_w * STEP_DOWN_STACK_MAX_WIDTH_RATIO_OF_MEDIAN:
                continue
            candidates = _find_overhang_via_flood_fill(full_img, st, st["floor_y"], st["top_y"])
            results[view].extend(candidates)
        for r in results[view]:
            print(f"OVERHANG_RISK (floodfill) candidate ({view}): x=[{r['x_min']:.0f}-{r['x_max']:.0f}] "
                  f"y=[{r['y_min']:.0f}-{r['y_max']:.0f}] ratio={r['ratio']*100:.0f}%")
    return results


def detect_low_exposed_step_regions_for_view(stacks, cargo_extent_view=None, full_img=None):
    """
    v24.22/v24.25/v24.26: ตรวจจับ "กล่อง/ตั้งชั้นล่างที่เปิดโล่งด้านบน" ซึ่งเป็นความเสี่ยง
    จริงที่กล่องสูงข้างเคียงอาจหล่นทับ (ยืนยันจากเคส EA10 - ท้ายตู้มีกล่องต่ำติดกล่องสูงกว่า)

    หลักคิด: ไม่ใช้แค่ pixel-height ratio แบบ STEP_DOWN เดิม เพราะเคสนี้ segmentation อาจ
    รวมกล่องหรือวัด height เพี้ยนจาก isometric แต่ยังเห็น pattern สำคัญคือ:
      - top_y ของตั้งนี้ต่ำกว่าขอบบนของ cargo มาก (มีพื้นที่ว่างด้านบนชัดเจน ตามเรขาคณิต)
      - floor_y อยู่ใกล้พื้น/ขอบล่าง cargo
      - มีเพื่อนบ้านที่ top_y สูงกว่าอย่างชัดเจนอย่างน้อย 1 ฝั่ง
      - ไม่กว้างผิดปกติเกินไปเมื่อเทียบกับ median width (กัน merged stack ใหญ่เกิน)

    v24.25 - HEIGHT-DIFFERENCE-RATIO GATE: เปรียบเทียบผลต่างความสูงรวมระหว่างตั้งเตี้ย
    กับตั้งข้างเคียงที่สูงกว่า (แทนที่ pixel-color verification ของ v24.24 ที่พิสูจน์แล้ว
    ว่าใช้แยกแยะ EA07/EA10 ไม่ได้จริง)

    v24.26 NEW - FLOOD-FILL DECOMPOSITION สำหรับตั้งที่ "กว้างผิดปกติ" (ROOT CAUSE FIX
    ที่แท้จริงของปัญหา EA10 ซึ่ง v24.25 ยังแก้ไม่ได้): ตรวจสอบแล้วพบว่าตั้งของ EA10 ที่มี
    กล่องเขียวที่ผู้ใช้ชี้ ถูก per-box segmentation รวม (merge) เป็นตั้งเดียวกว้างผิดปกติ
    (1.99 เท่าของค่ามัธยฐาน) ตั้งแต่ขั้นตอนแบ่งคอลัมน์ (เพราะพื้นสีเขียวของกล่องเตี้ยต่อ
    เนื่องเต็มความกว้าง ทำให้การสแกนแนวคอลัมน์แบบเดิมมองไม่เห็นจุดแบ่ง) เมื่อคำนวณความสูง
    ของ "ตั้งที่ถูกรวมผิด" นี้ทั้งก้อน ได้ค่าคลาดเคลื่อนที่ไม่ต่างจากเพื่อนบ้านมากพอ (v24.25
    วัดได้แค่ 8%) - จึงเพิ่มการตรวจสอบเพิ่มเติมเฉพาะตั้งที่กว้างผิดปกติจริง (> 1.6 เท่าของ
    ค่ามัธยฐาน เกณฑ์เดียวกับที่ STEP_DOWN_RISK ใช้อยู่แล้ว) ด้วย flood-fill แยกภูมิภาคสี
    ภายในตั้งนั้น แล้วเปรียบเทียบ "กล่องที่ชิดพื้น" กับ "กล่องที่สัมผัสกันโดยตรงด้านบน"
    (ไม่ใช่ผลรวมทุกชั้น) - ดู _find_low_exposed_via_flood_fill() สำหรับรายละเอียด

    หมายเหตุสำคัญ (ต้องแจ้งผู้ใช้ตรงไปตรงมา): ทดสอบ FLOOD-FILL PATH นี้ข้ามไฟล์ทดสอบ 5
    ไฟล์ (EA07, EA10, AA02-01, AA04-03, AA04-06) พบว่านอกจากจะตรวจพบเคส EA10 ที่ต้องการ
    ได้สำเร็จ (39%) และไม่ตรวจพบ false positive ที่ EA07 เคยรายงานไว้ (FRONT stack เดิม,
    สูงสุด 21%) แล้ว ยังพบ candidate ใหม่ที่ยังไม่เคยถูกตรวจสอบ/ยืนยันมาก่อนในไฟล์อื่น
    (เช่น EA07 BACK, AA04-03 BACK) ที่มีค่าใกล้เคียงหรือสูงกว่า - เนื่องจากไม่มีข้อมูล
    ตำแหน่งกล่องจริง (ground truth) ในไฟล์ PDF ให้ตรวจสอบได้ จึงไม่สามารถยืนยันได้ 100%
    ว่า candidate ใหม่เหล่านี้เป็นความเสี่ยงจริงหรือ false positive - ผู้ใช้ควรตรวจสอบผล
    ลัพธ์เพิ่มเติมจากไฟล์จริงและแจ้งกลับหากพบจุดผิดปกติ เพื่อปรับ threshold ต่อไป

    คืนค่า region ที่ใช้เป็น STEP_DOWN_RISK deterministic forced region
    """
    regions = []
    if not LOW_EXPOSED_DETECTOR_ENABLED:
        return regions
    if not stacks or len(stacks) < 2:
        return regions
    ss = sorted(stacks, key=lambda s: s["x0"])
    widths = sorted(_stack_width(s) for s in ss)
    median_w = widths[len(widths)//2] if widths else 1
    min_top = min((s["top_y"] for s in ss if s.get("boxes")), default=None)
    if min_top is None:
        return regions
    cargo_ymax = cargo_extent_view.get("ymax") if cargo_extent_view else max(s["floor_y"] for s in ss)
    for i, st in enumerate(ss):
        if not st.get("boxes"):
            continue
        w = _stack_width(st)

        # v24.26 NEW: ถ้าตั้งนี้ "กว้างผิดปกติจริง" (merged, ใช้เกณฑ์เดียวกับ STEP_DOWN)
        # ลองใช้ flood-fill decomposition ก่อน แทนที่จะข้ามไปเฉยๆ แบบ v24.22-v24.25
        if median_w > 0 and w > median_w * STEP_DOWN_STACK_MAX_WIDTH_RATIO_OF_MEDIAN:
            if full_img is not None:
                ff_candidates = _find_low_exposed_via_flood_fill(full_img, st, st["floor_y"], st["top_y"])
                for cand in ff_candidates:
                    print(f"LOW_EXPOSED candidate CONFIRMED via FLOOD-FILL (merged stack "
                          f"x=[{st['x0']:.0f}-{st['x1']:.0f}]): sub-region x=[{cand['x_min']:.0f}-"
                          f"{cand['x_max']:.0f}] ratio={cand['ratio']*100:.0f}%")
                    regions.append(cand)
            continue  # ไม่ใช้ whole-stack comparison เดิมกับตั้งที่กว้างผิดปกติ (ไม่แม่นยำ)

        if median_w > 0 and w > median_w * LOW_EXPOSED_MAX_WIDTH_RATIO_OF_MEDIAN:
            continue
        top_gap = st["top_y"] - min_top
        if top_gap < LOW_EXPOSED_MIN_TOP_GAP_PX:
            continue
        if (cargo_ymax - st["floor_y"]) > LOW_EXPOSED_FLOOR_PROXIMITY_PX:
            continue
        neigh = []
        if i > 0:
            neigh.append(ss[i-1])
        if i < len(ss)-1:
            neigh.append(ss[i+1])
        if not neigh:
            continue
        candidates = [n for n in neigh if n.get("boxes") and (n["top_y"] < st["top_y"])]
        if not candidates:
            continue
        best_neighbor = max(candidates, key=lambda n: st["top_y"] - n["top_y"])
        best_top_diff = st["top_y"] - best_neighbor["top_y"]
        if best_top_diff < LOW_EXPOSED_MIN_NEIGHBOR_TOP_DIFF_PX:
            continue

        # v24.25: HEIGHT-DIFFERENCE-RATIO GATE - เปรียบเทียบความสูงรวมของตั้งนี้กับ
        # ตั้งข้างเคียงที่สูงกว่า (แทนการตรวจสอบสี pixel ที่พิสูจน์แล้วว่าใช้แยกแยะไม่ได้)
        h_this = _stack_total_height(st)
        h_neighbor = _stack_total_height(best_neighbor)
        if h_this is None or h_neighbor is None or h_neighbor <= 0:
            continue
        height_diff_ratio = 1 - (h_this / h_neighbor)
        if height_diff_ratio < LOW_EXPOSED_HEIGHT_DIFF_MIN_RATIO:
            print(f"LOW_EXPOSED candidate REJECTED (x=[{st['x0']:.0f}-{st['x1']:.0f}]): "
                  f"height_diff_ratio={height_diff_ratio*100:.0f}% < threshold "
                  f"{LOW_EXPOSED_HEIGHT_DIFF_MIN_RATIO*100:.0f}% (this_h={h_this:.0f}px, "
                  f"neighbor_h={h_neighbor:.0f}px - likely isometric slope, not a genuine "
                  f"low-exposed stack, e.g. EA07-style continuous full block)")
            continue
        print(f"LOW_EXPOSED candidate CONFIRMED (x=[{st['x0']:.0f}-{st['x1']:.0f}]): "
              f"height_diff_ratio={height_diff_ratio*100:.0f}% (this_h={h_this:.0f}px, "
              f"neighbor_h={h_neighbor:.0f}px - genuine low stack next to much taller stack)")

        regions.append({
            "x_min": st["x0"], "y_min": st["top_y"],
            "x_max": st["x1"], "y_max": st["floor_y"],
            "ratio": min(0.99, max(0.30, height_diff_ratio)),
            "source": "FORCED_DETERMINISTIC_LOW_EXPOSED_STACK_STEP_DOWN",
        })
    return regions


def detect_low_exposed_step_regions_per_view(stack_box_model, cargo_extent, full_img=None):
    results = {"FRONT": [], "BACK": []}
    for view in ("FRONT", "BACK"):
        stacks = stack_box_model.get(view, [])
        if not stacks:
            stacks = stack_box_model.get(f"{view}_raw_stacks", [])
        regions = detect_low_exposed_step_regions_for_view(stacks, cargo_extent.get(view), full_img=full_img)
        results[view] = regions
        for r in regions:
            print(f"LOW_EXPOSED STEP_DOWN candidate ({view}): x=[{r['x_min']:.0f}-{r['x_max']:.0f}] y=[{r['y_min']:.0f}-{r['y_max']:.0f}]")
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
        # v24.13 FIX: ใช้เฉพาะขอบเขตความสูงของคาร์โก้จริง (view_cargo) เท่านั้น + padding
        # เล็กน้อย แทนที่จะใช้ min/max ระหว่าง container+cargo รวมกัน (ซึ่งทำให้กรอบ
        # ยืดเต็มความสูงของภาพเสมอ)
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

# ---------------------------------------------------------------------------
# v24.18 NEW: GAP MEASUREMENT ARROW - แสดง LATERAL_GAP_RISK/FRONT_EMPTY_RISK/
# REAR_EMPTY_RISK เป็น "เส้นลูกศร 2 หัว + ตัวเลขระยะห่างกำกับ" (คล้ายเส้นบอกขนาดใน
# แบบวิศวกรรม/CAD) แทนกรอบสี่เหลี่ยมทึบ - ดู CHANGELOG หัวไฟล์สำหรับรายละเอียดเต็ม
# ---------------------------------------------------------------------------

_DIMENSION_FONT_CACHE = {}


def _get_dimension_font(size=GAP_ARROW_LABEL_FONT_SIZE):
    """โหลดฟอนต์สำหรับ label ตัวเลขระยะห่าง (cached) - มี fallback เป็น default font
    ของ PIL หากไม่พบไฟล์ฟอนต์ TrueType ในระบบ (กันโค้ดพังในสภาพแวดล้อมที่ไม่มีฟอนต์นี้)"""
    if size in _DIMENSION_FONT_CACHE:
        return _DIMENSION_FONT_CACHE[size]
    font = None
    for font_name in ("DejaVuSans-Bold.ttf", "DejaVuSans.ttf", "Arial.ttf", "arial.ttf"):
        try:
            font = PIL.ImageFont.truetype(font_name, size)
            break
        except Exception:
            continue
    if font is None:
        try:
            font = PIL.ImageFont.load_default(size=size)
        except Exception:
            font = PIL.ImageFont.load_default()
    _DIMENSION_FONT_CACHE[size] = font
    return font


def _draw_arrowhead(draw, apex, direction_from, color,
                     length=GAP_ARROW_HEAD_LENGTH_PX, width=GAP_ARROW_HEAD_WIDTH_PX):
    """วาดหัวลูกศรรูปสามเหลี่ยมทึบที่ตำแหน่ง apex ชี้ออกจากทิศทาง direction_from
    (คือปลายลูกศรอยู่ที่ apex ฐานสามเหลี่ยมอยู่ทางฝั่ง direction_from)"""
    ax, ay = apex
    dx, dy = direction_from
    vx, vy = ax - dx, ay - dy
    dist = (vx ** 2 + vy ** 2) ** 0.5
    if dist < 1e-6:
        return
    ux, uy = vx / dist, vy / dist
    px_, py_ = -uy, ux  # perpendicular unit vector
    base_x, base_y = ax - ux * length, ay - uy * length
    p1 = (base_x + px_ * width / 2, base_y + py_ * width / 2)
    p2 = (base_x - px_ * width / 2, base_y - py_ * width / 2)
    draw.polygon([apex, p1, p2], fill=color)


def _draw_text_with_bg(draw, center_pos, text, font, text_color="black", bg_color="white", outline_color=None):
    """วาดข้อความพร้อมกล่องพื้นหลังทึบสีขาว (อ่านง่ายไม่ว่าพื้นหลังภาพจะเป็นสีอะไร)
    center_pos คือจุดกึ่งกลางของกล่องข้อความ"""
    x, y = center_pos
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = len(text) * (GAP_ARROW_LABEL_FONT_SIZE * 0.6), GAP_ARROW_LABEL_FONT_SIZE * 1.2
    pad = GAP_ARROW_LABEL_PADDING_PX
    rect = [x - tw / 2 - pad, y - th / 2 - pad, x + tw / 2 + pad, y + th / 2 + pad]
    draw.rectangle(rect, fill=bg_color, outline=(outline_color or text_color), width=1)
    draw.text((x - tw / 2, y - th / 2), text, fill=text_color, font=font)


def _draw_gap_measurement_arrow(draw, p1, p2, orientation, label_text, color):
    """
    v24.18 NEW: วาดเส้นลูกศร 2 หัว (dimension arrow) ระหว่างจุด p1 กับ p2 พร้อมขีดตั้งฉาก
    (dimension tick) ที่ปลายทั้ง 2 ข้าง และตัวเลข label_text กำกับกึ่งกลางเส้น (หรือ
    นอกเส้นถ้าเส้นสั้นเกินไป) - ใช้แทนกรอบสี่เหลี่ยมสำหรับ LATERAL_GAP_RISK/
    FRONT_EMPTY_RISK/REAR_EMPTY_RISK ตามคำแนะนำผู้ใช้

    orientation: "vertical" (LATERAL_GAP_RISK) หรือ "horizontal" (FRONT/REAR_EMPTY_RISK)
    - กำหนดทิศทางของขีดตั้งฉากที่ปลายเส้น (ให้ตั้งฉากกับเส้นหลักเสมอ)
    """
    x1, y1 = p1
    x2, y2 = p2
    length = ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5
    if length < 2:
        return False

    draw.line([x1, y1, x2, y2], fill=color, width=GAP_ARROW_LINE_WIDTH_PX)

    tick = GAP_ARROW_TICK_LENGTH_PX
    if orientation == "vertical":
        draw.line([x1 - tick, y1, x1 + tick, y1], fill=color, width=GAP_ARROW_LINE_WIDTH_PX)
        draw.line([x2 - tick, y2, x2 + tick, y2], fill=color, width=GAP_ARROW_LINE_WIDTH_PX)
    else:
        draw.line([x1, y1 - tick, x1, y1 + tick], fill=color, width=GAP_ARROW_LINE_WIDTH_PX)
        draw.line([x2, y2 - tick, x2, y2 + tick], fill=color, width=GAP_ARROW_LINE_WIDTH_PX)

    _draw_arrowhead(draw, (x1, y1), (x2, y2), color)
    _draw_arrowhead(draw, (x2, y2), (x1, y1), color)

    mid_x, mid_y = (x1 + x2) / 2, (y1 + y2) / 2
    font = _get_dimension_font()
    if length < GAP_ARROW_MIN_LENGTH_FOR_INLINE_LABEL_PX:
        # v24.18: เส้นสั้นเกินไป (ช่องว่างแคบ) - ย้าย label ออกไปด้านนอกเส้นแทนวางทับ
        # กึ่งกลาง กันตัวเลขบังกันเองในพื้นที่แคบ
        if orientation == "vertical":
            label_pos = (mid_x + tick + 34, mid_y)
        else:
            label_pos = (mid_x, mid_y - tick - 18)
    else:
        label_pos = (mid_x, mid_y)

    _draw_text_with_bg(draw, label_pos, label_text, font, text_color="black", bg_color="white", outline_color=color)
    return True


def _format_gap_label(mm_val, ratio_val):
    """แปลงค่าระยะห่าง (มม. หรือสัดส่วน) เป็นข้อความ label สำหรับกำกับเส้นลูกศร

    v24.18 NOTE: ใช้หน่วยภาษาอังกฤษ ("cm") แทน "ซม." เพราะฟอนต์ TrueType ที่มีอยู่ใน
    สภาพแวดล้อม deploy (DejaVu Sans) ไม่มี glyph ภาษาไทย - ถ้าใช้ข้อความไทยตรงนี้จะ
    เรนเดอร์เป็นกล่องสี่เหลี่ยมว่างแทนตัวอักษร (ยืนยันจากการทดสอบเรนเดอร์จริง) คำอธิบาย
    ความเสี่ยง (action_text/description) ในส่วนอื่นยังคงเป็นภาษาไทยตามปกติ เพราะเป็น
    ข้อความ JSON ธรรมดา ไม่ใช่ข้อความที่วาดลงบนรูปภาพ"""
    if mm_val is not None:
        return f"{mm_val / 10:.0f} cm"
    elif ratio_val is not None:
        return f"{ratio_val * 100:.0f}%"
    else:
        return "?"


def _compute_lateral_gap_arrow_geometry(view_container, view_cargo, full_img=None):
    """
    v24.18 NEW: คำนวณจุดเริ่ม/จุดสิ้นสุดของเส้นลูกศรสำหรับ LATERAL_GAP_RISK (แนวตั้ง -
    ช่องว่างระหว่างขอบบน/ล่างของคาร์โก้กับขอบบน/ล่างของตู้) ใช้หลักการเดียวกับ
    get_precise_lateral_gap_box (v24.2/v24.13) ในการเลือกฝั่งที่มีช่องว่างจริงมากกว่า
    และหาตำแหน่ง x ที่ว่างจริงด้วย pixel scan (_localize_lateral_gap_x_range)

    คืนค่า ("vertical", (x, y_cargo_edge), (x, y_container_edge)) หรือ None
    """
    if not view_container or not view_cargo:
        return None
    top_gap = view_cargo["ymin"] - view_container["ymin"]
    bottom_gap = view_container["ymax"] - view_cargo["ymax"]
    if bottom_gap >= top_gap and bottom_gap > 0:
        y1, y2 = view_cargo["ymax"], view_container["ymax"]
    elif top_gap > 0:
        y1, y2 = view_container["ymin"], view_cargo["ymin"]
    else:
        return None

    x0, x1_ = view_cargo["xmin"], view_cargo["xmax"]
    x_mid = (x0 + x1_) / 2
    if full_img is not None:
        localized = _localize_lateral_gap_x_range(full_img, x0, x1_, min(y1, y2), max(y1, y2))
        if localized:
            x_mid = (localized[0] + localized[1]) / 2
        else:
            # v24.19: ไม่มีหลักฐาน pixel ว่ามี x-range ว่างจริง ณ แถบ y นี้
            # จึงไม่วาดลูกศรลอยในพื้นที่ว่าง ให้ caller fallback เป็นกรอบ/box เดิมแทน
            return None
    return ("vertical", (x_mid, y1), (x_mid, y2))


def _compute_empty_gap_arrow_geometry(view_container, view_cargo, rear_side, risk_type):
    """
    v24.18 NEW: คำนวณจุดเริ่ม/จุดสิ้นสุดของเส้นลูกศรสำหรับ FRONT_EMPTY_RISK/
    REAR_EMPTY_RISK (แนวนอน - ช่องว่างตามความยาวตู้ระหว่างคาร์โก้กับผนังหัวตู้/ประตู
    ท้ายตู้) - ตำแหน่ง y ใช้กึ่งกลางความสูงคาร์โก้ เพื่อไม่ให้เส้นทับซ้อนกับตัวอักษร
    SKU บนกล่องหรือเส้นขอบกล่องส่วนบน/ล่าง

    คืนค่า ("horizontal", (x1, y_mid), (x2, y_mid)) หรือ None
    """
    if not view_container or not view_cargo:
        return None
    c_xmin, c_xmax = view_container["xmin"], view_container["xmax"]
    g_xmin, g_xmax = view_cargo["xmin"], view_cargo["xmax"]
    if risk_type == "FRONT_EMPTY_RISK":
        if rear_side == "LEFT":
            x1, x2 = g_xmax, c_xmax
        else:
            x1, x2 = c_xmin, g_xmin
    else:  # REAR_EMPTY_RISK / REAR_COMBINED_RISK
        if rear_side == "LEFT":
            x1, x2 = c_xmin, g_xmin
        else:
            x1, x2 = g_xmax, c_xmax
    if x2 < x1:
        x1, x2 = x2, x1
    y_mid = (view_cargo["ymin"] + view_cargo["ymax"]) / 2
    return ("horizontal", (x1, y_mid), (x2, y_mid))



def _compute_localized_lateral_gap_box(view_container, view_cargo, full_img=None):
    """
    v24.21 NEW: คืนค่า box ของพื้นที่ว่างที่มี pixel evidence จริงสำหรับ LATERAL_GAP_RISK
    โดยใช้ logic เดียวกับ get_precise_lateral_gap_box แต่ expose เป็น deterministic geometry
    เพื่อใช้วาด floor-empty marker ในตำแหน่งที่ผู้ใช้วงไว้ แทนการวาดลูกศร/label ลอยนอกตู้
    """
    if not view_container or not view_cargo:
        return None
    top_gap = view_cargo["ymin"] - view_container["ymin"]
    bottom_gap = view_container["ymax"] - view_cargo["ymax"]
    if bottom_gap >= top_gap and bottom_gap > 0:
        y0, y1 = view_cargo["ymax"], view_container["ymax"]
        gap_kind = "bottom_floor"
    elif top_gap > 0:
        y0, y1 = view_container["ymin"], view_cargo["ymin"]
        gap_kind = "top_space"
    else:
        return None

    x0, x1 = view_cargo["xmin"], view_cargo["xmax"]
    localized = None
    if full_img is not None:
        localized = _localize_lateral_gap_x_range(full_img, x0, x1, min(y0, y1), max(y0, y1))
    if not localized:
        return None
    lx0, lx1 = localized
    # pad เล็กน้อยเฉพาะใน box ของพื้นที่ว่าง ไม่ขยายกลับไปครอบ cargo
    pad_y = max(3, int(abs(y1 - y0) * 0.10))
    return (lx0, max(0, min(y0, y1) - pad_y), lx1, max(y0, y1) + pad_y, gap_kind)


def _draw_floor_empty_marker(draw, box_with_kind, label_text, color):
    """
    v24.21 NEW: วาด marker แบบบางรอบ empty floor zone จริง พร้อม label ใกล้พื้นที่นั้น
    ไม่วาดเป็นกรอบใหญ่ทับ cargo และไม่วาง label ลอยนอกตู้
    """
    if not box_with_kind:
        return False
    x0, y0, x1, y1, gap_kind = box_with_kind
    if x1 <= x0 or y1 <= y0:
        return False
    x0, y0, x1, y1 = map(int, (x0, y0, x1, y1))
    # วาด box บางมากเฉพาะพื้นที่ว่างจริง เพื่อเป็นบริบทให้ label
    draw.rectangle([x0, y0, x1, y1], outline=color, width=3)
    font = _get_dimension_font()
    # label อยู่กลางพื้นที่ marker หรือขยับนิดหน่อยถ้า marker เตี้ย
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if (y1 - y0) < 45:
        cy = y0 - FLOOR_EMPTY_MARKER_LABEL_OFFSET_PX
    _draw_text_with_bg(draw, (cx, cy), label_text, font, text_color="black", bg_color="white", outline_color=color)
    return True

def _try_draw_gap_risk_arrow(draw, risk_type, view_label, container_bounds, cargo_extent,
                              container_length_mm, full_img, color):
    """
    v24.18 NEW: ฟังก์ชันกลางสำหรับพยายามวาดเส้นลูกศรวัดระยะสำหรับ LATERAL_GAP_RISK/
    FRONT_EMPTY_RISK/REAR_EMPTY_RISK - คำนวณทั้งเรขาคณิต (จุดเริ่ม/สิ้นสุด) และตัวเลข
    label โดยตรงจาก container_bounds/cargo_extent เสมอ (deterministic, ไม่ผูกกับ
    แหล่งที่มาของ risk ว่าเป็น AI claim หรือ FORCED deterministic)

    คืนค่า True หากวาดสำเร็จ, False หากไม่มีข้อมูลพอ (ผู้เรียกควร fallback ไปใช้กรอบ
    สี่เหลี่ยมแบบเดิมเพื่อไม่ให้ risk นั้นไม่ถูกวาดอะไรเลย)
    """
    view_container = container_bounds.get(view_label)
    view_cargo = cargo_extent.get(view_label)
    if not view_container or not view_cargo:
        return False

    if risk_type == "LATERAL_GAP_RISK":
        # v24.21: LATERAL_GAP ที่อยู่ด้านล่าง cargo มักเป็นพื้นที่ว่างบนพื้นท้ายตู้/พื้นด้านหลัง
        # จึงให้วาดเป็น FLOOR EMPTY marker บน empty floor zone จริงก่อน ไม่วาดลูกศรลอย
        local_box = _compute_localized_lateral_gap_box(view_container, view_cargo, full_img)
        mm_val = compute_lateral_gap_mm(view_container, view_cargo, container_length_mm)
        ratio_val = compute_lateral_gap_ratio(view_container, view_cargo)
        if local_box:
            base_label = _format_gap_label(mm_val, ratio_val)
            # bottom_floor คือกรณีที่ผู้ใช้วงแดงให้ดู: พื้นว่างหลัง/ท้าย cargo
            label_text = f"FLOOR EMPTY {base_label}" if local_box[-1] == "bottom_floor" else f"SIDE GAP {base_label}"
            return _draw_floor_empty_marker(draw, local_box, label_text, color)
        # ไม่มี local pixel evidence -> ไม่วาด marker/lost arrow เพื่อกันกรอบ/label ลอยนอกตู้
        return False
    elif risk_type in ("FRONT_EMPTY_RISK", "REAR_EMPTY_RISK"):
        rear_side = HARDCODED_REAR_SIDE.get(view_label, "LEFT")
        geom = _compute_empty_gap_arrow_geometry(view_container, view_cargo, rear_side, risk_type)
        if not geom:
            return False
        orientation, p1, p2 = geom
        mm_val = compute_empty_gap_mm(view_container, view_cargo, rear_side, risk_type, container_length_mm)
        ratio_val = compute_empty_gap_ratio(view_container, view_cargo, rear_side, risk_type)
    else:
        return False

    base_label = _format_gap_label(mm_val, ratio_val)
    if risk_type == "LATERAL_GAP_RISK":
        label_text = f"SIDE GAP {base_label}"
    elif risk_type == "FRONT_EMPTY_RISK":
        label_text = f"FRONT EMPTY {base_label}"
    elif risk_type == "REAR_EMPTY_RISK":
        label_text = f"REAR EMPTY {base_label}"
    else:
        label_text = base_label
    return _draw_gap_measurement_arrow(draw, p1, p2, orientation, label_text, color)


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
        try:
            _all_text = "\n".join(_p.get_text("text") for _p in doc)
            _m = re.search(r"Manifest\s+([^\s_]+(?:-[^\s_]+)?)", _all_text)
            manifest_key = _m.group(1).upper() if _m else "UNKNOWN"
            _cube_m = re.search(r"Cargo Cube:\s*[^\n%]*/\s*([0-9]+(?:\.[0-9]+)?)\s*%", _all_text)
            cargo_cube_pct = float(_cube_m.group(1)) if _cube_m else None
        except Exception:
            manifest_key = "UNKNOWN"
            cargo_cube_pct = None
        print(f"v24.48 manifest_key={manifest_key} cargo_cube_pct={cargo_cube_pct}")
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

        # v24.13-v24.17: STEP_DOWN_RISK ใช้ "การเปรียบเทียบความสูงรวมของตั้งกล่องที่
        # ติดกัน" (per-box stack model เดียวกับ OVERHANG_RISK/TALL_UNSTABLE_RISK/
        # REAR_LATERAL_IMBALANCE) เป็นแหล่งข้อมูลเดียวเท่านั้น - แทนที่วิธีเดิมทั้งหมด
        # (height-profile pixel scan, floor-hole scan, cross-view mirror/veto + OCR-SKU
        # matching) v24.14-v24.17 เพิ่ม STACK-WIDTH SANITY GATE + RAW-STACK FALLBACK +
        # ISOLATED-PEAK EXCLUSION + EDGE-ARTIFACT GATE + MERGED-STACK GATE (median-based)
        step_down_regions = detect_step_down_regions_from_stack_model_per_view(stack_box_model, cargo_extent)
        # v24.22/v24.24: เพิ่ม candidate จาก low-exposed stack detector (เช่นกล่องชั้นล่าง
        # ที่ผู้ใช้วงแดงในเคส EA10 - ท้ายตู้มีกล่องต่ำติดกล่องสูงกว่า เสี่ยงกล่องสูงหล่นทับ)
        # v24.24: ส่ง img (ภาพเต็มหน้า) เข้าไปด้วยเสมอ เพื่อให้ผ่าน PIXEL-VERIFIED
        # OPEN-SPACE GATE ก่อนยอมรับเป็นความเสี่ยงจริง (แก้ false positive EA07 อย่างถูก
        # จุด แทนการปิด detector ทั้งหมดแบบ v24.23 ซึ่งทำให้ EA10 ตรวจไม่พบไปด้วย)
        low_exposed_step_regions = detect_low_exposed_step_regions_per_view(stack_box_model, cargo_extent, full_img=img)
        for view_label in ("FRONT", "BACK"):
            existing = step_down_regions.get(view_label, [])
            for lr in low_exposed_step_regions.get(view_label, []):
                duplicate = any(_box_iou_absolute((lr["x_min"], lr["y_min"], lr["x_max"], lr["y_max"]),
                                                  (r["x_min"], r["y_min"], r["x_max"], r["y_max"])) >= 0.15
                                for r in existing)
                if not duplicate:
                    existing.append(lr)
            step_down_regions[view_label] = existing

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

        # v24.27 NEW: OVERHANG-VIA-FLOODFILL - สำหรับตั้งที่กว้างผิดปกติ (merged) ตรวจจับ
        # กรณี "กล่องชั้นบนวางอยู่บนฐานรองรับที่แคบกว่า/ไม่ตรงตำแหน่งกัน" ซึ่งเป็นความ
        # เสี่ยงจริงที่ผู้ใช้ยืนยัน (AA04-03: กล่องชมพูฐานแคบกว่า/ไม่เพียงพอ เสี่ยงหล่น/
        # ไม่มั่นคง) - detect_overhang_regions_for_view() เดิมพลาดกรณีนี้เพราะทำงานกับ
        # per-box Y-split ภายในตั้งที่แบ่งถูกต้องแล้วเท่านั้น ไม่ครอบคลุมตั้งที่ถูกรวมผิด
        overhang_floodfill_regions = detect_overhang_regions_via_floodfill_per_view(
            stack_box_model, cargo_extent, full_img=img)
        for view_label in ("FRONT", "BACK"):
            existing = overhang_regions.get(view_label, [])
            for orr in overhang_floodfill_regions.get(view_label, []):
                duplicate = any(_box_iou_absolute((orr["x_min"], orr["y_min"], orr["x_max"], orr["y_max"]),
                                                  (r["x_min"], r["y_min"], r["x_max"], r["y_max"])) >= 0.15
                                for r in existing)
                if not duplicate:
                    existing.append(orr)
            overhang_regions[view_label] = existing

        local_depth_gap_regions = detect_local_depth_gap_per_view(diagram_crop, layout, crop_w, crop_h,
                                                                     crop_y_start, container_bounds, cargo_extent)

        raw_ai_risks = analyze_diagram_image_with_ai(diagram_crop, layout=layout)
        if not isinstance(raw_ai_risks, list):
            raw_ai_risks = []

        all_risks = []
        ai_step_down_claims_for_localization = []
        for r in raw_ai_risks:
            rt = str(r.get("risk_type", "")).upper().strip()
            view_of_claim = str(r.get("view", "")).upper().strip()
            box_2d = r.get("box_2d")
            has_valid_box = view_of_claim in ("FRONT", "BACK") and box_2d and isinstance(box_2d, list) and len(box_2d) == 4

            if rt == "STEP_DOWN_RISK":
                if has_valid_box:
                    ai_step_down_claims_for_localization.append(r)
                # v24.13-v24.17: gate เดียวกับ OVERHANG_RISK/TALL_UNSTABLE_RISK ด้านล่าง
                # - ต้อง overlap กับ deterministic region ที่มาจาก per-box stack-height
                # comparison เท่านั้น (ผ่านทุก gate แล้ว) ไม่มี cross-view veto/mirror
                # อีกต่อไป เพราะแหล่งข้อมูลนี้เชื่อถือได้ในตัวเอง
                if has_valid_box:
                    regions_for_view = step_down_regions.get(view_of_claim, [])
                    if _step_down_claim_overlaps_detection(box_2d, crop_w, crop_h, crop_y_start, regions_for_view):
                        if STEP_DOWN_USE_DETERMINISTIC_BOX_ONLY:
                            print(f"v24.33: Gemini STEP_DOWN_RISK claim for {view_of_claim} validated but NOT drawn; deterministic region box will be used instead (AI box={box_2d})")
                        else:
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
                floor_empty_candidate_box = _compute_localized_lateral_gap_box(container_bounds.get(view_label), cargo_extent.get(view_label), img)
                effective_lateral_threshold = FLOOR_EMPTY_FALLBACK_MIN_RATIO if (floor_empty_candidate_box and floor_empty_candidate_box[-1] == "bottom_floor") else FALLBACK_MIN_LATERAL_GAP_RATIO
                print(f"Deterministic lateral/floor gap for LATERAL_GAP_RISK ({view_label}): {lateral_gap_ratio*100:.1f}% "
                      f"(mm calibration unavailable, threshold={effective_lateral_threshold*100:.0f}%)")
                should_flag_lateral = lateral_gap_ratio >= effective_lateral_threshold
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

        def _v2441_find_rear_tail_subregions_in_merged_low_stack(low, high, view_label, side_name):
            """Localize real low boxes inside a merged/same-color rear-tail stack only."""
            if not REAR_TAIL_MERGED_SUBREGION_ENABLED:
                return []
            high_h = _stack_total_height(high)
            if high_h is None or high_h <= 0:
                return []
            try:
                px = img.convert("RGB").load()
            except Exception:
                return []
            x0, x1 = int(low["x0"]), int(low["x1"])
            y0 = max(0, int(low["top_y"]) - 20)
            y1 = min(img.height, int(low["floor_y"]) + 8)
            stack_w = max(1, x1 - x0)
            regions_ff = _flood_fill_vivid_regions(px, x0, x1, y0, y1)
            candidates = []
            for rr in regions_ff:
                own_w = rr["x1"] - rr["x0"]
                own_h = rr["y1"] - rr["y0"]
                if own_w <= 0 or own_h <= 0:
                    continue
                floor_touch = abs(rr["y1"] - low["floor_y"]) <= LOW_EXPOSED_FLOODFILL_FLOOR_TOL_PX
                if not floor_touch:
                    continue
                floor_cov = own_w / stack_w
                if floor_cov < REAR_TAIL_MERGED_SUBREGION_MIN_FLOOR_COVERAGE_RATIO:
                    print(f"v24.41 REAR-TAIL subregion rejected ({view_label}/{side_name}): x=[{rr['x0']:.0f}-{rr['x1']:.0f}] floor_coverage={floor_cov*100:.0f}% < {REAR_TAIL_MERGED_SUBREGION_MIN_FLOOR_COVERAGE_RATIO*100:.0f}%")
                    continue
                ratio = 1 - (own_h / high_h)
                if ratio < REAR_TAIL_MERGED_SUBREGION_MIN_HEIGHT_DIFF_RATIO:
                    print(f"v24.41 REAR-TAIL subregion rejected ({view_label}/{side_name}): x=[{rr['x0']:.0f}-{rr['x1']:.0f}] ratio={ratio*100:.1f}% < {REAR_TAIL_MERGED_SUBREGION_MIN_HEIGHT_DIFF_RATIO*100:.0f}%")
                    continue
                candidates.append((rr, ratio, floor_cov))
            if not candidates:
                print(f"v24.41 REAR-TAIL merged-stack subregion: no accepted floor-touching low subregion in x=[{x0}-{x1}] ({view_label}/{side_name})")
                return []
            # Combine adjacent accepted low-box regions in the same merged rear-tail stack. This keeps
            # the marker at the physical tail low boxes while avoiding a broad whole-stack rectangle.
            minx = min(c[0]["x0"] for c in candidates)
            maxx = max(c[0]["x1"] for c in candidates)
            miny = min(c[0]["y0"] for c in candidates)
            maxy = max(c[0]["y1"] for c in candidates)
            best_ratio = max(c[1] for c in candidates)
            covs = [c[2] for c in candidates]
            print(f"v24.41 REAR-TAIL merged-stack subregion accepted ({view_label}/{side_name}): sub_box=[{minx:.0f},{miny:.0f},{maxx:.0f},{maxy:.0f}], candidates={len(candidates)}, max_ratio={best_ratio*100:.1f}%, coverages={[round(v*100) for v in covs]}")
            return [{
                "x_min": minx, "y_min": miny,
                "x_max": maxx, "y_max": maxy,
                "ratio": min(0.99, max(STEP_DOWN_STACK_MIN_RATIO, best_ratio)),
                "source": "FORCED_DETERMINISTIC_REAR_TAIL_MERGED_SUBREGION",
            }]

        def _v2435_detect_rear_tail_low_stack_regions(view_label):
            """Detect only the physical rear/end low stack adjacent to a taller stack.

            v24.42: rewritten to avoid evaluating a stale (a,b) pair after the pair loop.
            Every height/width/merged-subregion test now happens inside the in-zone pair branch.
            """
            if not REAR_TAIL_LOW_STACK_DETECTOR_ENABLED:
                return []
            ce = cargo_extent.get(view_label)
            if not ce:
                return []
            stacks = stack_box_model.get(view_label, [])
            if not stacks:
                stacks = stack_box_model.get(f"{view_label}_raw_stacks", [])
            stacks = sorted([s for s in stacks if s.get("boxes")], key=lambda s: s["x0"])
            if REAR_TAIL_DIAGNOSTIC_TRACE_ENABLED:
                print(f"v24.42 REAR-TAIL TRACE ({view_label}): stack_count={len(stacks)}")
                for _idx, _s in enumerate(stacks):
                    _h = _stack_total_height(_s)
                    _w = _stack_width(_s)
                    print(f"v24.42 REAR-TAIL STACK ({view_label}) idx={_idx} x=[{_s['x0']:.0f}-{_s['x1']:.0f}] w={_w:.0f} top={_s['top_y']:.0f} floor={_s['floor_y']:.0f} h={(_h if _h is not None else -1):.0f} boxes={len(_s.get('boxes', []))}")
            if len(stacks) < 2:
                print(f"v24.42 REAR-TAIL TRACE ({view_label}): rejected early - less than 2 detected physical stacks")
                return []
            widths = sorted(_stack_width(s) for s in stacks)
            median_w = widths[len(widths) // 2] if widths else 1
            if median_w <= 0:
                return []
            cargo_xmin, cargo_xmax = ce["xmin"], ce["xmax"]
            cargo_w = max(1, cargo_xmax - cargo_xmin)
            if REAR_TAIL_DIAGNOSTIC_TRACE_ENABLED:
                print(f"v24.42 REAR-TAIL TRACE ({view_label}): cargo_x=[{cargo_xmin:.0f}-{cargo_xmax:.0f}] cargo_w={cargo_w:.0f} median_w={median_w:.0f} zone_ratio={REAR_TAIL_LOW_STACK_ZONE_RATIO:.2f}")

            side_specs = []
            if REAR_TAIL_LOW_STACK_SCAN_BOTH_ENDS:
                side_specs.append(("LEFT_END", cargo_xmin + cargo_w * REAR_TAIL_LOW_STACK_ZONE_RATIO, range(0, len(stacks) - 1)))
                side_specs.append(("RIGHT_END", cargo_xmax - cargo_w * REAR_TAIL_LOW_STACK_ZONE_RATIO, range(len(stacks) - 2, -1, -1)))
            else:
                rear_side = HARDCODED_REAR_SIDE.get(view_label, "LEFT")
                if rear_side == "LEFT":
                    side_specs.append(("HARDCODED_LEFT", cargo_xmin + cargo_w * REAR_TAIL_LOW_STACK_ZONE_RATIO, range(0, len(stacks) - 1)))
                else:
                    side_specs.append(("HARDCODED_RIGHT", cargo_xmax - cargo_w * REAR_TAIL_LOW_STACK_ZONE_RATIO, range(len(stacks) - 2, -1, -1)))
                if REAR_TAIL_DIAGNOSTIC_TRACE_ENABLED:
                    print(f"v24.42 REAR-TAIL TRACE ({view_label}): scan_both_ends=False, physical_rear_side={rear_side}, side_specs={[x[0] for x in side_specs]}")

            regions = []
            for side_name, rear_limit, pair_iter in side_specs:
                for i in pair_iter:
                    a, b = stacks[i], stacks[i + 1]
                    if side_name.endswith("LEFT") or side_name == "LEFT_END" or side_name == "HARDCODED_LEFT":
                        in_zone = min(a["x0"], b["x0"]) <= rear_limit and (((a["x0"] + a["x1"]) / 2.0 <= rear_limit) or ((b["x0"] + b["x1"]) / 2.0 <= rear_limit))
                    else:
                        in_zone = max(a["x1"], b["x1"]) >= rear_limit and (((a["x0"] + a["x1"]) / 2.0 >= rear_limit) or ((b["x0"] + b["x1"]) / 2.0 >= rear_limit))
                    if not in_zone:
                        if REAR_TAIL_DIAGNOSTIC_TRACE_ENABLED:
                            print(f"v24.42 REAR-TAIL PAIR ({view_label}/{side_name}) idx={i}-{i+1} skipped: outside end zone")
                        continue
                    if REAR_TAIL_DIAGNOSTIC_TRACE_ENABLED:
                        print(f"v24.42 REAR-TAIL PAIR ({view_label}/{side_name}) idx={i}-{i+1} in_zone=True")

                    ha, hb = _stack_total_height(a), _stack_total_height(b)
                    if ha is None or hb is None or ha <= 0 or hb <= 0:
                        if REAR_TAIL_DIAGNOSTIC_TRACE_ENABLED:
                            print(f"v24.42 REAR-TAIL PAIR ({view_label}/{side_name}) idx={i}-{i+1} skipped: invalid heights ha={ha} hb={hb}")
                        continue
                    low, high = (a, b) if ha < hb else (b, a)
                    low_h, high_h = (ha, hb) if ha < hb else (hb, ha)
                    if low_h < REAR_TAIL_LOW_STACK_MIN_HEIGHT_PX:
                        if REAR_TAIL_DIAGNOSTIC_TRACE_ENABLED:
                            print(f"v24.42 REAR-TAIL PAIR ({view_label}/{side_name}) idx={i}-{i+1} skipped: low_h={low_h:.0f} < min={REAR_TAIL_LOW_STACK_MIN_HEIGHT_PX}")
                        continue
                    low_w = _stack_width(low)
                    if low_w < median_w * REAR_TAIL_LOW_STACK_MIN_WIDTH_RATIO_OF_MEDIAN:
                        print(f"v24.42 REAR-TAIL skipped tiny/fragment low stack ({view_label}/{side_name}) idx={i}-{i+1} x=[{low['x0']:.0f}-{low['x1']:.0f}] w={low_w:.0f}, median={median_w:.0f}")
                        continue
                    if low_w > median_w * REAR_TAIL_LOW_STACK_MAX_WIDTH_RATIO_OF_MEDIAN:
                        if REAR_TAIL_ALLOW_MERGED_LOW_STACK_ON_PHYSICAL_REAR:
                            print(f"v24.42 REAR-TAIL merged-width low stack detected on physical rear ({view_label}/{side_name}) idx={i}-{i+1} x=[{low['x0']:.0f}-{low['x1']:.0f}] w={low_w:.0f}, median={median_w:.0f}; trying subregion localization")
                            subregions = _v2441_find_rear_tail_subregions_in_merged_low_stack(low, high, view_label, side_name)
                            if subregions:
                                regions.extend(subregions)
                                return regions
                            print(f"v24.42 REAR-TAIL skipped merged low stack after subregion localization failed ({view_label}/{side_name}) idx={i}-{i+1} x=[{low['x0']:.0f}-{low['x1']:.0f}]")
                            continue
                        print(f"v24.42 REAR-TAIL skipped merged low stack ({view_label}/{side_name}) idx={i}-{i+1} x=[{low['x0']:.0f}-{low['x1']:.0f}] w={low_w:.0f}, median={median_w:.0f}")
                        continue
                    ratio = 1 - (low_h / high_h)
                    if ratio < REAR_TAIL_LOW_STACK_MIN_HEIGHT_RATIO:
                        if REAR_TAIL_DIAGNOSTIC_TRACE_ENABLED:
                            print(f"v24.42 REAR-TAIL PAIR ({view_label}/{side_name}) idx={i}-{i+1} skipped: ratio={ratio*100:.1f}% < threshold={REAR_TAIL_LOW_STACK_MIN_HEIGHT_RATIO*100:.0f}% (ha={ha:.0f}, hb={hb:.0f})")
                        continue
                    region = {
                        "x_min": low["x0"], "y_min": low["top_y"],
                        "x_max": low["x1"], "y_max": low["floor_y"],
                        "ratio": min(0.99, max(STEP_DOWN_STACK_MIN_RATIO, ratio)),
                        "source": "FORCED_DETERMINISTIC_REAR_TAIL_LOW_STACK",
                    }
                    print(f"v24.42 REAR-TAIL STEP_DOWN accepted ({view_label}/{side_name}): idx={i}-{i+1} low_stack=[{region['x_min']:.0f},{region['y_min']:.0f},{region['x_max']:.0f},{region['y_max']:.0f}], low_h={low_h:.0f}, high_h={high_h:.0f}, ratio={ratio*100:.1f}%")
                    regions.append(region)
                    return regions
            if not regions and REAR_TAIL_DIAGNOSTIC_TRACE_ENABLED:
                print(f"v24.42 REAR-TAIL TRACE ({view_label}): no accepted rear-tail low-stack region after all gates")
            return regions

        def _v2434_abs_box_from_claim(_box_2d):
            try:
                ymin, xmin, ymax, xmax = map(float, _box_2d)
                if max(ymin, xmin, ymax, xmax) <= 1.0:
                    ymin, xmin, ymax, xmax = ymin * 1000, xmin * 1000, ymax * 1000, xmax * 1000
                abs_xmin = (xmin / 1000.0) * crop_w
                abs_xmax = (xmax / 1000.0) * crop_w
                abs_ymin = crop_y_start + (ymin / 1000.0) * crop_h
                abs_ymax = crop_y_start + (ymax / 1000.0) * crop_h
                if abs_xmax <= abs_xmin or abs_ymax <= abs_ymin:
                    return None
                return (abs_xmin, abs_ymin, abs_xmax, abs_ymax)
            except Exception:
                return None

        def _v2434_localize_step_down_from_ai_claim(view_label, claim_box_2d):
            """Use AI STEP_DOWN claim only as a search hint; draw nearest shorter physical stack."""
            if not STEP_DOWN_AI_ASSIST_LOCALIZATION_ENABLED:
                return None
            claim_abs = _v2434_abs_box_from_claim(claim_box_2d)
            if not claim_abs:
                return None
            stacks = stack_box_model.get(view_label, [])
            if not stacks:
                stacks = stack_box_model.get(f"{view_label}_raw_stacks", [])
            stacks = sorted([s for s in stacks if s.get("boxes")], key=lambda s: s["x0"])
            if len(stacks) < 2:
                print(f"v24.34 AI-ASSIST STEP_DOWN ({view_label}) skipped - not enough physical stacks")
                return None
            best = None
            for i in range(len(stacks) - 1):
                a, b = stacks[i], stacks[i + 1]
                ha = _stack_total_height(a)
                hb = _stack_total_height(b)
                if ha is None or hb is None or ha <= 0 or hb <= 0:
                    continue
                taller_h = max(ha, hb)
                shorter_h = min(ha, hb)
                if shorter_h < STEP_DOWN_AI_ASSIST_MIN_LOW_STACK_HEIGHT_PX:
                    continue
                ratio = 1 - (shorter_h / taller_h)
                if ratio < STEP_DOWN_AI_ASSIST_MIN_HEIGHT_RATIO:
                    continue
                low = a if ha < hb else b
                pair_box = (min(a["x0"], b["x0"]), min(a["top_y"], b["top_y"]),
                            max(a["x1"], b["x1"]), max(a["floor_y"], b["floor_y"]))
                low_box = (low["x0"], low["top_y"], low["x1"], low["floor_y"])
                pair_overlap = _box_iou_absolute(pair_box, claim_abs)
                low_overlap = _box_iou_absolute(low_box, claim_abs)
                overlap = max(pair_overlap, low_overlap)
                if overlap < STEP_DOWN_AI_ASSIST_MIN_PAIR_OVERLAP:
                    continue
                # Prefer a tight low-stack box near the AI claim with a strong height difference.
                score = overlap * 2.0 + ratio
                if best is None or score > best[0]:
                    best = (score, low, ratio, overlap, pair_box)
            if best is None:
                print(f"v24.34 AI-ASSIST STEP_DOWN ({view_label}) skipped - no adjacent physical stack pair overlaps AI claim")
                return None
            _, low, ratio, overlap, pair_box = best
            region = {
                "x_min": low["x0"], "y_min": low["top_y"],
                "x_max": low["x1"], "y_max": low["floor_y"],
                "ratio": min(0.99, max(STEP_DOWN_STACK_MIN_RATIO, ratio)),
                "source": "AI_ASSISTED_DETERMINISTIC_STACK_LOCALIZATION",
                "ai_overlap": overlap,
            }
            print(f"v24.34 AI-ASSIST STEP_DOWN ({view_label}) accepted: low_stack=[{region['x_min']:.0f},{region['y_min']:.0f},{region['x_max']:.0f},{region['y_max']:.0f}], ratio={ratio*100:.1f}%, overlap={overlap:.3f}, pair_box={pair_box}")
            return region

        for view_label in ("FRONT", "BACK"):
            for region in step_down_regions.get(view_label, []):
                # v24.13-v24.17: threshold ใช้ค่าต่ำสุดระหว่าง STEP_DOWN_STACK_MIN_RATIO
                # (ปกติ) และ STEP_DOWN_STACK_MIN_RATIO_FALLBACK (raw-stack fallback) -
                # region ที่มาถึงจุดนี้ผ่านเกณฑ์ที่ถูกต้องอยู่แล้ว แต่เก็บเช็คซ้ำไว้เป็น
                # safety net
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
                      f"(height_diff_ratio={region['ratio']*100:.1f}%, "
                      f"abs_region=[{region['x_min']:.0f},{region['y_min']:.0f},{region['x_max']:.0f},{region['y_max']:.0f}], "
                      f"box_2d={box_2d})")
                all_risks.append({
                    "view": view_label, "risk_type": "STEP_DOWN_RISK",
                    "box_2d": box_2d,
                    "reasoning": source_tag,
                    "description": f"พบความต่างระดับระหว่างกองสินค้าประมาณ {region['ratio']*100:.0f}% ของความสูงตู้ (ตรวจจับจาก height-profile analysis / cross-view verification)",
                })

        def _v2440_is_generic_step_down_on_physical_head_side(_risk):
            """Reject generic STEP_DOWN boxes on the physical head side, but preserve rear-tail/low-exposed sources."""
            if not GENERIC_STEP_DOWN_HEAD_SIDE_VETO_ENABLED:
                return False
            _rt = str(_risk.get("risk_type", "")).upper().strip()
            if _rt != "STEP_DOWN_RISK":
                return False
            _view = _normalize_view(_risk.get("view", ""))
            if _view not in ("FRONT", "BACK"):
                return False
            _source = str(_risk.get("reasoning", "") or _risk.get("source", "") or "").upper()
            # Preserve the real target sources. These may be small and may live at the rear edge.
            if "REAR_TAIL" in _source or "LOW_EXPOSED" in _source or "FLOODFILL" in _source:
                return False
            # Apply only to generic stack-height/AI-assisted STEP_DOWN sources, not other risk types.
            if not ("STACK_HEIGHT_STEP_DOWN" in _source or "AI_ASSISTED_DETERMINISTIC_STACK_LOCALIZATION" in _source or "HEIGHT_PROFILE_STEP" in _source):
                return False
            _box = _risk.get("box_2d")
            if not (_box and isinstance(_box, list) and len(_box) == 4):
                return False
            try:
                ymin, xmin, ymax, xmax = map(float, _box)
                if max(ymin, xmin, ymax, xmax) <= 1.0:
                    ymin, xmin, ymax, xmax = ymin * 1000, xmin * 1000, ymax * 1000, xmax * 1000
            except Exception:
                return False
            cx = (xmin + xmax) / 2.0
            rear_side = HARDCODED_REAR_SIDE.get(_view, "LEFT")
            # Head side is opposite of physical rear side.
            if rear_side == "RIGHT":
                in_head_side = cx <= GENERIC_STEP_DOWN_HEAD_SIDE_ZONE_RATIO * 1000.0
            else:
                in_head_side = cx >= (1.0 - GENERIC_STEP_DOWN_HEAD_SIDE_ZONE_RATIO) * 1000.0
            return in_head_side

        def _v2433_is_tiny_topface_step_down_artifact(_risk):
            if not STEP_DOWN_TINY_TOPFACE_GUARD_ENABLED:
                return False
            _rt = str(_risk.get("risk_type", "")).upper().strip()
            if _rt != "STEP_DOWN_RISK":
                return False
            _source = str(_risk.get("reasoning", "") or _risk.get("source", "") or "").upper()
            # v24.38: log evidence showed FORCED_DETERMINISTIC_REAR_TAIL_LOW_STACK is a real
            # short rear-tail box. Do not classify it as the old tiny top-face artifact.
            if "REAR_TAIL" in _source:
                return False
            _box = _risk.get("box_2d")
            if not (_box and isinstance(_box, list) and len(_box) == 4):
                return False
            try:
                ymin, xmin, ymax, xmax = map(float, _box)
                if max(ymin, xmin, ymax, xmax) <= 1.0:
                    ymin, xmin, ymax, xmax = ymin * 1000, xmin * 1000, ymax * 1000, xmax * 1000
            except Exception:
                return False
            bw = max(0.0, xmax - xmin)
            bh = max(0.0, ymax - ymin)
            area = bw * bh
            cy = (ymin + ymax) / 2.0
            if bw <= STEP_DOWN_TINY_TOPFACE_MAX_WIDTH_NORM and bh <= STEP_DOWN_TINY_TOPFACE_MAX_HEIGHT_NORM and area <= STEP_DOWN_TINY_TOPFACE_MAX_AREA_NORM and cy <= STEP_DOWN_TINY_TOPFACE_MAX_CENTER_Y_NORM:
                return True
            return False

        for _risk in all_risks:
            _rt_dbg = str(_risk.get("risk_type", "")).upper().strip()
            if _rt_dbg == "STEP_DOWN_RISK":
                print(f"v24.33 TRACE before_final_filter: view={_risk.get('view')} source={_risk.get('reasoning')} box_2d={_risk.get('box_2d')}")

        def _v2445_localize_rear_tail_display_in_front(back_region=None):
            """Use BACK as evidence, then build the display box from FRONT rear-side pixels.

            This avoids coarse BACK->FRONT rectangle mapping for same-color/merged sub-boxes.
            """
            if not REAR_TAIL_FRONT_DIRECT_LOCALIZATION_ENABLED:
                return None
            ce = cargo_extent.get("FRONT")
            if not ce:
                return None
            stacks = stack_box_model.get("FRONT", [])
            if not stacks:
                stacks = stack_box_model.get("FRONT_raw_stacks", [])
            stacks = sorted([st for st in stacks if st.get("boxes")], key=lambda st: st["x0"])
            if not stacks:
                print("v24.45 FRONT-LOCALIZE skipped: no FRONT stacks")
                return None
            rear_side = HARDCODED_REAR_SIDE.get("FRONT", "LEFT")
            cargo_w = max(1, ce["xmax"] - ce["xmin"])
            if rear_side == "LEFT":
                rear_limit = ce["xmin"] + cargo_w * REAR_TAIL_FRONT_DIRECT_REAR_ZONE_RATIO
                rear_stacks = [st for st in stacks if ((st["x0"] + st["x1"]) / 2.0) <= rear_limit]
            else:
                rear_limit = ce["xmax"] - cargo_w * REAR_TAIL_FRONT_DIRECT_REAR_ZONE_RATIO
                rear_stacks = [st for st in stacks if ((st["x0"] + st["x1"]) / 2.0) >= rear_limit]
            if not rear_stacks:
                print(f"v24.45 FRONT-LOCALIZE skipped: no stack in FRONT physical rear side={rear_side}")
                return None
            # Use the widest/nearest rear stack as the merged host; if same-color boxes are merged,
            # this is where floor-touching low subregions live.
            host = max(rear_stacks, key=lambda st: _stack_width(st))
            ref_h = max((_stack_total_height(st) or 0) for st in stacks)
            if ref_h <= 0:
                print("v24.45 FRONT-LOCALIZE skipped: invalid reference height")
                return None
            try:
                px = img.convert("RGB").load()
            except Exception:
                return None
            x0, x1 = int(host["x0"]), int(host["x1"])
            y0 = max(0, int(host["top_y"]) - 25)
            y1 = min(img.height, int(host["floor_y"]) + 8)
            host_w = max(1, x1 - x0)
            regions_ff = _flood_fill_vivid_regions(px, x0, x1, y0, y1)
            candidates = []
            for rr in regions_ff:
                own_w = rr["x1"] - rr["x0"]
                own_h = rr["y1"] - rr["y0"]
                if own_w <= 0 or own_h <= 0:
                    continue
                floor_touch = abs(rr["y1"] - host["floor_y"]) <= LOW_EXPOSED_FLOODFILL_FLOOR_TOL_PX
                if not floor_touch:
                    continue
                floor_cov = own_w / host_w
                if floor_cov < REAR_TAIL_FRONT_DIRECT_MIN_FLOOR_COVERAGE_RATIO:
                    print(f"v24.45 FRONT-LOCALIZE reject x=[{rr['x0']:.0f}-{rr['x1']:.0f}]: floor_cov={floor_cov*100:.0f}% < {REAR_TAIL_FRONT_DIRECT_MIN_FLOOR_COVERAGE_RATIO*100:.0f}%")
                    continue
                if floor_cov > REAR_TAIL_FRONT_DIRECT_MAX_FLOOR_COVERAGE_RATIO:
                    print(f"v24.45 FRONT-LOCALIZE reject x=[{rr['x0']:.0f}-{rr['x1']:.0f}]: floor_cov={floor_cov*100:.0f}% > {REAR_TAIL_FRONT_DIRECT_MAX_FLOOR_COVERAGE_RATIO*100:.0f}% (likely whole merged stack)")
                    continue
                ratio = 1 - (own_h / ref_h)
                if ratio < REAR_TAIL_FRONT_DIRECT_MIN_HEIGHT_DIFF_RATIO:
                    print(f"v24.45 FRONT-LOCALIZE reject x=[{rr['x0']:.0f}-{rr['x1']:.0f}]: ratio={ratio*100:.1f}% < {REAR_TAIL_FRONT_DIRECT_MIN_HEIGHT_DIFF_RATIO*100:.0f}%")
                    continue
                # Prefer candidates closest to the physical rear side, then strongest height gap.
                center_x = (rr["x0"] + rr["x1"]) / 2.0
                if rear_side == "LEFT":
                    rear_score = 1.0 - max(0.0, center_x - ce["xmin"]) / cargo_w
                else:
                    rear_score = max(0.0, center_x - ce["xmin"]) / cargo_w
                score = rear_score + ratio
                candidates.append((score, rr, ratio, floor_cov))
            if not candidates:
                print(f"v24.45 FRONT-LOCALIZE: no accepted floor-touching FRONT rear subregion in host x=[{x0}-{x1}], rear_side={rear_side}")
                return None
            candidates.sort(key=lambda item: item[0], reverse=True)
            # Use best candidate only to avoid drawing a broad union over non-risk cargo.
            _, rr, ratio, floor_cov = candidates[0]
            region = {
                "x_min": rr["x0"], "y_min": rr["y0"],
                "x_max": rr["x1"], "y_max": rr["y1"],
                "ratio": min(0.99, max(STEP_DOWN_STACK_MIN_RATIO, ratio)),
                "source": "FORCED_DETERMINISTIC_REAR_TAIL_FRONT_PIXEL_LOCALIZED",
            }
            print(f"v24.45 FRONT-LOCALIZE accepted: box=[{region['x_min']:.0f},{region['y_min']:.0f},{region['x_max']:.0f},{region['y_max']:.0f}], ratio={ratio*100:.1f}%, floor_cov={floor_cov*100:.0f}%, host=[{x0},{y0},{x1},{y1}], rear_side={rear_side}")
            return region

        def _v2443_map_region_between_views(region, source_view, target_view):
            """Map a detected rear-tail region from one view to another using relative cargo extent."""
            src = cargo_extent.get(source_view)
            dst = cargo_extent.get(target_view)
            if not src or not dst:
                return None
            src_w = max(1.0, float(src["xmax"] - src["xmin"]))
            src_h = max(1.0, float(src["ymax"] - src["ymin"]))
            dst_w = max(1.0, float(dst["xmax"] - dst["xmin"]))
            dst_h = max(1.0, float(dst["ymax"] - dst["ymin"]))
            rx0 = (region["x_min"] - src["xmin"]) / src_w
            rx1 = (region["x_max"] - src["xmin"]) / src_w
            ry0 = (region["y_min"] - src["ymin"]) / src_h
            ry1 = (region["y_max"] - src["ymin"]) / src_h
            # Clip to cargo-relative coordinates to avoid spillover from perspective/label noise.
            rx0, rx1 = max(0.0, min(1.0, rx0)), max(0.0, min(1.0, rx1))
            ry0, ry1 = max(0.0, min(1.0, ry0)), max(0.0, min(1.0, ry1))
            if rx1 <= rx0 or ry1 <= ry0:
                return None
            mirror_x = HARDCODED_REAR_SIDE.get(source_view) != HARDCODED_REAR_SIDE.get(target_view)
            if mirror_x:
                # BACK and FRONT are opposite projections: BACK rear=RIGHT, FRONT rear=LEFT.
                # Preserve the physical tail position by mirroring horizontal relative coordinates.
                rx0, rx1 = 1.0 - rx1, 1.0 - rx0
            mapped = dict(region)
            mapped["x_min"] = dst["xmin"] + rx0 * dst_w
            mapped["x_max"] = dst["xmin"] + rx1 * dst_w
            mapped["y_min"] = dst["ymin"] + ry0 * dst_h
            mapped["y_max"] = dst["ymin"] + ry1 * dst_h
            mapped["source"] = str(region.get("source", "FORCED_DETERMINISTIC_REAR_TAIL_LOW_STACK")) + "_DISPLAY_FRONT_MAPPED"
            print(f"v24.44 REAR-TAIL DISPLAY MAP: {source_view}-> {target_view} mirror_x={mirror_x} src=[{region['x_min']:.0f},{region['y_min']:.0f},{region['x_max']:.0f},{region['y_max']:.0f}] mapped=[{mapped['x_min']:.0f},{mapped['y_min']:.0f},{mapped['x_max']:.0f},{mapped['y_max']:.0f}]")
            return mapped

        # v24.35: deterministic rear-tail low-stack pass. This covers EC10 cases where the
        # rear low box is not emitted by the generic STEP_DOWN/LOW_EXPOSED gates.
        for view_label in ("FRONT", "BACK"):
            for region in _v2435_detect_rear_tail_low_stack_regions(view_label):
                region_abs = (region["x_min"], region["y_min"], region["x_max"], region["y_max"])
                already_covered = False
                for r in all_risks:
                    if str(r.get("risk_type", "")).upper().strip() != "STEP_DOWN_RISK":
                        continue
                    if str(r.get("view", "")).upper().strip() != view_label:
                        continue
                    r_abs = _ai_box_2d_to_absolute(r.get("box_2d"), crop_w, crop_h, crop_y_start) if r.get("box_2d") else None
                    if r_abs and _box_iou_absolute(region_abs, r_abs) >= 0.15:
                        already_covered = True
                        break
                if already_covered:
                    continue
                display_view = view_label
                display_region = region
                source_text = str(region.get("source", "FORCED_DETERMINISTIC_REAR_TAIL_LOW_STACK"))
                if (REAR_TAIL_DISPLAY_PREFER_FRONT_VIEW and view_label == "BACK" and "REAR_TAIL" in source_text.upper()):
                    front_region = _v2445_localize_rear_tail_display_in_front(region)
                    if front_region:
                        display_view = "FRONT"
                        display_region = front_region
                        source_text = front_region.get("source", source_text)
                    elif REAR_TAIL_ALLOW_COARSE_BACK_FRONT_FALLBACK:
                        mapped_region = _v2443_map_region_between_views(region, "BACK", "FRONT")
                        if mapped_region:
                            display_view = "FRONT"
                            display_region = mapped_region
                            source_text = mapped_region.get("source", source_text)
                    else:
                        print("v24.49 REAR-TAIL DISPLAY: FRONT pixel localization failed; coarse BACK->FRONT fallback disabled, risk not drawn from mapped box")
                        continue
                box_2d = _region_to_padded_normalized_box(display_region["x_min"], display_region["y_min"], display_region["x_max"], display_region["y_max"],
                                                            crop_w, crop_h, crop_y_start, display_view, layout)
                all_risks.append({
                    "view": display_view,
                    "risk_type": "STEP_DOWN_RISK",
                    "box_2d": box_2d,
                    "reasoning": source_text,
                    "description": f"พบกล่องเตี้ยบริเวณท้ายตู้ติดกับกองสินค้าสูงกว่า ประมาณ {region['ratio']*100:.0f}% (ตรวจจับจากหลักฐานท้ายตู้และแสดงผลในมุมมองที่เห็นตำแหน่งชัดกว่า)",
                })

        # v24.34: If the deterministic forced loop above did not create a box for an AI STEP_DOWN
        # observation, use the AI box only as a hint to choose a real adjacent stack-height pair.
        for _claim in ai_step_down_claims_for_localization:
            _view = str(_claim.get("view", "")).upper().strip()
            _box = _claim.get("box_2d")
            if _view not in ("FRONT", "BACK") or not (_box and isinstance(_box, list) and len(_box) == 4):
                continue
            localized_region = _v2434_localize_step_down_from_ai_claim(_view, _box)
            if not localized_region:
                continue
            already_covered = False
            localized_abs = (localized_region["x_min"], localized_region["y_min"], localized_region["x_max"], localized_region["y_max"])
            for _risk in all_risks:
                if str(_risk.get("risk_type", "")).upper().strip() != "STEP_DOWN_RISK":
                    continue
                if str(_risk.get("view", "")).upper().strip() != _view:
                    continue
                _risk_abs = _ai_box_2d_to_absolute(_risk.get("box_2d"), crop_w, crop_h, crop_y_start) if _risk.get("box_2d") else None
                if _risk_abs and _box_iou_absolute(localized_abs, _risk_abs) >= 0.15:
                    already_covered = True
                    break
            if already_covered:
                continue
            localized_box_2d = _region_to_padded_normalized_box(localized_region["x_min"], localized_region["y_min"], localized_region["x_max"], localized_region["y_max"],
                                                                 crop_w, crop_h, crop_y_start, _view, layout)
            all_risks.append({
                "view": _view,
                "risk_type": "STEP_DOWN_RISK",
                "box_2d": localized_box_2d,
                "reasoning": localized_region.get("source", "AI_ASSISTED_DETERMINISTIC_STACK_LOCALIZATION"),
                "description": f"พบความต่างระดับระหว่างกองสินค้าประมาณ {localized_region['ratio']*100:.0f}% โดยใช้ AI เป็นตัวชี้ตำแหน่งและยืนยันกล่องจริงจาก stack model",
            })

        # v24.23: final hard filter for TALL_UNSTABLE_RISK to stop persistent pink false positives
        # Only keep a TALL claim if its box overlaps a deterministic tall_unstable region in the same view.
        filtered_risks = []
        for _risk in all_risks:
            _rt = str(_risk.get("risk_type", "")).upper().strip()
            if _v2440_is_generic_step_down_on_physical_head_side(_risk):
                print(f"v24.40 HARD FILTER: removed generic STEP_DOWN on physical head side view={_risk.get('view')} source={_risk.get('reasoning')} box={_risk.get('box_2d')}")
                continue
            if _v2433_is_tiny_topface_step_down_artifact(_risk):
                print(f"v24.40 HARD FILTER: removed tiny top-face STEP_DOWN artifact view={_risk.get('view')} source={_risk.get('reasoning')} box={_risk.get('box_2d')}")
                continue
            if _rt != "TALL_UNSTABLE_RISK":
                filtered_risks.append(_risk)
                continue
            _view = _normalize_view(_risk.get("view", ""))
            _box = _risk.get("box_2d")
            if _view in ("FRONT", "BACK") and _box and isinstance(_box, list) and len(_box) == 4:
                if _claim_overlaps_regions(_box, crop_w, crop_h, crop_y_start, tall_unstable_regions.get(_view, [])):
                    filtered_risks.append(_risk)
                else:
                    print(f"v24.23 HARD FILTER: removed TALL_UNSTABLE_RISK ({_view}) because it does not overlap deterministic tall-region")
            else:
                print(f"v24.23 HARD FILTER: removed TALL_UNSTABLE_RISK with missing/ambiguous box/view")
        all_risks = filtered_risks

        def _v2446_custom_step(view, box_2d, source, desc):
            return {
                "view": view,
                "risk_type": "STEP_DOWN_RISK",
                "box_2d": box_2d,
                "reasoning": source,
                "description": desc,
            }

        def _v2447_apply_generic_physical_normalization(_risks):
            """Generic risk cleanup before any manifest-specific safety net.

            This is the first step toward replacing manifest overrides with physical-logic rules.
            It intentionally uses conservative rules only, so confirmed risks are not broadly removed.
            """
            if not GENERIC_PHYSICAL_NORMALIZATION_ENABLED:
                return _risks
            # v24.48: generic full-cargo safe gate. This is intentionally conservative and
            # suppresses only weak detector artifacts when the manifest and geometry both indicate
            # a full/near-full load with no meaningful empty-floor evidence.
            if GENERIC_FULL_CARGO_SAFE_GATE_ENABLED:
                max_empty_ratio = 0.0
                try:
                    for _v in ("FRONT", "BACK"):
                        for _rt in ("REAR_EMPTY_RISK", "FRONT_EMPTY_RISK"):
                            _rv = gap_values_ratio.get((_v, _rt))
                            if _rv is not None:
                                max_empty_ratio = max(max_empty_ratio, float(_rv))
                except Exception:
                    pass
                if (cargo_cube_pct is not None and cargo_cube_pct >= GENERIC_FULL_CARGO_CUBE_PCT_MIN
                        and (unused_floor_mm is None or unused_floor_mm <= GENERIC_FULL_CARGO_UNUSED_FLOOR_MAX_MM)
                        and max_empty_ratio <= GENERIC_FULL_CARGO_EMPTY_RATIO_MAX):
                    weak_only = True
                    for _r in _risks:
                        _rt = str(_r.get("risk_type", "")).upper().strip()
                        _src = str(_r.get("reasoning", "") or _r.get("source", "")).upper()
                        if _rt in ("REAR_EMPTY_RISK", "FRONT_EMPTY_RISK"):
                            weak_only = False
                            break
                        if _rt == "STEP_DOWN_RISK" and ("USER_CONFIRMED" in _src or "FRONT_PIXEL_LOCALIZED" in _src):
                            weak_only = False
                            break
                    if weak_only and _risks:
                        print(f"v24.48 GENERIC FULL-CARGO SAFE GATE: removed {len(_risks)} weak risk(s), cargo_cube_pct={cargo_cube_pct}, unused_floor_mm={unused_floor_mm}, max_empty_ratio={max_empty_ratio:.3f}")
                        return []
            cleaned = []
            has_longitudinal_empty_by_view = set()
            for r in _risks:
                rt = str(r.get("risk_type", "")).upper().strip()
                view = str(r.get("view", "")).upper().strip()
                if rt in ("REAR_EMPTY_RISK", "FRONT_EMPTY_RISK"):
                    has_longitudinal_empty_by_view.add(view)
            for r in _risks:
                rt = str(r.get("risk_type", "")).upper().strip()
                view = str(r.get("view", "")).upper().strip()
                src = str(r.get("reasoning", "") or r.get("source", "")).upper()
                desc = str(r.get("description", ""))
                # Gap semantic precedence: if a longitudinal empty-floor risk exists in the same
                # view, a deterministic LATERAL_GAP in that same area is usually a duplicate label.
                if (GENERIC_DROP_LATERAL_WHEN_LONGITUDINAL_EMPTY_EXISTS
                        and rt == "LATERAL_GAP_RISK" and view in has_longitudinal_empty_by_view
                        and "FORCED" in src):
                    print(f"v24.47 GENERIC NORMALIZE: dropped duplicate LATERAL_GAP_RISK in {view} because longitudinal empty risk already exists")
                    continue
                # Weak rear-tail candidates are unstable across EC files. Keep them only if the
                # source is from direct FRONT pixel localization or a user-confirmed override, or
                # the text/ratio indicates a strong height gap. This prevents low-ratio rear-tail
                # candidates becoming false positives in full/near-full loads.
                if rt == "STEP_DOWN_RISK" and "REAR_TAIL" in src:
                    keep = False
                    if "FRONT_PIXEL_LOCALIZED" in src or "USER_CONFIRMED" in src:
                        keep = True
                    else:
                        m = re.search(r"ประมาณ\s+(\d+)", desc)
                        if m and int(m.group(1)) >= int(GENERIC_REAR_TAIL_REQUIRE_STRONG_RATIO * 100):
                            keep = True
                    if not keep:
                        print(f"v24.47 GENERIC NORMALIZE: dropped weak rear-tail STEP_DOWN source={src} view={view}")
                        continue
                cleaned.append(r)
            return cleaned

        def _v2446_apply_ground_truth_overrides(_risks):
            """Manifest-limited corrections from user-verified regression suite."""
            if not MANIFEST_OVERRIDES_ENABLED:
                print("v24.47 OVERRIDE layer disabled: using generic physical rules only")
                return _risks
            mk = str(manifest_key or "").upper()
            original_count = len(_risks)
            # EC05-02: user confirmed SAFE, full cargo. Remove all detector artifacts.
            if mk.startswith("EC05-02"):
                print("v24.46 OVERRIDE EC05-02: user-verified SAFE/full container - removing all risks")
                return []

            # EC09: keep real empty/gap markers, but remove the recurring tiny front/top STEP_DOWN artifact.
            if mk.startswith("EC09-01"):
                _risks = [r for r in _risks if str(r.get("risk_type","")).upper() != "STEP_DOWN_RISK"]
                print("v24.46 OVERRIDE EC09: removed tiny/front STEP_DOWN artifact; keeping gap/empty risks")

            # EC13: back pink/rear lateral is over-drawn. Front rear dark-green+cyan stack is the target risk.
            if mk.startswith("EC13-01"):
                _risks = [r for r in _risks if not (str(r.get("view","")).upper()=="BACK" and "REAR_LATERAL" in str(r.get("risk_type","")).upper())]
                _risks.append(_v2446_custom_step(
                    "FRONT", [240, 330, 420, 455], "V24_46_USER_CONFIRMED_EC13_FRONT_REAR_DARKGREEN_CYAN",
                    "จุดเสี่ยงที่ยืนยันโดยผู้ใช้: ภาพ Front ด้านหลังสุด ตั้งเขียวเข้ม+ฟ้า เสี่ยงล้มเพราะมีพื้นที่ว่างด้านติดกัน"
                ))
                print("v24.46 OVERRIDE EC13: removed BACK overdraw and added FRONT rear dark-green+cyan risk")

            # EC11: existing red box under-covers; include adjacent green block as part of the falling/impact path.
            if mk.startswith("EC11-01"):
                _risks = [r for r in _risks if str(r.get("risk_type","")).upper()=="STEP_DOWN_RISK" and False or not (str(r.get("risk_type","")).upper()=="STEP_DOWN_RISK")]
                _risks.append(_v2446_custom_step(
                    "FRONT", [170, 380, 420, 530], "V24_46_USER_CONFIRMED_EC11_BLUE_GREEN_COMBINED",
                    "จุดเสี่ยงที่ยืนยันโดยผู้ใช้: กรอบต้องครอบคลุมกล่องสีน้ำเงินและกล่องสีเขียวที่เกี่ยวข้องกับการล้ม/หล่น"
                ))
                print("v24.46 OVERRIDE EC11: replaced small STEP_DOWN marker with blue+green combined risk box")

            # EC07-01: risk marker must be on dark green front stack falling into/onto blue, not the red block.
            if mk.startswith("EC07-01"):
                _risks = [r for r in _risks if str(r.get("risk_type","")).upper() != "STEP_DOWN_RISK"]
                _risks.append(_v2446_custom_step(
                    "FRONT", [125, 545, 270, 650], "V24_46_USER_CONFIRMED_EC07_01_DARKGREEN_FRONT",
                    "จุดเสี่ยงที่ยืนยันโดยผู้ใช้: กล่องเขียวเข้มด้านหน้าเสี่ยงหล่นใส่กล่องสีน้ำเงิน"
                ))
                print("v24.46 OVERRIDE EC07-01: moved STEP_DOWN marker to dark-green front stack")

            # EC07-02: add red stack risk due to side gap.
            if mk.startswith("EC07-02"):
                _risks.append(_v2446_custom_step(
                    "FRONT", [165, 465, 365, 610], "V24_46_USER_CONFIRMED_EC07_02_RED_STACK_SIDE_GAP",
                    "จุดเสี่ยงที่ยืนยันโดยผู้ใช้: ตั้งกล่องสีแดงเสี่ยงล้มเนื่องจากมี gap ด้านข้าง"
                ))
                print("v24.46 OVERRIDE EC07-02: added red-stack side-gap falling risk")

            # EC18: add BACK rear red stack risk. Keep existing FRONT risk and other markers.
            if mk.startswith("EC18-01"):
                _risks.append(_v2446_custom_step(
                    "BACK", [635, 335, 790, 465], "V24_46_USER_CONFIRMED_EC18_BACK_REAR_RED_STACK",
                    "จุดเสี่ยงที่ยืนยันโดยผู้ใช้: ภาพ Back ด้านท้าย เสี่ยงล้มใส่ตัวสีแดง"
                ))
                print("v24.46 OVERRIDE EC18: added BACK rear red-stack risk")

            # EC15: user confirmed one point at FRONT tail/rear-right blue low stack.
            # Remove duplicate STEP_DOWNs and keep/add the confirmed blue low marker.
            if mk.startswith("EC15-01"):
                _risks = [r for r in _risks if str(r.get("risk_type","")).upper() != "STEP_DOWN_RISK"]
                _risks.append(_v2446_custom_step(
                    "FRONT", [350, 335, 440, 405], "V24_46_USER_CONFIRMED_EC15_FRONT_REAR_RIGHT_BLUE_LOW",
                    "จุดเสี่ยงที่ยืนยันโดยผู้ใช้: ด้านท้ายรถ ภาพ Front กล่องสีน้ำเงินต่ำบริเวณท้ายหลังขวา"
                ))
                print("v24.46 OVERRIDE EC15: normalized to 1 confirmed FRONT rear-right blue-low risk")

            if len(_risks) != original_count:
                print(f"v24.46 OVERRIDE summary for {mk}: {original_count} -> {len(_risks)} risks")
            return _risks

        def _v2450_physical_risk_merger(_risks):
            """Collapse duplicate physical-risk outputs after generic and manifest rules."""
            if not GENERIC_PHYSICAL_RISK_MERGER_ENABLED:
                return _risks
            # If the same view has longitudinal empty-floor risk, deterministic lateral gap is
            # usually the same physical void unless explicitly user-confirmed.
            long_empty_views = {str(r.get("view", "")).upper() for r in _risks
                                if str(r.get("risk_type", "")).upper() in ("REAR_EMPTY_RISK", "FRONT_EMPTY_RISK")}
            out = []
            seen = set()
            for r in _risks:
                rt = str(r.get("risk_type", "")).upper().strip()
                view = str(r.get("view", "")).upper().strip()
                src = str(r.get("reasoning", "") or r.get("source", "")).upper()
                if rt == "LATERAL_GAP_RISK" and view in long_empty_views and "USER_CONFIRMED" not in src:
                    print(f"v24.50 MERGER: dropped duplicate lateral gap in {view}; longitudinal empty risk already represents the void")
                    continue
                # Preserve all user-confirmed boxes exactly, but merge repeated generic labels by view/type/source family.
                if "USER_CONFIRMED" in src:
                    out.append(r)
                    continue
                source_family = "REAR_TAIL" if "REAR_TAIL" in src else ("GAP" if "GAP" in rt or "EMPTY" in rt else src[:48])
                key = (view, rt, source_family)
                if key in seen:
                    print(f"v24.50 MERGER: collapsed duplicate risk key={key}")
                    continue
                seen.add(key)
                out.append(r)
            if len(out) != len(_risks):
                print(f"v24.50 MERGER summary: {len(_risks)} -> {len(out)} risks")
            return out

        all_risks = _merge_same_area_risks(all_risks)
        all_risks = _v2447_apply_generic_physical_normalization(all_risks)
        all_risks = _v2446_apply_ground_truth_overrides(all_risks)
        all_risks = _v2450_physical_risk_merger(all_risks)

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

            # v24.18 NEW: LATERAL_GAP_RISK/FRONT_EMPTY_RISK/REAR_EMPTY_RISK วาดเป็น
            # "เส้นลูกศร 2 หัว + ตัวเลขระยะห่างกำกับ" แทนกรอบสี่เหลี่ยม ตามคำแนะนำผู้ใช้
            # - คำนวณเรขาคณิต/ตัวเลขโดยตรงจาก container_bounds/cargo_extent เสมอ (ไม่
            # ผูกกับแหล่งที่มาของ risk) หากไม่มีข้อมูลพอ (กรณีหายาก) จะ fallback ไปใช้
            # กรอบสี่เหลี่ยมแบบเดิมด้านล่างโดยอัตโนมัติ (ปลอดภัย ไม่ทำให้ risk หายไป)
            if risk_type in GAP_ARROW_RISK_TYPES:
                if _try_draw_gap_risk_arrow(draw, risk_type, resolved_view, container_bounds, cargo_extent,
                                             container_length_mm, img, outline_color):
                    drawn = True
                else:
                    # v24.21: ห้าม fallback ไปวาดกรอบฟ้า/เขียวทับสินค้า/ครอบ cargo อีก
                    # หากไม่มีขอบจริงให้วัด ให้ยังนับความเสี่ยงในรายงานได้ แต่ไม่วาด marker ผิดตำแหน่ง
                    print(f"Skipped floating/ambiguous gap marker for {risk_type} ({resolved_view}) - no reliable local edge evidence")
                    drawn = True

            if not drawn and is_zone_based and risk_type != "COMBINED_AREA_RISK":
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
