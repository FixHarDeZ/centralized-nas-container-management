"""payment_schedule: 'monthly' → single full period 2; 'biweekly' → two periods."""

import importlib
import tempfile

import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("DATA_DIR", tempfile.mkdtemp())
    import calc

    importlib.reload(calc)
    import main

    importlib.reload(main)
    from fastapi.testclient import TestClient

    return TestClient(main.app)


def _mk(client, schedule):
    r = client.post(
        "/api/employees",
        json={
            "name": "S",
            "start_date": "2025-02-01",  # fully-past full month, Feb 2025 = 28 days
            "monthly_salary": 15400,
            "holiday_mode": "sunday",
            "payment_schedule": schedule,
        },
    )
    return r.json()["id"]


def test_biweekly_two_periods(client):
    eid = _mk(client, "biweekly")
    p = client.get(f"/api/employees/{eid}/payments?year=2025&month=2").json()
    assert [x["period"] for x in p] == [1, 2]
    assert p[0]["amount"] == 7700.0  # half
    assert p[1]["amount"] == 7700.0  # base - half


def test_monthly_single_full_period(client):
    eid = _mk(client, "monthly")
    p = client.get(f"/api/employees/{eid}/payments?year=2025&month=2").json()
    assert [x["period"] for x in p] == [2]
    assert p[0]["amount"] == 15400.0  # full base salary, one lump


def test_schedule_defaults_biweekly(client):
    r = client.post(
        "/api/employees",
        json={"name": "D", "start_date": "2025-02-01", "monthly_salary": 15400},
    )
    eid = r.json()["id"]
    got = client.get(f"/api/employees/{eid}").json()
    assert got["payment_schedule"] == "biweekly"
