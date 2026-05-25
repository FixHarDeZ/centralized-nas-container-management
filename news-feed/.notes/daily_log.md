# Daily Log — news-feed

---

## 2026-05-25 — Feature: AI Price Tracker + Leaderboard timestamps

### Changes
- **API:** เพิ่ม `GET /api/prices/updated` — returns `MAX(updated_at)` from prices table
- **Models:** เพิ่ม `get_price_updated_at(conn)` function
- **Frontend Price Tracker:** แสดง "🕐 Last updated: ..." ที่ด้านบน section + เพิ่มคอลัมน์ "Updated" ในตาราง
- **Frontend Leaderboard:** แสดง "🕐 Last updated: ..." ที่ด้านบน section (แสดง "Not yet updated" ถ้ายังไม่มีข้อมูล)
- Timestamp format: `th-TH` locale

### Deploy
ยังไม่ได้ deploy — รอ push + deploy

---

## 2026-05-24 (3) — Fix: digest dedup — ไม่ส่งข่าวซ้ำระหว่างรอบ

### Bug
`_digest_job` ใช้ `get_recent_articles_for_digest(hours=6)` แต่ไม่เช็ค `digest_log` → บทความที่เคยส่งแล้วอาจถูกส่งซ้ำถ้า `fetched_at` ยังอยู่ใน window 6 ชั่วโมง

**Root cause:** รอบ 07:00→12:00 ห่างกัน 5 ชั่วโมง แต่ query window 6 ชั่วโมง → overlap 1 ชั่วโมง; การเทสตอนเช้า fetch บทความที่ 09:00 → 12:00 ยังอยู่ใน window → ส่งซ้ำ

### Fix — `scheduler.py` `_digest_job`
```python
history = get_digest_history(conn, limit=20)
sent_ids = {aid for entry in history for aid in entry["article_ids"]}
candidates = get_recent_articles_for_digest(conn, hours=6, limit=20)
articles = [a for a in candidates if a["id"] not in sent_ids][:5]
```
- โหลด `digest_log` 20 รายการล่าสุด → รวม IDs ที่เคยส่ง
- ดึง candidates 20 บทความ → กรองออก → เหลือ 5 ตัวแรก

### Deploy
`bash scripts/deploy.sh -s news-feed -y` — build + restart สำเร็จ (9s) ✅

---

## 2026-05-24 (2) — Optimize fetcher + fetch/digest trigger endpoints

### Feature: Immediate fetch on start
- `scheduler.py` — เพิ่ม `next_run_time=datetime.now(UTC) + 5s` ใน fetch_job → fetch รันทันทีทุกครั้งที่ container start

### Feature: POST /api/fetch/trigger
- สร้าง `app/api/fetch.py` — endpoint ใหม่ protected by `X-Admin-Token`
- register ใน `main.py`

### Optimize: fetcher.py
- **ลบ `_fetch_body()`** — ไม่ fetch full article body จาก URL อีก (httpx GET ต่อบทความ)
- **ใช้ `_entry_body(entry)`** แทน — parse `entry.summary`/`entry.description` จาก RSS feed ตรงๆ ด้วย BeautifulSoup (ไม่มี HTTP call)
- **จำกัด `feed.entries[:10]`** — cap 10 บทความต่อ source ต่อรอบ
- ลบ `httpx` import ออกจาก fetcher.py

### Config: ENABLED_SOURCES
- เปลี่ยนจาก 7 sources → `techcrunch_ai` อย่างเดียว
- ล้าง `schedule.json` + `news.db` บน NAS แล้วเริ่มใหม่สะอาด

### ผลลัพธ์
- Fetch เวลา: 5+ นาที → ~60 วินาที
- Digest ส่ง Telegram สำเร็จ: `sent_to: ["telegram"], article_count: 5` ✅

---

## 2026-05-24 — Deploy fix: PermissionError + SQLite unable to open

### Bug 1 — PermissionError: /app/app/__init__.py

**Root cause:** `COPY app/ ./app/` ดึง permission `600` (root-only) จากไฟล์บน NAS ที่ tar extract มา → `USER app` (uid 1000) อ่านไม่ได้
**Fix:** `COPY --chown=app:app app/ ./app/`

### Bug 2 — sqlite3.OperationalError: unable to open database file

**Root cause:** Docker named volume `/data` ถูก create เป็น `root:root 755` → app user เป็นแค่ "others" (r-x) เขียน `news.db` ไม่ได้
**Fix ทันที:** `sudo chown 1000:1000 /volume2/@docker/volumes/news-feed_news_feed_data/_data`
**Fix ถาวร:** เพิ่ม `RUN mkdir -p /data && chown app:app /data` ใน Dockerfile ก่อน `USER app`

**Status:** Running ✅ — `GET /api/health → {status: ok, article_count: 0}`

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
