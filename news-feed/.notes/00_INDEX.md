# news-feed Stack — Index

**สร้าง:** 2026-05-23  
**Port:** 5064 (external) → Nginx :80 → news-feed :8000 (internal)  
**Status:** Running ✅ (2026-05-25)

---

## Architecture

Two-container stack:
- **Nginx (`news-feed-nginx`)** — reverse proxy on port 5064 with HTTP Basic Auth via `/etc/nginx/.htpasswd`
- **FastAPI (`news-feed`)** — internal app exposed only on Docker network port 8000
- **APScheduler BackgroundScheduler** — fetch (60min), price (6h), digest (cron), cleanup (cron 03:30 — retention)
- **SQLite** at `/data/news.db` (WAL mode)
- **Schedule config** at `/data/schedule.json` — อ่านทุก job run, เปลี่ยนได้ live

---

## File Map

| File | Responsibility |
|------|---------------|
| `app/config.py` | SOURCES dict, `get_config()`, `update_config()`, DB_PATH |
| `app/models.py` | SQLite CRUD — articles, prices, digest_log |
| `app/deps.py` | FastAPI `get_db` dependency |
| `app/fetcher.py` | RSS → dedup → body → summarize → insert |
| `app/summarizer.py` | Anthropic SDK / OpenRouter httpx, retry 3x |
| `app/pricer.py` | openrouter.ai/api/v1/models → upsert prices |
| `app/notifier.py` | LINE + Telegram push |
| `app/scheduler.py` | BackgroundScheduler setup, jobs เป็น closures |
| `app/main.py` | FastAPI lifespan, router registration, StaticFiles mount |
| `app/static/index.html` | Dashboard shell, 6 tabs |
| `app/static/app.js` | All 6 sections logic, Chart.js |

---

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | — | Dashboard (index.html) |
| GET | `/api/news` | — | List articles (source/date/limit filters) |
| DELETE | `/api/news` | basic-auth | Clear ALL articles → `{deleted}` |
| POST | `/api/news/cleanup` | basic-auth | Apply retention now (delete older than retention_days) → `{deleted, retention_days}` |
| GET | `/api/news/{id}` | — | Single article |
| POST | `/api/fetch/now` | basic-auth | Force fetch immediately → `{new_articles}` (no token; `/trigger` still token-gated) |
| GET | `/api/prices` | — | AI model prices (provider/sort filters) |
| GET | `/api/schedule` | — | Current config |
| POST | `/api/schedule` | — | Update digest times, sources, LLM model |
| GET | `/api/digest/history` | — | Last 30 digest logs |
| GET | `/api/health` | — | status, article_count, last_fetch |
| GET | `/api/news/sources` | — | Article count per source (last N hours, default 24h) |

---

## RSS Sources

| Key | Feed |
|-----|------|
| techcrunch_ai | TechCrunch AI |
| venturebeat | VentureBeat |
| theverge | The Verge |
| arstechnica | Ars Technica |
| gsmarena | GSMArena |
| 9to5mac | 9to5Mac |
| android_authority | Android Authority |

---

## .env Variables

| Variable | Purpose |
|----------|---------|
| ANTHROPIC_API_KEY | Anthropic Claude |
| LINE_CHANNEL_ACCESS_TOKEN | LINE push |
| LINE_USER_ID | LINE user target |
| TELEGRAM_BOT_TOKEN | Telegram bot |
| TELEGRAM_CHAT_ID | Telegram chat target |
| ADMIN_TOKEN | POST /api/digest/trigger |
| SUMMARIZER_PROVIDER | anthropic / openrouter |
| SUMMARIZER_MODEL | เช่น claude-sonnet-4-6 / deepseek/deepseek-chat |
| OPENROUTER_API_KEY | ถ้าใช้ openrouter |
| DIGEST_TIMES | 07:00,12:00,18:00 |
| ENABLED_SOURCES | comma-separated source keys |
| RETENTION_DAYS | จำนวนวันที่เก็บข่าว (default 30) — cleanup job ลบที่เก่ากว่านี้ทุก 03:30 |
| DATA_DIR | /data (inside container) |

---

## Known Gotchas

