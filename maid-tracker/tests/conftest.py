import os
import sqlite3
import tempfile

import pytest


@pytest.fixture
def db(monkeypatch):
    """Temp SQLite DB with the maid schema; sets DATA_DIR so calc.py picks it up."""
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmp)
    db_path = os.path.join(tmp, "maid_tracker.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, start_date TEXT, monthly_salary REAL,
            max_leave_carry REAL, holiday_mode TEXT DEFAULT 'sunday',
            monthly_leave_days REAL DEFAULT 0,
            employment_status TEXT DEFAULT 'active',
            probation_daily_rate REAL, monthly_start_date TEXT,
            payment_method TEXT DEFAULT 'cash', end_date TEXT
        );
        CREATE TABLE attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER, work_date TEXT, status TEXT,
            note TEXT, half_day INTEGER DEFAULT 0,
            UNIQUE(employee_id, work_date)
        );
        CREATE TABLE daily_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER, work_date TEXT, amount REAL,
            paid_at TEXT, slip_path TEXT,
            UNIQUE(employee_id, work_date)
        );
        """,
    )
    conn.commit()
    yield conn
    conn.close()


def add_emp(conn, **kw):
    cols = ", ".join(kw.keys())
    qs = ", ".join("?" for _ in kw)
    cur = conn.execute(
        f"INSERT INTO employees ({cols}) VALUES ({qs})",
        tuple(kw.values()),
    )
    conn.commit()
    return cur.lastrowid


def add_att(conn, emp_id, work_date, status, half_day=0):
    conn.execute(
        "INSERT INTO attendance (employee_id, work_date, status, half_day) VALUES (?,?,?,?)",
        (emp_id, work_date, status, half_day),
    )
    conn.commit()
