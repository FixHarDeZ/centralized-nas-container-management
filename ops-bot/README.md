# ops-bot

AI-powered incident response bot. Receives alerts from Uptime Kuma, auto-diagnoses via SSH, analyzes with a selectable MiMo model (default: mimo-v2.5-pro), and notifies Telegram with fix suggestions.

## Services

| Component | Role | Port |
|---|---|---|
| ops-bot | FastAPI webhook + Telegram bot + dashboard | 8000 (internal only) |
| ops-bot-nginx | Basic-auth reverse proxy | 5070 → 80 |

## Features

- **Auto-diagnose**: SSH into NAS host, run container/system diagnostics (read-only)
- **LLM Analysis**: selectable MiMo model analyzes root cause in Thai; model recorded per report
- **Telegram**: InlineKeyboard for log inspection
- **Commands**: `/status`, `/diagnose <service>`, `/logs <service> [lines]`
- **Watchtower**: Grace period 5 min after image updates (skip alerts during update)
- **Debounce**: 15 min cooldown between repeated alerts for the same service
- **Dashboard**: responsive overview, search by service/container, severity filters, and paginated incident history
- **AI Settings**: `/dashboard/settings` changes the analysis model without a restart; persistent override with reset to environment default

## Setup

### 1. Telegram Bot

1. Message @BotFather → `/newbot`
2. Copy token → vault key `stacks.ops_bot.telegram.bot_token`
3. Find chat ID → vault key `stacks.ops_bot.telegram.chat_id`

### 2. SSH Access (Key-based)

Bot SSHes into NAS host using an SSH key (not password). Set in vault:

- `stacks.ops_bot.ssh.host` — NAS IP
- `stacks.ops_bot.ssh.user` — SSH username
- `stacks.ops_bot.ssh.port` — SSH port (e.g. `2222`, default `22`)

Mount your SSH private key via docker-compose volume — host path comes from
`HOST_SSH_KEY_PATH` in `.env`; inside the container it is always
`/app/data/ssh/id_ed25519`.

**Sudoers prerequisite (one-time, on the NAS):** the SSH user's non-login shell
has no `/usr/local/bin` in PATH and `docker.sock` is root-only, so the bot runs
docker as `sudo -n /usr/local/bin/docker ...`. This requires a NOPASSWD entry:

```
# /etc/sudoers.d/ops-bot-docker  (mode 440)
<NAS_USER> ALL=(root) NOPASSWD: /usr/local/bin/docker
```

Read-only safety is enforced app-side by the command whitelist in
`app/ssh_client.py` (no restart/exec/rm ever reaches sudo).

### 3. LLM

Uses Xiaomi MiMo through the configured OpenAI-compatible endpoint (default model: `mimo-v2.5-pro`):

- `stacks.ops_bot.mimo_api_key` — API key
- `stacks.ops_bot.mimo_base_url` — Base URL

### 4. Dashboard Auth

Basic auth lives in the nginx sidecar, not the app. Credentials come from vault:

- `stacks.ops_bot.dashboard.basic_auth_user` — username
- `stacks.ops_bot.dashboard.basic_auth_password` — password

`make secrets` renders them into `.env`; `nginx/.htpasswd` is generated from
there (gitignored, regenerate on a fresh clone):

```bash
cd ops-bot
U=$(awk -F= '/^DASHBOARD_BASIC_AUTH_USER=/{print $2}' .env)
P=$(awk -F= '{if(/^DASHBOARD_BASIC_AUTH_PASSWORD=/){sub(/^[^=]*=/,"");print}}' .env)
printf '%s:%s\n' "$U" "$(openssl passwd -apr1 "$P")" > nginx/.htpasswd
chmod 644 nginx/.htpasswd
```

### 5. Webhook Security

`/webhook/uptime-kuma` is the one path nginx leaves open — Uptime Kuma's webhook
notification can't send basic auth. It is guarded by a shared secret instead:

- `stacks.ops_bot.kuma_webhook_secret` — shared secret (query param `?secret=...`)

Keep this key non-empty. With it unset, `_verify_secret()` allows every caller,
and the open path lets anyone forge incidents (SSH diagnostics + LLM spend).

