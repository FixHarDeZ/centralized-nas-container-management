# hermes-agent

Autonomous AI agent for Telegram and Discord, powered by [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent). Runs on Synology NAS via Docker Compose.

LINE messaging is handled by the separate `line-secretary` stack.

## Services

| Container | Role | Port |
|---|---|---|
| `hermes-gateway` | Gateway to Telegram + Discord (outbound polling) | — |
| `hermes-dashboard` | Web UI for monitoring and config (internal only) | `9119` |
| `hermes-nginx` | Basic-auth reverse proxy for dashboard | `5063` |

## Setup

### 1. Environment variables

Copy and fill in `.env.example`:

```
cp .env.example .env
```

Edit `.env`: fill in `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `DISCORD_BOT_TOKEN`

### 2. Telegram bot

1. Message @BotFather on Telegram → `/newbot`
2. Copy the token → set as `TELEGRAM_BOT_TOKEN`
3. Find your user ID (message @userinfobot) → set as `TELEGRAM_ALLOWED_USERS`

### 3. Discord bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) → New Application
2. Bot tab → Reset Token → copy → set as `DISCORD_BOT_TOKEN`
3. OAuth2 tab → URL Generator → scope: `bot`, permissions: `Send Messages`, `Read Message History` → invite to your server

### 4. Deploy

```
scripts/deploy.sh -s hermes-agent
```

Build takes ~5 minutes on first run (clones hermes-agent + installs deps).

### 5. First-boot config

Hermes generates a default `config.yaml` on first run. To customise model or channel settings:

```
docker exec -it hermes-gateway vi /opt/data/config.yaml
docker compose restart hermes-gateway
```

### 6. Verify

```
docker logs hermes-gateway
```

Should show Telegram/Discord connected. Open dashboard at `http://<NAS_HOST>:5063`

## Dashboard

Port `5063` is now served by an internal `nginx:alpine` sidecar with HTTP Basic Auth, proxying to `hermes-dashboard:9119` (including WebSocket upgrade headers for live dashboard traffic).
Create `nginx/.htpasswd` before deploy (same format as homepage), then authenticate in the browser before accessing the dashboard.

## Updating hermes-agent

To pull a newer version, rebuild with the desired git ref:

```
docker compose -f hermes-agent/docker-compose.yml build \
  --build-arg HERMES_REF=v0.15.0 --no-cache
docker compose -f hermes-agent/docker-compose.yml up -d
```
