# ops-bot

AI-powered incident response bot. Receives alerts from Uptime Kuma, auto-diagnoses via SSH, analyzes with LLM (mimo-v2.5-pro), and notifies Telegram with fix suggestions.

## Services

| Component | Role | Port |
|---|---|---|
| ops-bot | FastAPI webhook + Telegram bot + dashboard | 5070 |

## Features

- **Auto-diagnose**: SSH into NAS, run container/system diagnostics
- **LLM Analysis**: mimo-v2.5-pro analyzes root cause (Thai language)
- **Telegram**: InlineKeyboard for fix/restart confirmation
- **Commands**: `/status`, `/diagnose <service>`, `/logs <service>`
- **Watchtower**: Grace period 5 min after image updates
- **Dashboard**: Web UI at `/dashboard` for incident history

## Setup

### 1. Telegram Bot

1. Message @BotFather → `/newbot`
2. Copy token → vault key `stacks.ops_bot.telegram.bot_token`
3. Find chat ID → vault key `stacks.ops_bot.telegram.chat_id`

### 2. SSH Access

Bot SSHes into NAS host. Set in vault:
- `stacks.ops_bot.ssh.host` — NAS IP
- `stacks.ops_bot.ssh.user` — SSH username
- `stacks.ops_bot.ssh.password` — SSH password (or use SSH key)

### 3. LLM

Uses mimo-v2.5-pro via Xiaomi subscription:
- `stacks.ops_bot.mimo_api_key` — API key
- `stacks.ops_bot.mimo_base_url` — Base URL

### 4. Deploy

```bash
scripts/deploy.sh -s ops-bot
```

### 5. Uptime Kuma Setup

1. Open Uptime Kuma → Settings → Notifications
2. Add Notification → Webhook
3. URL: `http://<NAS_IP>:5070/webhook/uptime-kuma`
4. Method: POST

### 6. Service-Container Mapping

Edit `SERVICE_CONTAINER_MAP` in `app/webhook.py` to map Uptime Kuma service names to Docker container names.

## Telegram Commands

| Command | Description |
|---------|-------------|
| `/status` | แสดงสถานะ container ทั้งหมด |
| `/diagnose <service>` | manual trigger diagnostics |
| `/logs <container> [lines]` | ดู container logs (default 50) |
