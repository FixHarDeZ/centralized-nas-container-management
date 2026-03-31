# Watchtower + LINE Notifier (Sidecar approach)

## โครงสร้างไฟล์

```
watchtower-line/
├── docker-compose.yml
└── notifier/
    ├── Dockerfile
    ├── notifier.py
    └── requirements.txt
```

## วิธีใช้งาน

```bash
# Build และ start
docker compose up -d --build

# ดู notifier logs
docker compose logs -f watchtower-notifier
```

## Notifications ที่จะได้รับ

| Event | ข้อความที่ส่ง |
|---|---|
| Notifier เริ่มต้น | 🤖 LINE Notifier พร้อมทำงานแล้ว |
| Watchtower start | 🟢 Watchtower เริ่มทำงานแล้ว |
| Container อัปเดต | 🔄 Container อัปเดตแล้ว + ชื่อ image |
| ไม่มีอัปเดต | ✅ ตรวจสอบเสร็จ + สรุป |
| Error | 🔴 Watchtower พบ Error + log excerpt |

## Flow

```
Watchtower container (logs)
        ↓  docker logs --follow
watchtower-notifier (Python sidecar)
        ↓  parse & detect events
LINE Messaging API
        ↓
มือถือคุณ 📱
```

## หมายเหตุ

- Sidecar mount `/var/run/docker.sock` เพื่อใช้ `docker logs --follow` ติดตาม Watchtower
- ถ้า Watchtower restart, notifier จะ reconnect อัตโนมัติใน 10 วินาที
- ปรับ `WATCHTOWER_POLL_INTERVAL` เป็นวินาที (86400 = 24h)
