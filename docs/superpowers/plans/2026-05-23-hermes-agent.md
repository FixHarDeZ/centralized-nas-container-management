# hermes-agent Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `hermes-agent/` Docker Compose stack (official NousResearch/hermes-agent, Telegram + Discord) and strip Telegram code from `line-secretary` so it handles LINE only.

**Architecture:** New stack clones hermes-agent from GitHub at build time; two services (`hermes-gateway` + `hermes-dashboard`). `line-secretary` is trimmed to LINE-only (removes `telegram_client.py`, Telegram fields in config, and the `/webhook/telegram` endpoint + handler).

**Tech Stack:** debian:bookworm-slim, Python 3 + uv, Node.js 22, Docker Compose, FastAPI (line-secretary, existing)

---

## File Map

**Create:**
- `hermes-agent/Dockerfile`
- `hermes-agent/docker-compose.yml`
- `hermes-agent/.env.example`
- `hermes-agent/config.yaml.example`
- `hermes-agent/README.md`

**Modify:**
- `line-secretary/config.py` — remove 3 Telegram fields + `allowed_telegram_chat_ids` property
- `line-secretary/main.py` — remove `import telegram_client`, lifespan webhook call, `_push_tg()`, `/webhook/telegram` endpoint, `handle_telegram_message()`
- `line-secretary/.env.example` — remove Telegram section
- `CLAUDE.md` — add hermes-agent row, update line-secretary row
- `README.md` (root) — add hermes-agent row, update env vars section

**Delete:**
- `line-secretary/telegram_client.py`

---

## Task 1: Verify line-secretary baseline tests pass

**Files:** (read-only)

- [ ] **Step 1: Run existing tests**

```bash
cd line-secretary
pip install -r requirements.txt -q
pytest tests/ -v
```

Expected: all tests PASS. If any fail, stop and investigate before proceeding.

- [ ] **Step 2: Commit checkpoint**

No changes yet — this is baseline only. Note the number of tests passing.

---

## Task 2: Strip Telegram from line-secretary/config.py

**Files:**
- Modify: `line-secretary/config.py`

- [ ] **Step 1: Remove the three Telegram fields and `allowed_telegram_chat_ids` property**

Replace the entire file with:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    LINE_SECRETARY_CHANNEL_SECRET: str
    LINE_SECRETARY_CHANNEL_ACCESS_TOKEN: str
    LINE_SECRETARY_ALLOWED_USER_IDS: str  # comma-separated LINE user IDs
    NOTION_TOKEN: str

    # AI provider: "auto" (Groq primary + OpenRouter fallback), "groq", or "openrouter"
    AI_PROVIDER: str = "auto"
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""

    NOTION_QUICK_NOTE_PAGE_ID: str = ""

    DATA_DIR: str = "/data"

    model_config = SettingsConfigDict(extra="ignore")

    @property
    def allowed_user_ids(self) -> set[str]:
        return {uid.strip() for uid in self.LINE_SECRETARY_ALLOWED_USER_IDS.split(",")}


settings = Settings()
```

- [ ] **Step 2: Run tests to verify nothing broke**

```bash
cd line-secretary
pytest tests/ -v
```

Expected: same number of tests PASS as baseline.

---

## Task 3: Strip Telegram from line-secretary/main.py

**Files:**
- Modify: `line-secretary/main.py`

- [ ] **Step 1: Remove `import telegram_client` (line 11)**

Change the imports block from:
```python
import agent
import line_client
import notion as notion_mod
import provider as _provider
import store
import telegram_client
from cache import cache as _cache
from config import settings
```
To:
```python
import agent
import line_client
import notion as notion_mod
import provider as _provider
import store
from cache import cache as _cache
from config import settings
```

- [ ] **Step 2: Remove Telegram webhook registration from `lifespan()`**

Change:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init(settings.DATA_DIR)
    _cache.init(settings.NOTION_TOKEN)
    _cache.start()
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_WEBHOOK_URL:
        await telegram_client.set_webhook(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_WEBHOOK_URL)
    yield
```
To:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init(settings.DATA_DIR)
    _cache.init(settings.NOTION_TOKEN)
    _cache.start()
    yield
