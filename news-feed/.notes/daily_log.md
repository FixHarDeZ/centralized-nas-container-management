# Daily Log — news-feed

---

## 2026-05-23 — สร้าง stack ทั้งหมด (14 tasks)

### งานที่ทำ

สร้าง `news-feed/` stack ใหม่ครบทั้งหมดผ่าน subagent-driven development (14 tasks)

**Task 1–8 (backend modules):**
- `app/config.py` — SOURCES registry, `get_config()` / `update_config()` ใช้ lazy `_schedule_file()` ไม่ lock path ที่ import time
- `app/models.py` — SQLite WAL mode, CRUD ทุก table (articles, prices, digest_log)
- `app/fetcher.py` — feedparser + httpx + BS4, SHA256[:16] dedup, insert → body fetch → summarize → update
- `app/summarizer.py` — Anthropic SDK (prompt caching, ephemeral) + OpenRouter (httpx POST), exponential backoff 3x
- `app/pricer.py` — GET openrouter.ai/api/v1/models → multiply ×1M → upsert prices
- `app/notifier.py` — LINE Messaging API push + Telegram Bot sendMessage, skip if no creds
- `app/scheduler.py` — BackgroundScheduler: fetch (IntervalTrigger 60min), price (IntervalTrigger 6h), digest (CronTrigger per digest_times); jobs เป็น closures capture `db_path`
- Tests: 41 tests ผ่านทั้งหมด

**Task 9–10 (API endpoints):**
- `app/deps.py` — `get_db()` FastAPI dependency yields sqlite3.Connection จาก `request.app.state.db_path`
- `app/api/news.py` — GET /api/news, GET /api/news/{id}
- `app/api/prices.py` — GET /api/prices (provider filter, 4 sort options)
- `app/api/schedule.py` — GET/POST /api/schedule
- `app/api/digest.py` — GET /api/digest/history, POST /api/digest/trigger (X-Admin-Token)
- `app/api/health.py` — GET /api/health

**Task 11 (main.py final):**
- `app/main.py` — asynccontextmanager lifespan: DATA_DIR mkdir, init_db (try/except/finally + logger), app.state.db_path, scheduler start/stop
- StaticFiles mount ที่ `/` หลังจาก register routers ทั้งหมด (comment อธิบาย order dependency)

**Task 12 (dashboard):**
- `app/static/index.html` — dark theme, 6 nav tabs, Chart.js CDN
- `app/static/app.js` — loadSourceHealth (bar chart), loadNews + filterNews (search+filter), loadPrices (sort/provider), loadLeaderboard (top10 cheap + top5 expensive), loadDigestHistory (accordion), loadScheduleConfig + saveSchedule (POST /api/schedule)
- Fix: provider filter condition (`<= 1` ไม่ใช่ `!...> 1`), saveSchedule ตรวจ response.ok

**Task 13 (Docker):**
- `Dockerfile` — Python 3.12-slim, non-root user uid 1000, uvicorn CMD port 8000
- `docker-compose.yml` — port 5064:8000, named volume news_feed_data:/data, TZ=Asia/Bangkok, restart: unless-stopped
- `.env.example` — ทุก var เป็น placeholder ห้าม commit real secrets
- `README.md` — setup, dashboard, LLM switch guide, manual digest trigger (ใช้ `<NAS_HOST>`)

**Task 14 (docs):**
- `CLAUDE.md` ports table อัปเดตแล้ว (row news-feed/ port 5064)

### สถานะ

Stack พร้อม deploy — รอ user เติมค่าใน `.env` แล้วรัน `scripts/deploy.sh -s news-feed`

### Key Gotchas

- `_schedule_file()` ต้องเป็น lazy function ไม่ใช่ module-level constant — เพื่อให้ test patch ได้
- `setup_scheduler(db_path)` jobs ต้องเป็น closures — module-level `DB_PATH` จะไม่ถูก override จาก lifespan
- `get_recent_articles_for_digest` ใช้ `datetime('now', ?)` ใน SQL ตรงๆ — ไม่ต้องคำนวณ Python datetime
- Static mount ที่ `/` ต้อง register หลัง API routers ทุกตัว
