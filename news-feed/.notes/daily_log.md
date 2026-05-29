# Daily Log — news-feed

---

## 2026-05-29 — Debug: Summarizer fail silent (rate-limit) + backlog re-summarization

### Root cause
- `meta-llama/llama-3.3-70b-instruct:free` ถูก Venice (OpenRouter upstream) rate-limit ตั้งแต่ **2026-05-27T16:35Z** — summarizer retry หมดแล้ว silent skip ทุก article ไม่มี log error เลย
- `schedule.json` บน NAS override `.env` → model จริงที่ใช้คือ free llama ไม่ใช่ deepseek จาก `.env`
- ผลลัพธ์: articles 53 รายการ (2026-05-28T14:35 – 2026-05-29T01:35) มี `summary_th = NULL` → `get_recent_articles_for_digest` คืน 0 → digest ไม่ส่ง 40+ ชั่วโมง

### Fix
1. `POST /api/schedule` เปลี่ยน `summarizer_model` เป็น `deepseek/deepseek-chat` (เขียนลง `schedule.json` live)
2. `docker exec` Python script re-summarize articles ที่ค้าง (2 batch × 30) — null_left=0
3. `POST /api/digest/test` verify: `sent_to=["telegram"]`, `article_count=5`, `available_6h=20` ✅

### Detection tip
ดู `available_6h` จาก `POST /api/digest/test` — ถ้า = 0 ทั้งที่ timeline มีข่าว แปลว่า summarizer กำลัง fail

---

## 2026-05-29 — Feature batch: leaderboard nav, Top Hit cards, retention, fetch-now, sort & zone fixes

### 1. Zone fix — Xiaomi & more CN providers
- `PROVIDER_ZONES` (app.js): เพิ่ม `xiaomi`, `alibaba`, `ernie`, `yi`, `moonshotai`, `kimi`, `z-ai`, `thudm`, `glm`, `stepfun`, `internlm`, `opengvlab` → CN. ก่อนหน้านี้ Xiaomi (โมเดลจีน) ตกไป Others เพราะ prefix ไม่อยู่ใน map

### 2. News Timeline sort bug
- เดิม `_sortedNews()` แค่ reverse array ตาม order ของ API (อิง published DESC) — ถ้า published เท่ากัน/ผิดรูปแบบจะดูเหมือน sort มั่ว
- แก้เป็น sort by `new Date(a.published)` ตรงๆ (newest→oldest) แล้วค่อย reverse ตาม toggle → ถูกต้องเสมอไม่ขึ้นกับ order จาก API

### 3. Leaderboard — Top Hit Cheapest + Top Hit Free (cards ใหม่)
- `_isPopular(modelId)` = match กับ `TOP_HIT_MODELS` (substring)
- 💸 Top Hit — Cheapest: popular ที่ paid (combined>0) เรียงถูก→แพง top 10
- 🆓 Top Hit — Free: popular ที่ราคา $0 top 10

### 4. Leaderboard navigation (toggle + jump + watchlist)
- แยก `loadLeaderboard()` (fetch) ออกจาก `renderLeaderboard()` (render จาก `_lbPrices` cache) — bookmark ไม่ต้อง re-fetch
- **Jump bar** sticky (`.lb-jump`, `top:104px`) — pill กดแล้ว `scrollIntoView` + auto-expand card (`scroll-margin-top:160px` กัน sticky บัง)
- **Collapsible cards** — `.lb-head` onclick `toggleLbCard()` toggle `.collapsed` (ซ่อน `.lb-body`, หมุน caret)
- **Watchlist** — ⭐/☆ ต่อแถว (`_starBtn`), เก็บใน `localStorage['nf_watchlist']` (Set ของ model_id), การ์ด ⭐ My Watchlist ด้านบนสุด. delegated `.star-btn` handler → `toggleBookmark()` → re-render
- `_rankRow(p, num, priceHtml)` helper รวม row template (มี star) ใช้ทุก card ยกเว้น Free Models (ยังมี 📅 expiry edit เฉพาะตัว)
- XSS: `escapeAttr()` (escapeHtml + escape `"`) สำหรับ `data-model` attribute

