# watchtower — Daily Log

---

## 2026-06-24 — notifier sidecar ใช้ shared Notifier

ส่วนหนึ่งของงานรวม transport ข้าม stack → `shared/notify.py` (stdlib `urllib`, vendored ด้วย
`make sync-shared`, กัน drift ด้วย `tests/test_shared_sync.py`).

**watchtower:** `notifier/notifier.py` ตัด `send_line`/`send_telegram` (requests) → `_notifier`
ระดับ module (LINE + Telegram, plain text, timeout=10); `notify(text)` delegate ไป `_notifier.send()`
แล้ว print ช่องที่สำเร็จ. ลบ `requests` ออกจาก `requirements.txt` (เหลือ `tzdata`) — Docker socket
ยังใช้ raw `socket` เหมือนเดิม. Dockerfile เพิ่ม `COPY notify.py`. import-smoke ผ่าน (stack ไม่มี test).

⚠️ verify ถึงแค่ transport seam (TLS check urllib ใน `python:3.12-slim` บน NAS ผ่าน);
ของจริงพิสูจน์ตอน watchtower อัปเดต container ครั้งแรกหลัง deploy.
