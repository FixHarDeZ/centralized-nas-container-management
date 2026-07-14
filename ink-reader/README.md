# ink-reader

Doujin library for Meebook M8 (and any OPDS reader). Auto-scrapes new releases
from doujin-th.com, converts to CBZ, serves via a curation dashboard and an
OPDS catalog so KOReader can browse and download directly.

## Why

Reading doujin sites directly in a browser means heavy ads and a bad reading
layout — especially painful on an e-ink device. ink-reader pulls titles onto
the NAS as plain CBZ files, so any e-reader with OPDS support (KOReader on the
Meebook M8) gets a clean catalog and offline reading.

## Architecture

```
M8 (KOReader)
  │ OPDS browse + download CBZ (basic auth)
  ▼
┌──────── ink-reader (FastAPI, port 5068) ───────┐
│ scraper ─▶ CBZ files (/data/library)           │
│ SQLite catalog (/data/ink.db)                  │
│ dashboard: browse / 🗑 delete / ⚙️ settings     │
│ OPDS feed /opds                                │
│ scheduler: scrape cycle + auto-expire + backup │
└────────────────────────────────────────────────┘
         ▲ dashboard from phone/PC (nginx basic auth, DSM proxy :15068)
```

Single container (FastAPI + APScheduler + SQLite, same shape as
`torrentwatch/`) plus an `nginx:alpine` sidecar that owns basic auth and is
the only thing exposed on the host.

## Ports

| Context | Port |
|---|---|
| Container internal (`ink-reader`) | `8000` (not published — nginx-only) |
| NAS host (nginx sidecar, LAN) | `5068` |
| Synology Reverse Proxy (HTTPS external) | `15068` |

## Environment variables

All read by `config.py`, all optional (sane defaults shown):

| Var | Default | Purpose |
|---|---|---|
| `INK_SITE_BASE_URL` | `https://doujin-th.com` | Source site base URL |
| `INK_USER_AGENT` | (desktop Chrome UA) | User-Agent sent to the source site |
| `DATA_DIR` | `/data` | Root for db/library/covers/backups |
| `INK_SCRAPE_INTERVAL_HOURS` | `6` | Scrape cycle frequency |
| `INK_MAX_NEW_PER_CYCLE` | `10` | New titles downloaded per cycle |
| `INK_RETENTION_DAYS` | `30` | Default retention — seed only, runtime value lives in DB settings |
| `INK_REQUEST_DELAY_SECONDS` | `2` | Delay between requests to the source site |

## Runtime settings (dashboard ⚙️)

Stored in the SQLite `settings` table, editable from the dashboard gear icon
(`GET`/`PUT /api/settings`). Env vars above only seed the defaults.

| Setting | Default | Purpose |
|---|---|---|
| `retention_days` | `INK_RETENTION_DAYS` (30) | Days before a title auto-expires. Changing it recomputes `expires_at` for every live title. |
| `min_pages` | `30` | Page threshold for the "หน้าเยอะ" filter tab and `/opds/long` feed |

Dashboard/OPDS auth is **not** an app env var — it lives in the nginx
`.htpasswd` sidecar, generated from vault credentials
(`stacks.ink_reader.dashboard.*`).

## API

| Route | Method | Purpose |
|---|---|---|
| `/` | GET | Curation dashboard (static HTML) |
| `/api/titles?status=&source=` | GET | List titles, optional `status`/`source` filter |
| `/api/titles/{id}/delete` | POST | Remove CBZ+cover, mark `deleted` (tombstone) |
| `/api/scrape` | POST | Trigger a scrape cycle now (background thread, all sources) |
| `/api/status` | GET | Stats + per-source counts/sizes + last scrape result |
| `/api/settings` | GET/PUT | Runtime settings (`retention_days`, `min_pages`) |
| `/files/{id}.cbz` | GET | Download the CBZ |
| `/covers/{id}.jpg` | GET | Cover thumbnail |

## OPDS

| Route | Feed |
|---|---|
| `/opds` | Root navigation feed ("ใหม่ล่าสุด" / "หน้าเยอะ") |
| `/opds/new` | Acquisition feed, all live titles, newest first |
| `/opds/long` | Acquisition feed, titles with `pages >= min_pages` setting |

All routes are unauthenticated inside the app — the nginx sidecar owns basic
auth for everything on port 5068.

## KOReader setup (Meebook M8)

1. Sideload the KOReader APK (Android 11, e-ink — sideload is fine).
2. In KOReader: **Search → OPDS catalog → Add catalog**.
3. URL: `http://<NAS_HOST>:5068/opds`
4. Enter the basic auth username/password from the vault
   (`stacks.ink_reader.dashboard.*`).
5. Browse "ใหม่ล่าสุด", download a CBZ, it opens like any comic archive.

## Curation lifecycle

- New download → `status=new`, expires in `retention_days` (dashboard
  setting, default 30).
- 🗑 delete (dashboard or API) → CBZ + cover removed, `status=deleted`
  tombstone stays so the slug is never re-downloaded.
- The old ❤️ keep feature was removed (2026-07-13); existing `kept` rows are
  migrated back to `new` with a fresh expiry window on startup.
- Daily job (04:00 Asia/Bangkok) auto-expires `new` titles past `expires_at`
  the same way as a manual delete.
- Daily SQLite backup (03:00 Asia/Bangkok) → `/data/backups/`, matching the
  `torrentwatch`/`maid-tracker` backup pattern.
