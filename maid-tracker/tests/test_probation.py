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


def test_probation_tally_default_present_minus_absences(db, monkeypatch):
    calc = _calc(monkeypatch)
    eid = add_emp(db, name="A", start_date="2026-06-01", monthly_salary=15000,
                  employment_status="probation", probation_daily_rate=400)
    # Default: every day present. 10 days (06-01..06-10) = 10.0 minus absences.
    add_att(db, eid, "2026-06-04", "leave")            # full absence → -1.0
    add_att(db, eid, "2026-06-05", "leave", half_day=1)  # half absence → -0.5
    r = calc.compute_probation_tally(eid, date(2026, 6, 1), 400.0, up_to=date(2026, 6, 10))
    assert r["total_days"] == 8.5   # 10 - 1 - 0.5
    assert r["amount"] == 3400.0


def test_probation_tally_respects_up_to_bound(db, monkeypatch):
    calc = _calc(monkeypatch)
    eid = add_emp(db, name="B", start_date="2026-06-01", monthly_salary=15000,
                  employment_status="probation", probation_daily_rate=400)
    # up_to caps the window (e.g. day before pass date)
    r = calc.compute_probation_tally(eid, date(2026, 6, 1), 400.0, up_to=date(2026, 6, 5))
    assert r["total_days"] == 5.0   # 06-01..06-05 all present by default
    assert r["amount"] == 2000.0


def test_resign_uses_anchor_for_first_month_prorate(db, monkeypatch):
    calc = _calc(monkeypatch)
    eid = add_emp(db, name="C", start_date="2026-05-01", monthly_salary=15600,
                  employment_status="active", monthly_start_date="2026-06-20")
    anchor = date(2026, 6, 20)
    r = calc.compute_resign_summary(eid, anchor, date(2026, 6, 30), 15600.0, holiday_mode="sunday")
    assert r["daily_rate"] == 600.0
    assert r["base_salary"] == 5400.0


def test_resign_during_probation_unpaid_only(db, monkeypatch):
    calc = _calc(monkeypatch)
    eid = add_emp(db, name="D", start_date="2026-06-01", monthly_salary=15000,
                  employment_status="probation", probation_daily_rate=400)
    # Window 06-01..06-04 = 4 days present by default.
    add_att(db, eid, "2026-06-03", "leave")   # absent → not owed
    # 06-01 already paid → excluded from settlement
    db.execute("INSERT INTO daily_payments (employee_id, work_date, amount, paid_at) "
               "VALUES (?,?,?,?)", (eid, "2026-06-01", 400.0, "2026-06-01 18:00"))
    db.commit()
    r = calc.compute_probation_resign(eid, date(2026, 6, 1), date(2026, 6, 4), 400.0)
    # owed = 06-02 (1) + 06-04 (1) = 2.0  (06-01 paid, 06-03 absent)
    assert r["total_days"] == 2.0
    assert r["final_amount"] == 800.0
