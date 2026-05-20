# TorrentWatch — Daily Log

---

### Session Log Entry
**Timestamp:** 2026-05-20 (session 3)
**Title:** Bug fix — Auto Sticky rows from viewno18sbx.php ไม่ถูก scrape

**Root Cause:**
`_parse_row()` detect sticky โดยดู `<img src>` ที่ match regex `sticky\.gif|heart\.gif|pinned\.gif` เท่านั้น แต่ `viewno18sbx.php` ใช้ text label **"Auto Sticky:"** แทน image → `is_sticky = False` → rows ถูก filter ออกด้วย date filter (sticky entries มี date เก่า)

**Fix (scraper.py:510):**
อัปเดต `is_sticky` detection เพิ่ม 3 check:
1. `img[src]` match `autosticky` (เผื่ออนาคต)
2. `img[alt]` match `sticky` (case-insensitive)
3. `NavigableString` match `auto\s*sticky` (จับ text node "Auto Sticky:")

**ไฟล์ที่แก้:**
- `scraper.py:510` — triple-check sticky detection

**หมายเหตุ:** ควรยืนยัน fix ด้วย `GET /api/debug/html?source_id=<id>` เพื่อดู HTML จริงของ sticky row บน viewno18sbx.php ว่าเป็น text node หรือ element อื่น

---

### Session Log Entry
**Timestamp:** 2026-05-20 (session 2)
**Title:** Clean up untracked dev artifact files

**งานที่ทำ:**
- ตรวจสอบ 5 untracked files ที่ค้างอยู่ใน working tree
- ยืนยันว่าไม่มีไฟล์ที่ tracked อ้างถึงเลย
- ลบทั้งหมด:
  - `torrentwatch/preview.html` — dev preview ที่สร้างช่วง redesign
  - `torrentwatch/bootstrap-icons-inline.css` — referenced เฉพาะ preview.html
  - `torrentwatch/check.png` — ไม่มี reference
  - `torrentwatch/preview-today.png` — ไม่มี reference
  - `maid-tracker/static/style.css.original` — backup ก่อน redesign
- Working tree clean หลังลบ

---

### Session Log Entry
**Timestamp:** 2026-05-20
**Title:** 6 Features — Cover Proxy, History Search, Global Search, Watched/Skip, Configurable Schedule, Stats Page

**Feature 1: Cover Image Proxy**
- **`scraper.py`**: `fetch_cover_bytes(cover_url)` — fetches image through authenticated session with Referer header + re-login retry on failure
- **`main.py`**: `GET /api/cover/{torrent_id}` — proxies cover bytes with `Cache-Control: max-age=3600`; guesses content-type from URL extension
- **`static/app.js`**: `cardHTML()` — added `data-proxy="/api/cover/{id}"` attribute + `onerror` fallback: try direct URL first, retry via proxy only on failure (zero overhead normally, transparent recovery on session expire)

**Feature 2: History Tab Search (within date) + Feature 9: Global Search (across all dates)**
- **`static/index.html`**: added `<input id="history-search-input">` search row in History panel (same style as Today tab)
- **`static/app.js`**:
  - `state.searchHistory` added to state
  - `loadHistory(date)` refactored: if `date=null` AND `q.length >= 2` → calls `GET /api/search?source_id=X&q=TEXT` (global); if `date=null` AND no query → shows placeholder; if date selected → filters client-side by `state.searchHistory`
  - Source chip click in history tab resets `state.searchHistory` + clears input
  - `history-date-select` onChange now calls `loadHistory(date || null)`
  - `history-search-input` input event calls `loadHistory(state.historyDate || null)`
- **`main.py`**: `GET /api/search?source_id=ID&q=TEXT&limit=50` — SQLite LIKE search, keyword-flagged, max 200 results
- **`db.py`**: `search_torrents(source_id, q, limit)` — `LIKE '%q%'` ordered by date DESC, seeds DESC

**Feature 3: Mark as Watched / Skip**
- **`db.py`**:
  - `watched_status INTEGER DEFAULT 0` added to CREATE TABLE + migration in `init_db()`
  - `mark_torrent_status(torrent_id, status)`: 0=none, 1=watched, 2=skip
