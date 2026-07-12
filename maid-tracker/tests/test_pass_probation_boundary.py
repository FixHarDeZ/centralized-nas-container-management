"""Pass mid-month → daily continues through month-end, monthly starts next-month-1st."""

import importlib
import tempfile
from datetime import date

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATA_DIR", tempfile.mkdtemp())
    import calc

    importlib.reload(calc)
    import main

    importlib.reload(main)
    from fastapi.testclient import TestClient

    return TestClient(main.app), main


def _mk_prob(client, start="2025-02-01"):
    c, _ = client
    r = c.post(
        "/api/employees",
        json={
            "name": "P",
            "start_date": start,
            "monthly_salary": 15400,
            "employment_status": "probation",
            "probation_daily_rate": 500,
            "holiday_mode": "sunday",
            "monthly_leave_days": 2,
        },
    )
    return r.json()["id"]


def test_pass_midmonth_sets_next_month_anchor_keeps_probation(client):
    c, _ = client
    eid = _mk_prob(client)
    # backdated pass on 2025-02-10 (mid-month, in the past)
    c.post(f"/api/employees/{eid}/pass-probation", json={"pass_date": "2025-02-10"})
    emp = c.get(f"/api/employees/{eid}").json()
    # anchor moved to 1st of March (next month)
    assert emp["monthly_start_date"] == "2025-03-01"
    # promotion already ran (2025-03-01 <= today) → active
    assert emp["employment_status"] == "active"
    # first_month_leave_days set to full monthly_leave_days
    assert emp["first_month_leave_days"] == 2


def test_pass_month_has_no_monthly_period(client):
    c, _ = client
    eid = _mk_prob(client)
    c.post(f"/api/employees/{eid}/pass-probation", json={"pass_date": "2025-02-10"})
    # February (the pass month) has NO monthly periods — pay was daily all month
    p = c.get(f"/api/employees/{eid}/payments?year=2025&month=2").json()
    assert p == []


def test_next_month_full_salary(client):
    c, _ = client
    eid = _mk_prob(client)
    c.post(f"/api/employees/{eid}/pass-probation", json={"pass_date": "2025-02-10"})
    # March = first full monthly month
    p = c.get(f"/api/employees/{eid}/payments?year=2025&month=3").json()
    assert [x["period"] for x in p] == [1, 2]
    assert p[0]["amount"] + p[1]["amount"] == 15400.0


def test_daily_payable_through_pass_month_end(client):
    c, _ = client
    eid = _mk_prob(client)
    c.post(f"/api/employees/{eid}/pass-probation", json={"pass_date": "2025-02-10"})
    # daily-payments window caps at < monthly_start_date (2025-03-01) → includes 2025-02-28
    dp = c.get(f"/api/employees/{eid}/daily-payments?year=2025&month=2").json()
    dates = {d["work_date"] for d in dp}
    assert "2025-02-28" in dates
    assert "2025-02-15" in dates


def test_pass_on_first_of_month_starts_monthly_immediately(client):
    c, _ = client
    eid = _mk_prob(client)
    c.post(f"/api/employees/{eid}/pass-probation", json={"pass_date": "2025-02-01"})
    emp = c.get(f"/api/employees/{eid}").json()
    assert emp["monthly_start_date"] == "2025-02-01"
    assert emp["employment_status"] == "active"
    p = c.get(f"/api/employees/{eid}/payments?year=2025&month=2").json()
    assert [x["period"] for x in p] == [1, 2]


def test_promote_pending_leaves_unpassed_in_probation(client):
    c, main = client
    _mk_prob(client)  # never passed → monthly_start_date NULL
    main._promote_pending()  # must not sweep NULL-anchor maids
    emp = c.get("/api/employees").json()[0]
    assert emp["employment_status"] == "probation"


def test_undo_pass_reverts(client):
    c, _ = client
    eid = _mk_prob(client)
    c.post(f"/api/employees/{eid}/pass-probation", json={"pass_date": "2025-02-10"})
    c.delete(f"/api/employees/{eid}/pass-probation")
    emp = c.get(f"/api/employees/{eid}").json()
    assert emp["employment_status"] == "probation"
    assert emp["monthly_start_date"] is None


def test_stays_probation_during_tail(client):
    """Core of option 2: pass THIS month → anchor is next-month-1st (future) →
    NOT promoted → status stays probation through the tail, pass-month pay is []."""
    import datetime as _dt

    c, _ = client
    today = _dt.date.today()
    start = today.replace(day=1)
    r = c.post(
        "/api/employees",
        json={
            "name": "T",
            "start_date": start.isoformat(),
            "monthly_salary": 15400,
            "employment_status": "probation",
            "probation_daily_rate": 500,
            "holiday_mode": "sunday",
            "monthly_leave_days": 2,
        },
    )
    eid = r.json()["id"]
    c.post(f"/api/employees/{eid}/pass-probation", json={"pass_date": today.isoformat()})
    emp = c.get(f"/api/employees/{eid}").json()
    assert emp["employment_status"] == "probation"  # NOT promoted — anchor future
    nxt = (start.replace(day=28) + _dt.timedelta(days=7)).replace(day=1)
    assert emp["monthly_start_date"] == nxt.isoformat()
    p = c.get(f"/api/employees/{eid}/payments?year={today.year}&month={today.month}").json()
    assert p == []


def test_pass_month_summary_stays_daily_after_promotion(client):
    c, _ = client
    eid = _mk_prob(client)  # start 2025-02-01, probation, daily rate 500
    c.post(f"/api/employees/{eid}/pass-probation", json={"pass_date": "2025-02-10"})
    # Now active (anchor 2025-03-01 <= today). Look BACK at Feb (the pass month).
    s = c.get(f"/api/employees/{eid}/summary?year=2025&month=2").json()
    assert s["employment_status"] == "probation"  # daily framing, not monthly
    assert s["daily_rate"] == 500.0
    assert s["base_salary"] != 15400.0            # NOT full monthly salary
    # March = first full monthly month → monthly framing
    s2 = c.get(f"/api/employees/{eid}/summary?year=2025&month=3").json()
    assert s2.get("employment_status") != "probation"
