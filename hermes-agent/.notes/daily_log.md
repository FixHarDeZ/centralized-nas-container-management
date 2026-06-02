# Daily Log — hermes-agent

---

## 2026-06-02 — Approach A token tune (config diet)

### Trigger

mimo provider dashboard for 2026-06-02 showed 35.6M total tokens with cache hit ratio collapsed to **4%** (vs **80%** on 2026-06-01). The 35.6M spend covered what amounted to a small `docker-compose.yml` edit plus a daily-log update plus a git rebase conflict — clearly disproportionate.

### Root-cause discovery (schema verification)

Read `/opt/hermes/gateway/config.py` and `/opt/hermes/hermes_cli/config.py` `DEFAULT_CONFIG` on the running container (post-s6 migration, `HERMES_REF=v2026.5.29.2`). Findings:

- The repo template and these notes had documented `session.reset_on_idle_minutes: 60` as the idle-reset knob. **That key has never been honored.** Hermes uses `session_reset.idle_minutes` with default `1440` (24h). Live sessions have effectively never been idle-reset.
- `memory.memory_enabled` and `memory.user_profile_enabled` default to `true`, injecting ~1300 tokens of mutable content into the system prompt every turn — the primary cache-miss driver on a stable-prefix-based provider like mimo.
- `agent.image_input_mode: "text"` exists as a bonus lever to route screenshots through `vision_analyze` as text instead of sending pixels (vision tokens are uncacheable and expensive on mimo).
- Spec-guessed Tier 2 keys (`session.max_iterations`, `memory.enabled`, `tools` whitelist) do not exist under those names; renamed real keys (`agent.max_turns`, `memory.memory_enabled`) do.

Full schema map: `hermes-agent/.notes/hermes-v2026.5.16-schema.md`.

### Change

Applied seven targeted edits to `/opt/data/config.yaml` via `sed -i` (inside the `hermes_agent_data` volume; live config is a hermes-generated full dump, not a hand-written template — wholesale replacement would have lost the personalities, plugins, sessions, etc. blocks):

| Key | Before | After |
|---|---|---|
| `session_reset.idle_minutes` | 1440 | 15 |
| `agent.max_turns` | 60 | 20 |
| `agent.api_max_retries` | 3 | 1 |
| `agent.image_input_mode` | auto | text |
| `memory.memory_enabled` | true | false |
| `memory.user_profile_enabled` | true | false |
| `compression.threshold` | 0.5 | 0.80 |

Live backup at `/opt/data/config.yaml.bak-20260602` (volume-persistent).

### Deploy + verify

Repo template `hermes-agent/config.yaml.example` updated to match. Container restart via `docker compose restart hermes-gateway` initially hit an orphan s6-log lock (`Resource busy`) — fix was a full stack `down` + `up -d` which released the lock on the shared volume. After clean restart, all three containers (`hermes-gateway`, `hermes-dashboard`, `hermes-nginx`) came up healthy. YAML validated inside the container.

### Verification window

- Opens: 2026-06-02
- +24h check: 2026-06-03
- Closes: 2026-06-05

Tracker: `docs/superpowers/specs/2026-06-02-hermes-token-tuning-verification.md`.

### Escalation if targets missed

Re-enter brainstorming for Approach B (persona / prompt discipline). Do not silently tune config further beyond what is in the design spec.

---

## 2026-06-02 — Migrate Dockerfile to s6-overlay (Approach B — full upstream parity)

### งานที่ทำ

- อัปเดต `hermes-agent/Dockerfile` ให้ support s6-overlay ตาม upstream `v2026.5.29.2`:
  - Base image: `debian:bookworm-slim` → `debian:13.4` (trixie)
  - Multi-stage build: เพิ่ม `ghcr.io/astral-sh/uv:0.11.6-python3.13-trixie` และ `node:22-bookworm-slim` เป็น source stages
  - ลบ `tini` / `gosu` ออก
  - ติดตั้ง s6-overlay 3.2.3.0 พร้อม SHA256 checksum verify + multi-arch (amd64/arm64)
  - Wire `s6-rc.d/` + `cont-init.d/` จาก cloned repo
  - ติดตั้ง exec shim (`/opt/hermes/bin/hermes`) สำหรับ `docker exec` privilege drop
  - เพิ่ม `ui-tui` build + Playwright Chromium install
  - ENTRYPOINT: `["/init", "/opt/hermes/docker/main-wrapper.sh"]`, CMD: `[]`
- Bump `HERMES_REF: v2026.5.16` → `v2026.5.29.2` ใน `docker-compose.yml`
- แก้ `scripts/update-hermes.sh`: ลบ guard เดิมที่ block s6-overlay tags → กลับเป็น block pre-s6 tags แทน

### Architecture เปลี่ยนอย่างไร

- เดิม: `tini` (PID 1) → `entrypoint.sh` (gosu UID remap → exec hermes)
- ใหม่: `/init` (s6-overlay PID 1) → `cont-init.d/01-hermes-setup` (= `stage2-hook.sh` UID remap) → `main-wrapper.sh` routes CMD args → `hermes gateway run` / `hermes dashboard ...`
- Compose setup (2 containers: gateway + dashboard) ยังเหมือนเดิม — CMD args ผ่าน `main-wrapper.sh` routing เหมือนกัน

### Deploy result

- Build time: ~258s บน NAS (debian:13.4 pull + playwright chromium + web + ui-tui build)
- containers: `hermes-gateway`, `hermes-dashboard`, `hermes-nginx` ✅ Started

---

## 2026-05-30 — Fix gateway crash loop (s6-setuidgid: not found)

### Root Cause

Upstream `NousResearch/hermes-agent` migrated from gosu to **s6-overlay** sometime after `v2026.5.16`.
The new `main` branch adds `docker/stage2-hook.sh` which calls `s6-setuidgid` — but our Dockerfile installs `gosu` (not s6), so the binary doesn't exist → exit 127 → crash loop on every restart.

Note: `hermes update --force` may have triggered this earlier by pulling new upstream code into the container layer, but rebuild with `HERMES_REF=main` is what confirmed the root cause.

### Fix

Pinned `HERMES_REF: v2026.5.16` in `docker-compose.yml` — last tag that uses gosu-based entrypoint (no `stage2-hook.sh`). Rebuilt and redeployed.

To verify a tag is safe: `docker run --rm --entrypoint sh hermes-agent -c 'ls /opt/hermes/docker/stage2-hook.sh 2>/dev/null && echo EXISTS || echo NOTFOUND'` should print `NOTFOUND`.

### Upgrade path

When upgrading to a newer tag in the future, check if they've completed the s6-overlay migration and update our Dockerfile accordingly (install s6-overlay, change ENTRYPOINT to `/init`). Tags to watch: `v2026.5.28+`.

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
