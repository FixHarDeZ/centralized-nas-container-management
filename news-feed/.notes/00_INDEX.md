# news-feed Stack — Index

**สร้าง:** 2026-05-23  
**Port:** 5064 (external) → Nginx :80 → news-feed :8000 (internal)  
**Status:** Running healthy ✅ — modern dashboard deployed (2026-10-08)

> **2026-10-08 — Git cleanup ปิดงานแล้ว:** ผู้ใช้สั่งให้เหลือ main ทั้ง local/GitHub.
> Checkout หลักอยู่ main แล้ว; `codex/news-feed-modern-dashboard` ลบทั้งสองฝั่ง.
> งาน dashboard release อยู่ main `b437d5c`; commit `bb2ca52` มี tree เดียวกัน.
> สำรอง branches ก่อนลบที่ `.git/branch-cleanup-backups/20261008T095910Z/branches.bundle`
> พร้อม manifest (local เท่านั้น); managed shorts release worktree archive แล้ว.
> ไม่มีการเปลี่ยน app หรือ deploy ใหม่จาก cleanup นี้.
> บันทึก cleanup `8b55c6a` push main แล้ว; ปิด session ตามคำสั่ง “จบงาน”
> อัปเดต index/log ทั้ง news-feed และ shorts-factory. ไม่มี Git cleanup ค้าง.

> **2026-10-08 — Modern Editorial dashboard:** commit `77e5481`, push branch แล้ว;
> merge main + push release `56354a5` และ deploy เฉพาะ news-feed บน NAS สำเร็จ.
> 133 pytest + 22 Node tests ผ่านบน merged checkout; final code review ผ่าน ไม่มี findings ค้าง.
> `news-feed` healthy; APIs/assets → 200, SHA-256 ของ HTML/CSS/2 JS ตรง release; Nginx auth → 401.
> Browser preview ถูกปฏิเสธสิทธิ์ จึงยังไม่ยืนยัน desktop/tablet/mobile visual/interactions.
> ดู design/plan ใน `docs/superpowers/{specs,plans}/2026-10-08-news-feed-dashboard*` และ daily_log.

> **2026-06-24 — Notifier:** transport LINE/Telegram ย้ายไป shared module `shared/notify.py`
> (vendored = `app/notify.py`). `app/notifier.py` เหลือ formatter + `_notifier().send()`;
> creds อ่านจาก env เดิม (`LINE_CHANNEL_ACCESS_TOKEN`/`LINE_USER_ID`/`NEWS_FEED_TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID`).
> แก้ shared module ต้อง `make sync-shared`. ดู daily_log 2026-06-24.

---

## Architecture

Two-container stack:
- **Nginx (`news-feed-nginx`)** — reverse proxy on port 5064 with HTTP Basic Auth via `/etc/nginx/.htpasswd`
- **FastAPI (`news-feed`)** — internal app exposed only on Docker network port 8000
- **APScheduler BackgroundScheduler** — fetch (60min), price (6h), digest (cron), cleanup (cron 03:30 — retention)
- **SQLite** at `/data/news.db` (WAL mode)
- **Schedule config** at `/data/schedule.json` — อ่านทุก job run, เปลี่ยนได้ live

---

## File Map

| File | Responsibility |
|------|---------------|
| `app/config.py` | SOURCES dict, `get_config()`, `update_config()`, DB_PATH |
| `app/models.py` | SQLite CRUD — articles, prices, digest_log; `select_digest_articles()`, `get_sent_article_ids()` |
| `app/deps.py` | FastAPI `get_db` dependency |
| `app/fetcher.py` | RSS → dedup → body → summarize → insert |
| `app/summarizer.py` | Anthropic SDK / OpenRouter httpx, retry 3x |
| `app/pricer.py` | openrouter.ai/api/v1/models → upsert prices |
| `app/notifier.py` | LINE + Telegram push |
| `app/scheduler.py` | BackgroundScheduler setup, jobs เป็น closures |
| `app/main.py` | FastAPI lifespan, router registration, StaticFiles mount |
| `app/static/index.html` | Modern Editorial shell, 6 sections, default News Timeline, sidebar + mobile bottom nav/drawer |
| `app/static/dashboard.css` | Shared visual tokens, article previews, table/grid/settings styles; responsive 1120/900/760/420 breakpoints |
| `app/static/dashboard-utils.js` | Pure helpers: Bangkok next digest, text escaping/URL safety, article filters, cached watchlist parsing; browser + CommonJS |
| `app/static/app.js` | API/UI state, Chart.js, generation-guarded tab loads, coalesced overview, native news/digest details, drawer keyboard/focus, price/watchlist/config logic |
| `tests/dashboard.test.cjs` | Node built-in behavior/regression tests via pure helpers + minimal DOM seam; no extra dependencies, no layout verification |

