from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "log-medic.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitored_containers (
    name TEXT PRIMARY KEY,
    repo TEXT,
    subdir TEXT,
    maturity TEXT NOT NULL DEFAULT 'dev',
    notify_only INTEGER NOT NULL DEFAULT 0,
    paused INTEGER NOT NULL DEFAULT 0,
    regex_override TEXT,
    added_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    fingerprint TEXT NOT NULL,
    container TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    gate_reason TEXT,
    analysis TEXT,
    pr_url TEXT,
    PRIMARY KEY (fingerprint, container)
);

CREATE TABLE IF NOT EXISTS daily_quota (
    date TEXT PRIMARY KEY,
    analyzed_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS circuit_breaker (
    container TEXT PRIMARY KEY,
    tripped_at TEXT,
    last_new_fp_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    payload TEXT
);
"""


def get_conn(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def list_monitored_containers(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM monitored_containers").fetchall()


def get_monitored_container(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM monitored_containers WHERE name=?", (name,)
    ).fetchone()


def upsert_monitored_container(
    conn: sqlite3.Connection,
    name: str,
    repo: str | None,
    subdir: str | None,
    maturity: str,
    notify_only: int,
    paused: int,
    regex_override: str | None,
) -> None:
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO monitored_containers
        (name, repo, subdir, maturity, notify_only, paused, regex_override, added_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
        repo=excluded.repo, subdir=excluded.subdir, maturity=excluded.maturity,
        notify_only=excluded.notify_only, paused=excluded.paused,
        regex_override=excluded.regex_override, updated_at=excluded.updated_at
        """,
        (name, repo, subdir, maturity, notify_only, paused, regex_override, now, now),
    )
    conn.commit()


def delete_monitored_container(conn: sqlite3.Connection, name: str) -> None:
    conn.execute("DELETE FROM monitored_containers WHERE name=?", (name,))
    conn.commit()


def event_exists(conn: sqlite3.Connection, fingerprint: str, container: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM events WHERE fingerprint=? AND container=?",
            (fingerprint, container),
        ).fetchone()
        is not None
    )


def record_event(
    conn: sqlite3.Connection,
    fingerprint: str,
    container: str,
    status: str,
    gate_reason: str | None = None,
    now: str | None = None,
) -> None:
    """Insert-or-bump occurrence matched log line. Call exactly
    once per matched line; use update_event_status() later for status
    transitions on same occurrence (analyzed/pr_opened/etc.) so count
    isn't double-bumped."""
    now = now or _now_iso()
    if event_exists(conn, fingerprint, container):
        conn.execute(
            "UPDATE events SET last_seen=?, count=count+1 WHERE fingerprint=? AND container=?",
            (now, fingerprint, container),
        )
    else:
        conn.execute(
            """
            INSERT INTO events
            (fingerprint, container, first_seen, last_seen, count, status, gate_reason)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            """,
            (fingerprint, container, now, now, status, gate_reason),
        )
    conn.commit()


def update_event_status(
    conn: sqlite3.Connection,
    fingerprint: str,
    container: str,
    status: str,
    gate_reason: str | None = None,
    analysis: str | None = None,
    pr_url: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE events SET status=?,
        gate_reason=COALESCE(?, gate_reason),
        analysis=COALESCE(?, analysis),
        pr_url=COALESCE(?, pr_url)
        WHERE fingerprint=? AND container=?
        """,
        (status, gate_reason, analysis, pr_url, fingerprint, container),
    )
    conn.commit()


def get_recent_events(
    conn: sqlite3.Connection, limit: int = 50, container: str | None = None
) -> list[sqlite3.Row]:
    if container:
        return conn.execute(
            "SELECT * FROM events WHERE container=? ORDER BY last_seen DESC LIMIT ?",
            (container, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM events ORDER BY last_seen DESC LIMIT ?", (limit,)
    ).fetchall()


def get_today_quota(conn: sqlite3.Connection) -> int:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT analyzed_count FROM daily_quota WHERE date=?", (today,)
    ).fetchone()
    return row["analyzed_count"] if row else 0


def increment_quota(conn: sqlite3.Connection) -> None:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    conn.execute(
        """
        INSERT INTO daily_quota (date, analyzed_count) VALUES (?, 1)
        ON CONFLICT(date) DO UPDATE SET analyzed_count=analyzed_count+1
        """,
        (today,),
    )
    conn.commit()


def write_audit(conn: sqlite3.Connection, action: str, payload: str) -> None:
    conn.execute(
        "INSERT INTO audit_log (ts, action, payload) VALUES (?, ?, ?)",
        (_now_iso(), action, payload),
    )
    conn.commit()