### 5. News retention + clear-all
- Backend: `config.retention_days` (default 30, env `RETENTION_DAYS`), `schedule.py` allowed_keys + clamp `max(1,int())`
- `models.delete_articles_older_than(conn, days)` (DELETE WHERE fetched_at < datetime('now','-Nd')), `delete_all_articles(conn)`
- `scheduler._cleanup_job` CronTrigger 03:30 Bangkok
- API: `POST /api/news/cleanup` (apply retention now), `DELETE /api/news` (clear all) — ทั้งคู่หลัง nginx basic auth ไม่ต้อง token
- UI (Schedule Config): input `cfg-retention` + Danger Zone card ปุ่ม `clearAllNews()` มี `confirm()` ก่อนลบ

### 6. Fetch Now button
- API: `POST /api/fetch/now` (basic-auth, ไม่ต้อง token) คู่กับ `/api/fetch/trigger` เดิม (token)
- UI: ปุ่ม ⚡ Fetch Now ใน News Timeline → `fetchNow()` → reload news/health/source-health. (ส่ง Telegram ทันที = ปุ่ม 📤 Test Digest เดิมใน Digest History)
- nginx.conf: เพิ่ม `proxy_read_timeout 300s` กัน 504 ตอน fetch+summarize นาน

### Tests
- เพิ่ม 7 tests (models: delete_all/delete_old; api: clear-all, cleanup, fetch-now, retention valid/invalid)
- **56/56 passed** ✅
- Validation เพิ่ม: boot uvicorn จริง (DATA_DIR temp) ยืนยันทุก endpoint ตอบถูก, node logic test ยืนยัน Top Hit Cheapest/Free + Xiaomi=CN, `node --check app.js` ผ่าน
- ⚠️ ยังไม่ได้ verify การ render บน browser จริง (ไม่มี browser ใน env) — ตรวจ element-id ใน index.html ครบทุกตัวที่ app.js อ้างถึงแล้ว

### Deploy
- รอ push + deploy. หมายเหตุ: `schedule.json` บน NAS ไม่มี `retention_days` → consumer ใช้ `.get("retention_days",30)` อยู่แล้ว ไม่ต้องลบไฟล์; จะมีค่าเมื่อกด Save Config ครั้งแรก

---

## 2026-05-25 (10) — Infra: Nginx basic-auth sidecar for dashboard

### Changes
- เพิ่ม `nginx/nginx.conf` ตาม pattern ของ homepage: `auth_basic "Restricted"` + proxy ไป `http://news-feed:8000`
- `docker-compose.yml`: `news-feed` เปลี่ยนจาก `ports: 5064:8000` เป็น `expose: 8000`
- เพิ่ม service `news-feed-nginx` (`nginx:alpine`) เปิด public port `5064:80` และ mount `nginx.conf` + `.htpasswd`
- ยืนยันว่า root `.gitignore` มี `.htpasswd` อยู่แล้ว → `news-feed/nginx/.htpasswd` ถูก ignore, ไม่ commit
- อัปเดต README ให้ระบุว่าต้องสร้าง `nginx/.htpasswd` บนเครื่อง deploy/NAS เอง และ curl ผ่าน basic auth

### Validation
- `docker compose config` ผ่าน ✅
- `git check-ignore -v news-feed/nginx/.htpasswd` ชี้ไปที่ root `.gitignore` ✅

---

## 2026-05-25 (9) — Fix: Copy button กดไม่ได้ (HTTP clipboard fallback)

### Root Cause
`navigator.clipboard.writeText()` ต้องการ HTTPS หรือ localhost. news-feed เปิดที่ port 5064 ผ่าน plain HTTP → `navigator.clipboard = undefined` → synchronous TypeError → ไม่ถูก `.catch()` จับ → ปุ่มเงียบ ไม่มี feedback ใดๆ