- `_schedule_file()` ต้องเป็น lazy function — module-level constant จะ lock path ที่ import time ทำให้ test patch ไม่ได้
- Scheduler jobs ต้องเป็น closures capture `db_path` — ไม่ใช่อ่าน module-level `DB_PATH`
- StaticFiles mount ที่ `/` ต้อง register **หลัง** API routers ทุกตัว (catch-all)
- `get_recent_articles_for_digest` ใช้ SQLite `datetime('now', ?)` ตรงๆ ไม่ผ่าน Python datetime
- **`schedule.json` บน NAS override `.env` ทั้งหมด** — ถ้าเปลี่ยน ENABLED_SOURCES ใน .env ต้องลบ `schedule.json` ด้วย (`rm /volume2/@docker/volumes/news-feed_news_feed_data/_data/schedule.json`)
- **`entry.summary` ใน RSS ไม่ใช่ full body** — เพียงพอสำหรับ summarization, ไม่ต้อง fetch article URL
- **`_shownPrices[]` vs `allPrices[]`**: หลัง search filter index ใน rendered table ไม่ตรงกับ `allPrices` — `renderPriceTable(prices)` เก็บ `_shownPrices = prices` แล้ว copy handler ใช้ `_shownPrices[idx]`
- **Copy button XSS safety**: ใช้ `data-idx` (integer) + JS array lookup แทนการใส่ model_id ใน HTML attribute
- **Leaderboard categorization**: `paidPositive` ใช้ `combined > 0` (ไม่ใช่ `prompt>0 && complete>0`) — ป้องกัน mixed-price models (prompt=$0, complete=$5) หายไปจากทุก category
- **Source Health 422**: `/api/news` มี `le=100` แต่ frontend เคยขอ `limit=500` → 422 → silent error → blank chart. Fix: เพิ่ม `/api/news/sources` endpoint ที่ใช้ aggregate SQL แทน
- **Basic Auth sidecar**: dashboard/API public access ต้องผ่าน `news-feed-nginx`; ไฟล์ `nginx/.htpasswd` เป็น secret, gitignored, ต้องสร้างบนเครื่อง deploy/NAS เอง
- **`retention_days` backward-compat**: `schedule.json` เก่าไม่มี key นี้ — consumer ทุกตัวใช้ `.get("retention_days", 30)` จึงไม่ต้องลบ `schedule.json`; ค่าจะถูกเขียนลงไฟล์เมื่อกด Save Config ครั้งแรก
- **Watchlist เป็น client-side**: เก็บใน `localStorage['nf_watchlist']` (array ของ model_id) — per-browser ไม่ sync ข้าม device, ไม่มี backend state
- **Leaderboard render split**: `loadLeaderboard()` fetch → set `_lbPrices` → `renderLeaderboard()`; bookmark/collapse เรียก `renderLeaderboard()` ตรงๆ ไม่ re-fetch
- **`POST /api/fetch/now` อาจนาน**: fetch + summarize หลาย source > 60s → nginx ตั้ง `proxy_read_timeout 300s` กัน 504 (server ทำงานต่อแม้ client timeout)
- **Summarizer fail silent**: ถ้า OpenRouter model ถูก rate-limit, retry หมดแล้ว skip article เงียบๆ — ไม่มี log error. ตรวจสอบด้วย `POST /api/digest/test` ดู `available_6h`; ถ้า = 0 ทั้งที่ timeline มีข่าว → summarizer fail. Re-summarize backlog ด้วย `docker exec` Python script

---

## Change Log

| วันที่ | เรื่อง |
|--------|--------|
| 2026-05-23 | สร้าง stack ทั้งหมด (14 tasks), 41 tests ผ่าน |
| 2026-05-24 | Fix deploy: `COPY --chown=app:app`, `chown 1000:1000 /data`, Dockerfile `RUN mkdir /data` |
| 2026-05-24 | Optimize fetcher: RSS summary แทน full-body fetch, limit 10/source, `POST /api/fetch/trigger`, immediate fetch on start |
| 2026-05-24 | Fix digest dedup: กรอง `sent_ids` จาก `digest_log` ก่อน pick 5 บทความ |
| 2026-05-25 | Fix Invalid Date: เปลี่ยน `isoformat()` → `strftime("%Y-%m-%dT%H:%M:%SZ")` ใน fetcher/pricer/scheduler, feedparser ใช้ `published_parsed` แทน raw string |
| 2026-05-25 | Dashboard: ย้าย "Last fetch" ไป header, เพิ่ม Model ID column + copy button (XSS-safe) ใน Price Tracker |
| 2026-05-25 | Dashboard: Price Tracker search bar, กรองราคาติดลบ, Free Models section ใน Leaderboard |
| 2026-05-25 | Feature: Geo zone filter in Price Tracker (PROVIDER_ZONES + zone buttons + badge), escapeHtml() XSS fix |
| 2026-05-25 | Feature: Leaderboard zone badges, 🏆 Top Hit, 🧠 Top Intelligence sections (ELO-based, longest-match-first) |
| 2026-05-25 | Feature: Free model expiry — `free_expires_at` DB column + `PATCH /api/prices/{id}/expiry` + color-coded badge (urgent/warn/ok) + inline 📅 edit in Leaderboard |
| 2026-05-25 | Infra: เพิ่ม `nginx:alpine` basic-auth reverse proxy on port 5064; app เปลี่ยนเป็น internal-only `expose: 8000` และ `nginx/.htpasswd` เป็น local/NAS secret |
| 2026-05-27 | Fix: Telegram digest debug (`POST /api/digest/test`), News sort toggle, Test Digest button |
| 2026-05-29 | Feature: Top Hit Cheapest/Free cards, leaderboard jump bar + collapsible + watchlist (localStorage), news retention (`RETENTION_DAYS` + cleanup job + `DELETE /api/news` + `POST /api/news/cleanup`), `POST /api/fetch/now`, Xiaomi→CN zone fix, news sort by published date. 56 tests |
