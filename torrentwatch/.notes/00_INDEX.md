# TorrentWatch — Project Index (Memory Blueprint)

> อัปเดตล่าสุด: 2026-06-24 (notify transport → shared Notifier)
> ใช้ไฟล์นี้เป็น cold-start memory ก่อนเริ่มงานทุกครั้ง

> **2026-06-24 — Notifier:** `line_notify._push` / `telegram_notify._send` สลับ body เป็น
> `await asyncio.to_thread(_N.send, text)` โดย `_N` = shared `Notifier` จาก `shared/notify.py`
> (vendored = `notify.py`, `make sync-shared`). ไม่ merge 2 module — toggle แยกอิสระคงเดิม.
> `send_test_message`/`get_updates` ยังเป็น httpx. ดู daily_log 2026-06-24.

---

## Overview

TorrentWatch เป็น FastAPI app สำหรับ monitor torrent ใหม่จาก bearbit.org โดยอัตโนมัติ — scrape ตามตารางเวลา, filter ตาม seed/leech threshold และ keyword, แสดงผ่าน dark-theme web UI, ดาวน์โหลดได้ทั้งไปที่ browser และ NAS watch folder รันเป็น Docker container บน Synology DS925+

---

## Tech Stack

| Component | Detail |
|---|---|
| Runtime | Python 3.12 · FastAPI · Uvicorn |
| Database | SQLite (WAL mode) — `/data/torrentwatch.db` |
| Scraper | httpx async client + BeautifulSoup4 |
| Scheduler | APScheduler `BackgroundScheduler` |
| Frontend | Vanilla JS SPA + Bootstrap Icons (no framework) |
| Auth | HTTP Basic Auth (shared creds กับ homepage) |

---

## Ports

| Context | Port |
|---|---|
| Container internal | `8000` |
| NAS host (LAN) | `5059` |
| Synology Reverse Proxy (HTTPS external) | `15059` |

URL pattern:
- LAN: `http://192.168.x.x:5059`
- External: `https://<NAS_HOST>:15059`

> Ports 5060/5061 ใช้ไม่ได้ (blocked by browsers, SIP protocol)

---

## File Map

```
torrentwatch/
├── main.py          — FastAPI app + all API routes + Basic Auth middleware
├── config.py        — env var reads (SITE_*, DATA_DIR, BASIC_AUTH_*, LINE_*)
├── db.py            — SQLite CRUD: sources, torrents, keywords, settings, cleanup
├── scraper.py       — async httpx scraper: login, fetch, parse, paginate
├── scheduler.py     — APScheduler jobs: scrape + weekly cleanup + H&R check
├── hr.py            — myhr.php (Hit & Run) parser + risk split + push body
├── line_notify.py   — LINE Messaging API push (⚠️ NOT wired to scheduler yet)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── static/
    ├── index.html   — SPA shell (tabs: วันนี้, ประวัติ, รอบทำงาน, Keyword, สถิติ, ตั้งค่า, H&R)
    ├── app.js       — all frontend logic (fetch, render, state)
    └── style.css    — dark theme CSS variables
```

---

## Environment Variables (root `.env`)

| Variable | Purpose |
|---|---|
| `TORRENTWATCH_SITE_USERNAME` | bearbit.org login username |
| `TORRENTWATCH_SITE_PASSWORD` | bearbit.org login password |
| `TORRENTWATCH_DEFAULT_URLS` | comma-separated listing URLs (seed DB on first start) |
| `NAS_TORRENT_PATH` | host path → mounted to `/downloads` inside container |
| `NGINX_BASIC_AUTH_USER` | Basic Auth username (shared with homepage) |
| `NGINX_BASIC_AUTH_PASS` | Basic Auth password |

| `TORRENTWATCH_TELEGRAM_BOT_TOKEN` | Telegram Bot Token จาก @BotFather |
| `TORRENTWATCH_TELEGRAM_CHAT_ID` | Chat ID ปลายทาง (ค้นหาจากปุ่มใน Settings UI) |

---

## Database Schema

### `sources`
```sql
id, url (UNIQUE), label, enabled, sort_order (DEFAULT 0), created_at
```
**New in v2:** `sort_order` allows users to reorder sources via UI ↑↓ buttons. Migration backfills existing sources with `sort_order = id`. `get_sources()` / `get_enabled_sources()` now order by `sort_order ASC, id ASC`. New sources get `sort_order = MAX(sort_order) + 1`. Function `reorder_source(source_id, direction)` swaps with nearest neighbor.

### `torrents`
```sql
id, source_id (FK), site_id, title, detail_url, torrent_url,
cover_url, seeds, leeches, date_posted, posted_at, category,
file_count, file_size, completed, free_leech, multiplier, is_sticky, first_seen_at, last_updated_at,
downloaded_local, downloaded_nas,
watched_status    -- 0=none, 1=watched, 2=skip
sticky_notified   -- 0=ยังไม่ notify, 1=notify แล้ว (added 2026-05-21)
UNIQUE(source_id, site_id)
```

### `keywords`
```sql
id, source_id (FK), keyword, created_at
UNIQUE(source_id, keyword)
```

### `settings`
```sql
key (PK), value
```

