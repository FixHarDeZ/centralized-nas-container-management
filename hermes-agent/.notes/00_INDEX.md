# hermes-agent Stack — Index

**สร้าง:** 2026-05-24  
**Port:** 5063 (external Nginx basic auth) → 9119 (dashboard internal)  
**Status:** Updated ✅ (2026-05-25)

---

## Architecture

Three containers in the stack:
- **hermes-gateway** — from `hermes-agent` image, runs `hermes gateway run`; connects Telegram + Discord, processes messages
- **hermes-dashboard** — from `hermes-agent` image, runs `hermes dashboard`; listens only on internal port `9119`
- **hermes-nginx** — `nginx:alpine` sidecar; exposes `5063`, enforces HTTP Basic Auth via `.htpasswd`, proxies to `hermes-dashboard:9119`

Persistent volume: `hermes_agent_data:/opt/data` — config, sessions, memories, skills, logs

---

## Configuration

| File | Location | Purpose |
|------|----------|---------|
| `config.yaml` | `/opt/data/config.yaml` (volume) | Model, provider, gateway settings |
| `.env` | `hermes-agent/.env` | API keys + bot tokens |
| `nginx/nginx.conf` | `hermes-agent/nginx/nginx.conf` | Basic auth reverse proxy to dashboard |
| `nginx/.htpasswd` | `hermes-agent/nginx/.htpasswd` | APR1 credentials file (gitignored, must exist before deploy) |

### Critical: HERMES_HOME

`HERMES_HOME=/opt/data` must be set in docker-compose.yml environment for both containers.  
Without it, hermes falls back to `~/.hermes` (ephemeral, not the volume) and loses config on restart.

### Model Config (config.yaml)

Correct YAML format — `model:` must be a **mapping** (not scalar):

```yaml
model:
  default: "qwen/qwen3.6-plus"
  provider: "openrouter"
  base_url: "https://openrouter.ai/api/v1"
```

Wrong format (breaks YAML — scalar + indented children):
```yaml
model: deepseek/deepseek-chat   # ← breaks subsequent indented keys
  default: "..."
```

---

## .env Variables

| Variable | Purpose |
|----------|---------|
| OPENROUTER_API_KEY | OpenRouter LLM access |
| TELEGRAM_BOT_TOKEN | Telegram bot token (JaFixHermesBot) |
| TELEGRAM_ALLOWED_USERS | Comma-separated allowed Telegram user IDs |
| DISCORD_BOT_TOKEN | Discord (empty = disabled) |
| HERMES_UID | Container user UID (1000) |
| HERMES_GID | Container group GID (100) |

---

## Known Gotchas

- **`HERMES_HOME` must be in docker-compose env** — entrypoint sets it locally but doesn't export to child `hermes` binary; falls back to `~/.hermes` (ephemeral) without explicit env
- **`model:` must be a mapping** — setting `model: <slug>` as scalar + indented sub-keys (default, provider) is invalid YAML; causes "No models provided" HTTP 400 from OpenRouter
- **Telegram logs success at INFO level** — only failures appear as WARNING/ERROR in docker logs; silence = success
- **Discord error is expected** — `ERROR: No bot token configured` is normal if Discord not used
- **`.htpasswd` permissions matter** — keep `nginx/.htpasswd` readable by nginx worker (`644`); deploy script already normalizes this on NAS
- **Old sessions store model per-session** — sessions created before config fix have empty model; new sessions use config

---

## Change Log

| วันที่ | เรื่อง |
|--------|--------|
| 2026-05-25 | Add `nginx:alpine` basic-auth sidecar on port 5063, dashboard moved to internal `9119` only |
| 2026-05-24 | สร้าง stack, deploy, new Telegram bot JaFixHermesBot |
| 2026-05-24 | Fix model config: add HERMES_HOME to compose env, fix YAML structure, set qwen/qwen3.6-plus |