- **`main.py`**: `POST /api/torrents/{id}/status` body `{status: 0|1|2}` → 204
- **`static/app.js`**:
  - `cardHTML()`: renders `tw-badge-watched` / `tw-badge-skipped` in `tw-card-dl-badges`; always renders the badges div (not conditional); card class includes `tw-card-watched` / `tw-card-skipped`; watch/skip buttons in actions row (eye + x-circle icons)
  - `attachCardActions()`: `.btn-watch` and `.btn-skip` handlers toggle status via API, sync badge + card class + sibling button state in-DOM (no re-render)
  - `_syncWatchBadge(card, status)`: removes old badge, appends new one

**Feature 4: Configurable Scheduler**
- **`db.py`**: added `scrape_interval_night: "30"` and `scrape_interval_day: "60"` to `_DEFAULT_SETTINGS`
- **`scheduler.py`**: `_minute_pattern(interval)` maps 15→"0,15,30,45", 20→"0,20,40", 30→"0,30", 60→"0"; `reload_scrape_job()` reads intervals from DB settings
- **`main.py`**: `PUT /api/settings` now calls `scheduler.reload_scrape_job()` after saving
- **`static/index.html`**: replaced static schedule text in Schedule card with two `<select class="tw-select-sm">` for night/day interval (options: 15/20/30/60 min)
- **`static/app.js`**: `loadSettings()` populates selects; save payload includes `scrape_interval_night` and `scrape_interval_day`

**Feature 7: Stats Page**
- **`db.py`**: `get_stats(source_id)` — aggregate query: total, dl_local, dl_nas, watched, skipped, by_category (top 20), by_date (last 14 days), by_source
- **`main.py`**: `GET /api/stats?source_id=ID` (optional source filter)
- **`static/index.html`**: Stats panel (`#panel-stats`) + 5th nav tab (สถิติ / bi-bar-chart-line)
- **`static/app.js`**: `loadStats()` + `_statsCard()` + `_statsBar()` helpers; renders summary grid (5 stat cards), 14-day activity bar chart, category breakdown, source breakdown — all CSS bars with dynamic widths

**CSS (`static/style.css`)**:
- `.tw-card-watched` / `.tw-card-skipped` — opacity dim + colored border overlay via `::after`
- `.tw-badge-watched` / `.tw-badge-skipped` — green/red badge tokens
- `.tw-action-btn.done-watch` / `.done-skip` — tinted action button states
- `.tw-select-sm` — styled `<select>` for schedule intervals
- Stats panel styles: `.tw-stats-scroll`, `.tw-stats-grid`, `.tw-stat-card`, `.tw-stats-section`, `.tw-stats-header`, `.tw-stats-bars`, `.tw-stats-bar-row`, `.tw-stats-bar-track`, `.tw-stats-bar-fill`, `.tw-stats-bar-count`

**Files Changed:** `db.py`, `scraper.py`, `main.py`, `scheduler.py`, `static/index.html`, `static/app.js`, `static/style.css`

---

### Session Log Entry
**Timestamp:** 2026-05-20
**Title:** Fix card thumbnail zoom (object-fit: cover → contain)

**ไฟล์ที่แก้ไข:**

- `static/style.css` — `.tw-card-thumb` เปลี่ยน `object-fit: cover` → `object-fit: contain` ให้รูปแสดงพอดีช่องแทนการ crop/zoom
- `static/index.html` — bump cache version `v=20260520a`

**หมายเหตุ:** เคยแก้แล้วครั้งก่อน (commit 366579e) แต่ redesign รอบล่าสุด revert กลับเป็น cover

---

### Session Log Entry
**Timestamp:** 2026-05-19
**Title:** UI Bug Fixes — Toast, Logo, Download Local

**ไฟล์ที่แก้ไข:**

- `static/index.html` — revert logo to Bootstrap icon `bi-broadcast`, bump cache version `v=20260519f`
- `static/style.css` — toast: `opacity+visibility` แทน `translateY`-only; logo: `flex-shrink:0`; `.tw-logo-icon` color accent
- `static/app.js` — download local: ลบ `pointer-events:none` (บล็อก `.click()`), blob size guard, DOM 30s cleanup, แสดง KB ใน toast

**Bugs แก้:**

