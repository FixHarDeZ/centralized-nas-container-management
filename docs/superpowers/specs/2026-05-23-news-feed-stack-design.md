# news-feed Stack Design

**Date:** 2026-05-23  
**Status:** Approved  
**Location:** `news-feed/` inside `centralized-nas-container-management` repo  
**Port:** 5064

---

## Overview

A Docker Compose stack that fetches AI & IT news from RSS sources, summarises each article into Thai via Claude API, sends scheduled digest notifications to LINE and Telegram, and exposes a web dashboard for monitoring.

---

## Architecture

Single Python 3.12-slim container running FastAPI + APScheduler. No Redis. No separate frontend container. SQLite for all persistence.

```
news-feed/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── README.md
├── requirements.txt
├── .notes/
└── app/
    ├── main.py          # FastAPI app + lifespan startup (mounts static, registers scheduler)
    ├── scheduler.py     # APScheduler jobs: fetch_job, price_job, digest_job
    ├── fetcher.py       # feedparser RSS reader; deduplicates by URL sha256
    ├── summarizer.py    # Anthropic SDK call; returns Thai summary string
    ├── notifier.py      # LINE Messaging API push + Telegram Bot API send
    ├── pricer.py        # httpx GET openrouter.ai JSON API → parse model list
    ├── models.py        # sqlite3 init_db(), helper functions (no ORM)
    ├── api/
    │   ├── news.py      # /api/news, /api/news/{id}
    │   ├── prices.py    # /api/prices
    │   ├── schedule.py  # GET/POST /api/schedule
    │   ├── digest.py    # GET /api/digest/history, POST /api/digest/trigger
    │   └── health.py    # GET /api/health
    └── static/
        ├── index.html   # single-page dashboard
        └── app.js       # vanilla JS fetch() + Chart.js via CDN
```

**Docker Compose:**
- 1 service: `news-feed`
- Volume: `news_feed_data:/data` (SQLite + schedule config JSON)
- Port: `5064:8000`
- `env_file: .env`
- `restart: unless-stopped`
- `TZ: Asia/Bangkok`

---

## Data Model (SQLite at `/data/news.db`)

```sql
CREATE TABLE articles (
    id          TEXT PRIMARY KEY,   -- sha256(url)
    source      TEXT NOT NULL,      -- source key e.g. "techcrunch_ai"
    title       TEXT NOT NULL,
    url         TEXT NOT NULL UNIQUE,
    published   TEXT NOT NULL,      -- ISO8601 UTC
    summary_th  TEXT,               -- NULL until summarized; filled immediately after fetch
    fetched_at  TEXT NOT NULL       -- ISO8601 UTC
);

CREATE TABLE prices (
    model_id        TEXT PRIMARY KEY,
    provider        TEXT,
    name            TEXT,
    prompt_price    REAL,           -- USD per 1M tokens
    complete_price  REAL,
    context_length  INTEGER,
    updated_at      TEXT            -- ISO8601 UTC
);

CREATE TABLE digest_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at     TEXT NOT NULL,      -- ISO8601 UTC
    article_ids TEXT NOT NULL,      -- JSON array of article IDs
    channels    TEXT NOT NULL       -- "line,telegram" or subset
);
```

No ORM. Plain `sqlite3` with helper functions in `models.py`.

---

## RSS Sources

| Key | Feed Name | RSS URL |
|-----|-----------|---------|
| `techcrunch_ai` | TechCrunch AI | `https://techcrunch.com/category/artificial-intelligence/feed/` |
| `venturebeat` | VentureBeat | `https://venturebeat.com/feed/` |
| `theverge` | The Verge | `https://www.theverge.com/rss/index.xml` |
| `arstechnica` | Ars Technica | `https://feeds.arstechnica.com/arstechnica/technology-lab` |
| `gsmarena` | GSMArena | `https://www.gsmarena.com/rss-news-reviews.php3` |
| `9to5mac` | 9to5Mac | `https://9to5mac.com/feed/` |
| `android_authority` | Android Authority | `https://www.androidauthority.com/feed/` |

Sources are configurable via `ENABLED_SOURCES` env var (comma-separated keys). Can also be toggled live via `POST /api/schedule`.

---

## Scheduling & Data Flow

All times in Asia/Bangkok (UTC+7). APScheduler uses `AsyncIOScheduler`.

### fetch_job — every 60 minutes, 06:00–23:00

```
feedparser.parse(rss_url) for each enabled source
  → for each entry: compute id = sha256(url)
  → skip if id already in articles table
  → fetch article body: httpx GET → BS4 extract text (first 1500 chars)
  → INSERT articles (summary_th=NULL)
  → summarizer.summarize(title, body) → summary_th string
  → UPDATE articles SET summary_th = ...
```

### price_job — every 6 hours

