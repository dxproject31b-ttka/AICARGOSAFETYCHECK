# ใช้ Python Image เป็นฐาน
FROM python:3.10-slim

# ตั้งค่าให้ Python ไม่เขียน .pyc files และส่ง output ตรงไปยัง terminal
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ติดตั้ง poppler-utils
RUN apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# ตั้งค่าพื้นที่ทำงานและสร้าง User เพื่อความปลอดภัย
WORKDIR /app
RUN useradd -m appuser
USER appuser

# คัดลอกแค่ requirements ก่อนเพื่อใช้ประโยชน์จาก Docker Layer Caching
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# คัดลอก Source code ที่เหลือ
COPY --chown=appuser:appuser . .

# สั่งรัน functions-framework
CMD exec functions-framework --target=process_request --port=$PORT
