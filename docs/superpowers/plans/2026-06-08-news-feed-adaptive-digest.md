# news-feed Adaptive Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the fixed 12h digest window + hard 5-article cap with an adaptive window sized to the actual gap between digest ticks and a dynamic size that grows up to 10 when the backlog warrants it. Eliminates "พ้น window" expiry in normal operation.

**Architecture:** Pure helper computes lookback hours from `digest_times` + `now`. `select_digest_articles` gains `base`/`extra_max`/`max_per_source` params (replaces old `total=`). Four new config keys plumbed through `_env_defaults`, `/api/schedule` validation, and the Schedule Config UI. Scheduler `_digest_job` and `/api/digest/{trigger,test}` use the new helper. Frontend badge threshold relaxed from 12h to 36h (the outer adaptive bound).

**Tech Stack:** FastAPI · APScheduler · SQLite · vanilla JS frontend · pytest. Asia/Bangkok timezone for scheduling.

**Spec:** `docs/superpowers/specs/2026-06-08-news-feed-adaptive-digest-design.md`

**Working directory for all paths:** `/Users/peerawat.ujaiyen/MyCode/centralized-nas-container-management`

**One deviation from spec:** Spec mentioned keeping legacy `total=` as a deprecated alias on `select_digest_articles`. Plan drops that alias outright — only 4 internal call sites use it, all updated in this PR. Cleaner; YAGNI.

---

## File map

| File | Change |
|------|--------|
| `news-feed/app/scheduler.py` | Add module-level `_compute_digest_window`; rewire `_digest_job` to use it + new config keys |
| `news-feed/app/models.py` | Replace `select_digest_articles` signature; widen `get_recent_articles_for_digest` hours param to `float` |
| `news-feed/app/config.py` | Add 4 keys to `_env_defaults` |
| `news-feed/app/api/schedule.py` | Validate 4 new keys |
| `news-feed/app/api/digest.py` | `/trigger` + `/test` use new helper; `/test` response shape updated |
| `news-feed/app/static/app.js` | Badge threshold 12h→36h; 4 new config inputs read/written; `runTestDigest` reads new response shape |
| `news-feed/app/static/index.html` | 4 new inputs in Schedule Config card |
| `news-feed/tests/test_models.py` | Update existing `select_digest_articles` tests to new signature; add new ones |
| `news-feed/tests/test_scheduler.py` | NEW file: `_compute_digest_window` cases |
| `news-feed/tests/test_api.py` | Update `/api/digest/test` response shape assertion; cover schedule POST for new keys |
| `news-feed/tests/test_config.py` | Cover defaults for 4 new keys |
| `news-feed/README.md` | Document new config keys + behaviour |
| `news-feed/.notes/00_INDEX.md` | New gotcha entry + change log row |
| `news-feed/.notes/daily_log.md` | New dated entry |

---

## Task 1: Pure helper `_compute_digest_window`

**Files:**
- Modify: `news-feed/app/scheduler.py`
- Create: `news-feed/tests/test_scheduler.py`

- [ ] **Step 1.1: Write failing tests**

Create `news-feed/tests/test_scheduler.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.scheduler import _compute_digest_window

BKK = ZoneInfo("Asia/Bangkok")


def _at(year, month, day, hour, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=BKK)


def test_morning_digest_uses_overnight_gap():
    # 07:00 digest, prev tick = yesterday 18:00 → 13h + 1h buffer = 14h
    w = _compute_digest_window(_at(2026, 6, 8, 7, 0), ["07:00", "12:00", "18:00"])
    assert w == pytest.approx(14.0)


def test_noon_digest_uses_morning_gap():
    # 12:00 digest, prev tick = 07:00 → 5h + 1h = 6h
    w = _compute_digest_window(_at(2026, 6, 8, 12, 0), ["07:00", "12:00", "18:00"])
    assert w == pytest.approx(6.0)


def test_evening_digest_uses_noon_gap():
    # 18:00 digest, prev tick = 12:00 → 6h + 1h = 7h
    w = _compute_digest_window(_at(2026, 6, 8, 18, 0), ["07:00", "12:00", "18:00"])
    assert w == pytest.approx(7.0)


def test_single_digest_time_uses_24h():
    # Only one digest/day → prev tick = same time yesterday → 24h + 1h, clamped to 36h ceiling but stays 25h
    w = _compute_digest_window(_at(2026, 6, 8, 9, 0), ["09:00"])
    assert w == pytest.approx(25.0)


def test_clamps_to_min_4h():
    # Two ticks 1 minute apart (pathological) → 0.0167h + 1h ≈ 1.02h, clamped to 4h
    w = _compute_digest_window(_at(2026, 6, 8, 7, 1), ["07:00", "07:01"])
    assert w == 4.0


def test_clamps_to_max_36h():
    # Empty/invalid config falls back gracefully; here we use a >24h gap by using only one tick
    # but with a now() not on that tick — gap will still be < 24h, so use buffer to push past 36h
    w = _compute_digest_window(_at(2026, 6, 8, 7, 0), ["07:00"], buffer_hours=20.0)
    assert w == 36.0


def test_empty_digest_times_falls_back_to_12h():
    w = _compute_digest_window(_at(2026, 6, 8, 7, 0), [])
    assert w == 12.0


def test_unsorted_and_duplicate_times_handled():
    # Same as the canonical test but config came in unsorted with a dup
    w = _compute_digest_window(_at(2026, 6, 8, 7, 0), ["18:00", "07:00", "07:00", "12:00"])
    assert w == pytest.approx(14.0)


def test_off_tick_minute_uses_most_recent_prev_tick():
    # 07:30 → prev tick was today 07:00 → 0.5h + 1h = 1.5h → clamped to 4h
    w = _compute_digest_window(_at(2026, 6, 8, 7, 30), ["07:00", "12:00", "18:00"])
    assert w == 4.0


def test_invalid_time_string_ignored():
    # "bogus" rejected; valid times still used
    w = _compute_digest_window(_at(2026, 6, 8, 7, 0), ["07:00", "bogus", "18:00"])
    assert w == pytest.approx(14.0)
```

