# Daily Log

---

---

## 2026-05-23 (ช่วงที่ 4) — auth stack: Authelia SSO + Vaultwarden + migrate homepage/maid-tracker

### งานที่ทำ

**สร้าง `auth/` stack ใหม่ (Authelia + Vaultwarden):**
- `auth/docker-compose.yml` — 2 services: Authelia (SSO portal + forward-auth, port 9091) + Vaultwarden (Bitwarden-compatible vault, port 8222)
- สร้าง Docker bridge network `auth_net` ที่ stack อื่น join ผ่าน `external: true`
- `auth/authelia/configuration.yml` — Authelia v4.38+ config, `default_policy: deny` (fail-closed)
- `auth/authelia/users_database.yml` — admin user skeleton + Argon2 password placeholder
- `auth/.env.example` — AUTHELIA_SESSION_SECRET, AUTHELIA_STORAGE_ENCRYPTION_KEY, AUTHELIA_JWT_SECRET, VAULTWARDEN_ADMIN_TOKEN
- Watchtower disabled บนทั้ง 2 services

**Migrate homepage → Authelia forward-auth:**
- ลบ `command:` block (htpasswd) ออกจาก nginx service
- nginx join `auth_net` เพื่อเข้าถึง authelia container
- `nginx.conf` แทน `auth_basic` block ด้วย `auth_request /authelia` + `error_page 401 =302 http://<NAS_HOST>:9091`
- ลบ `NGINX_BASIC_AUTH_*` ออกจาก `.env.example`

**Migrate maid-tracker → Authelia forward-auth:**
- เพิ่ม nginx sidecar (`maid-nginx`) — port 5055:80 พร้อม forward-auth
- maid-tracker app เปลี่ยน `ports: "5055:8000"` → `expose: "8000"` (ไม่เปิด host โดยตรงอีกต่อไป)
- สร้าง `maid-tracker/nginx/nginx.conf` ด้วย pattern เดียวกับ homepage

**อื่นๆ:**
- เพิ่ม `auth` ใน `scripts/deploy.sh` ALL_STACKS (ต้องรันก่อน stack อื่น เพราะสร้าง `auth_net`)
- อัปเดต `CLAUDE.md`, `README.md`, `homepage/README.md`, `maid-tracker/README.md`

### ขั้นตอนถัดไปก่อน deploy

1. `cp auth/.env.example auth/.env` แล้วเติม secrets จริง
2. แทน `<NAS_HOST>` ใน `auth/authelia/configuration.yml`, `homepage/nginx/nginx.conf`, `maid-tracker/nginx/nginx.conf`
3. Generate Argon2 hash จริง: `docker run --rm authelia/authelia:latest authelia crypto hash generate argon2 --password 'YOUR_PASS'`
4. ใส่ hash ใน `auth/authelia/users_database.yml`
5. Deploy `auth` ก่อน แล้วค่อย redeploy `homepage` + `maid-tracker`

---

## 2026-05-23 — hermes-agent stack + line-secretary Telegram cleanup

- สร้าง `hermes-agent/` stack: containerize official NousResearch/hermes-agent
  - 2 services: `hermes-gateway` (Telegram + Discord, outbound polling) + `hermes-dashboard` (port 5063)
  - Dockerfile clones repo from GitHub at build time (ARG HERMES_REF=main, pinnable to tag)
  - UID 10000 inside container, remapped to 1000/100 (Synology admin) at runtime via gosu
  - Ports 5060/5061 blocked by browsers (SIP) → ใช้ port 5063 แทน
- Strip Telegram จาก `line-secretary` (3 commits):
  - ลบ TELEGRAM_* fields จาก config.py
  - ลบ import, lifespan call, _push_tg, /webhook/telegram, handle_telegram_message จาก main.py
  - ลบ telegram_client.py + อัปเดต .env.example
  - line-secretary เหลือแค่ LINE-only

---

## 2026-05-23 (ช่วงที่ 3) — Debug & deploy Telegram bot (line-secretary)

### งานที่ทำ
- Debug ว่าทำไม `/start` bot เงียบ → root cause: โค้ด Telegram ทั้งหมด local ยังไม่ได้ commit/deploy
- Router port forward 8443 → NAS 192.168.50.200 (Synology RP รับต่อไป localhost:5057)
- Commit รวม feat(telegram) ทั้งหมด → deploy `line-secretary` + `watchtower`

### Key Learnings
- Telegram webhook ต้องการ internet → NAS path: `router:8443 → NAS:8443 (RP) → localhost:5057`
- Telegram allowed ports: 443, 80, 88, 8443 เท่านั้น

---

## 2026-05-23 (ช่วงที่ 2) — Telegram support: watchtower + line-secretary

### งานที่ทำ

#### 1. Watchtower notifier — เพิ่ม Telegram
- เพิ่ม `send_telegram()` + `notify()` helper ใน `notifier.py`
- `notify()` ส่งทั้ง LINE และ Telegram พร้อมกันทุก event (session start, update, done, error)
- Token ใช้ bot เดียวกับ TorrentWatch (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`)

#### 2. Line-secretary — เพิ่ม Telegram bot webhook
- สร้าง `telegram_client.py` — `send()` แบบ async + `set_webhook()` register กับ Telegram
- อัปเดต `config.py` เพิ่ม `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_ALLOWED_CHAT_IDS`
- เพิ่ม `/webhook/telegram` endpoint ใน `main.py` — รับข้อความจาก Telegram แล้วผ่าน agent เดิมทั้งหมด (note flow, pending confirm, history, LLM)
- Startup `lifespan` เรียก `set_webhook()` อัตโนมัติถ้า token + URL ตั้งค่าไว้
- Webhook URL ต้องเป็น port 443/80/88/8443 เท่านั้น (Telegram limitation) → ใช้ port 8443

#### 3. Fix deploy.sh — .env upload bug
- บน macOS bsdtar `--exclude='./.env'` match `.env` ทุก level ไม่ใช่แค่ root
- แก้: exclude `.env` จาก tar ทั้งหมด แล้ว upload per-stack `.env` แยกชัดเจนหลัง tar extract
- ทุก stack `.env` ถูก push ขึ้น NAS อย่างถูกต้องและตรวจสอบได้

### ไฟล์ที่เปลี่ยน
- `watchtower/notifier/notifier.py`
- `watchtower/.env`, `watchtower/.env.example`
- `line-secretary/telegram_client.py` (ใหม่)
- `line-secretary/config.py`, `line-secretary/main.py`
- `line-secretary/.env`, `line-secretary/.env.example`
- `scripts/deploy.sh` (fix bsdtar .env exclude + per-stack upload)

### Setup ที่ต้องทำบน NAS (one-time)
- Synology RP: `https://<NAS_HOST>:8443` → `http://localhost:5057` (line-secretary Telegram webhook)

### สถานะ
- Watchtower Telegram ✅ ทำงานแล้ว
- Line-secretary Telegram webhook ✅ registered (HTTP 200) — รอ user ทดสอบ

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