Default settings:
- `seed_min = "10"` — seed threshold
- `leech_min = "10"` — leech threshold
- `completed_min = "20"` — completed/snatches threshold (0 = ปิดใช้ใน AND mode)
- `filter_mode = "or"` — "and" | "or"
- `scrape_sticky = "1"` — รวม sticky หรือไม่ (default เปลี่ยนเป็น "1" เมื่อ 2026-05-12)
- `retention_days = "7"` — จำนวนวันเก็บ record ก่อน cleanup
- `line_notify_keyword_enabled = "0"` — push LINE เมื่อพบ keyword match
- `auto_download_nas = "0"` — auto-save keyword match ไป /downloads
- `scrape_interval_night = "30"` — interval (นาที) ช่วง 19:00–01:00 (15/20/30/60)
- `scrape_interval_day = "60"` — interval (นาที) ช่วง 06:00–19:00 (15/20/30/60)
- `notify_sticky_enabled = "0"` — push LINE+Telegram เมื่อพบ sticky/pinned torrent ที่ยังไม่เคย notify (sticky_notified=0)
- `hr_notify_enabled = "0"` — push Hit & Run digest (default "0" แต่บน NAS เปิด "1" ไว้แล้วตั้งแต่ 2026-07-26)
- `hr_slack_hours = "24"` — เตือนเมื่อ slack (เวลาเหลือหลังหัก seed ที่ยังขาด) ต่ำกว่านี้
- `hr_autofix_enabled = "0"` — ถาม Telegram ก่อน re-add ไฟล์ H&R ที่ task ใน DS หายไป (บน NAS เปิด "1" ไว้แล้วตั้งแต่ 2026-07-27)
- `hr_fix_stale_hours = "24"` — tracker ไม่เห็น client เกินนี้ = ถือว่า task ใน Download Station หายแล้ว
- `hr_report_enabled = "0"` — รายงานสถานะ H&R ทุกไฟล์เข้า Telegram วันละครั้ง (บน NAS เปิด "1" ไว้แล้วตั้งแต่ 2026-08-02)
- `hr_report_time = "09:00"` — เวลาส่งรายงานรายวัน (`HH:MM`) — ค่าพังตกไปที่ 09:00 ไม่ raise เพราะ parse เกิดใน PUT /api/settings ถ้า raise จะไม่เหลือ job เลย

**Internal meta keys** (settings table, ไม่ผ่าน UI, อ่าน/เขียนด้วย `get_meta`/`set_meta`):
- `tg_last_update_id` — offset ล่าสุดของ getUpdates long-poll (hr_fix.poll_loop)
- `hr_last_digest` — sha1 (16 ตัว) ของ set ที่ actionable (risky+hit) รอบล่าสุด — เท่ากันแปลว่าไม่มีอะไรเปลี่ยน ข้าม push. เคลียร์เป็น "" เมื่อไม่มีรายการเสี่ยงเลย
- `free_all_notified_date` — วันที่ push "ทุก torrent ฟรี 100%" ไปแล้ว (กัน notify ซ้ำต่อวัน). Sitewide-free notify ทำงานเสมอ (ไม่มี toggle): scheduler นับ pre-filter `today_total`/`today_free` ต่อรอบ scrape → ยิงเมื่อ `today_free == today_total > 0`

### `runs`
```sql
id (PK), job, started_at, duration_s, ok, summary (JSON), error
```
หนึ่งแถวต่อการรันหนึ่งรอบของ job (`scrape` / `hr` / `cleanup` / `backup`). เขียนผ่าน `scheduler._record(job, trigger)` ซึ่งเป็น contextmanager: **กลืน exception** แล้วบันทึกเป็น `ok=0` + `error` เสมอ (รอบที่ล้มแล้วไม่เหลือแถวคือรอบที่อยากดูที่สุด) และรับ "soft error" ผ่าน `box["error"]` สำหรับกรณีที่ job return เฉยๆ เช่น relogin fail. `summary` เก็บ JSON ต่อ job — scrape: `sources/found/new/source_errors/rows_today/free_today`, hr: `total/risky/hits/seeding/sent`, cleanup: `days/deleted/runs_deleted`, backup: `file/retention_days`; ทุกอันมี `trigger` = `auto|manual`. **`check_hr` ที่ปิด toggle ไว้ return ก่อนเข้า `_record`** ไม่งั้นวันละ 2 แถว fail ปลอมกลบของจริง. เหตุผลที่ต้องลงตาราง: `_last_scrape`/`_scrape_status` เป็น module global ที่ deploy ทีเดียวหายหมด. Retention ใช้ `retention_days` (ขั้นต่ำ 14 วัน) ตัดใน `_cleanup_job` 03:00 เดิม ไม่เพิ่ม cron ใหม่. แท็บ "รอบทำงาน" แบ่ง `hr_fixes` จาก `/api/runs` เป็นสองบล็อก: สถานะที่ยังรอกดปุ่มใน Telegram (`pending`/`del_asked`/`del_confirm` = `HRFIX_WAITING` ใน `app.js`) อยู่บล็อกบนอย่างเดียว บล็อก "H&R actions ล่าสุด" ข้างล่างโชว์เฉพาะที่จบแล้ว ไม่งั้นแถวเดียวกันโผล่สองที่. เวลาทุกแถวเรนเดอร์ผ่าน `_fmtWhen()` ที่บังคับ `timeZone: "Asia/Bangkok"` — `hr_fixes` เก็บ ISO มี offset `+07:00` ส่วน `runs.started_at` เก็บ naive Bangkok (เติม `+07:00` ก่อน parse) การตัดสตริงดิบแบบเดิมโชว์ `07-27T00:48` อ่านเหมือน UTC

Index: `idx_torrents_source_date ON torrents(source_id, date_posted)`, `idx_runs_started ON runs(started_at DESC)`

---

## Scraper Logic

### Login Flow
1. GET `LOGIN_URL` → parse hidden form fields (CSRF etc.)
2. POST ด้วย `username` + `password` + hidden fields
3. ตรวจ response URL — ถ้า redirect กลับ login page = failed
4. Auto re-login เมื่อ session expire ระหว่าง scrape

