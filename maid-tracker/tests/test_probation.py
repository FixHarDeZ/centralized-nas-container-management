from datetime import date

from tests.conftest import add_emp, add_att


def _calc(monkeypatch):
    import importlib, calc
    importlib.reload(calc)
    return calc


def test_probation_day_boundary(db, monkeypatch):
    calc = _calc(monkeypatch)
    # not passed yet → every day is probation
    assert calc.is_probation_day(date(2026, 6, 25), None) is True
    # passed on 06-20: pre-pass = probation, on/after = monthly
    assert calc.is_probation_day(date(2026, 6, 19), date(2026, 6, 20)) is True
    assert calc.is_probation_day(date(2026, 6, 20), date(2026, 6, 20)) is False
    assert calc.is_probation_day(date(2026, 6, 21), date(2026, 6, 20)) is False


def test_probation_tally_counts_marked_work_only(db, monkeypatch):
    calc = _calc(monkeypatch)
    eid = add_emp(db, name="A", start_date="2026-06-01", monthly_salary=15000,
                  employment_status="probation", probation_daily_rate=400)
    add_att(db, eid, "2026-06-01", "work")
    add_att(db, eid, "2026-06-02", "work", half_day=1)
    add_att(db, eid, "2026-06-04", "leave")
    r = calc.compute_probation_tally(eid, date(2026, 6, 1), 400.0, up_to=date(2026, 6, 30))
    assert r["total_days"] == 1.5
    assert r["amount"] == 600.0


def test_probation_tally_stops_before_pass_date(db, monkeypatch):
    calc = _calc(monkeypatch)
    eid = add_emp(db, name="B", start_date="2026-06-01", monthly_salary=15000,
                  employment_status="probation", probation_daily_rate=400)
    add_att(db, eid, "2026-06-18", "work")
    add_att(db, eid, "2026-06-20", "work")
    r = calc.compute_probation_tally(eid, date(2026, 6, 1), 400.0, up_to=date(2026, 6, 19))
    assert r["total_days"] == 1.0
    assert r["amount"] == 400.0


def test_resign_uses_anchor_for_first_month_prorate(db, monkeypatch):
    calc = _calc(monkeypatch)
    eid = add_emp(db, name="C", start_date="2026-05-01", monthly_salary=15600,
                  employment_status="active", monthly_start_date="2026-06-20")
    anchor = date(2026, 6, 20)
    r = calc.compute_resign_summary(eid, anchor, date(2026, 6, 30), 15600.0, holiday_mode="sunday")
    assert r["daily_rate"] == 600.0
    assert r["base_salary"] == 5400.0
