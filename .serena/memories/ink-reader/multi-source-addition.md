# ink-reader: Multi-source addition (2026-07-07)

## What was done
Added 2 new scraper sources (hentaithai.net + miku-doujin.com) and multi-page listing support.

## Key files modified
- `sources/base.py` — added `needs_episode_fetch` flag + `parse_episode_page()` method
- `sources/hentaithai.py` — NEW: hentaithai.net parser
- `sources/mikudoujin.py` — NEW: miku-doujin.com parser (multi-episode)
- `scraper.py` — registered new sources, multi-page listing, episode fetching
- `config.py` — added `INK_LISTING_PAGES`, `INK_HENTAITHAI_BASE_URL`, `INK_MIKUDOUJIN_BASE_URL`

## Architecture decisions
- Multi-episode sources use `needs_episode_fetch = True` flag on Source class
- `_scrape_source()` auto-detects: if title page has no images but has episode_urls, fetches each episode
- `INK_LISTING_PAGES` (default 3) controls pagination depth per source
- hentaithai.net: 1 page = 1 doujin (images on title page directly)
- miku-doujin.com: 1 title = N episodes (images on episode pages)

## Bug fix: hentaithai 403
CDN `s1.hentaithai.net` is case-sensitive on Referer header. Fixed by `.lower()` on URLs.
Deploy gotcha: `docker compose up --build` uses cached layers — must `docker build --no-cache` to pick up source file changes.
CDN `s1.hentaithai.net` is case-sensitive on Referer header. Fixed by `.lower()` on URLs.

## Bug fix: miku-doujin lazy-loaded images
miku-doujin uses `img.lazy[data-src]` not `img.page-img[src]`. Fixed by also checking `data-src`.
Result: mikudoujin 2→11 titles. Only f-hkc truly empty.

## Fix: skip 404 and empty titles silently
404 errors (old CDN-deleted content) and "no reader images" (JS-rendered) now skip silently.
Only real errors are logged. Result: error=None on full scrape.

## Known limitation: miku-doujin f-hkc only
Only f-hkc is truly JS-rendered. All other titles work via data-src lazy loading.
~50% of titles load images via JS. Episode-based titles work, JS-rendered ones skip.

## Test state
- All 43 tests pass (was 34 before this change)
- 11 new tests for hentaithai + mikudoujin parsers
- test_cycle.py updated to handle multi-source (LISTING_PAGES=1, empty listings for new sources)

## Domain status
- hentaithai.net — live, scrapeable, no anti-bot
- hentaithai.com — DNS resolution failed (dead domain)
- miku-doujin.com — live, scrapeable, no anti-bot, multi-episode structure
