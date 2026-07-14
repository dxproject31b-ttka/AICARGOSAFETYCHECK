# ใช้ Python Image เป็นฐาน
FROM python:3.10-slim

# สำคัญมาก: ติดตั้ง poppler-utils ระดับ OS ให้ระบบแปลง PDF ได้
RUN apt-get update && apt-get install -y poppler-utils && rm -rf /var/lib/apt/lists/*

# ตั้งค่าพื้นที่ทำงาน
WORKDIR /app

# คัดลอกไฟล์ทั้งหมดลงใน Container
COPY . .

# ติดตั้งไลบรารี Python จากไฟล์ requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# สั่งรัน functions-framework ชี้เป้าหมายไปที่ฟังก์ชัน process_request ใน main.py
CMD exec functions-framework --target=process_request --port=$PORT