---

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | — | Dashboard (index.html) |
| GET | `/api/news` | — | List articles (source/date/limit filters) |
| GET | `/api/news/sent-ids` | — | All article IDs that appear in any digest_log entry |
| DELETE | `/api/news` | basic-auth | Clear ALL articles → `{deleted}` |
| POST | `/api/news/cleanup` | basic-auth | Apply retention now (delete older than retention_days) → `{deleted, retention_days}` |
| GET | `/api/news/{id}` | — | Single article |
| POST | `/api/fetch/now` | basic-auth | Force fetch immediately → `{new_articles}` (no token; `/trigger` still token-gated) |
| GET | `/api/prices` | — | AI model prices (provider/sort filters) |
| GET | `/api/schedule` | — | Current config |
| POST | `/api/schedule` | — | Update digest times, sources, LLM model |
| GET | `/api/digest/history` | — | Last 30 digest logs |
| GET | `/api/health` | — | status, article_count, last_fetch |
| GET | `/api/news/sources` | — | Article count per source (last N hours, default 24h) |

---

## RSS Sources

| Key | Feed |
|-----|------|
| techcrunch_ai | TechCrunch AI |
| venturebeat | VentureBeat |
| theverge | The Verge |
| arstechnica | Ars Technica |
| gsmarena | GSMArena |
| 9to5mac | 9to5Mac |
| android_authority | Android Authority |

---

## .env Variables