```

- [ ] **Step 3: Remove `_push_tg()` helper**

Delete this function entirely (it is between `_push_long` and the `# ── Webhook ──` comment):
```python
async def _push_tg(chat_id: str, text: str) -> None:
    await telegram_client.send(chat_id, text, settings.TELEGRAM_BOT_TOKEN)
```

- [ ] **Step 4: Remove `/webhook/telegram` endpoint**

Delete this entire endpoint + handler (lines 91–283 in original):
```python
@app.post("/webhook/telegram")
async def webhook_telegram(request: Request, background_tasks: BackgroundTasks):
    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=404)
    update = await request.json()
    msg = update.get("message") or update.get("edited_message")
    if msg and msg.get("text"):
        background_tasks.add_task(handle_telegram_message, msg)
    return {"status": "ok"}


async def handle_telegram_message(msg: dict) -> None:
    # ... entire function body (~180 lines) ...
```

The file should end at `handle_non_text_message()` and `handle_message()` (LINE handlers — keep those).

- [ ] **Step 5: Run tests**

```bash
cd line-secretary
pytest tests/ -v
```

Expected: same PASS count as baseline.

---

## Task 4: Delete telegram_client.py and update .env.example

**Files:**
- Delete: `line-secretary/telegram_client.py`
- Modify: `line-secretary/.env.example`

- [ ] **Step 1: Delete the file**

```bash
rm line-secretary/telegram_client.py
```

- [ ] **Step 2: Write new .env.example without Telegram section**

Replace `line-secretary/.env.example` with:

```
# Line Secretary stack — AI LINE Bot + Notion tools
# Copy to .env and fill in real values

# ─── LINE Messaging API (Line Secretary channel) ─────────────────────────────
LINE_SECRETARY_CHANNEL_SECRET=
LINE_SECRETARY_CHANNEL_ACCESS_TOKEN=
# Comma-separated list of allowed LINE user IDs
LINE_SECRETARY_ALLOWED_USER_IDS=

# ─── AI Provider ─────────────────────────────────────────────────────────────
# "auto" → Groq primary, OpenRouter fallback when rate-limited
# "groq" → Groq only
# "openrouter" → OpenRouter only
AI_PROVIDER=auto

# Groq — free at console.groq.com
GROQ_API_KEY=

# OpenRouter — supports Claude, GPT, Llama, etc.
OPENROUTER_API_KEY=

# ─── Notion ──────────────────────────────────────────────────────────────────
# Internal Integration Token from notion.so/my-integrations
NOTION_TOKEN=
NOTION_QUICK_NOTE_PAGE_ID=
```

- [ ] **Step 3: Run tests one final time**

```bash
cd line-secretary
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 4: Commit line-secretary cleanup**

```bash
git add line-secretary/config.py line-secretary/main.py \
        line-secretary/.env.example
git rm line-secretary/telegram_client.py
git commit -m "refactor(line-secretary): remove Telegram integration (moved to hermes-agent)"
```

---

## Task 5: Create hermes-agent/Dockerfile

**Files:**
- Create: `hermes-agent/Dockerfile`

- [ ] **Step 1: Create the file**

```dockerfile
FROM debian:bookworm-slim

ARG HERMES_REF=main

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers

# System packages — Node.js 22 LTS from NodeSource
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates \
        python3 python3-pip python3-dev \
        ffmpeg tini ripgrep \
        build-essential libffi-dev \
        gosu \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# uv — fast Python package manager
RUN pip3 install uv --break-system-packages

# Clone hermes-agent at build time (pin HERMES_REF to a tag for production)
RUN git clone --depth 1 \
    https://github.com/NousResearch/hermes-agent.git \
    /opt/hermes

WORKDIR /opt/hermes

# Python deps — messaging extras covers Telegram, Discord, WhatsApp, Slack gateways
RUN uv sync --extra messaging

# Node.js dashboard frontend assets
RUN npm ci && npm run build

