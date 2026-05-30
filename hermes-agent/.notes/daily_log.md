# Daily Log — hermes-agent

---

## 2026-05-30 — Fix gateway crash loop (s6-setuidgid: not found)

### Root Cause

- `hermes update --force` was run inside the running container
- This overwrote `/opt/hermes/docker/` in the container's overlay layer with new upstream s6-overlay-based code
- The new `stage2-hook.sh` calls `s6-setuidgid` at line 196, but our image uses `gosu` (not s6-overlay) — binary not found → exit 127 → crash loop

### Fix

- `docker compose stop hermes-gateway && docker compose rm -f hermes-gateway && docker compose up -d hermes-gateway`
- Recreating the container discards the modified overlay layer and starts fresh from the clean image
- Gateway back up and stable; Discord error expected (no token configured)

### Warning

**ห้ามรัน `hermes update --force` ใน container** — มันแก้ไข code ใน container layer ทำให้ entrypoint พัง. ถ้าอยากอัพเดต ให้ rebuild image: `docker compose up -d --build hermes-gateway`

---

## 2026-05-25 — Add Nginx basic-auth sidecar for dashboard

### งานที่ทำ

- สร้าง `hermes-agent/nginx/nginx.conf` ตาม pattern เดียวกับ `homepage` โดยให้ `auth_basic "Restricted"`, proxy ไป `http://hermes-dashboard:9119` และส่ง WebSocket upgrade headers สำหรับ dashboard traffic
- สร้าง `hermes-agent/nginx/.htpasswd` ด้วย APR1 hash เดียวกับ homepage และตั้ง permission เป็น `644`
- แก้ `docker-compose.yml` ให้ `hermes-dashboard` เปิดแค่ internal `expose: 9119` และเพิ่ม service `hermes-nginx` เปิด `5063:80`
- อัปเดตเอกสาร `hermes-agent/README.md`, root `README.md`, `CLAUDE.md`, และ `hermes-agent/.notes/00_INDEX.md`

### Verification

- รัน `docker compose -f hermes-agent/docker-compose.yml config` ผ่าน
- ตรวจสอบว่า `5063` ถูก bind ที่ `hermes-nginx` และ dashboard ภายในใช้ `9119` เท่านั้น

### Notes

- ไฟล์ `.htpasswd` ไม่ถูก commit เพราะ root `.gitignore` กันไว้แล้ว
- deploy script มี logic `chmod 644` ให้ไฟล์ `nginx/.htpasswd` บน NAS อยู่แล้ว ลดปัญหา nginx อ่านไฟล์ไม่ได้

---

## 2026-05-24 — Fix model loading: HERMES_HOME + YAML structure

### Bug: "No models provided" HTTP 400 from OpenRouter

**Root cause 1 — HERMES_HOME not exported to hermes binary:**
- `entrypoint.sh` sets `HERMES_HOME=/opt/data` as local shell variable but does not export it
- `exec hermes gateway run` inherits only exported vars → hermes sees no HERMES_HOME
- `get_hermes_home()` in `hermes_constants.py` falls back to `~/.hermes` (ephemeral, per-container)
- All config reads/writes go to wrong directory, ignoring `/opt/data/config.yaml`

**Fix:** Added `HERMES_HOME=/opt/data` to `environment:` in `docker-compose.yml` for both services

**Root cause 2 — YAML structure broken in config.yaml:**
- Previous debugging session ran `sed 's/model:/model: deepseek\/deepseek-chat/'`
- This made `model:` a scalar but left `default:`, `provider:`, `base_url:` indented under it
- Invalid YAML → hermes config parser silently used empty model → HTTP 400 "No models provided"

**Fix:** Restored `model:` as mapping header, set `default: "qwen/qwen3.6-plus"`, `provider: "openrouter"`

### Deploy
- Uploaded updated `docker-compose.yml` via `tar | ssh`
- `docker compose up -d` recreated both containers
- Verified: `HERMES_HOME=/opt/data` in `docker exec env`
- Verified: `model.default = qwen/qwen3.6-plus` in `/opt/data/config.yaml`

### Status
- Gateway running ✅
- Telegram: JaFixHermesBot connected (token `8719270748:...`)
- Model: `qwen/qwen3.6-plus` via OpenRouter

---

## 2026-05-24 — Initial deploy + Telegram bot setup

### งานที่ทำ

- สร้าง Telegram bot ใหม่ JaFixHermesBot (แยกจาก line-secretary และ news-feed)
- อัปเดต `hermes-agent/.env` ด้วย token ใหม่
- Deploy stack บน NAS
- Bot รับ message ได้ + model เชื่อมต่อ OpenRouter ด้วย qwen/qwen3.6-plus