- [ ] **Step 1.2: Run tests to verify they fail**

Run: `cd news-feed && python -m pytest tests/test_scheduler.py -v`
Expected: ImportError / 10 failures — `_compute_digest_window` does not exist yet.

- [ ] **Step 1.3: Implement helper**

Add to `news-feed/app/scheduler.py` near the top (after imports, before `_load_summarizer_state`):

```python
from datetime import time as _time

_MIN_WINDOW_HOURS = 4.0
_MAX_WINDOW_HOURS = 36.0
_FALLBACK_WINDOW_HOURS = 12.0


def _parse_digest_times(raw: list[str]) -> list[_time]:
    """Parse 'HH:MM' strings → sorted unique time objects. Invalid entries silently dropped."""
    seen: set[tuple[int, int]] = set()
    out: list[_time] = []
    for s in raw:
        try:
            h, m = s.strip().split(":")
            t = _time(int(h), int(m))
        except (ValueError, AttributeError):
            continue
        key = (t.hour, t.minute)
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    out.sort()
    return out


def _compute_digest_window(
    now: datetime,
    digest_times: list[str],
    buffer_hours: float = 1.0,
) -> float:
    """Lookback hours = (now - previous digest tick) + buffer, clamped to [4, 36].

    If `digest_times` is empty or all invalid, returns 12.0 (legacy default).
    `now` MUST be timezone-aware; the prev-tick calculation uses its date and tzinfo.
    """
    times = _parse_digest_times(digest_times)
    if not times:
        return _FALLBACK_WINDOW_HOURS

    today = now.date()
    candidates_today = [
        datetime.combine(today, t, tzinfo=now.tzinfo) for t in times
    ]
    prev_ticks = [d for d in candidates_today if d < now]
    if prev_ticks:
        prev = max(prev_ticks)
    else:
        # Wrap to yesterday's last tick
        yesterday = today - timedelta(days=1)
        prev = datetime.combine(yesterday, times[-1], tzinfo=now.tzinfo)

    gap_hours = (now - prev).total_seconds() / 3600.0
    window = gap_hours + buffer_hours
    return max(_MIN_WINDOW_HOURS, min(_MAX_WINDOW_HOURS, window))
```

- [ ] **Step 1.4: Run tests to verify they pass**

Run: `cd news-feed && python -m pytest tests/test_scheduler.py -v`
Expected: 10 passed.

- [ ] **Step 1.5: Commit**

```bash
git add news-feed/app/scheduler.py news-feed/tests/test_scheduler.py
git commit -m "feat(news-feed): _compute_digest_window adaptive helper"
```

---

## Task 2: Replace `select_digest_articles` signature

**Files:**
- Modify: `news-feed/app/models.py:206-224`
- Modify: `news-feed/tests/test_models.py:130-150`

- [ ] **Step 2.1: Update existing tests + add new cases**

Edit `news-feed/tests/test_models.py`. Replace the four `select_digest_articles` tests (lines ~118-150) with:

```python
def test_select_digest_articles_basic():
    candidates = [_make_article("a1", "tc"), _make_article("a2", "vb"), _make_article("a3", "tc")]
    result = select_digest_articles(candidates, sent_ids=set())
    assert [a["id"] for a in result] == ["a1", "a2", "a3"]


def test_select_digest_articles_skips_sent():
    candidates = [_make_article("a1", "tc"), _make_article("a2", "vb")]
    result = select_digest_articles(candidates, sent_ids={"a1"})
    assert [a["id"] for a in result] == ["a2"]


def test_select_digest_articles_quota_per_source():
    candidates = [_make_article(f"tc{i}", "techcrunch") for i in range(5)]
    result = select_digest_articles(candidates, sent_ids=set(), max_per_source=2)
    assert len(result) == 2
    assert all(a["source"] == "techcrunch" for a in result)


def test_select_digest_articles_quota_mixed():
    candidates = (
        [_make_article(f"tc{i}", "techcrunch") for i in range(3)] +
        [_make_article(f"vb{i}", "venturebeat") for i in range(3)]
    )
    result = select_digest_articles(
        candidates, sent_ids=set(), base=5, extra_max=0, max_per_source=2
    )
    ids = [a["id"] for a in result]
    assert ids == ["tc0", "tc1", "vb0", "vb1"]


def test_select_digest_articles_base_only():
    candidates = [_make_article(f"a{i}", f"src{i}") for i in range(10)]
    result = select_digest_articles(candidates, sent_ids=set(), base=3, extra_max=0)
    assert len(result) == 3


def test_select_digest_articles_dynamic_size():
    # 15 candidates across 5 sources, base=5, extra_max=5, cap 2/source
    # Expected: 10 articles (5 sources × 2 each)
    candidates = []
    for src in ["a", "b", "c", "d", "e"]:
        for i in range(3):
            candidates.append(_make_article(f"{src}{i}", src))
    result = select_digest_articles(
        candidates, sent_ids=set(), base=5, extra_max=5, max_per_source=2
    )
    assert len(result) == 10
    # Verify per-source cap held throughout the extras
    from collections import Counter
    counts = Counter(a["source"] for a in result)
    assert all(c <= 2 for c in counts.values())


def test_select_digest_articles_supply_below_base():
    candidates = [_make_article("a1", "x"), _make_article("a2", "y")]
    result = select_digest_articles(candidates, sent_ids=set(), base=5, extra_max=5)
    assert len(result) == 2
```

