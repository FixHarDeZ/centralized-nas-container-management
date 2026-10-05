"""Actual money paid to an employee, including discretionary payments."""

import importlib
import sqlite3
import tempfile

import pytest


@pytest.fixture
def client(monkeypatch):
    data_dir = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", data_dir)
    import calc
    import main

    importlib.reload(calc)
    importlib.reload(main)
    from fastapi.testclient import TestClient

    return TestClient(main.app), main


def employee(client):
    response = client.post("/api/employees", json={
        "name": "May", "start_date": "2025-01-01", "monthly_salary": 30000,
        "payment_schedule": "monthly",
    })
    assert response.status_code == 201
    return response.json()["id"]


def test_special_payment_create_edit_delete_and_validation(client):
    http, _ = client
    eid = employee(http)
    path = f"/api/employees/{eid}/special-payments"
    payload = {"paid_on": "2025-02-03", "amount": 2500, "reason": "  โบนัสปีใหม่  ", "paid_by": "ฟิก"}
    created = http.post(path, json=payload)
    assert created.status_code == 201, created.text
    sid = created.json()["id"]
    rows = http.get(path).json()
    assert len(rows) == 1
    assert rows[0]["reason"] == "โบนัสปีใหม่"
    assert rows[0]["amount"] == 2500
    assert rows[0]["paid_by"] == "ฟิก"

    changed = http.put(f"{path}/{sid}", json={**payload, "amount": 3000, "reason": "เงินปีใหม่"})
    assert changed.status_code == 200
    assert http.get(path).json()[0]["amount"] == 3000
    for bad in ({**payload, "amount": 0}, {**payload, "amount": -1},
                {**payload, "amount": "NaN"}, {**payload, "paid_on": "2025-02-30"},
                {**payload, "reason": "  "}):
        assert http.post(path, json=bad).status_code == 400
    assert http.post("/api/employees/99999/special-payments", json=payload).status_code == 404
    assert http.delete(f"{path}/{sid}").status_code == 200
    assert http.get(path).json() == []


def test_history_groups_by_salary_month_and_actual_special_date(client):
    http, main = client
    eid = employee(http)
    assert http.post(
        f"/api/employees/{eid}/payments/2/toggle?year=2025&month=1&paid_by=ฟิก"
    ).status_code == 200
    assert http.post(f"/api/employees/{eid}/special-payments", json={
        "paid_on": "2025-02-02", "amount": 1200, "reason": "โบนัส", "paid_by": "ปุ๊ก"
    }).status_code == 201
    # A historical daily payment remains in the ledger after probation ends.
    with sqlite3.connect(main.DB_PATH) as conn:
        conn.execute(
            "INSERT INTO daily_payments (employee_id, work_date, amount, paid_at) VALUES (?,?,?,?)",
            (eid, "2025-01-02", 600, "2025-01-02 18:00"),
        )
    history = http.get(f"/api/employees/{eid}/payment-history")
    assert history.status_code == 200, history.text
    body = history.json()
    assert body["totals"] == {"salary": 30000, "daily": 600, "special": 1200, "all": 31800}
    jan = next(m for m in body["months"] if m["year"] == 2025 and m["month"] == 1)
    feb = next(m for m in body["months"] if m["year"] == 2025 and m["month"] == 2)
    assert jan["total"] == 30600
    assert feb["total"] == 1200
    salary = next(x for x in jan["items"] if x["type"] == "salary")
    assert salary["period"] == 2
    assert salary["paid_at"]
    assert salary["amount"] == 30000
    assert feb["items"][0]["reason"] == "โบนัส"


def test_paid_salary_snapshot_survives_salary_change_and_unmark(client):
    http, main = client
    eid = employee(http)
    url = f"/api/employees/{eid}/payments/2/toggle?year=2025&month=1"
    http.post(url)
    with sqlite3.connect(main.DB_PATH) as conn:
        assert conn.execute("SELECT amount FROM salary_payments WHERE employee_id=?", (eid,)).fetchone()[0] == 30000
        conn.execute("UPDATE employees SET monthly_salary=40000 WHERE id=?", (eid,))
    assert http.get(f"/api/employees/{eid}/payment-history").json()["totals"]["salary"] == 30000
    http.post(url)
    assert http.get(f"/api/employees/{eid}/payment-history").json()["totals"]["salary"] == 0


def test_legacy_paid_salary_without_snapshot_is_labelled_estimate(client):
    http, main = client
    eid = employee(http)
    http.post(f"/api/employees/{eid}/payments/2/toggle?year=2025&month=1")
    with sqlite3.connect(main.DB_PATH) as conn:
        conn.execute("UPDATE salary_payments SET amount=NULL WHERE employee_id=?", (eid,))
    history = http.get(f"/api/employees/{eid}/payment-history").json()
    assert history["totals"]["salary"] == 30000
    assert history["months"][0]["items"][0]["estimated"] is True


def test_existing_database_migrates_without_losing_paid_salary(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    path = tmp_path / "maid_tracker.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE employees (
                id INTEGER PRIMARY KEY, name TEXT NOT NULL, age INTEGER,
                nationality TEXT, phone TEXT, line_id TEXT, facebook TEXT,
                start_date TEXT NOT NULL, monthly_salary REAL NOT NULL,
                created_at TEXT
            );
            CREATE TABLE salary_payments (
                id INTEGER PRIMARY KEY, employee_id INTEGER, year INTEGER,
                month INTEGER, period INTEGER, paid_at TEXT,
                UNIQUE(employee_id, year, month, period)
            );
            INSERT INTO employees (id, name, start_date, monthly_salary)
                VALUES (1, 'Legacy', '2025-01-01', 30000);
            INSERT INTO salary_payments (employee_id, year, month, period, paid_at)
                VALUES (1, 2025, 1, 2, '2025-01-31 17:00');
        """)
    import calc
    import main

    importlib.reload(calc)
    importlib.reload(main)
    from fastapi.testclient import TestClient

    history = TestClient(main.app).get("/api/employees/1/payment-history")
    assert history.status_code == 200, history.text
    assert history.json()["totals"]["salary"] == 15000
    assert history.json()["months"][0]["items"][0]["estimated"] is True
