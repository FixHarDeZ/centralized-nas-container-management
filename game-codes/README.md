# game-codes — Redeem-Code Notifier

Single Python poller container. No web layer, no exposed port. Every
`POLL_INTERVAL` seconds it polls a fixed list of redeem-code sources for a few
mobile/gacha games, diffs the result against `/data/seen_codes.json`, and
pushes any **new** code straight to Telegram — reusing the same bot + chat as
the `news-feed` stack (shared vault paths, see `secrets.manifest.yaml`).

## Sources

| Game | Type | URL | Redeem | Notes |
|------|------|-----|--------|-------|
| Genshin Impact | API (`hoyo-codes.seria.moe`) | `https://hoyo-codes.seria.moe/codes?game=genshin` | In-app link included | Filters `status == "OK"` only. Most reliable source, JSON. |
| Wuthering Waves | Scrape (`wuthering.gg/codes`) | `https://wuthering.gg/codes` | In-game only | Table row kept **unless** the status cell says "expired" — the live page only exposes status via a button label (e.g. "COPY" vs "Expired"), not the word "Active". **WuWa rarely has an active code at all** — codes are livestream-tied, so expect 0 or 1 most cycles. |
| Throne of Desire | Scrape (`mustplay.in.th`) | `https://www.mustplay.in.th/content/page/69671b935ee1bb833c7a0884` | In-game only | Whole-page scope (`scope_selector: None`) guarded by a digit-required regex (`tod(?=...\d...)`) so Thai/English prose starting with "tod" doesn't false-positive. The build sandbox couldn't reach the site to pin a tighter selector — **tighten `scope_selector` from the NAS** if false positives show up in Telegram. |
| Rise of Eros | Scrape (`cofregamers.com`) | `https://cofregamers.com/en/rise-of-eros-redeem-code-list/` | In-game only | Scoped to `.codigo-tabla-container`, matches 11-char alphanumeric codes. No per-code expiry status on the site, so every code in that container that hasn't been seen before is reported as new (no "expired" filter possible here). |

In practice, most real Telegram traffic comes from Genshin and Rise of Eros —
WuWa is sparse by nature and Throne of Desire depends on how often that page
actually changes.

## Behaviour

- **First run per source is silent.** The first time a source's key shows up
  in the state file, its current codes are seeded into `seen` without
  sending anything to Telegram — only codes that appear *after* that
  baseline are reported. This avoids dumping every historical code the
  moment the stack starts.
- **Health alerts fire only on the broken/healthy edge.** If fetching a
  source raises (network error, HTTP error, etc.), the first failure sends a
  one-shot "scraper พัง" alert; the alert does not repeat on every poll while
  still broken. When the source fetches successfully again, a one-shot
  recovery message is sent.
- **A zero-code result is *not* treated as broken.** WuWa legitimately has 0
  or 1 active codes between livestreams, so an empty result is normal and
  must not trip the health alert (that would train the user to ignore the
  channel).
- State is a single JSON file: `{"seen": {<key>: [codes...]}, "health": {<key>: "ok"|"broken"}}`.

## Adding a new game

Append an entry to the `SOURCES` list in `game_code_notifier.py`:

```python
{
    "key": "my_game",               # stable id, used as the state-file key
    "name": "My Game",              # display name in Telegram messages
    "type": "api_seria" | "table_status" | "section_regex",
    "url": "https://...",
    "scope_selector": ".css-selector-or-None",   # section_regex only
    "code_regex": r"...",                         # table_status / section_regex
    "redeem_url": "https://.../gift?code={code}" or None,
}
```

Pick the closest existing `type`:
- `api_seria` — JSON API shaped like the seria Genshin endpoint (`status`/`code`/`rewards` fields).
- `table_status` — HTML `<table>` with a code column and a status column (keep unless status says "expired").
- `section_regex` — regex-extract codes from a page (optionally scoped to a CSS selector first).

No registration elsewhere is needed — the poll loop iterates `SOURCES`
automatically, and a brand-new key seeds silently on its first run like any
other source.

## Environment

| Var | Default | Description |
|-----|---------|--------------|
| `GAME_CODES_TELEGRAM_BOT_TOKEN` | — | Telegram bot token. Shared with `news-feed` via vault (`stacks.news_feed.telegram.bot_token`). |
| `TELEGRAM_CHAT_ID` | — | Telegram chat id. Shared with `news-feed` via vault (`stacks.news_feed.telegram.chat_id`). |
| `POLL_INTERVAL` | `1800` | Seconds between polls. `0`/unset runs once and exits (cron-style). |
| `STATE_FILE` | `/data/seen_codes.json` | Path to the seen-codes/health JSON, persisted on the `game_codes_data` volume. |

## Tests

```bash
cd game-codes && python -m pytest -v
```

7 tests cover the parsers (fixtures for Genshin JSON, WuWa table HTML, ToD and
RoE scraped HTML) and the runtime (first-run-silent diff, health-alert edges).