### Listing Selectors (scraper.py top constants)
```python
ROW_SELECTOR  = "tr[data-category-id]"
COL_COVER     = 1    # <img src="..."> (absolute URL, ไม่ใช่ categories icon)
COL_TITLE     = 2    # <a href="details.php?id=X&hashinfo=Y"><b>title</b></a>
COL_FREE      = 3    # ฟรี — "100%"/"50%"/"No" → free_leech (keeps %-text, else "")
COL_MULTIPLIER= 4    # คูณ — "x6"/"No" → multiplier (keeps xN, else "")
COL_FILES     = 5    # file count
COL_DATE      = 6    # <nobr>DD-MM-YYYY<BR>HH:MM:SS</nobr>
COL_SIZE      = 7    # "2.63 GB" / "380.60 MB"
COL_COMPLETED = 8    # completed/snatches count ("N คน")
COL_SEEDS     = 9    # <span class="green|red">N</span>
COL_LEECHES   = 10
# col 11 = ผู้ปล่อยไฟล์ (uploader name) — new col as of 2026-07-05, unused
```
⚠️ **ทุกคอลัมน์ตั้งแต่ `วันลง` เลื่อนได้ทั้งชุดถ้า bearbit เพิ่ม/ลดคอลัมน์อีก** (เกิดแล้วรอบนี้ตอน 05-07-2026 — เพิ่ม uploader col ต่อท้าย ดันคอลัมน์ก่อนหน้าเลื่อนซ้าย 1) — ถ้าเจอ badge โชว์ค่าประหลาด (เช่น "N คน" แทนขนาดไฟล์) ให้ probe live ผ่าน authed session ก่อนแก้ (ดู `.notes/daily_log.md` 2026-07-05 สำหรับ probe script pattern)
Download URL: ~~`download.php?id={site_id}`~~ **ตายแล้ว (404, มิ.ย. 2026)**. bearbit ย้ายไป `downloadnew.php?id=X&genid=..&dltm=..&dlt=<token>&filename=..` — token สดต่อ session → ต้อง `resolve_download_url(detail_url)` ดึงลิงก์จากหน้า detail ทุกครั้ง (stored `torrent_url` ใช้ไม่ได้แล้ว). **⚠️ Download gates (2 ชั้น, handle ใน `_fetch_via_gate`):** (1) **ad-gate interstitial** (ก.ค. 2026) — `downloadnew.php` คืนหน้า HTML countdown, ปุ่มจริง `a#bbDlBtn` href มี `&adok=1&adt=..`, server บังคับรอ ≥5 วิ (cookie `bb_vlast`) → sleep `AD_GATE_WAIT_S=7` แล้วยิงปุ่ม; (2) **inbox PM gate** — ถ้าไม่ใช่ ad-gate + ไม่ใช่ torrent → `GET /inbox.php` เคลียร์ unread แล้ว retry ครั้งเดียว. ⚠️ download ช้าลง ~7 วิ/ไฟล์

### Filter Logic
- `seeds == 0` → ทิ้งเสมอ
- Sticky entries → **bypass threshold** (เพิ่มเข้า result โดยตรง)
- Non-sticky: ต้อง keyword match **OR** ผ่าน threshold ตาม filter_mode
- `filter_mode=or` → seeds≥min **หรือ** leeches≥min **หรือ** completed≥min
- `filter_mode=and` → seeds≥min **และ** leeches≥min **และ** completed≥min
  - ⚠️ `completed_min=0` = ปิดเงื่อนไข completed ใน AND mode (ไม่ require)

### Multi-page Scraping
- ไล่ `?page=0,1,2,...` สูงสุด 20 หน้า (safety cap)
- หยุดเมื่อพบ `date_posted < today` หรือ `items == []`

### Sticky Sync
- แต่ละ scrape เก็บ `seen_sticky_ids` (site_id ทุกตัวที่เป็น sticky บน bearbit)
- `db.sync_stickies()`: ถ้า site_id ยังอยู่ → refresh `date_posted=today`; ถ้าหายไป → clear `is_sticky=0` (ไม่ backdate)
- Sticky detection: regex `sticky\.gif|heart\.gif|pinned\.gif` บน `<img src>`

### Sticky Detection (scraper.py:510)
```python
# Triple-check: image src, image alt, or text label "Auto Sticky:"
is_sticky = bool(
    row.find("img", src=re.compile(r"sticky\.gif|heart\.gif|pinned\.gif|autosticky", re.I))
    or row.find("img", alt=re.compile(r"sticky", re.I))
    or row.find(string=re.compile(r"auto\s*sticky", re.I))
)
```
Bug fix 2026-05-20: viewno18sbx.php ใช้ text "Auto Sticky:" แทน image → rows ไม่ถูก detect เป็น sticky → ถูก drop ด้วย date filter (date เก่า)

### Category Mapping
```python
"901"→"H Anime", "902"→"H Game", "903"→"JP เซ็น", "904"→"JP ไม่เซ็น",
"905"→"ฝรั่ง", "906"→"เอเชียเซ็น", "907"→"เอเชีย", "908"→"Gay",
"910"→"คลิป", "911"→"รูป", "912"→"นิตยสาร"
```

---

## Scheduler

| Job | Schedule (Asia/Bangkok) | Description |
|---|---|---|
| `scrape_night` | 19:00–01:00 ทุก 30 นาที | scrape รอบกลางคืน (เวลา active) |
| `scrape_day` | 06:00–19:00 ทุก 60 นาที | scrape รอบกลางวัน |
| `cleanup` | ทุกวัน 03:00 + ตอน startup | ลบ records > `retention_days` วัน (default 7) |
| `hr_check` | ทุก 6 ชม. (03:10/09:10/15:10/21:10) | อ่าน myhr.php → เช็คไฟล์ที่พ้น H&R + ถาม auto-fix → push LINE+Telegram ไฟล์เสี่ยง (dedup ด้วย `hr_last_digest`) |

