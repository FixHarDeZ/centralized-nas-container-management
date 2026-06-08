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