1. Toast ค้างใน nav bar — translateY(80px) ไม่พอซ่อน (nav สูง 70px), แก้ด้วย opacity+visibility transition
2. Logo หาย — SVG/::before render ไม่ได้ cross-browser, revert เป็น Bootstrap icon ที่พิสูจน์แล้วว่าทำงาน
3. Download Local ไม่โหลดไฟล์ — `pointer-events:none` บน anchor บล็อก `.click()` dispatch

**Release:** v2.19.1

---

### Session Log Entry
**Timestamp:** 2026-05-18
**Title:** Database Schema — sort_order Migration for Source Reordering

**ไฟล์ที่แก้ไข:**

- **`db.py`**: 
  - `init_db()`: เพิ่ม migration `"ALTER TABLE sources ADD COLUMN sort_order INTEGER DEFAULT 0"` เข้าไป
  - `init_db()`: backfill `UPDATE sources SET sort_order = id WHERE sort_order = 0` สำหรับ existing sources
  - `get_sources()`: เปลี่ยน `ORDER BY id` → `ORDER BY sort_order ASC, id ASC`
  - `get_enabled_sources()`: เปลี่ยน `ORDER BY id` → `ORDER BY sort_order ASC, id ASC`
  - `add_source()`: คำนวณ `max_order = MAX(sort_order)` ก่อนแล้ว insert ด้วย `sort_order = max_order + 1` (new sources เข้าท้ายลิสต์)
  - `reorder_source()` (ใหม่): Swap sort_order กับ neighbor ตามทิศทาง "up"/"down"

**Verification:** test script ผ่านสี่ assertions:
1. Initial order [('a', 1), ('b', 2), ('c', 3)] ✓
2. Move first down: ['b', 'a', 'c'] ✓
3. Move last up: ['b', 'c', 'a'] ✓
4. All assertions passed ✓

**Commit:** `c40a36b` — feat(torrentwatch): add sort_order to sources — migration, backfill, reorder_source()

---

### Session Log Entry
**Timestamp:** 2026-05-18
**Title:** Frontend Redesign — Modern Minimal UI + Bottom Navigation

**ไฟล์ที่แก้ไข:**

- **`static/style.css`** (rewrite): Design system ใหม่ทั้งหมด — color palette เปลี่ยนจาก purple (`#818cf8`) เป็น indigo (`#6366f1`), bottom nav classes (`tw-bottom-nav`, `tw-nav-item`), card thumb ใช้ `object-fit: cover` + `box-shadow`, stats row ใหม่ (`tw-card-stats`, `tw-stat-val`, `tw-stat-sep`), kw-star badge absolute, settings ใช้ `tw-settings-scroll` + `tw-settings-body`, toast/go-top offset ใช้ `calc(var(--nav-h) + 12px)`
- **`static/index.html`** (rewrite): ย้าย nav จากด้านบน (`tw-tabs`) ไปด้านล่าง (`tw-bottom-nav`), search input ห่อใน `tw-search-wrap` พร้อม icon, settings รวม LINE + Telegram + Auto-DL เป็น Notification card เดียว, section title เปลี่ยนจาก `<div>` เป็น `<h2>` (accessibility), version bump → `v=20260518b`
- **`static/app.js`** (targeted edits): เปลี่ยน nav selector `.tw-tab` → `.tw-nav-item`, rewrite `cardHTML()` ใช้ stats row แทน badge row + `★ kw` absolute badge + detail link เป็น action ที่ 3, status badge แสดง `● scraping...` / `◉ idle`, `fmt()` helper สำหรับ k-format

**Bugs fixed ระหว่าง review:**
- `--surface1` stale CSS variable ใน Telegram result panel → แก้เป็น `--bg-elevated`
- Bottom nav ใช้ `position: sticky` ไม่ติดตอน scroll ลง → เปลี่ยนเป็น `position: fixed` + `calc(var(--nav-h) + 12px)` padding ใน list/settings
- `.tw-badge-cat` color `#818cf8` (old accent) → `#a5b4fc`
- `.tw-stat-sep` สี `var(--border)` มองไม่เห็น → `var(--text-dim)`
- `fmt()` ไม่ handle null/undefined/NaN → guard ด้วย `+n` + isNaN check

**Deploy:** `torrentwatch` container rebuilt + restarted บน NAS สำเร็จ

