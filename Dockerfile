# ใช้ Python Image เป็นฐาน
FROM python:3.10-slim

# ตั้งค่าให้ Python ไม่เขียน .pyc files และส่ง output ตรงไปยัง terminal
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=8080

# 🚨 ติดตั้ง OS Dependencies: poppler-utils (สำหรับ pdf2image) และ OpenCV libraries
RUN apt-get update && apt-get install -y \
    poppler-utils \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# สร้าง Non-root User เพื่อความปลอดภัยในการรันบน Cloud Run
RUN adduser --disabled-password --gecos "" appuser

# ตั้งค่าพื้นที่ทำงาน
WORKDIR /app

# คัดลอกและติดตั้ง Python packages (ใช้ Layer Caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# คัดลอก Source code ทั้งหมด และกำหนดสิทธิ์ให้ appuser
COPY --chown=appuser:appuser . .

# สลับไปใช้ appuser รันแอปพลิเคชัน
USER appuser

# สั่งรันด้วย functions-framework (สอดคล้องกับ @functions_framework.http ใน main.py)
CMD exec functions-framework --target=process_request --host=0.0.0.0 --port=$PORT
