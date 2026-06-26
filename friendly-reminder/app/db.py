"""SQLite database setup and helpers for friendly-reminder."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("DATA_DIR", "/data")) / "friendly-reminder.db"
SLIPS_DIR = Path(os.environ.get("DATA_DIR", "/data")) / "slips"


def init_db() -> None:
    SLIPS_DIR.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS installments (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                name             TEXT    NOT NULL,
                total_price      REAL    NOT NULL,
                num_installments INTEGER NOT NULL,
                start_date       TEXT    NOT NULL,
                note             TEXT,
                created_at       TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS payments (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                installment_id      INTEGER NOT NULL REFERENCES installments(id) ON DELETE CASCADE,
                installment_number  INTEGER NOT NULL,
                due_year            INTEGER NOT NULL,
                due_month           INTEGER NOT NULL,
                amount              REAL    NOT NULL,
                paid_at             TEXT,
                note                TEXT,
                slip_filename       TEXT,
                UNIQUE(installment_id, installment_number)
            );
        """)
        # Migration: add slip_filename for existing databases that pre-date this column
        try:
            conn.execute("ALTER TABLE payments ADD COLUMN slip_filename TEXT")
        except Exception:
            pass


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_conn():
    """FastAPI dependency — yields a connection per request."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
