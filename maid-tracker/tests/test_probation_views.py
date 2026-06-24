"""Endpoint-level tests for probation summary/overall semantics (TestClient)."""

import importlib
import tempfile

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATA_DIR", tempfile.mkdtemp())
    import calc

    importlib.reload(calc)  # rebind calc.DB_PATH to this test's DATA_DIR
    import main

    importlib.reload(main)  # rebind main's DB_PATH + re-import calc fns
    from fastapi.testclient import TestClient

    return TestClient(main.app)


def _mk_probation(client, start="2025-02-01"):
    # Use a fully-past month so get_summary's clamp-to-today doesn't truncate.
    r = client.post(
        "/api/employees",
        json={
            "name": "P",
            "start_date": start,
            "monthly_salary": 15600,
            "employment_status": "probation",
            "probation_daily_rate": 500,
            "payment_method": "cash",
            "holiday_mode": "sunday",
        },
    )
    return r.json()["id"]


def test_probation_summary_no_holiday_no_monthly(client):
    eid = _mk_probation(client)  # start 2025-02-01, Feb 2025 = 28 days
    # Default model: every day present. Mark absences to reduce.
    client.post(
        f"/api/employees/{eid}/attendance",
        json={"work_date": "2025-02-05", "status": "leave"},
    )  # -1.0
    client.post(
        f"/api/employees/{eid}/attendance",
        json={"work_date": "2025-02-06", "status": "leave", "half_day": True},
    )  # -0.5
    s = client.get(f"/api/employees/{eid}/summary?year=2025&month=2").json()
    assert s["employment_status"] == "probation"
    assert s["work_days"] == 26.5, s  # 28 - 1 - 0.5
    # no holiday/leave granted during probation
    assert s["holiday_days"] == 0
    # daily pay, not monthly salary
    assert s["daily_rate"] == 500.0
    assert s["base_salary"] == 13250.0  # 26.5 × 500
    assert s["actual_pay"] == 13250.0


def test_probation_overall_no_holiday(client):
    eid = _mk_probation(client)
    o = client.get(f"/api/employees/{eid}/overall").json()
    assert o["employment_status"] == "probation"
    assert o["total_holiday_days"] == 0
    assert o["total_leave_days"] == 0
    assert o["daily_rate"] == 500.0
    # internal consistency (count itself is date-dependent → don't hardcode)
    assert o["total_earned"] == round(o["total_work_days"] * 500.0, 2)


def test_probation_payslip_daily(client):
    eid = _mk_probation(client)
    r = client.get(f"/api/employees/{eid}/payslip/2025/2")
    assert r.status_code == 200
    body = r.content.decode("utf-8-sig")
    # daily payslip must not advertise a full monthly salary figure as the pay
    assert "500" in body  # daily rate present
    assert "15,600" not in body and "15600.00" not in body
