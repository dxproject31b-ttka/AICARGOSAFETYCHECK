# ใช้ Python Image เป็นฐาน
FROM python:3.10-slim

# ตั้งค่าให้ Python ไม่เขียน .pyc files และส่ง output ตรงไปยัง terminal
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ติดตั้ง poppler-utils สำหรับอ่านไฟล์ PDF
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# ตั้งค่าพื้นที่ทำงานและสร้าง User เพื่อความปลอดภัย
WORKDIR /app
RUN useradd -m appuser
USER appuser

# เพิ่มโฟลเดอร์ .local/bin เข้าไปใน PATH ของระบบ
# เพื่อให้ Container มองเห็นคำสั่ง functions-framework ที่ถูกติดตั้งผ่าน --user
ENV PATH="/home/appuser/.local/bin:${PATH}"

# คัดลอกแค่ requirements ก่อนเพื่อใช้ประโยชน์จาก Docker Layer Caching
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# คัดลอก Source code ที่เหลือ (เช่น main.py)
COPY --chown=appuser:appuser . .

# กำหนด PORT เริ่มต้นไว้ที่ 8080 (Cloud Run จะเปลี่ยนค่านี้ให้เองตอนรันจริง)
ENV PORT=8080

# จุดที่แก้ไข: ใช้ exec และกำหนด --host=0.0.0.0 พร้อมกับใช้ตัวแปร $PORT 
# (ห้ามใช้รูปแบบ Array [] เพราะมันจะไม่อ่านค่า $PORT)
CMD exec functions-framework --target=process_request --signature-type=http --host=0.0.0.0 --port=$PORT