nginx exempts that path with an **exact match** (`location = /webhook/uptime-kuma`).
The query string is not part of location matching, so `?secret=...` is fine — but a
URL with a trailing slash falls through to `location /` and 401s silently. Relax to
a prefix match if Kuma's stored URL ever gains one.

**Rotating the secret:** Uptime Kuma has no API for notification config — the URL
lives only inside a JSON blob in `kuma.db`. Stop the container, back the DB up, then
`UPDATE notification SET config = replace(config, 'secret=<old>', 'secret=<new>')
WHERE name='ops-bot';`, restart, and update the vault key in the same pass. The secret
travels in a query param, so it also lands in DSM's reverse-proxy access log in
cleartext — treat it as rotatable, not permanent.

### 6. Deploy

```bash
# Add vault keys first
make edit-vault
# Render .env
make secrets
# Deploy
scripts/deploy.sh -s ops-bot
```

### 7. Uptime Kuma Setup

1. Open Uptime Kuma → Settings → Notifications
2. Add Notification → Webhook
3. URL: `http://<NAS_IP>:5070/webhook/uptime-kuma?secret=<KUMA_WEBHOOK_SECRET>`
4. Method: POST

### 7b. External Access (DSM Reverse Proxy)

Control Panel → Login Portal → Advanced → Reverse Proxy:

| Field | Value |
|---|---|
| Source | HTTPS · `<NAS_DOMAIN>` · port `15070` |
| Destination | HTTP · `localhost` · port `5070` |

Then bind a certificate covering `<NAS_DOMAIN>` in Security → Certificate →
Configure. Reuse the existing wildcard/host cert that friendly-reminder already
uses for the same hostname — do **not** let DSM auto-issue a new one per RP entry
(a stray `ReverseProxy_<hash>` cert issued against a misspelled hostname is dead
weight and will never validate). Forward TCP `15070` on the router. Verify from
the NAS shell —
`https://localhost:15070` always 404s because DSM's generated block starts with
`if ($host !~ "^<NAS_DOMAIN>$") { return 404; }`, so pass the real hostname:

```bash
curl -s --resolve <NAS_DOMAIN>:15070:127.0.0.1 \
  -u '<user>:<pass>' -o /dev/null -w '%{http_code}\n' \
  https://<NAS_DOMAIN>:15070/dashboard
```

### 7c. Homepage Tile

The tile lives under "📥 Downloads & Monitoring" in `homepage/config/services.yaml`
with a plain `href` and no `ping`/`siteMonitor` widget: every path is behind basic
auth, so any probe gets a 401 and the tile renders permanently red.

### 8. Service-Container Mapping

Edit `SERVICE_CONTAINER_MAP` in `app/webhook.py` to map Uptime Kuma service names to Docker container names.

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/status` | แสดงสถานะ container ทั้งหมด |
| `/diagnose <service>` | manual trigger diagnostics |
| `/logs <container> [lines]` | ดู container logs (default 50, max 200) |

## Architecture

```
Uptime Kuma → POST /webhook/uptime-kuma
  → debounce check (15 min)
  → watchtower grace check (5 min)
  → SSH diagnostics (read-only commands)
  → LLM analysis (mimo-v2.5-pro)
  → Telegram notification + InlineKeyboard
  → SQLite incident record
