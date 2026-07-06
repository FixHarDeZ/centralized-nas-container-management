# ink-reader — Project Index (Memory Blueprint)

> อัปเดตล่าสุด: 2026-07-06 (initial build, Task 9)
> ใช้ไฟล์นี้เป็น cold-start memory ก่อนเริ่มงานทุกครั้ง

---

## Overview

ink-reader scrapes new doujin releases from doujin-th.com on a schedule,
converts them to CBZ, and serves a curation dashboard + OPDS catalog so
KOReader on a Meebook M8 (or any OPDS client) can browse and download
directly — avoiding the ad-heavy, badly-laid-out source site. Single FastAPI
container + APScheduler + SQLite, same shape as `torrentwatch/`, with an
nginx sidecar owning basic auth.

## Tech Stack

| Component | Detail |
|---|---|
| Runtime | Python 3.12 · FastAPI · Uvicorn |
| Database | SQLite — `/data/ink.db` |
| Scraper | httpx client + BeautifulSoup4 |
| Scheduler | APScheduler `BackgroundScheduler` |
| Frontend | Vanilla JS, no build step, Thai UI |
| Auth | nginx sidecar basic auth (not in-app) |

## DB Schema (`titles` table)

```sql
CREATE TABLE titles (
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,        -- source ID from doujin-th
  title TEXT NOT NULL,
  tags TEXT,                        -- comma-separated
  pages INTEGER,
  file_size INTEGER,                -- bytes, NULL after delete
  status TEXT NOT NULL DEFAULT 'new',  -- new | kept | deleted
  source_url TEXT,
  downloaded_at TEXT NOT NULL,
  expires_at TEXT                   -- NULL when kept/deleted
);
```

`slug` is the dedup key — deleted rows stay as tombstones so a title is never
re-downloaded.

## Ports

| Context | Port |
|---|---|
| Container internal (`ink-reader`) | `8000` |
| NAS host (nginx sidecar) | `5068` |
| Synology Reverse Proxy (HTTPS external) | `15068` |

## File Map

```
ink-reader/
├── main.py             — FastAPI app: API + file/cover serving + OPDS routes
├── config.py           — env var reads (INK_*, DATA_DIR)
├── db.py                — SQLite CRUD + lifecycle (keep/purge/expired_ids/stats)
├── cbz.py               — CBZ build/normalize from downloaded pages
├── scraper.py           — listing + title parsers, scrape_cycle orchestration
├── opds.py              — Atom/OPDS XML feed builder (stdlib xml.etree)
├── scheduler.py         — APScheduler jobs: scrape / expiry / backup
├── sqlite_backup.py     — verbatim copy of torrentwatch/sqlite_backup.py
├── static/index.html    — curation dashboard (vanilla JS)
├── Dockerfile
├── docker-compose.yml
├── nginx/nginx.conf     — basic-auth reverse proxy → ink-reader:8000
├── nginx/.htpasswd       — generated, gitignored (see README "vault" section)
├── secrets.manifest.yaml
├── requirements.txt
└── tests/
```

## Settings (env vars)

See root `ink-reader/README.md` "Environment variables" table —
`INK_SITE_BASE_URL`, `INK_USER_AGENT`, `DATA_DIR`, `INK_SCRAPE_INTERVAL_HOURS`,
`INK_MAX_NEW_PER_CYCLE`, `INK_RETENTION_DAYS`, `INK_REQUEST_DELAY_SECONDS`.

Dashboard/OPDS credentials are nginx-only: vault
`stacks.ink_reader.dashboard.{username,password}` → baked into
`nginx/.htpasswd` at deploy time (never an app env var).

## Gaps / Known Risk

- Parser selectors (`scraper.py`) were built against fixture HTML captured
  from a live pull before implementation (workstation cannot reach the site
  directly — outbound blocked). Task 9 Step 9 does a live confirmation pass
  against the deployed NAS container; if the site has changed again since
  the fixture capture, selectors need adjusting there, not here.
- No read-progress sync — KOReader tracks progress locally on the M8 only
  (explicitly out of scope, see spec).
- Single source only (doujin-th.com) — multi-source explicitly out of scope.

## Related

- Design spec: `docs/superpowers/specs/2026-07-06-ink-reader-design.md`
- Implementation plan: `docs/superpowers/plans/2026-07-06-ink-reader.md`