# Non-root user — uid 10000 matches official image default;
# entrypoint.sh remaps to HERMES_UID/HERMES_GID (1000/100) at runtime via gosu
RUN useradd -u 10000 -m -s /bin/bash hermes && \
    mkdir -p /opt/playwright-browsers && \
    chown -R hermes /opt/hermes /opt/playwright-browsers

VOLUME /opt/data

ENTRYPOINT ["/usr/bin/tini", "--", "/opt/hermes/docker/entrypoint.sh"]
CMD ["gateway", "run"]
```

- [ ] **Step 2: Verify Dockerfile syntax**

```bash
docker build --check hermes-agent/ 2>&1
```

Expected: exits 0 with no errors. (Requires Docker 26+ / BuildKit 0.12+. If `--check` is unsupported, skip this step and proceed to Task 6.)

---

## Task 6: Create hermes-agent/docker-compose.yml

**Files:**
- Create: `hermes-agent/docker-compose.yml`

- [ ] **Step 1: Create the file**

```yaml
services:
  hermes-gateway:
    build:
      context: .
      args:
        HERMES_REF: main
    image: hermes-agent
    container_name: hermes-gateway
    restart: unless-stopped
    env_file: .env
    environment:
      - TZ=Asia/Bangkok
      - HERMES_UID=${HERMES_UID:-1000}
      - HERMES_GID=${HERMES_GID:-100}
    volumes:
      - hermes_agent_data:/opt/data
    command: ["gateway", "run"]

  hermes-dashboard:
    image: hermes-agent
    container_name: hermes-dashboard
    restart: unless-stopped
    depends_on:
      - hermes-gateway
    env_file: .env
    environment:
      - TZ=Asia/Bangkok
      - HERMES_UID=${HERMES_UID:-1000}
      - HERMES_GID=${HERMES_GID:-100}
    ports:
      - "5060:9119"
    volumes:
      - hermes_agent_data:/opt/data
    command: ["dashboard", "--host", "0.0.0.0", "--no-open"]

volumes:
  hermes_agent_data:
```

---

## Task 7: Create hermes-agent/.env.example

**Files:**
- Create: `hermes-agent/.env.example`

- [ ] **Step 1: Create the file**

```
# hermes-agent stack — Official NousResearch/hermes-agent (Telegram + Discord)
# Copy to .env and fill in real values

# ─── LLM Provider ────────────────────────────────────────────────────────────
# OpenRouter recommended — supports Hermes, Claude, Llama, etc.
# Get a key at openrouter.ai
OPENROUTER_API_KEY=

# ─── Telegram ────────────────────────────────────────────────────────────────
# Create a bot via @BotFather → copy the token
TELEGRAM_BOT_TOKEN=
# Comma-separated numeric user IDs allowed to use the bot.
# Leave blank to allow anyone (not recommended).
TELEGRAM_ALLOWED_USERS=

# ─── Discord ─────────────────────────────────────────────────────────────────
# Create an application at discord.com/developers, add Bot, copy the token
DISCORD_BOT_TOKEN=
# Comma-separated server IDs to restrict to. Leave blank for all servers.
DISCORD_ALLOWED_GUILDS=

# ─── Container UID / GID ─────────────────────────────────────────────────────
# Must match the owner of the NAS volume directory so files are writable.
# Synology admin user = UID 1000 / GID 100 (the "users" group)
HERMES_UID=1000
HERMES_GID=100
```

---

## Task 8: Create hermes-agent/config.yaml.example

**Files:**
- Create: `hermes-agent/config.yaml.example`

- [ ] **Step 1: Create the file**

```yaml
# Hermes Agent configuration
# Copy this to the data volume: docker cp config.yaml.example hermes-gateway:/opt/data/config.yaml
# Or let hermes generate defaults on first run, then edit via:
#   docker exec -it hermes-gateway vi /opt/data/config.yaml

# ─── LLM ────────────────────────────────────────────────────────────────────
# Model slug — any OpenRouter-compatible identifier
# Options: nous/hermes-3-405b | openai/gpt-4o | anthropic/claude-opus-4-6
model: nous/hermes-3-405b
provider: auto   # auto-detects API keys from environment

