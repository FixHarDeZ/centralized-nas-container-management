# ink-reader — Daily Log

## 2026-07-06 — Initial build (Tasks 1-9)

Built full stack via Subagent-Driven Development from
`docs/superpowers/plans/2026-07-06-ink-reader.md`:

- Task 1: scaffold, config, DB layer (titles table, lifecycle helpers)
- Task 2: CBZ builder (normalize downloaded pages into CBZ + cover extraction)
- Task 3: scraper parsers (listing + title page, against HTML fixtures;
  selectors verified live pre-implementation, see design spec Global
  Constraints)
- Task 4: scrape cycle orchestration (dedup via slug, `MAX_NEW_PER_CYCLE` cap,
  per-title error isolation)
- Task 5: OPDS feed (root nav + `new`/`kept` acquisition feeds)
- Task 6: scheduler (scrape / expiry / backup jobs) + sqlite_backup.py
  (verbatim copy of torrentwatch's)
- Task 7: FastAPI app (API + file/cover serving + OPDS routes, all
  unauthenticated in-app — nginx sidecar owns auth)
- Task 8: curation dashboard (vanilla JS, Thai UI, cover grid + keep/delete)
- Task 9: Docker/nginx/secrets/docs (this entry) + deploy + live verification

All tasks reviewed clean (byte-for-byte brief compliance + code quality) via
fresh implementer + reviewer subagent pairs per task; see
`.superpowers/sdd/progress.md` for the per-task ledger.

Deploy + live verification (Task 9 Steps 8-9), 2026-07-06:

- `./scripts/deploy.sh -s ink-reader -y` — build + restart on NAS, both
  `ink-reader` and `ink-reader-nginx` came up healthy on first try.
- Added `ink-reader` to `scripts/deploy.sh`'s `ALL_STACKS` array (was missing
  — needed for `-s all` restarts and the pre-upload `.env` presence check to
  cover this stack automatically going forward).
- Live scrape cycle against the real doujin-th.com: `found=11, downloaded=10`
  (capped by `INK_MAX_NEW_PER_CYCLE=10`), `error=null`. Parser selectors from
  Task 3 held with zero drift — no fixture/parser changes needed.
- Confirmed full lifecycle live via API: keep → `status=kept`,
  `expires_at=null`; delete → tombstone (`status=deleted`, `file_size=null`,
  CBZ+cover removed from disk); `/opds` root feed renders valid Atom XML.
- nginx basic auth confirmed: 401 without credentials, 200 with vault
  credentials (`stacks.ink_reader.dashboard.*`), on both `/` and `/api/status`.