**Hotfix (หลัง deploy):** `object-fit: cover` → `object-fit: contain` บน `.tw-card-thumb` — ให้เห็นภาพทั้งหมดไม่ถูก crop (commit `366579e`)

---

### Session Log Entry
**Timestamp:** 2026-05-18
**Title:** Feature — Telegram Notification Support

**ไฟล์ที่แก้ไข:**

- **`telegram_notify.py`** (ใหม่): Telegram Bot API — `_send()`, `notify_keyword_matches()`, `send_test_message()`, `get_updates()` (ช่วย discover chat_id)
- **`config.py`**: เพิ่ม `TORRENTWATCH_TELEGRAM_BOT_TOKEN` + `TORRENTWATCH_TELEGRAM_CHAT_ID` env vars
- **`db.py`**: เพิ่ม `telegram_notify_keyword_enabled = "0"` ใน `_DEFAULT_SETTINGS`
- **`scheduler.py`**: import `telegram_notify`; อ่าน `telegram_notify_enabled` จาก settings; push Telegram หลัง LINE notify; เพิ่ม `telegram_configured` ใน `status()` dict
- **`main.py`**: import `telegram_notify`; เพิ่ม `POST /api/telegram/test` และ `GET /api/telegram/get-chat-id`
- **`static/index.html`**: เพิ่ม Telegram settings card (toggle, test button, get-chat-id button + result div); bump version string → `v=20260518`
- **`static/app.js`**: load/save `telegram_notify_keyword_enabled`; Telegram status hint; event handlers สำหรับ test + get-chat-id
- **`.env`**: เพิ่ม `TORRENTWATCH_TELEGRAM_BOT_TOKEN` (token ใส่แล้ว) + `TORRENTWATCH_TELEGRAM_CHAT_ID` (ต้องกรอก)

**วิธี Test:**

1. ใส่ Bot Token ใน `.env` แล้ว (เพิ่มแล้ว)
2. เปิด Settings → "ค้นหา Chat ID" → ส่งข้อความหา bot ก่อน → กดปุ่ม → copy chat_id มาใส่ `.env`
3. กด "ทดสอบส่ง Telegram" ตรวจสอบใน Telegram
4. เปิด toggle "เปิดใช้งาน" + บันทึก → จะส่งทุกครั้งที่พบ keyword match

---

### Session Log Entry
**Timestamp:** 2026-05-15
**Title:** Clean Code — Import hygiene, deduplication, private API elimination

- **`db.py`**: เพิ่ม `torrent_filename()` (shared utility), `clear_source_today()`, `clear_source_all()` (public API แทน `_conn()` ตรงๆ); เพิ่ม `import re` ที่ top
- **`main.py`**: ย้าย `re`, `quote`, `datetime`, `ZoneInfo` ขึ้น top; ลบ lazy imports ใน function body; ลบ `_torrent_filename` → `db.torrent_filename()`; `api_clear_*` ใช้ `db.clear_source_*`; `filter` param + `# noqa: A002`
- **`scraper.py`**: เพิ่ม `urlencode, parse_qs, urlunparse` ใน top import; ลบ lazy import ใน `_page_url`; fix COL alignment; extract `_is_torrent_content()` helper ลด duplicated logic 2 จุด
- **`scheduler.py`**: จัด import order (stdlib → third-party → local); ย้าย `urlparse` ออกจาก loop body; ลบ `import re` ที่ไม่ใช้; ลบ `_nas_filename` → `db.torrent_filename()`

---

### Session Log Entry
**Timestamp:** 2026-05-15
**Title:** Feature — Image Lightbox + Completed Downloads Sort

**Feature 1: Image display (bearbit style)**
- `style.css`: Changed `.tw-card-thumb` from `object-fit: cover` → `object-fit: contain` + `background: #000` — จะเห็นภาพทั้งหมดไม่ถูกครอป
- `style.css`: เพิ่ม lightbox overlay CSS (`.tw-lightbox`, `.tw-lightbox-img`, `.tw-lightbox-close`)
- `index.html`: เพิ่ม `<div id="lightbox">` overlay + close button
- `app.js`: เพิ่ม lightbox JS — click รูป (`[data-lightbox]`) → เปิด fullscreen; click overlay/close/Escape → ปิด
- `app.js`: เพิ่ม `data-lightbox` attribute บน `<img class="tw-card-thumb">` เพื่อ trigger lightbox

