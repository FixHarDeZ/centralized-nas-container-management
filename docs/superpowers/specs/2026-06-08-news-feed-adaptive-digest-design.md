# news-feed: Adaptive Digest Window + Dynamic Size

**Date:** 2026-06-08
**Stack:** `news-feed/`
**Status:** Design

---

## Problem

Articles fetched between digest runs frequently fall outside the digest selection window and are marked "พ้น window" without ever being sent. Latest digest run delivered only a handful of articles despite the backlog. Two compounding causes:

1. **Window/gap mismatch.** The digest job uses a fixed 12h lookback (`get_recent_articles_for_digest(hours=12)`), but the 18:00 → 07:00 overnight gap is 13h. Articles fetched in the 18:00–19:00 window fall off the lookback before the 07:00 digest sees them.
2. **Hard 5-article cap.** `select_digest_articles` returns at most 5 articles total (max 2 per source). With 7 active sources fetching every 60 minutes (up to ~10 articles each), 12h windows often contain 20–50 summarised candidates. Even when the window is wide enough, only 5 ever get sent; the rest expire.

Together, ~70%+ of summarised articles never reach LINE/Telegram on busy days.

## Goal

Eliminate "พ้น window" expiry in normal operation. Every summarised article should get at least one digest tick where it is eligible to be selected, and high-supply digest ticks should send more than 5 articles when the backlog warrants it.

## Non-goals

- Keeping articles eligible forever. Retention cleanup (default 30d) still owns final removal.
- Changing dedup behaviour (`digest_log`-based `sent_ids` continues to prevent repeats).
- Changing summarisation, fetch cadence, source list, or notifier transports.
- Removing the per-source diversity guarantee.

---

## Design

### 1. Adaptive window

Add a helper that computes the lookback window per digest tick instead of using a fixed 12h.

```python
def _compute_digest_window(now: datetime, digest_times: list[str], buffer_hours: float = 1.0) -> float:
    """Return lookback hours = (now - previous digest tick) + buffer.

    Clamped to [4, 36]. `previous tick` may be yesterday for the first digest of the day.
    """
```

Algorithm:
1. Parse `digest_times` (e.g. `["07:00","12:00","18:00"]`) into time-of-day tuples, sorted ascending.
2. Find the latest tick strictly before `now` (today). If none exists today, use the last tick of yesterday.
3. `window_hours = (now - prev_tick_datetime).total_seconds() / 3600 + buffer_hours`.
4. Clamp to `[4, 36]`.

Worked examples (`digest_times = ["07:00","12:00","18:00"]`, buffer = 1h, Asia/Bangkok):

| Now (local)        | Prev tick           | Raw gap | Window |
|--------------------|---------------------|---------|--------|
| 2026-06-08 07:00   | 2026-06-07 18:00    | 13h     | 14h    |
| 2026-06-08 12:00   | 2026-06-08 07:00    | 5h      | 6h     |
| 2026-06-08 18:00   | 2026-06-08 12:00    | 6h      | 7h     |

Edge cases:
- Single digest time configured → prev tick = same time yesterday → gap = 24h → window clamped to 24h.
- Empty `digest_times` → fall back to 12h (current default behaviour preserved).
- Times not sorted or duplicates → sort + dedup before use.

### 2. Dynamic digest size

Extend `select_digest_articles` to grow past the base size when supply allows, still bounded by per-source cap.

```python
def select_digest_articles(
    candidates: list[dict],
    sent_ids: set[str],
    base: int = 5,
    extra_max: int = 5,
    max_per_source: int = 2,
) -> list[dict]:
    """Pick base..base+extra_max articles. Single pass; per-source cap respected throughout."""
```

Behaviour:
- Iterate candidates (already sorted by `published DESC` from the model layer).
- Skip if `id in sent_ids` or per-source count is at `max_per_source`.
- Append until `len(selected) == base + extra_max` or candidates exhausted.
- Result length is between 0 and `base + extra_max`. There is no special threshold for "extras" — the cap just rises from 5 to 10 (configurable).

Rationale for not splitting "base" vs "extras" with separate selection logic: simpler, and the per-source cap already prevents a single noisy source from filling the slot. Increasing `max_per_source` to 3 would let 3-source days dominate; keep it at 2 unless we see this happen.

LINE/Telegram payload: 10 articles × ~150 chars Thai summary = ~1.5 KB. LINE push limit is 5 KB per message — safe headroom.

### 3. Config keys

Add to `_env_defaults()` in `app/config.py` and to `allowed_keys` in `app/api/schedule.py`:

| Key                          | Default | Range / type | Purpose |
|------------------------------|---------|--------------|---------|
| `digest_window_buffer_hours` | `1.0`   | `0–6` float  | Buffer added to gap when computing adaptive window |
| `digest_size_base`           | `5`     | `1–20` int   | Base article count per digest |
| `digest_size_max`            | `10`    | `1–20` int   | Hard ceiling (`base + extra_max`); must be ≥ `base` |
| `digest_max_per_source`      | `2`     | `1–5` int    | Per-source diversity cap |

All consumed via `config.get(key, default)` so existing `schedule.json` files require no migration. Validation rejects out-of-range values and `digest_size_max < digest_size_base`.

### 4. Wire-up in scheduler / API