### Fix
- เพิ่ม `_copyText(text)` helper ใน app.js
- ลองใช้ `navigator.clipboard.writeText()` ก่อน (HTTPS)
- Fallback เป็น `textarea + document.execCommand('copy')` ซึ่งทำงานได้บน plain HTTP
- Commit: `fix(news-feed): clipboard HTTP fallback for copy button`

---

## 2026-05-25 (8) — Feature: Free model expiry date in Leaderboard

### Task 1: Backend (DB + API)
- `prices` table: `ALTER TABLE prices ADD COLUMN free_expires_at TEXT` migration (idempotent try/except for `OperationalError` with "duplicate column" check only)
- `set_free_expiry(conn, model_id, expires_at)` in models.py: `datetime.strptime()` semantic validation, returns bool, None clears
- `upsert_price()` confirmed NOT touching `free_expires_at` — preserved across price syncs
- `PATCH /api/prices/{model_id:path}/expiry` — 404 not found, 422 bad date, success `{model_id, free_expires_at}`
- 7 new tests (46 total)
- Commits: `ce85139`, `0284fb7`, `1e7c559`

### Task 2: Frontend (Display + Inline Edit)
- `freeExpiryStatus(expires_at)` helper: expired/urgent (≤3d)/warn (≤7d)/ok (>7d)/invalid → {label, className}
- CSS: `.expiry-badge`, `.expiry-ok` (dark green), `.expiry-warn` (amber), `.expiry-urgent` (red + pulse-red animation), `.expiry-edit-input`
- Free models rows: expiry badge color-coded + 📅 button (data-idx → `_freeModels[]` lookup)
- 📅 click: toggles inline date input → `change` → PATCH → `loadLeaderboard()` reload
- Safety: model_id URL-encoded via `split('/').map(encodeURIComponent).join('/')`, input.value captured before `input.remove()` (race fix), NaN guard on invalid dates
- Commits: `6e2856c`, `94ea1c5`

---



### Task 1: Geo zone filter — AI Price Tracker
- `PROVIDER_ZONES` constant (25 providers → {zone, flag, label}: US/CN/EU/Others)
- `getZone(modelId)` helper with Others fallback
- Zone filter buttons (All | 🇺🇸 US | 🇨🇳 CN | 🇪🇺 EU | 🌍 Others) in price-tracker search row
- `filterPrices()` applies both text search + zone filter
- Zone badge in Model column of price table
- `escapeHtml()` helper added + applied to all user-data innerHTML injections (XSS fix)
- Commits: `ca9b110`, `5a097ec`

### Task 2: Leaderboard enhancements
- Zone badge added to all existing rows (cheapest/free/expensive)
- `TOP_HIT_MODELS` array (17 popular model substrings, order = rank priority)
- `MODEL_ELO_SCORES` object (20 models with Chatbot Arena ELO scores, approx.)
- 🏆 Top Hit card — top 10 matched from live price data
- 🧠 Top Intelligence card — top 10 by ELO, matched from live price data
- Bug fix: ELO matching sorts keys by length desc (longest-match-first) to prevent `gpt-4o` matching `gpt-4o-mini`
- Commits: `2cacc56`, `1e8910e`

### Tests
38/38 passed ✅

---

## 2026-05-25 (6) — Fix: Source Health 422 bug + token efficiency

### Root Cause
`/api/news` มี `le=100` (max 100) แต่ frontend ขอ `?limit=500` → FastAPI return 422 → `catch(e) { console.error(e) }` กลืน error เงียบ → Source Health แสดง blank chart ตลอด

### Fix 1 — API endpoint ใหม่ (ประหยัด resource)
- `api/news.py`: เพิ่ม `GET /api/news/sources?hours=24` — ใช้ `get_source_counts()` ที่มีอยู่แล้ว → aggregate SQL (`COUNT(*) GROUP BY source`) แทนการ fetch 500 rows