- [ ] **Step 2.2: Run tests to verify they fail**

Run: `cd news-feed && python -m pytest tests/test_models.py::test_select_digest_articles_dynamic_size tests/test_models.py::test_select_digest_articles_supply_below_base tests/test_models.py::test_select_digest_articles_base_only -v`
Expected: TypeError "unexpected keyword argument 'base'" (or similar).

- [ ] **Step 2.3: Update `select_digest_articles`**

Replace `news-feed/app/models.py` lines 206-224 with:

```python
def select_digest_articles(
    candidates: list[dict],
    sent_ids: set[str],
    base: int = 5,
    extra_max: int = 5,
    max_per_source: int = 2,
) -> list[dict]:
    """Pick up to `base + extra_max` articles, max `max_per_source` per source, skipping sent_ids."""
    cap = max(0, int(base)) + max(0, int(extra_max))
    source_counts: dict[str, int] = {}
    selected: list[dict] = []
    for a in candidates:
        if a["id"] in sent_ids:
            continue
        if source_counts.get(a["source"], 0) >= max_per_source:
            continue
        selected.append(a)
        source_counts[a["source"]] = source_counts.get(a["source"], 0) + 1
        if len(selected) >= cap:
            break
    return selected
```

- [ ] **Step 2.4: Run all model tests**

Run: `cd news-feed && python -m pytest tests/test_models.py -v`
Expected: all pass (no test still uses the old `total=` kwarg after Step 2.1).

- [ ] **Step 2.5: Commit**

```bash
git add news-feed/app/models.py news-feed/tests/test_models.py
git commit -m "feat(news-feed): select_digest_articles base+extra_max signature"
```

---

## Task 3: Widen `get_recent_articles_for_digest` hours param

**Files:**
- Modify: `news-feed/app/models.py:102-109`
- Modify: `news-feed/tests/test_models.py` (add float test)

- [ ] **Step 3.1: Write failing test**

Append to `news-feed/tests/test_models.py`:

```python
def test_get_recent_articles_accepts_float_hours(db, sample_article):
    insert_article(db, sample_article)
    update_article_summary(db, "abc123", "สรุปทดสอบ")
    # Float hours must work; SQLite datetime() accepts fractional modifiers.
    results = get_recent_articles_for_digest(db, hours=14.5, limit=10)
    assert len(results) >= 0  # Just exercises the float path without TypeError
```

- [ ] **Step 3.2: Run test**

