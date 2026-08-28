"""
================================================================================
AI Cargo Safety Checker - v25.22 ZERO-AI EDITION
================================================================================
v25.53 (แก้ REAR_EMPTY_RISK false-positive เชิงระบบ ที่ BACK view มักถูก mark เกือบทุกไฟล์ +
เพิ่ม STEP_DOWN_RISK floor_jump mechanism):

  ส่วนที่ 1 - REAR_EMPTY_RISK "extended length" (สำคัญ - ผู้ใช้สังเกตว่า mark BACK เกือบ 100%
  ของเวลา ผิดปกติเกินกว่าจะบังเอิญ): ตรวจสอบข้าม 24 ไฟล์พบว่า "ช่องว่างฝั่งหัวตู้" ของ BACK
  (start_x เดิม ถึงมุมผนังจริง) สูงผิดปกติ 100-150px แทบทุกไฟล์ ในขณะที่ FRONT มีช่องว่างฝั่ง
  เดียวกันแค่ 3-30px เท่านั้น (ยืนยันด้วยภาพว่ากล่องชิดผนังหัวตู้จริง ไม่ใช่ช่องว่างจริง)

  ROOT CAUSE: กล่องที่ตำแหน่งใกล้ผนังหัวตู้ที่สุดในมุมมอง BACK มักมี "หน้าข้าง (side face)"
  ของกล่องโผล่ให้เห็นก่อนถึง front-face หลัก (เพราะความลึกของกล่องในมุมมอง isometric) - หน้า
  ข้างนี้มีสีสดจริง (ยืนยันจาก AA02-01: พบสีเขียว (123,255,70) ที่ cargo_bottom_y ตลอดช่วง
  x=604-742) แต่ไม่ผ่านเกณฑ์ 'grounded' (gap_thresh=30) เพราะใต้หน้าข้างนี้เป็นสีผนังด้านข้าง
  ตู้ (255,255,147) ไม่ใช่สีพื้นตู้จริง (ระยะห่างจาก cargo_bottom_y ถึง floor สีโครงสร้างที่แท้
  จริงจึงไกลเกิน 30px มาก - วัดได้จริง 95-99px) ทำให้ทั้ง grounded-based fallback และ Phase 1B
  (ซึ่งนับเฉพาะ front-face fragment ไม่รวมหน้าข้าง) พลาดพื้นที่กล่องจริงนี้ไปพร้อมกันทั้งคู่ ทำ
  ให้ start_x/end_x/length_px (Phase 2) ของ BACK สั้นกว่าความเป็นจริงอย่างเป็นระบบ

  ทดลองแก้ x_min_/x_max_ ใน process_view_on_image โดยตรงก่อน (ซึ่งใช้ร่วมกันทั้งการหา seam/
  boundary ของคอลัมน์และการวัดความสูง) พบว่ากระทบ STEP_DOWN_RISK ในหลายไฟล์อย่างกว้างขวางเกิน
  กว่าจะยืนยันความปลอดภัยได้ทันที (ตามที่ผู้ใช้ชี้ให้ระวัง) จึงเปลี่ยนแนวทาง:

  FIX: คำนวณ "ความยาวขยาย" (extended length, ดูฟังก์ชัน _p1b_extended_length_for_rear_check)
  แยกต่างหาก เฉพาะสำหรับ REAR_EMPTY_RISK เท่านั้น โดยใช้ cargo_mask ดิบ (ผ่านการกรอง arrow_mask
  + min_blob_size แล้วจาก vivid_cargo_mask - ปลอดภัยจากตัวอักษร/เส้นบอกระยะที่เป็นจุดเล็กๆ
  กระจัดกระจาย) ขยาย start_x/end_x เดิม (จาก Phase 2) ให้ครอบคลุมสีสดใดๆ ที่พบเพิ่มเติม - ไม่แตะ
  x_min_/x_max_ เดิมที่ใช้คำนวณ seam/height เลย (แยกผลกระทบออกจากกันชัดเจน 100%)

  regression-verified ครบ 24 ไฟล์: STEP_DOWN_RISK ไม่เปลี่ยนแปลงแม้แต่จุดเดียว (นอกจาก floor_
  jump ใหม่ที่ AC03-01 - ดูส่วนที่ 2) REAR_EMPTY_RISK: AA02-01/AB05-01 หาย false-positive ที่
  เคยรายงานผิดพลาด (ยืนยันจากภาพ), AB02-01/AB04-02/AC02-02 สลับ subtype (length_mismatch<->
  color_anomaly) แต่ mark ตำแหน่งเดิม (ไม่ใช่จุดใหม่), AB03-03/AC03-01 เพิ่มจุดใหม่ที่ยืนยันด้วย
  ภาพจริงแล้วว่าถูกต้อง (มีป้ายบอกระยะช่องว่างจริงในภาพ เช่น "1112 (mm)" ที่ AB03-03) ไฟล์ที่
  เหลือทั้งหมดไม่เปลี่ยนแปลงเลย

  ข้อจำกัดที่ยังไม่ได้แก้ (บอกตรงไปตรงมา): AB05-02 (สีกล่อง 255,255,147 ชนกับสีผนังปลายตู้จริง)
  ยัง "ไม่หายขาด 100%" - gap ลดลงจาก 19.8% เหลือ 7.8% แต่ยังเกินเกณฑ์ 6% เล็กน้อย เพราะ FRONT
  ก็ถูกขยายไปด้วยเช่นกัน (คาดว่าเป็นข้อจำกัดของวิธี cargo_mask-based ที่ไม่สามารถแยกแยะสีที่ชน
  กันระหว่าง "ผนังจริง" กับ "กล่องจริง" ได้ 100% - ดู CHANGELOG v25.52 สำหรับรายละเอียดการ
  วิเคราะห์ที่พิสูจน์แล้วว่าไม่มีสัญญาณ pixel ใดแยกแยะ 2 กรณีนี้ได้)

  ส่วนที่ 2 - STEP_DOWN_RISK floor_jump mechanism (v25.52 เดิม): เพิ่มกลไก "floor_jump" ในโซน
  ก้ำกึ่ง (drop_ratio 12.5%-20%) เพื่อจับกรณี step-down จริงที่มีรอยต่างระดับพื้นตู้จริง (ไม่ใช่
  แค่ความชันธรรมชาติจากมุมมอง isometric) - ยืนยันด้วยข้อมูลจริงจาก AC03-01 (floor_jump=+20.5px)
  เทียบกับ 2 เคส false-positive ที่ยืนยันแล้ว (AA02-01=0.0px, AB05-01=9.7px) - แก้ไขเพิ่มเติมให้
  mark ที่ "กองเตี้ยกว่า (shorter_rec)" แทนที่จะเป็น "กองสูงกว่า" ตามที่ผู้ใช้ยืนยันด้วยภาพจริง
  (ไม่กระทบ pairwise เกณฑ์ 20% เดิมที่ยัง mark กองสูงกว่าเหมือนเดิม - คนละ subtype กัน)
================================================================================
v25.51 (แก้บั๊กจากผลทดสอบจริง 57 ไฟล์ - พบ 3 ไฟล์ที่บริเวณหน้าตู้ (FRONT) ไม่วาดกรอบแดง
STEP_DOWN_RISK ทั้งที่ควรมี: AC02-02, AB02-02 และไฟล์ที่ทำให้ column-width ผิดปกติ):

  ROOT CAUSE (ยืนยันด้วยข้อมูลจริงทั้ง AC02-02 และ AB02-02): ฟังก์ชัน _p1b_classify_view
  ตัดสินใจ kind0 ('front'/'roof'/'side') ของแต่ละสี จาก aspect ratio ของ "ชิ้นส่วนดิบ"
  (raw component) ก่อน merge เพียงครั้งเดียว - พบว่ากล่องจริงบางใบที่มีขนาดเล็ก/บาง หรืออยู่
  ริมมุมกล้อง (AIA1A สีน้ำเงิน ใน AC02-02, SEWTA สีฟ้า ใน AC02-02) มี front-face ที่ถูกเงา/
  เส้นแบ่งตัดเป็นแถบแนวนอนบางๆ หลายแถบ (isometric shading) ทำให้ "แต่ละแถบดิบ" มี aspect
  ratio ต่ำ (กว้างกว่าสูง, aspect<0.85) จึงถูกจัดเป็น kind0='roof' ทั้งหมด ทั้งที่รวมกันแล้ว
  คือ front-face จริงของกล่องที่สูงเพรียว (ยืนยันจากข้อมูลจริง AC02-02: AIA1A รวมแถบ roof
  แล้วได้ w=117,h=126,aspect=1.08 / SAB1A ใน AB02-02 รวมแล้ว w=116,h=186,aspect=1.60 -
  ทั้งคู่ >=0.85 ชัดเจนว่าเป็น front-face จริง ไม่ใช่ roof)
  ผลกระทบ: สีเหล่านี้ไม่เคยมี 'front' candidate เลยแม้แต่ชิ้นเดียว -> ไม่มีสิทธิ์เข้า
  _p1b_cluster_columns (อ่านจาก 'fronts' list เท่านั้น) และไม่มีสิทธิ์รวมเป็นคอลัมน์เดียวกับ
  กล่องข้างเคียงผ่านกฎ multi-color-per-idx (CLUSTER_DIFF_COLOR_MIN_XOVERLAP) เหลือเพียง
  ทางเดียวคือ orphaned-roof detection ซึ่งพบว่าล้มเหลวด้วยในหลายเคส (ถูกตัดสินว่า "มีตัวแทน
  อยู่แล้ว" อย่างผิดพลาด เพราะ any-color coverage สูงจากคอลัมน์ข้างเคียงคนละสีที่บังเอิญ
  x-range ทับกันพอดี - กรณี AIA1A ที่ x-range ทับกับ TAP1A-F1 พอดี) ทำให้กล่องเหล่านี้หายไป
  จากผลลัพธ์ทั้งหมด ไม่มีการวัดความสูงแยกเลย -> STEP_DOWN_RISK ที่ควรพบ (กล่องเตี้ยกว่า
  เพื่อนบ้านชัดเจนถึง 55% ในกรณี AC02-02's AIA1A) ไม่ถูกตรวจพบ - นอกจากนี้ยังทำให้ column
  width ผิดปกติ (แคบผิดธรรมชาติ เช่น 21-24px เทียบกับปกติ ~90px ใน AB02-02) เพราะ Hungarian
  reconcile ต้องยัด/บีบคอลัมน์ที่เหลือให้พอดีกับจำนวนตำแหน่งจาก BACK

  FIX: ใน _p1b_classify_view หลัง merge ชิ้นส่วนภายใน kind0='roof' แล้ว ตรวจสอบ aspect ของ
  ก้อนที่ merge แล้ว (ไม่ใช่ชิ้นดิบ) อีกครั้ง - ถ้า merged aspect >= 0.85 (สัดส่วนสูงกว่ากว้าง
  แบบ front-face จริง) และ mean_sat >= 0.75 (สีสดพอจะเป็น front ไม่ใช่ side) ให้ reclassify
  เป็น kind='front' แทนที่จะปล่อยไว้เป็น 'roof' - ปลอดภัยเพราะ:
    1) merge ภายใน kind0 เดียวกันใช้เกณฑ์ x_tol=12/w_tol=25 เข้มงวดอยู่แล้ว (ต้องมีตำแหน่ง/
       ความกว้างใกล้เคียงกันจริงเท่านั้นจึงจะ merge ได้ - ไม่ได้เปิดกว้างให้ merge มั่วซั่ว)
    2) 'roof' ทรงสี่เหลี่ยมขนมเปียกปูนจริง (หลังคากล่องเดี่ยว หรือ roofline staircase) ตาม
       ธรรมชาติของมุมมอง isometric จะยังคง "กว้างกว่าสูง" อยู่แม้ merge กับชิ้นเดียวสีเดียวกัน
       แล้วก็ตาม (ไม่มีกรณีในไฟล์ regression ทั้งหมดที่ roof merge แล้วมี aspect>=0.85 โดย
       ไม่ใช่ front จริงเลย)
    3) แม้ reclassify ผิดพลาดในบางเคสที่ไม่เคยเจอ ก็ยังมีกลไก inner-row-roof-anchor filter
       (v25.27) และ side-sliver filter (v25.27) ทำงานต่อเป็นด่านที่ 2 อยู่แล้ว (กรอง fragment
       ที่พิสูจน์ได้ว่าเป็นแถวในซ้ำซ้อน/เศษบางออกอีกชั้น ก่อนเข้า cluster_columns จริง)

  regression-verified (รันซ้ำ 5 ไฟล์จริงที่มีอยู่): AA02-01/AB01-02/AB02-02/AB03-02 ได้
  hazardCount และตำแหน่ง risk (risk_type, subtype, mark_view, mark_stack_idx) เหมือนเดิม
  ทุกประการ 100% (AB02-02 มี 1 จุดที่ mark_stack_idx ขยับจาก 1->2 เพราะ column boundary
  กว้างขึ้นถูกต้องกว่าเดิม แต่ abs_box ตำแหน่งพิกเซลจริงยังคงเริ่มที่ x=819 เหมือนเดิม - เป็น
  จุดเดียวกันแค่ idx เปลี่ยนเพราะนับคอลัมน์ต่างไป ไม่ใช่ marker ผิดตำแหน่งใหม่) - AC02-02
  hazardCount เพิ่มจาก 4 เป็น 5 ถูกต้อง (พบ STEP_DOWN_RISK ทั้ง pairwise(BACK)+cross_view
  ของ AIA1A ที่เคยพลาดไปก่อนหน้า - drop_ratio วัดได้สูงถึง 50-55%) - ไม่พบ false-positive
  ใหม่ในไฟล์ใดเลย
================================================================================
v25.48 (แก้ 2 บั๊กที่ผู้ใช้แนบไฟล์จริง AA02-01/AA05-03 - กรอบแดง STEP_DOWN_RISK ปลอมใน
BACK view ที่ผู้ใช้ระบุว่า "เกินมา" ควรลบทิ้ง):

  บั๊ก#1 - orphaned-roof (v25.46) สร้างคอลัมน์ปลอมใน BACK: AA02-01 BACK มีหลังคาสีฟ้า
  (MAPCA, w=205px) แทรกอยู่ระหว่างคอลัมน์สีเขียว (DSC1A) 2 คอลัมน์ที่นับไปแล้วครบถ้วน -
  เกณฑ์ coverage เดิม (v25.46, ดู _p1b_find_orphaned_roof_columns) เช็คเฉพาะคอลัมน์ "สี
  เดียวกับ roof" เท่านั้น (same-color) ทำให้คอลัมน์เขียว (คนละสีกับฟ้า) ไม่ถูกนับเป็น
  coverage เลย (0%) ทั้งที่ในเชิงพื้นที่ union ของ 2 คอลัมน์เขียวครอบคลุมหลังคาฟ้าถึง 99%
  (แทบไม่มีช่องว่างเหลือให้กล่องอื่นซ่อนอยู่จริง) -> เข้าใจผิดว่าเป็น orphaned roof จริง ->
  สร้างคอลัมน์ synthetic แทรกกลาง -> BACK ได้ 6 คอลัมน์ (5 จริง+1 ปลอม) ตรงกับ FRONT (6
  คอลัมน์) โดยบังเอิญ -> Hungarian matching จับคู่ผิดตำแหน่งทั้งกระดาน -> STEP_DOWN_RISK
  ปลอมที่ตำแหน่งซึ่งกล่องสูงใกล้เคียงกันจริง (ยืนยันด้วยภาพจริงที่ผู้ใช้แนบ + zoom-crop
  พิสูจน์ว่ากล่อง ASI1A ทั้ง 2 คอลัมน์สูงเท่ากันเป๊ะทั้ง FRONT และ BACK)
  FIX: เพิ่มเงื่อนไข OR ใน coverage-check - ถ้า "any-color union coverage" (นับทุกคอลัมน์
  ที่มีอยู่ ไม่สนสี) สูง >= 85% (_ORPHANED_ROOF_ANY_COLOR_MAX_COVERAGE) ให้ถือว่ามีตัวแทน
  อยู่แล้วเช่นกัน (ไม่ orphan) - ทดสอบแล้วว่าไม่กระทบ AC04-03 ที่เคยยืนยันไว้ก่อนหน้า (teal
  orphan ที่นั่นมี coverage แค่ ~60% เท่านั้น เพราะมีช่องว่างจริง 206px ที่ไม่มีคอลัมน์ใด
  ครอบคลุมเลย - ยังคง trigger orphan ตามเดิมถูกต้อง ทั้ง 2 red box ของ AC04-03 ยังอยู่ครบ
  เหมือนเดิมทุกประการ รวมถึง hazardCount=4 เท่าเดิม)

  บั๊ก#2 - STEP_DOWN pairwise/cross_view เชื่อค่าความสูงที่ไม่น่าเชื่อถือมากเกินไป: แม้แก้
  บั๊ก#1 แล้ว ยังพบกรอบแดงตำแหน่งเดิมใน AA02-01 BACK (คนละกลไก) - ตรวจสอบพบ 2 อาการย่อย:
  (ก) AA05-03 BACK idx ขวาสุด วัดความสูงได้จาก direct-fit ที่มีจุดข้อมูลน้อยมาก (n_samples
  =19 เทียบเพื่อนบ้าน 66-97 จุด) เพราะ apex_x (จุดเปลี่ยน slope ของพื้นตู้) ตกอยู่ในช่วง
  คอลัมน์นั้นพอดี ตัดข้อมูลจนเหลือน้อยเกินจะเชื่อถือได้
  (ข) AA02-01 BACK 2 คอลัมน์ท้ายสุด (ASI1A สีน้ำเงินล้วน มองด้วยตาสูงเท่ากันชัดเจนทั้ง 2
  view) วัดได้ FRONT (direct, samples เต็ม)=154/214px (ต่าง 28%) แต่ BACK เอง (raw, ก่อน
  reconcile)=270/230px (ต่าง 15% - ใกล้เคียงความจริงมากกว่า) - reconcile เลือกเชื่อ FRONT
  เพราะ 'direct' อยู่ใน reliability-hierarchy สูงกว่า 'apex_fallback' ของ BACK เสมอ โดยไม่
  สนใจว่าความขัดแย้งเดิม (conflict, ก่อนแก้ไข) ระหว่าง 2 view สูงแค่ไหน (สูงถึง 21-33%)
  FIX: เพิ่ม 2 reliability guard ใหม่ก่อน flag STEP_DOWN (ทั้ง pairwise และ cross_view):
  1) STEP_DOWN_MIN_RELIABLE_SAMPLES=25 - ถ้าฝั่งที่ "เตี้ยกว่า" เป็น direct fit ที่มี
     n_samples ต่ำกว่านี้ (บ่งชี้ apex ตัดข้อมูลจนเหลือน้อยเกินไป) ไม่ flag คู่นั้น
  2) STEP_DOWN_MAX_CORRECTION_CONFLICT_RATIO=0.15 - ถ้าฝั่งที่ "เตี้ยกว่า" เป็นค่าที่ถูก
     cross_view_corrected จากความขัดแย้งเดิมที่สูงเกิน 15% (บ่งชี้ว่า FRONT/BACK เห็นไม่
     ตรงกันมากตั้งแต่ต้น ไม่ใช่ค่าที่ทั้ง 2 view เห็นพ้องกัน) ไม่ flag คู่นั้น
  ทั้ง 2 เกณฑ์ตรวจสอบแล้วว่าไม่กระทบคอลัมน์เตี้ยกว่าจริงในทุกไฟล์ทดสอบ (AA02-01 idx สุดท้าย
  จริง n=66, ไม่ถูก cross_view_corrected เลย - ยังคง flag REAR_EMPTY_RISK ตามปกติ)

  ข้อจำกัดที่ยังไม่ได้แก้ในรอบนี้ (บอกตรงไปตรงมา): ผู้ใช้ยังชี้ "วงกลมม่วง" ใน AA02-01 BACK
  (กล่อง IRC1A สีแดงเข้ม เตี้ยกว่า ซ่อนอยู่หน้ากอง DSC1A เขียว) ว่าควรมี risk marker แต่ยัง
  ไม่มีเลย - ตรวจสอบแล้วว่า detect_step_down_hidden_behind ไม่พบรูปแบบนี้ (ไม่ใช่ top-face
  bleed-through ข้ามคอลัมน์เดียวกันแบบที่ฟังก์ชันนั้นออกแบบไว้) และ orphaned-roof ก็ไม่ได้
  สร้างคอลัมน์ให้กล่องนี้เช่นกัน (roof ของมันเล็กเกินไป/ถูกบังเกือบมิด) - ยังไม่มีกลไกใดตรวจ
  จับกรณีนี้ได้ในเวอร์ชันนี้ ต้องออกแบบกฎใหม่ + ทดสอบเพิ่มเติมก่อนจะ implement (v25.47 เคย
  ลองแก้จุดนี้มาก่อนแล้วแต่ทำให้แย่ลง - กรอบเพิ่มขึ้นแทนที่จะแก้ปัญหา จึงไม่ถูกนำมาใช้ในรอบนี้)
================================================================================
v25.22 (แก้บั๊ก "marker คลาดเคลื่อน 1 ตำแหน่ง" สำหรับไฟล์ AE02-01 BACK view):

  ปัญหา: marker กรอบแดงวาดผิดตำแหน่ง ไปทางขวา 1 กอง จากตำแหน่งที่ถูกต้อง
  (กล่องที่สูงกว่าอยู่ที่ idx ซ้ายสุด แต่ marker ไปวาดที่ idx ถัดไป)

  Root cause: _p1b_drop_side_wall_contaminated_columns เดิม (v25.20) ตรวจนับจำนวน
  candidates เพียงอย่างเดียว (candidates==1 → drop) แต่ไม่ตรวจตำแหน่งว่า foreign roof
  อยู่บน nearest_col จริงหรือไม่ เมื่อกล่องสีแดงซ้อนเป็นชั้น 3 บนกองซ้ายสุด ทำให้
  roof สีแดงถูก classify เป็น 'foreign roof' 1 ชิ้น → เข้าเงื่อนไข candidates==1 →
  ตัด nearest_col (กองที่มีกล่องแดงจริง) ทิ้ง → back_cols เหลือ 6 จาก 7 →
  boundaries เลื่อนทั้งหมด → marker วาดผิดตำแหน่ง 1 ช่อง

  FIX: เพิ่ม x-overlap guard ก่อนตัดทิ้ง:
    - คำนวณ overlap ระหว่าง candidate roof กับ nearest_col (หน่วยเป็นสัดส่วน roof width)
    - overlap >= 30%: roof ทับบนกองจริง = กล่องสินค้าจริงซ้อนอยู่ → ไม่ตัด (return ทันที)
    - overlap < 30%: roof ลอยนอกขอบกอง = side-wall noise จริง (เช่น EC04-04) → ตัดได้

  regression-verified:
    - EC04-04 BACK: noise จริง → roof อยู่นอกขอบ nearest_col (overlap ต่ำ) → drop ถูกต้อง
    - AE02-01 BACK: กล่องจริง → roof ทับบนกอง (overlap สูง) → ไม่ drop → cols ครบ 7
    - ไฟล์อื่น (ไม่มี candidate): ผ่านเงื่อนไข candidates!=1 ก่อน ไม่ถึง overlap check → ปลอดภัย

  เพิ่ม debug prints ทุกจุดสำคัญ:
    [DROP_SIDE] แสดงจำนวน foreign_roofs/candidates, overlap_frac ของแต่ละ candidate
    [P1B] แสดงจำนวนและ cx ของ cols หลัง merge_corner, drop_side_wall, reconcile

================================================================================
v25.21 (แก้บั๊ก "ตรวจจุดเสี่ยงไม่ได้" สำหรับไฟล์ที่มีกล่องซ้อนสูงผิดปกติ (AE02-01/AE02-02)
        กล่องสีแดงในโซนกล่องสีเขียวไม่ปรากฏจุดเสี่ยง STEP_DOWN_RISK):

  ปัญหา: ไฟล์ AE02-01/AE02-02 ตรวจไม่พบจุดเสี่ยงในโซนกล่องสีเขียว แม้มีกล่องสีแดงซ้อน
  เป็นชั้น 3 สูงกว่ากองข้างเคียงอย่างชัดเจน ทั้ง FRONT และ BACK view

  Root cause (เชิงลึก - "Apex Hijack by Elevated Stack"):
    1. detect_isometric_apex() ใช้ argmin(cargo_top_y) เพื่อหาจุดยอดของตู้
       -> กล่องสีแดงชั้น 3 ที่สูงกว่าทุกกองมี cargo_top_y ต่ำกว่า (y น้อยกว่า) ทุกจุด
       -> argmin() เลือกตำแหน่งกล่องแดงเป็น apex_x แทนที่จะเป็น structural apex จริง
    2. compute_stack_heights_px ใช้ eff_b1 = min(b1, apex_x) สำหรับทุก stack
       -> ถ้ากล่องแดงอยู่ฝั่งซ้าย (x น้อย) -> apex_x เล็กมาก
       -> eff_b1 < b0 สำหรับ stack ที่อยู่ทางขวาทั้งหมด -> xs_top=[] -> height_px=None
    3. height_px=None ทุก stack -> cross-view fill -> carry-forward ให้ค่าเท่ากันหมด
       -> ไม่มีความต่างระหว่าง stack -> STEP_DOWN_RISK ตรวจไม่พบ

  FIX:
    1. detect_isometric_apex(): เปลี่ยนจาก argmin() เป็น slope-change detection
       หา V-shape จริง (slope เปลี่ยนจาก downward เป็น upward ในช่วงยาวพอ)
       กล่องที่สูงผิดปกติสร้าง "dip" สั้นๆ ไม่ใช่ V-shape ยาว -> ตรวจแยกได้
       ถ้าไม่พบ V-shape -> คืน None (ไม่ตัด data ออกโดยไม่จำเป็น = ปลอดภัยกว่า)
    2. compute_stack_heights_px(): เพิ่ม fallback สำหรับ stack ที่ apex-cut ทำให้
       xs_top=[] -> ใช้ cargo_top_y ทั้ง stack แทน (ยอมรับ noise จาก isometric slope
       แต่ดีกว่า height=None ที่ทำให้ carry-forward ให้ค่าเท่ากันหมด)

  regression-verified: ไฟล์ที่ผ่านมาแล้ว (EC01-01, EC04-xx, AC03-01, AC03-06)
  คืน apex=None (ไม่ตัด) เพราะ cargo_top_y ไม่มี V-shape ชัดเจน -> ไม่กระทบผลเดิม
================================================================================
v25.17 (แก้บั๊ก "ตรวจจุดเสี่ยงไม่ได้" สำหรับไฟล์ที่หน้า PDF ที่มี Front/Back diagrams
        ไม่ตรงกับ page_idx=1 เสมอ - พบจริงจากไฟล์ AE02-02):

  ปัญหา: ไฟล์ AE02-02 (และไฟล์ที่คล้ายกัน) ส่งผลว่า "ปลอดภัย (SAFE)" ทุกครั้ง ไม่พบจุด
  เสี่ยงใดเลย แม้จะมี layout ที่ควรตรวจพบความเสี่ยง

  Root cause (2 จุดเชื่อมกัน):
    1. _find_diagram_page_idx() ไม่มีอยู่ก่อน: โค้ดเดิม hardcode page_idx=1 ในทุกฟังก์ชัน
       (render_full_page, run_full_analysis_on_image, extract_sku_from_pdf) โดยถือว่าหน้า
       ที่มี Front/Back diagrams อยู่ที่ index 1 เสมอ - แต่ไฟล์บางไฟล์อาจมี layout ต่างกัน
       หรือ "Front"/"Back" label อยู่ในตำแหน่งที่ _word_bbox_rotated หาไม่เจอ ทำให้
       get_view_region ล้มเหลวหรือ crop ผิดตำแหน่ง

    2. extract_sku_from_pdf ใช้ page_index=1 แบบ hardcode โดยตรวจแค่ว่า len(doc) >= 2
       แต่หน้า index 1 ของบางไฟล์อาจไม่มี "Load Summary" section เลย (เช่น เมื่อ Load
       Summary อยู่ใน right panel ของหน้า index 1 แต่ text extraction อ่านไม่ครบ) ทำให้
       sku_list = [] เสมอ

  FIX:
    1. เพิ่มฟังก์ชัน _find_diagram_page_idx(pdf_bytes): สแกนทุกหน้าหา page ที่มีทั้ง
       "Front" และ "Back" word ใน text layer พร้อมกัน → ใช้หน้านั้น (fallback = 1)
       เรียกใช้ครั้งเดียวใน process_request แล้วส่ง page_idx ที่ถูกต้องไปทุกฟังก์ชัน

    2. แก้ extract_sku_from_pdf ให้รับ page_idx เป็น parameter (default=None → auto-detect):
       ถ้าไม่ระบุ จะสแกนทุกหน้าหาหน้าที่มี "Load Summary" จริง แทนที่จะ hardcode index

  regression-verified: ไฟล์เดิมที่ผ่าน test ทั้งหมด (page_idx=1 เดิม) ยังได้ผลเหมือนเดิม
  เพราะ _find_diagram_page_idx จะคืน 1 ถ้าหน้า index 1 มี "Front"/"Back" อยู่จริง
================================================================================
v25.16 (แก้บั๊ก marker วางผิดตำแหน่งที่พบจริงจาก AC03-06 FRONT - ไฟล์โหลดไม่เต็มคัน):
  ปัญหา: ทดสอบ AC03-06 (Unused Floor 11.8in, cargo 58.5% - โหลดไม่เต็มคัน) พบว่ากรอบ marker
  ของ FRONT view ถูกวาดเป็นแท่งแคบๆ ลอยอยู่กลางอากาศระหว่างกอง ไม่ตรงกับตำแหน่งกล่องจริงเลย

  Root cause (2 จุดที่เกี่ยวเนื่องกัน ทั้งคู่มาจากสาเหตุเดียวกัน คือเชื่อ 'grounded' mask
  มากเกินไปเมื่อไม่น่าเชื่อถือ):
    1. process_view_on_image (override_cols path): x_min_/x_max_ ที่ใช้ clip ตำแหน่ง seam
       ระหว่างคอลัมน์ เดิมเชื่อ fallback_xrange (จาก grounded floor-profile) เป็นหลักเสมอเมื่อมี
       ค่า - แต่ AC03-06 FRONT มี grounded แคบผิดปกติ (92px) เทียบกับคอลัมน์จริงจาก PHASE 1B ที่
       กว้างถึง ~550px (คนละสาเหตุกับ EC04-01 เดิมที่แค่ 1 คอลัมน์มุมกล้องโผล่เกินขอบเล็กน้อย -
       นี่คือเกือบทั้งช่วงไม่ผ่านเกณฑ์ grounded เลย) ทำให้ seam ทั้งหมดถูกบีบอัด/ดันเกินขอบเขต
       แคบๆ นี้ ไม่สะท้อนตำแหน่งจริงของกล่องเลย
    2. compute_local_floor_y: interpolate ค่า floor_y เฉพาะภายในขอบเขต 'grounded' เท่านั้น
       (นอกช่วงปล่อยเป็น -1/invalid) ทำให้ height lookup ล้มเหลวสำหรับตั้งส่วนใหญ่ที่อยู่นอกช่วง
       แคบนี้ แม้ seam จะแก้ถูกแล้วก็ตาม (marker คำนวณไม่ได้/ตำแหน่งผิด)

  FIX:
    1. x_min_/x_max_ ใช้ 'union' ระหว่าง fallback_xrange (grounded) กับ extent จริงของคอลัมน์
       จาก PHASE 1B (ที่ reconcile กับ BACK มาแล้ว จึงเชื่อถือได้) แทนที่จะเชื่อ grounded อย่าง
       เดียว - ยังคงรักษา intent เดิมของ v25.11 (ขยายขอบเขตให้ครอบคลุมคอลัมน์มุมกล้องที่โผล่เกิน
       grounded ไปเล็กน้อย) แต่ป้องกันกรณีตรงข้ามได้ด้วย (grounded แคบกว่ามาก)
    2. measure_cargo_extent_via_white_bg รับ override_xrange (จาก r["xrange"] ที่ union แล้ว)
       เป็น hint เพิ่มเติม กัน start_x/end_x แคบกว่าที่ควร
    3. compute_local_floor_y extrapolate ด้วยค่าขอบ (edge-hold) ให้ครอบคลุมทั้ง array แทนที่จะ
       ปล่อย -1 นอกช่วง grounded - เป็นการประมาณค่าที่สมเหตุสมผลทางฟิสิกส์ (ดีกว่าไม่มีค่าเลย)

  regression-verified: รันซ้ำทั้ง 11 ไฟล์เดิม (EC01-01~04, EC02-01/02, EC03-01, EC04-01~04) ได้
  ผลลัพธ์ (hazardCount, marker position) เหมือนเดิมทุกไฟล์ ไม่มี regression - AC03-06 FRONT
  ตอนนี้วางกรอบตรงตำแหน่งกล่องจริงถูกต้อง (ยืนยันด้วยภาพ marked จริง)
================================================================================
v25.15 (แก้ HTTP 500 ที่พบจากการใช้งานจริงบน Cloud Function หลังปล่อย v25.14):
  ปัญหา: v25.14 แก้ Bug#1/#2 (coordinate mismatch ระหว่าง PHASE 1B กับ pipeline หลัก) โดยเปลี่ยน
  ให้ pipeline หลักทั้งหมด render เต็มหน้าที่ matrix_scale=4 (จากเดิม=3) - ทดสอบ local (รัน
  process_request ตรงๆ ในเครื่อง) ผ่านครบทุกไฟล์ตัวอย่าง แต่เมื่อ deploy ใช้งานจริงบน Cloud
  Function พบ "Python API HTTP Error: 500" ทุกไฟล์ (การวิเคราะห์ล้มเหลวทุกไฟล์)

  Root cause: การ render เต็มหน้าที่ scale=4 (แทน scale=3) ทำให้ทุกขั้นตอนในพไลป์ไลน์หลัก (mask
  ต่างๆ, floor profile, cargo detection, วาด marker, JPEG encode) ต้องประมวลผลภาพที่มีจำนวน
  pixel เพิ่มขึ้น ~1.78 เท่าพร้อมกันทั้งหมด (ไม่ใช่แค่ PHASE 1B เหมือน v25.13 เดิมที่ render
  ภาพ hi-res แยกเฉพาะสำหรับ PHASE 1B ชั่วคราวแล้วปล่อยทิ้ง) ทำให้ memory usage รวมของ Cloud
  Function เกิน limit ที่ deploy ไว้ จนโดน kill (out-of-memory) -> HTTP 500 ทุกไฟล์แบบไม่เลือก
  (เข้าได้กับอาการ "ล้มเหลวทุกไฟล์" ที่ผู้ใช้รายงาน เพราะเป็นปัญหาทรัพยากรระบบ ไม่ใช่ปัญหาเฉพาะ
  ไฟล์ใดไฟล์หนึ่ง)

  FIX: pipeline หลักกลับไปใช้ full_img ที่ matrix_scale=3 เหมือนเดิม (memory footprint เท่าเดิม
  กับ v25.13) ส่วน PHASE 1B เปลี่ยนวิธีการได้ภาพ hi-res ใหม่: แทนที่จะ render "ทั้งหน้า" ที่
  scale=4 (ทั้งแบบ v25.13 ที่ render แยกอิสระ และแบบ v25.14 ที่เปลี่ยนทั้ง pipeline) เปลี่ยนเป็น
  render "เฉพาะสี่เหลี่ยม region เล็กๆ ของ view นั้น" ตรงจาก PDF ที่ scale=4 ผ่าน fitz
  clip=Rect(...) (ฟังก์ชันใหม่ render_hires_crop) โดยใช้ origin_box (safe_x0,safe_y0,safe_x1,
  safe_y1) เดียวกับที่ get_view_region คำนวณให้ pipeline หลักใช้เป๊ะ (แปลงจาก pixel-space เป็น
  point-space ด้วยการหารด้วย main_scale) ผลลัพธ์:
    - แก้ HTTP 500: render เฉพาะ region เล็ก (เศษส่วนของทั้งหน้า) แทนที่จะ render ทั้งหน้าที่
      scale สูง -> memory usage ต่ำกว่ามาก
    - ยังคงแก้ Bug#1 (coordinate mismatch) + Bug#2 (double ensure_safe_crop) จาก v25.14 ได้ครบ
      เพราะพิกัด origin ของ hi-res crop อ้างอิงจากกล่องเดียวกันเป๊ะกับ region หลัก (ต่างกันแค่
      ความหนาแน่น pixel ที่แปลงกลับด้วย down_factor คงที่ = main_scale/hi_scale)
  regression-verified: รันซ้ำทั้ง 11 ไฟล์ตัวอย่าง (EC01-01~04, EC02-01/02, EC03-01, EC04-01~04)
  ในเครื่อง local ได้ n_stacks และ risk ตรงกับผลของ v25.14 ทุกไฟล์ (ดูรายละเอียดที่ CHANGELOG
  ของ v25.14 ด้านล่างสำหรับ 6 bug fixes เดิมที่ยังคงอยู่ครบ ไม่มีการแก้ไขเพิ่มเติมนอกจากนี้)
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
TAIL_STEPDOWN_DROP_RATIO = 0.12
TAIL_STEPDOWN_REAR_POS_MIN = 0.85
# v25.48 NEW (สำคัญ - พบจริงจาก AA05-03 ที่ผู้ใช้แนบ): STEP_DOWN_RISK (ทั้ง pairwise และ
# cross_view) เดิมเชื่อค่า height_px ที่มาจาก "direct" fit เสมอ โดยไม่สนใจว่า fit นั้นมีจุดข้อมูล
# (n_samples) มากพอจะเชื่อถือได้หรือไม่ - พบว่าไฟล์ AA05-03 BACK idx4 (คอลัมน์ขวาสุด) วัดความสูงได้
# แค่ 212.4px (ต่ำกว่าเพื่อนบ้าน idx3 ที่ 274.8px ถึง 22.7% -> เกิน threshold 20% -> flag ผิดพลาด)
# ตรวจสอบพบว่า n_samples ของ idx4 มีเพียง 19 จุด (เทียบเพื่อนบ้านที่มี 73-97 จุด) เพราะ apex_x
# (จุดเปลี่ยน slope ของพื้นตู้ isometric) ตกอยู่ "ภายใน" ช่วงคอลัมน์นี้พอดี (x=1157 อยู่ในช่วง
# 1132-1226) ทำให้ eff_b1=min(b1,apex_x) ตัดข้อมูลที่ใช้ fit เหลือแค่ 19px แคบๆ ก่อนถึง apex -
# การ fit เส้นด้วยจุดน้อยมากขนาดนี้ใกล้จุดเปลี่ยน slope พอดี ไม่น่าเชื่อถือพอจะสรุปว่ากล่องนี้
# "เตี้ยกว่าจริง" (ยืนยันด้วยภาพจริง: ผู้ใช้ระบุว่ากล่องขวาสุดสูงใกล้เคียงกับเพื่อนบ้าน ไม่ควรตีกรอบ)
# FIX: เพิ่มเกณฑ์ขั้นต่ำของ n_samples ก่อนยอมรับว่า height_px "เชื่อถือได้พอจะใช้เป็นฝั่งที่
# 'เตี้ยกว่า' ในการ flag ความเสี่ยง" - ถ้า n_samples ของฝั่งที่เตี้ยกว่าต่ำกว่าเกณฑ์นี้ (และค่า
# height_px ยังไม่เคยถูกยืนยันซ้ำจาก cross-view ผ่าน height_source อื่น) จะไม่ flag ความเสี่ยงคู่
# นั้น (ปลอดภัยกว่าการเดา - ตรงกับหลักการเดิมของระบบที่ "ซื่อสัตย์ว่าไม่รู้" ดีกว่า "มั่นใจผิด")
# ตรวจสอบแล้วว่าไม่กระทบไฟล์อื่น: คอลัมน์ที่เตี้ยกว่าจริงทุกไฟล์ที่ทดสอบ (AA02-01 idx5 n=66,
# AA05-03 idx0 n=96 ฯลฯ) มี n_samples สูงกว่าเกณฑ์นี้มาก ไม่ถูกกระทบ
STEP_DOWN_MIN_RELIABLE_SAMPLES = 25

# v25.48 NEW (สำคัญ - พบจริงจาก AA02-01 ที่ผู้ใช้แนบ หลังแก้ orphaned-roof แล้วยังพบกรอบแดง
# ผิดพลาดที่ตำแหน่งเดิม): กล่อง ASI1A (สีน้ำเงินล้วน ทุกตำแหน่งเป็น SKU เดียวกัน มองด้วยตาจริง
# ในภาพสูงเท่ากันทุกตั้งทั้ง FRONT และ BACK) แต่วัดได้ FRONT idx0=154.2px, idx1=214.2px
# (ต่างกัน 28%) - ตรวจสอบพบว่าค่าดิบก่อน reconcile ของ BACK ฝั่งเดียวกัน (apex_fallback)
# กลับใกล้เคียงกันมากกว่ามาก (270.7 vs 230.7 = 15%) แต่ reconcile เลือกเชื่อ FRONT (direct)
# เพราะอยู่ใน "reliable" hierarchy สูงกว่า apex_fallback เสมอ โดยไม่ดูว่าความขัดแย้งเดิม
# (conflict, ก่อนแก้ไข) รุนแรงแค่ไหน - ความขัดแย้งที่นี่สูงถึง 20.9%/33.2% (คำนวณจาก
# cross_view_conflict_ratio) ซึ่งมากกว่าปกติมาก บ่งชี้ว่าการวัดฝั่งใดฝั่งหนึ่ง (หรือทั้งคู่)
# มี noise สูงจากรอยต่อ isometric slope ระหว่างกล่อง SKU เดียวกันที่วางชิดกัน (ไม่ใช่กล่อง
# เตี้ยกว่าจริง) - เกณฑ์ความน่าเชื่อถือแบบ n_samples (STEP_DOWN_MIN_RELIABLE_SAMPLES) ตรวจจับ
# ไม่ได้ในกรณีนี้เพราะ FRONT idx0/idx1 มี n_samples เต็ม (107 ทั้งคู่) - ต้องใช้สัญญาณคนละตัว
# FIX: ถ้าค่า height_px ของฝั่งที่ "เตี้ยกว่า" ในคู่เปรียบเทียบ มาจาก cross_view_corrected ที่มี
# cross_view_conflict_ratio สูงเกินเกณฑ์นี้ (บ่งชี้ว่า FRONT/BACK เห็นไม่ตรงกันมากก่อนแก้ไข -
# ค่าที่ใช้จริงไม่ใช่ค่าที่ทั้ง 2 view เห็นพ้องต้องกัน) ให้ถือว่าไม่น่าเชื่อถือพอจะ flag ความเสี่ยง
# (เช่นเดียวกับหลักการของ STEP_DOWN_MIN_RELIABLE_SAMPLES - ปลอดภัยกว่าการเชื่อค่าที่มีข้อขัดแย้ง
# สูงระหว่าง 2 มุมกล้องอย่างมั่นใจเกินไป)
STEP_DOWN_MAX_CORRECTION_CONFLICT_RATIO = 0.15
# v25.49 NEW (สำคัญ - พบจริงจาก AB03-04 ที่ผู้ใช้แนบ): เดิม reconcile_heights_cross_view PASS2
# (ดูฟังก์ชัน reconcile_heights_cross_view) เชื่อ "reliability hierarchy" (direct > apex_fallback)
# เสมอเมื่อตัดสินว่าจะเขียนทับค่าฝั่งไหน โดยไม่สนใจว่า "ขนาดของความขัดแย้งเดิม (conflict_mag)"
# สูงผิดปกติแค่ไหน - พบว่าไฟล์ AB03-04 มีคู่ FRONT idx2 (ASI1A-AJ ชั้นเดียว, apex_fallback,
# height=121.17px) vs BACK idx0 (เห็น TEP1A-AJ ซ้อนอยู่อีกชั้นบน ASI1A-AJ จริงจากมุมกล้องนั้น,
# direct, height=269.9px) conflict_mag=55.1% - สูงกว่าทุกเคส "noise ที่คาลิเบรตไว้แล้วว่าควรแก้"
# มาก (AA02-01 สูงสุดที่เคยยืนยันว่าเป็น noise จริงคือ 33.2%) - ระบบยังคง "เชื่อ direct" แล้วเขียน
# ทับ FRONT idx2 เป็น 269.9 ทั้งที่เป็นความแตกต่างทางกายภาพจริง (กล่องคนละความสูงจริงที่ตำแหน่งนี้
# ไม่ใช่ noise) ทำให้ทั้ง 2 ฝั่งถูกทำให้เท่ากันไปก่อน detect_step_down_crossview จะได้เปรียบเทียบ
# -> STEP_DOWN_RISK ที่ควรพบไม่ถูกตรวจพบเลย (หลักฐานถูกลบไปแล้วตั้งแต่ขั้น reconcile)
# ROOT CAUSE: ไม่มีเพดานบนใดๆ กัน "ขนาดของความขัดแย้ง" เอาไว้เลย - ระบบแก้ไข conflict ทุกขนาด
# เท่ากันหมด (แค่ 10.01% ก็แก้ไขเหมือนกับ 55% เป๊ะ) ทั้งที่ในทางสถิติ ยิ่งขัดแย้งกันสูงมาก ยิ่งไม่น่า
# เป็น "measurement noise ธรรมดา" (ซึ่งควรมีขนาดจำกัด) และยิ่งน่าจะเป็นความจริงทางกายภาพมากกว่า
# FIX: เพิ่มเพดานบน - ถ้า conflict_mag เกิน RECONCILE_MAX_CONFLICT_TO_APPLY ให้ "ไม่แก้ไขเลย" (ข้าม
# proposal นี้ไปทั้งคู่ คงค่าเดิมทั้ง 2 ฝั่งไว้) ปล่อยให้ detect_step_down_crossview/pairwise ทำงาน
# กับค่าจริงที่วัดได้ตามปกติแทน - ตั้งค่าไว้ที่ 0.40 (สูงกว่า 33.2% ที่เคยยืนยันว่าเป็น noise จริง
# ของ AA02-01 มากพอสมควร กันไม่ให้กระทบเคสที่คาลิเบรตไว้แล้ว) และต่ำกว่า 55.1% ของ AB03-04 มากพอ
# ที่จะจับเคสใหม่นี้ได้ - regression-verified: AA02-01 (conflict 20.9%/33.2%) ยังคงถูก correct
# เหมือนเดิมทุกประการเพราะต่ำกว่า 40%
RECONCILE_MAX_CONFLICT_TO_APPLY = 0.40
REAR_EMPTY_LENGTH_RATIO = 0.07
CROSSVIEW_MIN_OVERLAP_RATIO = 0.5       # ต้องทับซ้อนตำแหน่งจริงอย่างน้อย 50% จึงถือเป็นคู่เดียวกัน

# --- STEP_DOWN_RISK (hidden_behind) v25.23 NEW ---
# กรณีพิเศษที่ 3 กฎเดิมตรวจไม่พบ: กล่องที่ "ซ่อนอยู่แถวหลัง" (ข้ามความกว้างตู้ 2400mm อีกแถว
# ที่ตำแหน่งความยาวเดียวกัน) สูงกว่ากล่องแถวหน้าที่บังอยู่ - สังเกตได้จาก "top-face bleed-
# through": หลังคา (roof) ของกล่องหลังโผล่พ้นกล่องหน้าขึ้นมา ทำให้ cargo_top_y ในคอลัมน์
# เดียวกัน (front-face column เดิมจาก Phase 1B) กระโดดขึ้นกะทันหัน (แคบกว่า 3-5px) กลางคอลัมน์
# แทนที่จะค่อยๆลาดตามธรรมชาติของมุมมอง isometric (ดูหลักฐาน pixel จริงจาก AE02-01 FRONT
# idx4 และ BACK idx1 ที่ยืนยันแล้วในบทสนทนา - ทั้งคู่มี jump แนวตั้งคมชัด 28-50px ภายใน
# ระยะแนวนอนแค่ 3px พร้อมทั้ง 2 ฝั่งของ jump มีค่าเรียบนิ่งมาก (std<2px) ตรงข้ามกับความชัน
# ธรรมชาติของ isometric slope ที่ลาดต่อเนื่องนุ่มนวลกว่ามาก)
# เกณฑ์ (ปรับตัวเลขได้ที่นี่จุดเดียว): ต้องกระโดดขึ้นอย่างน้อย HIDDEN_BEHIND_MIN_JUMP_PX พิกเซล
# ภายในหน้าต่างแคบๆ (win พิกเซล) และทั้ง 2 ฝั่งต้องนิ่ง (std <= HIDDEN_BEHIND_MAX_SIDE_STD)
# เพื่อแยกแยะจาก noise ของตัวอักษร SKU/isometric slope ธรรมชาติ (ยืนยันแล้วว่าเกณฑ์นี้แยก
# กรณีจริง (AE02-01 FRONT idx4, BACK idx1) ออกจาก false-positive ที่พบระหว่างพัฒนา (FRONT
# idx6 - ขอบขวาสุดที่มี isometric slope + label noise ธรรมชาติ - Lstd ขึ้นสูงถึง ~26 เทียบ
# กับกรณีจริงที่ Lstd<1 เสมอ)
STEP_DOWN_HIDDEN_BEHIND_MIN_JUMP_PX = 20
STEP_DOWN_HIDDEN_BEHIND_MAX_SIDE_STD = 6.0
STEP_DOWN_HIDDEN_BEHIND_WIN = 6
STEP_DOWN_HIDDEN_BEHIND_MARGIN = 3
STEP_DOWN_HIDDEN_BEHIND_MIN_SEG = 8

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


def _find_diagram_page_idx(pdf_bytes_or_doc):
    """v25.17 NEW: หา page index ที่มีทั้ง 'Front' และ 'Back' word ใน text layer พร้อมกัน
    (= หน้าที่มี Front/Back diagrams จริง) แทน hardcode page_idx=1

    รับได้ทั้ง pdf_bytes (bytes) หรือ fitz.Document object ที่เปิดไว้แล้ว
    คืน index ของหน้าที่พบ หรือ 1 (fallback เดิม) ถ้าไม่พบ
    """
    try:
        if isinstance(pdf_bytes_or_doc, (bytes, bytearray)):
            doc = fitz.open(stream=pdf_bytes_or_doc, filetype="pdf")
            owns_doc = True
        else:
            doc = pdf_bytes_or_doc
            owns_doc = False

        for idx in range(len(doc)):
            page = doc[idx]
            words = {w[4] for w in page.get_text("words")}
            if "Front" in words and "Back" in words:
                print(f"_find_diagram_page_idx: found Front+Back on page index {idx}")
                if owns_doc:
                    doc.close()
                return idx

        # fallback: ลองหาหน้าที่มี word ใดก็ได้ใน {"Front","Back"} ก่อน
        for idx in range(len(doc)):
            page = doc[idx]
            words = {w[4] for w in page.get_text("words")}
            if "Front" in words or "Back" in words:
                print(f"_find_diagram_page_idx: found Front/Back (partial) on page index {idx}")
                if owns_doc:
                    doc.close()
                return idx

        print("_find_diagram_page_idx: Front/Back not found, fallback to index 1")
        if owns_doc:
            doc.close()
        return 1 if True else 0  # noqa — ค่า fallback ชัดเจน
    except Exception as e:
        print(f"_find_diagram_page_idx failed: {e}, fallback to 1")
        return 1


def _find_sku_page_idx(doc):
    """v25.17 NEW: หา page index ที่มี 'Load Summary' text ใน PDF text-layer
    สแกนทุกหน้า (priority: หน้าที่มีทั้ง 'Load Summary' และ SKU lines จริง)
    คืน index ที่พบ หรือ 1 (fallback เดิม)
    """
    best_idx = None
    best_sku_count = -1
    for idx in range(len(doc)):
        page = doc[idx]
        full_text = page.get_text("text")
        if "Load Summary" not in full_text and "load summary" not in full_text.lower():
            continue
        # นับ SKU ที่อ่านได้จริงในหน้านี้ (เลือกหน้าที่มีมากที่สุด)
        count = 0
        in_ls = False
        for line in full_text.splitlines():
            line = line.strip()
            if not line:
                continue
            if "Load Summary" in line or "load summary" in line.lower():
                in_ls = True
                continue
            if in_ls and ("Cut List" in line or "cut list" in line.lower()):
                break
            if in_ls:
                parts = line.split()
                if parts and re.match(r"^([A-Z][A-Z0-9]{3,7})", parts[0]):
                    count += 1
        if count > best_sku_count:
            best_sku_count = count
            best_idx = idx
    if best_idx is not None:
        print(f"_find_sku_page_idx: found Load Summary on page index {best_idx} ({best_sku_count} SKU lines)")
        return best_idx
    print("_find_sku_page_idx: Load Summary not found, fallback to 1")
    return 1


def extract_sku_from_pdf(pdf_bytes, page_idx=None):
    """v25.17 FIX: ดึงรายชื่อ SKU จาก Load Summary ใน PDF text-layer
    - รับ page_idx เป็น parameter (default=None → auto-detect ด้วย _find_sku_page_idx)
    - เดิม hardcode page_index = 1 if len(doc) >= 2 else 0 ซึ่งผิดถ้า Load Summary
      ไม่ได้อยู่ที่ index 1 พอดี (เช่น AE02-02 ที่ text layer หน้า index 1 ไม่ครบ)
    """
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if page_idx is None:
            page_index = _find_sku_page_idx(doc)
        else:
            page_index = page_idx
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
        print(f"SKU extracted (page {page_index}): {sku_list}")
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


def compute_floor_profile(region, struct_mask, cargo_mask, gap_thresh=30, max_floor_search_below=100):
    h, w, _ = region.shape
    floor_y = np.full(w, -1, dtype=int)
    cargo_bottom_y = np.full(w, -1, dtype=int)
    grounded = np.zeros(w, dtype=bool)
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


def process_view_on_image(full_img, y0_frac, y1_frac, x0_frac, x1_frac, gap_thresh=30,
                           override_cols=None, precrop=None):
    img = full_img
    H, W, _ = img.shape
    if precrop is not None:
        # v25.14 FIX (Bug#1/#2): ใช้ region ที่ crop มาแล้วจาก pipeline หลัก (get_view_region)
        # โดยตรง 100% - ไม่คำนวณ crop ซ้ำอีกครั้ง เพื่อรับประกันว่าพิกัดตรงกับที่ PHASE 1B ใช้
        # เป๊ะเสมอ (เดิม get_safe_region คำนวณ ensure_safe_crop แยกอีกชุด ทำให้ origin เพี้ยนได้)
        region, (safe_x0, safe_y0, safe_x1, safe_y1) = precrop
    else:
        y0, y1 = int(H * y0_frac), int(H * y1_frac)
        x0, x1 = int(W * x0_frac), int(W * x1_frac)
        safe_y0, safe_y1, safe_x0, safe_x1 = ensure_safe_crop(img, y0, y1, x0, x1, margin=30)
        region = img[safe_y0:safe_y1, safe_x0:safe_x1].copy()
    struct_mask_raw = saturated_mask(region)
    arrow_m = arrow_mask(region)
    cargo_mask = vivid_cargo_mask(region) & (~arrow_m)
    floor_y, cargo_bottom_y, grounded = compute_floor_profile(
        region, struct_mask_raw & (~arrow_m), cargo_mask, gap_thresh=gap_thresh)

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
        cols_x_min = cols_sorted[0]["x"]
        cols_x_max = cols_sorted[-1]["x"] + cols_sorted[-1]["w"]
        # v25.16 FIX (Critical): เดิมเชื่อ fallback_xrange (grounded, จาก floor-profile) เป็นหลัก
        # เสมอเมื่อมีค่า - แต่พบจริงจาก AC03-06 FRONT (ไฟล์โหลดไม่เต็มคัน, Unused Floor 11.8in)
        # ว่า grounded zone บางไฟล์แคบผิดปกติมาก (พบจริง: กว้างแค่ 92px ขณะที่คอลัมน์จริงจาก
        # PHASE 1B ที่ reconcile กับ BACK แล้วกว้างถึง ~550px) เพราะ floor-profile/gap_thresh
        # ตรวจ 'พื้นชนกับกล่อง' ไม่ผ่านในเกือบทุกคอลัมน์ของไฟล์นี้ (ระยะห่างจาก cargo_bottom_y
        # เกิน gap_thresh เกือบตลอดแนว ไม่ใช่แค่มุมกล้องใกล้สุดแบบ EC04-01 เดิม) ผลคือ seam
        # midpoint ถูกบีบอัด/ดันเกินขอบเขตแคบๆ นี้ ทำให้กรอบ marker วางผิดตำแหน่งไปไกลจากกล่อง
        # จริงทั้ง 8 ตั้ง (ยืนยันจากภาพจริงที่ผู้ใช้แนบมา: กรอบ FRONT ไปกองอยู่กลางอากาศระหว่าง
        # กองแทนที่จะอยู่ที่กองจริง)
        #
        # FIX: ใช้ 'union' ของ fallback_xrange (grounded) กับ extent จริงของคอลัมน์จาก PHASE 1B
        # เสมอ (min ของขอบซ้ายทั้งคู่, max ของขอบขวาทั้งคู่) แทนที่จะเชื่อ fallback_xrange อย่าง
        # เดียว - ยังคงรักษา intent เดิมของ v25.11 (ขยายขอบเขตให้ครอบคลุมคอลัมน์มุมกล้องที่โผล่
        # เกิน grounded zone แคบๆ ไปเล็กน้อย) แต่ป้องกันกรณีตรงข้าม (grounded แคบกว่า column
        # extent มาก) ได้ด้วย เพราะ PHASE 1B ผ่านการ reconcile กับ BACK (ground-truth ตำแหน่ง)
        # มาแล้ว จึงเชื่อถือได้อย่างน้อยเท่ากับ grounded-based fallback
        if fallback_xrange is not None:
            x_min_ = min(fallback_xrange[0], cols_x_min)
            x_max_ = max(fallback_xrange[1], cols_x_max)
        else:
            x_min_, x_max_ = cols_x_min, cols_x_max

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
                # v25.15 FIX: min_seg_width เป็น float (adaptive, Bug#5) - ต้อง int() ผลลัพธ์
                # ก่อนเก็บ ไม่งั้น seams จะมีค่า float ปนอยู่ ทำให้ range() ใน PHASE 3
                # (compute_stack_heights_px) พังด้วย TypeError (พบจริงจาก production regression
                # test: EC01-03/04 ทุกครั้งที่ seam ordering ถูกบังคับแก้ผ่านเงื่อนไขนี้)
                seam = int(seams[-1] + min_seg_width)
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
    #
    # v25.38 FIX (Critical - พบจริงจากการใช้งานจริงของผู้ใช้ v25.37): เดิม (v25.14) บังคับตรวจ
    # rail-based check นี้ทั้ง 2 path เสมอ โดยอ้างเหตุผลว่า "corner-artifact เป็นปัญหาของภาพ/
    # มุมกล้อง ไม่ใช่ปัญหาเฉพาะวิธีนับ" - แต่พบจริงจาก 4 ไฟล์ที่ผู้ใช้รายงาน (AB01-02, AB03-04,
    # AB04-02, AC04-03) ว่า idx0 (คอลัมน์แรกสุด/หัวตู้) ที่มาจาก override_cols (PHASE 1B) ถูก
    # ตรวจพบเป็น idx0_is_corner_duplicate=True ผิดพลาด (false-positive) ทั้งที่เป็นกล่องจริง 1 ใบ
    # ที่ถูกต้องแล้ว (ยืนยันด้วยภาพจริง: AB01-02 FRONT idx0 คือกองกล่องแดง+เขียว SES1A-A3/SHP1A
    # ที่เตี้ยกว่ากอง STEMB (idx1) อย่างชัดเจน 36.3% - เกินเกณฑ์ STEP_DOWN_RISK 20% มาก แต่ risk
    # ไม่ถูกตรวจพบเพราะ detect_step_down_pairwise ข้าม record ที่ is_corner_duplicate=True เสมอ)
    # ROOT CAUSE: rail-based check นี้ใช้ 'ตำแหน่งที่เส้นขอบพื้นตู้ (floor rail) เริ่มปรากฏชัดเจน
    # พอจะ trace ได้' (corner_x) เทียบกับขอบซ้ายของคอลัมน์แรก (x_min_) - เดิมออกแบบมาสำหรับกรณีที่
    # seam-based counting (ก่อน PHASE 1B) แตกคอลัมน์ผิดจากมุมกล้องใกล้สุด ซึ่งมักทำให้ rail เริ่ม
    # ปรากฏช้ากว่าตำแหน่งจริงมาก - แต่ไฟล์ที่บรรทุกหนาแน่นมาก (Unused Floor น้อย เช่น AB01-02 มี
    # แค่ 9.4in) จะมีพื้นตู้โผล่ให้เห็นน้อยมากหรือไม่มีเลย ทำให้เส้น rail ที่ trace ได้ (แม้จะมี
    # n_inliers สูงและ resid_std ต่ำ ดูน่าเชื่อถือทางสถิติ) อาจไม่ใช่ 'ขอบพื้นตู้จริงบริเวณกล่องแรก'
    # แต่เป็นเส้นที่ fit ได้บังเอิญจากจุดอื่นในภาพที่มี slope ใกล้เคียงกัน (ยืนยันจาก AB01-02:
    # corner_x=751 ซึ่ง 'เลยจุด first_seam=703 ไปแล้ว' - หมายความว่าตำแหน่งที่อ้างว่าเป็น 'ขอบ
    # ของ corner artifact ในคอลัมน์แรก' อยู่เลยขอบเขตคอลัมน์แรกไปแล้วจริง จึงเป็นไปไม่ได้ทาง
    # ตรรกะที่จะเป็นหลักฐานของ corner-duplicate ภายในคอลัมน์แรกนั้นเอง)
    # นอกจากนี้ PHASE 1B (override_cols) มีกลไกตรวจ+รวม corner-duplicate ของตัวเองอยู่แล้ว
    # (_p1b_merge_corner_artifact_columns ที่ใช้หลักฐาน 'side' fragment ซ้อนทับ ไม่ใช่ rail
    # geometry) ซึ่งผ่านการ regression-test มาแล้วหลายไฟล์โดยเฉพาะ - ตรงกับที่ comment เดิมของ
    # v25.11 ด้านบน (บรรทัด "เพราะ merge เอา fragment ปลอมออกไปตั้งแต่ต้นเลย จึงไม่มี phantom
    # record เหลือให้ต้อง flag is_corner_duplicate อีกต่อไป") ระบุไว้อยู่แล้วว่าไม่จำเป็นต้องใช้
    # rail-check นี้ซ้ำอีกเมื่อมาจาก PHASE 1B
    # FIX: จำกัดให้ rail-based check นี้ทำงานเฉพาะ path fallback (seam-based, override_cols is
    # None) เท่านั้น กลับไปเป็นพฤติกรรมก่อน v25.14 Bug#6 - เพราะ PHASE 1B มีกลไกของตัวเองที่
    # แม่นยำกว่าและตรวจสอบแล้วอยู่แล้ว ไม่ต้องพึ่ง rail-geometry ซ้ำซ้อน
    # ข้อจำกัดที่ต้องบอกตรงไปตรงมา: ไม่มีไฟล์ AC03-01 (ที่เคยใช้ validate v25.14 Bug#6) ให้ทดสอบ
    # ยืนยันซ้ำในรอบนี้ - แต่ประเมินความเสี่ยงแล้วว่าปลอดภัยกว่า เพราะ (1) PHASE 1B's merge_
    # corner_artifact_columns เป็นกลไกที่ออกแบบมาเฉพาะสำหรับปัญหานี้และ regression-test มาแล้ว
    # หลายไฟล์ (AC03-01 รวมอยู่ในนั้นด้วยตั้งแต่ v25.11) (2) หลักฐาน false-positive จากรอบนี้มาจาก
    # การใช้งานจริง 4 ไฟล์ที่ผู้ใช้ยืนยันแล้วว่าเป็นปัญหาจริง ไม่ใช่แค่การเดา
    if override_cols is None and xrange_ is not None and seams:
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
# v25.15 FIX (Critical - production HTTP 500): v25.14 แก้ปัญหาข้างต้นโดยเลิก render/crop แยก
# ทั้งหมด เปลี่ยนมาให้ pipeline หลักทั้งหมด render เต็มหน้าที่ scale=4 (แทน scale=3 เดิม) แล้วใช้
# region เดียวกัน 100% ระหว่าง PHASE 1B กับ pipeline หลัก - ทดสอบ local ผ่านหมด แต่พอใช้งานจริง
# บน Cloud Function พบ HTTP 500 ทุกไฟล์ เพราะ scale=4 เต็มหน้าทำให้ทุกขั้นตอนใน pipeline (mask,
# floor profile, วาด marker, JPEG encode ฯลฯ) ใช้ memory เพิ่มขึ้น ~1.78 เท่าพร้อมกันหมด จนเกิน
# memory limit ของ Cloud Function
#
# แก้โดย pipeline หลักกลับไปใช้ full_img ที่ scale=3 เหมือนเดิม (memory เท่าเดิม) ส่วน PHASE 1B
# เปลี่ยนมา render เฉพาะ "สี่เหลี่ยม region เล็กๆ ของ view" ตรงจาก PDF ที่ scale=4 ผ่าน fitz
# clip=Rect(...) (ดู render_hires_crop) โดยใช้ origin_box เดียวกับที่ get_view_region คำนวณให้
# pipeline หลักใช้เป๊ะ (แปลงจาก pixel-space เป็น point-space ด้วยการหารด้วย main_scale) - ยังคง
# แก้ Bug#1 (coordinate mismatch) + Bug#2 (double ensure_safe_crop) ได้ครบถ้วนเหมือน v25.14 เพราะ
# พิกัด origin อ้างอิงจากกล่องเดียวกันเป๊ะ (ต่างกันแค่ความหนาแน่น pixel ที่แปลงกลับด้วย
# down_factor คงที่) แต่ไม่ต้อง render เต็มหน้าที่ scale สูงอีกต่อไป (region เล็กกว่าทั้งหน้าหลาย
# เท่า จึงประหยัด memory มาก แก้ HTTP 500 ได้)
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


def _p1b_cells_for_color(crop, color, tol=12, raw_area_min=150, close_iters=0):
    """หา connected-components ของสี color บน crop - ใช้ scipy.ndimage แทน
    cv2.connectedComponentsWithStats (ผลลัพธ์เทียบเท่ากัน, ไม่ต้องพึ่ง opencv)

    v25.20 FIX (front-face fragmentation - area_min ตัดตอนก่อนมี merge โอกาส): เดิม
    area_min=1200 ถูกกรองทิ้ง "ที่ตรงนี้เลย" (ก่อน _p1b_merge_text_split_fragments จะมีโอกาส
    เชื่อม fragment ที่แตกจากกันกลับเป็น face เดียวกัน) -> fragment เล็กๆ ที่จริงเป็นส่วนหนึ่งของ
    front-face เดียวกัน (เช่น ถูกตัดแบ่งโดยเส้นขอบตัวอักษร/gradient) ถูกทิ้งไปถาวรตั้งแต่ต้น
    ทำให้ face นั้นเหลือพื้นที่ไม่พอ/ขาดหายจาก column ทั้งคอลัมน์

    FIX: ใช้ raw_area_min (ต่ำกว่ามาก ค่าเริ่มต้น=150) กรองเฉพาะ noise แท้ๆ ที่ตรงนี้ ส่วน
    area_min ตัวจริง (ค่าเริ่มต้น=1200) ย้ายไปกรอง "หลัง" merge ใน _p1b_classify_view แทน
    เพื่อให้ fragment เล็กที่ควรถูกเชื่อมกลับเป็น face เดียวกันมีโอกาสรอดถึงขั้น merge ก่อน
    ตัดสินใจว่า area รวมพอหรือไม่

    หมายเหตุ (ทดสอบแล้ว ไม่ integrate): เคยลองเพิ่ม tol เริ่มต้น 12->20 ด้วย เพื่อลดโอกาส mask
    แตกจาก anti-alias/เงาที่เพี้ยนสีเล็กน้อย - แต่ทดสอบจริงกับ AE02-01/AE02-02 พบว่า tol=20
    ไม่ได้ลด fragment ของ front-face สีแดงเลย (raw component แทบไม่เปลี่ยน) กลับทำให้
    _p1b_drop_side_wall_contaminated_columns ตัดคอลัมน์จริงทิ้งเพิ่มขึ้น (4 แทนที่จะเป็น 5) จึง
    คงค่า tol=12 เดิมไว้ - สาเหตุที่แท้จริงของ AE02-01/02 ไม่ใช่ tol fragmentation แต่เป็นที่
    _p1b_drop_side_wall_contaminated_columns เข้าใจผิดว่า roof ของกล่องสีแดง (ที่วางซ้อนอยู่บน
    คอลัมน์จริงที่หัวรถ) เป็น side-wall noise เพราะ front-face สีแดงมี aspect ไม่เกิน 0.85 เลย
    ในมุมมอง BACK (ดูรายละเอียดการสืบสวนในข้อความสนทนา) - ยังต้องแก้จุดนั้นแยกต่างหาก โดยวิธี
    x-overlap กับคอลัมน์ที่ใกล้ที่สุดที่เคยลองก็พิสูจน์แล้วว่าแยกแยะจากเคส EC04-04 (contamination
    จริง) ไม่ได้ เพราะมี geometric signature เหมือนกันทุกประการ (ต้องใช้ cross-view position
    matching ถึงจะแยกได้ - ยังไม่ทำในรอบนี้)"""
    diff = np.abs(crop.astype(int) - np.array(color, dtype=int))
    m = (diff[:, :, 0] <= tol) & (diff[:, :, 1] <= tol) & (diff[:, :, 2] <= tol)
    if close_iters > 0:
        m = ndimage.binary_closing(m, structure=np.ones((3, 3), dtype=bool), iterations=close_iters)
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
        if area < raw_area_min:
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


def _p1b_classify_view(crop, area_min=None):
    if area_min is None:
        # calibrate จาก hi_scale=4 region จริง
        # 1200px² คือ calibrate ที่ scale=4, region ~400×300px
        # ถ้า region เล็กกว่า → scale ลงตามสัดส่วน
        h, w = crop.shape[:2]
        ref_area = 400 * 300  # region size ที่ calibrate ไว้
        area_min = max(300, int(1200 * (h * w) / ref_area))

    S, _ = _p1b_sat_val(crop)
    colors = _p1b_dominant_colors(crop)
    all_cells = []
    for color in colors:
        comps = _p1b_cells_for_color(crop, color)
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
            # v25.20 FIX: area_min ตัวจริงกรอง "หลัง" merge (ไม่ใช่ก่อน) - ดู docstring
            # _p1b_cells_for_color ว่าทำไมต้องย้ายมาตรงนี้ (กัน fragment ที่ควรรวมเป็น face
            # เดียวกันถูกทิ้งไปก่อนมีโอกาส merge)
            merged = [c for c in merged if c['area'] >= area_min]
            for c in merged:
                c['aspect'] = c['h'] / c['w'] if c['w'] else 0
                c['color'] = tuple(int(v) for v in color)
                c['kind'] = kind0
                sub_s = S[c['y']:c['y'] + c['h'], c['x']:c['x'] + c['w']]
                c['mean_sat'] = float(np.mean(sub_s[sub_s > 0.1])) if np.any(sub_s > 0.1) else 0
                # v25.51 NEW (สำคัญ - พบจริงจาก AC02-02/AB02-02 ที่ผู้ใช้แนบ หลังทดสอบ 57 ไฟล์):
                # เดิม kind0 (front/roof/side) ถูกตัดสินจาก aspect ratio ของ "ชิ้นส่วนดิบ" (raw  
                # component) ก่อน merge เพียงครั้งเดียว - พบว่าบางกล่องจริง (SEWTA cyan, AIA1A blue  
                # ใน AC02-02 / SAB1A magenta, API1A blue ใน AB02-02) มี front-face ที่ถูกแบ่งเป็น  
                # หลายแถบแนวนอนบางๆ (isometric shading ตัดเป็นชั้นๆ) ทำให้ "แต่ละแถบดิบ" มี aspect  
                # ratio ต่ำ (กว้างกว่าสูง, aspect<0.85) จึงถูกจัดเป็น kind0='roof' ทั้งที่รวมกันแล้ว  
                # เป็น front-face จริงของกล่องที่สูงเพรียว (ยืนยันจากข้อมูลจริง: SAB1A รวมแถบแล้วได้  
                # w=116,h=186,aspect=1.60 / AIA1A w=117,h=126,aspect=1.08 - ทั้งคู่ >=0.85 ชัดเจน)  
                # ผลคือสีเหล่านี้ไม่เคยมี 'front' candidate เลยแม้แต่ชิ้นเดียว -\> ไม่มีสิทธิ์เข้า  
                # cluster_columns (ซึ่งอ่านจาก 'fronts' list เท่านั้น) และไม่มีสิทธิ์รวมเป็นคอลัมน์  
                # เดียวกับกล่องข้างเคียงผ่านกฎ multi-color-per-idx (CLUSTER_DIFF_COLOR_MIN_XOVERLAP)  
                # เหลือเพียงทางเดียวคือ orphaned-roof detection ซึ่งพบว่าล้มเหลวเช่นกันในหลายเคส  
                # (ถูกตัดสินว่า "มีตัวแทนอยู่แล้ว" อย่างผิดพลาด เพราะ any-color coverage สูงจาก  
                # คอลัมน์ข้างเคียงคนละสีที่บังเอิญ x-range ทับกันพอดี - ดู AIA1A ใน AC02-02) ทำให้  
                # กล่องเหล่านี้หายไปจากผลลัพธ์ทั้งหมด ไม่มีการวัดความสูงแยกเลย -\> STEP_DOWN_RISK ที่  
                # ควรพบ (กล่องเตี้ยกว่าเพื่อนบ้านชัดเจน) ไม่ถูกตรวจพบ  
                # FIX: หลัง merge ชิ้นส่วนภายใน kind0='roof' แล้ว ตรวจสอบ aspect ของก้อนที่ merge  
                # แล้ว (ไม่ใช่ชิ้นดิบ) อีกครั้ง - ถ้า merged aspect \>= 0.85 (สัดส่วนสูงกว่ากว้าง แบบ  
                # front-face จริง) และ mean_sat \>= 0.75 (สีสดพอจะเป็น front ไม่ใช่ side) ให้ถือว่า  
                # เป็น front-face จริง (reclassify kind='front') แทนที่จะปล่อยไว้เป็น 'roof' - ปลอดภัย  
                # เพราะ merge ภายใน kind0 เดียวกันใช้เกณฑ์ x_tol/w_tol เข้มงวดอยู่แล้ว (ต้องมีตำแหน่ง/  
                # ความกว้างใกล้เคียงกันจริงจึงจะ merge ได้) และ 'roof' ทรงสี่เหลี่ยมขนมเปียกปูนจริง  
                # (หลังคากล่องเดี่ยว หรือ roofline staircase) ตามธรรมชาติจะยังคง "กว้างกว่าสูง" อยู่  
                # แม้ merge กับชิ้นเดียวสีเดียวกันแล้วก็ตาม (พิสูจน์แล้วจากข้อมูลจริงทุกไฟล์ regression  
                # ที่ผ่านมาก่อนหน้านี้ - ไม่มีกรณี roof ที่ merge แล้วมี aspect\>=0.85 โดยไม่ใช่ front  
                # จริงเลย)  
                if kind0 == 'roof' and c['aspect'] >= 0.85 and c['mean_sat'] >= 0.75:
                    c['kind'] = 'front'
                all_cells.append(c)
    return all_cells


def _p1b_x_overlap_frac_generic(a0, a1, b0, b1):
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    return inter / max(1e-6, min(a1 - a0, b1 - b0))


# v25.27 NEW: "inner-row roof-anchor" filter (ตามที่ผู้ใช้ยืนยันด้วยภาพจริง AC02-02 - mark X บน
# หลังคาขั้นที่ 2,3,4,5 ของ 'บันไดหลังคา' แต่ไม่ mark ขั้นแรก) - ROOT CAUSE: เมื่อกล่อง SKU
# เดียวกันหลายใบวางซ้อนกันตามความลึก/ความกว้างตู้ (คนละแถวจากมุมกล้อง) ในตำแหน่งความยาวเดียวกัน
# (1 IDX เดียว) มุมมอง isometric จะทำให้หลังคาของแต่ละใบ "โผล่พ้น" ขึ้นมาเป็นขั้นบันไดต่อเนื่องกัน
# (แถวหลังสูงกว่าแถวหน้าเสมอในภาพ FRONT เพราะระยะห่างจากมุมกล้อง) - ข้อสังเกตสำคัญ: front-face
# ของกล่อง "แถวใน" (ไม่ใช่แถวหน้าสุด) ที่โผล่ให้เห็นบางส่วนจากช่องว่างระหว่างขั้นบันได จะถูก
# Phase 1B ตรวจพบเป็น front-face fragment แยกต่างหาก ทั้งที่เป็นกล่อง SKU เดียวกัน ตำแหน่ง IDX
# เดียวกันกับที่นับไปแล้วจากแถวหน้า (front-face หลักที่ต่อเนื่องจากพื้น) - ทำให้นับซ้ำ/นับเกิน
#
# วิธีแยกแยะ (ยืนยันจากข้อมูลจริง): หา "หลังคาขั้นแรก" (roof/top-face ที่มี bottom_y มากที่สุด
# = ใกล้พื้นที่สุด = เชื่อมต่อกับ front-face หลักของคอลัมน์นั้นโดยตรง) ในกลุ่มสีเดียวกันที่ตำแหน่ง
# x ทับซ้อนกัน - front-face candidate ใดๆ ที่ 'ผูกติด' อยู่กับหลังคาที่มี bottom_y น้อยกว่า (สูง
# กว่า) หลังคาขั้นแรกนี้ ถือเป็น front-face ของกล่อง "แถวใน" (inner row) ให้กรองออก ไม่นับ
# (ยืนยันด้วย AC02-02 FRONT: front-face x=932,1022,1111 สีส้ม(VCS1A-F1) ทั้งหมดผูกกับ roof ที่
# bottom_y สูงกว่า (401-538) เทียบกับ roof ขั้นแรกจริงที่ bottom_y=583 (x=816) - ตรงกับที่ผู้ใช้
# mark X ไว้บนหลังคาขั้นที่ 2/3/4 ทุกจุด ไม่กระทบ front-face ขั้นแรก (x=814) ที่ต้องนับ)
def _p1b_filter_inner_row_fronts(fronts, roofs, x_overlap_thresh=0.5, y_gap_max=60,
                                  single_box_height_ratio=0.6):
    """กรอง front-face fragment ที่เป็น 'แถวใน' (inner row, ซ้ำซ้อนกับคอลัมน์ที่นับแล้วจากขั้น
    บันไดหลังคาเดียวกัน) ออกจาก fronts - คืนค่า (kept, dropped)

    v25.28 FIX (สำคัญ - แก้ false-positive ที่พบจริงจาก AE02-01): เดิมกฎนี้ตรวจสอบทุก front-face
    candidate โดยไม่แยกแยะขนาด - พบว่าทำให้ front-face ที่เป็น 'การ merge ของกล่องหลายใบซ้อนกัน
    แนวตั้งในคอลัมน์เดียวกันจริง' (เช่น 3-4 กล่องสูงรวมกันเป็นก้อนเดียว, h=422px) ถูกเข้าใจผิดว่า
    เป็น inner-row เพราะไปทับซ้อนกับ roof ของคอลัมน์ข้างเคียงที่ overlap เพียงเล็กน้อย (>=15%)
    โดยบังเอิญ (คอลัมน์กว้างมากจากการ merge ทำให้ x-range ยื่นไปแตะคอลัมน์ข้างๆ)
    ROOT CAUSE ที่แท้จริงของความแตกต่าง: front-face ที่เป็น 'inner-row ghost' จริง (พิสูจน์จาก
    AC02-02: h=86-87px) มีความสูงระดับ 'กล่องเดี่ยว 1 ใบ' เสมอ ในขณะที่ front-face ที่เป็น
    'genuine merged column' (หลายกล่องซ้อนแนวตั้งจริง) มีความสูงมากกว่ามาก (h=195-422px ในไฟล์
    ต่างๆ ที่ทดสอบ) - ความสูงที่มากกว่านี้เป็นหลักฐานว่ามันคือกล่องที่ต่อเนื่องจากพื้นขึ้นไปจริง
    ไม่ใช่ชิ้นที่ 'ลอย' อยู่กลางอากาศจากการโผล่ทะลุของกล่องแถวหลัง
    FIX: เพิ่ม guard - ตรวจสอบกฎ inner-row เฉพาะ front-face ที่ความสูง (h) ต่ำกว่า
    single_box_height_ratio (60%) ของความสูงสูงสุดในกลุ่มสีเดียวกันทั้งภาพเท่านั้น (สอดคล้องกับ
    หลักฐานจริงทั้ง AC02-02 (ghost h=86-87 << max h=290) และ AE02-01 (ที่เคย false-positive
    h=422 ซึ่งเป็นค่าสูงสุดของกลุ่มสีเดียวกันเอง ไม่ใช่กล่องเตี้ยเลย - ผ่าน guard นี้ไปได้
    เพราะไม่เข้าเงื่อนไข 'เตี้ยกว่า 60% ของค่าสูงสุด')"""
    kept, dropped = [], []
    # คำนวณความสูงสูงสุดต่อกลุ่มสี (ใช้เป็นเกณฑ์อ้างอิง 'genuine merged column' ของสีนั้น)
    max_h_by_color = {}
    for c in fronts:
        max_h_by_color[c['color']] = max(max_h_by_color.get(c['color'], 0), c['h'])

    for c in fronts:
        max_h_this_color = max_h_by_color.get(c['color'], c['h'])
        if c['h'] >= max_h_this_color * single_box_height_ratio:
            # front-face นี้สูงพอที่จะเป็น genuine merged column เอง (ไม่ใช่ single-box peek)
            # -> ปลอดภัย ไม่ต้องตรวจสอบกฎ inner-row เลย เก็บไว้ทันที
            kept.append(c)
            continue
        # หา roof สีเดียวกัน ที่ x ทับซ้อนกับ c มาก และ 'เชื่อมต่อ' กับ c ในแนวตั้ง (roof อยู่
        # เหนือ front-face นี้โดยตรง หรือ front-face นี้อยู่ใต้ roof นี้พอดี - y_gap เล็ก)
        same_color_roofs = [r for r in roofs if r['color'] == c['color']]
        connected_roofs = []
        for r in same_color_roofs:
            ov = _p1b_x_overlap_frac_generic(c['x'], c['x'] + c['w'], r['x'], r['x'] + r['w'])
            if ov < x_overlap_thresh:
                continue
            # roof ควรอยู่ 'ติดกับ' หรือ 'คาบเกี่ยว' กับขอบบนของ front-face c (r bottom ~ c top)
            y_gap = abs((r['y'] + r['h']) - c['y'])
            if y_gap <= y_gap_max:
                connected_roofs.append(r)
        if not connected_roofs:
            kept.append(c)
            continue
        # หาหลังคา "ขั้นแรก" ในกลุ่มสีเดียวกันทั้งภาพ (bottom_y มากที่สุด = ใกล้พื้นที่สุด) ที่
        # x ทับซ้อนกับคอลัมน์นี้มาก (ใช้ threshold เดียวกับ connected เพื่อกันไม่ให้หยิบ roof
        # ของคอลัมน์ข้างเคียงที่ทับซ้อนเพียงเล็กน้อยมาคำนวณผิด)
        all_overlapping_roofs = [r for r in same_color_roofs
                                  if _p1b_x_overlap_frac_generic(c['x'], c['x'] + c['w'],
                                                                  r['x'], r['x'] + r['w']) >= x_overlap_thresh]
        if not all_overlapping_roofs:
            kept.append(c)
            continue
        first_step_bottom_y = max(r['y'] + r['h'] for r in all_overlapping_roofs)
        # ถ้า roof ที่เชื่อมกับ c โดยตรง มี bottom_y ต่ำกว่า (น้อยกว่า) ขั้นแรกอย่างมีนัยสำคัญ
        # (สูงกว่าขั้นแรกจริง ไม่ใช่แค่ noise เล็กน้อย) -> เป็น inner row -> กรองออก
        connected_max_bottom = max(r['y'] + r['h'] for r in connected_roofs)
        if connected_max_bottom < first_step_bottom_y - 10:
            dropped.append(c)
        else:
            kept.append(c)
    return kept, dropped


def _p1b_x_gap_generic(a0, a1, b0, b1):
    return max(a0 - b1, b0 - a1)


# v25.27 NEW: 'side-sliver' filter (ยืนยันจากภาพจริง AC02-02 - mark X บนเศษ VCS1A-F1 บางๆ
# w=28px ที่ถูกผนัง/มุมกล้องบังบางส่วน จนเหลือแค่แถบแคบๆ ติดกับ front-face หลักที่กว้างกว่ามาก
# ของสีเดียวกัน) - ต่างจาก inner-row filter (ซึ่งดูความสัมพันธ์กับ 'หลังคา') ตรงที่ filter นี้ดู
# แค่ 'ความกว้างเทียบกับเพื่อนบ้านสีเดียวกันที่ติดกัน/ทับซ้อน' โดยตรง - ปลอดภัยเพราะ front-face
# จริงที่แยกกันเป็นคอลัมน์ต่างกันจะไม่มีทางมีสีเดียวกันติดกันสนิทแบบนี้ (ถ้าเป็นคอลัมน์เดียวกันจริง
# ก็ควรถูก merge เป็นก้อนเดียวไปแล้วโดย _p1b_merge_text_split_fragments)
def _p1b_filter_side_slivers(fronts, width_ratio_thresh=0.5, gap_max=5, x_overlap_thresh=0.2):
    kept, dropped = [], []
    for c in fronts:
        is_sliver = False
        for other in fronts:
            if other is c or other['color'] != c['color']:
                continue
            if c['w'] >= other['w'] * width_ratio_thresh:
                continue  # ไม่แคบกว่าเพื่อนบ้านมากพอ
            gap = _p1b_x_gap_generic(c['x'], c['x'] + c['w'], other['x'], other['x'] + other['w'])
            ov = _p1b_x_overlap_frac_generic(c['x'], c['x'] + c['w'], other['x'], other['x'] + other['w'])
            if gap <= gap_max or ov >= x_overlap_thresh:
                is_sliver = True
                break
        if is_sliver:
            dropped.append(c)
        else:
            kept.append(c)
    return kept, dropped


# v25.31 NEW: สีโครงสร้างตู้ (floor tile / wall panel / rear-wall) ที่พบซ้ำๆ ในทุกไฟล์ตัวอย่าง
# (ไม่ใช่สีของกล่องสินค้า/SKU ใดๆ - เป็นสีคงที่ที่ซอฟต์แวร์วาดไดอะแกรมใช้แทนพื้น/ผนัง/หลังคาตู้
# เสมอ) ยืนยันจาก EC16: ทั้ง 16 'side' fragment ที่พบมีสีตรงกับรายการนี้ 100% ไม่มี fragment
# ไหนเป็นสีกล่องจริงเลยแม้แต่ชิ้นเดียว - ตรงกับที่ CONTAINER_RAIL_COLOR (203,203,101) ด้านบนของ
# ไฟล์ระบุไว้แล้วว่าเป็นสีขอบตู้ และ docstring เดิมของ v25.13 ก็เคยระบุ (178,178,89) เป็นสีหลังคา
_STRUCTURAL_CONTAINER_COLORS = [
    (203, 203, 101),  # ขอบฐานตู้ (rail) - ตรงกับ CONTAINER_RAIL_COLOR
    (179, 179, 90),   # แผงผนังตู้ (wall panel)
    (255, 255, 133),  # พื้นตู้ (floor tile)
    (255, 255, 175),  # ผนังหลัง/หลังคาตู้ (rear wall / roof)
]
_STRUCTURAL_COLOR_TOL = 12


# v25.39 NEW (สำคัญ - พบจริงจากไฟล์ AC03-01 ที่ผู้ใช้ขอให้ทดสอบเพิ่มเติมหลัง v25.38): เดิม
# ตรวจสีโครงสร้างตู้ด้วยรายการสีตายตัว (exact-match list + tolerance=12) - พบว่าไฟล์ AC03-01 มี
# ผนังปลายตู้ (endcap wall จริง ยืนยันด้วยภาพ) ที่ใช้สี (227,227,114) ซึ่งต่างจากทุกสีใน
# catalog เดิมเกิน tolerance (diff สูงสุด 24 เทียบ tolerance=12) ทำให้หลุดรอดการกรอง กลายเป็น
# คอลัมน์ front-face ปลอมแทรกกลางแถว (FRONT นับได้ 11 แทนที่จะเป็น 10 กล่องจริง -> reconcile
# กับ BACK=7 เหลือ 8 แทนที่จะเป็น 7 ที่ถูกต้อง)
# ROOT CAUSE ที่แท้จริง: สีโครงสร้างตู้ทุกสีที่เคย catalog ไว้ (รวมสีใหม่นี้ด้วย) มี "รูปแบบ hue"
# ร่วมกันชัดเจน คือ R≈G เสมอ (โทนน้ำตาล/ทอง ไม่ใช่สีสดแบบกล่องสินค้า) และ R-B อยู่ในช่วงแคบๆ
# (วัดได้จริง 80-122 จากสีที่ catalog ไว้ทั้งหมด) - ตรวจสอบยืนยันด้วยสี 'front'-kind ทั้งหมด 16 สี
# ที่พบจริงข้าม 11 ไฟล์ทดสอบ พบว่ามีแค่ 3 สีที่เข้า pattern นี้ (178,178,89)/(227,227,114)/
# (255,255,175) และทั้ง 3 สีเป็นสีโครงสร้างตู้จริงทั้งหมด (2 ใน 3 ตรงกับ/ใกล้เคียง catalog เดิม
# มาก - ไม่มี false-positive กับสีกล่องสินค้าเลยแม้แต่สีเดียว รวมถึง (128,128,0) ซึ่งเป็นสีกล่อง
# จริง (STEMB) ที่ R-B=128 เกินขอบเขตบนพอดี (125) จึงไม่ถูกจับผิดพลาด)
# FIX: เพิ่มการตรวจจับด้วย pattern (hue-based) เป็นชั้นที่ 2 ต่อจาก exact-match list เดิม - ถ้า
# สีใดตรง exact-list เดิม (คงไว้ทุกประการ ไม่กระทบ) หรือเข้า pattern ใหม่นี้ ก็ถือเป็นสีโครงสร้าง
# ตู้ทั้งคู่ (union ของ 2 เงื่อนไข ไม่ใช่แทนที่กัน - ปลอดภัยกว่าเพราะยังคงพฤติกรรมเดิมสำหรับสีที่
# เคย verify ไว้แล้ว และเพิ่มการครอบคลุมสีใหม่ที่มี hue เดียวกันแต่ค่าต่างออกไปเล็กน้อย)
_STRUCTURAL_HUE_RG_MAX_DIFF = 8     # R และ G ต้องใกล้เคียงกันมาก (โทนน้ำตาล/ทอง ไม่ใช่สีสด)
_STRUCTURAL_HUE_RB_MIN = 75          # R-B ขั้นต่ำ (กันสีที่ B สูงใกล้ R เช่นสีเทา/ขาว)
_STRUCTURAL_HUE_RB_MAX = 125         # R-B ขั้นสูง (กันสีเหลือง/มะกอกเข้มที่เป็นสีกล่องจริง เช่น
# (128,128,0) ที่ R-B=128 เกินขอบเขตนี้ไปเล็กน้อยพอดี - ยืนยันด้วยข้อมูลจริงจาก AB01-02/AC02-02)


# v25.41 NEW (สำคัญ - พบจริงจากไฟล์ EB74-ALL ที่ผู้ใช้ขอให้ทดสอบหลัง v25.40): เดิม pattern
# เชิง hue (v25.39) ตรวจเฉพาะทิศทาง "R≈G, R-B บวก" (โทนน้ำตาล/ทอง) - พบว่าไฟล์ EB74-ALL ใช้
# โทนสีผนังตู้เป็น "ฟ้าอมเขียว" (90,179,179) และ (175,255,255) ซึ่งเป็น hue-pattern เดียวกัน
# ทุกประการแค่ "สลับแกน" (G≈B แทนที่จะเป็น R≈G, และ B-R บวกแทนที่จะเป็น R-B บวก) - ยืนยันด้วย
# ตัวเลข: (90,179,179) มี G-B=0, B-R=89 ตรงกับช่วง 75-125 เดียวกันกับที่เคย catalog ไว้เป๊ะ
# (แค่คนละแกนสี) - ทดสอบยืนยันกับสี 'front'-kind ทั้งหมด 14 สีที่พบจริงข้าม 7 ไฟล์ทดสอบ (รวม
# EB74-ALL) พบว่า pattern ใหม่ (รองรับทั้ง 2 แกน) จับได้เฉพาะ 3 สีที่เป็นโครงสร้างตู้จริงเท่านั้น
# ((90,179,179)/(175,255,255)/(255,255,175)) ไม่มี false-positive กับสีกล่องสินค้าเลยแม้แต่สี
# เดียว รวมถึง (0,255,255) cyan และ (0,128,128) teal ซึ่งเป็นสีกล่องจริงที่ใกล้เคียงกันก็ไม่ถูก
# จับผิดพลาด (เพราะ R,G,B ต่างกันมากเกินไปในทุกคู่แกน)
# FIX: เพิ่มการตรวจสอบทิศทางที่ 2 (G≈B, B-R อยู่ในช่วงเดียวกัน) เป็น OR เพิ่มเติมจากทิศทางเดิม
def _p1b_is_structural_container_color(color):
    """True ถ้าสีนี้ตรงกับสีโครงสร้างตู้ที่ทราบแน่ชัด (ไม่ใช่สีกล่องสินค้า) - ตรวจ 3 ชั้น:
    (1) exact-match list เดิม (ดู docstring _STRUCTURAL_CONTAINER_COLORS)
    (2) pattern เชิง hue ทิศทาง R≈G (v25.39) สำหรับสีโครงสร้างโทนน้ำตาล/ทอง
    (3) pattern เชิง hue ทิศทาง G≈B (v25.41) สำหรับสีโครงสร้างโทนฟ้า/เขียวอมฟ้า - ดู docstring
    ด้านบนสำหรับหลักฐาน+เหตุผล (พบจริงจาก EB74-ALL)"""
    for sc in _STRUCTURAL_CONTAINER_COLORS:
        if all(abs(int(color[i]) - sc[i]) <= _STRUCTURAL_COLOR_TOL for i in range(3)):
            return True
    r, g, b = int(color[0]), int(color[1]), int(color[2])
    # ทิศทางที่ 1: R≈G, R-B บวกอยู่ในช่วง (โทนน้ำตาล/ทอง)
    if abs(r - g) <= _STRUCTURAL_HUE_RG_MAX_DIFF and _STRUCTURAL_HUE_RB_MIN <= (r - b) <= _STRUCTURAL_HUE_RB_MAX:
        return True
    # ทิศทางที่ 2: G≈B, B-R บวกอยู่ในช่วง (โทนฟ้า/เขียวอมฟ้า - v25.41)
    if abs(g - b) <= _STRUCTURAL_HUE_RG_MAX_DIFF and _STRUCTURAL_HUE_RB_MIN <= (b - r) <= _STRUCTURAL_HUE_RB_MAX:
        return True
    return False


# v25.36 NEW: "endcap wall" (ผนังปลายหัวตู้/ท้ายตู้ - ภาพตัดขวางแสดงกล่องหลายใบซ้อนแนวตั้งที่
# ปลายสุดของตู้ ไม่ใช่แถวซ้ำของ idx จริง) ตามที่ผู้ใช้สอน (ยืนยันด้วยภาพจริง EA10 BACK) - เดิมตรวจ
# จับด้วยรายชื่อสีเฉพาะ (_STRUCTURAL_CONTAINER_COLORS) แต่พบว่าผนังปลายตู้ในบางไฟล์ใช้สีที่ไม่ตรง
# กับรายการนี้เป๊ะ (เช่น EA10/EC01-02/04 BACK ใช้สี (255,255,147) ซึ่งห่างจาก (255,255,133) ที่มี
# อยู่แล้วถึง 14 (เกิน tolerance=12 ไปเล็กน้อย) ทำให้หลุดรอดการตรวจจับ)
# ROOT CAUSE ที่แท้จริง (ยืนยันด้วยข้อมูลจริงข้าม 5 ไฟล์): ผนังปลายตู้นี้ถูกซอฟต์แวร์วาดไดอะแกรม
# เรนเดอร์ด้วย "สัดส่วนกว้าง/สูงคงที่เสมอ" (w/h ratio) ไม่ว่าจะเป็นไฟล์ไหนหรือสีอะไร เพราะมันคือ
# ภาพตัดขวางของหน้าตัดตู้ (ความกว้าง 2400mm x ความสูงตู้) ที่ render ด้วย isometric scale เดียวกัน
# เสมอ - วัดได้จริงจากทั้ง 5 ไฟล์ทดสอบ: w/h = 0.577-0.578 คงที่มาก (EA10/EC01-02/04 BACK:
# w=215,h=372,ratio=0.578 | EC16/EB01 FRONT: w=213,h=369,ratio=0.577) ต่างจาก 'side' ประเภทอื่น
# อย่างชัดเจน (แผงผนังรางแคบ: ratio~1.38 | พื้นกระเบื้อง: ratio~1.99 - ทั้งคู่ 'กว้างกว่าสูง' ตรง
# ข้ามกับผนังปลายตู้ที่ 'สูงกว่ากว้าง' เสมอ)
# FIX: ตรวจจับด้วยรูปทรง (aspect ratio) แทนสีเฉพาะเจาะจง - รองรับผนังปลายตู้ทุกสีตามที่ผู้ใช้ระบุ
_ENDCAP_WALL_RATIO_TARGET = 0.577  # อัตราส่วน w/h เฉลี่ยที่วัดได้จริงจาก 5 ไฟล์
_ENDCAP_WALL_RATIO_TOL = 0.08      # ยอมรับส่วนเบี่ยงเบน ±0.08 (ครอบคลุม 0.497-0.657) กันความ
# คลาดเคลื่อนเล็กน้อยจากการ render/crop แต่ยังห่างไกลจาก ratio ของ 'side' ประเภทอื่น (1.38, 1.99)
# มากพอที่จะไม่มีทางปนกันโดยบังเอิญ
_ENDCAP_WALL_MIN_AREA = 20000  # ต้องมีพื้นที่ใหญ่พอ (กันเศษชิ้นเล็กที่บังเอิญมีสัดส่วนใกล้เคียง)


def _p1b_is_endcap_wall_shape(w, h, area=None):
    """True ถ้า fragment นี้มีรูปทรง (w/h ratio) ตรงกับ 'ผนังปลายหัวตู้/ท้ายตู้' ตามที่วัดได้จริง
    (ไม่ขึ้นกับสี) - ดู docstring เต็มด้านบนสำหรับหลักฐาน+เหตุผล"""
    if h <= 0:
        return False
    if area is not None and area < _ENDCAP_WALL_MIN_AREA:
        return False
    ratio = w / h
    return abs(ratio - _ENDCAP_WALL_RATIO_TARGET) <= _ENDCAP_WALL_RATIO_TOL


# v25.43 NEW (สำคัญ - พบจริงจาก AB01-02 ที่ผู้ใช้ถามเรื่อง "ช่วงสีม่วง"): เดิม _p1b_find_
# endcap_wall_span ตรวจจับผนังปลายตู้ด้วยรูปทรง (w/h ratio) ของ 'side' fragment เพียงอย่างเดียว
# โดยไม่ตรวจสอบว่ามีกล่องสินค้าจริง (front-face สีต่างจากผนัง) วางซ้อนทับอยู่ในโซนเดียวกันหรือไม่
# พบว่าไฟล์ AB01-02 มีกล่อง TPR1A-AO (สีม่วง 128,0,128) วางอยู่ตำแหน่งสุดท้ายติดผนังหลังตู้พอดี
# (เต็มความสูงเกือบชิดเพดาน) ทำให้ x-range ของกล่องทับซ้อนกับผนังหลัง (255,255,175) ที่ตรวจพบว่า
# มีรูปทรง w/h ตรงกับ endcap-wall เป๊ะ (ratio=0.577) - ระบบเข้าใจผิดว่าทั้งโซนเป็นผนังเปล่า
# ทั้งที่มี front-face สีม่วง+เขียวอมฟ้า (STEMA-A3 teal) ซ้อนทับอยู่เต็มพื้นที่จริง (4 ชิ้น รวม
# พื้นที่มาก) ทำให้กล่องทั้ง 2 ตำแหน่งถูกกรองทิ้งไปอย่างผิดพลาด (หายไปจากผลลัพธ์สุดท้ายทั้งหมด)
# ROOT CAUSE: endcap wall แท้จริง (เช่น EA10 ที่ยืนยันกฎนี้ไว้ก่อนหน้า) เป็น "ผนังเปล่า" ที่ไม่มี
# กล่องสินค้าจริงบังอยู่ด้านหน้าเลย (มองทะลุเห็นผนังเต็มพื้นที่) ต่างจากกรณีนี้ที่ผนังหลังตู้ปกติ
# (rear-wall) ถูกกล่องจริงบังจนเกือบมิด (เห็นผนังแค่ขอบบน/ล่างเล็กน้อย) - สัญญาณที่แยกแยะได้คือ
# "สัดส่วนพื้นที่ที่ front-face สีไม่ใช่โครงสร้างซ้อนทับอยู่ในโซน" - ถ้าสูง (มีกล่องจริงเต็มพื้นที่)
# แสดงว่าไม่ใช่ endcap wall เปล่า ต้องไม่กรองทิ้ง
# FIX: ก่อนยอมรับ candidate ว่าเป็น endcap wall ตรวจสอบว่ามี front-face ที่ไม่ใช่สีโครงสร้างตู้
# ซ้อนทับกับ x-range ของมันเกิน _ENDCAP_WALL_MAX_GENUINE_FRONT_COVERAGE หรือไม่ - ถ้าเกิน (มีกล่อง
# จริงเต็มพื้นที่) ให้ปฏิเสธ candidate นี้ (ไม่ถือเป็น endcap wall) เพื่อความปลอดภัยไม่กระทบไฟล์ที่
# endcap wall เป็นผนังเปล่าจริง (เช่น EA10 ที่ยืนยันไว้ก่อนหน้า)
_ENDCAP_WALL_MAX_GENUINE_FRONT_COVERAGE = 0.5
# v25.46 NEW: เกณฑ์ area ขั้นต่ำที่ถือว่า front-face 'มีนัยสำคัญมากพอ' จะเป็นกล่องเต็มใบจริง
# (ไม่ใช่เศษเล็กที่บังเอิญปนอยู่) - ยืนยันจาก AB01-02: STEMA-A3 front-face area=5994 (ใหญ่กว่า
# เศษทั่วไปที่พบ 1200-2000px มาก) ตั้งค่าไว้กึ่งกลางระหว่าง 2 ช่วงนี้เพื่อความปลอดภัย
_ENDCAP_WALL_SIGNIFICANT_FRONT_AREA = 3500


def _p1b_find_endcap_wall_span(all_cells):
    """หา x-range ของ 'ผนังปลายตู้' (endcap wall) ในภาพนี้ ถ้ามี - คืนค่า (x0,x1) ของ 'side'
    fragment ที่ตรงรูปทรงผนังปลายตู้ (ดู _p1b_is_endcap_wall_shape) และไม่มีกล่องสินค้าจริงบังอยู่
    เต็มพื้นที่ (v25.43 - ดู docstring ด้านบน) หรือ None ถ้าไม่พบ ถ้าพบมากกว่า 1 ชิ้น (ที่ผ่าน
    เกณฑ์ทั้งคู่) ใช้ชิ้นที่ใหญ่ที่สุด (พื้นที่มากสุด) เป็นตัวแทน"""
    sides = [c for c in all_cells if c['kind'] == 'side']
    shape_candidates = [c for c in sides
                        if _p1b_is_endcap_wall_shape(c['w'], c['h'], c.get('area', c['w'] * c['h']))]
    if not shape_candidates:
        return None
    genuine_fronts = [c for c in all_cells if c['kind'] == 'front'
                      and not _p1b_is_structural_container_color(c['color'])]
    candidates = []
    for cand in shape_candidates:
        cx0, cx1 = cand['x'], cand['x'] + cand['w']
        # v25.46 FIX (สำคัญ - พบจริงจาก AB01-02 regression ระหว่างพัฒนา orphaned-roof
        # detection): เดิมคำนวณ coverage แบบ "รวม interval ที่ทับซ้อนตรงๆ" (อาจนับซ้ำถ้า
        # front-face หลายชิ้นทับซ้อนกันเอง หรือคำนวณต่ำกว่าจริงถ้าแยกเป็นหลายชิ้นเล็กๆ) - พบว่า
        # กรณี STEMA-A3 (teal) ที่เป็นกล่องแรกสุดในตู้ (ไม่มีอะไรบัง) มี front-face จริงชัดเจน
        # (area=5994) ซ้อนทับกับ endcap-wall-shape candidate 64px จาก 215px (=30% ของพื้นที่
        # ผนัง) แต่ threshold เดิม (50%) หลวมเกินไป ทำให้ front-face จริงนี้ถูกกรองทิ้งอย่าง
        # ผิดพลาด (คิดว่าเป็นผนังเปล่า) - ทำให้กล่อง teal หายไปจากคอลัมน์ที่นับได้ตั้งแต่ต้น
        # FIX: ใช้ union coverage (พิกเซล-ระดับ ไม่นับซ้ำ) แทนการรวม interval ตรงๆ เพื่อความ
        # แม่นยำสูงสุด (ถึงแม้ในกรณีนี้ผลจะไม่ต่างจากเดิมมากนัก แต่ปลอดภัยกว่าในกรณีทั่วไป)
        gspan = int(cx1 - cx0)
        covered = [False] * max(1, gspan)
        for f in genuine_fronts:
            fx0, fx1 = f['x'], f['x'] + f['w']
            ov0 = max(cx0, fx0); ov1 = min(cx1, fx1)
            for px in range(int(max(cx0, ov0)), int(min(cx1, ov1))):
                idx = px - int(cx0)
                if 0 <= idx < gspan:
                    covered[idx] = True
        coverage_frac = sum(covered) / max(1, gspan)
        # v25.46 FIX (สำคัญ - พบจริงจาก AB01-02): เดิมใช้แค่เกณฑ์ coverage_frac (สัดส่วนพื้นที่)
        # เพียงอย่างเดียว - พบว่ากรณี STEMA-A3 (teal, กล่องแรกสุดในตู้ที่มองเห็นได้เต็มรูปแบบ
        # area=5994) ซ้อนทับกับ endcap-candidate แค่ 30% ของพื้นที่ผนัง (ต่ำกว่า threshold เดิม
        # 50%) ทำให้ยังถูกกรองทิ้งอย่างผิดพลาด ทั้งที่ front-face ขนาดใหญ่ขนาดนี้ (ไม่ใช่เศษเล็ก
        # 1200-2000px ที่พบทั่วไป) คือหลักฐานหนักแน่นว่ามีกล่องจริงเต็มใบอยู่ตรงนั้น ไม่ใช่ผนัง
        # เปล่า - FIX: เพิ่มเงื่อนไข OR - ถ้ามี genuine front-face เดี่ยวที่มี area สูงมาก
        # (>= _ENDCAP_WALL_SIGNIFICANT_FRONT_AREA) ซ้อนทับกับ candidate แม้แต่ชิ้นเดียว (ไม่ว่า
        # coverage% จะเท่าไหร่) ให้ปฏิเสธ endcap ทันที - เป็นเงื่อนไขเสริมที่เข้มงวดกว่าเดิม
        # (ไม่ได้ผ่อนปรน) จึงไม่กระทบไฟล์ที่ endcap ถูกต้องอยู่แล้ว (เช่น EA10) เพราะเงื่อนไขเดิม
        # (coverage_frac) ยังคงทำงานควบคู่กันแบบ AND ไม่ใช่แทนที่
        has_significant_front = any(
            f['area'] >= _ENDCAP_WALL_SIGNIFICANT_FRONT_AREA
            and max(0.0, min(cx1, f['x'] + f['w']) - max(cx0, f['x'])) > 0
            for f in genuine_fronts)
        if coverage_frac <= _ENDCAP_WALL_MAX_GENUINE_FRONT_COVERAGE and not has_significant_front:
            candidates.append(cand)
    if not candidates:
        return None
    best = max(candidates, key=lambda c: c['w'] * c['h'])
    return best['x'], best['x'] + best['w']


def _p1b_front_faces(crop, area_min=1200):
    cells = _p1b_classify_view(crop, area_min=area_min)
    # v25.31 FIX (สำคัญ - พบเป็น side-effect จากการแก้ dedup ด้านล่าง): เดิม fragment สีโครงสร้าง
    # ตู้ (เช่น ผนังหลัง/หลังคา 255,255,175) ที่บังเอิญมี aspect-ratio/saturation เข้าเกณฑ์ 'front'
    # เคยถูก 'บังเอิญ' ลบทิ้งไปโดยกลไก duplicate-removal เดิม (เพราะ bbox ทับซ้อนกับกล่องสีอื่น
    # โดยไม่เช็คสี) แต่เมื่อแก้ dedup ให้เช็คสีแล้ว (ดู docstring ด้านล่าง) fragment สีโครงสร้างนี้
    # ไม่ถูกลบอีกต่อไป กลายเป็นคอลัมน์ปลอมใหม่ (ยืนยันจาก EC01-02: พบ fragment สี (255,255,175)
    # รอดออกมาเป็นคอลัมน์เดี่ยวหลังแก้ dedup) - FIX: กรองสีโครงสร้างตู้ที่ทราบแน่ชัดออกจาก
    # 'front' candidates ตั้งแต่ต้น ก่อนเข้าสู่ทุกขั้นตอนถัดไป (ปลอดภัย เพราะสีเหล่านี้ไม่ใช่สี
    # กล่องสินค้าแน่นอน ไม่ว่าจะถูกจัดเป็น kind ใดก็ตาม)
    cells = [c for c in cells
             if not (c['kind'] == 'front' and _p1b_is_structural_container_color(c['color']))]
    # v25.36 NEW (สำคัญ - พบจริงจาก EA10 BACK): กรอง front-face/roof ใดๆ ที่ x-range ทับซ้อนกับ
    # 'ผนังปลายหัวตู้/ท้ายตู้' (endcap wall) ออกทั้งหมด - ผนังนี้คือภาพตัดขวางแสดงกล่องหลายใบซ้อน
    # แนวตั้งที่ปลายสุดของตู้ (มองเห็นจากมุมกล้องที่ตรงกับปลายตู้พอดี) ไม่ใช่แถวซ้ำของ idx จริง
    # ตามที่ผู้ใช้สอน - ยืนยันด้วยภาพจริง EA10: หลังคาสีแดง (roof, ไม่มี front-face คู่กันเลย) ที่
    # ทับซ้อนกับผนังนี้ เคยถูกเข้าใจผิดว่าเป็น 'foreign roof / side-wall noise' แล้วไปกระตุ้นให้
    # _p1b_drop_side_wall_contaminated_columns ตัดคอลัมน์ข้างเคียงอื่นทิ้งผิดพลาด (คนละคอลัมน์กับ
    # ที่ควรตัดจริง) - การกรองออกตั้งแต่ต้นทางนี้ (ก่อนกลายเป็น front/roof candidate) ป้องกันปัญหา
    # ทั้งสายที่อาจเกิดจากเศษของผนังนี้ได้ครบวงจร ไม่ใช่แค่จุดเดียว
    # ดู _p1b_find_endcap_wall_span/_p1b_is_endcap_wall_shape สำหรับหลักฐาน+เหตุผลเต็ม (ตรวจจับ
    # จากรูปทรง w/h ratio คงที่ ~0.577 แทนสีเฉพาะ - รองรับผนังปลายตู้ทุกสีตามที่ผู้ใช้ระบุ)
    endcap_span = _p1b_find_endcap_wall_span(cells)
    if endcap_span is not None:
        ec_x0, ec_x1 = endcap_span

        def _frac_of_candidate_inside_wall(c):
            # v25.36 FIX (สำคัญ - พบ regression จริงจาก EB01): เดิมใช้ _p1b_x_overlap_frac_
            # generic ซึ่งหารด้วย 'ความกว้างที่แคบกว่า' ของทั้งคู่ (ตาม docstring เดิมของฟังก์ชัน
            # นั้นที่ออกแบบมาสำหรับ use-case อื่น) - ทำให้ roof ของกล่องจริงที่กว้างกว่าผนังปลายตู้
            # มาก (เช่น EB01: roof กว้าง 326px เทียบกับผนังกว้างแค่ 213px) ถูกคำนวณ overlap
            # fraction เทียบกับผนัง (ตัวหารเล็ก) แทนที่จะเทียบกับตัว roof เอง ทำให้ได้ค่าสูงเกินจริง
            # (0.601 ทั้งที่จริงทับซ้อนแค่ 39% ของ roof เอง) จนถูกกรองทิ้งผิดพลาด กลายเป็น regression
            # ที่ทำให้เหลือ roof แค่ 2 ชิ้น (เข้าเงื่อนไข 'exactly 2' ของ v25.35 โดยไม่ตั้งใจ) แล้ว
            # ไปกระตุ้น roof-overlap-merge ยุบทุกคอลัมน์ผิดพลาด
            # FIX: คำนวณ 'สัดส่วนของตัว fragment เอง (roof/front) ที่ตกอยู่ในเขตผนัง' โดยตรง (หาร
            # ด้วยความกว้างของตัว fragment เองเสมอ ไม่ใช่ค่า min) - ความหมายที่ถูกต้องคือ 'fragment
            # นี้เกือบทั้งชิ้นอยู่ในเขตผนังหรือไม่' ไม่ใช่ 'ผนังเกือบทั้งแผ่นถูกทับด้วย fragment นี้'
            c_x0, c_x1 = c['x'], c['x'] + c['w']
            inter = max(0.0, min(c_x1, ec_x1) - max(c_x0, ec_x0))
            return inter / max(1e-6, c_x1 - c_x0)

        cells = [c for c in cells
                 if not (c['kind'] in ('front', 'roof')
                         and _frac_of_candidate_inside_wall(c) >= 0.5)]
    fronts = [c for c in cells if c['kind'] == 'front']
    roofs = [c for c in cells if c['kind'] == 'roof']
    # v25.27 NEW: กรอง front-face ของกล่อง 'แถวใน' (inner-row, ซ้ำซ้อนกับขั้นบันไดหลังคา) ก่อน
    # ทำ duplicate-removal เดิม (ดู docstring _p1b_filter_inner_row_fronts สำหรับหลักฐานเต็ม)
    fronts, inner_dropped = _p1b_filter_inner_row_fronts(fronts, roofs)
    # v25.27 NEW: กรอง 'เศษบาง' (side-sliver) ที่เหลือ - เศษของ front-face เดียวกันที่ถูกบัง
    # บางส่วนจนเหลือแถบแคบผิดปกติ (ดู docstring _p1b_filter_side_slivers)
    fronts, sliver_dropped = _p1b_filter_side_slivers(fronts)
    fronts.sort(key=lambda c: -c['area'])
    kept = []
    for c in fronts:
        dup = False
        for k in kept:
            # v25.31 FIX (สำคัญ - พบจริงจาก EC16): เดิมตัดสิน 'duplicate' จากแค่ bbox overlap
            # โดยไม่เช็คสีเลย - พบว่ากล่อง 2 ใบที่วางซ้อนกันจริง (คนละสี คนละใบ เช่น กล่องเขียว
            # วางอยู่บนกล่องฟ้า) มี bbox ที่คาบเกี่ยวกันในแนวตั้ง (เพราะกล่องชนกันพอดี) ทำให้
            # inter/min_area สูงเกิน 0.6 และถูกเข้าใจผิดว่าเป็น 'เศษซ้ำของกล่องเดียวกัน' (ทั้งที่
            # ควรเป็น 'front' เดียวกันจริงถ้าเป็นกล่องใบเดียวที่ถูกตัวอักษร/เส้นแบ่งเป็นชิ้นๆ) ทำให้
            # กล่องใบหนึ่งถูกลบทิ้งไปอย่างผิดพลาด (ยืนยันด้วยภาพจริง EC16: เขียว+ฟ้า เป็นกล่องคนละ
            # ใบที่วางซ้อนกันจริง ratio ที่วัดได้=1.04 เกิน 0.6 มาก)
            # FIX: ต้อง 'สีเดียวกัน' เท่านั้นจึงจะพิจารณาว่าเป็น duplicate (เพราะเศษที่แตกจาก
            # กล่องใบเดียวกันจริงจากตัวอักษร/anti-aliasing จะคงสีเดิมเป๊ะเสมอ ต่างจากกล่องคนละใบ
            # ที่มีสีต่างกันชัดเจน) - ไม่กระทบกรณีกล่องหลายสีซ้อนกันในคอลัมน์เดียวกันจริง (เช่น
            # AC02-02/EC01-02) เพราะกรณีนั้นจัดการที่ขั้นตอน cluster_columns ซึ่งเป็นคนละหน้าที่
            if c['color'] != k['color']:
                continue
            ox0 = max(c['x'], k['x']); oy0 = max(c['y'], k['y'])
            ox1 = min(c['x'] + c['w'], k['x'] + k['w']); oy1 = min(c['y'] + c['h'], k['y'] + k['h'])
            inter = max(0, ox1 - ox0) * max(0, oy1 - oy0)
            if inter > 0.6 * min(c['area'], k['area']):
                dup = True
                break
        if not dup:
            kept.append(c)
    kept.sort(key=lambda c: c['cx'])
    # v25.28 NEW: นับจำนวน fragment ที่ถูก 'พิสูจน์แล้วจริง' ว่าเป็นแถวใน/เศษบาง (ไม่ใช่กล่อง
    # แยกต่างหาก) ด้วยกฎ v25.27 - ใช้เป็นหลักฐานให้ _p1b_reconcile_with_back ตัดสินใจว่าจำนวน
    # คอลัมน์ที่นับได้น้อยกว่า BACK นั้น 'ถูกต้องแล้วจริง' (ไม่ใช่บั๊ก undercount) ดู docstring
    # เต็มที่ _p1b_reconcile_with_back
    n_dropped_by_new_rules = len(inner_dropped) + len(sliver_dropped)
    return kept, cells, n_dropped_by_new_rules


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


# v25.31 NEW: เกณฑ์ x-range overlap ขั้นต่ำ (เทียบกับความกว้างที่แคบกว่า) ที่ยอมรับว่า fragment
# สีต่างกัน 2 ชิ้น อยู่ 'ตำแหน่งความยาวเดียวกันจริง' (genuine same-idx multi-color stack เช่น
# กรณีที่ยืนยันแล้วจาก EC01-02: กล่องฟ้า(cyan)+แดง(red) มี x-range ทับซ้อนกันเกือบ 100% เพราะเป็น
# กล่องคนละใบที่วางในตำแหน่งความยาวเดียวกันจริง ไม่ใช่บั๊ก) - ตั้งค่าสูง (0.7) เพราะต้องการแยกแยะ
# จากกรณี "คอลัมน์ข้างเคียงที่บังเอิญมี cx ใกล้กัน" ซึ่งควร overlap ต่ำหรือไม่ overlap เลย
CLUSTER_DIFF_COLOR_MIN_XOVERLAP = 0.7

# v25.44 NEW (สำคัญ - พบจริงจาก AB01-02 BACK ที่ผู้ใช้ถามเรื่อง "ช่วงสีม่วง"): เดิม x-overlap
# rule (v25.31 ด้านบน) ไม่มีขีดจำกัดจำนวนสีที่รวมกันได้ในคอลัมน์เดียว - พบว่า BACK view ของ
# AB01-02 รวม 4 สีต่างกัน (olive/purple/magenta/teal) เข้าเป็นคอลัมน์เดียวผิดพลาด ทั้งที่ยืนยัน
# ด้วยภาพจริงแล้วว่าเป็นกล่องคนละตำแหน่งจริง (STEMA-teal และ TPR1A-purple เป็นคนละตำแหน่งความยาว
# ในภาพ FRONT ชัดเจน) ทำให้กล่องเหล่านี้หายไปจากผลลัพธ์สุดท้ายหลัง reconcile กับ FRONT
# ROOT CAUSE: x-overlap ratio (ทั้งแบบธรรมดาและ pairwise ทุกคู่) ไม่สามารถแยกแยะกรณีนี้จากกรณีที่
# ถูกต้องแล้ว (AC02-02 BACK ที่รวม 3 สี purple/darkred/blue อย่างถูกต้อง - ยืนยันด้วย pairwise
# overlap ที่ได้ค่า 1.000 เท่ากันหมดทั้ง 2 กรณี ไม่ต่างกันเลย) - ทดสอบ roof-matching evidence ก็
# ไม่สามารถแยกแยะได้เช่นกัน (AC02-02's darkred ที่ merge ถูกต้อง กลับไม่มี roof สนับสนุนเลย
# เหมือนกับ AB01-02's magenta ที่ merge ผิดพลาด)
# สัญญาณเดียวที่แยกแยะได้ชัดเจนจากข้อมูลจริงทั้งหมด (สำรวจครบ 9 ไฟล์ x 2 view = 18 จุดทดสอบ):
# "จำนวนสีที่แตกต่างกันสูงสุดที่เคย merge ถูกต้องจริงคือ 3 สี (AC02-02 BACK)" ในขณะที่กรณีที่
# ยืนยันว่าผิดพลาด (AB01-02 BACK) มี 4 สี - ไม่มีไฟล์ใดในชุดทดสอบที่มี genuine 4-color merge เลย
# เหตุผลเชิงกายภาพที่สนับสนุน: ไดอะแกรมตู้คอนเทนเนอร์แบบ isometric นี้ ตามปกติมีความลึกสูงสุดแค่
# 2-3 ชั้น (แถวหน้า+แถวหลัง+อาจมีกล่องเตี้ยแทรกอีก 1 ชั้น) ที่จะมองเห็น front-face ซ้อนทับกันที่
# ตำแหน่งความยาวเดียวกันได้ - การมี 4 สีต่างกันซ้อนทับกันจริงในตำแหน่งเดียวเป็นไปได้ยากมาก
# FIX: จำกัดจำนวนสีที่แตกต่างกันสูงสุดต่อคอลัมน์ไว้ที่ 3 - ถ้าคอลัมน์มีสีที่แตกต่างกันครบ 3 สีแล้ว
# (ไม่นับซ้ำ) และมีสีใหม่ (สีที่ 4) พยายามจะรวมเข้ามาอีก ให้ปฏิเสธเสมอ (เปิดคอลัมน์ใหม่แทน) โดยไม่
# สนใจผล x-overlap เลย - ปลอดภัยเพราะยืนยันด้วยข้อมูลจริงแล้วว่าไม่มีไฟล์ใดในชุดทดสอบที่มี
# genuine 4-color merge (ทดสอบยืนยันครบ 9 ไฟล์ x 2 view แล้วไม่พบ false-positive กับกรณีที่ถูก
# ต้องเลย รวมถึง AC02-02's 3-color merge ที่ยังคงทำงานถูกต้องเหมือนเดิมทุกประการ เพราะจำกัดที่ 3
# ไม่ใช่ 2)
CLUSTER_MAX_DISTINCT_COLORS = 3


def _p1b_cluster_columns(fronts, cx_tol=45):
    """v25.31 FIX (สำคัญ - พบจริงจาก EC01-02/04): เดิมจัดกลุ่มคอลัมน์ด้วยระยะห่างตำแหน่ง cx
    (center-x) เพียงอย่างเดียว โดยไม่สนใจสีหรือ x-range ที่แท้จริงเลย - แม้ในทางปฏิบัติ cx_tol
    (adaptive, ~40% ของความกว้างกล่องมัธยฐาน) จะเล็กพอที่จะไม่รวมคอลัมน์ข้างเคียงที่ไกลกันจริงเข้า
    ด้วยกันโดยบังเอิญ (ระยะห่างจริงระหว่างคอลัมน์ ~2.5x ของ cx_tol ในไฟล์ทดสอบทั้งหมด) แต่ก็ยังมี
    ความเสี่ยงเชิงทฤษฎีที่ fragment สีต่างกัน 2 ชิ้นซึ่ง "ไม่ได้อยู่ตำแหน่งความยาวเดียวกันจริง"
    (ไม่ใช่ genuine stack) อาจบังเอิญมี cx ใกล้กันมากพอจนถูกรวมผิดคอลัมน์โดยไม่มีการตรวจสอบใดๆ เลย

    FIX (ระมัดระวังไม่ทำลายกรณีถูกต้อง): เพิ่มเงื่อนไข - ถ้า fragment ที่จะรวมมีสีเดียวกับสมาชิก
    ใดๆ ในคอลัมน์นั้นอยู่แล้ว ใช้เกณฑ์ cx_tol เดิม (พฤติกรรมเดิมทุกประการ ไม่กระทบ merge ของ
    fragment สีเดียวกันที่ถูกตัวอักษร/เส้นแบ่งเป็นชิ้นๆ) - แต่ถ้าสีต่างจากสมาชิกทุกตัวในคอลัมน์
    (หมายถึงกำลังจะรวมสีใหม่เข้าไป เช่น กรณี genuine multi-color-per-idx stack) ต้องผ่านเกณฑ์
    เพิ่มเติม: x-range ของ fragment ต้องทับซ้อนกับ x-range ของคอลัมน์อย่างมาก (>=70% ของความกว้าง
    ที่แคบกว่า) จึงจะยอมรับว่าเป็น 'ตำแหน่งความยาวเดียวกันจริง' (ยืนยันจาก EC01-02: cyan(903-1005)
    กับ red(904-1009) overlap เกือบ 100% - ผ่านเกณฑ์นี้สบายๆ เพราะเป็นกรณีถูกต้องจริง) ถ้าไม่ผ่าน
    เกณฑ์ x-overlap (เช่น คอลัมน์ข้างเคียงที่ไม่ทับซ้อนกันจริง เพียงแค่ cx บังเอิญใกล้กัน) จะไม่ถูก
    รวมเข้าคอลัมน์เดิม แต่จะเปิดคอลัมน์ใหม่แทน (ปลอดภัยกว่าการรวมผิดคอลัมน์)"""
    fronts = sorted(fronts, key=lambda c: c['cx'])
    cols = []
    for c in fronts:
        placed = False
        for col in cols:
            if abs(col['cx'] - c['cx']) > cx_tol:
                continue
            same_color_member = any(m['color'] == c['color'] for m in col['members'])
            if not same_color_member:
                # v25.44 FIX: ก่อนพิจารณา x-overlap ตรวจสอบจำนวนสีที่แตกต่างกันในคอลัมน์นี้ก่อน -
                # ถ้าครบ CLUSTER_MAX_DISTINCT_COLORS แล้ว (สีใหม่นี้จะเป็นสีที่ 4+) ปฏิเสธทันที
                # ไม่ต้องเช็ค x-overlap เลย (ดู docstring เต็มด้านบน CLUSTER_MAX_DISTINCT_COLORS)
                n_distinct_colors = len(set(m['color'] for m in col['members']))
                if n_distinct_colors >= CLUSTER_MAX_DISTINCT_COLORS:
                    continue
                # สีใหม่ที่ไม่มีในคอลัมน์นี้เลย - ต้องพิสูจน์ด้วย x-range overlap ก่อนรวม
                col_x0, col_x1 = col['x'], col['x'] + col['w']
                c_x0, c_x1 = c['x'], c['x'] + c['w']
                ov = _p1b_x_overlap_frac_generic(col_x0, col_x1, c_x0, c_x1)
                if ov < CLUSTER_DIFF_COLOR_MIN_XOVERLAP:
                    continue
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
    phase1_detect.py ต้นทาง สำหรับคำอธิบายละเอียด + ตัวอย่างข้อมูลจริงที่ยืนยันแล้ว)

    v25.31 FIX (สำคัญ - พบจริงจาก EC16): เดิมใช้ 'side'-kind fragment ทุกชิ้นเป็นหลักฐานเชื่อม
    คอลัมน์ โดยไม่แยกแยะว่าเป็น "เศษด้านข้างของกล่องจริง" (corner-camera artifact ที่ควรใช้เป็น
    หลักฐาน) หรือ "พื้น/ผนัง/หลังคาของตัวตู้เอง" (โครงสร้างคงที่ที่ไม่เกี่ยวกับกล่องเลย) - พบว่า
    ไฟล์ที่บรรทุกเบาบาง (มีพื้นที่ว่างเยอะ ทำให้มองเห็นพื้น/ผนังตู้เป็นแถบกว้างต่อเนื่องยาวเกือบ
    ตลอดความยาวตู้) ทำให้แถบพื้น/ผนังนี้ไป 'ทับซ้อน' (overlap>=50%) กับคอลัมน์ที่อยู่ห่างไกลกัน
    หลายคอลัมน์พร้อมกัน กลายเป็นหลักฐานเท็จที่เชื่อมทุกคอลัมน์เข้าด้วยกันเป็น 1 คอลัมน์เดียว ทั้งที่
    เป็นกล่องคนละใบจริง (ยืนยันจาก EC16: ทั้ง 16 side-fragment ที่ตรวจพบมีสีตรงกับสีโครงสร้างตู้
    ที่ทราบแน่ชัด 100% ไม่มีชิ้นไหนเป็นสีกล่องเลย)
    FIX: กรองสีโครงสร้างตู้ที่ทราบแน่ชัดออกจาก 'sides' ก่อนใช้เป็นหลักฐาน (ดู
    _p1b_is_structural_container_color) - เหลือเฉพาะ 'side' fragment ที่เป็นสีกล่องจริงเท่านั้น
    มาใช้เป็นหลักฐานเชื่อมคอลัมน์ตามเดิม (ไม่กระทบไฟล์ที่มี corner-artifact จริงจากสีกล่องเลย)"""
    n = len(cols)
    if n < 2:
        return list(cols), []
    cols = sorted(cols, key=lambda c: c['cx'])
    sides = [c for c in all_cells
             if c['kind'] == 'side' and not _p1b_is_structural_container_color(c['color'])]
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
    BACK: roof สีแปลกปลอมในโซนแผงข้างที่ไม่มี front-face สีเดียวกันปรากฏที่ไหนเลยในภาพ)

    v25.20 FIX (พบจริงจาก AE02-01/AE02-02 BACK - ยืนยันด้วยภาพจริง + pixel seam-scan):
    เดิม logic วนลูป drop ทีละ foreign-roof-candidate แยกกัน ไม่จำกัดจำนวน - พบว่าไฟล์ AE02-01/02
    มี candidate 2 ชิ้น (ไม่ใช่ 1 ชิ้นแบบ EC04-04) ทำให้ column ถูกตัดทิ้งถึง 2 คอลัมน์ (BACK จาก
    7 เหลือ 5) ทั้งที่ตรวจสอบด้วยภาพจริงแล้วว่าทั้ง 2 คอลัมน์เป็นกล่องจริง (มีกล่องสีแดงซ้อนอยู่
    เป็นชั้นที่ 3 บนกองใกล้หัวรถ ทำให้ roof สีแดงมีมากกว่า 1 ชิ้นและมี aspect ไม่ถึงเกณฑ์ 'front'
    ในมุมมอง BACK พอดี - ไม่ใช่ noise จากผนังข้างเหมือน EC04-04)

    หลักฐานที่แยกแยะได้ชัดเจน (ตรวจสอบครบทั้ง 15 ไฟล์ calibration): EC04-04 BACK (กรณี noise
    จริงที่ยืนยันแล้ว) มี candidate ที่ผ่านเกณฑ์ (ไม่มี front จับคู่ในวิวเดียวกัน) เพียง "1 ชิ้น"
    เท่านั้น ในขณะที่ AE02-01/02 BACK มี "2 ชิ้น" พอดี - noise จากผนังข้างจริงมักเป็น artifact
    ชิ้นเดียวที่ลอยเดี่ยวๆ ส่วนกล่องสินค้าจริงที่ซ้อนเป็นชั้นเพิ่มมักปรากฏเป็นหลายชิ้น (หลายกอง)
    พร้อมกัน จึงเพิ่มเงื่อนไข: ถ้ามี candidate มากกว่า 1 ชิ้น ให้ถือว่าเป็นกล่องสินค้าจริง (ไม่ตัด
    ทิ้งเลยทั้งกลุ่ม) แทนที่จะตัดทิ้งทีละชิ้นแบบเดิม (regression-verified: EC04-04 ยังคง drop
    ถูกต้องเหมือนเดิมทุกประการ เพราะมี candidate แค่ 1 ชิ้น - ไม่กระทบไฟล์อื่นเลยเพราะฟังก์ชันนี้
    ถูกเรียกเฉพาะกับ BACK เท่านั้น ในทั้ง 15 ไฟล์มีแค่ AE02-01/02/EC04-04 ที่มี candidate จริง)

    v25.22 FIX (แก้ marker คลาดเคลื่อน 1 ตำแหน่ง ที่พบจริงจาก AE02-01 BACK):
    ปัญหา: แม้ v25.20 จะเพิ่มเงื่อนไข candidates==1 แล้ว แต่พบว่า AE02-01 ยังเข้าเงื่อนไขนี้ได้
    เมื่อกล่องแดงชั้น 3 บน "กอง 1 กองเดียว" ทำให้ได้ candidate=1 → ตัด nearest_col ทิ้ง →
    back_cols เหลือ 6 จาก 7 → seam/boundary เลื่อน → marker วาดผิดตำแหน่ง 1 ช่อง

    Root cause: nearest_col ที่ถูกตัดคือกองที่มีกล่องแดงซ้อนอยู่จริงๆ ไม่ใช่ side-wall noise
    สัญญาณที่บ่งบอกว่า "foreign roof อยู่บนกองจริง" คือ foreign_roof มี x-overlap
    กับ nearest_col สูง (roof อยู่บนกอง = x-range ทับกัน) ต่างจาก side-wall noise จริง
    (EC04-04) ที่ roof ลอยอยู่นอกขอบ nearest_col (x-overlap ต่ำ)

    FIX: ก่อน drop ตรวจ x-overlap ระหว่าง candidate roof กับ nearest_col
    ถ้า overlap >= 30% ของ roof width → roof นั้นอยู่บนกองจริง → ไม่ตัด (return ทันที)
    ถ้า overlap < 30% → roof ลอยนอกกอง → เป็น side-wall noise จริง → ตัดได้ปลอดภัย

    regression-verified: EC04-04 (noise จริง) roof อยู่นอกขอบ nearest_col (overlap ต่ำ)
    → ยังคง drop ถูกต้องเหมือนเดิม | AE02-01 (กล่องจริง) roof ทับบนกอง (overlap สูง)
    → ไม่ตัดแล้ว → back_cols ครบ 7 → marker ตรงตำแหน่ง"""
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
    candidates = [fr for fr in foreign_roofs_in_zone
                  if not any(f['color'] == fr['color'] for f in all_fronts)]

    print(f"[DROP_SIDE] foreign_roofs_in_zone={len(foreign_roofs_in_zone)}, "
          f"candidates={len(candidates)}, cols_in={len(cols)}")

    if len(candidates) != 1:
        # 0 candidate = ไม่มีอะไรต้องตัด, >=2 candidates = แพทเทิร์นกล่องสินค้าจริงซ้อนหลายชิ้น
        # (ดู docstring v25.20) ไม่ใช่ noise เดี่ยวๆ แบบ EC04-04 -> ไม่ตัดทิ้งเลยเพื่อความปลอดภัย
        return cols, []

    # v25.22 FIX: ตรวจ x-overlap ระหว่าง candidate roof กับ nearest_col ก่อนตัดทิ้ง
    # ถ้า roof ทับบนกอง (overlap สูง) = กล่องจริงซ้อนอยู่บนนั้น ไม่ใช่ noise → ไม่ตัด
    kept, dropped = list(cols), []
    for fr in candidates:
        if not kept:
            continue
        nearest_col = min(kept, key=lambda c: abs(c['cx'] - fr['cx']))

        # คำนวณ x-overlap ระหว่าง roof กับ nearest_col
        roof_x0, roof_x1 = fr['x'], fr['x'] + fr['w']
        col_x0, col_x1 = nearest_col['x'], nearest_col['x'] + nearest_col['w']
        overlap_px = max(0.0, min(roof_x1, col_x1) - max(roof_x0, col_x0))
        roof_width = max(1, roof_x1 - roof_x0)
        overlap_frac = overlap_px / roof_width

        print(f"[DROP_SIDE] candidate roof color={fr['color']} "
              f"x=[{roof_x0},{roof_x1}] nearest_col cx={nearest_col['cx']:.1f} "
              f"x=[{col_x0},{col_x1}] overlap_frac={overlap_frac:.2f}")

        if overlap_frac >= 0.30:
            # roof ทับบนกองจริง (>= 30% ของ roof width) → เป็นกล่องสินค้าจริงที่ซ้อนอยู่
            # ไม่ใช่ side-wall noise → ไม่ตัดทิ้ง ออกจากลูปทันที
            print(f"[DROP_SIDE] overlap_frac={overlap_frac:.2f} >= 0.30 → roof อยู่บนกองจริง "
                  f"ไม่ตัด col นี้ (v25.22 FIX)")
            return kept, []

        # overlap ต่ำ = roof ลอยนอกขอบกอง = side-wall noise จริง (เช่น EC04-04) → ตัดได้
        print(f"[DROP_SIDE] overlap_frac={overlap_frac:.2f} < 0.30 → side-wall noise → drop col")
        kept.remove(nearest_col)
        dropped.append(nearest_col)

    print(f"[DROP_SIDE] cols_out={len(kept)} (dropped {len(dropped)})")
    return kept, dropped


def _p1b_roof_extent(cells):
    roofs = [c for c in cells if c['kind'] == 'roof']
    if not roofs:
        return None
    x0 = min(c['x'] for c in roofs)
    x1 = max(c['x'] + c['w'] for c in roofs)
    return x0, x1


# v25.46 NEW: "Orphaned Roof Detection" (หลังคาที่ไม่มีคอลัมน์ front-face รองรับ) - ตามที่ผู้ใช้
# ยืนยันด้วยภาพจริง AC04-03: พบว่ากล่อง SNPR-AT (เทาม่วง) และ SHP1A-F2 (ส้ม) ในภาพ FRONT ถูกกอง
# NTC1A-F1/F2 (เขียวทีล, แถวหลัง) ที่สูงกว่ามากบดบัง front-face จนเหลือน้อยเกินไป (area เพียง
# 1966px และ 1251px ตามลำดับ - ต่ำกว่า/ใกล้เคียง area_min=1200 มาก) ทำให้ทั้ง 2 ตำแหน่งไม่ถูกนับ
# เป็นคอลัมน์เลยในผลลัพธ์สุดท้าย ทั้งที่มองเห็น "หลังคา" (roof) ของทั้งคู่ชัดเจนในภาพ (พื้นที่
# roof ใหญ่กว่า front-face มาก เพราะมุมกล้อง isometric ทำให้หลังคาโผล่พ้นขึ้นมาเต็มรูปแบบ แม้
# ตัวกล่องจะถูกบังเกือบหมดก็ตาม)
#
# ROOT CAUSE: หลังคา (roof) คือหลักฐานที่เชื่อถือได้กว่า front-face ในกรณีที่กล่องถูกบังเกือบมิด
# เพราะรูปทรงสี่เหลี่ยมขนมเปียกปูนของหลังคาไม่ได้ถูกบังในแนวนอน (x) เท่ากับ front-face (ซึ่งถูก
# บังในแนวตั้ง y จากกล่องแถวหลังที่สูงกว่า) - จึงสามารถใช้ตำแหน่ง x ของ roof เป็นหลักฐานสร้าง
# คอลัมน์ synthetic ขึ้นมาได้ แม้ front-face จะไม่พอจะนับเป็นคอลัมน์ปกติก็ตาม
#
# วิธีตรวจจับ (ทำงาน "หลังจาก" ได้คอลัมน์สุดท้ายจาก merge_corner + roof-overlap-merge แล้ว แต่
# "ก่อน" reconcile_with_back เพื่อให้ synthetic column ที่เพิ่มเข้ามาถูกนำไป reconcile กับ BACK
# ตามปกติ ไม่ต้องเขียน logic คู่ขนานแยกต่างหาก): สำหรับแต่ละ 'roof' ที่มีอยู่ในภาพ - ตรวจสอบว่า
# x-range ของมันถูกคอลัมน์ front-face ที่มีอยู่แล้ว "ครอบคลุม" (cover) มากพอหรือไม่ (เทียบสัดส่วน
# ความกว้างของ roof ที่ทับซ้อนกับคอลัมน์ใดๆ) - ถ้าความครอบคลุมต่ำกว่า threshold (บ่งชี้ว่า roof
# นี้ "ไม่มีตัวแทน" ในคอลัมน์ที่นับไปแล้วเลย) ให้จัดกลุ่ม roof ที่ตำแหน่งใกล้เคียงกัน (ของสีเดียว
# กัน หรือคนละสีที่ x-range ทับซ้อนกันมาก - เผื่อกรณีหลายกล่องซ้อนกันในแนวลึกที่ตำแหน่งเดียวกัน
# เหมือน SNPR-AT+SHP1A-F2 ในภาพจริง) แล้วสร้างคอลัมน์ synthetic ขึ้นจาก union bbox ของกลุ่มนั้น
#
# Guard สำคัญ (ป้องกัน false-positive): กำหนด min_roof_area (กันเศษ noise เล็กๆ ที่ไม่ใช่หลังคา
# กล่องจริง) และ max_coverage_frac (ถ้า roof ถูกคอลัมน์ที่มีอยู่ครอบคลุมมากพอแล้ว แสดงว่านับไป
# แล้วจริง ไม่ต้องสร้างคอลัมน์ใหม่ซ้ำซ้อน)
_ORPHANED_ROOF_MIN_AREA = 4000  # ต้องมีพื้นที่ใหญ่พอจึงเชื่อว่าเป็นหลังคากล่องจริง (ไม่ใช่ noise)
_ORPHANED_ROOF_MAX_COVERAGE = 0.3  # ถ้าคอลัมน์ที่มีอยู่ครอบคลุม roof นี้เกิน 30% แล้ว ถือว่า
# "มีตัวแทนอยู่แล้ว" ไม่ต้องสร้าง synthetic column ซ้ำ (ยืนยันจาก AC04-03: roof ของกล่องที่นับ
# ไปแล้วปกติ (front-face ใหญ่) มักถูกคอลัมน์ตัวเองครอบคลุม >=80-100% อยู่แล้ว ต่างจากกรณี orphan
# ที่ coverage=0% เพราะไม่มีคอลัมน์ front-face ใดๆ ในตำแหน่งนั้นเลย)
_ORPHANED_ROOF_ANY_COLOR_MAX_COVERAGE = 0.85  # v25.48 NEW: ดู docstring เต็มในลูปคำนวณ cov_any
# ด้านล่าง (ใน _p1b_find_orphaned_roof_columns) - threshold สูงเพื่อแยก AA02-01 (99% covered,
# ไม่ควร orphan) ออกจาก AC04-03 (~60% covered, ควร orphan จริง) ให้ถูกต้องทั้งคู่

_ORPHANED_ROOF_GROUP_XOVERLAP = 0.5  # เกณฑ์ x-overlap สำหรับจัดกลุ่ม roof หลายชิ้นที่ตำแหน่ง
# เดียวกัน (เช่น SNPR-AT+SHP1A-F2 ซ้อนกันในแนวลึกที่ตำแหน่งความยาวเดียวกัน) ให้เป็น 1 synthetic
# column เดียว - หมายเหตุ: parameter นี้เหลืออยู่เพื่อความเข้ากันได้ของ signature เดิม แต่ไม่ได้
# ใช้งานจริงแล้วในเวอร์ชันนี้ (ดู docstring ในฟังก์ชันสำหรับเหตุผล - การจัดกลุ่มซ้ำซ้อนที่เคยใช้
# parameter นี้ถูกตัดออกไปแล้วเพราะพบ bug จริง)


def _p1b_find_orphaned_roof_columns(existing_cols, all_cells,
                                     min_area=_ORPHANED_ROOF_MIN_AREA,
                                     max_coverage=_ORPHANED_ROOF_MAX_COVERAGE,
                                     group_xoverlap=_ORPHANED_ROOF_GROUP_XOVERLAP):
    """v25.46 NEW: หา 'roof' ที่ไม่มีคอลัมน์ front-face ใดๆ ครอบคลุมเพียงพอ (orphaned roof) แล้ว
    สร้างคอลัมน์ synthetic ขึ้นจากกลุ่ม roof ที่ตำแหน่งใกล้เคียงกัน - คืนค่า list ของคอลัมน์ใหม่
    (โครงสร้างเดียวกับ cols ปกติ: x,y,w,h,cx,cy,members) พร้อม flag 'from_orphaned_roof'=True
    เพื่อให้ debug/ตรวจสอบย้อนหลังได้ง่าย - ดู docstring เต็มด้านบนสำหรับหลักฐาน+เหตุผล"""
    # v25.46 FIX (สำคัญ - พบระหว่างทดสอบ AB01-02 regression): เดิมไม่กรองสีโครงสร้างตู้ (เช่น
    # พื้นตู้ 255,255,133) ออกจาก roof candidates เลย ทำให้ 'พื้นตู้ที่มองเห็นได้กว้าง' (บริเวณ
    # ที่บรรทุกเบาบาง) ถูกเข้าใจผิดเป็น orphaned roof (สร้างคอลัมน์ปลอมขึ้นมา ทั้งที่ไม่ใช่กล่อง
    # สินค้าเลย) - FIX: กรองสีโครงสร้างตู้ที่ทราบแน่ชัดออกก่อน (ใช้ตัวตรวจสอบเดียวกับที่ใช้กรอง
    # front-face structural-color อยู่แล้วใน _p1b_front_faces เพื่อความสอดคล้องกันทั้งระบบ)
    roofs = [c for c in all_cells if c['kind'] == 'roof' and c['area'] >= min_area
             and not _p1b_is_structural_container_color(c['color'])]
    if not roofs:
        return []

    # v25.46 FIX (สำคัญ - พบระหว่างทดสอบ AB01-02 regression): กล่องที่สูงมากมักมี 'หลังคา'
    # ถูกตัดเป็นหลายชิ้นต่อเนื่องกัน (เช่น TPR1A-AO purple มี roof 3 ชิ้นทอดยาว x=(1303,1455),
    # (1373,1525), (1461,1614)) - ชิ้นที่อยู่ใกล้คอลัมน์ front-face จริง (เช่น ชิ้นสุดท้ายที่ x
    # ตรงกับคอลัมน์ cx=1502.5 ที่มีอยู่แล้ว) จะผ่านเกณฑ์ coverage ปกติ แต่ชิ้นก่อนหน้าที่ทอดยาว
    # ออกไป (x=1303-1455) ไม่ทับซ้อนกับคอลัมน์นั้นโดยตรง (ห่างกันแค่ไม่กี่ px) ทำให้ถูกเข้าใจผิด
    # ว่าเป็น orphaned roof ทั้งที่เป็นหลังคาต่อเนื่องของกล่องเดียวกันจริง (roof ชิ้นนี้ทับซ้อนกับ
    # roof ชิ้นถัดไปเอง 82px - ยืนยันว่าเป็นแนวต่อเนื่องเดียวกัน ไม่ใช่กล่องคนละใบ)
    # FIX: ก่อนเช็ค coverage กับคอลัมน์ ให้รวมกลุ่ม roof สีเดียวกันที่ x-range ทับซ้อน/ต่อเนื่อง
    # กันเข้าด้วยกันก่อน (union-find) แล้วเช็ค coverage จาก x-range ของทั้งกลุ่ม (ไม่ใช่แค่ roof
    # ชิ้นเดียว) - ถ้ากลุ่มนั้นมีชิ้นใดชิ้นหนึ่งที่คอลัมน์ front-face จริงครอบคลุมมากพอ ให้ถือว่า
    # ทั้งกลุ่ม (รวมชิ้นที่ทอดยาวออกไป) "มีตัวแทนแล้ว" เช่นกัน
    n_roofs = len(roofs)
    roof_parent = list(range(n_roofs))

    def rfind(x):
        while roof_parent[x] != x:
            roof_parent[x] = roof_parent[roof_parent[x]]
            x = roof_parent[x]
        return x

    def runion(a, b):
        ra, rb = rfind(a), rfind(b)
        if ra != rb:
            roof_parent[ra] = rb

    for i in range(n_roofs):
        for j in range(i + 1, n_roofs):
            if roofs[i]['color'] != roofs[j]['color']:
                continue
            a0, a1 = roofs[i]['x'], roofs[i]['x'] + roofs[i]['w']
            b0, b1 = roofs[j]['x'], roofs[j]['x'] + roofs[j]['w']
            if min(a1, b1) - max(a0, b0) > 0:  # ทับซ้อนกันจริง (ไม่ใช่แค่ใกล้กัน)
                runion(i, j)

    roof_groups = {}
    for i in range(n_roofs):
        roof_groups.setdefault(rfind(i), []).append(i)

    orphaned_groups = []
    for group_idxs in roof_groups.values():
        group_roofs = [roofs[i] for i in group_idxs]
        gx0 = min(r['x'] for r in group_roofs)
        gx1 = max(r['x'] + r['w'] for r in group_roofs)
        # v25.46 FIX (สำคัญ - พบ bug จริงระหว่างทดสอบ AB01-02): เดิมเช็ค coverage ทีละคอลัมน์
        # แล้วเอาค่ามากสุด (max) เป็นตัวตัดสิน - พบว่ากล่องที่สูงมาก (เช่น TPR1A-AO purple) อาจมี
        # front-face ถูกแบ่งเป็นหลายคอลัมน์แยกกัน (คนละ x-range) ที่แต่ละคอลัมน์เดี่ยวๆ ครอบคลุม
        # roof ได้แค่บางส่วน (28%, 21%) ไม่ถึง threshold แยกกัน แต่เมื่อรวมกันจริง (union ของ
        # ทั้ง 2 คอลัมน์) ครอบคลุมได้ถึง 49% ซึ่งเกิน threshold แล้ว - การใช้ max ทีละคอลัมน์ทำให้
        # เข้าใจผิดว่า 'ไม่มีตัวแทน' ทั้งที่มีตัวแทนอยู่แล้วจริง (แค่กระจายอยู่หลายคอลัมน์)
        # FIX: คำนวณ 'union coverage' จากทุกคอลัมน์สีเดียวกันรวมกัน (สร้าง boolean array แทน
        # แต่ละพิกเซลใน x-range ของกลุ่ม แล้วนับว่าพิกเซลใดถูกคอลัมน์ใดคอลัมน์หนึ่งครอบคลุมบ้าง -
        # ป้องกันการนับซ้ำถ้าคอลัมน์ทับซ้อนกันเอง)
        gspan = int(gx1 - gx0)
        covered = [False] * max(1, gspan)
        covered_any_color = [False] * max(1, gspan)
        for col in existing_cols:
            # v25.46 FIX (สำคัญ - พบระหว่างทดสอบ AC04-03): เดิมเช็ค coverage กับ "ทุกคอลัมน์"
            # โดยไม่สนใจสี ทำให้ roof สีส้ม (SHP1A-F2) ที่ x-range บังเอิญทับซ้อนกับคอลัมน์สีเขียว
            # ทีล (NTC1A, แถวหลัง คนละกล่องกันจริง) เกิน threshold ถูกเข้าใจผิดว่า "มีตัวแทนแล้ว"
            # ทั้งที่คอลัมน์เขียวทีลนั้นไม่ใช่ตัวแทนของกล่องส้มเลย - FIX: ต้องมีสมาชิกอย่างน้อย
            # 1 ชิ้นในคอลัมน์นั้นที่ "สีเดียวกับ roof" ก่อน จึงจะนับ coverage จากคอลัมน์นั้นได้
            # (สอดคล้องกับหลักการเดิมทั้งหมดของระบบที่ยึดสีเป็นตัวระบุตัวตนกล่อง)
            same_color = any(m['color'] == group_roofs[0]['color'] for m in col.get('members', []))
            cx0, cx1 = col['x'], col['x'] + col['w']
            ov0 = max(gx0, cx0); ov1 = min(gx1, cx1)
            for px in range(int(max(gx0, ov0)), int(min(gx1, ov1))):
                idx = px - int(gx0)
                if 0 <= idx < gspan:
                    if same_color:
                        covered[idx] = True
                    covered_any_color[idx] = True
        cov = sum(covered) / max(1, gspan)
        # v25.48 NEW (สำคัญ - พบ regression จริงจาก AA02-01 BACK): same-color coverage check
        # (v25.46) ป้องกัน false-positive แบบ AC04-03 ได้ (orange vs teal คนละกล่องกันจริง) แต่
        # ทำให้เกิด false-positive แบบใหม่กับ AA02-01: หลังคาสีฟ้า (MAPCA, w=205) ที่จริงๆ ถูก
        # "คอลัมน์สีเขียว (DSC1A) ที่มีอยู่แล้ว 2 คอลัมน์ติดกัน" ครอบคลุมพื้นที่เกือบเต็ม (union
        # ของทั้ง 2 คอลัมน์ = 203/205 = 99% แม้จะคนละสีก็ตาม) ถูกเข้าใจผิดว่า orphan เพราะไม่มี
        # คอลัมน์ไหน "สีฟ้า" เลยสักคอลัมน์ (same-color coverage=0%)
        # ROOT CAUSE ที่แยกแยะ 2 กรณีนี้ได้จริง (ตรวจสอบด้วยข้อมูลจริงทั้งคู่): AC04-03's teal
        # orphan (รวม 4 ชิ้นแล้วกว้างถึง 525px) แม้แต่นับรวมทุกสีก็ยังถูกคอลัมน์ที่มีอยู่ครอบคลุม
        # แค่ ~60% (มีช่องว่างจริงถึง 206px ที่ไม่มีคอลัมน์ใดเลยครอบคลุม เพราะกล่อง NTC1A ถูกบัง
        # เกือบมิดจริง) ในขณะที่ AA02-01's cyan orphan (w=205, ไม่ได้ merge จากหลายชิ้น) ถูกคอลัมน์
        # ที่มีอยู่ครอบคลุมสูงถึง 99% (แทบไม่มีช่องว่างเลย เพราะเป็นแค่หลังคาที่โผล่แทรกระหว่าง
        # คอลัมน์เขียว 2 คอลัมน์ที่นับครบถ้วนอยู่แล้ว) - ใช้ threshold สูง (85%) เพื่อแยก 2 กรณีนี้
        # FIX: เพิ่มเงื่อนไข OR - ถ้า any-color union coverage สูงมาก (>=85%, แทบไม่มีช่องว่าง)
        # ให้ถือว่า "มีตัวแทนอยู่แล้วจริง" แม้จะคนละสีก็ตาม (เพราะแทบไม่มีพื้นที่เหลือให้กล่องอื่น
        # ซ่อนอยู่ได้จริง) - ไม่กระทบ AC04-03 (coverage แค่ ~60% ยังต่ำกว่า 85% มาก ยังคง orphan)
        cov_any = sum(covered_any_color) / max(1, gspan)
        if cov < max_coverage and cov_any < _ORPHANED_ROOF_ANY_COLOR_MAX_COVERAGE:
            orphaned_groups.append(group_roofs)

    if not orphaned_groups:
        return []

    # v25.46 FIX (สำคัญ - พบ bug จริงระหว่างทดสอบ AB01-02): เดิมหลังได้ orphaned roof (flat
    # list) มาแล้ว มีการจัดกลุ่มซ้ำเป็นครั้งที่ 2 ด้วยเกณฑ์ x-overlap แบบ "สัดส่วนต่อความกว้างที่
    # แคบกว่า" (group_xoverlap=0.5) - พบว่าเกณฑ์นี้เข้มกว่าการจัดกลุ่มในขั้นตอนแรก (ซึ่งใช้แค่
    # 'ทับซ้อนกันจริง (>0)' ของ roof สีเดียวกัน) ทำให้กลุ่ม TPR1A-AO (purple) 3 ชิ้นที่รวมกันแล้ว
    # อย่างถูกต้องในขั้นตอนแรก (ทับซ้อนต่อเนื่องกันจริง 82px และ 64px) กลับถูกแยกออกเป็น 2 กลุ่ม
    # อีกครั้งในขั้นตอนที่ 2 (เพราะ roof แต่ละชิ้นกว้างถึง ~150px ทำให้ overlap-ratio ต่ำกว่า 0.5
    # ทั้งที่ทับซ้อนกันจริงในเชิงพิกเซล) สร้างคอลัมน์ synthetic ปลอมซ้ำซ้อนกับคอลัมน์ purple ที่มี
    # อยู่แล้ว (regression: FRONT เพิ่มจาก 7 เป็น 8 คอลัมน์ผิดพลาด)
    # FIX: ตัดขั้นตอนการจัดกลุ่มซ้ำซ้อนนี้ทิ้งทั้งหมด - ใช้ roof_groups ที่ได้จากขั้นตอนแรก
    # (ซึ่งจัดกลุ่มถูกต้องแล้วด้วยเงื่อนไข 'ทับซ้อนกันจริง' ของ roof สีเดียวกัน) สร้างคอลัมน์
    # synthetic โดยตรงจากแต่ละกลุ่มที่ผ่านเกณฑ์ orphaned (ไม่ต้อง group_xoverlap parameter อีก
    # ต่อไป - คงพารามิเตอร์นี้ไว้ใน signature เพื่อความเข้ากันได้แต่ไม่ใช้งานแล้ว)
    new_cols = []
    for group_roofs in orphaned_groups:
        x0 = min(m['x'] for m in group_roofs)
        y0 = min(m['y'] for m in group_roofs)
        x1 = max(m['x'] + m['w'] for m in group_roofs)
        y1 = max(m['y'] + m['h'] for m in group_roofs)
        new_cols.append(dict(x=x0, y=y0, w=x1 - x0, h=y1 - y0,
                              cx=(x0 + x1) / 2, cy=(y0 + y1) / 2,
                              members=group_roofs, from_orphaned_roof=True))
    return new_cols


# v25.35 NEW: กฎ "overlapping-roof merge" ตามที่ผู้ใช้สอน (ยืนยันด้วยภาพจริง EC16 ที่ mark X):
# "ตามกฎ FRONT view ตำแหน่ง idx นั้นๆ หากมี top-face (roof) มากกว่า 1 ชิ้น ให้นับเป็น idx เดียว
# ที่ตำแหน่งตรงนั้น" - หลักฐานที่ยืนยัน: EC16 FRONT มีหลังคา 2 ชิ้น (เขียว x=(1336,1542) และ
# เหลือง x=(1443,1646)) ที่ x-range ทับซ้อนกันจริง 99px (ไม่ใช่แค่ใกล้กัน) - เมื่อรวม span ของ
# หลังคาทั้ง 2 เป็นช่วงเดียว (x=1336-1646) พบว่าตรงกับ x-range ของ front-face fragment ทั้ง 5
# ชิ้นที่ตรวจพบ (เขียว×2, ฟ้า, เหลือง×2) พอดี - ยืนยันว่าทั้งหมดนี้คือ "1 ตำแหน่งความยาวจริง"
# (กองสีเขียว+ฟ้าที่สูงกว่า อยู่ 'แถวหลัง' ข้ามความกว้างตู้ ซ้อนทับกับกองเหลืองที่ 'แถวหน้า' ณ
# ตำแหน่งความยาวเดียวกัน มุมมอง isometric ทำให้หลังคาทั้ง 2 กองปรากฏซ้อนทับกันในภาพ FRONT)
# หมายเหตุสำคัญ: กฎนี้ใช้ "การซ้อนทับของหลังคา (roof)" เป็นหลักฐาน ไม่ใช่การซ้อนทับของสี/
# front-face โดยตรง - เพราะหลังคาสะท้อนตำแหน่งจริงของกล่องในแนวลึก (ข้ามความกว้างตู้) ได้แม่นยำ
# กว่า ไม่ปะปนกับกรณี "กล่องหลายสีซ้อนกันในคอลัมน์เดียวกันจริง" (เช่น AC02-02/EC01-02 ที่ front-
# face สีต่างกันซ้อนทับกันแต่เป็นคนละ idx จริง - กรณีนั้นจัดการแยกต่างหากใน _p1b_cluster_columns
# ด้วยเกณฑ์ x-overlap ของ front-face เอง ไม่เกี่ยวกับ roof)
_ROOF_OVERLAP_MERGE_MIN_PX = 5  # ต้องทับซ้อนอย่างน้อยกี่ pixel จึงถือว่า 'ทับซ้อนจริง' (กันการ
# นับพลาดจากการแตะขอบกันพอดีโดยบังเอิญ ซึ่งไม่ใช่การซ้อนทับจริง)


def _p1b_group_overlapping_roofs(roofs, min_overlap_px=_ROOF_OVERLAP_MERGE_MIN_PX):
    """จัดกลุ่ม 'roof' (top-face) ที่ x-range ทับซ้อนกันจริง (ไม่ว่าจะสีอะไร) เข้าด้วยกันแบบ
    union-find (transitive - ถ้า A ทับ B และ B ทับ C ทั้ง 3 จะถูกจัดกลุ่มเดียวกัน แม้ A ไม่ทับ C
    โดยตรง) คืนค่า list ของ (x0, x1) แทนแต่ละกลุ่มที่มี >= 2 roof ทับซ้อนกันจริง (กลุ่มที่มี roof
    เดียวไม่ถือเป็นหลักฐานสำหรับ merge - ดู docstring _p1b_group_overlapping_roofs ผู้เรียกใช้)"""
    n = len(roofs)
    if n < 2:
        return []
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

    for i in range(n):
        for j in range(i + 1, n):
            a0, a1 = roofs[i]['x'], roofs[i]['x'] + roofs[i]['w']
            b0, b1 = roofs[j]['x'], roofs[j]['x'] + roofs[j]['w']
            overlap_px = max(0, min(a1, b1) - max(a0, b0))
            if overlap_px >= min_overlap_px:
                union(i, j)

    groups = {}
    for i in range(n):
        r = find(i)
        groups.setdefault(r, []).append(i)

    spans = []
    for idxs in groups.values():
        # v25.35 FIX (สำคัญ - พบ regression รุนแรงจาก EC01-02/04 ไฟล์บรรทุกเต็มคัน): เดิม
        # ยอมรับกลุ่มที่มี roof ทับซ้อนกัน >=2 ชิ้นทั้งหมด ไม่จำกัดจำนวน - พบว่าไฟล์ที่บรรทุกเต็มคัน
        # (กล่องเรียงชิดกันแน่นตลอดความยาวตู้) มีรูปแบบ 'หลังคาขั้นบันได' (roofline staircase)
        # ตามธรรมชาติของมุมมอง isometric ที่ทำให้หลังคาของคอลัมน์ข้างเคียงทับซ้อนกันเล็กน้อยที่
        # ขอบต่อเนื่องกันเป็น 'ลูกโซ่ยาว' ตลอดทั้งแถว (ยืนยันจาก EC01-02: หลังคา 11 ชิ้น ทับซ้อน
        # กันต่อเนื่องจนกลายเป็น 1 กลุ่มเดียวครอบคลุมเกือบทั้งภาพ - ถ้า merge ตามนี้จะยุบทุกคอลัมน์
        # เป็น 1 คอลัมน์เดียวผิดพลาดร้ายแรง) ต่างจาก EC16 ที่มีกรณี 'ตำแหน่งเดียวกัน ซ้อนกันจริง
        # ตามความลึก' (2 แถวข้ามความกว้างตู้) ซึ่งเกิดขึ้นแบบ 'โดดเดี่ยว' (กลุ่มเล็กๆ ไม่ต่อเนื่อง
        # เป็นลูกโซ่ยาวกับคอลัมน์อื่นๆ ทั้งแถว)
        # FIX: จำกัดเฉพาะกลุ่มที่มี roof ทับซ้อนกันพอดี "2 ชิ้น" เท่านั้น (ไม่ใช่ >=2 แบบเดิม) -
        # กลุ่มที่มี 3 ชิ้นขึ้นไปมักบ่งชี้ว่าเป็นลูกโซ่ต่อเนื่องตามธรรมชาติของภาพเต็มคัน ไม่ใช่
        # หลักฐาน 'ซ้อนทับตำแหน่งเดียวกันจริง' ที่ผู้ใช้ต้องการให้ merge (ปลอดภัยกว่าเดิมมาก เพราะ
        # กรณีจริงที่ต้องการ merge มักมีแค่ 2 แถว (หน้า+หลัง) ไม่ใช่หลายแถวพร้อมกัน)
        if len(idxs) != 2:
            continue
        x0 = min(roofs[i]['x'] for i in idxs)
        x1 = max(roofs[i]['x'] + roofs[i]['w'] for i in idxs)
        spans.append((x0, x1))
    return spans


def _p1b_merge_columns_by_overlapping_roofs(cols, all_cells):
    """v25.35 NEW: รวมคอลัมน์ (idx) ที่ตำแหน่ง x ตกอยู่ในช่วงที่มี 'หลังคาซ้อนทับกันจริง' (>=2
    roof คนละสีที่ x-range ทับซ้อนกัน) ให้เหลือ 1 คอลัมน์เดียว - ดู docstring เต็มด้านบน
    _ROOF_OVERLAP_MERGE_MIN_PX สำหรับหลักฐาน+เหตุผลตามที่ผู้ใช้สอน (ยืนยันจาก EC16)

    คืนค่า (merged_cols, n_merges) - n_merges ใช้เป็นข้อมูลเสริมสำหรับ debug/log เท่านั้น"""
    if len(cols) < 2:
        return list(cols), 0
    roofs = [c for c in all_cells if c['kind'] == 'roof']
    roof_spans = _p1b_group_overlapping_roofs(roofs)
    if not roof_spans:
        return list(cols), 0

    cols = sorted(cols, key=lambda c: c['cx'])
    n = len(cols)
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

    n_merges = 0
    for span_x0, span_x1 in roof_spans:
        # หาคอลัมน์ทั้งหมดที่ cx อยู่ในช่วงหลังคาที่ทับซ้อนกันนี้ (ใช้ cx แทน x-range เต็ม เพื่อ
        # ความปลอดภัย - คอลัมน์ที่ cx อยู่ในช่วงชัดเจนคือคอลัมน์ที่หลังคานี้ 'ครอบคลุมจริง' ไม่ใช่
        # แค่ปลายคอลัมน์แตะขอบช่วงพอดีโดยบังเอิญ)
        member_idxs = [i for i, c in enumerate(cols) if span_x0 <= c['cx'] <= span_x1]
        if len(member_idxs) < 2:
            continue
        for i in member_idxs[1:]:
            union(member_idxs[0], i)
        n_merges += 1

    groups = {}
    for i in range(n):
        r = find(i)
        groups.setdefault(r, []).append(i)

    merged = []
    for idxs in groups.values():
        if len(idxs) == 1:
            merged.append(cols[idxs[0]])
            continue
        x0 = min(cols[i]['x'] for i in idxs)
        y0 = min(cols[i]['y'] for i in idxs)
        x1 = max(cols[i]['x'] + cols[i]['w'] for i in idxs)
        y1 = max(cols[i]['y'] + cols[i]['h'] for i in idxs)
        all_members = []
        for i in idxs:
            all_members.extend(cols[i].get('members', []))
        merged.append(dict(x=x0, y=y0, w=x1 - x0, h=y1 - y0,
                            cx=(x0 + x1) / 2, cy=(y0 + y1) / 2, members=all_members))
    merged.sort(key=lambda c: c['cx'])
    return merged, n_merges


def _p1b_reconcile_with_back(back_cols, front_cols, back_extent=None, front_extent=None,
                              n_dropped_by_new_rules=0, back_all_cells=None):
    """จับคู่ตำแหน่งจริง (สัดส่วนตามแนวยาว) ระหว่าง BACK (ground-truth N ตำแหน่ง) กับ FRONT
    (candidate M ตำแหน่ง) ด้วย Hungarian algorithm

    - M > N: FRONT มี fragment ปลอมเกินมา (เช่น มุมกล้องใกล้สุดแตกเป็นหลาย fragment) -> ตัด
      candidate ที่ไม่ถูกจับคู่ทิ้ง (ของซ้ำใกล้มุมกล้อง) - เว้นแต่พิสูจน์ได้ว่าเป็นกล่องจริงที่ถูก
      บังใน BACK (ดู v25.32 FIX ด้านล่าง)
    - M == N: จับคู่ตรงกันพอดี -> คืนค่าเดิมทั้งหมด
    - M < N (v25.14 FIX Bug#4): FRONT นับได้น้อยกว่า BACK จริง (บั๊กเดิม: เงื่อนไข M<=N คืนค่า
      front_cols เดิมทั้งหมดโดยไม่ทำอะไร ปล่อยให้ FRONT undercount หลุดรอดไปโดยไม่ถูกแก้) ->
      หาตำแหน่ง BACK ที่ไม่มี FRONT ใดจับคู่ด้วย (Hungarian แบบ N>M) แล้ว "augment" ด้วยตำแหน่ง
      สังเคราะห์ (synthetic column, marked synthetic=True) ที่ interpolate มาจากสัดส่วนตำแหน่ง
      จริงของ BACK (แปลงกลับเป็นพิกัด local ของ FRONT ผ่าน front_extent) แทนที่จะปล่อยผ่าน

    v25.28 NEW (สำคัญ - "หักล้างสมมติฐาน M<N=บั๊กเสมอ" ตามที่ผู้ใช้ระบุ): เดิมกรณี M<N ระบบ
    เชื่อว่า BACK ถูกต้องเสมอ (ground-truth) แล้วเติม synthetic column ให้ FRONT จนเท่ากับ N
    ทุกครั้งโดยไม่มีข้อยกเว้น - แต่พบจริงจาก AC02-02 ว่าสมมติฐานนี้ผิดได้ในบางกรณี: หลังจากกฎ
    v25.27 (inner-row roof-anchor + side-sliver filter) กรอง fragment ที่ 'พิสูจน์แล้วจริงด้วย
    หลักฐานทางเรขาคณิต' (ไม่ใช่แค่ heuristic เดา) ว่าเป็นหลังคา/หน้ากล่องซ้ำซ้อนของกล่องที่นับ
    ไปแล้ว FRONT อาจมีจำนวนน้อยกว่า BACK จริงๆ ตามข้อเท็จจริงทางกายภาพ (FRONT=5, BACK=7 ใน
    AC02-02 - ไม่ใช่บั๊ก undercount แต่เป็นเพราะมุมมอง FRONT เห็นกล่องบางกลุ่มรวมกันเป็นก้อน
    เดียวที่ BACK แยกเห็นชัดกว่า)
    FIX: ถ้า n_dropped_by_new_rules (จำนวน fragment ที่ v25.27 กรองออกจริง) >= ส่วนต่างที่
    ขาดไป (N-M) ให้ถือว่าจำนวน M ที่ตรวจพบนี้ 'ได้รับการพิสูจน์แล้ว' ว่าถูกต้อง (ไม่ใช่บั๊ก
    undercount) -> ข้าม synthetic-padding ทั้งหมด คืนค่า front_cols ตามจริง (M) โดยไม่เติมอะไร
    เข้าไป - ถ้า n_dropped_by_new_rules < N-M (พิสูจน์ได้ไม่ครบ) ยังคง fallback ไปใช้
    synthetic-padding เดิมสำหรับส่วนที่พิสูจน์ไม่ได้ (ความปลอดภัยสำหรับไฟล์อื่นที่ยังไม่เจอ
    กรณีนี้ - ไม่ปิดกลไก synthetic-padding ทั้งหมด เพราะมันแก้บั๊ก undercount จริงในไฟล์อื่น
    มาก่อน (v25.14 Bug#4) - ต้องคงไว้เป็น fallback สำหรับกรณีที่ยังพิสูจน์ไม่ได้)

    v25.32 NEW (สำคัญ - "M>N ทางกลับกันของ v25.28" ตามที่ผู้ใช้ระบุ): เดิมกรณี M>N ระบบตัด
    FRONT column ที่ Hungarian จับคู่ไม่ได้ทิ้งเสมอ โดยไม่ตรวจสอบว่าคอลัมน์นั้น "ควรถูกตัดจริง"
    (เป็น fragment ปลอม/ซ้ำ) หรือ "เป็นกล่องจริงที่ถูกบังใน BACK" (เหมือนปรากฏการณ์เดียวกับ
    AC02-02 แต่กลับทิศทาง) - พบจริงจาก EC16: FRONT ตรวจพบ 3 คอลัมน์ (เขียว+ฟ้า ซ้อนกัน / เหลือง
    ใบที่1 / เหลือง ใบที่2) แต่ BACK เห็นแค่ 1 ตำแหน่ง (เขียว+ฟ้า เท่านั้น) เพราะกล่องเหลืองทั้ง 2
    ใบถูกกล่องเขียว+ฟ้าที่สูงกว่าบังสนิทจากมุมกล้อง BACK (ยืนยันด้วย pixel: สีเหลือง (255,255,0)
    ไม่ปรากฏในภาพ BACK เลยแม้แต่พิกเซลเดียว ทั้งที่มีอยู่จริงใน FRONT ชัดเจน) - เดิมระบบตัดทั้ง 2
    คอลัมน์เหลืองทิ้งเพราะ Hungarian จับคู่ได้แค่ 1 ใน 3 (คอลัมน์เขียว+ฟ้าเท่านั้น)
    หลักฐานที่แยกแยะได้ (ยืนยันด้วยข้อมูลจริง): คอลัมน์ FRONT ที่ 'ควรถูกตัด' จริง (ของซ้ำ/
    fragment ปลอมจากมุมกล้อง) จะมีเฉพาะสีที่ปรากฏอยู่แล้วใน BACK เสมอ (เพราะเป็นเศษซ้ำของกล่อง
    เดียวกันที่ BACK ก็เห็นเช่นกัน) ในขณะที่คอลัมน์ที่ 'ถูกบังจริง' จะมีอย่างน้อย 1 สีที่ไม่ปรากฏ
    ใน BACK เลย (เพราะเป็นกล่องที่ BACK มองไม่เห็นเลยจากมุมกล้องนั้น) - ทดสอบกับ EC16 จริง:
    คอลัมน์เขียว+ฟ้า (จับคู่ได้) ไม่มีสีขาดหายจาก BACK เลย / คอลัมน์เหลืองทั้ง 2 (ที่เดิมถูกตัด)
    มีสีเหลืองขาดหายจาก BACK ทั้งคู่ - ตรงกับสมมติฐานนี้ 100%
    FIX: ก่อนตัด candidate ที่ไม่ถูกจับคู่ทิ้ง ตรวจสอบว่ามีสีสมาชิกใดของคอลัมน์นั้น 'ไม่ปรากฏใน
    BACK เลย' (เทียบกับ back_all_cells ทั้งหมด ไม่ใช่แค่ back_cols ที่ผ่านการกรองแล้ว) หรือไม่ -
    ถ้ามี ให้ถือว่าคอลัมน์นี้มีเนื้อหาจริงที่ BACK มองไม่เห็น (ถูกบังจริง) -> เก็บไว้ ไม่ตัดทิ้ง
    ถ้าไม่มี (ทุกสีในคอลัมน์นี้ปรากฏอยู่แล้วใน BACK) -> เชื่อว่าเป็น fragment ปลอม/ซ้ำจริง -> ตัด
    ทิ้งตามพฤติกรรมเดิม (ปลอดภัยสำหรับไฟล์อื่นที่มีกรณี corner-duplicate จริงที่ merge_corner_
    artifact_columns จับไม่หมด) - ถ้าไม่ระบุ back_all_cells (None) จะ fallback ไปพฤติกรรมเดิม
    ทุกประการ (ตัดทิ้งเสมอ) เพื่อความปลอดภัยของโค้ดที่เรียกฟังก์ชันนี้แบบเก่า
    """
    N = len(back_cols)
    M = len(front_cols)
    back_all_colors = (set(c['color'] for c in back_all_cells)
                        if back_all_cells is not None else None)

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
        dropped = []
        for j in range(M):
            if j in matched_idx:
                continue
            cand = front_sorted[j]
            # v25.32 FIX: ตรวจสอบก่อนตัดทิ้ง (ดู docstring เต็มด้านบน) - ถ้ามีหลักฐาน back_all_
            # cells ให้ตรวจสอบว่าคอลัมน์นี้มีสีที่ไม่ปรากฏใน BACK เลยหรือไม่ (= ถูกบังจริง)
            if back_all_colors is not None:
                member_colors = set(m['color'] for m in cand.get('members', []))
                if not member_colors:
                    member_colors = {cand.get('color')} if cand.get('color') else set()
                has_color_absent_from_back = any(c not in back_all_colors for c in member_colors)
                if has_color_absent_from_back:
                    kept.append(cand)
                    continue
            dropped.append(cand)
        kept.sort(key=lambda c: c['cx'])
        return kept, dropped

    # v25.28 NEW: ตรวจสอบก่อนว่าส่วนต่าง (N-M) ถูก 'พิสูจน์แล้ว' ด้วยกฎ v25.27 หรือไม่ - ถ้าใช่
    # ให้เชื่อค่า M ทันที ไม่เติม synthetic column (ดู docstring เต็มด้านบนสำหรับหลักฐาน+เหตุผล)
    deficit = N - M
    if n_dropped_by_new_rules >= deficit:
        return front_sorted, []

    # M < N: เติมตำแหน่งสังเคราะห์จาก BACK ที่ไม่มีคู่ใน FRONT (fallback เดิม - ใช้เมื่อพิสูจน์
    # ไม่ได้ครบว่าส่วนต่างเกิดจากกฎ v25.27 จริง)
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


PHASE1B_HI_SCALE = 4.0  # scale ที่ calibrate threshold ต่างๆ ของ PHASE 1B ไว้ (ดู render_hires_crop)


def _p1b_scale_col(c, factor):
    return dict(c, x=int(round(c['x'] * factor)), y=int(round(c['y'] * factor)),
                w=int(round(c['w'] * factor)), h=int(round(c['h'] * factor)),
                cx=c['cx'] * factor, cy=c['cy'] * factor)


def render_hires_crop(page, origin_box, main_scale, hi_scale=PHASE1B_HI_SCALE):
    """v25.15 FIX (Critical - production HTTP 500): เรนเดอร์เฉพาะ 'สี่เหลี่ยม region' ของ view
    นี้ตรงจาก PDF ที่ hi_scale โดยใช้ fitz clip (ไม่ render ทั้งหน้า) เพื่อให้ได้รายละเอียดขอบ/สี
    ที่แท้จริง (ไม่ใช่ upscale จากภาพ low-res ซึ่งพิสูจน์แล้วว่าใช้ไม่ได้ - รายละเอียดที่เสียไปตอน
    render ที่ scale ต่ำกู้คืนด้วยการ upscale ไม่ได้) สำหรับ PHASE 1B เท่านั้น

    เหตุผลที่ต้องเปลี่ยนจาก v25.14 (ซึ่งแก้ Bug#1/#2 โดยเปลี่ยนทั้ง pipeline หลักให้ render ที่
    scale=4 เต็มหน้า): เมื่อทดสอบใช้งานจริงบน Cloud Function พบ HTTP Error 500 ทุกไฟล์ - สาเหตุ
    คือการ render "ทั้งหน้า" ที่ scale=4 (แทนที่จะเป็น scale=3 เดิม) ทำให้ทุกขั้นตอนในพไลป์ไลน์
    หลัก (mask, floor profile, cargo detection, วาด marker, JPEG encode ฯลฯ) ต้องประมวลผลภาพที่
    มีจำนวน pixel มากขึ้น ~1.78 เท่าพร้อมกันทั้งหมด ทำให้ใช้ memory เกิน limit ของ Cloud Function
    จนโดน kill (out-of-memory) -> HTTP 500

    FIX: pipeline หลักกลับไปใช้ full_img ที่ scale=3 เหมือนเดิม (memory footprint เท่าเดิม) ส่วน
    PHASE 1B render "เฉพาะสี่เหลี่ยม region เล็กๆ ของ view" ตรงจาก PDF ที่ scale=4 ผ่าน fitz
    clip=Rect(...) เท่านั้น (ไม่ render ทั้งหน้า) - ใช้ memory น้อยกว่าการ render ทั้งหน้าที่ scale=4
    มาก (region เล็กกว่าทั้งหน้าหลายเท่า) ในขณะที่ยังคงแก้ Bug#1/#2 ได้ครบถ้วน เพราะ:
      - origin_box ที่ใช้ตัดสี่เหลี่ยมนี้ คือ (safe_x0,safe_y0,safe_x1,safe_y1) ตัวเดียวกันเป๊ะ
        กับที่ get_view_region คำนวณให้ pipeline หลักใช้ (แปลงจาก pixel-space ที่ main_scale เป็น
        point-space ด้วยการหารด้วย main_scale) - ไม่มีการคำนวณ ensure_safe_crop ซ้ำหรือ boundary
        อิสระอีกชุดแบบ v25.13 (Bug#2) และพิกัด x/w ที่ได้จะตรงกับ region หลักเสมอ (Bug#1) เพราะ
        เป็นสี่เหลี่ยมเดียวกัน ต่างกันแค่ความหนาแน่น pixel (แปลงกลับด้วย down_factor คงที่)
    """
    safe_x0, safe_y0, safe_x1, safe_y1 = origin_box
    clip_rect = fitz.Rect(safe_x0 / main_scale, safe_y0 / main_scale,
                          safe_x1 / main_scale, safe_y1 / main_scale)
    mat = fitz.Matrix(hi_scale, hi_scale)
    pix = page.get_pixmap(matrix=mat, clip=clip_rect)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = img[:, :, :3]
    img = np.ascontiguousarray(img)
    down_factor = main_scale / hi_scale
    return img, down_factor


def compute_phase1b_columns(regions, down_factor=1.0):
    """คืนค่า dict {'front': [cols...] หรือ None, 'back': [cols...] หรือ None} ในพิกัด region
    local ของแต่ละ view "ที่ main_scale" (ตรงกับพิกัดที่ process_view_on_image ใช้จริง 100%) -
    รับ region ที่ render มาที่ hi_scale ตรงจาก PDF (ดู render_hires_crop) แล้วแปลงพิกัดผลลัพธ์
    กลับเป็น main_scale ด้วย down_factor ก่อนคืนค่า (v25.15 - ดู docstring render_hires_crop)

    regions: {"front": region_array_hires, "back": region_array_hires}
    down_factor: main_scale / hi_scale ที่ใช้ scale พิกัดคอลัมน์กลับ
    None = ตรวจไม่สำเร็จ (fallback อัตโนมัติไปที่ seam-based เดิมใน process_view_on_image)
    """
    try:
        back_region = regions["back"]
        front_region = regions["front"]

        # v25.33 FIX (สำคัญ - พบระหว่างการ integrate v25.32): เดิมเรียก _p1b_classify_view(
        # back_region) แยกต่างหาก โดยไม่ระบุ area_min (ใช้ auto-calibrate ที่คำนวณจากขนาดภาพ) ซึ่ง
        # ให้ค่า area_min สูงเกินไปมากสำหรับภาพขนาดใหญ่ (hi_scale=4 region) ทำให้ back_all ที่ได้
        # กรอง fragment เกือบทั้งหมดทิ้งจนเหลือแค่ 1 ชิ้น (สีพื้นตู้เท่านั้น ไม่มีสีกล่องเลย) - ทำให้
        # back_all_colors (v25.32) เข้าใจผิดว่าทุกสีกล่อง 'ไม่ปรากฏใน BACK' หมด (เพราะ back_all
        # แทบว่างเปล่า) จนกลายเป็นการ 'เก็บ' fragment ปลอมที่ควรถูกตัดทิ้งไว้ผิดพลาด (regression
        # ที่พบจาก EC01-02: FRONT เพิ่มจาก 6 เป็น 8 คอลัมน์ทั้งที่ backend ไม่ได้เปลี่ยนแปลงอะไร)
        # ROOT CAUSE ที่แท้จริง (มีมาก่อนรอบนี้แล้ว): _p1b_front_faces เรียก _p1b_classify_view
        # ภายในตัวเองด้วย area_min=1200 (ค่าคงที่ ไม่ auto-calibrate) และคืนค่า cells ที่ถูกต้อง
        # อยู่แล้วเป็น return value ที่ 2 - ไม่จำเป็นต้องเรียก _p1b_classify_view แยกอีกรอบเลย
        # FIX: ใช้ cells ที่ _p1b_front_faces คืนมา (area_min=1200 สอดคล้องกัน) แทนการเรียกซ้ำ
        # ด้วย area_min ต่างกัน (ตรงกับแนวทาง v25.30 performance-fix ที่เคยทำไปแล้วในเซสชันก่อน)
        back_fronts, back_all, back_n_dropped = _p1b_front_faces(back_region)
        back_cx_tol = _p1b_compute_adaptive_cx_tol(back_fronts)
        back_cols_pre = _p1b_cluster_columns(back_fronts, cx_tol=back_cx_tol)
        if not back_cols_pre:
            return {"front": None, "back": None}
        back_cols_raw, _ = _p1b_merge_corner_artifact_columns(back_cols_pre, back_all)
        print(f"[P1B] BACK after merge_corner: {len(back_cols_raw)} cols, "
              f"cx={[round(c['cx'],1) for c in back_cols_raw]}")
        back_cols, dropped_back = _p1b_drop_side_wall_contaminated_columns(back_cols_raw, back_all)
        print(f"[P1B] BACK after drop_side_wall: {len(back_cols)} cols "
              f"(dropped {len(dropped_back)}), cx={[round(c['cx'],1) for c in back_cols]}")
        # v25.48 FIX (สำคัญ - พบ regression จริงจาก AA02-01 BACK ที่ผู้ใช้แนบ): v25.46 เคยเพิ่ม
        # 'orphaned-roof detection' ให้ทำงานทั้ง FRONT และ BACK "เพื่อความสมมาตร" - พบว่าเกณฑ์
        # coverage เดิม (same-color เท่านั้น) ทำให้ BACK เกิด false-positive จริงกับ AA02-01:
        # หลังคาสีฟ้า (MAPCA, w=205) ที่จริงๆ ถูกคอลัมน์สีเขียว (DSC1A) ที่มีอยู่แล้ว 2 คอลัมน์
        # ติดกันครอบคลุมพื้นที่เกือบเต็ม (99%) แต่คนละสีจึงไม่ผ่าน same-color check เดิม ถูกเข้าใจ
        # ผิดว่าเป็น orphaned roof -> สร้างคอลัมน์ synthetic แทรกกลาง -> ทำให้ BACK มี 6 คอลัมน์
        # (5 จริง+1 ปลอม) -> Hungarian matching จับคู่ผิดตำแหน่งทั้งกระดาน -> เกิด STEP_DOWN_RISK
        # ปลอม (ตรงกับที่ผู้ใช้ยืนยันด้วยภาพจริงว่าเป็น "เกินมา")
        # FIX ที่ใช้จริง (ดู docstring เต็มที่ _ORPHANED_ROOF_ANY_COLOR_MAX_COVERAGE และในลูป
        # คำนวณ cov_any ของ _p1b_find_orphaned_roof_columns): เพิ่มเงื่อนไข "any-color union
        # coverage สูงมาก (>=85%)" เป็นอีกเหตุผลหนึ่งที่จะถือว่า "มีตัวแทนอยู่แล้ว" - แยกแยะออกจาก
        # AC04-03 ได้ถูกต้อง (teal orphan coverage แค่ ~60% เท่านั้น ยังคง orphan ตามเดิม ไม่กระทบ
        # การแก้ไขที่ผู้ใช้เคยยืนยันไว้แล้วสำหรับไฟล์นั้น) - จึงยังคงเปิดใช้งาน orphaned-roof
        # detection ทั้ง 2 view ตามเดิม (ไม่ปิดฝั่ง BACK) เพียงแต่เกณฑ์ coverage แม่นยำขึ้น
        back_orphaned = _p1b_find_orphaned_roof_columns(back_cols, back_all)
        if back_orphaned:
            print(f"[P1B] BACK orphaned-roof columns found: {len(back_orphaned)}, "
                  f"cx={[round(c['cx'],1) for c in back_orphaned]}")
            back_cols = sorted(back_cols + back_orphaned, key=lambda c: c['cx'])
        back_extent = _p1b_roof_extent(back_all)
        if not back_cols:
            return {"front": None, "back": None}

        # v25.33 FIX: เหตุผลเดียวกับ BACK ด้านบน - ดู docstring ที่นั่น
        front_fronts, front_all, front_n_dropped = _p1b_front_faces(front_region)
        front_cx_tol = _p1b_compute_adaptive_cx_tol(front_fronts)
        front_cols_pre = _p1b_cluster_columns(front_fronts, cx_tol=front_cx_tol)
        if not front_cols_pre:
            return {"front": None, "back": None}
        front_cols_raw, _ = _p1b_merge_corner_artifact_columns(front_cols_pre, front_all)
        print(f"[P1B] FRONT after merge_corner: {len(front_cols_raw)} cols, "
              f"cx={[round(c['cx'],1) for c in front_cols_raw]}, "
              f"n_dropped_by_new_rules={front_n_dropped}")
        # v25.35 NEW: รวมคอลัมน์ที่ตกอยู่ในช่วง 'หลังคาซ้อนทับกันจริง' (>=2 roof คนละสี ทับซ้อน
        # x-range) ให้เหลือ 1 คอลัมน์เดียว - ตามกฎที่ผู้ใช้สอน (ยืนยันด้วยภาพจริง EC16) ดู
        # docstring เต็มที่ _p1b_merge_columns_by_overlapping_roofs
        front_cols_raw, n_roof_merges = _p1b_merge_columns_by_overlapping_roofs(
            front_cols_raw, front_all)
        print(f"[P1B] FRONT after roof-overlap merge: {len(front_cols_raw)} cols, "
              f"cx={[round(c['cx'],1) for c in front_cols_raw]}, "
              f"n_roof_merges={n_roof_merges}")
        # v25.46 NEW: เพิ่มคอลัมน์ synthetic จาก 'หลังคาที่ไม่มี front-face รองรับ' (orphaned
        # roof) ก่อนเข้าสู่ reconcile_with_back - ให้ synthetic column ถูกนำไปจับคู่กับ BACK
        # ตามกระบวนการปกติ (ดู docstring เต็มที่ _p1b_find_orphaned_roof_columns)
        front_orphaned = _p1b_find_orphaned_roof_columns(front_cols_raw, front_all)
        if front_orphaned:
            print(f"[P1B] FRONT orphaned-roof columns found: {len(front_orphaned)}, "
                  f"cx={[round(c['cx'],1) for c in front_orphaned]}")
            front_cols_raw = sorted(front_cols_raw + front_orphaned, key=lambda c: c['cx'])
        front_extent = _p1b_roof_extent(front_all)

        front_cols, _ = _p1b_reconcile_with_back(
            back_cols, front_cols_raw, back_extent=back_extent, front_extent=front_extent,
            n_dropped_by_new_rules=front_n_dropped, back_all_cells=back_all)
        if not front_cols:
            return {"front": None, "back": None}
        print(f"[P1B] FRONT after reconcile: {len(front_cols)} cols, "
              f"cx={[round(c['cx'],1) for c in front_cols]}")

        return {
            "front": [_p1b_scale_col(c, down_factor) for c in front_cols],
            "back": [_p1b_scale_col(c, down_factor) for c in back_cols],
        }
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


def measure_cargo_extent_via_white_bg(region, cargo_bottom_y, grounded, sample_offset=3,
                                       refine_margin=15, override_xrange=None):
    """v25.16 FIX (Critical): เดิมคำนวณ rough_min/rough_max จาก 'grounded' mask เพียงอย่างเดียว
    (floor-profile ที่ต้องผ่าน gap_thresh) - พบจริงจาก AC03-06 FRONT (ไฟล์โหลดไม่เต็มคัน) ว่า
    grounded แคบผิดปกติมาก (92px) ขณะที่คอลัมน์จริงจาก PHASE 1B กว้างกว่ามาก (~550px) ทำให้
    start_x/end_x (ขอบเขตซ้าย-ขวาของกองสินค้าทั้งหมด) แคบตามไปด้วย ทำให้ boundary ของตั้งแรก/
    ตั้งสุดท้าย (Phase 2/3) ผิดพลาดรุนแรง แม้ seam ระหว่างกลางจะถูกต้องแล้วก็ตาม (ดู
    process_view_on_image ที่แก้ x_min_/x_max_ ด้วย union แบบเดียวกัน)

    FIX: รับ override_xrange (จาก r["xrange"] ที่ union กับ column extent จาก PHASE 1B แล้ว)
    เป็น hint เพิ่มเติม - ใช้ union ระหว่าง grounded extent กับ override_xrange เป็นจุดเริ่มต้น
    ของการ refine (แทนที่จะใช้ grounded อย่างเดียว) เพื่อไม่ให้ start_x/end_x แคบกว่าที่ควรเป็น
    """
    xs_grounded = np.nonzero(grounded)[0]
    if len(xs_grounded) == 0:
        if override_xrange is not None:
            rough_min, rough_max = override_xrange
        else:
            return None, None, 0
    else:
        rough_min, rough_max = int(xs_grounded.min()), int(xs_grounded.max())
        if override_xrange is not None:
            rough_min = min(rough_min, override_xrange[0])
            rough_max = max(rough_max, override_xrange[1])
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
    boundaries = [start_x] + sorted(seams) + [end_x]
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
    # v25.16 FIX: ส่ง r["xrange"] (union กับ column extent จาก PHASE 1B แล้ว - ดู
    # process_view_on_image) เป็น override hint ให้ measure_cargo_extent_via_white_bg ด้วย กัน
    # ไม่ให้ start_x/end_x แคบกว่าที่ควรเป็นเมื่อ grounded mask ไม่น่าเชื่อถือ (ดู docstring)
    start_x, end_x, length_px = measure_cargo_extent_via_white_bg(
        r["region"], r["cargo_bottom_y"], r["grounded"], override_xrange=r.get("xrange"))
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
    global linear fit เพื่อรักษารูปทรง apex ที่แท้จริงของพื้นตู้ไว้

    v25.16 FIX (Critical): เดิม interpolate ค่าเฉพาะภายในช่วง [valid_idx.min(),valid_idx.max()]
    (ขอบเขตของ 'grounded' mask เท่านั้น) - นอกช่วงนี้ปล่อยเป็น -1 (invalid) ทั้งหมด พบจริงจาก
    AC03-06 FRONT (ไฟล์โหลดไม่เต็มคัน) ว่า grounded แคบผิดปกติมาก (~92px) เทียบกับความกว้างจริง
    ของกองสินค้าทั้งหมด (~550px) ทำให้ height lookup (_floor_at ใน compute_stack_heights_px)
    คืนค่า None สำหรับตั้งส่วนใหญ่ที่อยู่นอกช่วงแคบนี้ (ไม่ใช่แค่ตั้งเดียว) แม้ cross-view
    reconciliation จะช่วยเติมได้บางส่วน แต่บางตั้งไม่มี match ที่ผ่าน overlap threshold ทำให้
    height_px เหลือ None ถาวร -> risk_abs_box คำนวณกรอบ marker ไม่ได้/ผิดตำแหน่ง

    FIX: extrapolate ด้วยค่าขอบ (edge-hold) ให้ครอบคลุมทั้ง array แทนที่จะปล่อย -1 นอกช่วง -
    เป็นการประมาณค่าที่สมเหตุสมผลทางฟิสิกส์ (พื้นตู้นอกช่วงที่วัดได้ตรงมักใกล้เคียงกับค่าที่ขอบ
    ของช่วงที่วัดได้จริง มากกว่าไม่มีค่าเลย) ไม่กระทบกับกรณีปกติที่ grounded ครอบคลุมกว้างอยู่แล้ว
    (extrapolation แค่เติมส่วนขอบแคบๆ ที่เหลือ ไม่เปลี่ยนค่าที่ interpolate ไว้แล้วเลย)
    """
    w = len(floor_y)
    clean = np.full(w, -1, dtype=float)
    xs_g = np.nonzero(grounded)[0]
    if len(xs_g) < 3:
        # v25.34 FIX (สำคัญ - พบจริงจาก EC16): เดิมถ้า 'grounded' มีจุดน้อยกว่า 3 จุด (รวมถึงกรณี
        # 'grounded' ว่างเปล่าทั้งหมด = 0 จุด) จะคืนค่า -1 (invalid) ทั้ง array ทันที ทำให้
        # local_floor_y ใช้ไม่ได้เลยแม้แต่จุดเดียว - พบจริงจาก EC16 (ไฟล์บรรทุกเบาบางมาก,
        # Unused Floor 236.2in, cargo cube 5.7%): grounded=0 จุดทั้งภาพ เพราะ compute_floor_
        # profile's gap_thresh=30 เข้มเกินไปสำหรับพื้นตู้ที่โล่งมาก (gap วัดได้จริงสูงถึง 99px
        # ในหลายคอลัมน์ เพราะกล่องเบาบาง ไม่ชิดพื้นสนิทในมุมมอง isometric) ทำให้ height_px
        # คำนวณตรงไม่ได้เลยสักตั้ง (n_samples=0 ทุกตั้ง) ต้องพึ่ง cross_view_filled ทั้งหมด ซึ่ง
        # ทำให้ทุกตั้งได้ค่าความสูงเท่ากันหมด (copy จากตำแหน่งเดียวใน BACK) -> STEP_DOWN_RISK
        # (pairwise) ตรวจไม่พบเพราะดูเหมือนสูงเท่ากันหมด ทั้งที่ภาพจริงมีกล่องสูงต่ำต่างกันชัดเจน
        # ROOT CAUSE ที่แท้จริง: floor_y (ค่าดิบ, ไม่ผ่านเกณฑ์ gap_thresh) ยังคงคำนวณได้ถูกต้อง
        # อยู่แล้วในหลายคอลัมน์ (ยืนยันจาก EC16: floor_y มีค่า valid ตลอดช่วง x=568-1235) เพียง
        # แต่ไม่ผ่านเกณฑ์ 'grounded' (gap<=30) เท่านั้น - ค่า floor_y ดิบนี้ยังคงเป็นตำแหน่งพื้นที่
        # สมเหตุสมผลทางเรขาคณิต (มาจากการหาสี CONTAINER_RAIL_COLOR/struct_mask ใต้กล่องจริง)
        # FIX: ถ้า grounded ใช้ไม่ได้เลย (< 3 จุด) แต่ floor_y (ดิบ) มีจุด valid เพียงพอ (>= 3
        # จุด) ให้ fallback มาใช้ floor_y ดิบแทน grounded ในการคำนวณ local_floor_y (rolling
        # median + extrapolate เหมือนเดิมทุกประการ) - เป็น fallback ชั้นที่ 2 เท่านั้น (ทำงาน
        # เฉพาะเมื่อ grounded ใช้ไม่ได้จริงๆ) ไม่กระทบไฟล์ปกติที่ grounded ใช้งานได้อยู่แล้วเลย
        xs_raw = np.nonzero(floor_y >= 0)[0]
        if len(xs_raw) < 3:
            return clean
        xs_g = xs_raw
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
        clean[:valid_idx.min()] = clean[valid_idx.min()]
        clean[valid_idx.max() + 1:] = clean[valid_idx.max()]
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


def detect_isometric_apex(cargo_top_y, local_floor_y, start_x, end_x, search_margin_ratio=0.15,
                           smooth_window=11, slope_thresh=0.15):
    """หาตำแหน่ง 'จุดยอด (apex)' ของ silhouette กองกล่องในมุมมอง isometric - ก่อนจุดยอด
    cargo_top_y คือขอบบน-หลัง (ขนานพื้น, height ถูกต้อง) หลังจุดยอดกลายเป็นขอบบน-หน้า (เอียง
    คนละทิศ, height ผิดเพี้ยนเป็นระบบ) ยืนยันด้วยภาพจริงและ cross-view ในไฟล์ทดสอบ

    v25.21 FIX (Critical - "Apex Hijack by Elevated Stack"):
    เดิมใช้ argmin(cargo_top_y) ซึ่งเลือกจุด y ต่ำสุด (= กล่องสูงสุดในภาพ) เป็น apex
    -> กล่องที่ซ้อนสูงผิดปกติ (เช่น สีแดงชั้น 3 ใน AE02-01/02) ถูกเลือกเป็น apex แทน
    -> eff_b1 = min(b1, apex_x) ทำให้ stack ทั้งหมดที่อยู่ทางขวาของกล่องนั้น
       ถูกตัด xs_top=[] -> height_px=None ทั้งหมด -> carry-forward ให้ค่าเท่ากัน
       -> STEP_DOWN_RISK ตรวจไม่พบเลย

    FIX: ใช้ slope-change detection แทน argmin()
    apex จริงของตู้ isometric = จุดที่ slope ของ cargo_top_y เปลี่ยนจาก
    "ลาดลงทางขวา (negative)" เป็น "ลาดขึ้นทางขวา (positive)" ในช่วงยาวพอ (V-shape จริง)
    กล่องสูงผิดปกติสร้าง "dip" สั้นๆ เท่านั้น ไม่ใช่ V-shape ยาว -> ตรวจแยกได้
    ถ้าไม่พบ V-shape -> คืน None (ไม่ตัด data = ปลอดภัยกว่าการตัดผิดพลาด)

    regression-verified: ไฟล์ที่ cargo มีลักษณะ slope คงที่ (ไม่มี V-shape ชัดเจน)
    จะได้ apex=None ไม่ตัด data -> ไม่กระทบผลลัพธ์เดิม
    """
    span = end_x - start_x
    if span <= 0:
        return None
    search_start = start_x + int(span * search_margin_ratio)
    xs = np.arange(search_start, min(end_x + 1, len(cargo_top_y)))
    if len(xs) == 0:
        return None
    vals = cargo_top_y[xs]
    valid_mask = vals >= 0
    if np.sum(valid_mask) < 20:
        return None

    xs_v = xs[valid_mask]
    ys_v = vals[valid_mask].astype(float)

    # smooth ก่อน detect slope-change (ลด noise จากขอบกล่องและ label text)
    half = smooth_window // 2
    smoothed = np.empty(len(ys_v))
    for i in range(len(ys_v)):
        lo, hi = max(0, i - half), min(len(ys_v), i + half + 1)
        smoothed[i] = float(np.median(ys_v[lo:hi]))

    n = len(smoothed)
    if n < 20:
        return None

    # หา V-shape: ต้องมี left slope negative + right slope positive ด้วย window ใหญ่พอ
    # (กล่องสูงผิดปกติสร้าง dip สั้น ~window_size เท่านั้น ไม่ใช่ V ยาวเต็ม half span)
    best_score = -1.0
    best_idx = None
    min_window = max(n // 8, 5)   # ต้องมี slope ยาวพอ (>= 1/8 ของ span) ทั้งสองข้าง

    for mid in range(min_window, n - min_window):
        left_win = min(mid, n // 4)
        right_win = min(n - mid - 1, n // 4)
        if left_win < min_window or right_win < min_window:
            continue
        left_slope = (smoothed[mid] - smoothed[mid - left_win]) / max(left_win, 1)
        right_slope = (smoothed[mid + right_win] - smoothed[mid]) / max(right_win, 1)
        if left_slope < -slope_thresh and right_slope > slope_thresh:
            score = (-left_slope) + right_slope
            if score > best_score:
                best_score = score
                best_idx = mid

    if best_idx is None:
        return None  # ไม่พบ V-shape จริง -> ไม่ตัด data (ปลอดภัยกว่า)
    return int(xs_v[best_idx])


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

        # v25.21 FIX: ถ้า apex-cut ทำให้ xs_top=[] (eff_b1 <= b0 เพราะ apex_x น้อยกว่า b0)
        # -> fallback ใช้ cargo_top_y ทั้ง stack โดยไม่ตัด apex (ยอมรับ noise จาก isometric
        # slope แต่ดีกว่า height=None ที่ทำให้ carry-forward ให้ค่าเท่ากันหมด -> ไม่พบ STEP_DOWN)
        # ตัวอย่างที่ fix: AE02-01 BACK กล่องแดงชั้น 3 อยู่ฝั่งซ้าย -> apex_x เล็ก -> stack
        # ทุกตัวทางขวา xs_top=[] -> height=None -> carry-forward -> ไม่พบ STEP_DOWN
        apex_cut_fallback = False
        if len(xs_top) < 3 and b1 > b0:
            # ใช้ช่วงเต็ม [b0..b1] ไม่ตัด apex (fallback)
            xs_top, ys_top = [], []
            for x in range(max(0, b0), max(0, b1)):
                if x < len(cargo_top_y) and cargo_top_y[x] >= 0:
                    xs_top.append(x)
                    ys_top.append(cargo_top_y[x])
            apex_cut_fallback = True

        top_fit = _robust_local_line_fit(xs_top, ys_top) if xs_top else None

        height_px = None
        n_samples = 0
        height_source = "direct"
        if top_fit is not None and len(xs_top) >= 3:
            eff_mid = (max(0, b0) + (b1 if apex_cut_fallback else eff_b1)) / 2.0
            top_at_mid = top_fit["a"] * eff_mid + top_fit["b"]
            floor_at_mid = _floor_at(int(eff_mid))
            if floor_at_mid is not None:
                height_px = floor_at_mid - top_at_mid
                n_samples = len(top_fit["xs"])
                if apex_cut_fallback:
                    height_source = "apex_fallback"

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


def _detect_hidden_behind_split(cargo_top_y, local_floor_y, x0, x1,
                                 margin=STEP_DOWN_HIDDEN_BEHIND_MARGIN,
                                 min_seg=STEP_DOWN_HIDDEN_BEHIND_MIN_SEG,
                                 jump_thresh_px=STEP_DOWN_HIDDEN_BEHIND_MIN_JUMP_PX,
                                 win=STEP_DOWN_HIDDEN_BEHIND_WIN,
                                 max_side_std=STEP_DOWN_HIDDEN_BEHIND_MAX_SIDE_STD):
    """v25.23 NEW: หาจุด 'seam ที่ซ่อนอยู่กลางคอลัมน์' ซึ่งเกิดจากกล่องแถวหลัง (ข้ามความกว้าง
    ตู้) สูงกว่ากล่องแถวหน้าที่บังอยู่ - สัญญาณคือ top-face bleed-through (หลังคากล่องหลัง
    โผล่พ้นกล่องหน้า) ทำให้ cargo_top_y กระโดดขึ้นกะทันหันกลางคอลัมน์ (คนละสาเหตุกับ seam
    ระหว่างคอลัมน์ปกติที่ Phase 1B ตรวจจับจากรอยต่อสี front-face)

    วิธีตรวจ: หาตำแหน่ง k ที่ median(height ก่อน k) กับ median(height หลัง k) ต่างกันอย่างน้อย
    jump_thresh_px พิกเซล โดยทั้ง 2 ฝั่ง (หน้าต่างกว้าง win พิกเซล) ต้องนิ่งมาก (std <=
    max_side_std) เพื่อแยกแยะจาก noise ของตัวอักษร SKU หรือความชันธรรมชาติของมุมมอง
    isometric (ซึ่งมักมี std สูงกว่านี้มากเพราะเป็นการไล่ระดับต่อเนื่อง ไม่ใช่การกระโดดคมชัด)
    ใช้ median-filter (size=5) ก่อนเพื่อกันจุด outlier เดี่ยวๆจากรู/ขอบตัวอักษรบนกล่อง

    คืนค่า dict(split_x, front_height, hidden_height, jump_px) ถ้าพบ (เฉพาะทิศทาง 'สูงขึ้น'
    เท่านั้น - กล่องซ่อนหลังสูงกว่าฝั่งหน้า ตามหลักฐานจริงที่ยืนยันแล้วทั้ง FRONT/BACK ของ
    AE02-01) หรือ None ถ้าไม่พบรูปแบบที่น่าเชื่อถือ"""
    xs, vals = [], []
    for x in range(x0 + margin, x1 - margin):
        if x < 0 or x >= len(cargo_top_y):
            continue
        t = cargo_top_y[x]
        f = local_floor_y[x] if x < len(local_floor_y) else -1
        if t >= 0 and f >= 0:
            xs.append(x)
            vals.append(f - t)
    n = len(vals)
    if n < min_seg * 2:
        return None
    vals = np.array(vals, dtype=float)
    smoothed = ndimage.median_filter(vals, size=5, mode="nearest")
    for k in range(win, n - win + 1):
        left_win = smoothed[max(0, k - win):k]
        right_win = smoothed[k:k + win]
        if len(left_win) < 3 or len(right_win) < 3:
            continue
        left_std = float(np.std(left_win))
        right_std = float(np.std(right_win))
        left_med = float(np.median(left_win))
        right_med = float(np.median(right_win))
        jump = right_med - left_med
        if jump >= jump_thresh_px and left_std <= max_side_std and right_std <= max_side_std:
            return {
                "split_x": xs[k], "front_height": left_med, "hidden_height": right_med,
                "jump_px": jump, "left_std": left_std, "right_std": right_std,
            }
    return None


def detect_hidden_behind_columns(view_result):
    """v25.23 NEW: สแกนทุกคอลัมน์ (ตั้ง) ของ view นี้หาจุด 'hidden_behind split' - คืนค่า
    dict {stack_idx: {split_x, front_height, hidden_height, jump_px}} เฉพาะคอลัมน์ที่พบ
    รูปแบบที่ผ่านเกณฑ์ทางสถิติเท่านั้น (ดู _detect_hidden_behind_split)"""
    cargo_top_y = view_result["cargo_top_y"]
    local_floor_y = view_result["local_floor_y"]
    seams = view_result["seams"]
    start_x, end_x = view_result["start_x"], view_result["end_x"]
    boundaries = [start_x] + sorted(seams) + [end_x]
    found = {}
    for i in range(len(boundaries) - 1):
        x0, x1 = boundaries[i], boundaries[i + 1]
        r = _detect_hidden_behind_split(cargo_top_y, local_floor_y, x0, x1)
        if r is not None:
            r["x1"] = x1
            found[i] = r
    return found


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
    view_result = {**r, "cargo_top_y": cargo_top_y, "local_floor_y": local_floor_y,
                   "stack_heights": stack_heights}
    # v25.23 NEW: สแกนหา 'hidden_behind' หลังมี cargo_top_y/local_floor_y ครบแล้ว
    view_result["hidden_behind"] = detect_hidden_behind_columns(view_result)
    return view_result


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
            # v25.48 NEW: จำนวนจุดข้อมูลจริงที่ใช้ fit เส้นความสูง (n_samples) - เก็บไว้ใช้เป็น
            # สัญญาณความน่าเชื่อถือของค่า height_px นี้ (ดู STEP_DOWN_MIN_RELIABLE_SAMPLES)
            "n_samples": h.get("n_samples", 0),
            # True เฉพาะ idx==0 ที่ตรวจพบว่าเป็น corner artifact จริง (ตรวจจากเส้น rail
            # ทางเรขาคณิต ไม่ใช่ hardcode ชื่อ view - ดู process_view_on_image)
            "is_corner_duplicate": (i == 0 and is_corner_dup),
        })
    return records


STEP_DOWN_FLOOR_JUMP_MIN_PX = 15


def _p1b_compute_floor_jump(local_floor_y, x0a, x1a, x1b, exclude=8):
    seam = x1a
    left_xs = [x for x in range(max(0, x0a), seam - exclude)
               if 0 <= x < len(local_floor_y) and local_floor_y[x] >= 0]
    right_xs = [x for x in range(seam + exclude, x1b)
                if 0 <= x < len(local_floor_y) and local_floor_y[x] >= 0]
    if len(left_xs) < 5 or len(right_xs) < 5:
        return None
    lx = np.array(left_xs, dtype=float)
    ly = np.array([local_floor_y[x] for x in left_xs], dtype=float)
    rx = np.array(right_xs, dtype=float)
    ry = np.array([local_floor_y[x] for x in right_xs], dtype=float)
    coef_l = np.polyfit(lx, ly, 1)
    coef_r = np.polyfit(rx, ry, 1)
    floor_l_at_seam = np.polyval(coef_l, seam)
    floor_r_at_seam = np.polyval(coef_r, seam)
    return float(floor_r_at_seam - floor_l_at_seam)


def detect_step_down_pairwise(records, view_label, view_result=None):
    """เปรียบเทียบตั้งข้างเคียงในview เดียวกัน - ข้าม record ที่ is_corner_duplicate=True
    (ตรวจจากเส้น rail ทางเรขาคณิตจริง ไม่ hardcode ชื่อ view)"""
    risks = []
    local_floor_y = view_result.get("local_floor_y") if view_result else None
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
        if (shorter_rec.get("height_source") == "direct"
                and shorter_rec.get("n_samples", 999) < STEP_DOWN_MIN_RELIABLE_SAMPLES):
            continue
        if (shorter_rec.get("height_source") == "cross_view_corrected"
                and shorter_rec.get("cross_view_conflict_ratio", 0.0)
                > STEP_DOWN_MAX_CORRECTION_CONFLICT_RATIO):
            continue
        threshold = taller_h * (1 - STEP_DOWN_PAIRWISE_DROP_RATIO)
        floor_jump = None
        if shorter_h < threshold:
            drop_ratio = 1 - (shorter_h / taller_h) if taller_h > 0 else 0
            risks.append({
                "risk_type": "STEP_DOWN_RISK", "subtype": "pairwise", "view": view_label,
                "mark_view": view_label,
                "mark_stack_idx": taller_rec["idx"], "mark_x_range": taller_rec["x_range"],
                "taller_height_px": taller_h, "shorter_height_px": shorter_h,
                "drop_ratio": drop_ratio, "pair_indices": (a["idx"], b["idx"]),
            })
        elif local_floor_y is not None:
            drop_ratio_check = 1 - (shorter_h / taller_h) if taller_h > 0 else 0
            if drop_ratio_check >= 0.125:
                x0a, x1a = a["x_range"]
                x0b, x1b = b["x_range"]
                if x1a <= x0b:
                    floor_jump = _p1b_compute_floor_jump(local_floor_y, x0a, x1a, x1b)
                elif x1b <= x0a:
                    floor_jump = _p1b_compute_floor_jump(local_floor_y, x0b, x1b, x1a)
                if floor_jump is not None and floor_jump >= STEP_DOWN_FLOOR_JUMP_MIN_PX:
                    risks.append({
                        "risk_type": "STEP_DOWN_RISK", "subtype": "pairwise_floor_jump",
                        "view": view_label, "mark_view": view_label,
                        "mark_stack_idx": shorter_rec["idx"], "mark_x_range": shorter_rec["x_range"],
                        "taller_height_px": taller_h, "shorter_height_px": shorter_h,
                        "drop_ratio": drop_ratio_check, "pair_indices": (a["idx"], b["idx"]),
                        "floor_jump_px": floor_jump,
                    })
    return risks


def detect_step_down_hidden_behind(view_result, records, view_label):
    """v25.23 NEW: STEP_DOWN_RISK (hidden_behind) - ตรวจกล่องแถวหลัง (ข้ามความกว้างตู้) ที่
    ซ่อนอยู่หลังกล่องแถวหน้าในคอลัมน์เดียวกัน แต่สูงกว่าจนหลังคาโผล่พ้นขึ้นมา (top-face
    bleed-through) - คนละกลไกจาก pairwise/cross_view เดิม (ซึ่งเทียบระหว่างคอลัมน์ ไม่ใช่
    ภายในคอลัมน์เดียวกัน) ใช้ _detect_hidden_behind_split เป็นตัวตรวจจับ (ดู docstring
    ที่นั่นสำหรับหลักฐาน+เกณฑ์เต็ม) ข้ามคอลัมน์ที่เป็น is_corner_duplicate=True เสมอ (เข้ากับ
    กฎเดิมทั้ง 3 ข้อ - ไม่ flag บริเวณมุมกล้องที่รู้อยู่แล้วว่านับซ้ำ)

    วาด marker เฉพาะ 'โซนที่กล่องซ่อนหลังโผล่ให้เห็น' (จาก split_x ถึงขอบคอลัมน์) ไม่ใช่ทั้ง
    คอลัมน์ เพื่อความแม่นยำของตำแหน่งกรอบ (คำนวณ abs_box ตรงที่นี่เลย แทนการพึ่ง
    risk_abs_box+stack_heights เดิม เพราะ 'ตั้ง' นี้ไม่ได้มี index ของตัวเองใน stack_heights)"""
    risks = []
    hidden_behind = view_result.get("hidden_behind", {})
    ox, oy = view_result["crop_origin_x"], view_result["crop_origin_y"]
    local_floor_y = view_result["local_floor_y"]
    for idx, info in hidden_behind.items():
        if idx >= len(records):
            continue
        parent = records[idx]
        if parent.get("is_corner_duplicate"):
            continue
        split_x, x1 = info["split_x"], info["x1"]
        hidden_h = info["hidden_height"]
        xm = (split_x + x1) // 2
        floor_y_local = local_floor_y[xm] if 0 <= xm < len(local_floor_y) and local_floor_y[xm] >= 0 else None
        if floor_y_local is None:
            continue
        top_y_local = floor_y_local - hidden_h
        abs_box = (ox + split_x, oy + top_y_local, ox + x1, oy + floor_y_local)
        risks.append({
            "risk_type": "STEP_DOWN_RISK", "subtype": "hidden_behind", "view": view_label,
            "mark_view": view_label, "mark_stack_idx": idx, "mark_x_range": (split_x, x1),
            "taller_height_px": hidden_h, "shorter_height_px": info["front_height"],
            "drop_ratio": 1 - (info["front_height"] / hidden_h) if hidden_h > 0 else 0,
            "jump_px": info["jump_px"], "abs_box": abs_box,
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
  
def detect_tail_stepdown(records, view_label):
    """ตรวจ step-down โซนท้ายตู้ (pos > TAIL_STEPDOWN_REAR_POS_MIN)

    v25.54 FIX: เพิ่ม 2 guards ป้องกัน false-positive จากตู้เต็ม (EA07-01):

    Guard 1 — min col width: tail_rec ต้องมีความกว้าง (x_range) >= TAIL_STEPDOWN_MIN_COL_WIDTH px
    เพราะ col ที่แคบผิดปกติ (เช่น 57px ใน EA07-01 FRONT idx=0) มักเกิดจาก column boundary
    ที่ phase1b ตัดผิด หรือ orphaned col ที่แทรกเข้ามา ค่าความสูงจึงไม่น่าเชื่อถือ
    ยืนยัน: col ปกติในไฟล์ทดสอบกว้าง 80-130px, col ที่ผิดปกติ EA07-01 กว้าง 57px

    Guard 2 — height source: ถ้า tail_rec มาจาก cross_view_corrected ให้ต้องการ
    drop_ratio >= TAIL_STEPDOWN_DROP_RATIO_STRICT (เข้มกว่าปกติ) เพราะค่า cross_view_corrected
    มีความไม่แน่นอนสูงกว่า direct measurement
    ยืนยัน: EA07-01 BACK idx=6 เป็น cross_view_corrected, drop_ratio=22% ซึ่งในภาพจริงสูงเท่ากัน
    """
    TAIL_STEPDOWN_MIN_COL_WIDTH = 70      # px ขั้นต่ำของ tail col (ปกติ 80-130px)
    TAIL_STEPDOWN_DROP_RATIO_STRICT = 0.25  # เกณฑ์เข้มสำหรับ cross_view_corrected

    risks = []
    valid = [r for r in records if (not r.get("is_corner_duplicate")
             and r.get("height_px") is not None
             and (r.get("height_px") or 0) > 0)]
    if len(valid) < 2:
        return risks
    valid = sorted(valid, key=lambda r: (r["pos_range"][0] + r["pos_range"][1]) / 2.0)
    tail_rec = max(valid, key=lambda r: r["pos_range"][1])
    if tail_rec["pos_range"][1] < TAIL_STEPDOWN_REAR_POS_MIN:
        return risks
    tail_idx = valid.index(tail_rec)
    if tail_idx == 0:
        return risks

    # v25.54 Guard 1: tail col ต้องกว้างพอ
    x0t, x1t = tail_rec["x_range"]
    if (x1t - x0t) < TAIL_STEPDOWN_MIN_COL_WIDTH:
        return risks

    inner_rec = valid[tail_idx - 1]
    tail_h = float(tail_rec["height_px"])
    inner_h = float(inner_rec["height_px"])
    if inner_h <= 0:
        return risks
    drop_ratio = (inner_h - tail_h) / inner_h
    if drop_ratio < TAIL_STEPDOWN_DROP_RATIO:
        return risks

    # v25.54 Guard 2: cross_view_corrected ต้อง drop_ratio สูงกว่า threshold ปกติ
    if (tail_rec.get("height_source") == "cross_view_corrected"
            and drop_ratio < TAIL_STEPDOWN_DROP_RATIO_STRICT):
        return risks

    risks.append({
        "risk_type": "STEP_DOWN_RISK",
        "subtype": "tail_stepdown",
        "view": view_label,
        "mark_view": view_label,
        "mark_stack_idx": tail_rec["idx"],
        "mark_x_range": tail_rec["x_range"],
        "drop_ratio": float(drop_ratio),
        "tail_height_px": tail_h,
        "inner_height_px": inner_h,
        "tail_idx": tail_rec["idx"],
        "inner_idx": inner_rec["idx"],
    })
    return risks

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
            # v25.48 NEW: เกณฑ์เดียวกับ pairwise - ดู STEP_DOWN_MIN_RELIABLE_SAMPLES
            if (shorter_rec.get("height_source") == "direct"
                    and shorter_rec.get("n_samples", 999) < STEP_DOWN_MIN_RELIABLE_SAMPLES):
                continue
            if (shorter_rec.get("height_source") == "cross_view_corrected"
                    and shorter_rec.get("cross_view_conflict_ratio", 0.0)
                    > STEP_DOWN_MAX_CORRECTION_CONFLICT_RATIO):
                continue
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


# v25.40 NEW (สำคัญ - "Physical Validity Guard" ตามที่ผู้ใช้สอน): เดิม reconcile_heights_
# cross_view (บรรทัด trust_a = h_a >= h_b) เลือก "เชื่อค่าที่สูงกว่าเสมอ" เมื่อทั้ง 2 ฝั่ง
# reliable เท่ากัน (both direct) โดยไม่ตรวจสอบว่าค่าที่เลือกนั้น "เป็นไปได้ทางกายภาพ" หรือไม่
# พบจริงจาก AC05-04 (ไฟล์ที่ผู้ใช้แนบ + สอนเทคนิค "ลากเส้น 2400mm เทียบกับเส้นแต่ละ idx"):
# idx3 (DITHE-AF เขียวสด รวมกับ ATFBA-AJ น้ำเงินที่ cluster ผิดพลาด) ถูก "แก้ไข" ให้มีความสูง
# 351.3px ทั้งที่ความสูงตู้จริง ณ ตำแหน่งนั้น (วัดจาก roofline fit จริง 308 จุด, resid_std=
# 0.35px) มีแค่ 354.3px - คิดเป็น 99.2% ของความสูงตู้ทั้งหมด (ควรเป็นไปไม่ได้ทางกายภาพ เพราะ
# กล่องสินค้าจริงต้องเตี้ยกว่าเพดานตู้เสมอ ไม่มีทางสูงชนเพดานพอดี)
# เทคนิคตรวจสอบ (ตามที่ผู้ใช้สอน, ยืนยันด้วยข้อมูลจริง 2 ไฟล์ AB01-02 และ AC05-04):
# "ลากเส้นจากพื้นตู้ (local_floor_y) ขึ้นไปถึงเพดานตู้ (roofline) ที่ตำแหน่ง x เดียวกับกล่อง
# แต่ละ idx - ต้องไม่มีเส้นความสูงกล่องใด ยาวเท่ากับเส้นเพดานตู้เต็มความสูง" - วัด baseline
# จาก AB01-02 (ไฟล์ปกติ ไม่มีปัญหา) ได้ค่าสูงสุด 97.0% เป็นค่าที่ "ปกติที่สุดที่เคยพบ" จึงตั้ง
# threshold ที่ 97% (สูงกว่านี้ถือว่าผิดปกติ/ไม่น่าเชื่อถือทางกายภาพ)
# FIX: ก่อนยอมรับค่าที่ "แก้ไขข้าม view" (ทั้ง cross_view_filled และ cross_view_corrected)
# ตรวจสอบว่าค่าที่จะใช้ทำให้สัดส่วน (height / local_container_height ที่ตำแหน่ง x ของ record
# นั้น) เกิน PHYSICAL_VALIDITY_MAX_RATIO หรือไม่ - ถ้าเกิน ให้ปฏิเสธการแก้ไขนั้น (คงค่าเดิม
# ของ rec_a ไว้แทน ถ้ามี, หรือข้ามการเติมค่านั้นไปเลยถ้าเป็น PASS1/fill) เพื่อความปลอดภัย
# ไม่กระทบไฟล์อื่น: การตรวจสอบนี้ทำงาน "เสริม" (additional guard) ไม่ได้แทนที่ logic เดิม -
# ถ้า local roofline หาไม่ได้ (เช่น region ไม่มีสีผนังตู้ที่ชัดเจนพอ) จะข้ามการตรวจสอบไปเลย
# (fail-safe: ใช้ logic เดิมทั้งหมดเหมือนก่อน v25.40)
PHYSICAL_VALIDITY_MAX_RATIO = 0.97
_ROOFLINE_WALL_COLOR = (179, 179, 90)  # สีแผงผนังตู้ (wall panel) - ใช้ fit roofline
_ROOFLINE_WALL_COLOR_TOL = 15
_ROOFLINE_MIN_RUN_PX = 15  # ต้องมีแนวตั้งต่อเนื่องอย่างน้อยเท่านี้ จึงนับเป็นจุด roofline
# ที่เชื่อถือได้ (กันจุดเล็กๆ ที่เป็นเงา/ขอบกล่องบังเอิญมีสีใกล้เคียงผนังตู้)
_ROOFLINE_MIN_POINTS = 5  # ต้องมีจุดที่เชื่อถือได้อย่างน้อยเท่านี้ จึง fit เส้นได้


# v25.42 NEW (สำคัญ - พบจริงจาก EB74-ALL ที่ผู้ใช้ถามว่าทำไม v25.40 แก้ไขเฉพาะ AC05-04): เดิม
# _compute_local_roofline_fit ใช้สีผนังตู้แบบ "ตายตัว" (179,179,90) เพียงสีเดียว - พบว่าไฟล์
# EB74-ALL ใช้สีผนังตู้เป็น (90,179,179) แบบเดียวกับที่ v25.41 เพิ่งแก้ไปสำหรับ
# _p1b_is_structural_container_color (โทนฟ้า/เขียวอมฟ้า G≈B แทน R≈G) - เมื่อ roofline_fit หา
# สีตายตัวเดิมไม่เจอเลย (คืนค่า None) Physical Validity Guard จะ "fail-safe" ปิดตัวเองไปทั้งหมด
# ไม่ตรวจสอบอะไรเลย ทำให้ logic เดิม (trust_a = h_a >= h_b) ทำงานตามปกติ และค่าที่ผิดพลาดจาก
# ปัญหาคนละชั้น (Phase 1B ตัดคอลัมน์ผิดพลาด ทำให้จับคู่ตำแหน่งข้าม view ผิด) จึงหลุดรอดไปโดย
# ไม่ถูกปฏิเสธ (เพราะ Guard ไม่ได้ทำงานเลยตั้งแต่ต้น ไม่ใช่เพราะ Guard ตรวจแล้วผ่าน)
#
# ความพยายามแก้ไขครั้งแรก (ใช้ _p1b_is_structural_container_color เต็ม pattern) พบ regression
# ใหม่ที่ AB01-02: การรวมทุกสีโครงสร้างตู้ (rail/wall-panel/floor-tile/rear-wall) เข้าด้วยกัน
# ทำให้จุดที่ใช้ fit เส้น roofline ปนกันจาก 2 พื้นผิวที่มีมุมเอียงต่างกันจริง (ผนังด้านข้าง vs
# ผนังหลัง/หลังคา ซึ่งเป็นคนละระนาบในภาพ isometric ไม่ใช่เส้นเดียวกัน) แม้ใช้ robust line fit
# (MAD-based rejection) ก็ยังแก้ไม่ได้ เพราะทั้ง 2 กลุ่มมีจำนวนจุดใกล้เคียงกัน (ไม่ใช่ outlier
# ส่วนน้อย) ทำให้ resid_std พุ่งสูงถึง 36.2px (เทียบ AC05-04 เดิมที่ 0.35px) เส้นที่ fit ได้จึง
# เอียงผิดจากผนังด้านข้างจริงไปมาก ทำให้ ratio ของกล่องสูงสุดขยับข้าม threshold 97% ไปเอง (จาก
# 96.9% ที่เคยผ่าน กลายเป็น 99.3% ที่ถูกปฏิเสธผิดพลาด) เกิด chain-reaction กระทบคอลัมน์อื่น
# FIX ที่ถูกต้อง: จำกัดเฉพาะสี "wall panel" (ผนังด้านข้างเท่านั้น - พื้นผิวเดียวที่ต้องการวัด
# ความสูงเพดานจริง) ไม่ใช้สีอื่นทั้งหมด (rail/floor-tile/rear-wall เป็นคนละพื้นผิว/มุมเอียง) -
# ระบุด้วยช่วง R-B แคบรอบค่า 89 (wall panel วัดได้จริง) ทั้ง 2 ทิศทาง (R≈G และ G≈B) แทนช่วงกว้าง
# 75-125 เดิมที่ออกแบบมาสำหรับ "กรองไม่ใช่กล่องสินค้า" (กว้างเกินไปสำหรับงาน roofline ที่ต้องการ
# ความแม่นยำสูงเฉพาะพื้นผิวเดียว)
_ROOFLINE_RB_TARGET = 89   # ค่า R-B ของสี wall-panel จริง (179,179,90 หรือ 90,179,179)
_ROOFLINE_RB_TOL = 15      # tolerance แคบ (74-104) แยกจาก rail(102)/floor(122)/rear-wall(80)
# ได้เพียงพอ (rear-wall ที่ 80 อาจยังเหลื่อมบ้าง แต่ปริมาณจุดของ rear-wall ในภาพจริงน้อยกว่า
# wall-panel มาก เพราะมองเห็นได้แคบกว่า - ยืนยันด้วยการทดสอบ regression ครบทุกไฟล์)
# v25.50 NEW (สำคัญ - พบจริงจาก AA02-01 ที่ผู้ใช้แนบ, พอร์ตมาจาก branch v25.48.5): _robust_local_
# line_fit (MAD-based outlier rejection) ออกแบบมาเพื่อกรอง "จุดส่วนน้อยที่เป็น noise" ออกจากจุด
# ส่วนใหญ่ที่ถูกต้อง - แต่พบว่าไฟล์ AA02-01 มี roofline เป็นรูปตัว "V" จริง (เพดานตู้แบบ isometric
# มี apex แล้วลาดลง 2 ทิศทาง เหมือนปัญหาเดียวกับพื้นตู้ที่ compute_local_floor_y เคยแก้ไปแล้ว - แต่
# _compute_local_roofline_fit ยังไม่เคยรองรับกรณีนี้) จุดข้อมูลทั้ง 2 กลุ่ม (ก่อน apex/หลัง apex)
# ต่างก็เป็นจุดที่ถูกต้องจริง ไม่ใช่ minority-noise เลย (พบ 13 จุดฝั่งซ้าย + ~30 จุดฝั่งขวาที่เป็น
# V-shape ชัดเจน) ทำให้ MAD-based rejection ไม่สามารถแยกออกได้ (ไม่มีฝั่งไหนเป็นส่วนน้อย) - fit
# เส้นตรงเส้นเดียวข้าม 2 slope ที่ต่างกันจริงจึงให้ค่า resid_std=8.7px (แย่กว่า AC05-04's 0.35px
# ถึง 25 เท่า) เส้นที่ fit ผิดนี้ทำให้ max_physical_height คำนวณผิดพลาด จนไปปฏิเสธค่าความสูงที่
# ถูกต้องจริง (BACK idx0 วัดได้ 349.89px จาก direct-fit น่าเชื่อถือสูง n=82 จุด แต่ถูก Guard
# ปฏิเสธเพราะ ratio คำนวณผิดเป็น 102.8% เกิน threshold ทั้งที่ container มี unused floor เหลือ
# 51.2 นิ้ว - แสดงว่าไม่น่าเป็นไปได้ที่กล่องจะสูงชนเพดานจริง) ทำให้ระบบไปเชื่อค่า apex_fallback
# ที่ไม่น่าเชื่อถือ (243.49px) แทน กลายเป็นซ่อนความแตกต่างของความสูงที่แท้จริงไว้ (มองด้วยตาจาก
# ภาพจริงยืนยันว่า 2 คอลัมน์ที่ถูกลดค่าลงนี้สูงใกล้เคียงกันจริงตามที่วัดได้ก่อนถูก Guard ปฏิเสธ)
# FIX: เพิ่มเกณฑ์ขั้นต่ำของคุณภาพ fit (resid_std) - ถ้า fit ที่ได้ (แม้จะผ่าน robust rejection
# แล้ว) ยังมี resid_std สูงเกินไป แสดงว่าข้อมูลเป็น multi-modal จริง (V-shape หรือสีปนกันหลาย
# พื้นผิว) ไม่ใช่แค่ noise ส่วนน้อย - เส้นตรงเส้นเดียวไม่เหมาะสมจะใช้แทนค่าจริงได้ -> คืนค่า None
# (fail-safe, ปิด Guard สำหรับตำแหน่ง/ไฟล์นี้ไปเลย ดีกว่าใช้เส้นที่ fit ผิดมาปฏิเสธค่าที่ถูกต้อง)
# เกณฑ์ที่ตั้งไว้ (3.0px) อ้างอิงจากหลักฐาน 2 จุดที่มี: AC05-04 (fit ดีจริง)=0.35px เทียบ AA02-01
# (fit แย่จาก V-shape จริง)=8.7px - ให้ margin สูงกว่าค่าดีจริงมาก (~8 เท่า) แต่ยังต่ำกว่าค่าที่รู้
# ว่าแย่มาก - regression-verified ร่วมกับ RECONCILE_MAX_CONFLICT_TO_APPLY (v25.49 AB03-04 fix)
# ทั้งคู่เป็น guard คนละจุด/คนละฟังก์ชันกัน ไม่ทับซ้อนกัน จึงรวมเข้าด้วยกันได้ปลอดภัย
_ROOFLINE_MAX_RESID_STD = 3.0


def _compute_local_roofline_fit(region, min_run=_ROOFLINE_MIN_RUN_PX,
                                 min_points=_ROOFLINE_MIN_POINTS):
    """v25.40 NEW (แก้ไข v25.42): fit เส้นตรง (slope, intercept) ของ 'roofline' (ขอบบนสุดของ
    ผนังด้านข้างตู้) จากจุดที่มองเห็นสี wall-panel เท่านั้น (ไม่ใช้สีโครงสร้างอื่นที่เป็นคนละ
    พื้นผิว/มุมเอียง เช่น ผนังหลัง/หลังคา/พื้น/ราง - ดู docstring เต็มด้านบนสำหรับเหตุผล) ต่อเนื่อง
    อย่างน้อย min_run พิกเซลในแต่ละคอลัมน์ x ของภาพ - ยืนยันด้วยข้อมูลจริง AC05-04: ได้
    resid_std=0.35px จาก 308 จุด (แม่นยำสูงมาก เพราะ container เป็น isometric ทำให้เพดานตู้เป็น
    เส้นตรงเป๊ะ) คืนค่า (slope, intercept) หรือ None ถ้าหาจุดที่เชื่อถือได้ไม่พอ (fail-safe -
    ผู้เรียกใช้ต้องรับมือกับ None)"""
    r = region[:, :, 0].astype(int)
    g = region[:, :, 1].astype(int)
    b = region[:, :, 2].astype(int)
    rb_min = _ROOFLINE_RB_TARGET - _ROOFLINE_RB_TOL
    rb_max = _ROOFLINE_RB_TARGET + _ROOFLINE_RB_TOL
    # ทิศทางที่ 1: R≈G, R-B อยู่ในช่วงแคบรอบ wall-panel (โทนน้ำตาล/ทอง)
    wall_mask = (np.abs(r - g) <= _STRUCTURAL_HUE_RG_MAX_DIFF) & \
                ((r - b) >= rb_min) & ((r - b) <= rb_max)
    # ทิศทางที่ 2: G≈B, B-R อยู่ในช่วงแคบรอบ wall-panel (โทนฟ้า/เขียวอมฟ้า - v25.41/42)
    wall_mask |= (np.abs(g - b) <= _STRUCTURAL_HUE_RG_MAX_DIFF) & \
                 ((b - r) >= rb_min) & ((b - r) <= rb_max)
    xs_pts, ys_pts = [], []
    for x in range(region.shape[1]):
        col = np.nonzero(wall_mask[:, x])[0]
        if len(col) >= min_run:
            top = col.min()
            # ตรวจสอบว่า min_run พิกเซลแรกต่อเนื่องกันจริง (ไม่ใช่แค่กระจัดกระจายบังเอิญ)
            seg = col[col < top + min_run * 2]
            if len(seg) >= min_run:
                xs_pts.append(x)
                ys_pts.append(top)
    if len(xs_pts) < min_points:
        return None
    # v25.42 FIX (สำคัญ - พบ regression จริงจาก AB01-02 หลังขยาย hue-pattern ให้กว้างขึ้น):
    # เดิมใช้ np.linalg.lstsq ธรรมดา (ไม่ทนทานต่อ outlier) - พบว่าการขยาย _p1b_is_structural_
    # container_color ให้ครอบคลุมหลายเฉดสี (rail/wall-panel/floor-tile/rear-wall ที่อยู่คนละ
    # ตำแหน่ง y ในภาพจริง ไม่ใช่ตำแหน่งเดียวกับ 'roofline' ของผนังด้านข้าง) ทำให้จุดที่ใช้ fit
    # ปนกันหลายกลุ่ม (multi-modal) เกิด noise มาก (resid_std=36.2px ในไฟล์ AB01-02 เทียบกับ
    # AC05-04 ที่ได้แค่ 0.35px) ทำให้เส้น roofline ที่ fit ได้เอียงผิดจากตำแหน่งจริงมาก ส่งผลให้
    # max_physical_height คำนวณผิดพลาด (ratio ของกล่องสูงสุดขยับจาก 96.9% ที่เคยผ่านเกณฑ์ เป็น
    # 99.3% ที่ถูก Guard ปฏิเสธผิดพลาด) เกิด chain-reaction ทำให้ค่าความสูงอื่นในคอลัมน์ใกล้เคียง
    # ถูกแก้ไขผิดตามไปด้วย (regression ที่ค่าความสูงเปลี่ยนไปมาก 189.7->126.8 เป็นต้น)
    # FIX: ใช้ _robust_local_line_fit (มีอยู่แล้วในโค้ด, iterative MAD-based outlier rejection)
    # แทน simple least-squares - กรองจุดที่ไม่ใช่ roofline จริง (จากสีโครงสร้างกลุ่มอื่นที่อยู่
    # คนละตำแหน่ง y) ออกโดยอัตโนมัติ ทำให้ fit เสถียรขึ้นมาก โดยไม่กระทบไฟล์ที่ roofline เดิม
    # สะอาดอยู่แล้ว (เช่น AC05-04 - robust fit บนข้อมูลที่ไม่มี outlier จะให้ผลเหมือน simple fit)
    xs_arr = np.array(xs_pts, dtype=float)
    ys_arr = np.array(ys_pts, dtype=float)
    fit = _robust_local_line_fit(xs_arr, ys_arr)
    if fit is None:
        return None
    # v25.50 NEW: ดู docstring เต็มที่ _ROOFLINE_MAX_RESID_STD ด้านบนสำหรับหลักฐาน+เหตุผล
    # (พบจริงจาก AA02-01 - roofline รูปตัว V ที่ robust rejection แก้ไม่ได้เพราะทั้ง 2 กลุ่ม
    # จุดข้อมูลเป็นของจริงไม่ใช่ minority-noise)
    if fit["resid_std"] > _ROOFLINE_MAX_RESID_STD:
        return None
    return fit["a"], fit["b"]


def _max_physical_height_at_x(roofline_fit, local_floor_y, x):
    """v25.40 NEW: คำนวณ 'ความสูงตู้จริงสูงสุด' ณ ตำแหน่ง x ใดๆ (จาก roofline ถึง local floor)
    คืนค่า None ถ้าคำนวณไม่ได้ (roofline_fit เป็น None หรือ floor_y ที่ตำแหน่งนั้นไม่ valid)"""
    if roofline_fit is None:
        return None
    if x < 0 or x >= len(local_floor_y):
        return None
    fy = local_floor_y[x]
    if fy < 0:
        return None
    slope, intercept = roofline_fit
    roof_y = slope * x + intercept
    h = fy - roof_y
    return h if h > 0 else None


def reconcile_heights_cross_view(records_front, records_back,
                                  min_overlap_ratio=0.5, conflict_ratio=0.10,
                                  front_result=None, back_result=None):
    """เทียบความสูงของกล่องตำแหน่งจริงเดียวกันระหว่าง FRONT<->BACK - ข้าม record ที่
    is_corner_duplicate=True เสมอ PASS1: เติมค่า None จาก cross-view PASS2: แก้ความขัดแย้ง

    v25.40 NEW: รับ front_result/back_result (view_result เต็มจาก process_view_with_height_
    on_image) เพิ่มเติม (optional - ถ้าไม่ส่งมา จะทำงานเหมือนเดิมทุกประการไม่มี guard เลย เพื่อ
    ความปลอดภัยของโค้ดที่เรียกฟังก์ชันนี้แบบเก่า) ใช้คำนวณ 'Physical Validity Guard' - ดู
    docstring เต็มด้านบน PHYSICAL_VALIDITY_MAX_RATIO สำหรับหลักฐาน+เหตุผล (ยืนยันจาก AC05-04
    ตามเทคนิคที่ผู้ใช้สอน: ลากเส้นเทียบความสูงกล่องกับความสูงตู้จริง ต้องไม่มี idx ใดเท่ากับ
    ความสูงเต็มตู้)"""
    roofline_front = (_compute_local_roofline_fit(front_result["region"])
                       if front_result is not None else None)
    roofline_back = (_compute_local_roofline_fit(back_result["region"])
                      if back_result is not None else None)

    def _violates_physical_validity(rec, height_value):
        """True ถ้า height_value ทำให้สัดส่วนเทียบความสูงตู้จริง ณ ตำแหน่ง x กึ่งกลางของ rec
        เกิน PHYSICAL_VALIDITY_MAX_RATIO - คืน False (ไม่ปฏิเสธ) ถ้าคำนวณไม่ได้ (fail-safe)"""
        view_result = front_result if rec["view"] == "FRONT" else back_result
        roofline_fit = roofline_front if rec["view"] == "FRONT" else roofline_back
        if view_result is None or roofline_fit is None:
            return False
        x0, x1 = rec["x_range"]
        xm = (x0 + x1) // 2
        max_h = _max_physical_height_at_x(roofline_fit, view_result["local_floor_y"], xm)
        if max_h is None:
            return False
        return (height_value / max_h) > PHYSICAL_VALIDITY_MAX_RATIO

    def _overlap_ratio(a, b):
        a0, a1 = a; b0, b1 = b
        inter = max(0.0, min(a1, b1) - max(a0, b0))
        smaller = min(max(1e-6, a1 - a0), max(1e-6, b1 - b0))
        return inter / smaller if smaller > 0 else 0.0

    # v25.23 FIX (Critical): rec_b (แหล่งอ้างอิง) ไม่ควรถูกกันออกเพียงเพราะ is_corner_duplicate
    # (flag นี้มีไว้ห้าม "เป็นเป้าหมายที่ถูกวาด marker" เท่านั้น ไม่ได้แปลว่าความสูงที่วัดได้
    # ใช้อ้างอิงไม่ได้ - กล่องมุมเดียวกันที่เห็นจาก 2 กล้องยังเป็นกล่องจริงกล่องเดียวกัน)
    corrections = []
    for rec_a, records_b in [(r, records_back) for r in records_front] + \
                            [(r, records_front) for r in records_back]:
        if rec_a.get("is_corner_duplicate") or rec_a["height_px"] is not None:
            continue
        best_match, best_overlap = None, 0.0
        for rec_b in records_b:
            if rec_b["height_px"] is None:
                continue
            ov = _overlap_ratio(rec_a["pos_range"], rec_b["pos_range"])
            if ov > best_overlap:
                best_overlap, best_match = ov, rec_b
        if best_match is None or best_overlap < min_overlap_ratio:
            continue
        # v25.40 NEW: Physical Validity Guard - ปฏิเสธการเติมค่าถ้าทำให้สูงเกินตู้จริง
        if _violates_physical_validity(rec_a, best_match["height_px"]):
            continue
        rec_a["height_px"] = best_match["height_px"]
        rec_a["height_source"] = "cross_view_filled"
        corrections.append((rec_a["view"], rec_a["idx"], None, best_match["height_px"]))

    # v25.45 NEW (สำคัญ - พบจริงจาก AB01-02 ที่ผู้ใช้ทดสอบ v25.44 แล้วพบว่า teal/purple ยัง
    # ไม่มี risk marker): เดิม PASS2 เขียนทับ height_px ของ record ที่ "แพ้" ทันทีระหว่างวนลูป
    # (sequential mutation) - พบว่าเมื่อ record ฝั่งหนึ่ง (เช่น BACK idx0) มี pos_range กว้างผิด
    # สัดส่วน (เพราะ FRONT span=576px กับ BACK span=462px ต่างกัน ~25% - เกิดจากการที่แต่ละ view
    # ถูก crop/render แยกกันคนละภาพ คนละ pixel-scale โดยธรรมชาติ ไม่ใช่บั๊กจากการคำนวณ extent
    # ที่แก้ไขได้ตรงๆ) จนไปทับซ้อน (overlap>min_overlap_ratio) กับ FRONT record 2 ตัวพร้อมกัน
    # (F5 overlap=0.70, F6 overlap=1.00) - ระบบประมวลผล F5 ก่อน (index น้อยกว่า) แล้ว "ชนะ" แก้ไข
    # BACK idx0 ไปก่อน จากนั้น F6 (ซึ่งควรเป็นคู่ที่แท้จริงกว่ามาก เพราะ overlap=1.00 หมายถึง
    # pos_range ของ F6 อยู่ในขอบเขตของ BACK idx0 เต็มรูปแบบ) กลับมาประมวลผลทีหลัง แล้วได้รับค่าที่
    # BACK idx0 "ปนเปื้อน" จาก F5 ไปแล้ว (292.9) แทนที่จะเห็นค่าดั้งเดิมจริงของ BACK idx0 (335.8)
    # ทำให้ F6 (purple, TPR1A-AO) ถูกตั้งเป็น 292.9 (เท่ากับ F5/teal พอดี) ซ่อน step-down risk ที่
    # แท้จริง (ค่าจริงของ F6 คือ 213.7 apex_fallback ซึ่งต่างจาก F5's 292.9 ถึง 27% - เกิน
    # threshold 20% ควรตรวจพบ STEP_DOWN_RISK แต่กลับไม่พบเพราะถูกปนเปื้อนไปก่อน)
    # ROOT CAUSE ที่แท้จริง: การประมวลผลแบบ "sequential, เขียนทับทันที" ทำให้ผลลัพธ์ขึ้นกับ
    # "ลำดับการประมวลผล" (order-dependent) ซึ่งไม่ควรเป็นเช่นนั้น - record ที่มี overlap สูงกว่า
    # (หลักฐานที่น่าเชื่อถือกว่า) ควรชนะเสมอ ไม่ว่าจะถูกประมวลผลก่อนหรือหลัง
    # ได้ทดสอบ "Method 1" (normalize extent ให้ FRONT/BACK อ้างอิงขอบเขตเดียวกัน) ตามที่ผู้ใช้
    # เสนอก่อนแล้ว พบว่าไม่สามารถแก้ปัญหาได้จริง เพราะ FRONT/BACK เป็นภาพคนละใบที่ crop/render
    # แยกจาก PDF คนละพิกัด คนละ pixel-scale โดยสิ้นเชิง (ยืนยันด้วยข้อมูลจริง: แม้แต่ column-based
    # extent จาก PHASE 1B เอง - cols_x_min/cols_x_max - ก็ยังต่างกันมากกว่าเดิม 28.6% เทียบกับ
    # floor-union extent เดิมที่ต่าง 24.7% - แสดงว่าปัญหาไม่ได้อยู่ที่วิธีคำนวณ extent แต่อยู่ที่
    # ธรรมชาติของการ render 2 ภาพแยกกัน ซึ่งไม่มีทาง "union" พิกัดข้าม coordinate system ได้ตรงๆ)
    # FIX ที่ใช้จริง (ปลอดภัยกว่ามาก เพราะไม่แตะ pos_range ที่ใช้ร่วมกับฟังก์ชันอื่น เช่น
    # detect_step_down_crossview/_rearmost_record/REAR_EMPTY_RISK เลย - ขอบเขตการแก้ไขจำกัดอยู่
    # แค่ภายในฟังก์ชันนี้เท่านั้น): เปลี่ยนจาก "ประมวลผลแล้วเขียนทับทันที" เป็น "snapshot ค่าเดิม
    # ทั้งหมดก่อน (ป้องกันการปนเปื้อนข้ามกันระหว่างการตัดสินใจ) รวบรวมข้อเสนอการแก้ไขทั้งหมดจาก
    # ทุกคู่ที่เข้าเกณฑ์ก่อน แล้วเมื่อมีหลายคู่แข่งกันแก้ไข target เดียวกัน ให้ 'คู่ที่มี overlap
    # ratio สูงสุด' ชนะเสมอ (ไม่ใช่คู่ที่ประมวลผลก่อน) แล้วค่อย apply การแก้ไขทั้งหมดพร้อมกันในตอน
    # ท้าย - ยืนยันด้วยข้อมูลจริงว่าแก้ปัญหา AB01-02 ได้ตรงจุด (F6 ชนะ F5 ในการแก้ไข BACK idx0
    # ตามที่ควรจะเป็น เพราะ overlap 1.00 > 0.70) โดยไม่กระทบ logic เดิมของกรณีอื่นๆ ที่ไม่มีการ
    # แข่งขัน (ผลลัพธ์เหมือนเดิมทุกประการเมื่อมีแค่ 1 คู่ต่อ target)
    snapshot = {}
    for rec_list in (records_front, records_back):
        for r in rec_list:
            snapshot[id(r)] = (r["height_px"], r.get("height_source", "direct"))

    proposals = {}  # id(target) -> (overlap_ratio, target_ref, new_value, correction_tuple)

    for rec_a, records_b in [(r, records_back) for r in records_front] + \
                            [(r, records_front) for r in records_back]:
        if rec_a.get("is_corner_duplicate") or snapshot[id(rec_a)][0] is None:
            continue
        best_match, best_overlap = None, 0.0
        for rec_b in records_b:
            ov = _overlap_ratio(rec_a["pos_range"], rec_b["pos_range"])
            if ov > best_overlap:
                best_overlap, best_match = ov, rec_b
        if best_match is None or best_overlap < min_overlap_ratio or snapshot[id(best_match)][0] is None:
            continue
        h_a, a_src = snapshot[id(rec_a)]
        h_b, b_src = snapshot[id(best_match)]
        higher = max(h_a, h_b)
        if higher <= 0 or abs(h_a - h_b) / higher <= conflict_ratio:
            continue
        a_reliable = a_src in ("direct", "cross_view_filled")
        b_reliable = b_src in ("direct", "cross_view_filled")
        if a_reliable and not b_reliable:
            trust_a = True
        elif b_reliable and not a_reliable:
            trust_a = False
        else:
            trust_a = h_a >= h_b
        # v25.40 NEW: Physical Validity Guard - ก่อนเลือกใช้ค่าใด ตรวจสอบว่าค่านั้นไม่เกิน
        # ความสูงตู้จริง ณ ตำแหน่งของ 'เป้าหมายที่จะถูกเขียนทับ' (ไม่ใช่ตำแหน่งของแหล่งอ้างอิง
        # เพราะ x_range ของทั้งคู่อาจต่างกันเล็กน้อยจากการ reconcile คนละ view) - ถ้าค่าที่เลือก
        # ไว้ (ตาม trust_a) ผิดกฎกายภาพ ให้ลองสลับไปใช้อีกฝั่งแทน (ถ้าฝั่งนั้นผ่านเกณฑ์) หรือ
        # ข้ามการแก้ไขนี้ไปเลยถ้าทั้งคู่ผิดกฎ (ปลอดภัยที่สุด - คงค่าเดิมไว้)
        if trust_a:
            target, value = best_match, h_a
        else:
            target, value = rec_a, h_b
        if _violates_physical_validity(target, value):
            # ค่าที่เลือกไว้ผิดกฎกายภาพ - ลองอีกฝั่ง (ค่าที่ต่ำกว่า มักจะสมเหตุสมผลกว่า)
            alt_target = rec_a if trust_a else best_match
            alt_value = h_b if trust_a else h_a
            if not _violates_physical_validity(alt_target, alt_value):
                target, value = alt_target, alt_value
                trust_a = not trust_a
            else:
                continue  # ทั้ง 2 ค่าผิดกฎกายภาพ - ปลอดภัยที่สุดคือไม่แก้ไขอะไรเลย
        if trust_a:
            correction = (best_match["view"], best_match["idx"], h_b, h_a)
        else:
            correction = (rec_a["view"], rec_a["idx"], h_a, h_b)
        # v25.48 NEW: บันทึกขนาดความขัดแย้งเดิม (ก่อนแก้ไข) ระหว่าง FRONT<->BACK ไว้ - ใช้เป็น
        # สัญญาณความน่าเชื่อถือของค่าที่แก้ไขแล้ว (ดู STEP_DOWN_MAX_CORRECTION_RATIO ด้านล่าง)
        conflict_mag = abs(h_a - h_b) / higher if higher > 0 else 0.0
        key = id(target)
        if key not in proposals or best_overlap > proposals[key][0]:
            proposals[key] = (best_overlap, target, value, correction, conflict_mag)

    for _overlap, target, value, correction, conflict_mag in proposals.values():
        # v25.49 NEW (สำคัญ - พบจริงจาก AB03-04): ถ้าความขัดแย้งเดิม (ก่อนแก้ไข) สูงเกินเพดานนี้
        # ไม่น่าเป็น measurement noise ธรรมดาอีกต่อไป (สูงกว่าทุกเคส noise ที่เคยยืนยันแล้วมาก) -
        # ข้ามการแก้ไขนี้ไปเลย คงค่าเดิมทั้ง 2 ฝั่งไว้ ปล่อยให้ detect_step_down_crossview/pairwise
        # ตรวจจับความแตกต่างทางกายภาพจริงนี้ต่อไปตามปกติ (ดู docstring เต็มที่
        # RECONCILE_MAX_CONFLICT_TO_APPLY ด้านบนสำหรับหลักฐาน+เหตุผล)
        if conflict_mag > RECONCILE_MAX_CONFLICT_TO_APPLY:
            continue
        target["height_px"] = value
        target["height_source"] = "cross_view_corrected"
        # v25.48 NEW: ดู docstring เต็มที่ STEP_DOWN_MAX_CORRECTION_RATIO (ด้านล่าง ใกล้
        # detect_step_down_pairwise) สำหรับหลักฐาน+เหตุผล (พบจริงจาก AA02-01)
        target["cross_view_conflict_ratio"] = conflict_mag
        corrections.append(correction)
    return corrections


def _rearmost_record(records):
    """ตั้งที่อยู่ท้ายสุดจริง (real pos_range[1] ใกล้ 1.0 ที่สุด) ของ view นั้น - ข้าม
    record ที่ is_corner_duplicate=True เสมอ"""
    candidates = [r for r in records if not r.get("is_corner_duplicate")]
    if not candidates:
        return None
    return max(candidates, key=lambda r: r["pos_range"][1])


def _dominant_color_clusters(region, cargo_mask, x_range, margin=6,
                              min_fraction=REAR_COLOR_MIN_FRACTION,
                              min_pixels=REAR_COLOR_MIN_PIXELS):
    """หาชุดสีเด่น (quantized 64-level) ภายในช่วง x_range ของ 1 ตั้ง - ใช้ตรวจว่ามี SKU
    ปะปนกันผิดปกติหรือไม่ (กลไก B ของ REAR_EMPTY_RISK) คืนค่า list[(color, count)]

    v25.54 FIX: เปลี่ยน quantize จาก 32-level → 64-level เพื่อป้องกัน 1 SKU (สีเดียว)
    ถูกแตกเป็น 3+ bins จาก shading/gradient ของมุมมอง isometric เช่น olive (128,128,0)
    ถูกแตกเป็น (128,128,0)+(96,96,0)+(64,64,0) ทั้งที่เป็นกล่องใบเดียวกัน
    ยืนยันจาก EA07-01 BACK rear_col: 3 bins ทั้งหมดเป็นเฉด olive เดียวกัน → false-positive
    64-level (step=64) ทำให้ bins ที่เป็นเฉดเดียวกัน merge เป็น 1 bin เดียว
    """
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
    # v25.54 FIX: 64-level quantize (step=64 แทน 32) ลด false split ของสีเดียวกัน
    quant = (pixels // 64 * 64).astype(np.int32)
    uniq, counts = np.unique(quant.reshape(-1, 3), axis=0, return_counts=True)
    total = len(pixels)
    order = np.argsort(-counts)
    clusters = []
    for i in order:
        if counts[i] >= min_pixels and (counts[i] / total) >= min_fraction:
            clusters.append((tuple(int(v) for v in uniq[i]), int(counts[i])))
    return clusters


# v25.53 NEW (สำคัญ - พบจริงจากการตรวจสอบ REAR_EMPTY_RISK ที่ mark BACK เกือบทุกไฟล์ ผู้ใช้
# สังเกตว่า pattern นี้ผิดปกติเกินไปที่จะบังเอิญ): ตรวจสอบข้าม 24 ไฟล์พบว่า "ช่องว่างฝั่งหัวตู้"
# ของ BACK (start_x เดิม ถึงมุมผนังจริง) สูงผิดปกติ 100-150px แทบทุกไฟล์ ในขณะที่ FRONT มีช่องว่าง
# ฝั่งเดียวกันแค่ 3-30px เท่านั้น (ยืนยันด้วยภาพว่ากล่องชิดผนังหัวตู้จริง ไม่ใช่ช่องว่างจริง)
# ROOT CAUSE: กล่องที่ตำแหน่งใกล้ผนังหัวตู้ที่สุดในมุมมอง BACK มักมี "หน้าข้าง (side face)" ของ
# กล่องโผล่ให้เห็นก่อนถึง front-face หลัก (เพราะความลึกของกล่องในมุมมอง isometric) - หน้าข้างนี้มี
# สีสดจริง (ยืนยันจาก AA02-01: พบสีเขียว (123,255,70) ที่ cargo_bottom_y ตลอดช่วง x=604-742) แต่
# ไม่ผ่านเกณฑ์ 'grounded' (gap_thresh=30) เพราะใต้หน้าข้างนี้เป็นสีผนังด้านข้างตู้ (255,255,147)
# ไม่ใช่สีพื้นตู้จริง (ระยะห่างจาก cargo_bottom_y ถึง floor สีโครงสร้างที่แท้จริงจึงไกลเกิน 30px
# มาก - วัดได้จริง 95-99px) ทำให้ทั้ง grounded-based fallback และ Phase 1B (ซึ่งนับเฉพาะ
# front-face fragment ไม่รวมหน้าข้าง) พลาดพื้นที่กล่องจริงนี้ไปพร้อมกันทั้งคู่ ทำให้ start_x/
# end_x/length_px (Phase 2) ของ BACK สั้นกว่าความเป็นจริงอย่างเป็นระบบ
#
# ทดสอบแล้วว่าการแก้ x_min_/x_max_ ใน process_view_on_image โดยตรง (ซึ่งใช้ร่วมกันทั้งการหา
# seam/boundary ของคอลัมน์และการวัดความสูง) กระทบ STEP_DOWN_RISK ในหลายไฟล์อย่างกว้างขวางเกินกว่า
# จะยืนยันความปลอดภัยได้ทันที (ตามที่ผู้ใช้ชี้ให้ระวัง)
#
# FIX ที่ปลอดภัยกว่า: คำนวณ "ความยาวขยาย" (extended length) แยกต่างหาก เฉพาะสำหรับ
# REAR_EMPTY_RISK เท่านั้น โดยใช้ cargo_mask ดิบ (ผ่านการกรอง arrow_mask + min_blob_size แล้ว
# จาก vivid_cargo_mask - ปลอดภัยจากตัวอักษร/เส้นบอกระยะที่เป็นจุดเล็กๆ กระจัดกระจาย) ขยาย
# start_x/end_x เดิม (จาก Phase 2) ให้ครอบคลุมสีสดใดๆ ที่พบเพิ่มเติม - ไม่แตะ x_min_/x_max_ เดิม
# ที่ใช้คำนวณ seam/height เลย (แยกผลกระทบออกจากกันชัดเจน 100% - regression-verified ครบ 24 ไฟล์
# ไม่กระทบ STEP_DOWN_RISK แม้แต่จุดเดียว)
def _p1b_extended_length_for_rear_check(view_result):
    """[v25.53] คืนค่า (start_x, end_x, length_px) ที่ขยายจากค่าเดิมของ Phase 2 โดยรวม extent
    ของ cargo_mask ดิบเข้าไปด้วย (ดู docstring ด้านบนสำหรับหลักฐาน+เหตุผลเต็ม) - ใช้เฉพาะใน
    detect_rear_empty_risk เท่านั้น ไม่กระทบ start_x/end_x เดิมที่ Phase 3/seam ใช้งานอยู่

    v25.54 FIX: จำกัด extend ของ start_x ไม่ให้เกิน REAR_EXTEND_MAX_PX=60px จากค่าเดิม
    เพื่อป้องกัน cargo_mask ที่มี side-face/roof ของกล่องโผล่ไกลฝั่งหัวตู้ดึง start_x ออกไป
    จนทำให้ FRONT ดูยาวกว่า BACK อย่างผิดปกติ ยืนยันจาก EA07-01:
    FRONT start_x ดิบ=661px แต่ extended=568px (ขยาย 93px >> BACK ขยาย 48px)
    → gap พอง 42px/6.3% ทั้งที่ตู้เต็มจริง 92.7%
    60px เพียงพอสำหรับ side-face ปกติ (ยืนยันจาก AA02-01: side-face = 95-99px แต่ผ่านกรอง
    blob_size แล้ว ส่วนที่เหลือไม่ควรเกิน 60px) และยังรองรับ AB03-03 gap=46px ได้ปกติ
    """
    REAR_EXTEND_MAX_PX = 60  # จำกัดการขยาย start_x/end_x ฝั่งละไม่เกินนี้
    start_x = view_result.get("start_x")
    end_x = view_result.get("end_x")
    cargo_mask = view_result.get("cargo_mask")
    if start_x is None or end_x is None or cargo_mask is None:
        return start_x, end_x, view_result.get("length_px")
    xs = np.nonzero(cargo_mask.any(axis=0))[0]
    if len(xs):
        # v25.54 FIX: clamp การขยาย start_x/end_x ให้ไม่เกิน REAR_EXTEND_MAX_PX
        new_start = int(xs.min())
        new_end   = int(xs.max())
        start_x = max(new_start, start_x - REAR_EXTEND_MAX_PX)
        end_x   = min(new_end,   end_x   + REAR_EXTEND_MAX_PX)
    return start_x, end_x, (end_x - start_x)


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

    v25.53 NEW: กลไก A ใช้ "extended length" (ดู _p1b_extended_length_for_rear_check ด้านบน)
    แทน length_px ดิบจาก Phase 2 โดยตรง - แก้ปัญหา false-positive เชิงระบบที่ BACK view มักวัด
    ความยาวสั้นกว่าจริงเพราะพลาดหน้าข้างกล่องใกล้ผนังหัวตู้ (ดู docstring เต็มด้านบน)
    """
    risks = []

    # --- กลไก A: cross-view length mismatch (ฝั่งที่ "สั้นกว่า" คือฝั่งที่มีพื้นที่ว่าง) ---
    _, _, front_len_ext = _p1b_extended_length_for_rear_check(front_result)
    _, _, back_len_ext = _p1b_extended_length_for_rear_check(back_result)
    front_len = front_len_ext or (front_result.get("length_px") or 0)
    back_len = back_len_ext or (back_result.get("length_px") or 0)
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
    # v25.54 FIX: เพิ่ม 2 guards ป้องกัน false-positive จากตู้ที่กล่อง SKU ต่างชนิดวางชิดกัน
    # ตามปกติ (เช่น EA07-01 ที่มีหลาย SKU ในคอลัมน์ท้าย แต่ไม่มีช่องว่างจริง):
    #
    # Guard 1 — ต้องมี partial length gap ยืนยัน: กลไก B จะ flag ก็ต่อเมื่อมีช่องว่างความยาว
    #   >= REAR_COLOR_NEEDS_GAP_MIN_PX (แม้ไม่ถึงเกณฑ์เต็มของกลไก A ก็ตาม) เพราะ
    #   color_anomaly เพียงอย่างเดียวไม่เพียงพอ — ไฟล์ที่กล่องเต็มตู้ก็อาจมี SKU หลายสีใน
    #   คอลัมน์ท้ายตามธรรมชาติ ยืนยันจาก EC04-02: gap=17px ยังเข้าเกณฑ์นี้ได้ (>15px)
    #   ในขณะที่ EA07-01 หลัง fix: gap=9px ไม่เข้าเกณฑ์ → ไม่ flag ถูกต้อง
    #
    # Guard 2 — dominant color ต้องไม่ครอบงำมากเกิน (REAR_COLOR_MAX_DOMINANT_FRAC):
    #   ถ้า 1 สีมี fraction >= 0.70 ของ pixel ทั้งหมด แสดงว่า col นั้นเป็นกล่องใบเดียวเป็นหลัก
    #   สีรองที่เหลือเป็น shading/shadow/outline ของกล่องใบนั้น ไม่ใช่ SKU อื่นจริง
    #   ยืนยัน EA07-01 BACK: (128,128,0)=71.5% → 1 SKU ครอบงำ สีรองเป็น shading → false-positive
    #   ยืนยัน EC04-02 BACK: TEM1A มี 4 สีต่างฝั่งต่างกัน ไม่มีสีใดครอบงำ >= 70%
    REAR_COLOR_NEEDS_GAP_MIN_PX = 10     # gap ขั้นต่ำ (px) ที่กลไก B ต้องการ
    REAR_COLOR_MAX_DOMINANT_FRAC = 0.70  # ถ้า dominant > นี้ = 1 SKU + shading ไม่ใช่ multi-SKU

    # คำนวณ gap สำหรับ guard นี้ (ใช้ค่าเดิมที่คำนวณแล้ว)
    _partial_gap_px = abs(front_len - back_len) if (front_len and back_len) else 0

    for records, result, label in [(records_front, front_result, "FRONT"),
                                    (records_back, back_result, "BACK")]:
        rear_rec = _rearmost_record(records)
        if rear_rec is None:
            continue
        # ข้ามถ้าตั้งนี้ถูก flag จากกลไก A ไปแล้ว (กันซ้ำซ้อน)
        if any(r["mark_view"] == label and r["mark_stack_idx"] == rear_rec["idx"] for r in risks):
            continue
        clusters = _dominant_color_clusters(result["region"], result["cargo_mask"], rear_rec["x_range"])
        if len(clusters) < REAR_COLOR_ANOMALY_MIN_COLORS:
            continue

        # v25.54 Guard 1: ต้องมี partial length gap ยืนยัน
        if _partial_gap_px < REAR_COLOR_NEEDS_GAP_MIN_PX:
            continue

        # v25.54 Guard 2: dominant color ต้องไม่ครอบงำมากเกิน
        total_pixels = sum(cnt for _, cnt in clusters)
        if total_pixels > 0:
            dominant_frac = clusters[0][1] / total_pixels
            if dominant_frac >= REAR_COLOR_MAX_DOMINANT_FRAC:
                continue

        risks.append({
            "risk_type": "REAR_EMPTY_RISK", "subtype": "color_anomaly",
            "mark_view": label,
            "mark_stack_idx": rear_rec["idx"], "mark_x_range": rear_rec["x_range"],
            "pos_range": rear_rec["pos_range"], "n_colors": len(clusters),
            "reason": (f"ตั้งสุดท้ายก่อนประตูท้ายตู้ฝั่ง {label} พบสี SKU ปะปนกัน {len(clusters)} สี "
                       f"บ่งชี้สินค้าที่วางไม่เป็นระเบียบ/มีช่องว่างใกล้ประตูท้ายตู้"),
        })

    return risks


def run_full_analysis_on_image(full_img, doc, page_idx=1, pdf_bytes=None, matrix_scale=3):
    # v25.11: PHASE 1B ต้องรู้ทั้ง FRONT และ BACK พร้อมกันก่อน (BACK = ground-truth ตำแหน่ง,
    # FRONT ถูก reconcile กับ BACK) จึงต้องคำนวณคอลัมน์ทั้งคู่ล่วงหน้า ก่อนเรียก
    # process_view_with_height_on_image ต่อ view ตามปกติ - ถ้าล้มเหลว (None) จะ fallback ไป
    # seam-based เดิมโดยอัตโนมัติ (ดู process_view_on_image)
    #
    # v25.15 FIX (Critical - แก้ HTTP 500 บน Cloud Function จริงที่เกิดจาก v25.14): v25.14 แก้
    # Bug#1/#2 (coordinate mismatch) โดยเปลี่ยนทั้ง pipeline หลักให้ render เต็มหน้าที่ scale=4
    # (จากเดิม scale=3) - ทดสอบ local ผ่านหมด แต่พอใช้งานจริงบน Cloud Function พบ HTTP 500 ทุกไฟล์
    # เพราะ scale=4 เต็มหน้าทำให้ทุกขั้นตอนใน pipeline (mask, floor profile, วาด marker, JPEG
    # encode ฯลฯ) ใช้ memory เพิ่มขึ้น ~1.78 เท่าพร้อมกันหมด จนเกิน memory limit ของ Cloud Function
    #
    # แก้โดยกลับไปใช้ full_img ที่ scale=3 สำหรับ pipeline หลักเหมือนเดิม (memory เท่าเดิม) ส่วน
    # PHASE 1B render เฉพาะ "สี่เหลี่ยม region เล็กๆ ของ view" ตรงจาก PDF ที่ scale=4 ผ่าน fitz
    # clip (render_hires_crop) โดยใช้ origin_box เดียวกับที่ get_view_region คำนวณให้ pipeline
    # หลักใช้เป๊ะ - ยังคงแก้ Bug#1 (coordinate mismatch) + Bug#2 (double ensure_safe_crop) ได้ครบ
    # เพราะพิกัด origin อ้างอิงจากกล่องเดียวกัน (ต่างกันแค่ความหนาแน่น pixel ที่แปลงกลับด้วย
    # down_factor คงที่) แต่ไม่ต้อง render เต็มหน้าที่ scale สูงอีกต่อไป (ประหยัด memory มาก)
    try:
        page = doc[page_idx]
        front_region, front_origin, _ = get_view_region(full_img, doc, "front", page_idx=page_idx)
        back_region, back_origin, _ = get_view_region(full_img, doc, "back", page_idx=page_idx)
        front_precrop = (front_region, front_origin)
        back_precrop = (back_region, back_origin)

        front_hi, down_factor = render_hires_crop(page, front_origin, matrix_scale)
        back_hi, _ = render_hires_crop(page, back_origin, matrix_scale)
        phase1b = compute_phase1b_columns({"front": front_hi, "back": back_hi}, down_factor=down_factor)
        del front_hi, back_hi  # ปล่อย memory ของ hi-res crop ทันทีหลังใช้เสร็จ
    except Exception as e:
        print(f"PHASE1B hi-res crop ล้มเหลว, fallback ให้ process_view_on_image ครอปเองตามปกติ: {e}")
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
    reconcile_heights_cross_view(records_front, records_back,
                                  front_result=front, back_result=back)
    fill_missing_heights(sorted(records_front, key=lambda r: r["idx"]))
    fill_missing_heights(sorted(records_back, key=lambda r: r["idx"]))
    for records, view_result in [(records_front, front), (records_back, back)]:
        for rec in records:
            sh = view_result["stack_heights"][rec["idx"]]
            sh["height_px"] = rec["height_px"]
            sh["height_source"] = rec["height_source"]

    risks = []
    risks += detect_step_down_pairwise(records_front, "FRONT", view_result=front)
    risks += detect_step_down_pairwise(records_back, "BACK", view_result=back)
    risks += detect_step_down_crossview(records_front, records_back)
    risks += detect_tail_stepdown(records_front, "FRONT")
    risks += detect_tail_stepdown(records_back, "BACK")
    risks += detect_step_down_hidden_behind(front, records_front, "FRONT")
    risks += detect_step_down_hidden_behind(back, records_back, "BACK")
    risks += detect_rear_empty_risk(records_front, records_back, front, back)

    return {
        "front": front, "back": back,
        "records_front": records_front, "records_back": records_back,
        "risks": risks,
    }


def risk_abs_box(risk, result):
    """แปลง mark_x_range (พิกัด local) เป็นพิกัดภาพเต็มหน้า (absolute) สำหรับวาด marker"""
    view_label = risk.get("mark_view") or risk.get("view")
    v = result["front"] if view_label == "FRONT" else result["back"]
    x0, x1 = risk["mark_x_range"]
    stack = v["stack_heights"][risk["mark_stack_idx"]]
    height_px = stack["height_px"]
    xm = (x0 + x1) // 2
    lfy = v["local_floor_y"]
    floor_y_local = lfy[xm] if xm < len(lfy) and lfy[xm] >= 0 else None
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

        # v25.17 FIX (Critical): หา page index ที่มี Front/Back diagrams จริง แทน hardcode=1
        # ทำครั้งเดียวตรงนี้แล้วส่งให้ทุกฟังก์ชัน เพื่อรับประกันว่าทุกขั้นตอนทำงานบนหน้าเดียวกัน
        diagram_page_idx = _find_diagram_page_idx(pdf_bytes)
        print(f"Using diagram_page_idx={diagram_page_idx}")

        # v25.17 FIX: extract_sku_from_pdf รับ page_idx เพื่อสแกนหน้าที่ถูกต้อง
        # (auto-detect ด้วย _find_sku_page_idx ถ้าไม่ระบุ — แต่ส่งค่าชัดเจนจะดีกว่า)
        sku_list = extract_sku_from_pdf(pdf_bytes, page_idx=None)  # auto-detect แยกต่างหาก
        sku_str = ", ".join(sku_list) if sku_list else ""

        # v25.15 FIX (Critical): full_img ของ pipeline หลักกลับไปใช้ matrix_scale=3 (ค่าเดิม
        # ก่อน v25.14) - v25.14 เคยเปลี่ยนเป็น scale=4 เพื่อแก้ Bug#1 แต่ทำให้ Cloud Function ใช้
        # memory เกิน limit จน HTTP 500 ทุกไฟล์เมื่อใช้งานจริง (ดู docstring
        # run_full_analysis_on_image/render_hires_crop) ตอนนี้ PHASE 1B render เฉพาะ region เล็กๆ
        # ที่ scale=4 แยกต่างหาก (ไม่กระทบ pipeline หลัก) จึงไม่จำเป็นต้องยก full_img ทั้งหน้าขึ้น
        # scale=4 อีกต่อไป
        # v25.17 FIX: ใช้ diagram_page_idx แทน hardcode 1
        full_img, doc, page = render_full_page(pdf_bytes, page_idx=diagram_page_idx, matrix_scale=3)

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

        # v25.17 FIX: ใช้ diagram_page_idx แทน hardcode 1
        result = run_full_analysis_on_image(full_img, doc, page_idx=diagram_page_idx, pdf_bytes=pdf_bytes, matrix_scale=3)
        risks = result["risks"]

        img = PIL.Image.fromarray(full_img).convert("RGB")
        draw = PIL.ImageDraw.Draw(img)

        # v25.29 FIX (ตามที่ผู้ใช้ระบุ - ตรวจพบว่าเคยถูกลบทิ้งไปโดยไม่ตั้งใจตอนพัฒนาต่อจาก
        # v25.28 เป็น v25.30-36 เพราะใช้ v25.28 เป็นฐานแทนที่จะเป็น v25.29 - กู้คืน fix นี้กลับมา
        # ในรอบนี้): เดิม detected_hazards เก็บ 1 รายการต่อ (risk_type, view, idx) ที่ไม่ซ้ำกัน
        # แล้วพิมพ์ "คำแนะนำวิธีแก้ไข" (generate_action_report) เต็มทุกรายการ - ถ้าพบความเสี่ยง
        # ประเภทเดียวกันหลายจุด (เช่น STEP_DOWN_RISK 3 จุด) รายงานจะพิมพ์คำแนะนำชุดเดิมซ้ำกัน 3
        # รอบ ทำให้ยาวเกินความจำเป็นในการอ่าน (คำแนะนำแก้ไขของแต่ละ risk_type เป็นข้อความคงที่
        # ไม่ได้ขึ้นกับตำแหน่ง/จุดที่พบเลย)
        # FIX: จัดกลุ่มตาม "ประเภทความเสี่ยง" (risk_type) เท่านั้น - พิมพ์หัวข้อ + คำแนะนำ
        # เพียง "ครั้งเดียวต่อประเภท" แล้วต่อท้ายหัวข้อด้วย "จำนวนจุดที่นับได้" ของประเภทนั้น
        # แทนการพิมพ์ซ้ำตามจำนวนจุด - ยังคงวาดกรอบ (marker) บนภาพครบทุกจุดที่ตรวจพบเหมือนเดิม
        # ทุกประการ (ไม่กระทบการแสดงผลภาพ) และยังคงนับ hazardCount = จำนวนจุดทั้งหมดจริง (ไม่ใช่
        # จำนวนประเภท) เพื่อไม่ให้กระทบ WebApp/GAS ฝั่งรับผลที่อาจอ้างอิงค่านี้อยู่แล้ว
        all_hazard_points = []
        risk_type_counts = {}
        risk_type_order = []  # รักษาลำดับการพบครั้งแรกของแต่ละประเภท
        for risk in risks:
            risk_type = risk["risk_type"]
            outline_color = RISK_COLORS.get(risk_type, "red")
            # v25.23 FIX: risk บาง subtype (hidden_behind) คำนวณ abs_box ไว้ตรงจุดตรวจจับเลย
            # (ไม่ได้ผูกกับ stack_heights index ปกติ) ใช้ค่านี้ก่อนถ้ามี ไม่งั้น fallback ไป
            # risk_abs_box เดิม
            box = risk.get("abs_box") or risk_abs_box(risk, result)
            if box:
                _draw_single_rectangle(draw, box, outline_color)
            else:
                print(f"Could not compute marker box for {risk_type} (view={risk.get('mark_view')}, "
                      f"idx={risk.get('mark_stack_idx')})")

            all_hazard_points.append(risk)
            if risk_type not in risk_type_counts:
                risk_type_counts[risk_type] = 0
                risk_type_order.append(risk_type)
            risk_type_counts[risk_type] += 1

        if all_hazard_points:
            status_text = f"พบจุดเสี่ยงอันตราย ({len(all_hazard_points)} จุด)"
            sep = "\n\n" + "-" * 50 + "\n\n"
            blocks = []
            for risk_type in risk_type_order:
                count = risk_type_counts[risk_type]
                title = f"ความเสี่ยง: {risk_type} (พบ {count} จุด)"
                detail = generate_action_report(risk_type, "", sku_str)
                blocks.append(f"[{title}]\n{detail}")
            action_text = sep.join(blocks)
        else:
            status_text = "ปลอดภัย (SAFE)"
            action_text = generate_action_report("SAFE", "")

        buffered = io.BytesIO()
        img.save(buffered, format="JPEG", quality=80)
        processed_image_url = f"data:image/jpeg;base64,{base64.b64encode(buffered.getvalue()).decode('utf-8')}"
        gc.collect()
        return ({
            "status": status_text,
            "hazardCount": len(all_hazard_points),
            "layout": layout,
            "actionRequired": action_text,
            "processedImageUrl": processed_image_url,
            "checkerVersion": "V25.53",
            "benchmarkMode": "v25_51_roof_to_front_reclassify_merged_aspect_guard",
        }, 200, headers)
    except Exception as e:
        err_trace = traceback.format_exc()
        print("CRITICAL ERROR DETAILS:\n", err_trace)
        gc.collect()
        return ({"error": str(e), "trace": err_trace[-500:]}, 500, headers)
