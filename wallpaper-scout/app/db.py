import json
import os
import sqlite3
from contextlib import contextmanager

DB_PATH = os.path.join(os.environ.get("DATA_DIR", "/data"), "wallpaper-scout.db")


def init_db() -> None:
    """Initialize database schema."""
    with _conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            query TEXT NOT NULL,
            purposes TEXT NOT NULL,
            frequency_per_day INTEGER NOT NULL,
            max_new_per_cycle INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            backfilled INTEGER NOT NULL DEFAULT 0,
            search_terms TEXT
        );

        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
            purpose TEXT NOT NULL,
            wallhaven_id TEXT NOT NULL,
            filename TEXT NOT NULL,
            downloaded_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            UNIQUE(topic_id, purpose, wallhaven_id)
        );
        """)


@contextmanager
def _conn():
    """Context manager for database connection."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_conn():
    """FastAPI dependency — yields request."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_topic(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["purposes"] = json.loads(d["purposes"])
    d["search_terms"] = json.loads(d["search_terms"]) if d["search_terms"] else None
    return d


def create_topic(
    query: str,
    purposes: list[str],
    frequency_per_day: int,
    max_new_per_cycle: int,
) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO topics (query, purposes, frequency_per_day, max_new_per_cycle) VALUES (?, ?, ?, ?)",
            (query, json.dumps(purposes), frequency_per_day, max_new_per_cycle),
        )
        return cur.lastrowid


def get_topic(topic_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
        return _row_to_topic(row) if row else None


def list_topics() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM topics").fetchall()
        return [_row_to_topic(row) for row in rows]


def update_topic(topic_id: int, **fields) -> None:
    allowed_fields = {"query", "purposes", "frequency_per_day", "max_new_per_cycle", "enabled"}
    fields = {k: v for k, v in fields.items() if k in allowed_fields}
    if not fields:
        return
    if "purposes" in fields:
        fields["purposes"] = json.dumps(fields["purposes"])

    with _conn() as conn:
        set_clause = ", ".join(f"{k} = ?" for k in fields.keys())
        values = list(fields.values()) + [topic_id]
        conn.execute(f"UPDATE topics SET {set_clause} WHERE id = ?", values)


def delete_topic(topic_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))


def set_search_terms(topic_id: int, terms: list[str]) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE topics SET search_terms = ? WHERE id = ?",
            (json.dumps(terms), topic_id),
        )


def mark_backfilled(topic_id: int) -> None:
    with _conn() as conn:
        conn.execute("UPDATE topics SET backfilled = 1 WHERE id = ?", (topic_id,))


def download_exists(topic_id: int, purpose: str, wallhaven_id: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM downloads WHERE topic_id = ? AND purpose = ? AND wallhaven_id = ?",
            (topic_id, purpose, wallhaven_id),
        ).fetchone()
        return row is not None


def record_download(topic_id: int, purpose: str, wallhaven_id: str, filename: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO downloads (topic_id, purpose, wallhaven_id, filename) VALUES (?, ?, ?, ?)",
            (topic_id, purpose, wallhaven_id, filename),
        )


def daily_download_counts(day: str) -> dict[str, int]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT t.query as query, COUNT(*) as n FROM downloads d
            JOIN topics t ON t.id = d.topic_id
            WHERE date(d.downloaded_at) = ?
            GROUP BY t.query
            """,
            (day,),
        ).fetchall()
        return {r["query"]: r["n"] for r in rows}