```

## Fix-as-PR

When an incident diagnosis is complete, the bot offers `🔧 เปิด PR` buttons in Telegram for proposed config or source fixes. Tapping a button:

1. Creates a new Git branch from `main`
2. Commits the suggested file changes
3. Opens a pull request on GitHub (via REST API)
4. Sends the PR URL back to Telegram

A human reviews, merges, and deploys with:
```bash
make secrets
./scripts/deploy.sh -s <stack>
```

**Read-only guarantee:** The bot never executes fixes on the NAS — it only proposes them as PRs. All changes are staged in Git and require human approval before any deployment.

### Vault Configuration

Fix-as-PR requires two GitHub secrets:

- `stacks.ops_bot.github.token` — fine-grained personal access token with scopes:
  - `contents:write` (commit + branch creation)
  - `pull_requests:write` (PR creation)
  - Limited to this repository only
- `stacks.ops_bot.github.repo` — GitHub repo in format `<owner>/<repo>` (e.g., `FixHarDeZ/centralized-nas-container-management`)

Add these via `make edit-vault`, then `make secrets && ./scripts/deploy.sh -s ops-bot`.

## Security

- SSH commands are whitelisted (read-only: `docker ps`, `docker logs`, `df`, `free`, etc.)
- Dashboard + everything except the Kuma webhook path is behind nginx basic auth
  (`nginx/.htpasswd`); the app itself is never published on the host
- `/webhook/uptime-kuma` is exempt from basic auth and guarded by
  `KUMA_WEBHOOK_SECRET` (constant-time compare) — required before exposing 5070
- The `ops-bot` app container carries the watchtower-disable label; the nginx
  sidecar deliberately does **not** — it runs `nginx:alpine` and should keep
  receiving security patches
- Fix-as-PR uses GitHub fine-grained PAT with minimal scopes (this repo only)

## Dashboard and model settings

Open `/dashboard` through the existing nginx basic-auth proxy. Overview cards
summarize **historical incidents**, not live outages: recovery currently only
sends a Telegram notification and does not update incident status in SQLite.
Search matches service/container text literally; severity filtering uses the
latest analysis, with 25 incidents per page. Details show evidence, suggested
fixes, model provenance, token usage, collapsible diagnostic logs and actions.
Older reports without model provenance display “ไม่ได้บันทึกไว้”.

In **AI Settings** (`/dashboard/settings`):

1. Select a model, or enter its exact Model ID. **ดึงรายชื่อโมเดล** calls the
   configured provider's `/models` endpoint with a 10-second timeout. Endpoints
   that do not expose model discovery can still use manual Model IDs.
2. Click **บันทึกการตั้งค่า**. The override is saved in SQLite `settings`, key
   `mimo_model`, in the existing data volume. No restart or environment edit.
3. **คืนค่าเริ่มต้น** deletes the override; `MIMO_MODEL` (or its application
   default) becomes effective again. Subsequent environment changes only affect
   the active model when no dashboard override exists.

Saving validates ID syntax, **not provider availability or model capability**.
Choose a model supported by the configured endpoint/account and compatible with
function calling and `reasoning_effort=low`. API keys and endpoint configuration
remain managed via vault/deployment; the dashboard does not expose/edit them.

Each diagnosis snapshots its model once; a settings change never switches models
mid-run. All resulting reports include `model_used` in `analyses.report_json`.
The agent loop has a 600-second overall `asyncio.wait_for` deadline and a 10-round
cap, disables implicit SDK retries, uses `reasoning_effort=low`, and does not send
`max_tokens`. Timeout reports retain already-received token counts and findings
(tokens from an unfinished provider response are unavailable).

Settings writes are `POST /dashboard/settings` with JSON `{ "model": "..." }`
(or `null` to reset), a same-host HTTP(S) `Origin`, and `X-Ops-Settings: 1`.
Browser cross-origin requests cannot pass the custom-header preflight; no CORS
allowlist is configured. These checks supplement **nginx basic auth**, not replace
it. Keep the app port internal. Model discovery is `GET /dashboard/api/models`.

## Suggested next improvements

1. **Persist incident lifecycle:** record recovery timestamps and distinguish
   open/resolved incidents before adding live outage counts or time-to-recovery.
2. **Durable diagnosis state:** queued/running/completed/failed, start/end times,
   and restart recovery. Current background tasks do not survive container restarts.
3. **Re-analyze from dashboard:** explicit action with duplicate-run protection,
   immutable analysis versions and comparison of findings/models/tokens.
4. **Group recurring incidents:** persistent debounce and recurring-cause history
   by service; prioritize services that repeatedly fail instead of expanding alerts.

## Verification

```bash
cd ops-bot
.venv/bin/python -m pytest tests -q
```

Tests isolate rendered `.env`, use temporary SQLite databases and mock external
providers/SSH/Telegram. Dashboard model save/reset, validation, cross-origin
rejection, model discovery failure, history pagination, legacy reports, per-run
model snapshot and overall deadline cancellation have regression coverage.
