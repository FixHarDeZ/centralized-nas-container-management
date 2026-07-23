# watchtower — Daily Log

---

## 2026-07-24 — major-version watch + uptime-kuma pin fix

**ปัญหา:** watchtower ไม่เคยอัปเดต uptime-kuma เลยทั้งที่มี release ใหม่. สาเหตุ = tag `:latest`
ของ `louislam/uptime-kuma` ค้างที่ v1 ตั้งแต่ 2025-10; release ใหม่ (2.x) ไป push ที่ tag `2` แทน.
watchtower เทียบ digest ของ `latest` ไม่เปลี่ยน เลยไม่มีอะไรให้อัปเดต. Fix: pin
`uptime-kuma/docker-compose.yml` เป็น `:2` (backup v1 DB → `/volume2/docker/uptime-kuma-v1-backup-*.tar.gz`
ก่อน, v2 auto-migrate SQLite ตอน boot; deploy แล้ว running v2.4.0).

**Feature:** semver tag ข้าม major ให้ไม่ได้ (tag N แข็งเมื่อ vN+1 ออก — กับดักเดิม). เพิ่ม
daemon thread `major_watch_loop` ใน `notifier.py`: poll GitHub `releases/latest` ของ repo ใน
`MAJOR_WATCH` วันละครั้ง แจ้ง LINE+Telegram (ผ่าน `notify()` เดิม) เมื่อ major > ที่ pin ไว้.
Dedupe ใน memory (re-nag หลัง restart). Pure fn `newer_major()` + `test_major_watch.py` (รัน
`python test_major_watch.py` → OK). เพิ่ม repo = 1 บรรทัดใน `MAJOR_WATCH`. Config
`MAJOR_CHECK_INTERVAL_HOURS` (default 24).

⚠️ deploy: `./scripts/deploy.sh -s watchtower -y` รันแบบ non-interactive จาก workstation ได้
(sudo password จาก `.env.deploy` pipe ผ่าน `sudo -S`); ที่ก่อนหน้า remote ค้าง `:latest` เพราะ
manual run โดน abort ที่ confirm prompt ไม่ใช่ deploy พัง.

## 2026-06-24 — notifier sidecar ใช้ shared Notifier

ส่วนหนึ่งของงานรวม transport ข้าม stack → `shared/notify.py` (stdlib `urllib`, vendored ด้วย
`make sync-shared`, กัน drift ด้วย `tests/test_shared_sync.py`).

**watchtower:** `notifier/notifier.py` ตัด `send_line`/`send_telegram` (requests) → `_notifier`
ระดับ module (LINE + Telegram, plain text, timeout=10); `notify(text)` delegate ไป `_notifier.send()`
แล้ว print ช่องที่สำเร็จ. ลบ `requests` ออกจาก `requirements.txt` (เหลือ `tzdata`) — Docker socket
ยังใช้ raw `socket` เหมือนเดิม. Dockerfile เพิ่ม `COPY notify.py`. import-smoke ผ่าน (stack ไม่มี test).

⚠️ verify ถึงแค่ transport seam (TLS check urllib ใน `python:3.12-slim` บน NAS ผ่าน);
ของจริงพิสูจน์ตอน watchtower อัปเดต container ครั้งแรกหลัง deploy.
