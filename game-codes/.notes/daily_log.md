# game-codes — Daily Log

## 2026-06-24 — Final verification + deploy (SDD Task 6)

All test suites pass: shared 16/16, sync guard 2/2, game-codes 8/8, news-feed 133/133.
Deployed via `./scripts/deploy.sh -s game-codes -y` — container rebuilt with httpx + shared
http_client.py, starts successfully. Container logs show httpx-style HTTP logging (`HTTP Request: GET ...`),
no import errors, loop mode active at 1800s interval.

## 2026-06-24 — ใช้ shared Notifier แทน send_telegram เดิม

ส่วนหนึ่งของงานรวม transport ข้าม stack → `shared/notify.py` (stdlib `urllib`, vendored ด้วย
`make sync-shared`, กัน drift ด้วย `tests/test_shared_sync.py`).

**game-codes:** `send_telegram()` เหลือ wrapper บางๆ ครอบ `Notifier(telegram=TgCreds(...,
parse_mode="HTML", disable_preview=True), timeout=HTTP_TIMEOUT).send(text)` — ตัด requests POST
+ try/except เดิมออก (Notifier กลืน error ภายใน, ตรงกับ ponytail comment เดิมที่กันไม่ให้
crash restart loop). เก็บ wrapper `send_telegram` ไว้เพราะ `tests/test_runtime.py` monkeypatch
มัน + health-alert เรียกมัน. Dockerfile เพิ่ม `COPY notify.py`. ยังใช้ requests ใน `fetch()`. 8 pass.

⚠️ verify ถึงแค่ transport seam; ของจริงพิสูจน์ตอน poll เจอ code ใหม่ครั้งแรกหลัง deploy.

## 2026-06-22

- Created new `game-codes/` stack: single Python poller container, no web
  layer, no exposed port. Polls 4 game redeem-code sources and pushes new
  codes to Telegram, reusing news-feed's existing bot token + chat id via
  shared vault paths (no new Telegram bot needed).
- Verified all 4 sources against their real markup/response shape before
  writing parsers:
  - Genshin: `hoyo-codes.seria.moe` JSON API, filter `status == "OK"`.
  - Wuthering Waves: chose `wuthering.gg/codes` over game8's Status column
    after checking the live DOM — game8-style "Active"/"Expired" text wasn't
    reliably present; wuthering.gg exposes status via a button label instead,
    so the parser keeps a row unless the status text says "expired" rather
    than requiring it to say "Active".
  - Throne of Desire: scrapes `mustplay.in.th`. Could not reach the site from
    the build sandbox to pin a `scope_selector`, so left it `None` (whole-page
    scope) and fixed the regex to require a digit after the `tod` prefix
    (`tod(?=[a-z0-9]*\d)[a-z0-9]{3,}`) — the original ungated regex would have
    false-positived on ordinary English/Thai words starting with "tod".
  - Rise of Eros: scraped `cofregamers.com`, pinned `scope_selector` to
    `.codigo-tabla-container` from live HTML to exclude prose elsewhere on the
    page that also happens to be 11 characters.
- Implemented first-run-per-source silent seeding in `diff_new` — a source's
  first successful poll seeds `state["seen"][key]` without sending any
  Telegram messages, so the stack doesn't dump every historical code on
  first start.
- Implemented health-alert logic in `run_once`: a fetch exception flips
  `health[key]` from `"ok"`/missing to `"broken"` and sends one alert (not
  repeated every poll while still broken); the next successful fetch flips it
  back and sends a recovery note. Explicitly did NOT alert on a zero-code
  result, since WuWa legitimately returns 0 codes most cycles (livestream-tied)
  and alerting on that would train the user to ignore the channel.
- Wrote `tests/test_parsers.py` (fixtures for all 4 sources) and
  `tests/test_runtime.py` (first-run-silent diff + health-alert edges). Full
  suite: `python -m pytest -v` → 7 passed.
- Remaining manual step: deploy via `./scripts/deploy.sh` + restart
  (`docker compose --project-directory game-codes/ -f game-codes/docker-compose.yml up -d --build`)
  and confirm `docker logs game-codes` shows a silent seed run. Not done in
  this session — left to a human deploy step.
- **Deployed & first run:** container running on NAS. First poll hit
  cofregamers.com 429 (Too Many Requests) — rate limit, not scraper breakage.
  Telegram sent: "⚠️ Rise of Eros scraper พัง: 429 Client Error: Too Many
  Requests".
- **Fixed 429 handling:** replaced bare `fetch()` with retry loop — 3 attempts,
  exponential backoff (10s → 20s) on HTTP 429 before giving up. 429 no longer
  triggers health alert immediately; only after all retries exhausted.
  File: `game_code_notifier.py:156-168`.
- **Pending:** rebuild + redeploy container on NAS with the fix.
- **Throne of Desire source research:** searched cofregamers.com (all 3 pages),
  game8.co, pocketgamer.com, ign.com, gamesradar.com, touchtapplay.com —
  none have ToD. Bing search also returned nothing relevant. ToD has no
  dedicated code aggregator site. User doesn't want mustplay.in.th (original
  source). ToD scraper remains **disabled**.
- **NAS fetch test:** SSH'd into NAS and tested all 4 sources — all returned
  200. Genshin 1018B, WuWa 24KB, RoE 309KB, ToD 95KB. Local workstation
  may block some sites but NAS doesn't.
- **Persistent 429 fix:** cofregamers.com rate-limits IP for extended periods
  (retry within same cycle doesn't help). Added per-source cooldown tracking
  in `state["rate_limited_until"]` — on 429, skip that source for 30 min
  (first occurrence) or 60 min (repeated within 1h). Cooldown clears on
  successful fetch. Retries reduced back to 3 (rapid retries are useless
  against IP bans). File:   `game_code_notifier.py`.

## 2026-06-24 — Migrate to shared http_client, drop requests

ส่วนหนึ่งของ Task 4 (SDD): เปลี่ยน `game-codes/game_code_notifier.py` ให้ใช้
`http_client.py` (shared module from Task 1, vendored ด้วย `make sync-shared`).

- แทนที่ `import requests` ด้วย `from http_client import get as http_get`
- เขียน `fetch()` ใหม่: เรียก `http_get(url, headers=HEADERS, timeout=HTTP_TIMEOUT, retries=3, backoff=20.0)` — ลบ `retries` param ออกจาก signature
- `requirements.txt`: ลบ `requests==2.32.3`, เพิ่ม `httpx==0.28.0`
- `Dockerfile`: เพิ่ม `http_client.py` ใน COPY line
- ทดสอบ: 8 passed
- Deviation: ใช้ `http_client.py` แทน `http.py` ตาม user instruction
