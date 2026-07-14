"""pay-all daily payments + pass-probation congratulation notify + schedule-aware period amount."""

import importlib
import tempfile
from datetime import date, timedelta

import pytest


@pytest.fixture
def app_env(monkeypatch):
    monkeypatch.setenv("DATA_DIR", tempfile.mkdtemp())
    import calc

    importlib.reload(calc)
    import main

    importlib.reload(main)
    from fastapi.testclient import TestClient

    return TestClient(main.app), main


def _mk_probation(client, days_ago=5, rate=400.0):
    start = (date.today() - timedelta(days=days_ago)).isoformat()
    r = client.post(
        "/api/employees",
        json={
            "name": "P",
            "start_date": start,
            "monthly_salary": 12000,
            "employment_status": "probation",
            "probation_daily_rate": rate,
        },
    )
    return r.json()["id"], start


def test_pay_all_pays_every_outstanding_day(app_env):
    client, _ = app_env
    eid, start = _mk_probation(client, days_ago=5, rate=400.0)  # 6 present days

    # One absent day (excluded) + one day already paid (untouched)
    absent = (date.today() - timedelta(days=3)).isoformat()
    client.post(f"/api/employees/{eid}/attendance", json={"work_date": absent, "status": "leave"})
    client.post(f"/api/employees/{eid}/daily-payments/{start}/toggle?paid_by=ฟิก")

    r = client.post(f"/api/employees/{eid}/daily-payments/pay-all?paid_by=ปุ๊ก")
    assert r.status_code == 200
    body = r.json()
    assert body["paid_days"] == 4.0  # 6 days − 1 absent − 1 already paid
    assert body["total"] == 1600.0

    # Everything now paid; second call is a no-op
    dp = client.get(
        f"/api/employees/{eid}/daily-payments?year={date.today().year}&month={date.today().month}"
    ).json()
    assert all(d["paid"] for d in dp)
    r2 = client.post(f"/api/employees/{eid}/daily-payments/pay-all")
    assert r2.json() == {"paid_days": 0.0, "total": 0.0}


def test_pay_all_rejects_plain_active_employee(app_env):
    client, _ = app_env
    r = client.post(
        "/api/employees",
        json={"name": "A", "start_date": "2025-01-01", "monthly_salary": 12000},
    )
    eid = r.json()["id"]
    assert client.post(f"/api/employees/{eid}/daily-payments/pay-all").status_code == 400


def test_pass_probation_sends_congrats_notify(app_env, monkeypatch):
    client, main = app_env
    eid, _ = _mk_probation(client, days_ago=40)

    calls = {}

    def fake_notify(**kw):
        calls.update(kw)

    monkeypatch.setattr(main.line_notify, "notify_pass_probation", fake_notify)
    pass_date = date.today().replace(day=15).isoformat()
    r = client.post(f"/api/employees/{eid}/pass-probation", json={"pass_date": pass_date})
    assert r.status_code == 200
    anchor = r.json()["monthly_start_date"]
    assert calls["emp_name"] == "P"
    assert calls["pass_date"] == pass_date
    assert calls["monthly_start_date"].isoformat() == anchor
    assert calls["monthly_salary"] == 12000


def test_period_amount_respects_monthly_schedule(app_env):
    """Bug fix: toggle/webhook amount for payment_schedule='monthly' = full salary."""
    _, main = app_env
    emp = {
        "id": 1,
        "start_date": "2025-01-01",
        "monthly_start_date": None,
        "monthly_salary": 15400,
        "payment_schedule": "monthly",
        "max_leave_carry": None,
    }
    amount, ded_days, ded_amount = main._compute_period_amount(emp, 2025, 2, 2)
    assert amount == 15400.0
    assert (ded_days, ded_amount) == (0.0, 0.0)
    emp["payment_schedule"] = "biweekly"
    amount, _, _ = main._compute_period_amount(emp, 2025, 2, 2)
    assert amount == 7700.0


def test_i18n_pass_probation_block():
    import i18n

    assert i18n.pass_probation_block(
        "th", name="x", pass_date="2026-07-15", start="01/08/2026", salary="12,000",
        schedule="biweekly", holiday_mode="sunday", leave_days="0",
    ) is None
    block = i18n.pass_probation_block(
        "my", name="Aye", pass_date="2026-07-15", start="01/08/2026", salary="12,000",
        schedule="monthly", holiday_mode="monthly", leave_days="2",
        daily_until_start=True,
    )
    assert "Aye" in block and "12,000" in block and "2" in block
    assert i18n._PASS_PROBATION["my"]["tail_daily"] in block


def test_i18n_daily_pay_all_all_langs():
    import i18n

    for lang in ("my", "en", "lo", "km"):
        block = i18n.translate_block(
            "daily_pay_all", lang, name="P", days="4", amount="1,600", paid_by="ฟิก",
        )
        assert "P" in block and "1,600" in block
