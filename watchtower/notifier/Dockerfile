FROM python:3.12-slim

# ไม่ต้องติดตั้ง docker CLI อีกต่อไป — ใช้ Docker socket API โดยตรง
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY notifier.py .

CMD ["python", "-u", "notifier.py"]