**Feature 2: Completed downloads (คนที่โหลดจบ) + sort**
- `scraper.py`: เพิ่ม `COL_COMPLETED = 9` — parse column 9 ของ bearbit (น่าจะเป็น completed/snatches count)
- `scraper.py`: parse และ return `completed` ใน dict ของ `_parse_row`
- `db.py`: เพิ่ม column `completed INTEGER DEFAULT 0` ใน CREATE TABLE + migration `ALTER TABLE`
- `db.py`: อัปเดต `upsert_torrent` — UPDATE และ INSERT รวม `completed`
- `db.py`: เพิ่ม `"completed": "completed DESC"` ใน `_sort_order()`
- `index.html`: เพิ่มปุ่ม sort "โหลดจบ" (data-sort="completed") ทั้ง Today และ History toolbar
- `app.js`: เพิ่ม `completedBadge` ใน `cardHTML()` — แสดงเมื่อ `completed > 0`
- `style.css`: เพิ่ม `.tw-badge-completed` (สีฟ้า #38bdf8) และ `.tw-completed-icon`

**หมายเหตุ**: COL_COMPLETED = 9 เป็น best guess จาก column ordering ของ bearbit — ถ้า scrape แล้วค่าเป็น 0 ทั้งหมด ให้เปลี่ยน column index ใน scraper.py

---

### Session Log Entry
**Timestamp:** 2026-05-12 11:19
**Title:** Sticky/Pinned Bug — Root Cause Analysis
**Details:**
- User reported newly pinned sticky torrents not being scraped (site shows 3, only 2 appear)
- Traced full flow: `scheduler → scraper.scrape_source → _parse_listing → _parse_row → db.upsert_torrent → db.sync_stickies`
- Found 4 distinct bugs causing sticky loss

---

### Session Log Entry
**Timestamp:** 2026-05-12 11:22
**Title:** Fix 1 — Default scrape_sticky changed from "0" to "1"
**Details:**
- [`db.py:13`](torrentwatch/db.py:13): Changed `_DEFAULT_SETTINGS["scrape_sticky"]` from `"0"` to `"1"`
- [`db.py:87-88`](torrentwatch/db.py:87): Added forced migration `UPDATE settings SET value='1' WHERE key='scrape_sticky' AND value='0'` — existing DBs with old default won't be updated by `INSERT OR IGNORE`

---

### Session Log Entry
**Timestamp:** 2026-05-12 11:23
**Title:** Fix 2 — Stickies now bypass seed/leech thresholds
**Details:**
- [`scraper.py:365-371`](torrentwatch/scraper.py:365): When `is_sticky=True`, entry is added to results immediately with `keyword_match` set, skipping `seeds==0` and `seed_min/leech_min` threshold checks
- Rationale: stickies are site-pinned for prominence — should not be filtered by arbitrary thresholds

---

### Session Log Entry
**Timestamp:** 2026-05-12 11:45
**Title:** Fix 3 — upsert_torrent UPDATE missing is_sticky/date_posted
**Details:**
- Discovered that a torrent previously scraped as non-sticky would never get promoted when bearbit later pins it
- [`db.py:206-213`](torrentwatch/db.py:206): UPDATE now includes `date_posted` and `is_sticky` columns (was only `seeds, leeches, last_updated_at`)
- [`db.py:166-172`](torrentwatch/db.py:166): Added promotion safety net in `sync_stickies` — entries in `seen_sticky_ids` with `is_sticky=0` get promoted

---

### Session Log Entry
**Timestamp:** 2026-05-12 11:55
**Title:** Fix 4 — Sticky detection regex typo: stickyt.gif → sticky.gif
**Details:**
- Original regex `stickyt\.gif` had an extra 't' — would only match `stickyt.gif`, not `sticky.gif`
- This explained why exactly 1 of 3 stickies was missing (2 used `heart.gif`, 1 used `sticky.gif`)
- [`scraper.py:400`](torrentwatch/scraper.py:400): Fixed to `sticky\.gif|heart\.gif|pinned\.gif`

---

### Session Log Entry
**Timestamp:** 2026-05-12 13:31
**Title:** Fix 5 — sync_stickies demotion tolerance for 1-time detection misses
**Details:**
- After fixes 1-4, all 3 stickies appeared on first scrape, but an old sticky disappeared on subsequent scrape
- Root cause: `sync_stickies` demoted immediately on single miss (set `date_posted=yesterday`)
- [`db.py:193-196`](torrentwatch/db.py:193): Demotion now only clears `is_sticky=0` without backdating `date_posted` — entry survives 1-2 missed detections, ages out naturally if truly un-pinned
- Added comprehensive debug logging in `_parse_row`, `_parse_listing`, `sync_stickies`, and scheduler for tracing

---

### Session Log Entry
**Timestamp:** 2026-05-12 14:38
**Title:** Created .notes/00_INDEX.md and daily_log.md
**Details:**
- Created `torrentwatch/.notes/` directory with project blueprint and daily log
- `00_INDEX.md` covers: overview, stack, file map, architecture decisions, known technical debt
- Formatted per Memory & Notion Sync Protocol for future Notion integration

---

### Session Log Entry
**Timestamp:** 2026-05-13 13:33
**Title:** Wired LINE Notifications — keyword match alerts now live
**Details:**
- [`config.py:18-20`](torrentwatch/config.py:18): Added `LINE_ACCESS_TOKEN` / `LINE_USER_ID` from env vars (`TORRENTWATCH_LINE_ACCESS_TOKEN`, `TORRENTWATCH_LINE_USER_ID`)
- [`scheduler.py:16`](torrentwatch/scheduler.py:16): Imported `line_notify` module
- [`scheduler.py:82-86`](torrentwatch/scheduler.py:82): `_do_scrape()` now captures `is_new` from `db.upsert_torrent()` and collects entries where `is_new=True AND keyword_match=True`
- [`scheduler.py:96-97`](torrentwatch/scheduler.py:96): Calls `line_notify.notify_keyword_matches()` per source when new keyword-matched entries are found
- [`scheduler.py:110-111`](torrentwatch/scheduler.py:110): Calls `line_notify.notify_round_summary()` at end of scrape cycle when `total_found > 0`
- [`env.example:122-126`](.env.example:122): Added `TORRENTWATCH_LINE_ACCESS_TOKEN` / `TORRENTWATCH_LINE_USER_ID` env var examples
- `line_notify.py` already had fully working `notify_keyword_matches()` and `notify_round_summary()` — just needed to be connected
- Docker compose already uses `env_file: ../.env`, so new vars are picked up automatically on next deploy

---

### Session Log Entry
**Timestamp:** 2026-05-13 14:05
**Title:** Added LINE toggle + test button in Settings UI
**Details:**
- [`db.py:15`](torrentwatch/db.py:15): Added `line_notify_keyword_enabled` to `_DEFAULT_SETTINGS` (default `"0"` — user must opt-in)
- [`line_notify.py:64-72`](torrentwatch/line_notify.py:64): Added `send_test_message()` — sends a test LINE message, returns `{"ok": True/False}`
- [`scheduler.py:57`](torrentwatch/scheduler.py:57): `_do_scrape()` now reads `line_notify_keyword_enabled` setting; both `notify_keyword_matches()` and `notify_round_summary()` are gated behind it
- [`main.py:17`](torrentwatch/main.py:17): Imported `line_notify`; added `POST /api/line/test` endpoint at line 330
- [`index.html:127-142`](torrentwatch/static/index.html:127): Added "LINE Notification" settings card with toggle switch + test button
- [`app.js:369`](torrentwatch/static/app.js:369): `loadSettings()` sets toggle state; save payload includes `line_notify_keyword_enabled`
- [`app.js:506-519`](torrentwatch/static/app.js:506): Test button handler — calls `POST /api/line/test`, shows toast on success/failure
- [`style.css:610-627`](torrentwatch/static/style.css:610): Added `.tw-btn-secondary` style for the test button

---

---

### Session Log Entry
**Timestamp:** 2026-05-14
**Title:** Fix scrape stuck-running bug + better progress display + category chip counts

**Scrape stuck-running bug fix (`scheduler.py`)**

- Root cause: `_do_scrape()` ไม่มี `try/finally` → ถ้า crash นอก per-source loop, `_scrape_status` ค้างที่ `"running"` ตลอด ทำให้ทุก click ตอบ `"already_running"` โดยไม่ทำอะไร
- [`scheduler.py`]: ครอบ body ของ `_do_scrape()` ด้วย `try/finally` → reset `_scrape_status="idle"` และ `_scrape_progress={}` เสมอ ไม่ว่าจะ crash

**Better scrape progress (`scheduler.py` + `app.js`)**

- [`scheduler.py`]: เปลี่ยน `source_label` จาก URL path fragment → ใช้ `source["label"]` (ชื่อจริงที่ user ตั้ง) เป็น fallback
- [`scheduler.py`]: `_scrape_progress` เพิ่ม field `source_idx` / `source_total` สำหรับแสดง N/M
- [`scheduler.py`]: `_update_progress()` รับ `source_idx` / `source_total` เพิ่ม
- [`scheduler.py`]: lambda `on_page` ใช้ default args (`_lbl`, `_idx`, `_tot`) แก้ closure bug ใน loop
- [`app.js`]: status badge แสดง `⟳ ชื่อ Source (1/2) — หน้า 3 พบ 15 รายการ`
- [`app.js`]: กด Scrape button → เรียก `updateStatusBadge()` ทันที → fast-poll 1.5s เริ่มเลย
- [`app.js`]: ลบ `setTimeout(() => btn.classList.remove("spinning"), 1500)` ออก → button spinning sync กับ status จริง (หยุดเมื่อ status = idle)

**Category chips with counts (`app.js`)**

- [`app.js`] `renderCategoryChips()`: นับ count per category จาก input list แสดงใน chip เช่น `JP ไม่เซ็น (8)`
- [`app.js`] `loadToday()`: restructure filter order — apply keyword/sticky/search ก่อน, ส่ง pre-category list ให้ `renderCategoryChips()`, แล้วจึง apply category filter → counts สะท้อน filter ที่ active อยู่จริง

---

---

### Session Log Entry
**Timestamp:** 2026-05-14
**Title:** Fix multi-source scrape: source 4 (Anime) ไม่เคย scrape ได้เลย

Root cause: `db.upsert_torrent`, `db.sync_stickies`, `line_notify.notify_keyword_matches` อยู่นอก per-source try/except → ถ้า source 1 (18+) throw ที่ขั้นตอนเหล่านี้ (เช่น LINE API timeout, DB error), loop หยุดเลย source 4 ไม่เคยเริ่ม

Diagnostic: เพิ่ม `GET /api/debug/parse-test/{source_id}` ชั่วคราว → confirm scraper parse ถูก (`entries_real_settings: 8`), `details.php` link มีอยู่, column mapping + date ถูกทุกอย่าง → ปัญหาอยู่ที่ scheduler loop ไม่ใช่ scraper

Fix (`scheduler.py`):

- wrap `db.upsert_torrent` per-entry ด้วย try/except → error ของ entry หนึ่งไม่กระทบ entries อื่น
- wrap `db.sync_stickies` ด้วย try/except แยก
- wrap `line_notify.notify_keyword_matches` ด้วย try/except แยก
- ผล: แต่ละ source ทำงาน independently ไม่ว่า source 1 จะ fail ที่ขั้นไหน source 4 ก็ยังวิ่งต่อได้

Fix (`scraper.py`):

- เพิ่ม fallback selector สำหรับ title link — ถ้าไม่เจอ `details\.php` จะหา anchor ที่มี `<b>` child และ `?id=\d+` ใน href (รองรับ listing pages อื่นที่ใช้ PHP filename ต่างกัน)
- viewno18sbx.php ใช้ `details.php` เหมือนกัน แต่ fallback ป้องกัน future sources

---

---

### Session Log Entry
**Timestamp:** 2026-05-14
**Title:** Fix first-scrape-of-day returning 0 items — stale connection after overnight idle

Root cause: `_fetch` จะ return `None` ทันทีเมื่อ connection exception เกิดขึ้น โดยไม่มี retry ทำให้ scrape รอบแรกหลัง pause 01:00-06:00 (5 ชั่วโมง idle) fail เงียบๆ 0 items ทั้งที่ bearbit มี torrent ใหม่ผ่าน filter เพียบ

Fix (`scraper.py`):

- `_fetch`: เมื่อเกิด transport exception → re-login แล้ว retry request 1 ครั้ง แทนที่จะ return `None` ทันที
- เพิ่ม `relogin()` function (`global _login_ok = await _login()`) สำหรับ scheduler เรียก

Fix (`scheduler.py`):

- `_do_scrape()`: เรียก `await scraper.relogin()` ทุกครั้งก่อนเริ่ม loop sources เพื่อ establish fresh session ก่อน scrape แต่ละรอบ
- ถ้า relogin fail → return ภายใน try block (finally ยัง reset `_scrape_status = "idle"` เสมอ)

---

---

### Session Log Entry
**Timestamp:** 2026-05-18
**Title:** Feature — Source Reorder (↑↓) + File Size Colored Badge

**Feature 1: Source Reorder**

- **`db.py`**:
  - `CREATE TABLE sources`: เพิ่ม `sort_order INTEGER DEFAULT 0` ใน DDL
  - migration loop: เพิ่ม `"ALTER TABLE sources ADD COLUMN sort_order INTEGER DEFAULT 0"`
  - backfill: `UPDATE sources SET sort_order = id WHERE sort_order = 0`
  - `get_sources()` + `get_enabled_sources()`: เปลี่ยน `ORDER BY id` → `ORDER BY sort_order ASC, id ASC`
  - `add_source()`: คำนวณ `max_order = MAX(sort_order)` insert ด้วย `sort_order = max_order + 1`
  - `seed_default_sources()`: เพิ่ม `sort_order` ใน INSERT ด้วย `enumerate(urls, start=1)`
  - `reorder_source(source_id, direction)` (ใหม่): swap sort_order กับ nearest neighbor ทิศ "up"/"down"
- **`main.py`**:
  - `from typing import Literal` เพิ่ม import
  - `SourceReorder(BaseModel)` model ใหม่: `direction: Literal["up", "down"]`
  - `POST /api/sources/{source_id}/reorder` endpoint ใหม่ — returns updated sources list
- **`static/app.js`**:
  - `renderSourcesList()`: เปลี่ยน `.map(s =>` → `.map((s, i) =>` + เพิ่ม ↑↓ chevron buttons
  - ↑ disabled เมื่อ `i === 0`, ↓ disabled เมื่อ `i === sources.length - 1`
  - event handler `.src-reorder`: เรียก `POST /api/sources/{id}/reorder` → `await loadSources()` → `loadSettings()`

**Feature 2: File Size Colored Badge**

- **`static/style.css`**:
  - `.tw-badge-size` — `font-size: 12px; font-weight: 700; padding: 2px 7px` (companion class กับ `.tw-badge`)
  - `.tw-badge-size-sm` — gray `rgba(107,114,128,0.15)` / `#9ca3af` (MB หรือ <1 GB)
  - `.tw-badge-size-md` — amber `rgba(245,158,11,0.15)` / `#f59e0b` (1–4.9 GB)
  - `.tw-badge-size-lg` — red `rgba(239,68,68,0.15)` / `#ef4444` (≥5 GB)
  - `.tw-btn-icon:disabled` — `opacity: 0.3; cursor: not-allowed; pointer-events: none` (bonus fix)
- **`static/app.js`**:
  - `sizeClass(s)` helper (ก่อน card renderer section): parse GB จาก string → return tier class
  - `cardHTML()`: เปลี่ยน `tw-stat-sep + tw-stat-lbl` → `<span class="tw-badge tw-badge-size ${sizeClass(...)}">`

**Commits:**
- `c40a36b` feat(torrentwatch): add sort_order to sources — migration, backfill, reorder_source()
- `53b1b1b` fix(torrentwatch): seed_default_sources with sort_order + add sort_order to CREATE TABLE DDL
- `f6592a6` feat(torrentwatch): add POST /api/sources/{id}/reorder endpoint
- `8110d2b` fix(torrentwatch): use Literal type for direction + explicit status_code=200
- `2c85ea0` feat(torrentwatch): source reorder ↑↓ buttons in Settings
- `50b5fc3` feat(torrentwatch): file size colored badge — gray/amber/red by tier

**Pushed to:** `origin/main` (15cbe43 → 50b5fc3)

---

### Pending / Next Steps

- [ ] Cover image โหลดตรงจาก bearbit CDN — ถ้า session expire รูปแตกพร้อมกัน
