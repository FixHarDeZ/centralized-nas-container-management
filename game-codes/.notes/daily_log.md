# game-codes — Daily Log

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
