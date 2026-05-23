# hermes-agent Stack Design

**Date:** 2026-05-23  
**Status:** Approved  
**Scope:** New Docker Compose stack for autonomous AI agent (Telegram + Discord)

---

## Overview

Add a `hermes-agent/` stack that containerizes the official [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) on the Synology NAS. The stack replaces `line-secretary`'s Telegram integration; `line-secretary` remains active for LINE messaging only.

---

## Architecture

### Services

| Service | Role | Port | Command |
|---|---|---|---|
| `hermes-gateway` | Outbound gateway to Telegram + Discord (polling) | none | `gateway run` |
| `hermes-dashboard` | Web UI for monitoring and configuration | `5060:9119` | `dashboard --host 0.0.0.0 --no-open` |

Both services share a single `hermes-agent` Docker image built from the same `Dockerfile`.

### Data Flow

```
Telegram API ←→ hermes-gateway ←→ LLM (OpenRouter)
Discord API  ←→ hermes-gateway ←→ /opt/data (skills, sessions, memory)
                      ↕
              hermes-dashboard (port 5060, read/write /opt/data)
```

### Volume

`hermes_agent_data` → `/opt/data` inside container

```
/opt/data/
├── config.yaml       ← agent configuration (model, channel settings)
├── .env              ← hermes internal env (populated from container env)
├── sessions/         ← conversation history
├── skills/           ← auto-generated and user-defined skills
└── logs/             ← runtime logs
```

---

## File Structure

```
hermes-agent/
├── Dockerfile
├── docker-compose.yml
├── .env.example
├── config.yaml.example
└── README.md
```

---

## Dockerfile

Single-stage build from `debian:bookworm-slim`. Clones `NousResearch/hermes-agent` at build time using `ARG HERMES_REF=main` (pinnable to a tag).

Key steps:
1. Install system deps: `git`, `curl`, `python3`, `nodejs`, `npm`, `ffmpeg`, `tini`, `ripgrep`
2. Install `uv` via pip
3. `git clone --depth 1 https://github.com/NousResearch/hermes-agent /opt/hermes`
4. `uv sync --extra messaging` — Python deps for Telegram/Discord/WhatsApp gateways
5. `npm ci && npm run build` — dashboard frontend assets
6. Create `hermes` user with `UID=1000 / GID=100` (Synology admin mapping)
7. Entrypoint: `/opt/hermes/docker/entrypoint.sh` wrapped by `tini`

> Build requires internet access. Change `HERMES_REF=main` to a version tag (e.g. `v0.14.0`) to pin the version.

---

## Environment Variables (`.env.example`)

```
# LLM Provider
OPENROUTER_API_KEY=

# Telegram
TELEGRAM_BOT_TOKEN=
TELEGRAM_ALLOWED_USERS=      # comma-separated user IDs; blank = allow all

# Discord
DISCORD_BOT_TOKEN=
DISCORD_ALLOWED_GUILDS=      # optional: restrict to specific server IDs

# Container UID/GID (Synology admin = 1000/100)
HERMES_UID=1000
HERMES_GID=100
```

---

## Agent Configuration (`config.yaml.example`)

```yaml
model: nous/hermes-3-405b    # or openai/gpt-4o, anthropic/claude-opus-4-6
provider: auto

telegram:
  reply_to_mode: first
  disable_link_previews: true

discord:
  require_mention: true      # must @hermes in servers; DMs work without mention
  auto_thread: true
```

Bootstrap: copy `config.yaml.example` into the named volume path before first boot, or let hermes generate defaults on first run.

---

## Integration with Existing Stacks

### line-secretary changes
- Remove `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_ALLOWED_CHAT_IDS` from `line-secretary/.env`
- Remove Telegram webhook registration and handler from `line-secretary` code
- `line-secretary` retains: LINE webhook, Notion tools, Groq/OpenRouter LLM

### CLAUDE.md Stacks Table
Add row:

| `hermes-agent/` | Autonomous AI Agent (Telegram + Discord) | 5060 (dashboard) | Build clones `NousResearch/hermes-agent` from GitHub. Copy `config.yaml.example` into volume before first boot. |

---

## First-Boot Checklist

1. `cp hermes-agent/.env.example hermes-agent/.env` → fill in API keys
2. `deploy.sh -s hermes-agent` → upload and build on NAS (build takes ~5 min)
3. Start once with `docker compose up hermes-gateway` — hermes generates default `config.yaml` in the named volume on first run
4. Customize model/channels: `docker exec -it hermes-gateway vi /opt/data/config.yaml` (or copy via `docker cp`)
5. Restart: `docker compose restart hermes-gateway`
6. Verify: `docker logs hermes-gateway` → should show Telegram/Discord connected
7. Open dashboard: `http://<NAS_HOST>:5060`

---

## Constraints & Gotchas

- **No LINE support** — hermes-agent gateway does not implement LINE. `line-secretary` handles LINE.
- **Build needs internet** — `git clone` at build time; NAS must reach `github.com`
- **`network_mode: host` dropped** — official compose uses host networking; we use bridge with explicit port `5060:9119` to avoid Synology system port conflicts
- **UID mapping** — official default is `10000:10000`; changed to `1000:100` to match Synology admin user so volume files remain readable on the host
- **Dashboard security** — port 5060 is LAN-accessible without auth; do not expose to WAN without adding Nginx + basic auth (same pattern as `maid-tracker`)