### Fix 2 — Frontend caching (ไม่ re-fetch ทุก tab switch)
- `app.js`: `loadSourceHealth()` ใช้ `/api/news/sources` แทน `/api/news?limit=500`
- เพิ่ม `_sourceHealthLoaded` flag → โหลดครั้งเดียว, ไม่ re-fetch เมื่อกลับมา tab เดิม
- เพิ่ม `refreshSourceHealth()` สำหรับ force reload
- เพิ่ม empty state message "No articles fetched yet"
- Error log มี context แทน silent swallow

### Fix 3 — UI
- `index.html`: เพิ่ม ↻ Refresh button ใน source-health card

### Tests
26/26 passed ✅

### Deploy
รอ push + deploy



### Task 1: AI Price Tracker
- `index.html`: เพิ่ม `<input id="price-search">` ใน `.search-row` ก่อน selects
- `app.js`:
  - Extract `renderPriceTable(prices)` จาก `loadPrices()` — sets `_shownPrices` global
  - `loadPrices()` filter negative prices (`prompt<0 || complete<0`) ออกจาก `allPrices`
  - `filterPrices()` search ตาม name/model_id, call `renderPriceTable(filtered)`
  - Copy handler เปลี่ยนจาก `allPrices[idx]` → `_shownPrices[idx]` (safe after search filter)

### Task 2: Leaderboard
- `index.html`: เพิ่ม card `🆓 Free Models` ระหว่าง cheap และ expensive card
- `app.js` `loadLeaderboard()`:
  - `validPrices` = filter negatives ก่อน
  - `freeModels` = validPrices ที่ both prices === 0 (แสดงทุกตัว, ไม่มี rank, badge "FREE")
  - `paidPositive` = validPrices ที่ combined > 0 (รวม mixed-price เช่น prompt=0, complete>0)
  - Top 10 Cheapest = paidPositive first 10 (ไม่มี free, ไม่มี negative)
  - Top 5 Expensive = paidPositive reversed first 5
  - Empty state สำหรับทุก section

### Quality fixes (จาก code review)
- Mixed-price models (เช่น prompt=$0, complete=$5) ไม่หลุด category — ใช้ combined > 0
- Empty state handling สำหรับ Top 10 และ Top 5

### Commits
- `7bb211f` feat: price tracker search bar + filter negative prices
- `7a61b02` feat: leaderboard free models section + filter negatives
- `bd1a709` fix: filter negative prices in leaderboard before categorizing
- `4f0775e` fix: leaderboard mixed-price models + empty states

### Deploy
รอ push + deploy



