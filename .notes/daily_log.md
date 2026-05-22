# Daily Log

---

## 2026-05-23 — Homepage widgets fix + Per-stack .env refactor + Watchtower 429 fix

### งานที่ทำ

#### 1. Debug & fix homepage widgets พัง
- **สาเหตุ:** DSM Auto-Block (error code 407) บล็อก IP ของ Docker container (172.24.0.2, 172.25.0.2, 172.20.0.2) หลังจาก login fail ซ้ำๆ — homepage แสดงเป็น "Authentication failed. 2FA enabled." ซึ่งทำให้เข้าใจผิด
- **Fix:**
  1. เพิ่ม private subnets ใน DSM Allow List: `10.0.0.0/255.0.0.0`, `172.16.0.0/255.240.0.0`, `192.168.0.0/255.255.0.0`
  2. ลบ Docker IPs ที่ค้างใน Block List ออกผ่าน `sqlite3 /etc/synoautoblock.db`
  3. Restart homepage container

#### 2. Refactor: per-stack .env (แยก secrets ตาม stack)
- **สาเหตุ:** root `.env` ไฟล์เดียวทำให้ทุก container เห็น secret ทั้งหมด ยากต่อการ debug
- **โครงสร้างใหม่:**
  - Root `.env` → เฉพาะ `NAS_*` (deploy.sh) + `NOTION_*` (sync_notion.py) — containers ไม่เห็น
  - `<stack>/.env` → secrets เฉพาะ stack นั้นๆ
  - `<stack>/.env.example` → template (commit ได้)
- **ไฟล์ที่เปลี่ยน:**
  - สร้าง `homepage/.env`, `jellyfin/.env`, `line-secretary/.env`, `maid-tracker/.env`, `torrentwatch/.env`, `uptime-kuma/.env`, `watchtower/.env`
  - สร้าง `.env.example` ครบทุก stack
  - แก้ `env_file: ../.env` → `env_file: .env` ใน 5 stacks
  - แก้ `deploy.sh`: ลบ "upload root .env + distribute" step, เปลี่ยน restart ใช้ `--project-directory` แทน `--env-file`
  - อัปเดต root `.env.example`, `CLAUDE.md`, `README.md`

#### 3. Fix watchtower notifier 429 rate limit
- **สาเหตุ:** startup ส่ง LINE 2 ข้อความในช่วงเวลา <1 วินาที (startup message + session_start handler)
- **Fix:** ลบ `send_line()` ออกจาก `main()` — session_start handler แจ้งครบอยู่แล้ว
- Deploy watchtower ใหม่ rebuild image สำเร็จ

### ไฟล์ที่เปลี่ยน
- `*/env`, `*/.env.example` (7 stacks)
- `homepage/docker-compose.yml`, `line-secretary/docker-compose.yml`, `maid-tracker/docker-compose.yml`, `torrentwatch/docker-compose.yml`, `watchtower/docker-compose.yml`
- `scripts/deploy.sh`
- `.env`, `.env.example`, `.gitignore`
- `CLAUDE.md`, `README.md`
- `watchtower/notifier/notifier.py`

### Key Learnings
- DSM Auto-Block error code 407 แสดงเป็น "2FA enabled" ใน homepage log — ต้อง check homepage container logs โดยตรงเพื่อเห็น actual code
- `--project-directory` ทำให้ `docker compose` หา `.env` ในโฟลเดอร์ของ stack เองโดยอัตโนมัติ
- tar `--exclude='./.env'` (มี `./` นำหน้า) excludes เฉพาะ root level — sub-stack `.env` ไม่ถูก exclude

---

## 2026-05-22 — Centralise NAS volume root paths via env vars

### งานที่ทำ
- เพิ่ม `NAS_VOLUME_ROOT` และ `NAS_MEDIA_ROOT` ใน `.env` และ `.env.example`
- Replace hardcoded `/volume1` ใน compose files ทุกตัวด้วย `${NAS_VOLUME_ROOT}`
- แยก Jellyfin media paths ออกมาใช้ `${NAS_MEDIA_ROOT}` แทน เพราะอาจย้าย volume แยกกัน
- Homepage disk monitor widget ใช้ `{{HOMEPAGE_VAR_VOLUME_ROOT}}` ผ่าน Homepage's own substitution system
- ทดสอบด้วย `docker compose --env-file ../.env config` ทุก stack — interpolate ถูกต้องทั้งหมด
- ผู้ใช้ทดสอบจริงโดยเปลี่ยน `.env` เป็น `NAS_VOLUME_ROOT=/volume2` — ทำงานได้ทันที

### ไฟล์ที่เปลี่ยน
- `.env` — เพิ่ม `NAS_VOLUME_ROOT`, `NAS_MEDIA_ROOT`
- `.env.example` — เพิ่ม `NAS_VOLUME_ROOT`, `NAS_MEDIA_ROOT`
- `uptime-kuma/docker-compose.yml` — 1 volume line
- `homepage/docker-compose.yml` — 1 volume line + `HOMEPAGE_VAR_VOLUME_ROOT` env
- `jellyfin/docker-compose.yml` — 6 volume lines (config/cache ใช้ NAS_VOLUME_ROOT, media ใช้ NAS_MEDIA_ROOT)
- `homepage/config/widgets.yaml` — disk monitor ใช้ `{{HOMEPAGE_VAR_VOLUME_ROOT}}`

### Commits
- `9bfd6a8` refactor: centralise NAS volume root path via NAS_VOLUME_ROOT env var
- `4c2f2f0` refactor(jellyfin): split media paths to NAS_MEDIA_ROOT env var

### วิธีย้าย volume ในอนาคต
แก้ `.env` แค่ 2-3 บรรทัด แล้ว deploy:
```
NAS_VOLUME_ROOT=/volume2        # docker container data
NAS_MEDIA_ROOT=/volume1         # media library (อาจคงไว้หรือย้ายแยก)
NAS_TARGET_PATH=/volume2/docker # deploy destination
```