| Variable | Purpose |
|----------|---------|
| ANTHROPIC_API_KEY | Anthropic Claude |
| LINE_CHANNEL_ACCESS_TOKEN | LINE push |
| LINE_USER_ID | LINE user target |
| TELEGRAM_BOT_TOKEN | Telegram bot |
| TELEGRAM_CHAT_ID | Telegram chat target |
| ADMIN_TOKEN | POST /api/digest/trigger |
| SUMMARIZER_PROVIDER | anthropic / openrouter / mimo |
| SUMMARIZER_MODEL | เช่น claude-sonnet-4-6 / deepseek/deepseek-chat / mimo-v2.5-pro |
| OPENROUTER_API_KEY | ถ้าใช้ openrouter |
| MIMO_API_KEY | ถ้าใช้ mimo |
| MIMO_BASE_URL | mimo API endpoint (default: https://token-plan-sgp.xiaomimimo.com/v1) |
| DIGEST_TIMES | 07:00,12:00,18:00 |
| ENABLED_SOURCES | comma-separated source keys |
| RETENTION_DAYS | จำนวนวันที่เก็บข่าว (default 30) — cleanup job ลบที่เก่ากว่านี้ทุก 03:30 |
| DATA_DIR | /data (inside container) |

---

## Known Gotchas

- `_schedule_file()` ต้องเป็น lazy function — module-level constant จะ lock path ที่ import time ทำให้ test patch ไม่ได้
- Scheduler jobs ต้องเป็น closures capture `db_path` — ไม่ใช่อ่าน module-level `DB_PATH`
- StaticFiles mount ที่ `/` ต้อง register **หลัง** API routers ทุกตัว (catch-all)
- `get_recent_articles_for_digest` ใช้ SQLite `datetime('now', ?)` ตรงๆ ไม่ผ่าน Python datetime
- **`schedule.json` บน NAS override `.env` ทั้งหมด** — ถ้าเปลี่ยน ENABLED_SOURCES ใน .env ต้องลบ `schedule.json` ด้วย (`rm /volume2/@docker/volumes/news-feed_news_feed_data/_data/schedule.json`)
- **`entry.summary` ใน RSS ไม่ใช่ full body** — เพียงพอสำหรับ summarization, ไม่ต้อง fetch article URL
- **`_shownPrices[]` vs `allPrices[]`**: หลัง search filter index ใน rendered table ไม่ตรงกับ `allPrices` — `renderPriceTable(prices)` เก็บ `_shownPrices = prices` แล้ว copy handler ใช้ `_shownPrices[idx]`
- **Copy button XSS safety**: ใช้ `data-idx` (integer) + JS array lookup แทนการใส่ model_id ใน HTML attribute
- **Leaderboard categorization**: `paidPositive` ใช้ `combined > 0` (ไม่ใช่ `prompt>0 && complete>0`) — ป้องกัน mixed-price models (prompt=$0, complete=$5) หายไปจากทุก category
- **Source Health 422**: `/api/news` มี `le=100` แต่ frontend เคยขอ `limit=500` → 422 → silent error → blank chart. Fix: เพิ่ม `/api/news/sources` endpoint ที่ใช้ aggregate SQL แทน
- **Basic Auth sidecar**: dashboard/API public access ต้องผ่าน `news-feed-nginx`; ไฟล์ `nginx/.htpasswd` เป็น secret, gitignored, ต้องสร้างบนเครื่อง deploy/NAS เอง
- **`retention_days` backward-compat**: `schedule.json` เก่าไม่มี key นี้ — consumer ทุกตัวใช้ `.get("retention_days", 30)` จึงไม่ต้องลบ `schedule.json`; ค่าจะถูกเขียนลงไฟล์เมื่อกด Save Config ครั้งแรก
- **Watchlist sync กับ server**: `watchlist` table + `GET/POST /api/watchlist` และ `PATCH /api/watchlist/{model_id}`; `localStorage['nf_watchlist']` เป็น cache/fallback และ migrate ขึ้น server เมื่อ server ว่าง. ทุก card ใช้ `_watchlist` Set เดียวกัน; toggle optimistic และแสดง sync error ใน overview เมื่อ server failure. Invalid/blocked localStorage ไม่ทำให้ dashboard crash
- **Leaderboard render split**: `loadLeaderboard()` fetch → set `_lbPrices` → `renderLeaderboard()`; bookmark/collapse เรียก `renderLeaderboard()` ตรงๆ ไม่ re-fetch
- **`POST /api/fetch/now` อาจนาน**: fetch + summarize หลาย source > 60s → nginx ตั้ง `proxy_read_timeout 300s` กัน 504 (server ทำงานต่อแม้ client timeout)
- **Summarizer fail silent** (เกิด 2 ครั้งแล้ว: 2026-05-29 OpenRouter free rate-limit, 2026-06-03 Mimo 401 invalid key): summarize() raise → fetcher log `logger.error("summarize failed ...")` แต่ article insert ไปแล้วเลย NULL ค้าง. ตรวจสอบด้วย `POST /api/digest/test` ดู `available_12h`; ถ้า = 0 ทั้งที่ timeline มีข่าว → summarizer fail. **สิ่งแรกที่ต้องเช็ค**: `schedule.json` ระบุ provider/model อะไร (override .env) แล้ว curl test ตรง. Re-summarize backlog ด้วย `docker exec python` SELECT WHERE summary_th IS NULL → loop summarize(title,"") → UPDATE (body ไม่เก็บใน DB ใช้ title อย่างเดียวพอ)
- **Reasoning models กิน token เยอะ**: Mimo v2.5 (และโมเดล reasoning ทั่วไป) ใช้ `reasoning_content` ก่อน generate `content` — ถ้า `max_tokens` ต่ำจะได้ `finish_reason=length` กับ `content=""` (empty). `_summarize_mimo` ใช้ 1500 + timeout 60s. ถ้าจะเพิ่ม reasoning provider อื่น ต้องตั้งสูงพอด้วย. **บั๊กเงียบที่ยังเหลือ**: fetcher.py และ models.update_article_summary ไม่ check empty string → article จะมี `summary_th=""` (ไม่ใช่ NULL) หลุดเข้า digest เป็นรายการเปล่า; ขณะนี้ใช้งานไม่กระทบเพราะ max_tokens=1500 พอแล้ว
- **Container env stale หลังอัปเดต vault**: `deploy.sh` upload `.env` ใหม่ แต่ถ้าไม่ recreate compose container ก็ยังถือ env ที่โหลดตอน start เดิม → key ใหม่ไม่มีผล. Fix: `docker compose up -d` (recreate ที่ไม่ใช่ restart) หรือ deploy ใหม่
- **Mobile bottom nav**: แสดงเมื่อ `max-width:760px`; sidebar ซ่อน. `showTab()` sync `[data-tab]`/`aria-current` โดยไม่อิงลำดับปุ่ม; 3 primary tabs + More สำหรับ drawer tabs. Drawer trap Tab, Escape/overlay ปิด, คืน focus และปิดเมื่อ resize กลับ desktop
- **Dashboard async guards**: `loadTab()` ส่ง freshness callback ให้ทุก loader ตรวจหลัง awaits ก่อน mutate DOM/state; config load/save guards ป้องกัน stale form และเปิด Save หลัง latest load failure. `loadOverview()` ใช้ shared Promise + versioned loop; ห้ามเปลี่ยนกลับเป็น early-return แล้วทิ้ง post-save refresh
- **News scope/filter**: latest100 search/status/source/sort คงอยู่ข้าม refresh (เก็บ option source ที่ไม่อยู่ในหน้าใหม่ด้วย); summary tiles อ่าน aggregate24h จาก `/api/news/sources`. Sent-ID API failure = unknown status ไม่ใช่ unsent; source counts ไม่ใช่ RSS connection health
- **Benchmark reference**: Top Hit/Intelligence ใช้ static data ฝังใน JS; UI ระบุไม่ใช่อันดับสด. ข่าวใช้ escaped text + http/https URL allowlist; native details รองรับ keyboard
- **Price table expand row**: `togglePriceExpand(idx)` ใช้ `_shownPrices[idx]` (ไม่ใช่ `allPrices`) — copy button ต้อง `e.stopPropagation()` เพื่อกัน row expand ขึ้นมาพร้อมกัน
- **Provider badge บน mobile**: `.price-cell-provider` span inject ใน `renderPriceTable()` มี `display:none` ใน base CSS, `display:block` ใน media query เท่านั้น — col 3 (Provider) ซ่อนบน mobile แต่ยังอยู่ใน DOM
- **Adaptive digest window**: `_compute_digest_window(now, digest_times, buffer)` ใน `app/scheduler.py` คำนวณ lookback จาก gap ระหว่าง digest ticks (clamp 4–36h). ห้าม hardcode 12h ที่ฝั่ง consumer ใหม่ — อ่านจาก helper เสมอ. Frontend `_digestBadge` ใช้ 36h outer bound (heuristic, ไม่ใช่ค่า window จริง).
- **`digest_size_max` < `digest_size_base` reject**: `/api/schedule` ตรวจ cross-field validation; max ที่ส่งมาน้อยกว่า base ปัจจุบัน → ไม่บันทึก (ค่าเดิมคงอยู่). ส่ง `digest_size_base` กับ `digest_size_max` พร้อมกันถ้าจะลด max

---

## Change Log

| วันที่ | เรื่อง |
|--------|--------|
| 2026-10-08 | Modern Editorial UI ครบ 6 หน้า + overview/filters/error handling/safety/async guards/deferred settings reload; commit `77e5481`, merge main release `56354a5`, deploy healthy; 133 pytest + 22 Node ผ่าน; browser visual verification ถูกปฏิเสธสิทธิ์ |
| 2026-05-23 | สร้าง stack ทั้งหมด (14 tasks), 41 tests ผ่าน |
| 2026-05-24 | Fix deploy: `COPY --chown=app:app`, `chown 1000:1000 /data`, Dockerfile `RUN mkdir /data` |
| 2026-05-24 | Optimize fetcher: RSS summary แทน full-body fetch, limit 10/source, `POST /api/fetch/trigger`, immediate fetch on start |
| 2026-05-24 | Fix digest dedup: กรอง `sent_ids` จาก `digest_log` ก่อน pick 5 บทความ |
| 2026-05-25 | Fix Invalid Date: เปลี่ยน `isoformat()` → `strftime("%Y-%m-%dT%H:%M:%SZ")` ใน fetcher/pricer/scheduler, feedparser ใช้ `published_parsed` แทน raw string |
| 2026-05-25 | Dashboard: ย้าย "Last fetch" ไป header, เพิ่ม Model ID column + copy button (XSS-safe) ใน Price Tracker |
| 2026-05-25 | Dashboard: Price Tracker search bar, กรองราคาติดลบ, Free Models section ใน Leaderboard |
| 2026-05-25 | Feature: Geo zone filter in Price Tracker (PROVIDER_ZONES + zone buttons + badge), escapeHtml() XSS fix |
| 2026-05-25 | Feature: Leaderboard zone badges, 🏆 Top Hit, 🧠 Top Intelligence sections (ELO-based, longest-match-first) |
| 2026-05-25 | Feature: Free model expiry — `free_expires_at` DB column + `PATCH /api/prices/{id}/expiry` + color-coded badge (urgent/warn/ok) + inline 📅 edit in Leaderboard |
| 2026-05-25 | Infra: เพิ่ม `nginx:alpine` basic-auth reverse proxy on port 5064; app เปลี่ยนเป็น internal-only `expose: 8000` และ `nginx/.htpasswd` เป็น local/NAS secret |
| 2026-05-27 | Fix: Telegram digest debug (`POST /api/digest/test`), News sort toggle, Test Digest button |
| 2026-05-29 | Feature: Top Hit Cheapest/Free cards, leaderboard jump bar + collapsible + watchlist (localStorage), news retention (`RETENTION_DAYS` + cleanup job + `DELETE /api/news` + `POST /api/news/cleanup`), `POST /api/fetch/now`, Xiaomi→CN zone fix, news sort by published date. 56 tests |
| 2026-05-29 | Mobile layout: bottom nav bar (News/Board/Prices/More), bottom drawer (Digest/Health/Config), responsive Price table (3-col + tap-to-expand), stacked news controls. CSS `@media(max-width:640px)` only — desktop unchanged. |
| 2026-05-29 | Digest status badge on News Timeline (ส่งแล้ว/รอส่ง/พ้น window); `GET /api/news/sent-ids`; digest window 6h→12h; max 2 articles/source/digest via `select_digest_articles()`. 65 tests. |
| 2026-05-31 | Feature: เพิ่ม Xiaomi MiMo เป็น summarizer provider ตัวที่ 3 (OpenAI-compatible API); `MIMO_API_KEY` + `MIMO_BASE_URL` ใน vault/manifest; dashboard dropdown เพิ่ม Mimo option |
| 2026-06-05 | Feature: Schedule Config Add/Remove digest time buttons (`_renderDigestTimeInputs`); Price Tracker My Watchlist card (`#pt-watchlist-card`); star ☆/★ column in price table; mobile colspan + nth-child fix |
| 2026-06-05 | Feature: Summarizer fail alert (`send_summarizer_alert` + state file `/data/summarizer_state.json`; threshold=2 consecutive empty digests; cooldown=6h); Source descriptions in Schedule Config (`SOURCE_META`) |
| 2026-06-05 | Feature: Summarizer Fallback Chain — `_dispatch()` helper + fallback loop in `summarize()`; `summarizer_fallback` field in schedule config; Fallback Chain UI card in Schedule Config |
| 2026-06-05 | Feature: Dynamic RSS Source Add/Remove — `get_all_sources(config)` merge built-in+custom; `custom_sources` field; `fetcher.py` uses merged dict; Add/Remove UI in Schedule Config |
| 2026-06-05 | Feature: Watchlist Sync — `watchlist` DB table; `GET/POST /api/watchlist` + `PATCH /api/watchlist/{model_id}`; frontend syncs server on load, PATCH on toggle; localStorage as fallback |
| 2026-06-05 | Feature: Price History Chart — `price_history` table; `snapshot_all_prices` after each price job; `GET /api/prices/{id}/history`; Chart.js sparkline in expand row; `_priceCharts` cache + cleanup |
| 2026-06-03 | Debug: Mimo API key invalid (401) → summarize silent fail → 3 วันไม่มี digest. Switch openrouter+deepseek ชั่วคราว + backfill 44/48 articles |
| 2026-06-03 | Fix: Mimo v2.5 เป็น reasoning model — `max_tokens 300→1500` + `timeout 30→60` ใน `_summarize_mimo`; ต้อง recreate container เพื่อโหลด `.env` ใหม่ (deploy ปกติทำให้แล้ว); switch กลับเป็น Mimo, backfill 4 ตัวที่ deepseek คืน empty → ครบ 0 NULL |
| 2026-06-08 | Feature: Adaptive digest window + dynamic size — `_compute_digest_window` helper, `select_digest_articles(base, extra_max, max_per_source)`, 4 config keys (`digest_window_buffer_hours`, `digest_size_base`, `digest_size_max`, `digest_max_per_source`), badge threshold 12h→36h, `/api/digest/test` response shape updated |
