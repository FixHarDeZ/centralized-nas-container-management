# TorrentWatch

**EN** | [ไทย](#ภาษาไทย)

A daily torrent monitor that scrapes [bearbit.org](https://bearbit.org) on a schedule, paginates through all of today's uploads, filters by seed/leech thresholds and keywords, and surfaces them via a mobile-friendly dark-themed web UI. Runs as a Docker container on Synology NAS.

![TorrentWatch screenshot](../screenshots/torrentwatch.png)

---

## Features

- **Multi-source** — add multiple listing URLs (e.g. `viewbrsb.php`, `viewno18sbx.php`); each has its own keyword list
- **Multi-page scraping** — paginates `?page=0,1,2,...` until it hits an item from a previous day, so all of today's uploads are captured
- **Today-only filter** — sticky/pinned entries are auto-skipped, only fresh uploads appear
- **Seed/leech threshold** with **AND/OR** mode toggle (configurable; seed ≠ 0 always enforced)
- **Per-source keywords** — keyword-matched torrents bypass the threshold
- **Cover image, file size, file count, upload time** displayed per card
- **Sort by** seed count, leech count, or upload time
- **Clickable title** — opens the bearbit detail page through a backend proxy that bypasses bearbit's anti-hotlink Referer check
- **Two download modes**:
  - **Browser** — proxies the `.torrent` to your browser (preserves Thai filename via RFC 5987)
  - **NAS** — saves directly to a configurable subdirectory inside the mounted watch folder
- **History tab** — browse any past date (read-only, frozen data)
- **Auto schedule** — every 30 min or 1 hour, during 19:00–01:00 or all day
- **Live progress** — header badge shows source/page/count in real-time during scrape; auto-refreshes the list when done
- **Weekly cleanup** — deletes records older than 7 days every Sunday at 03:00

## Stack

| Component | Detail |
|---|---|
| Runtime | Python 3.12 · FastAPI · Uvicorn |
| Database | SQLite (WAL mode) — persisted in named volume `torrentwatch_data` |
| Scraper | httpx async session + BeautifulSoup4 · login + Referer handling |
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

# Host path to Synology watch folder (mounted to /downloads inside container)
NAS_TORRENT_PATH=/var/services/homes/<NAS_USER>/Torrents_Watch
```

### 3. NAS Watch Folder

The "→ NAS" download button writes `.torrent` files inside the mounted watch folder. The mount is configured in `docker-compose.yml`:

```yaml
volumes:
  - torrentwatch_data:/data
  - ${NAS_TORRENT_PATH}:/downloads
```

The host path `NAS_TORRENT_PATH` must already exist on the NAS before starting the container. The "NAS path" setting in the UI controls a **subdirectory** within `/downloads` (e.g. set to `Movies` to save into `Torrents_Watch/Movies/`).

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

> Ports 5060 and 5061 are blocked by browsers (SIP protocol) — use 5062 or higher.

## Settings (Web UI)

| Setting | Default | Description |
|---|---|---|
| Seed min | `5` | Minimum seeds for a torrent to pass |
| Leech min | `10` | Minimum leeches for a torrent to pass |
| Filter mode | `AND` | `AND` = both must meet · `OR` = either is enough |
| NAS path | empty | Subdirectory inside `/downloads` (empty = root of watch folder) |
| Scrape interval | `30 min` | How often to scrape (30 or 60 min) |
| Scrape window | `19:00–01:00` | Active hours, or `all day` |

## API Reference

| Method · Path | Purpose |
|---|---|
| `GET /api/torrents?source_id=…&sort=seeds\|leeches\|date&filter=all\|keyword` | Today's torrents for a source |
| `GET /api/history/dates?source_id=…` | Available history dates |
| `GET /api/history?source_id=…&date=YYYY-MM-DD` | Read-only past day |
| `GET /api/detail/{torrent_id}` | **Proxied** detail page (bypasses bearbit anti-hotlink) |
| `GET /api/download/local/{id}` | Stream `.torrent` to browser (RFC 5987 Thai filename) |
| `POST /api/download/nas/{id}` | Save `.torrent` into the NAS watch folder |
| `GET /api/sources` · `POST` · `DELETE` · `PATCH` | Source CRUD |
| `GET /api/keywords?source_id=…` · `POST` · `DELETE` | Per-source keyword CRUD |
| `GET /api/settings` · `PUT` | Read/update settings (rebuilds scrape job on interval/time change) |
| `POST /api/scrape` | Manual scrape trigger |
| `GET /api/status` | Scraper + scheduler state, including live `scrape_progress` |
| `GET /api/debug/html?source_id=…` | Raw scraped HTML — for selector tuning |
| `GET /api/debug/login-page` | Raw bearbit login page |
| `POST /api/debug/relogin` | Force re-login |
| `GET /api/debug/download-test/{id}` | Probe download URL without saving |
| `DELETE /api/debug/clear-all/{source_id}` | Wipe all torrent data for a source |
| `DELETE /api/debug/clear-today/{source_id}` | Wipe today's data only |

## Anti-hotlink Bypass

Bearbit blocks any request whose `Referer` header isn't a bearbit URL — both for `.torrent` downloads and detail pages. TorrentWatch handles this transparently:

- **Scraper** sends `Referer: https://bearbit.org/...` on every backend request
- **Title click** opens `/api/detail/{id}` — the backend fetches the bearbit detail page with a proper Referer, then serves the HTML through our domain (with `<base href="https://bearbit.org/">` injected so images/CSS still resolve)

## Scraper Selectors

If bearbit changes its HTML layout, update the `SELECTOR_*` and `COL_*` constants at the top of `scraper.py` — no other code changes needed. The `/api/debug/html` endpoint dumps the raw HTML for inspection.

---

## ภาษาไทย

[EN](#torrentwatch)

TorrentWatch เป็น app สำหรับ monitor torrent ใหม่จาก bearbit.org อัตโนมัติ ไล่ scrape ทีละหน้าจน list ของวันนี้หมด filter ตาม seed/leech และ keyword แล้วแสดงผ่าน web UI บนมือถือ — รันเป็น Docker container บน Synology NAS

![TorrentWatch screenshot](../screenshots/torrentwatch.png)

---

## คุณสมบัติ

- รองรับหลาย source URL (`viewbrsb.php`, `viewno18sbx.php`, ฯลฯ) แต่ละ source มี keyword list ของตัวเอง
- **Multi-page scraping** — ไล่ `?page=0,1,2,...` จนกว่าจะเจอ torrent ที่ไม่ใช่วันนี้แล้วหยุด
- **Today only** — ตัด sticky/pinned ทิ้งอัตโนมัติ
- เงื่อนไข seed/leech แบบ **AND** (ทั้งคู่) หรือ **OR** (อย่างใดอย่างหนึ่ง)
- Keyword ต่อ source — ถ้า title match จะข้าม threshold ได้
- การ์ดแสดง: รูปปก, ขนาด, จำนวนไฟล์, เวลา upload
- เรียงตาม seed / leech / เวลา upload
- กดชื่อ → เปิดหน้า detail ผ่าน backend proxy (bypass anti-hotlink ของ bearbit)
- ดาวน์โหลด: **Browser** (proxy ผ่าน backend, ชื่อไทยใช้ RFC 5987) หรือ **NAS** (เขียนตรงเข้า watch folder)
- History tab — ดูย้อนหลังได้
- Auto scrape: 30 นาที / 1 ชั่วโมง · ช่วง 19:00–01:00 หรือทั้งวัน
- Header badge แสดง progress live: source / page / จำนวน items ระหว่าง scrape
- ลบข้อมูลเก่าอัตโนมัติทุก Sunday 03:00 (เกิน 7 วัน)

## การตั้งค่า

### 1. Account bearbit.org

ต้องมี account บน bearbit.org credential เก็บใน `.env` ที่ root — ไม่ commit

### 2. Environment Variables

เพิ่มใน `.env`:

```env
TORRENTWATCH_SITE_USERNAME=your_bearbit_username
TORRENTWATCH_SITE_PASSWORD=your_bearbit_password
TORRENTWATCH_DEFAULT_URLS=https://bearbit.org/viewbrsb.php
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
