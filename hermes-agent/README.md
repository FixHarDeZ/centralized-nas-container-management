# hermes-agent

Autonomous AI agent for Telegram and Discord, powered by [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent). Runs on Synology NAS via Docker Compose.

LINE messaging is handled by the separate `line-secretary` stack.

## Services

| Container | Role | Port |
|---|---|---|
| `hermes-gateway` | Gateway to Telegram + Discord (outbound polling) | — |
| `hermes-dashboard` | Web UI for monitoring + config | `5063` |

Dashboard has built-in basic auth (username/password configured via vault).

## Setup

### 1. Environment variables

Secrets are managed via `secrets/vault.sops.yaml` (sops+age encrypted). Run `make secrets` to generate `.env`.

Required vault keys under `stacks.hermes_agent`:
- `openrouter_api_key` — OpenRouter LLM access
- `telegram.bot_token` — Telegram bot token
- `telegram.allowed_users` — Comma-separated allowed user IDs
- `dashboard.basic_auth_user` — Dashboard login username
- `dashboard.password_hash` — scrypt hash of dashboard password
- `dashboard.basic_auth_password` — Plaintext password (for reference only)

### 2. Telegram bot

1. Message @BotFather on Telegram → `/newbot`
2. Copy the token → set as `TELEGRAM_BOT_TOKEN`
3. Find your user ID (message @userinfobot) → set as `TELEGRAM_ALLOWED_USERS`

### 3. Discord bot (optional)

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
docker compose -f hermes-agent/docker-compose.yml restart hermes-gateway
```

### 6. Verify

```
docker logs hermes-gateway
```

Should show Telegram/Discord connected. Open dashboard at `http://<NAS_HOST>:5063`

## Dashboard Auth

Since v2026.7.1, hermes requires auth providers when binding to non-loopback addresses. The stack uses a wrapper script (`scripts/inject-dashboard-auth.sh`) that reads `DASHBOARD_PASSWORD_HASH` from env vars and injects `dashboard.basic_auth` into `config.yaml` before startup.

Login credentials are stored in `secrets/vault.sops.yaml`.

## Updating hermes-agent

To pull a newer version, update `HERMES_REF` in `docker-compose.yml`:

```
docker compose -f hermes-agent/docker-compose.yml build --no-cache
docker compose -f hermes-agent/docker-compose.yml up -d
```
