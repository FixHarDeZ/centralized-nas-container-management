# game-codes Stack — Index

**สร้าง:** 2026-06-22
**Port:** — (no web layer, no exposed port)
**Status:** Built, tests passing, not yet deployed to NAS

---

## Architecture

Single container, no web layer, no database server:

- **`game-codes`** — Python 3.12-slim, one script (`game_code_notifier.py`),
  runs as non-root `app` user (uid/gid 1000).
- **Loop mode**: if `POLL_INTERVAL > 0` (default `1800`), loops forever,
  polling all sources and sleeping between cycles. `POLL_INTERVAL=0`/unset
  runs a single pass and exits (cron-style, unused in the NAS deploy which
  uses `restart: unless-stopped` + loop mode).
- **State file**: `/data/seen_codes.json` on the `game_codes_data` named
  volume — the only persistent data this stack has.
- **No outbound dependency on news-feed code** — it only reuses news-feed's
  Telegram bot token + chat id via the shared vault path, so the two stacks
  can be deployed/restarted independently.

## State File Schema

```json
{
  "seen": {
    "genshin": ["CODE1", "CODE2"],
    "wuwa": ["..."],
    "throne_of_desire": ["..."],
    "rise_of_eros": ["..."]
  },
  "health": {
    "genshin": "ok",
    "wuwa": "ok",
    "throne_of_desire": "ok",
    "rise_of_eros": "ok"
  }
}
```

- `seen[key]` — every code ever observed for that source (sorted list), used
  to diff for "new" codes on the next poll.
- `health[key]` — `"ok"` or `"broken"`. Only transitions on fetch
  exception/HTTP error; flips back to `"ok"` on the next successful fetch.
  Drives the one-shot break/recovery Telegram alerts (no repeat spam while
  still broken).
- A source key only appears in `seen`/`health` after its first successful
  poll. First appearance seeds all currently-live codes silently (no
  Telegram message) — only codes found on later polls are reported.

## Environment Variables

| Var | Source | Default | Notes |
|-----|--------|---------|-------|
| `GAME_CODES_TELEGRAM_BOT_TOKEN` | vault: `stacks.news_feed.telegram.bot_token` | — | Same bot as news-feed's Telegram notifier. |
| `TELEGRAM_CHAT_ID` | vault: `stacks.news_feed.telegram.chat_id` | — | Same chat as news-feed's Telegram notifier. |
| `POLL_INTERVAL` | literal | `1800` | Seconds between poll cycles. |
| `STATE_FILE` | literal | `/data/seen_codes.json` | Persisted on `game_codes_data` volume. |

See `secrets.manifest.yaml` for the exact vault → env mapping consumed by
`scripts/render_env.py` (`make secrets`).

## Sources Table

| Key | Game | Parser type | Site | Scope | Status filter |
|-----|------|-------------|------|-------|----------------|
| `genshin` | Genshin Impact | `api_seria` | `hoyo-codes.seria.moe` (JSON API) | whole response | `status == "OK"` |
| `wuwa` | Wuthering Waves | `table_status` | `wuthering.gg/codes` | `<table>` rows | keep unless status cell contains "expired" |
| `throne_of_desire` | Throne of Desire | `section_regex` | `mustplay.in.th` content page | **whole page** (`scope_selector: None`) | regex requires a digit after `tod` prefix — no separate status filter, every regex match not already seen is reported |
| `rise_of_eros` | Rise of Eros | `section_regex` | `cofregamers.com` redeem-code list | `.codigo-tabla-container` | 11-char alnum regex — no status filter (site exposes no per-code expiry) |

## Known Gaps / Follow-ups

- **`throne_of_desire.scope_selector` is `None` (whole-page scope).** The
  build sandbox had no network access to `mustplay.in.th`, so the selector
  could not be pinned empirically. The digit-guard regex
  (`tod(?=[a-z0-9]*\d)[a-z0-9]{3,}`) is the only safety net against
  false-positives from Thai/English prose. If Telegram starts getting junk
  "Throne of Desire" alerts, pin `scope_selector` to the actual code-table
  container from the NAS (which has outbound network access) and redeploy.
- **`rise_of_eros` has no per-code expiry/status signal.** Unlike WuWa
  (status column) or Genshin (`status` field), cofregamers.com's
  `.codigo-tabla-container` doesn't expose whether a code is still
  redeemable — every new 11-char match is reported as new with no way to
  later mark it expired. Low risk (false positives just mean an occasionally
  dead code gets sent), but worth knowing this source can't filter on its own.
- **WuWa status detection relies on a button-label heuristic**, not an
  explicit "Active"/"Expired" text field — verified against the live DOM at
  build time (2026-06-22) but could drift if the site redesigns the table.
- **No automated re-pinning**: if any of the 3 scraped sites changes markup,
  the only signal is either silence (zero codes reported, not flagged as
  broken by design) or a health-alert (only on full fetch/HTTP failure, not
  on "page loaded but selector now matches nothing").

## Files

| File | Responsibility |
|------|-----------------|
| `game_code_notifier.py` | Entire app: `SOURCES` config, 3 parsers, fetch, state load/save, diff, Telegram send, health-alert edge logic, main loop. |
| `secrets.manifest.yaml` | Vault → env mapping (`make secrets` reads this to generate `.env`). |
| `Dockerfile` | `python:3.12-slim`, non-root `app` user, `/data` volume mount point. |
| `docker-compose.yml` | Single `game-codes` service, `game_codes_data` named volume, `TZ=Asia/Bangkok`. |
| `tests/test_parsers.py` | Fixture-based tests for `fetch_api_seria`, `fetch_table_status`, `fetch_section_regex` against saved HTML/JSON fixtures (`tests/fixtures/`). |
| `tests/test_runtime.py` | Tests for `diff_new` (first-run-silent) and the health-alert broken/recovery edges in `run_once`. |
