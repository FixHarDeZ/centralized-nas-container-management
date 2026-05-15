# TorrentWatch — Daily Log

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

### Pending / Next Steps

- [ ] Cover image โหลดตรงจาก bearbit CDN — ถ้า session expire รูปแตกพร้อมกัน