**การเรียงในแท็บ H&R** — ปุ่ม `.tw-sort-btn` ใน `#hr-sort` (reuse ชุดเดียวกับแท็บวันนี้/ประวัติ) → `state.sort.hr` → map `HR_SORTS` ใน `app.js`: `slack` (default, ใกล้ครบกำหนดขึ้นก่อน), `remaining` (ขาด seed อีกน้อยสุด), `seen` (`last_seen_h` มาก→น้อย = ไม่เห็น client นานสุดขึ้นก่อน), `finished` (`finished_at` string compare desc — format `%Y-%m-%d %H:%M` เรียงเป็น lexicographic ได้เลย). ค่า null จมล่างสุดทุกโหมด (`?? Infinity` / `?? -Infinity` ตามทิศ). **`loadHr()` ถูกผ่าเป็น fetch + `_renderHr()` แล้วแคชไว้ที่ `_hrData`** — เปลี่ยน sort ต้องไม่ยิง `/api/hr` ใหม่ เพราะ endpoint นั้น scrape myhr.php สดทุกครั้ง (กด sort รัวๆ = ยิง tracker รัวๆ). error path ก็ย้ายมาอยู่ใน `_renderHr()` (`_hrData` เป็น null)

**เวลาที่ดึงข้อมูล** — `/api/hr` scrape สดทุกครั้งที่เรียก จึงส่ง `fetched_at` = `datetime.now(_TZ)` (`_TZ` = Asia/Bangkok ที่ `main.py:139`) format `%Y-%m-%d %H:%M:%S` — ต่างจาก `_last_scrape` ของ scheduler ที่ตัดวินาที เพราะอันนี้อยู่หลังปุ่ม refresh มือ กด 2 ครั้งในนาทีเดียวต้องเห็นเลขขยับ. `loadHr()` เรนเดอร์ใน header ของบล็อก "รายไฟล์" (`.tw-hr-fetched`, `margin-left:auto`) ไม่แตะ `index.html` — path error จึงไม่ค้าง timestamp เก่า. ห้ามใช้ `datetime.now()` เปล่า จะเป็น UTC เพี้ยนจาก "อัปเดตล่าสุด" ที่หัว dashboard 7 ชม.

**Badge ผู้ปล่อยไฟล์/free/คูณ** — `myhr.php` ไม่มีคอลัมน์พวกนี้ `db.attach_badges(rows)` จึง join กลับตาราง `torrents` ด้วย `site_id` แล้วยัด `free_leech`/`multiplier`/`uploader` + สตริงสำเร็จรูป `badges` (จาก `db.badge_text()`) ลงทุกแถว. เรียกจุดเดียวก่อน `hr.summarize()` ทั้งใน `scheduler._check_hr_once` และ `main.api_hr` เพื่อให้ digest / ปุ่ม auto-fix / แท็บ H&R ใช้ข้อมูลชุดเดียวกัน — `hr.py` ไม่ import db (คง self-check ให้รันเดี่ยวได้) แค่พิมพ์ `r["badges"]` เมื่อมี. ฝั่ง listing `db.badge_text()` ถูกใช้ผ่าน `_item()` ใน `line_notify.py`/`telegram_notify.py` (keyword + sticky noti). DB เก็บคอลัมน์คูณดิบเป็น `x6` ส่วน UI แปลงเป็น `UPLOAD 6X` ด้วย `multLabel()` ให้ตรงกับที่เว็บพิมพ์. ⚠️ `torrents` เป็น `UNIQUE(source_id, site_id)` ไม่ใช่ unique ที่ `site_id` เดี่ยวๆ แต่แถวจาก `myhr.php` ไม่มี `source_id` ให้ filter — `badges_by_site_ids` เลยใส่ `ORDER BY id` ให้แถวใหม่สุดชนะแบบคาดเดาได้ ไม่ปล่อยให้ planner เลือกเอง (ไม่งั้นแจ้งชื่อผู้ปล่อยไฟล์ผิดได้). `hr_fix.apply_fix()` re-parse myhr.php เองโดยไม่เรียก `attach_badges` — ตอนนี้ไม่พิมพ์ badge เลยไม่มีปัญหา ถ้าจะเพิ่มต้อง enrich ก่อน

**⚠️ auto-fix/cleared ต้องอยู่เหนือ dedup:** `check_hr()` มี early-return เมื่อ `hr_last_digest` ไม่เปลี่ยน — set เสี่ยงนิ่งเป็นวันๆ ดังนั้นอะไรที่วางใต้บรรทัดนั้นจะไม่รันเลยใน production (force=True ตอนเทสต์จะผ่าน หลอกได้). `hr_fix.check_cleared()` + `hr_fix.scan_and_prompt()` เลยเรียกทันทีหลัง `summarize()`