# ─── Telegram ───────────────────────────────────────────────────────────────
telegram:
  reply_to_mode: first        # first | all | off
  disable_link_previews: true

# ─── Discord ────────────────────────────────────────────────────────────────
discord:
  require_mention: true   # must @hermes in servers; DMs work without mention
  auto_thread: true        # auto-create thread per conversation in channels

# ─── Session ────────────────────────────────────────────────────────────────
session:
  reset_on_idle_minutes: 60  # clear context after 60 min silence
```

---

## Task 9: Create hermes-agent/README.md

**Files:**
- Create: `hermes-agent/README.md`

- [ ] **Step 1: Create the file**

```markdown
# hermes-agent

Autonomous AI agent for Telegram and Discord, powered by [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent). Runs on Synology NAS via Docker Compose.

LINE messaging is handled by the separate `line-secretary` stack.

## Services

| Container | Role | Port |
|---|---|---|
| `hermes-gateway` | Gateway to Telegram + Discord (outbound polling) | — |
| `hermes-dashboard` | Web UI for monitoring and config | `5060` |

## Setup

### 1. Environment variables

```bash
cp .env.example .env
# Edit .env: fill in OPENROUTER_API_KEY, TELEGRAM_BOT_TOKEN, DISCORD_BOT_TOKEN
```

### 2. Telegram bot

1. Message @BotFather on Telegram → `/newbot`
2. Copy the token → set as `TELEGRAM_BOT_TOKEN`
3. Find your user ID (message @userinfobot) → set as `TELEGRAM_ALLOWED_USERS`

### 3. Discord bot

