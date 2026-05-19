# TorrentWatch — Project Index (Memory Blueprint)

> อัปเดตล่าสุด: 2026-05-19 (UI bug fixes: toast, logo, download local)
> ใช้ไฟล์นี้เป็น cold-start memory ก่อนเริ่มงานทุกครั้ง

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
| Synology Reverse Proxy (HTTPS external) | `5062` |

URL pattern:
- LAN: `http://192.168.x.x:5059`
- External: `https://<NAS_HOST>:5062`

> Ports 5060/5061 ใช้ไม่ได้ (blocked by browsers, SIP protocol)

---

## File Map

```
torrentwatch/
├── main.py          — FastAPI app + all API routes + Basic Auth middleware
├── config.py        — env var reads (SITE_*, DATA_DIR, BASIC_AUTH_*, LINE_*)
├── db.py            — SQLite CRUD: sources, torrents, keywords, settings, cleanup
├── scraper.py       — async httpx scraper: login, fetch, parse, paginate
├── scheduler.py     — APScheduler jobs: scrape + weekly cleanup
├── line_notify.py   — LINE Messaging API push (⚠️ NOT wired to scheduler yet)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── static/
    ├── index.html   — SPA shell (tabs: วันนี้, ประวัติ, Keyword, ตั้งค่า)
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
file_count, file_size, completed, is_sticky, first_seen_at, last_updated_at,
downloaded_local, downloaded_nas
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

Index: `idx_torrents_source_date ON torrents(source_id, date_posted)`

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
COL_FILES     = 5    # file count
COL_DATE      = 7    # <nobr>DD-MM-YYYY<BR>HH:MM:SS</nobr>
COL_SIZE      = 8    # "2.63 GB" / "380.60 MB"
COL_COMPLETED = 9    # completed/snatches count (best guess — verify via /api/debug/html)
COL_SEEDS     = 10   # <span class="green|red">N</span>
COL_LEECHES   = 11
```
Download URL: `SITE_BASE_URL/download.php?id={site_id}&hashinfo={hashinfo}`

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

### Sticky Detection Regex (scraper.py:375)
```python
is_sticky = bool(row.find("img", src=re.compile(r"sticky\.gif|heart\.gif|pinned\.gif", re.I)))
```

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
| `cleanup` | Sunday 03:00 | ลบ records > 7 วัน |

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
| `/api/keywords` | GET/POST/DELETE | Per-source keyword CRUD |
| `/api/settings` | GET/PUT | Global settings |
| `/api/scrape` | POST | Manual scrape trigger |
| `/api/download/local/{id}` | GET | Proxy .torrent to browser (RFC 5987 Thai filename) |
| `/api/download/nas/{id}` | POST | Save .torrent to `/downloads` |
| `/api/detail/{id}` | GET | Proxy bearbit detail page (bypass anti-hotlink) |
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
  tab: "today" | "history" | "keywords" | "settings",
  sources: [],
  activeSource: { today, history, keywords },  // source_id per tab
  sort: { today, history },                    // "seeds" | "leeches" | "completed" | "date"
  filter: "all" | "keyword",
  showSticky: true,
  historyDate: "",
  settings: {},
  search: "",         // text search on title (Today tab only)
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

## Known Gaps (ณ 2026-05-18)

| Gap | รายละเอียด | ไฟล์ที่เกี่ยวข้อง |
|---|---|---|
| ✅ LINE notification — **FIXED** | wired เข้า config.py + scheduler.py แล้ว (2026-05-13) | config.py, scheduler.py |
| ✅ Telegram notification — **ADDED** | telegram_notify.py ใหม่ + wired ใน scheduler (2026-05-18) — ต้องใส่ TELEGRAM_CHAT_ID ใน .env | telegram_notify.py, config.py, scheduler.py |
| ✅ Category filter — **FIXED** | chip bar แสดงใต้ toolbar (Today tab) | app.js, index.html |
| ✅ Text search — **FIXED** | search input กรอง title (Today tab) | app.js, index.html |
| ✅ Retention configurable — **FIXED** | `retention_days` setting ใน UI | db.py, index.html |
| ✅ Source reorder — **ADDED** | ↑↓ buttons ใน Settings, persist ใน DB `sort_order` (2026-05-18) | db.py, main.py, app.js |
| ✅ File size badge — **ADDED** | badge สีตามขนาด gray/amber/red ใน torrent cards (2026-05-18) | app.js, style.css |
| COL_COMPLETED ยังไม่ verify | column 9 ของ bearbit สันนิษฐานว่าเป็น completed — ใช้ `/api/debug/html` ตรวจ | scraper.py |
| Cover image โหลดตรงจาก bearbit CDN | ถ้า session expire รูปแตกพร้อมกัน | scraper.py |

---

## Recent Changes

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
