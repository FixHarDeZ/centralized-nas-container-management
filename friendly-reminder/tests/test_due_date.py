"""Tests for the effective due-date clamp used by the daily reminders."""
from datetime import date

from app.main import _effective_due


def test_normal_day():
    assert _effective_due(2026, 6, 25) == date(2026, 6, 25)


def test_clamp_31_to_30_day_month():
    # April has 30 days
    assert _effective_due(2026, 4, 31) == date(2026, 4, 30)


def test_clamp_31_to_february_non_leap():
    assert _effective_due(2026, 2, 31) == date(2026, 2, 28)


def test_clamp_31_to_february_leap():
    assert _effective_due(2024, 2, 31) == date(2024, 2, 29)


def test_day_1():
    assert _effective_due(2026, 12, 1) == date(2026, 12, 1)