`_digest_job` in `app/scheduler.py`:
```python
config = get_config()
window = _compute_digest_window(
    datetime.now(BANGKOK_TZ),
    config.get("digest_times", DEFAULT_TIMES),
    buffer_hours=float(config.get("digest_window_buffer_hours", 1.0)),
)
candidates = get_recent_articles_for_digest(conn, hours=window, limit=100)
articles = select_digest_articles(
    candidates, sent_ids,
    base=int(config.get("digest_size_base", 5)),
    extra_max=int(config.get("digest_size_max", 10)) - int(config.get("digest_size_base", 5)),
    max_per_source=int(config.get("digest_max_per_source", 2)),
)
```

`get_recent_articles_for_digest` signature accepts `hours: float` (currently `int`); SQLite `datetime('now', '-X hours')` accepts fractional strings. Bump `limit` default from 50 to 100 since dynamic size needs more raw candidates to filter from.

`/api/digest/trigger` and `/api/digest/test` (`app/api/digest.py`) use the same helper. `/test` response gains diagnostic fields:

```json
{
  "sent_to": ["line", "telegram"],
  "article_count": 8,
  "window_computed_hours": 14.0,
  "candidates_in_window": 23,
  "already_sent_ids": 142,
  "config": {"size_base": 5, "size_max": 10, "max_per_source": 2}
}
```

Drop the existing `available_12h` / `available_24h` / `window_used` keys (they reflect the fixed-window model that no longer exists). Dashboard label that consumes them updates accordingly.

### 5. Frontend badge

`_digestBadge` in `app/static/app.js` currently compares against a hard-coded 12h. Replace with a 36h outer bound (the maximum possible adaptive window). Articles fetched within 36h and not yet sent → "รอส่ง". Older than 36h and unsent → "พ้น window" (rare; only happens if many digests in a row hit `digest_size_max` and a low-priority source keeps producing).

```js
const inWindow = new Date(a.fetched_at) >= new Date(Date.now() - 36 * 3600 * 1000);
```

Rationale for not computing the exact server-side window in JS: avoids re-implementing the algorithm in two languages, and the badge is informational only (does not gate any action).

### 6. Dashboard config UI (optional, included)

Add 4 inputs under the existing Schedule Config card, after "Primary Model" and before "Summarizer Fallback Chain":

- Window buffer (hours, decimal)
- Digest base size (int)
- Digest max size (int)
- Max per source (int)

`saveSchedule` includes the 4 keys in its POST body. No new endpoint; reuses `POST /api/schedule`.

---

## Components touched

| File                            | Change |
|---------------------------------|--------|
| `app/models.py`                 | `get_recent_articles_for_digest` accepts `float` hours and `limit` up to 100; `select_digest_articles` gains `base`/`extra_max` params (keeps legacy `total` as deprecated alias for one release) |
| `app/scheduler.py`              | New `_compute_digest_window`; `_digest_job` uses it + reads new config keys |
| `app/api/digest.py`             | `/trigger` and `/test` use new helper; `/test` returns new diagnostic shape |
| `app/api/schedule.py`           | `allowed_keys` + validation for 4 new keys |
| `app/config.py`                 | `_env_defaults` adds 4 keys |
| `app/static/app.js`             | Badge threshold 12h→36h; render + read 4 new config inputs |
| `app/static/index.html`         | 4 new inputs in Schedule Config card |
| `tests/test_models.py`          | New cases for `select_digest_articles` with base/extra_max |
| `tests/test_scheduler.py`       | New cases for `_compute_digest_window` across all 3 ticks + edge cases |
| `tests/test_api.py`             | Update `/api/digest/test` response shape assertions |
| `news-feed/.notes/00_INDEX.md`  | Update Known Gotchas + Change Log |
| `news-feed/.notes/daily_log.md` | Append today's entry |
| `news-feed/README.md`           | Document new config keys + adaptive window behaviour |

## Compatibility & rollout

- All 4 new config keys are read with `.get(key, default)`. Existing `schedule.json` on the NAS works untouched on first restart, then gains the keys the first time the user clicks Save Config.
- `select_digest_articles(candidates, sent_ids)` (positional only) still works because new params have defaults.
- No DB schema change. No data migration.
- Deploy via standard flow (`make secrets` → `./scripts/deploy.sh`). Container recreate picks up the new code; no env changes required (the 4 new keys are pure config, not secrets).

## Testing

Unit:
- `_compute_digest_window`: each of 3 digest ticks at boundary minute, off-tick minutes, single-time-of-day list, empty list, unsorted list, duplicate times.
- `select_digest_articles`: 3 candidates → returns 3; 5 candidates 1 source → returns 2 (per-source cap); 15 candidates from 5 sources → returns 10 (max); already-sent skipped; per-source cap respected at the extra tier.

Integration:
- `_digest_job` smoke test with seeded DB containing 20 articles across 3 sources and verify 10 selected at 07:00, 5 at 12:00 (smaller window, fewer candidates).
- `/api/digest/test` snapshot includes new keys.

Manual (post-deploy on NAS):
- Trigger `POST /api/digest/test`, verify `window_computed_hours` matches the algorithm for current time.
- Watch the next scheduled 07:00 digest; confirm article count > 5 if backlog exists.
- Verify Schedule Config UI persists the 4 new values.

## Risks

- **LINE/Telegram message size.** 10 articles fit, but if a future change adds long source-specific footers, payload could exceed 5 KB. Mitigation: keep `digest_size_max` configurable; revert to 5 if message truncation is observed.
- **Frontend badge drift.** The 36h heuristic in JS is an upper bound, not the exact server window. Acceptable because the badge is informational and the dedup logic on the backend is the source of truth.
- **`schedule.json` overrides `.env`.** Already a known gotcha (documented). New keys follow the same rule — once a user saves config, `schedule.json` wins. Documented in the change log entry.
