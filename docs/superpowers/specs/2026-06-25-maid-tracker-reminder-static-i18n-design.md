# Maid-Tracker Reminder Translation — Static Dict Replaces LLM — Design

**Date:** 2026-06-25
**Stack:** `maid-tracker/`
**Status:** Design — approved by owner
**Supersedes:** Feature C of `2026-06-24-maid-tracker-multilingual-notify-design.md`

## Problem

Feature C (2026-06-24) translates reminder free-text via MiMo LLM, cached to
`reminders.message_i18n` on save. Caching already solved the "translate every
send" cost — but the underlying input set turned out to be tiny and almost
static: owner confirms ~2-10 distinct reminder texts exist, and new ones are
added rarely. An LLM dependency (API key, network call, two known failure
modes already patched — empty `content` from token starvation, MiMo's
reasoning-token burn) buys nothing over a hand-maintained dict for an input
space this small. `i18n.py` already proves the static-dict pattern works for
the system-template messages; apply the same pattern here.

## Design

### 1. New module `reminder_i18n.py` replaces `reminder_translate.py`

```python
# machine-generated (seeded from MiMo output already in production),
# needs native-speaker review — same caveat as i18n.py
REMINDERS = {
    "🛏️ วันนี้เปลี่ยนผ้าปูที่นอนด้วยนะคะ": {
        "my": "...", "en": "...", "lo": "...", "km": "...",
    },
    "🚿 วันนี้ล้างห้องน้ำด้วยนะคะ": {
        "my": "...", "en": "...", "lo": "...", "km": "...",
    },
}


def lookup(text: str) -> dict | None:
    return REMINDERS.get(text)
```

Same return shape as the old `translate_reminder(text) -> dict | None`
(`{"my":..,"en":..,"lo":..,"km":..}` or `None`). Drop-in swap at all 4 call
sites in `main.py` (lines 471, 1947, 1975, 2032):
`reminder_translate.translate_reminder(text)` → `reminder_i18n.lookup(text)`.
No other line changes — `message_i18n` DB column, its cache-write logic, and
`line_notify._reminder_body`'s consumption of it are all untouched.

### 2. Seed data — exported from production, not re-translated

Pull current `message_i18n` values off the NAS `reminders` table (already
LLM-translated once, live in production) into `REMINDERS`, keyed by the exact
`message` text. No new LLM call. New reminder text not yet in the dict →
`lookup()` returns `None` → existing fallback (Thai-only send) already
handles it, no code change needed.

When the owner adds a genuinely new reminder text in the future: add an entry
to `REMINDERS` by hand (or run `reminder_translate.py`'s old MiMo call
one-off, paste the result in, mark reviewed). Acceptable given the confirmed
near-zero growth rate.

### 3. Cleanup

- Delete `maid-tracker/reminder_translate.py`.
- Remove `MIMO_API_KEY` / `MIMO_BASE_URL` / `MIMO_MODEL` from
  `maid-tracker/secrets.manifest.yaml` only. The vault key
  `shared.llm.mimo_api_key` itself stays — `news-feed` still consumes it.
- `http_client.py` (vendored for the MiMo call) — check if anything else in
  `maid-tracker/` still imports it; if not, remove it too (`make sync-shared`
  re-vendors if ever needed again).

## Testing

- Existing reminder-cache round-trip tests (save → `message_i18n` populated →
  send picks active language) get a search-replace: swap the MiMo-call mock
  for a `REMINDERS` dict entry / lookup miss.
- `test_reminder` endpoint (`main.py:2022`) and create/update paths: assert
  `lookup()` of a known seeded text returns the 4-language dict; assert an
  unseeded text returns `None` and the send falls back Thai-only.

## Out of scope

- No change to Feature A (static template fragments, `i18n.py`) or Feature B
  (daily-pay override) from the prior design — those already shipped as-is.
- No native-speaker review of the seeded strings in this change — they carry
  forward the same unverified-machine-output status they had as LLM output;
  swapping the engine doesn't change that risk, just removes the ongoing LLM
  dependency.

## Files touched

- `maid-tracker/reminder_i18n.py` — **new**, static dict + `lookup()`.
- `maid-tracker/reminder_translate.py` — **deleted**.
- `maid-tracker/main.py` — 4 call sites swap import + function call.
- `maid-tracker/secrets.manifest.yaml` — remove 3 MiMo entries.
- `maid-tracker/http_client.py` — removed if no longer imported by anything else in the stack.
- `maid-tracker/tests/` — update reminder-translation tests to dict-based.
- `maid-tracker/.notes/daily_log.md` + `00_INDEX.md` — update per project rules.

## Risks

- **Seed data must come from NAS**, not re-generated locally — re-running the
  LLM would produce different unverified strings, defeating the point. Pull
  exact `message_i18n` values from the live `reminders` table before deleting
  `reminder_translate.py`.
- Forgetting to add a dict entry for a brand-new reminder text silently falls
  back to Thai-only — same failure mode as today's "LLM failed" path, so not
  a regression, just a different trigger.
