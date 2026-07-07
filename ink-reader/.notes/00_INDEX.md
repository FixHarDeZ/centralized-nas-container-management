# ink-reader — Project Index (Memory Blueprint)

> อัปเดตล่าสุด: 2026-07-07 (Multi-source architecture + dashboard redesign)
> ใช้ไฟล์นี้เป็น cold-start memory ก่อนเริ่มงานทุกครั้ง

---

## Overview

ink-reader scrapes new doujin releases from doujin-th.com on a schedule,
converts them to CBZ, and serves a curation dashboard + OPDS catalog so
KOReader on a Meebook M8 (or any OPDS client) can browse and download
directly — avoiding the ad-heavy, badly-laid-out source site. Single FastAPI
container + APScheduler + SQLite, same shape as `torrentwatch/`, with an
nginx sidecar owning basic auth.

## Sources

| Source | Type | Slug prefix | Content |
|---|---|---|---|
| doujin-th.com | SMF forum | `doujinth-` | Thai-translated doujin |

Source parsers live in `sources/` directory. Each implements the `Source`
abstract class with `parse_listing()`, `parse_title_page()`, `listing_url()`.
โดจินแปลไทย.com was removed — domain expired and parked by Sedo (Oct 2025).

## Tech Stack

| Component | Detail |
|---|---|
| Runtime | Python 3.12 · FastAPI · Uvicorn |
| Database | SQLite — `/data/ink.db` |
| Scraper | httpx client + BeautifulSoup4 (multi-source plugins) |
| Scheduler | APScheduler `BackgroundScheduler` |
| Frontend | Vanilla JS, no build step, Thai UI (modern dark theme) |
| Auth | nginx sidecar basic auth (not in-app) |

## DB Schema (`titles` table)

```sql
CREATE TABLE titles (
  id INTEGER PRIMARY KEY,
  slug TEXT UNIQUE NOT NULL,        -- namespaced: <source>-<id>
  title TEXT NOT NULL,
  tags TEXT,                        -- comma-separated
  pages INTEGER,
  file_size INTEGER,                -- bytes, NULL after delete
  status TEXT NOT NULL DEFAULT 'new',  -- new | kept | deleted
  source_url TEXT,
  source TEXT DEFAULT 'doujinth',   -- doujinth | dojintplthai
  downloaded_at TEXT NOT NULL,
  expires_at TEXT                   -- NULL when kept/deleted
);
```

`slug` is the dedup key — deleted rows stay as tombstones so a title is never
re-downloaded. `source` tracks which scraper found the title.

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
├── db.py                — SQLite CRUD + lifecycle + source_stats()
├── cbz.py               — CBZ build/normalize from downloaded pages
├── scraper.py           — multi-source scraper orchestration
├── sources/
│   ├── __init__.py
│   ├── base.py          — abstract Source class
│   ├── doujinth.py      — doujin-th.com parsers
│   └── dojintplthai.py  — โดจินแปลไทย.com parsers
├── opds.py              — Atom/OPDS XML feed builder (stdlib xml.etree)
├── scheduler.py         — APScheduler jobs: scrape / expiry / backup
├── sqlite_backup.py     — verbatim copy of torrentwatch/sqlite_backup.py
├── static/index.html    — curation dashboard (modern dark UI, vanilla JS)
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

## API

| Route | Method | Purpose |
|---|---|---|
| `/api/titles?status=&source=` | GET | List titles, optional filters |
| `/api/status` | GET | Stats + per-source counts + last scrape |

## Gaps / Known Risk

- Parser selectors for doujin-th.com verified live 2026-07-06, no drift
  expected.
- HTTPS reverse proxy support: OPDS feed URLs detect scheme from
  `X-Forwarded-Proto` header. Requires redeploy.
- No read-progress sync — KOReader tracks progress locally on the M8 only
  (explicitly out of scope, see spec).
- KOReader-on-M8 setup/read test not yet done — user's manual device step.
- Multi-source architecture ready (sources/ + namespaced slugs) — adding a
  new source only needs a new parser module in sources/.

## Deploy Status

- Last deploy: 2026-07-06 (pre-multi-source). Redeploy needed for
  multi-source + dashboard redesign.
- Port 5068 is intentionally LAN-only.

## Related

- Design spec: `docs/superpowers/specs/2026-07-06-ink-reader-design.md`
- Implementation plan: `docs/superpowers/plans/2026-07-06-ink-reader.md`