- External port 5068 is LAN-only by design (matches spec) — verification was
  done via SSH to the NAS and curling `localhost:5068`, not from the
  workstation directly (workstation is off the NAS's LAN).
- Remaining, explicitly manual (per plan Step 10): DSM reverse proxy
  15068→5068 (only if outside-LAN dashboard access wanted), and KOReader
  setup/read test on the physical Meebook M8 — both are the user's own
  action, not automatable from here.

## 2026-07-06 — Fix OPDS cover display for KOReader

KOReader on Meebook M8 showed only title text in the OPDS catalog — no cover
thumbnails. Root cause: relative URLs + wrong relation type.

Changes:
- `opds.py`: Added `base_url` parameter to `root_feed()` and `titles_feed()`.
  All hrefs now use absolute URLs when base_url is provided. Changed image
  relation from `http://opds-spec.org/image` to `http://opds-spec.org/thumbnail`
  (KOReader-compatible).
- `main.py`: Extract `base_url` from request's `Host` header and pass to OPDS
  feed builders. No new env var needed — URL is derived automatically.
- `tests/test_opds.py`: Added tests for absolute URL mode and updated
  thumbnail relation assertion.

Deploy needed: `./scripts/deploy.sh -s ink-reader -y` to pick up the fix.

## 2026-07-07 — Multi-source architecture + dashboard redesign

Refactored scraper from single-source to multi-source plugin architecture
and redesigned dashboard. Added ink-reader widget to homepage dashboard.

### Source architecture
- New `sources/` directory with abstract `Source` class (`base.py`)
- `sources/doujinth.py`: extracted parsers from old scraper.py
- Slugs namespaced: `doujinth-<id>` for doujin-th.com
- โดจินแปลไทย.com attempted but removed — domain expired, parked by Sedo

### Scraper refactor
- `scraper.py` now uses source plugins, iterates all sources in `scrape_cycle()`
- `_scrape_source()` handles per-source listing → filter → download flow
- Shared `_download_title()` pipeline (CBZ build + DB insert)

### DB changes
- New `source TEXT` column on `titles` table (default `'doujinth'`, migration auto-runs)
- New `source TEXT` column on `scrape_log` table
- `add_title()` now accepts `source` parameter
- New `source_stats()` function returns per-source counts/sizes

### API changes
- `/api/status` now includes `"sources": {name: {count, size}}` in response
- `/api/titles` now supports `?source=` filter parameter

### Dashboard redesign
- Modern dark UI with CSS custom properties, subtle shadows, transitions
- Source health indicators (colored dots in header)
- Per-source filter tabs ("doujin-th", "โดจินแปลไทย")
- Source badge on each card
- Responsive design, hover effects on cards
- Refresh button, improved scrape button with loading state

### Config
- New `INK_DOJINTPLTHAI_URL` env var (removed — domain expired)
- nginx: `/api/status` public (no auth) for homepage widget integration

### Tests
- All 34 tests pass
- New fixtures: `dojintplthai_listing.html`, `dojintplthai_title.html`
- Updated test_scraper.py, test_cycle.py, test_api.py for multi-source

## 2026-07-07 — HTTPS reverse proxy support for remote OPDS access

OPDS feed URLs were hardcoded with `http://` scheme, breaking KOReader access
when the NAS is reached via DSM reverse proxy (HTTPS :15068).

Changes:
- `main.py`: Extracted `_opds_base_url()` helper — reads `X-Forwarded-Proto`
  header to determine scheme (`http`/`https`) instead of hardcoding.
- `nginx/nginx.conf`: Changed `X-Forwarded-Proto` to `$http_x_forwarded_proto`
  so the header from DSM reverse proxy is passed through correctly.
- `tests/test_api.py`: Added `test_opds_https_scheme` — verifies feed links use
  `https://` when request includes `x-forwarded-proto: https`.

Deploy needed: `./scripts/deploy.sh -s ink-reader -y` to pick up the fix.

## 2026-07-07 — Add hentaithai.net + miku-doujin.com sources + listing pages

Added 2 new scraper sources and multi-page listing support.

### New sources
- `sources/hentaithai.py`: hentaithai.net parser
  - Listing: `/page-<number>` pages, extracts `t<id>` slugs from `<a>` tags
  - Title page: images in `<img class="img-fluid">`, tags in `<a class="badge">`
  - Filters decorative images (`/other/`, `/sticker/`, `change-to-bw`)
- `sources/mikudoujin.py`: miku-doujin.com parser (multi-episode)
  - Listing: `/<slug>/` URLs from `<a class="inz-a">` elements
  - Title page: episode list in `<td a[href]>` with `/ep-<n>/` pattern
  - Episode pages: images in `<img class="page-img">`
  - `needs_episode_fetch = True` — scraper auto-fetches episode pages

### Base class changes
- `sources/base.py`: Added `needs_episode_fetch: bool = False` flag and
  `parse_episode_page()` method (default no-op)

### Scraper changes
- `scraper.py`: Iterates all 3 sources in `scrape_cycle()`
- `_scrape_source()` now fetches multiple listing pages (`INK_LISTING_PAGES`)
- Multi-episode handling: when `needs_episode_fetch=True` and title page has
  no images, fetches each episode URL and aggregates images

### Config
- New `INK_LISTING_PAGES` env var (default `3`) — pages to scrape per source
- New `INK_HENTAITHAI_BASE_URL` (default `https://hentaithai.net`)
- New `INK_MIKUDOUJIN_BASE_URL` (default `https://miku-doujin.com`)

### Tests
- All 43 tests pass
- New fixtures: `hentaithai_listing.html`, `hentaithai_title.html`,
  `mikudoujin_listing.html`, `mikudoujin_title.html`, `mikudoujin_episode.html`,
  `mikudoujin_title_lazy.html`
- 11 new tests for hentaithai + mikudoujin parsers
- Updated test_cycle.py to handle multi-source (LISTING_PAGES=1, empty listings
  for new sources)

### Bug fix: hentaithai 403 Forbidden on image downloads
- Root cause: CDN `s1.hentaithai.net` is case-sensitive on Referer header.
  HTML has `//HentaiThai.net/t50579` (capital H) but CDN requires lowercase.
- Fix: `.lower()` on both listing URLs and image URLs in `hentaithai.py`
- Verified: image download now returns 200 (was 403)
- Deploy gotcha: `docker compose up --build` uses cached layers — must
  `docker build --no-cache` to pick up source file changes

### Bug fix: miku-doujin lazy-loaded images
- Root cause: miku-doujin uses `img.lazy[data-src]` for lazy loading instead
  of `img.page-img[src]`. Parser only checked `src` attribute.
- Fix: `_extract_page_images()` now also checks `data-src` attribute for
  images with "uploads" in the URL, with dedup via `seen` set.
- Result: mikudoujin went from 2→11 titles (f-hkc is truly empty)
- Deploy: `./scripts/deploy.sh -s ink-reader -y` (must upload files first)

### Known limitation: miku-doujin f-hkc only
- `f-hkc` is the only truly JS-rendered title (no images at all in HTML)
- All other previously failing titles now work via `data-src` lazy loading
- Would need headless browser (playwright) to support f-hkc type titles

### Fix: skip 404 and empty titles silently
- 404 errors (old content with deleted CDN images) now skip silently
- "no reader images found" (JS-rendered titles) now skip silently
- Only real errors are logged to scrape_log
- Result: error=None on full scrape cycle

### Deploy + live verification (final)
- Deployed via `./scripts/deploy.sh -s ink-reader -y` (uploads files + rebuilds)
- Results: found=61, downloaded=9, **error=None**
- Sources: doujinth=3, hentaithai=17, mikudoujin=20 (total 40 new, 253MB)
- All 43 tests pass
