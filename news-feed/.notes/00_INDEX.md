# news-feed Stack — Index

**สร้าง:** 2026-05-23  
**Port:** 5064 (external) → 8000 (internal)  
**Status:** Running ✅ (2026-05-24)

---

## Architecture

Single Python 3.12-slim container:
- **FastAPI** — HTTP API + StaticFiles dashboard
- **APScheduler BackgroundScheduler** — fetch (60min), price (6h), digest (cron)
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
| GET | `/api/news/{id}` | — | Single article |
| GET | `/api/prices` | — | AI model prices (provider/sort filters) |
| GET | `/api/schedule` | — | Current config |
| POST | `/api/schedule` | — | Update digest times, sources, LLM model |
| GET | `/api/digest/history` | — | Last 30 digest logs |
| POST | `/api/digest/trigger` | X-Admin-Token | Manual digest now |
| GET | `/api/health` | — | status, article_count, last_fetch |

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
| DATA_DIR | /data (inside container) |

---

## Known Gotchas

- `_schedule_file()` ต้องเป็น lazy function — module-level constant จะ lock path ที่ import time ทำให้ test patch ไม่ได้
- Scheduler jobs ต้องเป็น closures capture `db_path` — ไม่ใช่อ่าน module-level `DB_PATH`
- StaticFiles mount ที่ `/` ต้อง register **หลัง** API routers ทุกตัว (catch-all)
- `get_recent_articles_for_digest` ใช้ SQLite `datetime('now', ?)` ตรงๆ ไม่ผ่าน Python datetime
- **`schedule.json` บน NAS override `.env` ทั้งหมด** — ถ้าเปลี่ยน ENABLED_SOURCES ใน .env ต้องลบ `schedule.json` ด้วย (`rm /volume2/@docker/volumes/news-feed_news_feed_data/_data/schedule.json`)
- **`entry.summary` ใน RSS ไม่ใช่ full body** — เพียงพอสำหรับ summarization, ไม่ต้อง fetch article URL
- **Digest dedup:** `_digest_job` ต้องโหลด `digest_log` ก่อนแล้วกรอง `sent_ids` ออก — ไม่งั้นบทความที่ fetch ใน window 6h ก่อน digest ล่าสุดจะถูกส่งซ้ำ

---

## Change Log

| วันที่ | เรื่อง |
|--------|--------|
| 2026-05-23 | สร้าง stack ทั้งหมด (14 tasks), 41 tests ผ่าน |
| 2026-05-24 | Fix deploy: `COPY --chown=app:app`, `chown 1000:1000 /data`, Dockerfile `RUN mkdir /data` |
| 2026-05-24 | Optimize fetcher: RSS summary แทน full-body fetch, limit 10/source, `POST /api/fetch/trigger`, immediate fetch on start |
| 2026-05-24 | Fix digest dedup: กรอง `sent_ids` จาก `digest_log` ก่อน pick 5 บทความ |
