# ops-bot

AI-powered incident response bot. Receives alerts from Uptime Kuma, auto-diagnoses via SSH, analyzes with LLM (mimo-v2.5-pro), and notifies Telegram with fix suggestions.

## Services

| Component | Role | Port |
|---|---|---|
| ops-bot | FastAPI webhook + Telegram bot + dashboard | 8000 (internal only) |
| ops-bot-nginx | Basic-auth reverse proxy | 5070 → 80 |

## Features

- **Auto-diagnose**: SSH into NAS host, run container/system diagnostics (read-only)
- **LLM Analysis**: mimo-v2.5-pro analyzes root cause (Thai language)
- **Telegram**: InlineKeyboard for log inspection
- **Commands**: `/status`, `/diagnose <service>`, `/logs <service> [lines]`
- **Watchtower**: Grace period 5 min after image updates (skip alerts during update)
- **Debounce**: 15 min cooldown between repeated alerts for the same service
- **Dashboard**: Web UI at `/dashboard` for incident history

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

Uses mimo-v2.5-pro via Xiaomi subscription:

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
Configure, and forward TCP `15070` on the router. Verify from the NAS shell —
`https://localhost:15070` always 404s because DSM's generated block starts with
`if ($host !~ "^<NAS_DOMAIN>$") { return 404; }`, so pass the real hostname:

```bash
curl -s --resolve <NAS_DOMAIN>:15070:127.0.0.1 \
  -u '<user>:<pass>' -o /dev/null -w '%{http_code}\n' \
  https://<NAS_DOMAIN>:15070/dashboard
```

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
- Watchtower label disables self-update
- Fix-as-PR uses GitHub fine-grained PAT with minimal scopes (this repo only)
