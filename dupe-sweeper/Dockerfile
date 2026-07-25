FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# ponytail: runs as root on purpose — it must delete media files owned by
# assorted Synology users, and root sidesteps the dynamic-UID ownership trap.
# The container is LAN-only behind nginx basic auth; deletes are realpath-gated.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