**ตาราง `hr_seen`** — snapshot แถวล่าสุดของทุกรายการบน myhr.php (`site_id` PK, seeded/target/remaining/state/seen_at) เขียนทับทุกรอบที่อ่านหน้า. มีไว้เพราะ **bearbit ลบแถวออกจากหน้าทันทีที่ seed ครบภาระ** ส่วนเราอ่านวันละ 2 รอบ = แทบไม่เคย sample เห็น `48.0/48.0` ตอนยังอยู่บนหน้า (นี่คือเหตุผลที่ `check_cleared` ไม่เคยยิงเลย และ `hr_fixes` ค้างที่ `fixed` ถาวร). `hr_fix.check_vanished()` เทียบ snapshot กับหน้าปัจจุบัน: แถวที่หายไปแล้ว **(ที่ยังขาด − ชม.ที่ผ่านไปตั้งแต่ snapshot) ≤ 2 ชม.** — ไฟล์ยัง seed ต่อหลัง sighting สุดท้าย เวลาที่ผ่านไปจึงหักหนี้ได้ (tolerance คงที่ 2 ชม. แบบเดิมเขียนทิ้งเงียบๆ ทุกไฟล์ที่ขาด 2–12 ชม.); `seen_at` อ่านไม่ได้ = ไม่หักอะไร ตกกลับไปใช้ 2 ชม. แบบเดิม; **หักได้สูงสุด 13 ชม.** (`_MAX_CREDIT_H`) เพราะ fetch พัง = return ก่อนถึง `hr_seen_snapshot` snapshot จึงค้าง ถ้าไม่ cap ไว้ snapshot เก่า 2-3 วันจะทำให้ทุกแถวที่หายผ่านหมด รวมถึงแถวที่กลายเป็น `hit` ระหว่างนั้น (snapshot ยังจำเป็น `warn`) และ state ไม่ใช่ `hit` → ถือว่าพ้น H&R, set `cleared` (ไฟล์ที่ไม่เคยผ่าน auto-fix ใช้ `db.hr_fix_add_cleared()` แทรกแถวใหม่ ไม่งั้นไม่มีวันได้คำถามลบ เพราะ flow ลบผูกกับตาราง `hr_fixes` ล้วนๆ) แล้วยิงคำถามลบ; ขาดเกินนั้น = แถวหายด้วยเหตุอื่น ทิ้ง log ไว้ ไม่ถือว่าครบ (ลบถาวร ไม่เข้า #recycle จึงห้ามเดา). **`rows == []` return 0 ทันที** — `parse_hr` คืน `[]` ทั้งกรณี fetch พังและหน้าโล่ง จะอ่านเป็น "ครบทั้งหน้า" ไม่ได้. LINE/Telegram "พ้น Hit & Run" ส่งเฉพาะไฟล์ที่ผ่าน auto-fix (`fixed`/`stalled`) ไฟล์ที่ seed ครบเองไปคำถามลบตรงๆ ไม่งั้นวันละสิบ push.

**เช็ค DS ก่อนถามลบ**: `check_vanished` เรียก `hr_fix.ds_tasks()` ครั้งเดียวต่อรอบ แล้ว `dsm.find_task()` ต่อแถว — เจอ = ถามลบ, ไม่เจอ = `cleared` + note ไม่ถาม (torrent ที่โหลดจากมือถือ/client อื่น ไม่มีไฟล์ของเราให้ลบ), DS ล่ม = ไม่ตัดสิน คา snapshot ไว้. guard นี้ delete-only ห้ามแตะ `hr.fix_candidates()`. snapshot ที่ไม่มี title (fallback เป็น `site_id`) นับเป็นเคส "ถามไม่ได้" เช่นกัน — ไม่มีชื่อให้ `find_task` เทียบ จึงห้ามตัดเป็น "ไม่อยู่ใน DS" ต้องเก็บ snapshot ไว้รอบหน้า. เคสไม่เจอ task ส่ง Telegram แจ้ง (ไม่มีปุ่ม) ว่าให้ไปลบเองที่ client ที่โหลดมา.

**หมายเหตุ match task**: `hr_seen.title` = `torrents.title` เป๊ะ และ scraper เขียน `db.torrent_filename(title)` ลง `/downloads` → DS คืนค่าเดิมใน `uri` ⇒ `dsm.find_task()` ใช้ได้กับไฟล์ที่ seed ครบเอง ไม่ต้องมี match key เพิ่ม. ไฟล์ที่ task ถูกลบจาก DS ไปแล้วจบที่ `del_failed` (ไม่เดา path). `check_vanished` ลืม snapshot เฉพาะตอนงานจบจริง — ส่ง Telegram ไม่ผ่านให้คา `cleared` ไว้ retry รอบหน้า.

**แท็บ "ประวัติ" ใน H&R** — ปุ่มสลับ `#hr-view` (live/history) ซ่อน `#hr-sort-bar` ตอนอยู่โหมดประวัติ; โหมดประวัติอ่าน `/api/hr/history` แล้วแบ่ง "รอพี่กดใน Telegram" (`HRFIX_WAITING`) กับ "จบแล้ว" ใช้ `_hrFixRow` ตัวเดียวกับแท็บรอบทำงาน. `_hrFixRow` โชว์ `note` แล้ว — `note` คือสิ่งเดียวที่แยก "รอยืนยันลบ" ออกจาก "แจ้งเฉยๆ เพราะโหลดจากมือถือ" จึงห้าม set status โดยไม่ส่ง note: `hr_fix_set_status(site_id, status)` ที่ไม่ใส่ note จะ **ล้างของเดิมเป็นค่าว่าง** (ทุก branch ใน `check_vanished`/`check_cleared` เขียน note แล้ว รวม branch ที่ยังไม่ตัดสิน). `hr_fixes` ไม่โดน retention 7 วัน (cleanup แตะแค่ `torrents` กับ `runs`) ประวัติจึงอยู่ยาว

**ตาราง `hr_fixes`** — สถานะ auto-fix ต่อ site_id: `pending` (ถาม Telegram แล้วรอกด) → `fixed` (โหลด .torrent ลง watch folder แล้ว) → `cleared` (seed ครบ แจ้งแล้ว) · `stalled` (กด fix แล้วแต่ 24 ชม. ผ่านไป **แล้วถาม `list_tasks` ยืนยันว่าไม่มี task ใน DS จริง** → ยิง Telegram บอกว่า fix ไม่ติด + รอบถัดไปถามใหม่ · เจอ task = ไม่ตีตรา `stalled` เพราะ payload ที่ถูกลบไปแล้วต้องโหลดใหม่ทั้งไฟล์ก่อน seed ซึ่งกินเวลาเกิน 24 ชม. ได้ง่ายๆ ถ้าตีตราจากเวลาอย่างเดียวจะถามซ้ำแล้วหย่อน .torrent เดิมเข้าไปวนไม่จบ · DS ตอบไม่ได้ = ข้ามไว้รอบหน้า) · `wedged` (มี task ใน DS แต่ผ่าน `_FIX_WEDGED_H = 120` ชม. ยังไม่ seed = ค้างฝั่ง DS เอง เช่นหลัง OOM outage 2026-08-19 ที่ทุก task ใหม่รายงาน `size_downloaded = 0` ตลอดจนไม่มีวันจบ → ยิง Telegram ครั้งเดียวให้คนไปดู/ลบ task เอง แล้วไม่ถามซ้ำ). **ก่อนถึง 120 ชม. เคสมี task แต่ยังไม่ seed จะโดน `dsm.nudge_task()`** = pause → sleep 5 → resume ทุกรอบ: ตัวนับ progress ของ DS อัปเดตเฉพาะตอน hash check (พังมาตั้งแต่ OOM outage 19/08 — `size_downloaded` ค้างนิ่งทั้งที่ไฟล์เขียนลงดิสก์จริง) task ที่โหลดครบแล้วจึงไม่รู้ตัวและไม่เคยพลิกเป็น seeding, pause/resume คือสิ่งเดียวที่บังคับให้ DS อ่านไฟล์ใหม่. ⚠️ เคสที่ nudge ช่วยไม่ได้คือ torrent ที่ชื่อโฟลเดอร์/ไฟล์ข้างในเกิน **255 ไบต์** (ไทย 1 ตัว = 3 ไบต์) — transmission ขึ้น `Couldn't open` ใน `/volume1/@download/transmissiond.log` แล้วค้าง `hash_checking` ตลอดกาล โหลดบน ext4/btrfs ไม่ได้ ต้องลบ task ทิ้งอย่างเดียว · `skipped` (กดข้าม) · `expired` (ไม่กดเกิน 12 ชม.) · `failed`. **ลบหลังพ้น H&R** (`hr_delete_enabled`, default off) ต่อท้าย: `cleared` → `del_asked` (ถามครั้งแรก) → `del_confirm` (ดึง DS task + real path มาโชว์ ยังไม่ลบ) → `deleted` · `del_task_only` (ลบแค่ task เก็บไฟล์ไว้) · `del_skipped` · `del_failed` — ปุ่มแรกไม่ลบอะไรเลย ปุ่มที่สองถึงลบ (task ก่อน แล้วค่อยไฟล์) และถ้า `FileStation.List getinfo` หา real path ไม่เจอ = **ยังส่งยืนยันรอบสอง แต่เหลือปุ่มเดียวคือลบเฉพาะ task** ห้ามเดา path (torrent หลายไฟล์ไม่มีโฟลเดอร์ครอบจะลงตรง `destination` ลบไปโดนของอื่น) — `del_failed` เหลือไว้ให้เคสหา task ไม่เจอ/DSM error เท่านั้น (รวมกรณี `getinfo` **โยน error** ไม่ใช่แค่คืนค่าว่าง: DSM timeout ตอน resolve = สถานะเดียวกัน "มี task แต่ไม่รู้ไฟล์" ถ้าปล่อยเป็น `del_failed` แถวนั้นจะตายถาวรเพราะรอบต่อไปมองว่าจัดการแล้ว). **ลบเฉพาะ task** ปลอดภัยเพราะ `SYNO.DownloadStation.Task delete` ยิงด้วย `force_complete=false` ไม่แตะ payload = หยุด seed แต่ไฟล์อยู่ครบ. ⚠️ DS รายงาน task delete ที่ล้มเหลว**ข้างใน `data`** (`[{"error": 544, "id": ...}]`) โดย top-level ยัง `success: true` → `dsm.delete_task` ต้องไล่อ่าน per-id error เอง ไม่งั้นจะรายงาน "ลบ task แล้ว" + เขียน `del_task_only` ทั้งที่ task ยังอยู่. แต่ 544 คือสิ่งที่ได้จาก id ที่ไม่มีอยู่จริงด้วย และ "task หายไปแล้ว" คือผลที่ทั้งสอง caller ต้องการอยู่แล้ว → เจอ per-id error ให้ `list_tasks` ซ้ำ ถ้า id หายแล้วนับว่าสำเร็จ ยังอยู่ค่อย raise (ไม่งั้น `_do_delete` จะตกที่ `del_failed` ไม่ได้ไปถึง `delete_path` ตอนที่ user ลบ task ทิ้งเองระหว่างที่ปุ่มยืนยันค้างใน Telegram). ทุกปุ่มที่จบเกม `edit_message` ข้อความต้นทาง (ปุ่มหายไปด้วย) **แล้วยิงข้อความใหม่ซ้ำ** — `editMessageText` ไม่มี noti เข้ามือถือ (เห็นเป็น "กดแล้วไม่มีอะไรเกิด") และตอน `ask` ถ้าไม่ edit ข้อความ stage 1 ปุ่ม "ขอดูก่อนลบ" จะค้างอยู่เหนือไฟล์ที่ลบไปแล้ว. `SYNO.FileStation.Delete` **ลบถาวร ไม่เข้า #recycle**. ปุ่มใช้ได้ครั้งเดียว (เช็ค `status == pending`) และรับเฉพาะ callback ที่ `chat_id` ตรง `TORRENTWATCH_TELEGRAM_CHAT_ID` ปุ่มยืนยันครั้งที่สอง re-stat path ก่อนลบ ถ้า real_path/size ไม่ตรงกับตอนโชว์ = ไม่ลบ (`del_confirm` ไม่มีวันหมดอายุ ปุ่มค้างใน Telegram เป็นสัปดาห์ได้), FileStation code 408 (ไม่มีไฟล์แล้ว) นับเป็นสำเร็จ เพราะ DS อาจลบ payload ไปพร้อม task, และ `dsm.py` ห่อ httpx error ทุกตัวเป็น `DsmError` ไม่งั้น timeout กลางทางจะโดน poller กลืนแล้วสถานะค้าง.

**⚠️ Cron coroutine = คนละ event loop:** job ของ APScheduler รันใน thread ของตัวเอง (`_run_async` → `asyncio.run()`) ส่วน `scraper._client` ถูกสร้างใน loop ของ FastAPI ตอน startup → request แรกในงาน cron ตาย `Event loop is closed`. ทุก coroutine ที่ยิงเน็ตจาก cron ต้อง `await scraper.relogin()` ก่อน (`_do_scrape` และ `check_hr` ทำแล้ว). **แต่ `relogin()` เดิมไม่ได้สร้าง client ใหม่** login ครั้งแรกจึงเจอ connection ที่ตายในลูปนั้น (`RuntimeError: unable to perform operation on <TCPTransport closed=True ...>`) แล้ว `_do_scrape` ยกเลิกทั้งรอบ (`relogin failed — scrape aborted`, 0s, 0 entries) เป็นระยะ. ตอนนี้ล้มครั้งแรก = `aclose()` ทิ้งแล้วสร้างใหม่ด้วย `_new_client()` แล้วลองอีกครั้ง; เหตุผลเก็บที่ `scraper.last_login_error()` แล้วต่อท้าย `box["error"]` ให้หน้า "รอบทำงาน" อ่านได้เลย

ตารางเวลา **ไม่ configurable** ผ่าน UI (hardcoded)

---

## API Summary

### Public (no auth)
- `GET /api/status` — scheduler state + scrape progress

### Protected (Basic Auth)
| Endpoint | Method | Purpose |
|---|---|---|
| `/api/sources` | GET/POST/DELETE/PATCH | Source CRUD + enable/disable/rename |
| `/api/torrents` | GET | Today's torrents (source_id, sort, filter) |
| `/api/history` | GET | Past day torrents (read-only) |
| `/api/history/dates` | GET | Available dates for source |
| `/api/search` | GET | Global text search across all dates (q, source_id, limit) |
| `/api/keywords` | GET/POST/DELETE | Per-source keyword CRUD |
| `/api/settings` | GET/PUT | Global settings (PUT triggers scheduler reload) |
| `/api/scrape` | POST | Manual scrape trigger |
| `/api/runs` | GET | ประวัติ run (`limit`, `job`) + counters 7 วัน + `hr_fix_recent(20)` + `status()` — ห้ามใส่ `_AUTH_BYPASS_PATHS` เพราะโชว์ internal ของ scrape |
| `/api/stats` | GET | Aggregate stats (optional source_id filter) |
| `/api/torrents/{id}/status` | POST | Set watched_status: 0=none, 1=watched, 2=skip |
| `/api/cover/{id}` | GET | Proxy cover image through authenticated session |
| `/api/download/local/{id}` | GET | Proxy .torrent to browser (RFC 5987 Thai filename) |
| `/api/download/nas/{id}` | POST | Save .torrent to `/downloads` |
| `/api/detail/{id}` | GET | Proxy bearbit detail page (bypass anti-hotlink) |
| `/api/hr` | GET | myhr.php snapshot สด (rows + risky_ids + hit_count/cap + `fetched_at`) |
| `/api/hr/notify` | POST | บังคับส่ง H&R digest เดี๋ยวนี้ (ข้าม toggle + dedup) + รัน auto-fix scan |
| `/api/hr/history` | GET | `hr_fixes` ใหม่สุดก่อน (`limit` cap 500) — แท็บ "ประวัติ" ใน H&R อ่านอันนี้ |
| `/api/debug/html` | GET | Raw scraped HTML |
| `/api/debug/login-page` | GET | Raw bearbit login page |
| `/api/debug/relogin` | POST | Force re-login |
| `/api/debug/download-test/{id}` | GET | Probe download URL (no save) |
| `/api/debug/clear-today/{id}` | DELETE | Wipe today's data for source |
| `/api/debug/clear-all/{id}` | DELETE | Wipe all data for source |

---

## Frontend State (app.js)

```js
state = {
  tab: "today" | "history" | "runs" | "keywords" | "stats" | "settings" | "hr",
  sources: [],
  activeSource: { today, history, keywords },  // source_id per tab
  sort: { today, history },                    // "seeds" | "leeches" | "completed" | "date"
  filter: "all" | "keyword",
  showSticky: true,
  historyDate: "",
  settings: {},
  search: "",         // text search on title (Today tab)
  searchHistory: "",  // text search in History — if no date selected, triggers global search
  activeCategory: "", // category chip filter (Today tab only)
}
```

Status polling: 1.5s ขณะ scrape running → 60s ขณะ idle  
Auto-refresh Today list เมื่อ scrape เปลี่ยน status จาก running → idle

---

## Anti-hotlink Bypass

Bearbit block request ที่ Referer ไม่ใช่ bearbit URL:
- **Download**: backend set `Referer: detail_url` ก่อน fetch .torrent
- **Detail page**: `/api/detail/{id}` proxy HTML ผ่าน backend + inject `<base href="https://bearbit.org/">` ให้ CSS/images resolve ได้

---

## Known Gaps (ณ 2026-05-20)

| Gap | รายละเอียด | ไฟล์ที่เกี่ยวข้อง |
|---|---|---|
| ✅ LINE notification — **FIXED** | wired เข้า config.py + scheduler.py แล้ว (2026-05-13) | config.py, scheduler.py |
| ✅ Telegram notification — **ADDED** | telegram_notify.py ใหม่ + wired ใน scheduler (2026-05-18) | telegram_notify.py, config.py, scheduler.py |
| ✅ Category filter — **FIXED** | chip bar แสดงใต้ toolbar (Today tab) | app.js, index.html |
| ✅ Text search — **FIXED** | search input กรอง title (Today + History tab) | app.js, index.html |
| ✅ Retention configurable — **FIXED** | `retention_days` setting ใน UI | db.py, index.html |
| ✅ Source reorder — **ADDED** | ↑↓ buttons ใน Settings, persist ใน DB `sort_order` (2026-05-18) | db.py, main.py, app.js |
| ✅ File size badge — **ADDED** | badge สีตามขนาด gray/amber/red ใน torrent cards (2026-05-18) | app.js, style.css |
| ✅ Cover image proxy — **FIXED** | `GET /api/cover/{id}` proxy ผ่าน authenticated session; onerror fallback ใน img tag | scraper.py, main.py, app.js |
| ✅ History search — **ADDED** | search box ใน History tab; ถ้าไม่เลือกวัน + พิมพ์ query → global search ข้าม all dates | app.js, index.html |
| ✅ Global search — **ADDED** | `GET /api/search?q=TEXT&source_id=ID` LIKE search ข้าม all dates | db.py, main.py |
| ✅ Watched/Skip — **ADDED** | `watched_status` column ใน DB; eye/x-circle buttons บน cards; badge + card dimming | db.py, main.py, app.js, style.css |
| ✅ Configurable schedule — **ADDED** | `scrape_interval_night`/`scrape_interval_day` settings (15/20/30/60 min); selects ใน UI | db.py, scheduler.py, main.py, index.html, app.js |
| ✅ Stats page — **ADDED** | Tab สถิติ แสดง 5 summary cards + 14-day chart + category breakdown + source breakdown | db.py, main.py, app.js, index.html, style.css |
| ✅ Sticky notification — **FIXED** | toggle ใน Settings → แจ้งเตือน LINE+Telegram; ใช้ sticky_notified flag แทน is_new (2026-05-21) | db.py, scheduler.py, line_notify.py, telegram_notify.py |
| COL_COMPLETED ยังไม่ verify | column 9 ของ bearbit สันนิษฐานว่าเป็น completed — ใช้ `/api/debug/html` ตรวจ | scraper.py |

---

## Recent Changes

### 2026-07-06 (Uploader on card)

1. **`scraper.py`** — `COL_UPLOADER = 11` parse (anchor→img alt→text, cap 60) → `uploader` in `_parse_row` dict
2. **`db.py`** — `uploader` column (schema + migration) + upsert; UPDATE guards with `COALESCE(NULLIF(?,''), uploader)`
3. **`static/app.js`** — `.tw-card-uploader` chip under stats row (only when `t.uploader`)
4. **`static/style.css`** — `.tw-card-uploader` pill (accent-dim, ellipsis)

### 2026-05-18 (Source Reorder + Size Badge)

1. **`db.py`** — `sort_order` column migration + backfill + `reorder_source()` + updated `get_sources()`/`add_source()`
2. **`main.py`** — `POST /api/sources/{id}/reorder` endpoint + `Literal["up","down"]` type
3. **`static/app.js`** — ↑↓ reorder buttons ใน `renderSourcesList()` + `sizeClass()` helper + `cardHTML()` size badge
4. **`static/style.css`** — `.tw-badge-size*` (4 rules) + `.tw-btn-icon:disabled`

### 2026-05-18 (Frontend Redesign)

1. **`static/style.css`** (rewrite) — Modern Minimal dark, indigo accent `#6366f1`, bottom nav (`tw-bottom-nav`/`tw-nav-item`), card stats row, `position: fixed` bottom nav
2. **`static/index.html`** (rewrite) — bottom nav, search icon wrap, Notification card รวม LINE+Telegram+Auto-DL, `<h2>` section titles
3. **`static/app.js`** (edits) — nav selector `.tw-tab` → `.tw-nav-item`, `cardHTML()` ใหม่ (stats row + kw-star), status badge dot, `fmt()` null-safe

### 2026-05-18 (Telegram notification)

1. **`telegram_notify.py`** ใหม่ — Telegram Bot API (sendMessage, getUpdates)
2. **`config.py`** — เพิ่ม `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` env vars
3. **`db.py`** — เพิ่ม `telegram_notify_keyword_enabled` setting (default "0")
4. **`scheduler.py`** — wire Telegram notify ข้าง LINE, เพิ่ม `telegram_configured` ใน status
5. **`main.py`** — `POST /api/telegram/test`, `GET /api/telegram/get-chat-id`
6. **`static/`** — Telegram settings card + JS handlers (toggle, test, get-chat-id)

### 2026-05-15 (clean code)

1. **Image lightbox** — `.tw-card-thumb` เปลี่ยนเป็น `object-fit: contain` (เห็นภาพทั้งหมด) + click รูป → fullscreen overlay
2. **Completed column** — `COL_COMPLETED = 9` parse จาก bearbit, เก็บใน DB column `completed`
3. **Sort by completed** — ปุ่ม "โหลดจบ" ใน Today/History toolbar
4. **`completed_min` threshold** — setting ใหม่ default 20, ทำงานกับ AND/OR filter_mode

### 2026-05-12

1. **`scrape_sticky` default** เปลี่ยนจาก `"0"` → `"1"` + migration สำหรับ existing DB
2. **Sticky bypass threshold** — sticky entries ข้าม seed_min/leech_min ทั้งหมด
3. **`upsert_torrent` UPDATE** — เพิ่ม `is_sticky` + `date_posted` ใน UPDATE clause
4. **Sticky regex typo** — แก้ `stickyt\.gif` → `sticky\.gif` + เพิ่ม `pinned\.gif`
5. **sync_stickies demotion** — clear `is_sticky=0` แทนการ backdate
