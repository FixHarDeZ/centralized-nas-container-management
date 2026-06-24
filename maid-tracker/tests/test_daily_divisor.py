"""Daily-rate divisor = ALL calendar days (holidays paid too).

Locks the invariant: dr = salary / calendar_days, and a full month still
pays exactly the monthly salary (catches any proration loop left counting
Mon–Sat only).
"""

import importlib
from datetime import date

import calc

from tests.conftest import add_emp


def test_divisor_counts_all_calendar_days():
    # Feb 2025 = 28 days (no Sunday exclusion)
    assert calc.working_days_in_month(2025, 2) == 28
    # Mar 2025 = 31 days
    assert calc.working_days_in_month(2025, 3) == 31


def test_daily_rate_includes_holidays():
    # 28000 / 28 calendar days = 1000 (was ~1166 under Mon–Sat)
    assert calc.daily_rate(28000, 2025, 2) == 1000.0


def test_full_month_pays_full_salary(db):
    importlib.reload(calc)  # rebind calc.DB_PATH to this test's DATA_DIR
    # Worked the whole of Feb 2025, no leave → base salary == monthly salary.
    eid = add_emp(
        db,
        name="A",
        start_date="2025-02-01",
        monthly_salary=28000,
        holiday_mode="sunday",
    )
    r = calc.compute_resign_summary(
        eid,
        date(2025, 2, 1),
        date(2025, 2, 28),
        28000,
        holiday_mode="sunday",
    )
    assert r["daily_rate"] == 1000.0
    assert r["base_salary"] == 28000.0  # 1000 × 28 (Sundays included)


def test_partial_month_prorates_over_calendar_days(db):
    importlib.reload(calc)
    # Start 2025-02-15 → 14 calendar days (15..28) paid, incl 2 Sundays.
    eid = add_emp(
        db,
        name="B",
        start_date="2025-02-15",
        monthly_salary=28000,
        holiday_mode="sunday",
    )
    r = calc.compute_resign_summary(
        eid,
        date(2025, 2, 15),
        date(2025, 2, 28),
        28000,
        holiday_mode="sunday",
    )
    assert r["base_salary"] == 14000.0  # 1000 × 14 calendar days
