# ink-reader — Doujin Library for Meebook M8 (Design Spec)

**Date:** 2026-07-06
**Status:** Approved by user (brainstorming session)

## Problem

User reads doujin on doujin-th.com via browser. Pain: heavy ads, bad reading
layout. Wants files stored on NAS, comfortable reading on Meebook M8 e-reader
(Android 11, e-ink, sideload OK), and per-title keep/delete curation.

## Decisions (locked with user)

| Question | Decision |
|---|---|
| Reading path | Sideload KOReader on M8, browse/download via OPDS from NAS |
| Discovery | Auto-scrape latest releases from doujin-th.com on schedule |
| Curation | Auto-expire unmarked titles + ❤️ keep button; 🗑 delete immediate |
| Architecture | Approach A: single FastAPI container with built-in OPDS feed (Komga rejected — extra JVM container, split curation) |
| Stack name | `ink-reader` |
| Retention | 30 days for `new` titles not marked keep |

## Architecture

Single stack following the `torrentwatch/` pattern: flat FastAPI app +
APScheduler + SQLite + static dashboard, with an nginx sidecar for basic auth.

```
M8 (KOReader)
  │ OPDS browse + download CBZ (basic auth)
  ▼
┌──────── ink-reader (FastAPI, port 5068) ───────┐
│ scraper ─▶ CBZ files (/data/library)           │
│ SQLite catalog (/data/ink.db)                  │
│ dashboard: ❤️ keep / 🗑 delete (grid of covers)│
│ OPDS feed /opds                                │
│ scheduler: scrape cycle + auto-expire + backup │
└────────────────────────────────────────────────┘
         ▲ dashboard from phone/PC (nginx basic auth, DSM proxy :15068)
```

- **Ports:** FastAPI app internal-only (container network); nginx sidecar publishes **5068** on the NAS; DSM reverse proxy **15068** (HTTPS) for outside-LAN dashboard access. KOReader on LAN talks to `http://<NAS_HOST>:5068`.
- **Volume `/data`:** `library/` (CBZ), `covers/` (jpg thumbnails), `ink.db`, `backups/`.
- **Vault keys:** `stacks.ink_reader.dashboard.username` / `.password` (nginx basic auth, same credentials used by KOReader OPDS client).

## Components

### 1. Scraper (`scraper.py`)

- Crawls doujin-th.com latest-releases listing on schedule (default every 6h,
  configurable), downloads up to `MAX_NEW_PER_CYCLE` (default 10) new titles
  per cycle.
- Per title: use the site's download link (site offers per-title download) →
  zip → normalize to CBZ (rename, ensure images sorted, strip junk files).
  Extract cover (first page) as thumbnail. Metadata: title, tags, page count,
  source URL, source slug/ID.
- **Fallback:** if download link broken/changed, scrape reader-page images
  directly and build CBZ.
- **Dedup:** source slug/ID is the natural key. Deleted titles leave a
  **tombstone** row so they are never re-downloaded.
- ⚠️ Site structure could NOT be verified from workstation (outbound blocked,
  MITM cert — same as bearbit case). Verify selectors/download flow live on
  NAS during implementation; keep parser isolated behind fixtures.
- Browser-like User-Agent; polite delay between requests.

### 2. Data model (`db.py`, SQLite)

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

Lifecycle:
- Download → `status='new'`, `expires_at = now + RETENTION_DAYS` (default 30).
- ❤️ keep → `status='kept'`, `expires_at=NULL`. Permanent.
- 🗑 delete → remove CBZ + cover, `status='deleted'` (tombstone stays).
- Daily expiry job: `new` titles past `expires_at` → same as delete.
- Daily SQLite backup 03:00 → `/data/backups/` gzip, 30-day retention
  (maid-tracker pattern).

### 3. Dashboard (static HTML + `/api/*`)

- Cover grid: thumbnail, title, tags, expiry countdown (days left).
- Filters: all / new / kept.
- Per-title buttons: ❤️ keep, 🗑 delete (delete asks confirm).
- Global: "scrape now" button, storage stats (count + total size per status).
- Mobile-friendly (used mostly from phone).
- Behind nginx basic auth.

API:
- `GET /api/titles?status=` — list
- `POST /api/titles/{id}/keep`
- `POST /api/titles/{id}/delete`
- `POST /api/scrape` — trigger cycle now
- `GET /api/status` — stats

### 4. OPDS feed (`opds.py`)

- `GET /opds` — root navigation feed: "ใหม่ล่าสุด" (status=new, newest first)
  and "ที่เก็บไว้" (status=kept).
- `GET /opds/new`, `GET /opds/kept` — acquisition feeds, entries link to
  `GET /files/{id}.cbz` (`application/vnd.comicbook+zip`) + cover thumbnail.
- Atom/OPDS 1.2 XML, hand-built with stdlib `xml.etree` (no extra dep).
- Same basic auth as dashboard (KOReader supports basic auth per catalog).

### 5. Reading flow on M8

One-time setup: install KOReader APK, add OPDS catalog
`http://<NAS_HOST>:5068/opds` (via nginx port) with basic auth credentials.
Daily use: open catalog → pick title → download CBZ to device → read offline.
Read progress lives in KOReader locally (not synced — YAGNI). After reading,
mark ❤️/🗑 in dashboard from phone.

## Error handling

- Scrape cycle failures: log + skip title, never crash the scheduler; cycle
  status shown on dashboard (`last_run`, `last_error`).
- Partial download: write to temp path, move into `library/` only when CBZ
  is complete and valid (zip test) — no half files in the feed.
- Site layout change: parser raises, cycle marks error, dashboard shows it.

## Testing

- pytest, offline-first: parser against saved HTML fixtures, CBZ normalize,
  expiry/tombstone logic, OPDS XML well-formedness + required attributes.
- Live smoke test of scraper on NAS after deploy (workstation cannot reach
  the site).

## Explicitly out of scope (YAGNI)

- Telegram/LINE notifications (dashboard is enough).
- Server-side read progress / sync.
- Search or browse of the source site from dashboard (auto-scrape latest only;
  can add a paste-URL queue later if wanted).
- Multi-source support.
