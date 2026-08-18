"""Bank details (transfer payees) survive create, read and update."""

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


def _payload(**over):
    base = {
        "name": "นัน",
        "start_date": "2026-07-05",
        "monthly_salary": 12000,
        "payment_method": "transfer",
        "bank_name": "กสิกรไทย",
        "bank_account": "123-4-56789-0",
        "bank_account_name": "Nan Nan",
    }
    base.update(over)
    return base


def test_bank_details_roundtrip(client):
    emp_id = client.post("/api/employees", json=_payload()).json()["id"]
    emp = client.get(f"/api/employees/{emp_id}").json()
    assert emp["bank_name"] == "กสิกรไทย"
    assert emp["bank_account"] == "123-4-56789-0"
    assert emp["bank_account_name"] == "Nan Nan"

    client.put(f"/api/employees/{emp_id}", json=_payload(bank_name="ไทยพาณิชย์"))
    assert client.get(f"/api/employees/{emp_id}").json()["bank_name"] == "ไทยพาณิชย์"


def test_bank_details_optional_for_cash(client):
    emp_id = client.post(
        "/api/employees",
        json=_payload(
            payment_method="cash", bank_name=None, bank_account=None,
            bank_account_name=None,
        ),
    ).json()["id"]
    emp = client.get(f"/api/employees/{emp_id}").json()
    assert emp["bank_name"] is None and emp["bank_account"] is None
    assert emp["bank_account_name"] is None
