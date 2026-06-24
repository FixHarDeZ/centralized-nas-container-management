from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest
from app.scheduler import _compute_digest_window, _parse_digest_times

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
    w = _compute_digest_window(
        _at(2026, 6, 8, 7, 0), ["18:00", "07:00", "07:00", "12:00"],
    )
    assert w == pytest.approx(14.0)


def test_off_tick_minute_uses_most_recent_prev_tick():
    # 07:30 → prev tick was today 07:00 → 0.5h + 1h = 1.5h → clamped to 4h
    w = _compute_digest_window(_at(2026, 6, 8, 7, 30), ["07:00", "12:00", "18:00"])
    assert w == 4.0


def test_invalid_time_string_ignored():
    # "bogus" rejected; valid times still used
    w = _compute_digest_window(_at(2026, 6, 8, 7, 0), ["07:00", "bogus", "18:00"])
    assert w == pytest.approx(14.0)


def test_naive_datetime_raises():
    with pytest.raises(ValueError, match="timezone-aware"):
        _compute_digest_window(datetime(2026, 6, 8, 7, 0), ["07:00"])


def test_tick_fired_late_uses_previous_tick_not_itself():
    # APScheduler fires at HH:MM:00.xxxxxx — without flooring, the helper would
    # treat the current tick as its own previous tick (gap ≈ 1ms → clamp to 4h min).
    # With minute-floor, the 07:00 tick correctly wraps to yesterday's 23:00 prev.
    now = datetime(2026, 6, 8, 7, 0, 0, 1234, tzinfo=BKK)
    w = _compute_digest_window(now, ["07:00", "12:00", "17:00", "20:00", "23:00"])
    # prev = yesterday 23:00 → gap = 8h + 1h buffer = 9h
    assert w == pytest.approx(9.0)


def test_tick_fired_late_morning_canonical():
    # Same as test_morning_digest_uses_overnight_gap but with microseconds.
    now = datetime(2026, 6, 8, 7, 0, 0, 9999, tzinfo=BKK)
    w = _compute_digest_window(now, ["07:00", "12:00", "18:00"])
    assert w == pytest.approx(14.0)


# --- Direct tests for _parse_digest_times ---


def test_parse_times_basic():
    result = _parse_digest_times(["07:00", "12:00", "18:00"])
    assert [(t.hour, t.minute) for t in result] == [(7, 0), (12, 0), (18, 0)]


def test_parse_times_strips_whitespace():
    result = _parse_digest_times(["  07:00  ", "12:00"])
    assert [(t.hour, t.minute) for t in result] == [(7, 0), (12, 0)]


def test_parse_times_dedupes():
    result = _parse_digest_times(["07:00", "07:00", "12:00"])
    assert [(t.hour, t.minute) for t in result] == [(7, 0), (12, 0)]


def test_parse_times_sorts():
    result = _parse_digest_times(["18:00", "07:00", "12:00"])
    assert [(t.hour, t.minute) for t in result] == [(7, 0), (12, 0), (18, 0)]


def test_parse_times_single_digit_accepted():
    # "7:0" → time(7, 0) is valid per Python int() parsing
    result = _parse_digest_times(["7:0"])
    assert [(t.hour, t.minute) for t in result] == [(7, 0)]


def test_parse_times_rejects_hhmmss():
    # "07:00:00" fails split → 3 parts, can't unpack into h, m
    result = _parse_digest_times(["07:00:00"])
    assert result == []


def test_parse_times_rejects_24h():
    # hour=24 fails time() constructor (max 23)
    result = _parse_digest_times(["24:00"])
    assert result == []


def test_parse_times_rejects_whitespace_only():
    result = _parse_digest_times(["   "])
    assert result == []


def test_parse_times_empty_list():
    assert _parse_digest_times([]) == []


def test_digest_job_uses_adaptive_window_and_dynamic_size(tmp_path, monkeypatch):
    """Smoke: 15 fresh articles across 5 sources → 10 sent (per-source cap 2 binds before size cap)."""
    from datetime import datetime

    from app.config import update_config
    from app.models import get_conn, init_db, insert_article, update_article_summary
    from app.scheduler import setup_scheduler

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    db_path = str(tmp_path / "news.db")
    conn = get_conn(db_path)
    init_db(conn)

    now_iso = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for src in ["a", "b", "c", "d", "e"]:
        for i in range(3):
            aid = f"{src}{i}"
            insert_article(
                conn,
                {
                    "id": aid,
                    "source": src,
                    "title": f"t-{aid}",
                    "url": f"https://x/{aid}",
                    "published": "2026-06-08T06:00:00",
                    "fetched_at": now_iso,
                },
            )
            update_article_summary(conn, aid, "สรุป")
    conn.close()

    update_config(
        {
            "digest_size_base": 5,
            "digest_size_max": 10,
            "digest_max_per_source": 2,
            "digest_window_buffer_hours": 1.0,
            "digest_times": ["07:00", "12:00", "18:00"],
        },
    )

    sent = []
    monkeypatch.setattr(
        "app.scheduler.send_digest",
        lambda articles, cfg: sent.append(list(articles)) or ["line"],
    )

    sched = setup_scheduler(db_path)
    try:
        job = next(j for j in sched.get_jobs() if j.id.startswith("digest_"))
        job.func()  # invoke once

        assert len(sent) == 1
        assert len(sent[0]) == 10  # 5 sources × 2 per source = 10
    finally:
        if sched.running:
            sched.shutdown(wait=False)