Run: `cd news-feed && python -m pytest tests/test_models.py::test_get_recent_articles_accepts_float_hours -v`
Expected: PASS already (current signature `hours: int` doesn't reject float at runtime — Python is duck-typed). This test locks in the behaviour so a future typecheck doesn't regress it.

- [ ] **Step 3.3: Update signature**

Edit `news-feed/app/models.py` line 102:

```python
def get_recent_articles_for_digest(conn: sqlite3.Connection, hours: float = 6, limit: int = 5) -> list[dict]:
```

(Just the type annotation. SQLite already handles fractional hours in the modifier string.)

- [ ] **Step 3.4: Run test again**

Run: `cd news-feed && python -m pytest tests/test_models.py::test_get_recent_articles_accepts_float_hours -v`
Expected: PASS.

- [ ] **Step 3.5: Commit**

```bash
git add news-feed/app/models.py news-feed/tests/test_models.py
git commit -m "refactor(news-feed): widen digest hours param to float"
```

---

## Task 4: Add config defaults

**Files:**
- Modify: `news-feed/app/config.py:23-32`
- Modify: `news-feed/tests/test_config.py`

- [ ] **Step 4.1: Write failing tests**

Append to `news-feed/tests/test_config.py`:

```python
def test_env_defaults_includes_digest_tuning_keys(monkeypatch):
    monkeypatch.delenv("DIGEST_TIMES", raising=False)
    from app.config import _env_defaults
    d = _env_defaults()
    assert d["digest_window_buffer_hours"] == 1.0
    assert d["digest_size_base"] == 5
    assert d["digest_size_max"] == 10
    assert d["digest_max_per_source"] == 2
```

- [ ] **Step 4.2: Run test to verify it fails**

Run: `cd news-feed && python -m pytest tests/test_config.py::test_env_defaults_includes_digest_tuning_keys -v`
Expected: KeyError.

- [ ] **Step 4.3: Update `_env_defaults`**

Replace `news-feed/app/config.py` lines 23-32 with:

```python
def _env_defaults() -> dict:
    return {
        "digest_times": [t.strip() for t in os.getenv("DIGEST_TIMES", "07:00,12:00,18:00").split(",")],
        "enabled_sources": [s.strip() for s in os.getenv("ENABLED_SOURCES", ",".join(SOURCES)).split(",")],
        "summarizer_provider": os.getenv("SUMMARIZER_PROVIDER", "anthropic"),
        "summarizer_model": os.getenv("SUMMARIZER_MODEL", "claude-sonnet-4-6"),
        "retention_days": int(os.getenv("RETENTION_DAYS", "30")),
        "summarizer_fallback": [],
        "custom_sources": [],
        "digest_window_buffer_hours": 1.0,
        "digest_size_base": 5,
        "digest_size_max": 10,
        "digest_max_per_source": 2,
    }
```

- [ ] **Step 4.4: Run test**

Run: `cd news-feed && python -m pytest tests/test_config.py -v`
Expected: all pass.

- [ ] **Step 4.5: Commit**

```bash
git add news-feed/app/config.py news-feed/tests/test_config.py
git commit -m "feat(news-feed): four new digest tuning defaults"
```

---

## Task 5: Validate new keys in `/api/schedule`

**Files:**
- Modify: `news-feed/app/api/schedule.py:15` (allowed_keys + validation)
- Modify: `news-feed/tests/test_api.py`

- [ ] **Step 5.1: Write failing tests**

Append to `news-feed/tests/test_api.py`:

```python
def test_schedule_post_accepts_tuning_keys(client):
    r = client.post("/api/schedule", json={
        "digest_window_buffer_hours": 2.0,
        "digest_size_base": 3,
        "digest_size_max": 8,
        "digest_max_per_source": 3,
    })
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["digest_window_buffer_hours"] == 2.0
    assert cfg["digest_size_base"] == 3
    assert cfg["digest_size_max"] == 8
    assert cfg["digest_max_per_source"] == 3


def test_schedule_post_rejects_out_of_range(client):
    r = client.post("/api/schedule", json={
        "digest_size_base": 999,        # > 20, ignored
        "digest_size_max": -5,          # < 1, ignored
        "digest_max_per_source": 0,     # < 1, ignored
        "digest_window_buffer_hours": 100.0,  # > 6, ignored
    })
    assert r.status_code == 200
    cfg = r.json()
    # All four keys should retain defaults because each value was rejected
    assert cfg["digest_size_base"] == 5
    assert cfg["digest_size_max"] == 10
    assert cfg["digest_max_per_source"] == 2
    assert cfg["digest_window_buffer_hours"] == 1.0


def test_schedule_post_rejects_max_less_than_base(client):
    # Setting base=8 alone is fine
    r = client.post("/api/schedule", json={"digest_size_base": 8})
    assert r.json()["digest_size_base"] == 8
    # But setting max=3 while base=8 is invalid → max should be ignored
    r = client.post("/api/schedule", json={"digest_size_max": 3})
    assert r.json()["digest_size_max"] == 10  # unchanged from default
```

- [ ] **Step 5.2: Run tests to verify they fail**

Run: `cd news-feed && python -m pytest tests/test_api.py::test_schedule_post_accepts_tuning_keys -v`
Expected: assertion fail — keys are stripped by the filter.

- [ ] **Step 5.3: Update `post_schedule`**

Replace the body of `post_schedule` in `news-feed/app/api/schedule.py` with:

```python
@router.post("")
def post_schedule(body: dict):
    allowed_keys = {
        "digest_times", "enabled_sources", "summarizer_provider", "summarizer_model",
        "retention_days", "summarizer_fallback", "custom_sources",
        "digest_window_buffer_hours", "digest_size_base", "digest_size_max",
        "digest_max_per_source",
    }
    filtered = {k: v for k, v in body.items() if k in allowed_keys}
    if "retention_days" in filtered:
        try:
            filtered["retention_days"] = max(1, int(filtered["retention_days"]))
        except (TypeError, ValueError):
            del filtered["retention_days"]
    if "summarizer_fallback" in filtered:
        valid_providers = {"anthropic", "openrouter", "mimo"}
        fb = filtered["summarizer_fallback"]
        if isinstance(fb, list):
            filtered["summarizer_fallback"] = [
                {"provider": str(e.get("provider", "anthropic")), "model": str(e.get("model", ""))}
                for e in fb
                if isinstance(e, dict) and e.get("provider") in valid_providers
            ]
        else:
            del filtered["summarizer_fallback"]
    if "custom_sources" in filtered:
        cs = filtered["custom_sources"]
        if isinstance(cs, list):
            filtered["custom_sources"] = [
                {"key": str(e.get("key", "")).strip(), "name": str(e.get("name", "")).strip(), "url": str(e.get("url", "")).strip()}
                for e in cs
                if isinstance(e, dict)
                and str(e.get("key", "")).strip()
                and str(e.get("url", "")).strip().startswith("http")
            ]
        else:
            del filtered["custom_sources"]

    # Range validation for the four new tuning keys.
    def _clamp_int(key: str, lo: int, hi: int) -> None:
        if key not in filtered:
            return
        try:
            v = int(filtered[key])
        except (TypeError, ValueError):
            del filtered[key]
            return
        if v < lo or v > hi:
            del filtered[key]
        else:
            filtered[key] = v

    def _clamp_float(key: str, lo: float, hi: float) -> None:
        if key not in filtered:
            return
        try:
            v = float(filtered[key])
        except (TypeError, ValueError):
            del filtered[key]
            return
        if v < lo or v > hi:
            del filtered[key]
        else:
            filtered[key] = v

    _clamp_float("digest_window_buffer_hours", 0.0, 6.0)
    _clamp_int("digest_size_base", 1, 20)
    _clamp_int("digest_size_max", 1, 20)
    _clamp_int("digest_max_per_source", 1, 5)

    # Cross-field: max must be ≥ base. Compare against the merged result so a partial update
    # (only max sent, base from existing config) is validated correctly.
    if "digest_size_max" in filtered:
        existing = get_config()
        prospective_base = filtered.get("digest_size_base", existing.get("digest_size_base", 5))
        if filtered["digest_size_max"] < int(prospective_base):
            del filtered["digest_size_max"]

    return update_config(filtered)
```

- [ ] **Step 5.4: Run tests**

Run: `cd news-feed && python -m pytest tests/test_api.py -v`
Expected: all pass.

- [ ] **Step 5.5: Commit**

```bash
git add news-feed/app/api/schedule.py news-feed/tests/test_api.py
git commit -m "feat(news-feed): validate digest tuning keys in POST /api/schedule"
```

---

## Task 6: Wire `_digest_job` to use adaptive window + dynamic size

**Files:**
- Modify: `news-feed/app/scheduler.py:75-117`

- [ ] **Step 6.1: Write failing test**

Append to `news-feed/tests/test_scheduler.py`:

```python
def test_digest_job_uses_adaptive_window_and_dynamic_size(tmp_path, monkeypatch):
    """Smoke test: 15 fresh articles across 5 sources at 07:00 → 10 sent (max), 12:00 → 6 (limited by sources)."""
    from datetime import datetime, timezone
    from app.config import update_config
    from app.models import get_conn, init_db, insert_article, update_article_summary
    from app.scheduler import setup_scheduler

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db_path = str(tmp_path / "news.db")
    conn = get_conn(db_path)
    init_db(conn)

    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for src in ["a", "b", "c", "d", "e"]:
        for i in range(3):
            aid = f"{src}{i}"
            insert_article(conn, {
                "id": aid, "source": src,
                "title": f"t-{aid}", "url": f"https://x/{aid}",
                "published": "2026-06-08T06:00:00",
                "fetched_at": now_iso,
            })
            update_article_summary(conn, aid, "สรุป")
    conn.close()

    update_config({
        "digest_size_base": 5, "digest_size_max": 10, "digest_max_per_source": 2,
        "digest_window_buffer_hours": 1.0,
        "digest_times": ["07:00", "12:00", "18:00"],
    })

    sent = []
    monkeypatch.setattr("app.scheduler.send_digest", lambda articles, cfg: sent.append(list(articles)) or ["line"])

    sched = setup_scheduler(db_path)
    job = next(j for j in sched.get_jobs() if j.id.startswith("digest_"))
    job.func()  # invoke once

    assert len(sent) == 1
    assert len(sent[0]) == 10  # 5 sources × 2 per source = 10
```

- [ ] **Step 6.2: Run test**

Run: `cd news-feed && python -m pytest tests/test_scheduler.py::test_digest_job_uses_adaptive_window_and_dynamic_size -v`
Expected: assertion fail (current logic returns 5 articles, not 10).

- [ ] **Step 6.3: Update `_digest_job`**

In `news-feed/app/scheduler.py`, find `_digest_job` (around line 75) and replace its body:

```python
    def _digest_job() -> None:
        config = get_config()
        conn = get_conn(db_path)
        data_dir = Path(db_path).parent
        try:
            bkk = ZoneInfo("Asia/Bangkok")
            now_local = datetime.now(bkk)
            window_hours = _compute_digest_window(
                now_local,
                config.get("digest_times", ["07:00", "12:00", "18:00"]),
                buffer_hours=float(config.get("digest_window_buffer_hours", 1.0)),
            )
            history = get_digest_history(conn, limit=20)
            sent_ids = {aid for entry in history for aid in entry["article_ids"]}
            candidates = get_recent_articles_for_digest(conn, hours=window_hours, limit=100)
            base = int(config.get("digest_size_base", 5))
            size_max = int(config.get("digest_size_max", 10))
            extra_max = max(0, size_max - base)
            articles = select_digest_articles(
                candidates, sent_ids,
                base=base,
                extra_max=extra_max,
                max_per_source=int(config.get("digest_max_per_source", 2)),
            )
            sent = send_digest(articles, config)
            if sent and articles:
                insert_digest_log(
                    conn,
                    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    [a["id"] for a in articles],
                    ",".join(sent),
                )
            logger.info(
                "digest_job sent to: %s (window=%.1fh, candidates=%d, selected=%d)",
                sent, window_hours, len(candidates), len(articles),
            )

            # Alert if summarizer appears broken (candidates exist but none have summaries)
            state = _load_summarizer_state(data_dir)
            if candidates and not articles:
                state["consecutive_empty"] = state.get("consecutive_empty", 0) + 1
                logger.warning(
                    "digest_job: %d candidates but 0 articles sent (consecutive_empty=%d)",
                    len(candidates), state["consecutive_empty"],
                )
                if state["consecutive_empty"] >= _ALERT_THRESHOLD:
                    last = state.get("last_alert_at")
                    now = datetime.now(timezone.utc)
                    cooldown_ok = last is None or (
                        now - datetime.fromisoformat(last) > timedelta(hours=_ALERT_COOLDOWN_HOURS)
                    )
                    if cooldown_ok:
                        send_summarizer_alert(config)
                        state["last_alert_at"] = now.isoformat()
                        state["consecutive_empty"] = 0
                        logger.warning("summarizer_alert sent")
            else:
                state["consecutive_empty"] = 0
            _save_summarizer_state(data_dir, state)
        finally:
            conn.close()
```

Add `from zoneinfo import ZoneInfo` to imports at the top of `scheduler.py` if not already present.

- [ ] **Step 6.4: Run test**

Run: `cd news-feed && python -m pytest tests/test_scheduler.py -v`
Expected: all pass.

- [ ] **Step 6.5: Run full test suite to catch regressions**

Run: `cd news-feed && python -m pytest -v`
Expected: all pass (existing scheduler-alert tests should still work).

- [ ] **Step 6.6: Commit**

```bash
git add news-feed/app/scheduler.py news-feed/tests/test_scheduler.py
git commit -m "feat(news-feed): digest_job uses adaptive window + dynamic size"
```

---

## Task 7: Update `/api/digest/test` and `/trigger` response shape

**Files:**
- Modify: `news-feed/app/api/digest.py`
- Modify: `news-feed/tests/test_api.py`

- [ ] **Step 7.1: Write failing tests**

Append to `news-feed/tests/test_api.py`:

```python
def test_digest_test_returns_new_shape(client, monkeypatch):
    monkeypatch.setattr("app.api.digest.send_digest", lambda articles, cfg: ["line"])
    r = client.post("/api/digest/test")
    assert r.status_code == 200
    body = r.json()
    assert "window_computed_hours" in body
    assert "candidates_in_window" in body
    assert "config" in body
    assert set(body["config"].keys()) == {"size_base", "size_max", "max_per_source"}
    # Old fields are gone
    assert "available_12h" not in body
    assert "window_used" not in body
```

- [ ] **Step 7.2: Run test**

Run: `cd news-feed && python -m pytest tests/test_api.py::test_digest_test_returns_new_shape -v`
Expected: assertion fail.

- [ ] **Step 7.3: Rewrite `/test` and `/trigger`**

Replace the body of `news-feed/app/api/digest.py` (everything below `router = APIRouter(...)`) with:

```python
@router.get("/history")
def digest_history(db: Annotated[sqlite3.Connection, Depends(get_db)]):
    return get_digest_history(db)


def _run_digest(db_path: str, *, log_when_sent: bool = True) -> dict:
    """Shared digest execution path for /trigger and /test."""
    from zoneinfo import ZoneInfo
    from app.scheduler import _compute_digest_window

    config = get_config()
    conn = get_conn(db_path)
    try:
        bkk = ZoneInfo("Asia/Bangkok")
        window_hours = _compute_digest_window(
            datetime.now(bkk),
            config.get("digest_times", ["07:00", "12:00", "18:00"]),
            buffer_hours=float(config.get("digest_window_buffer_hours", 1.0)),
        )
        history = get_digest_history(conn, limit=20)
        sent_ids = {aid for entry in history for aid in entry["article_ids"]}
        candidates = get_recent_articles_for_digest(conn, hours=window_hours, limit=100)
        base = int(config.get("digest_size_base", 5))
        size_max = int(config.get("digest_size_max", 10))
        articles = select_digest_articles(
            candidates, sent_ids,
            base=base,
            extra_max=max(0, size_max - base),
            max_per_source=int(config.get("digest_max_per_source", 2)),
        )
        sent = send_digest(articles, config)
        if log_when_sent and sent and articles:
            insert_digest_log(
                conn,
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                [a["id"] for a in articles],
                ",".join(sent),
            )
        return {
            "sent_to": sent,
            "article_count": len(articles),
            "window_computed_hours": round(window_hours, 2),
            "candidates_in_window": len(candidates),
            "already_sent_ids": len(sent_ids),
            "config": {
                "size_base": base,
                "size_max": size_max,
                "max_per_source": int(config.get("digest_max_per_source", 2)),
            },
        }
    finally:
        conn.close()


@router.post("/trigger")
def trigger_digest(x_admin_token: Optional[str] = Header(None)):
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected or x_admin_token != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
    from app.config import DB_PATH
    return _run_digest(DB_PATH)


@router.post("/test")
def test_digest(request: Request):
    """Send a test digest immediately (no admin token required — protected by nginx basic auth)."""
    return _run_digest(request.app.state.db_path)
```

Keep the existing imports at the top of the file; remove the now-unused legacy logic.

- [ ] **Step 7.4: Run tests**

Run: `cd news-feed && python -m pytest tests/test_api.py -v`
Expected: all pass.

- [ ] **Step 7.5: Commit**

```bash
git add news-feed/app/api/digest.py news-feed/tests/test_api.py
git commit -m "feat(news-feed): digest /test response includes adaptive window info"
```

---

## Task 8: Frontend badge threshold + test-digest status label

**Files:**
- Modify: `news-feed/app/static/app.js:303-309`
- Modify: `news-feed/app/static/app.js:600-605` (runTestDigest status text)

- [ ] **Step 8.1: Update badge threshold**

Edit `news-feed/app/static/app.js`. Find `_digestBadge` near line 303. Change the `12 * 60 * 60 * 1000` constant:

```javascript
function _digestBadge(a) {
  if (_sentIds.has(a.id)) return '<span class="digest-badge badge-sent">ส่งแล้ว</span>';
  if (!a.summary_th) return '';
  // 36h is the outer bound of the adaptive digest window. Beyond that, an article
  // very likely missed its slot and won't be picked up.
  const inWindow = new Date(a.fetched_at) >= new Date(Date.now() - 36 * 60 * 60 * 1000);
  if (inWindow) return '<span class="digest-badge badge-pending">รอส่ง</span>';
  return '<span class="digest-badge badge-expired">พ้น window</span>';
}
```

- [ ] **Step 8.2: Update `runTestDigest` status label**

Find the test-digest success branch near line 604. Replace the status line:

```javascript
      statusEl.textContent = `✓ ส่งสำเร็จ → ${data.sent_to.join(', ')} (${data.article_count} บทความ, window: ${data.window_computed_hours}h, candidates: ${data.candidates_in_window})`;
```

- [ ] **Step 8.3: Verify in browser**

There are no frontend tests in this repo. Manual check is deferred to the final Task 11 (post-deploy verification).

- [ ] **Step 8.4: Commit**

```bash
git add news-feed/app/static/app.js
git commit -m "feat(news-feed): badge threshold 36h, test-digest status shows window"
```

---

## Task 9: Schedule Config UI — 4 new inputs

**Files:**
- Modify: `news-feed/app/static/index.html` (Schedule Config card)
- Modify: `news-feed/app/static/app.js` (loadScheduleConfig + saveSchedule)

- [ ] **Step 9.1: Locate the Schedule Config card**

Run: `grep -n "Primary Model\|Summarizer Fallback\|Schedule Config" news-feed/app/static/index.html`

You should find the card section that contains Primary Model inputs and the Summarizer Fallback Chain heading. The 4 new inputs go between them.

- [ ] **Step 9.2: Add HTML inputs**

Insert this block in `news-feed/app/static/index.html` immediately after the closing of the Primary Model card and before the Summarizer Fallback Chain card (find the exact location with grep above):

```html
<div class="card">
  <h3>Digest Tuning</h3>
  <div class="form-row">
    <label>Window buffer (hours)
      <input type="number" id="cfg-window-buffer" step="0.5" min="0" max="6">
    </label>
    <label>Base size
      <input type="number" id="cfg-size-base" step="1" min="1" max="20">
    </label>
    <label>Max size
      <input type="number" id="cfg-size-max" step="1" min="1" max="20">
    </label>
    <label>Max per source
      <input type="number" id="cfg-max-per-source" step="1" min="1" max="5">
    </label>
  </div>
  <p style="font-size:.85em;color:#64748b;margin:.5rem 0 0">
    Adaptive lookback adds buffer to the gap between digest ticks (clamped 4–36h).
    Dynamic size grows from base up to max when many candidates exist.
  </p>
</div>
```

If the existing form structure uses a different wrapper class (look at adjacent cards), match it. The IDs `cfg-window-buffer`, `cfg-size-base`, `cfg-size-max`, `cfg-max-per-source` are the contract with JS.

- [ ] **Step 9.3: Read values in `loadScheduleConfig`**

In `news-feed/app/static/app.js`, find `loadScheduleConfig`. After other field reads (e.g., `document.getElementById('cfg-retention').value = ...`), add:

```javascript
  document.getElementById('cfg-window-buffer').value = cfg.digest_window_buffer_hours ?? 1.0;
  document.getElementById('cfg-size-base').value = cfg.digest_size_base ?? 5;
  document.getElementById('cfg-size-max').value = cfg.digest_size_max ?? 10;
  document.getElementById('cfg-max-per-source').value = cfg.digest_max_per_source ?? 2;
```

- [ ] **Step 9.4: Send values in `saveSchedule`**

In the same file, find `saveSchedule`. In the POST body assembly add:

```javascript
    digest_window_buffer_hours: parseFloat(document.getElementById('cfg-window-buffer').value),
    digest_size_base: parseInt(document.getElementById('cfg-size-base').value, 10),
    digest_size_max: parseInt(document.getElementById('cfg-size-max').value, 10),
    digest_max_per_source: parseInt(document.getElementById('cfg-max-per-source').value, 10),
```

- [ ] **Step 9.5: Commit**

```bash
git add news-feed/app/static/index.html news-feed/app/static/app.js
git commit -m "feat(news-feed): Schedule Config UI for digest tuning"
```

---

## Task 10: Update docs (.notes + README)

**Files:**
- Modify: `news-feed/README.md`
- Modify: `news-feed/.notes/00_INDEX.md`
- Modify: `news-feed/.notes/daily_log.md`

- [ ] **Step 10.1: Update README**

Add a section to `news-feed/README.md` describing the four new config keys. Insert it near the existing config documentation (find with `grep -n "DIGEST_TIMES\|RETENTION_DAYS" news-feed/README.md`):

```markdown
### Digest Tuning (schedule.json / dashboard)

Adaptive lookback + dynamic size replaces the old fixed 12h/5-article model.

| Key                          | Default | Range   | Purpose |
|------------------------------|---------|---------|---------|
| `digest_window_buffer_hours` | `1.0`   | 0–6     | Added to the gap between consecutive digest ticks; clamped to [4, 36] |
| `digest_size_base`           | `5`     | 1–20    | Base articles per digest |
| `digest_size_max`            | `10`    | 1–20    | Hard ceiling (must be ≥ base) |
| `digest_max_per_source`      | `2`     | 1–5     | Per-source diversity cap |

Window is computed at each tick as `(now - prev_tick) + buffer`, so the overnight
07:00 digest sees ~14h while the 12:00 digest sees ~6h. Articles never fall off
between fetch and the next eligible digest under normal cadence.
```

- [ ] **Step 10.2: Update 00_INDEX.md**

Append to the "Known Gotchas" section in `news-feed/.notes/00_INDEX.md`:

```markdown
- **Adaptive digest window**: `_compute_digest_window(now, digest_times, buffer)` ใน `app/scheduler.py` คำนวณ lookback จาก gap ระหว่าง digest ticks (clamp 4–36h). ห้าม hardcode 12h ที่ฝั่ง consumer ใหม่ — อ่านจาก helper เสมอ. Frontend `_digestBadge` ใช้ 36h outer bound (heuristic, ไม่ใช่ค่า window จริง).
- **`digest_size_max` < `digest_size_base` reject**: `/api/schedule` ตรวจ cross-field validation; max ที่ส่งมาน้อยกว่า base ปัจจุบัน → ไม่บันทึก (ค่าเดิมคงอยู่). ส่ง `digest_size_base` กับ `digest_size_max` พร้อมกันถ้าจะลด max
```

Append a new row to the Change Log table:

```markdown
| 2026-06-08 | Feature: Adaptive digest window + dynamic size — `_compute_digest_window` helper, `select_digest_articles(base, extra_max, max_per_source)`, 4 config keys (`digest_window_buffer_hours`, `digest_size_base`, `digest_size_max`, `digest_max_per_source`), badge threshold 12h→36h, `/api/digest/test` response shape updated |
```

- [ ] **Step 10.3: Update daily_log.md**

Prepend to `news-feed/.notes/daily_log.md` (under the header line):

```markdown
## 2026-06-08 — Adaptive Digest Window + Dynamic Size

### งานที่ทำ
แก้ปัญหา "พ้น window" — fixed 12h ไม่ครอบคลุม overnight gap 13h + cap 5 articles ไม่พอ flush backlog

**Backend:**
- `app/scheduler.py`: `_compute_digest_window(now, digest_times, buffer=1.0)` คำนวณ lookback จาก gap (clamp 4–36h); `_digest_job` ใช้ helper + config keys ใหม่
- `app/models.py`: `select_digest_articles(base=5, extra_max=5, max_per_source=2)` แทน `total=`; `get_recent_articles_for_digest(hours: float)` รองรับเศษส่วน
- `app/config.py`: 4 defaults ใหม่ (`digest_window_buffer_hours`, `digest_size_base`, `digest_size_max`, `digest_max_per_source`)
- `app/api/schedule.py`: validation + cross-field check `digest_size_max ≥ digest_size_base`
- `app/api/digest.py`: `/test` + `/trigger` แชร์ `_run_digest()`; response shape ใหม่ (`window_computed_hours`, `candidates_in_window`, `config{}`)

**Frontend:**
- `app.js`: badge threshold 12h→36h; runTestDigest status แสดง window + candidates
- `index.html`: Digest Tuning card (4 inputs) ใน Schedule Config

### Tests
N pass (ตัวเลขจริงเติมหลังรัน suite สุดท้าย — Task 11)
```

- [ ] **Step 10.4: Commit**

```bash
git add news-feed/README.md news-feed/.notes/00_INDEX.md news-feed/.notes/daily_log.md
git commit -m "docs(news-feed): adaptive digest window + dynamic size"
```

---

## Task 11: Final verification + deploy

- [ ] **Step 11.1: Run full test suite**

Run: `cd news-feed && python -m pytest -v`
Expected: all tests pass. Note the count.

- [ ] **Step 11.2: Update test count in daily_log.md**

Replace `N pass` in `news-feed/.notes/daily_log.md` with the actual number from Step 11.1, then commit:

```bash
git add news-feed/.notes/daily_log.md
git commit -m "docs(news-feed): record test count for adaptive digest"
```

- [ ] **Step 11.3: Deploy to NAS**

Run: `./scripts/deploy.sh news-feed`
Expected: tar+ssh upload, `docker compose up -d --build` on the NAS, news-feed container recreates.

- [ ] **Step 11.4: Post-deploy smoke test**

Open the dashboard, navigate to Schedule Config → Digest Tuning. Verify the 4 inputs render with current values (defaults if first deploy).

Click "Test Digest". Verify the response message includes `window: Xh, candidates: Y` and that `X` matches the algorithm for the current local time (e.g., at 14:30 BKK with default times 07/12/18, prev tick = 12:00, window = 2.5h + 1h = 3.5h → clamped to 4h).

- [ ] **Step 11.5: Wait for next scheduled tick**

Watch the container logs at the next digest tick: `ssh nas "docker logs news-feed --tail 50 | grep digest_job"`. Confirm the log line shows the computed window and selected count.

Expected log line format: `digest_job sent to: ['line', 'telegram'] (window=14.0h, candidates=23, selected=10)`.

- [ ] **Step 11.6: Confirm "พ้น window" backlog is drained over the next 1-2 days**

In the dashboard's News Timeline, count badges of type `badge-expired` ("พ้น window"). This number should be flat or decreasing over 48h with the new behaviour. If it's still climbing, the helper isn't being hit or `digest_size_max` is too low — diagnose with `POST /api/digest/test`.

---

## Self-Review

**Spec coverage check:**

| Spec section | Implementing task |
|--------------|-------------------|
| §1 Adaptive window helper | Task 1 |
| §2 Dynamic size in `select_digest_articles` | Task 2 |
| §3 Four new config keys | Task 4 + 5 |
| §4 `_digest_job` + `/digest/{trigger,test}` wire-up | Task 6 + 7 |
| §5 Frontend badge 12h→36h | Task 8 |
| §6 Dashboard config UI (4 inputs) | Task 9 |
| Compatibility & rollout | Task 4 (defaults) + Task 11 (deploy) |
| Testing strategy | Tasks 1, 2, 5, 6, 7, 11 |
| Files touched table | Full map at top of plan |
| Risks: LINE message size | Mitigated by `digest_size_max` config (Task 4); user can lower if needed |
| Risks: Frontend badge drift | Documented in Task 10 gotcha |
| Risks: `schedule.json` override | Existing gotcha; new keys follow same rule (Task 10) |

**Placeholder scan:** No "TBD", "TODO", or "fill in details". Every code block contains the actual code. Every test contains the actual assertions.

**Type consistency:** Helper signature `_compute_digest_window(now, digest_times, buffer_hours=1.0) -> float` used identically in Tasks 1, 6, 7. `select_digest_articles(candidates, sent_ids, base, extra_max, max_per_source)` used identically in Tasks 2, 6, 7. Config keys `digest_window_buffer_hours / digest_size_base / digest_size_max / digest_max_per_source` spelled identically in Tasks 4, 5, 6, 7, 9, 10.

**Deviation from spec noted:** Plan drops the legacy `total=` alias on `select_digest_articles` instead of keeping it for a release. Reason: only 4 internal call sites use it, all updated in this PR; deprecation alias is dead code on day 1. Recorded at top of plan.
