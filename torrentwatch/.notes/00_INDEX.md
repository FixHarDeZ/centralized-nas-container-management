# TorrentWatch — Project Index (Memory Blueprint)

> อัปเดตล่าสุด: 2026-05-12  
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

⚠️ `LINE_ACCESS_TOKEN` และ `LINE_USER_ID` **ยังไม่ได้เพิ่มใน config.py** (ดู Known Gaps)

---

## Database Schema

### `sources`
```sql
id, url (UNIQUE), label, enabled, created_at
```

### `torrents`
```sql
id, source_id (FK), site_id, title, detail_url, torrent_url,
cover_url, seeds, leeches, date_posted, posted_at, category,
file_count, file_size, is_sticky, first_seen_at, last_updated_at,
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
- `filter_mode = "or"` — "and" | "or"
- `scrape_sticky = "1"` — รวม sticky หรือไม่ (default เปลี่ยนเป็น "1" เมื่อ 2026-05-12)

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
ROW_SELECTOR = "tr[data-category-id]"
COL_COVER   = 1    # <img src="..."> (absolute URL, ไม่ใช่ categories icon)
COL_TITLE   = 2    # <a href="details.php?id=X&hashinfo=Y"><b>title</b></a>
COL_FILES   = 5    # file count
COL_DATE    = 7    # <nobr>DD-MM-YYYY<BR>HH:MM:SS</nobr>
COL_SIZE    = 8    # "2.63 GB" / "380.60 MB"
COL_SEEDS   = 10   # <span class="green|red">N</span>
COL_LEECHES = 11
```
Download URL: `SITE_BASE_URL/download.php?id={site_id}&hashinfo={hashinfo}`

### Filter Logic
- `seeds == 0` → ทิ้งเสมอ
- Sticky entries → **bypass threshold** (เพิ่มเข้า result โดยตรง)
- Non-sticky: ต้อง keyword match **OR** (seed≥min AND/OR leech≥min ตาม filter_mode)
- `filter_mode=and` → ต้องผ่านทั้ง seed_min และ leech_min
- `filter_mode=or` → ผ่านอย่างใดอย่างหนึ่ง

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
  sort: { today, history },                    // "seeds" | "leeches" | "date"
  filter: "all" | "keyword",
  showSticky: true,
  historyDate: "",
  settings: {},
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

## Known Gaps (ณ 2026-05-13)

| Gap | รายละเอียด | ไฟล์ที่เกี่ยวข้อง |
|---|---|---|
| ✅ LINE notification — **FIXED** | `line_notify.py` เขียนครบแล้ว (`notify_keyword_matches`, `notify_round_summary`) — wired เข้า config.py + scheduler.py แล้ว (2026-05-13) | config.py, scheduler.py |
| ไม่มี category filter ใน UI | column `category` มีใน DB ทุก row แต่ไม่มีปุ่ม filter ใน frontend | app.js, index.html |
| ไม่มี text search | ไม่มี search input กรอง title ใน list | app.js |
| Retention 7 วัน hardcoded | `cleanup_old_records(days=7)` ใน scheduler.py ไม่ expose เป็น setting | scheduler.py, db.py |
| Cover image โหลดตรงจาก bearbit CDN | ถ้า session expire หรือ URL เปลี่ยน รูปแตกพร้อมกันหมด | scraper.py |

---

## Recent Fixes (2026-05-12)

1. **`scrape_sticky` default** เปลี่ยนจาก `"0"` → `"1"` + migration สำหรับ existing DB
2. **Sticky bypass threshold** — sticky entries ข้าม seed_min/leech_min ทั้งหมด
3. **`upsert_torrent` UPDATE** — เพิ่ม `is_sticky` + `date_posted` ใน UPDATE clause (เดิมอัปเดตแค่ seeds/leeches)
4. **Sticky regex typo** — แก้ `stickyt\.gif` → `sticky\.gif` + เพิ่ม `pinned\.gif`
5. **sync_stickies demotion** — เปลี่ยนจาก backdate ทันที → แค่ clear `is_sticky=0` (tolerant ต่อ 1-time miss)
