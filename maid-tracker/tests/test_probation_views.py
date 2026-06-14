"""Endpoint-level tests for probation summary/overall semantics (TestClient)."""
import os
import tempfile
import importlib
from datetime import date

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATA_DIR", tempfile.mkdtemp())
    import calc
    importlib.reload(calc)          # rebind calc.DB_PATH to this test's DATA_DIR
    import main
    importlib.reload(main)          # rebind main's DB_PATH + re-import calc fns
    from fastapi.testclient import TestClient
    return TestClient(main.app)


def _mk_probation(client):
    r = client.post("/api/employees", json={
        "name": "P", "start_date": "2026-06-01", "monthly_salary": 15600,
        "employment_status": "probation", "probation_daily_rate": 500,
        "payment_method": "cash", "holiday_mode": "sunday"})
    return r.json()["id"]


def test_probation_summary_no_holiday_no_monthly(client):
    eid = _mk_probation(client)
    # mark 2 weekday work + 1 Sunday work (2026-06-07 is Sunday)
    for d in ["2026-06-02", "2026-06-03", "2026-06-07"]:
        client.post(f"/api/employees/{eid}/attendance", json={"work_date": d, "status": "work"})
    s = client.get(f"/api/employees/{eid}/summary?year=2026&month=6").json()
    assert s["employment_status"] == "probation"
    # only MARKED work days count (no default-fill of unmarked weekdays)
    assert s["work_days"] == 3.0, s
    # no holiday/leave granted during probation
    assert s["holiday_days"] == 0
    assert s["leave_days"] == 0
    # daily pay, not monthly salary
    assert s["daily_rate"] == 500.0
    assert s["base_salary"] == 1500.0   # 3 × 500
    assert s["actual_pay"] == 1500.0


def test_probation_overall_no_holiday(client):
    eid = _mk_probation(client)
    for d in ["2026-06-02", "2026-06-03"]:
        client.post(f"/api/employees/{eid}/attendance", json={"work_date": d, "status": "work"})
    o = client.get(f"/api/employees/{eid}/overall").json()
    assert o["employment_status"] == "probation"
    assert o["total_work_days"] == 2.0
    assert o["total_holiday_days"] == 0
    assert o["total_leave_days"] == 0
    assert o["daily_rate"] == 500.0
    assert o["total_earned"] == 1000.0


def test_probation_payslip_daily(client):
    eid = _mk_probation(client)
    client.post(f"/api/employees/{eid}/attendance", json={"work_date": "2026-06-02", "status": "work"})
    r = client.get(f"/api/employees/{eid}/payslip/2026/6")
    assert r.status_code == 200
    body = r.content.decode("utf-8-sig")
    # daily payslip must not advertise a full monthly salary figure as the pay
    assert "500" in body          # daily rate present
    assert "15,600" not in body and "15600.00" not in body