```
httpx GET https://openrouter.ai/api/v1/models  (public JSON API, no auth)
  → parse response.data[] for id, name, pricing.prompt, pricing.completion, context_length
  → derive provider from model_id prefix (e.g. "openai/gpt-4o" → "openai")
  → UPSERT prices table
```

### digest_job — 07:00, 12:00, 18:00

```
SELECT articles WHERE fetched_at >= NOW()-6h AND summary_th IS NOT NULL
  ORDER BY published DESC LIMIT 5
  → format digest message (Thai)
  → notifier.send_line(message)
  → notifier.send_telegram(message)
  → INSERT digest_log
```

### Claude Summarization

- **Model:** `claude-sonnet-4-6`
- **Max tokens:** 300
- **Prompt caching:** system prompt cached (ephemeral cache)
- **System prompt:** (cached) "คุณคือผู้ช่วยสรุปข่าวเทคโนโลยีเป็นภาษาไทย กระชับ อ่านง่าย"
- **User prompt:** `สรุปบทความนี้ 2-3 ประโยค:\nTitle: {title}\nContent: {body[:1500]}`
- **Retry:** exponential backoff 3x on rate limit / 5xx

---

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | — | Dashboard (index.html) |
| GET | `/api/news` | — | List articles; query: `source`, `date`, `limit` (default 20) |
| GET | `/api/news/{id}` | — | Single article with full summary |
| GET | `/api/prices` | — | AI model prices; query: `provider` (string), `sort` (`prompt_asc`\|`prompt_desc`\|`complete_asc`\|`combined_asc`, default `combined_asc`) |
| GET | `/api/schedule` | — | Current schedule config (times + enabled sources) |
| POST | `/api/schedule` | — | Update digest times / toggle sources; body: JSON |
| GET | `/api/digest/history` | — | List digest_log entries (last 30) |
| POST | `/api/digest/trigger` | `X-Admin-Token` header | Manually trigger digest now |
| GET | `/api/health` | — | `{"status":"ok","last_fetch":"…","article_count":…}` |

All endpoints are public except `POST /api/digest/trigger` which requires `X-Admin-Token: {ADMIN_TOKEN}`.

---

## Dashboard (Static HTML/JS)

Single-page app at `/`. Served by FastAPI `StaticFiles`. No build step. Chart.js loaded from CDN.

**Sections:**

1. **Source Health** — bar chart: articles fetched per source (last 24h). Status dot (green/red) per source. Last fetch timestamp.

2. **News Timeline** — card list: title, source badge, published time, Thai summary (collapsed, expand on click). Search bar (client-side keyword filter). Filter dropdown by source.

3. **AI Price Tracker** — sortable table: model name, provider, prompt price, complete price, context length. Last updated timestamp.

4. **AI Leaderboard** — ranked list: top 10 cheapest models (by prompt+complete combined), top 5 most expensive. Filter by provider.

5. **Digest History** — timeline of past digest sends; click entry to see article list for that digest.

6. **Schedule Config** — edit digest times (inline time inputs). Toggle enabled/disabled per source. Save button → `POST /api/schedule`.

Footer: Last digest time + manual `[Trigger Digest]` button (calls `POST /api/digest/trigger` with admin token stored in sessionStorage).

---

## .env / Config

```bash
# Anthropic
ANTHROPIC_API_KEY=sk-ant-...

# LINE Messaging API
LINE_CHANNEL_ACCESS_TOKEN=...
LINE_USER_ID=U...

# Telegram
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...

# Admin
ADMIN_TOKEN=...

# Schedule (Bangkok time, comma-separated HH:MM)
DIGEST_TIMES=07:00,12:00,18:00

# Sources (comma-separated source keys, all enabled by default)
ENABLED_SOURCES=techcrunch_ai,venturebeat,theverge,arstechnica,gsmarena,9to5mac,android_authority

# Paths
DATA_DIR=/data
TZ=Asia/Bangkok
```

Schedule config (digest times + enabled sources) is persisted to `/data/schedule.json` so POST changes survive restarts. `.env` values are defaults only.

---

## Integration with hermes-agent

news-feed does **not** share Telegram bot token with hermes-agent. They are independent. The `/api/news` endpoint is designed to be callable by any external tool — hermes-agent can query it to answer user questions like "what's the latest AI news?" without code changes to news-feed.

---

## Security

- No `.env` committed (`.gitignore` covers all `*/.env`)
- No real IPs or passwords in code or docs — use placeholders `<NAS_HOST>`, etc.
- `ADMIN_TOKEN` required for digest trigger endpoint
- Watchtower: no special label needed (not critical infra), auto-updates OK

---

## Deliverables

1. `news-feed/docker-compose.yml`
2. `news-feed/Dockerfile`
3. `news-feed/.env.example`
4. `news-feed/README.md`
5. `news-feed/requirements.txt`
6. `news-feed/app/` — all Python modules
7. `news-feed/app/static/` — `index.html` + `app.js`
8. CLAUDE.md root table updated (port 5064 row)
9. Root `README.md` updated if needed