### Changes
- `index.html`: เพิ่ม `<th>Model ID</th>` เป็น column ที่ 2 ใน `#price-table` header + CSS `.model-id` (monospace, #94a3b8) + CSS `.copy-btn`
- `app.js`: `loadPrices()` row template ใช้ `(p, i)` map → แสดง `model_id` span + copy button พร้อม `data-idx="${i}"`
- `app.js`: delegated click handler ที่ `document` level (ไม่ใช่ใน loadPrices ที่ re-add ทุกครั้ง) — ใช้ `WeakMap` สำหรับ timeout tracking

### Security & Quality Fixes (จาก code review)
- **XSS prevention**: ใช้ `data-idx` + `allPrices[idx].model_id` lookup แทนการ embed `model_id` ลงใน HTML attribute โดยตรง
- **Race condition fix**: `_copyTimers = new WeakMap()` track timeout ID ต่อปุ่ม → `clearTimeout` ก่อน set ใหม่ทุกครั้ง

### Commits
- `d57a6a2` feat: add model ID column with copy button to AI Price Tracker
- `eac984b` fix: prevent XSS in copy button and race condition with rapid clicks

### Deploy
รอ push + deploy



### Root Cause
**ไม่ใช่เรื่อง space separator** — ปัญหาจริงคือ format ที่ Python ส่งออกมา:

| Source | Format จริง | ปัญหา |
|--------|------------|-------|
| `datetime.now(timezone.utc).isoformat()` | `"2026-05-25T14:17:40.183000+00:00"` | append `'Z'` → `"...+00:00Z"` = **Invalid** |
| feedparser raw `entry.published` | `"Mon, 25 May 2026 07:00:00 +0000"` | `.replace(' ','T')` → `"Mon,T25TMay..."` = **Invalid** |

Fix ก่อนหน้า (`.replace(' ','T') + 'Z'`) แก้ได้เฉพาะ SQLite `datetime('now')` format แต่ทุก field จริงๆ มาจาก Python `isoformat()` ไม่ใช่ SQLite function

### Fix — Backend (เปลี่ยน format ที่ source)
- `fetcher.py`: `_entry_published()` ใช้ feedparser `published_parsed`/`updated_parsed` (UTC `struct_time`) แทน raw string → format เป็น `strftime("%Y-%m-%dT%H:%M:%SZ")`
- `fetcher.py`: `fetched_at` → `strftime("%Y-%m-%dT%H:%M:%SZ")` (ไม่ใช้ `isoformat()`)
- `pricer.py`: `updated_at` → `strftime("%Y-%m-%dT%H:%M:%SZ")`
- `scheduler.py`: `sent_at` → `strftime("%Y-%m-%dT%H:%M:%SZ")`

### Fix — Frontend (ทำให้เรียบง่าย)
- `app.js`: ลบ `.replace(' ','T') + 'Z'` ออกทุกจุด → ใช้ `new Date(str)` ตรงๆ เพราะ backend ส่ง ISO 8601 + Z ที่ถูกต้องแล้ว

### Tests
38/38 passed ✅

### Deploy
รอ push + deploy



### Bug
- AI Price Tracker / Leaderboard / Digest History แสดงเป็น "Invalid Date"
- **Root cause:** SQLite datetime `"2026-05-25 12:30:00"` (space separator) + `'Z'` → `new Date()` ใน Safari/Firefox ไม่ยอมรับ format นี้ (ต้องการ ISO 8601 ที่มี `T`)

### Fix
- `app.js` — ทุก `new Date(str + 'Z')` เปลี่ยนเป็น `new Date(str.replace(' ','T') + 'Z')` ครอบคลุม: `h.last_fetch`, `updatedData.updated_at` (x2), `p.updated_at`, `d.sent_at`
- `app.js` — `a.published` ใน News Timeline ก็แก้เช่นกัน (`.replace(' ','T')`)

### UI: Move Last fetch to header
- `index.html` — ย้าย `footer-info` (Last fetch) จาก `<footer>` ไปแสดงที่ `<header>` ด้านขวา (margin-left:auto)
- `<footer>` เปลี่ยนเป็น hidden element เพื่อไม่ให้แสดงที่ด้านล่าง

### Deploy
รอ push + deploy

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

---

## 2026-05-27 — Fix: Telegram digest debug + sort + test button

### Root Cause (telegram ไม่ส่งตามเวลา)
ไม่สามารถยืนยัน root cause ได้โดยไม่มี container logs แต่ `_digest_job` silently skip เมื่อไม่มีบทความใหม่ที่มี `summary_th` ใน 6 ชั่วโมงล่าสุด เพิ่ม test endpoint เพื่อ diagnose ได้ทันที

### Fix 1 — `POST /api/digest/test` (ไม่ต้อง X-Admin-Token)
- Protected by nginx basic auth แทน
- Fallback ไป 24h window ถ้า 6h ว่าง
- Return diagnostic: `available_6h`, `available_24h`, `already_sent_ids`, `window_used`
- Log เข้า digest_log เหมือน scheduled job

### Fix 2 — News Timeline sort toggle
- `_newsSortNewest` flag + `toggleNewsSort()` function
- `_sortedNews()` helper reverse array เมื่อ oldest first
- ปุ่ม "🕐 Newest first / Oldest first" ใน search row

### Fix 3 — Test Digest button in Digest History
- ปุ่ม "📤 ส่ง Test Digest" ใน header ของ Past Digests card
- แสดงผลทันที: ส่งสำเร็จ/ไม่มีบทความ/error
- Auto-reload digest history หลังส่งสำเร็จ

### Tests
49/49 passed ✅
