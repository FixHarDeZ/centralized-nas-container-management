# Daily Log — hermes-agent

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
- Telegram: JaFixHermesBot connected (token `REDACTED:...`)
- Model: `qwen/qwen3.6-plus` via OpenRouter

---

## 2026-05-24 — Initial deploy + Telegram bot setup

### งานที่ทำ

- สร้าง Telegram bot ใหม่ JaFixHermesBot (แยกจาก line-secretary และ news-feed)
- อัปเดต `hermes-agent/.env` ด้วย token ใหม่
- Deploy stack บน NAS
- Bot รับ message ได้ + model เชื่อมต่อ OpenRouter ด้วย qwen/qwen3.6-plus