1. Go to [discord.com/developers/applications](https://discord.com/developers/applications) → New Application
2. Bot tab → Reset Token → copy → set as `DISCORD_BOT_TOKEN`
3. OAuth2 tab → URL Generator → scope: `bot`, permissions: `Send Messages`, `Read Message History` → invite to your server

### 4. Deploy

```bash
scripts/deploy.sh -s hermes-agent
```

Build takes ~5 minutes on first run (clones hermes-agent + installs deps).

### 5. First-boot config

Hermes generates a default `config.yaml` on first run. To customise model or channel settings:

```bash
docker exec -it hermes-gateway vi /opt/data/config.yaml
docker compose restart hermes-gateway
```

Or copy the example before first start:

```bash
# On NAS after deploy
docker run --rm -v hermes_agent_data:/data alpine \
  sh -c "cat > /data/config.yaml" < hermes-agent/config.yaml.example
```

### 6. Verify

```bash
docker logs hermes-gateway   # should show Telegram/Discord connected
# Open dashboard
open http://<NAS_HOST>:5060
```

## Dashboard

Port `5060` is LAN-accessible. Do **not** expose to WAN without adding a reverse proxy with authentication (same pattern as `maid-tracker`).

## Updating hermes-agent

To pull a newer version, rebuild with the desired git ref:

```bash
# On NAS
docker compose -f hermes-agent/docker-compose.yml build \
  --build-arg HERMES_REF=v0.15.0 --no-cache
docker compose -f hermes-agent/docker-compose.yml up -d
```
```

---

## Task 10: Update CLAUDE.md and root README.md

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Add hermes-agent row to CLAUDE.md Stacks Table**

In `CLAUDE.md`, after the `line-secretary/` row in the Stacks & Ports Directory table, insert:

```
| `hermes-agent/` | Autonomous AI Agent (Telegram + Discord) | 5060 (dashboard) / — (gateway) | Build clones `NousResearch/hermes-agent` from GitHub (`ARG HERMES_REF`). `config.yaml` auto-generated on first run. `network_mode: host` dropped — uses bridge networking. |
```

The existing `line-secretary/` row needs no change (it doesn't mention Telegram).

- [ ] **Step 2: Add hermes-agent row to root README.md Stacks table**

In `README.md`, after the `line-secretary/` row in the Stacks table, add:

```
| `hermes-agent/` | Autonomous AI agent — Telegram + Discord (NousResearch/hermes-agent) | `5060` (dashboard) | — |
```

Update the Environment Variables section to add `hermes-agent/.env`:

After the `watchtower/.env` line, add:
```
hermes-agent/.env         # OPENROUTER_API_KEY, TELEGRAM_BOT_TOKEN, DISCORD_BOT_TOKEN, HERMES_UID/GID
```

Update the bootstrap loop:
Change:
```bash
for d in homepage jellyfin line-secretary maid-tracker torrentwatch uptime-kuma watchtower; do
```
To:
```bash
for d in homepage jellyfin line-secretary maid-tracker torrentwatch uptime-kuma watchtower hermes-agent; do
```

- [ ] **Step 3: Commit docs**

```bash
git add CLAUDE.md README.md
git commit -m "docs: add hermes-agent to stacks tables in CLAUDE.md and README"
```

---

## Task 11: Create hermes-agent stack files and final commit

**Files:** all `hermes-agent/` files

- [ ] **Step 1: Stage all new hermes-agent files**

```bash
git add hermes-agent/Dockerfile \
        hermes-agent/docker-compose.yml \
        hermes-agent/.env.example \
        hermes-agent/config.yaml.example \
        hermes-agent/README.md
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(hermes-agent): add autonomous AI agent stack (Telegram + Discord)"
```

- [ ] **Step 3: Run final test suite for line-secretary**

```bash
cd line-secretary
pytest tests/ -v
```

Expected: all tests PASS.

- [ ] **Step 4: Verify Docker Compose file parses correctly**

```bash
docker compose -f hermes-agent/docker-compose.yml config --quiet
```

Expected: exits 0, no errors.

---

## Task 12: Update .notes/ (mandatory per CLAUDE.md)

**Files:**
- Modify: `.notes/daily_log.md`
- Modify: `.notes/00_INDEX.md`

- [ ] **Step 1: Append to .notes/daily_log.md**

Add an entry for today (2026-05-23):

```markdown
## 2026-05-23 — hermes-agent stack

- สร้าง `hermes-agent/` stack: containerize official NousResearch/hermes-agent
  - Services: `hermes-gateway` (Telegram + Discord, outbound polling) + `hermes-dashboard` (port 5060)
  - Dockerfile clones repo from GitHub at build time (ARG HERMES_REF=main)
  - UID mapping 1000/100 for Synology admin user
- Stripped Telegram from `line-secretary`: removed telegram_client.py, config fields, /webhook/telegram endpoint
  - line-secretary now LINE-only
```

- [ ] **Step 2: Update .notes/00_INDEX.md**

In the `.env` files table, change the `line-secretary/.env` row from:

```
| `line-secretary/.env` | `LINE_SECRETARY_*`, `NOTION_TOKEN`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_ALLOWED_CHAT_IDS` |
```

To:

```
| `line-secretary/.env` | `LINE_SECRETARY_*`, `NOTION_TOKEN`, `GROQ_API_KEY`, `OPENROUTER_API_KEY` |
| `hermes-agent/.env`   | `OPENROUTER_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `DISCORD_BOT_TOKEN`, `DISCORD_ALLOWED_GUILDS`, `HERMES_UID`, `HERMES_GID` |
```

And add to the Change Log table:

```
| 2026-05-23 | เพิ่ม hermes-agent stack (Telegram + Discord). ย้าย Telegram ออกจาก line-secretary |
```

- [ ] **Step 3: Commit notes**

```bash
git add .notes/daily_log.md .notes/00_INDEX.md
git commit -m "docs(notes): update daily log and index for hermes-agent session"
```

---

## Post-Deploy Checklist (on NAS)

After running `scripts/deploy.sh -s hermes-agent`:

1. `docker logs hermes-gateway --follow` — wait for Telegram/Discord connected message
2. Open `http://<NAS_HOST>:5060` — dashboard should load
3. Send `/start` to the Telegram bot — should receive a greeting
4. Remove old Telegram bot token from `line-secretary/.env` on NAS (if not already done by deploy)
5. Restart line-secretary: `docker compose -f /volume2/docker/line-secretary/docker-compose.yml restart`
