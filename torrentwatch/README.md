# TorrentWatch

**EN** | [ไทย](#ภาษาไทย)

A daily torrent monitor that scrapes [bearbit.org](https://bearbit.org) on a schedule, filters today's uploads by seed/leech thresholds and keywords, and surfaces them via a mobile-friendly dark-themed web UI. Runs as a Docker container on Synology NAS.

---

## Features

- Scrapes multiple listing URLs independently — each source has its own keyword list
- Filters to **today's uploads only** — no backlog noise
- Seed / leech threshold filtering (configurable; seed ≠ 0 always enforced)
- Per-source keyword watchlist — keyword-matched torrents appear even if below threshold
- Cover image, file size, file count, and upload time displayed per card
- Sort by seed count, leech count, or upload time
- Download torrent to browser **or** save directly to a NAS watch folder
- LINE push notifications on keyword matches and per-round summaries (toggleable)
- History tab — browse any past date's results (read-only, frozen data)
- Auto scrape schedule: every 30 min or 1 hour, during 19:00–01:00 or all day
- Weekly cleanup — deletes records older than 7 days every Sunday at 03:00

## Stack

| Component | Detail |
|---|---|
| Runtime | Python 3.12 · FastAPI · Uvicorn |
| Database | SQLite (WAL mode) — persisted in named volume `torrentwatch_data` |
| Scraper | httpx + BeautifulSoup4 · session-based login |
| Scheduler | APScheduler `BackgroundScheduler` |
| Host port | `5059` → container `8000` |
| Reverse proxy | Synology RP `https://…:5062` → `http://localhost:5059` |

## Setup

### 1. bearbit.org Account

You need an active account on bearbit.org. Credentials are stored only in the root `.env` — never committed.

### 2. Environment Variables

Add to the root `.env`:

```env
TORRENTWATCH_SITE_USERNAME=your_bearbit_username
TORRENTWATCH_SITE_PASSWORD=your_bearbit_password

# Comma-separated initial listing URLs (seeds the DB on first start; edit via Settings UI after)
TORRENTWATCH_DEFAULT_URLS=https://bearbit.org/viewbrsb.php

# LINE push notifications (optional — can leave empty to disable)
TORRENTWATCH_LINE_ACCESS_TOKEN=your_line_channel_access_token
TORRENTWATCH_LINE_USER_ID=your_line_user_id

# Host path to Synology watch folder (uncomment the volume line in docker-compose.yml to enable)
NAS_TORRENT_PATH=/var/services/homes/<NAS_USER>/Torrents_Watch
```

### 3. NAS Download (optional)

To enable the "→ NAS" download button, uncomment this line in `docker-compose.yml`:

```yaml
# - ${NAS_TORRENT_PATH}:/downloads
```

The path must already exist on the NAS host before starting the container.

### 4. Deploy

```bash
./deploy.sh   # upload files and restart torrentwatch
```

Register in Synology Container Manager → Project → Create → path `/volume1/docker/torrentwatch`.

### 5. Synology Reverse Proxy

DSM → Control Panel → Login Portal → Advanced → Reverse Proxy → Create:

| Field | Value |
|---|---|
| Source Protocol | HTTPS |
| Source Port | `5062` |
| Destination Protocol | HTTP |
| Destination Hostname | `localhost` |
| Destination Port | `5059` |

Router must forward external port `5062 → NAS`.

> Port 5060 and 5061 are blocked by browsers (SIP protocol) — use 5062 or higher.

## Settings

All settings are configurable from the web UI (Settings tab):

| Setting | Default | Description |
|---|---|---|
| Seed min | `5` | Minimum seeds to include a torrent |
| Leech min | `10` | Minimum leeches to include |
| NAS path | `/downloads` | Volume mount path for NAS downloads |
| Scrape interval | `30 min` | How often to scrape (30 or 60 min) |
| Scrape time | `19:00–01:00` | Window to run scrapes (or all day) |
| LINE notify | Off | Push notifications via LINE |
| LINE summary | On | Send per-round summary |
| LINE keyword only | Off | Only notify on keyword matches |

## Debug Endpoints

| Endpoint | Description |
|---|---|
| `GET /api/debug/html?source_id=<id>` | Raw scraped HTML — use to tune CSS selectors |
| `GET /api/debug/login-page` | Raw login page HTML — inspect form field names |
| `POST /api/debug/relogin` | Force re-login and report result |
| `GET /api/debug/download-test/<id>` | Probe download URL without saving |
| `DELETE /api/debug/clear-all/<source_id>` | Delete all torrent data for a source |
| `DELETE /api/debug/clear-today/<source_id>` | Delete today's data only |

## Scraper Selectors

If bearbit.org changes its HTML layout, update the `SELECTOR_*` constants at the top of `scraper.py` without touching any other code. The debug HTML endpoint helps identify the new structure.

---

## ภาษาไทย

[EN](#torrentwatch)

TorrentWatch เป็น app สำหรับ monitor torrent ใหม่จาก bearbit.org อัตโนมัติ filter เฉพาะไฟล์ที่ลงในวันนั้น และแสดงผ่าน web UI บนมือถือ รันเป็น Docker container บน Synology NAS

---

## คุณสมบัติ

- รองรับหลาย source URL — แต่ละ source มี keyword list ของตัวเอง
- แสดงเฉพาะ **torrent ที่ลงในวันนั้น** — ไม่มีข้อมูลย้อนหลังปน
- กรองตาม seed / leech ขั้นต่ำ (ตั้งค่าได้ seed ≠ 0 บังคับเสมอ)
- Keyword watchlist ต่อ source — ถ้า title ตรงกับ keyword จะแสดงแม้ seed/leech ต่ำกว่า threshold
- แสดงรูปปก, ขนาดไฟล์, จำนวนไฟล์, และเวลาที่ upload
- เรียงตาม seed, leech, หรือเวลา upload
- ดาวน์โหลด .torrent ผ่าน browser **หรือ** ส่งตรงไปยัง watch folder ใน NAS
- LINE notification เมื่อเจอ keyword match และสรุปยอดแต่ละรอบ (เปิด/ปิดได้)
- แท็บ History — ดูผลย้อนหลังรายวัน (read-only)
- ตั้งเวลา scrape: ทุก 30 นาที หรือทุก 1 ชั่วโมง ช่วง 19:00–01:00 หรือทั้งวัน
- ล้างข้อมูลอัตโนมัติทุก Sunday 03:00 ลบ record อายุเกิน 7 วัน

## การตั้งค่า

### 1. สมัครสมาชิก bearbit.org

ต้องมี account บน bearbit.org credential เก็บใน `.env` ที่ root — ไม่ commit

### 2. Environment Variables

เพิ่มใน `.env`:

```env
TORRENTWATCH_SITE_USERNAME=your_bearbit_username
TORRENTWATCH_SITE_PASSWORD=your_bearbit_password
TORRENTWATCH_DEFAULT_URLS=https://bearbit.org/viewbrsb.php
TORRENTWATCH_LINE_ACCESS_TOKEN=...   # ถ้าต้องการ LINE noti
TORRENTWATCH_LINE_USER_ID=...
NAS_TORRENT_PATH=/var/services/homes/<NAS_USER>/Torrents_Watch
```

### 3. Deploy

```bash
./deploy.sh   # อัปโหลดไฟล์และ restart torrentwatch
```

Register ใน Synology Container Manager → Project → Create → path `/volume1/docker/torrentwatch`

### 4. เข้าใช้งาน

- LAN: `http://192.168.x.x:5059`
- External: `https://<NAS_HOST>:5062` (ผ่าน Synology Reverse Proxy)
