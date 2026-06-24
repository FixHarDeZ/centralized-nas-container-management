"""Endpoint tests for payer (paid_by) + 'other' document upload (TestClient)."""

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


def _mk_active(client, start="2025-02-01"):
    r = client.post(
        "/api/employees",
        json={
            "name": "A",
            "start_date": start,
            "monthly_salary": 15600,
            "payment_method": "cash",
            "holiday_mode": "sunday",
        },
    )
    return r.json()["id"]


def test_payment_paid_by_roundtrip(client):
    eid = _mk_active(client)
    # mark period 2 paid by a specific payer
    r = client.post(
        f"/api/employees/{eid}/payments/2/toggle?year=2025&month=2&paid_by=%E0%B8%9F%E0%B8%B4%E0%B8%81",
    )
    assert r.status_code == 200 and r.json()["paid"] is True
    pays = client.get(f"/api/employees/{eid}/payments?year=2025&month=2").json()
    p2 = next(p for p in pays if p["period"] == 2)
    assert p2["paid_by"] == "ฟิก"
    # unmark clears the payer
    client.post(f"/api/employees/{eid}/payments/2/toggle?year=2025&month=2")
    pays = client.get(f"/api/employees/{eid}/payments?year=2025&month=2").json()
    p2 = next(p for p in pays if p["period"] == 2)
    assert not p2["paid"] and p2["paid_by"] is None


def test_other_document_with_label(client):
    eid = _mk_active(client)
    img = ("c.png", b"\x89PNG\r\n\x1a\n" + b"0" * 32, "image/png")
    r = client.post(
        f"/api/employees/{eid}/documents",
        data={"doc_type": "other", "doc_label": "สัญญาจ้าง"},
        files={"files": img},
    )
    assert r.status_code == 200, r.text
    docs = client.get(f"/api/employees/{eid}/documents").json()
    assert len(docs) == 1
    assert docs[0]["doc_type"] == "other"
    assert docs[0]["doc_label"] == "สัญญาจ้าง"


def test_invalid_doc_type_rejected(client):
    eid = _mk_active(client)
    img = ("c.png", b"\x89PNG\r\n\x1a\n", "image/png")
    r = client.post(
        f"/api/employees/{eid}/documents",
        data={"doc_type": "../evil"},
        files={"files": img},
    )
    assert r.status_code == 400
