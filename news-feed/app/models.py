import json
import sqlite3
from datetime import datetime
from typing import Optional


def get_conn(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
            id          TEXT PRIMARY KEY,
            source      TEXT NOT NULL,
            title       TEXT NOT NULL,
            url         TEXT NOT NULL UNIQUE,
            published   TEXT NOT NULL,
            summary_th  TEXT,
            fetched_at  TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS prices (
            model_id        TEXT PRIMARY KEY,
            provider        TEXT,
            name            TEXT,
            prompt_price    REAL,
            complete_price  REAL,
            context_length  INTEGER,
            updated_at      TEXT
        );
        CREATE TABLE IF NOT EXISTS digest_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sent_at     TEXT NOT NULL,
            article_ids TEXT NOT NULL,
            channels    TEXT NOT NULL
        );
    """)
    conn.commit()
    # Migration: add free_expires_at column if not present (manually set, NOT from OpenRouter)
    try:
        conn.execute("ALTER TABLE prices ADD COLUMN free_expires_at TEXT")
        conn.commit()
    except sqlite3.OperationalError as e:
        if "duplicate column" not in str(e):
            raise


def article_exists(conn: sqlite3.Connection, article_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM articles WHERE id = ?", (article_id,)).fetchone()
    return row is not None


def insert_article(conn: sqlite3.Connection, article: dict) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO articles (id, source, title, url, published, fetched_at) VALUES (?,?,?,?,?,?)",
        (article["id"], article["source"], article["title"], article["url"],
         article["published"], article["fetched_at"]),
    )
    conn.commit()


def update_article_summary(conn: sqlite3.Connection, article_id: str, summary_th: str) -> None:
    conn.execute("UPDATE articles SET summary_th = ? WHERE id = ?", (summary_th, article_id))
    conn.commit()


def get_articles(conn: sqlite3.Connection, source: Optional[str] = None,
                 date: Optional[str] = None, limit: int = 20) -> list[dict]:
    query = "SELECT * FROM articles WHERE 1=1"
    params: list = []
    if source:
        query += " AND source = ?"
        params.append(source)
    if date:
        query += " AND published >= ?"
        params.append(date)
    query += " ORDER BY published DESC LIMIT ?"
    params.append(limit)
    return [dict(row) for row in conn.execute(query, params).fetchall()]


def get_article(conn: sqlite3.Connection, article_id: str) -> Optional[dict]:
    row = conn.execute("SELECT * FROM articles WHERE id = ?", (article_id,)).fetchone()
    return dict(row) if row else None


def get_recent_articles_for_digest(conn: sqlite3.Connection, hours: int = 6, limit: int = 5) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM articles WHERE summary_th IS NOT NULL "
        "AND fetched_at >= datetime('now', ?) "
        "ORDER BY published DESC LIMIT ?",
        (f"-{hours} hours", limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_article_count(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]


def get_last_fetch_time(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT MAX(fetched_at) FROM articles").fetchone()
    return row[0]  # MAX() returns None on empty table


def get_source_counts(conn: sqlite3.Connection, hours: int = 24) -> list[dict]:
    rows = conn.execute(
        "SELECT source, COUNT(*) as count FROM articles "
        "WHERE fetched_at >= datetime('now', ?) GROUP BY source",
        (f"-{hours} hours",),
    ).fetchall()
    return [dict(r) for r in rows]


def upsert_price(conn: sqlite3.Connection, model: dict) -> None:
    conn.execute(
        "INSERT INTO prices (model_id, provider, name, prompt_price, complete_price, context_length, updated_at) "
        "VALUES (?,?,?,?,?,?,?) ON CONFLICT(model_id) DO UPDATE SET "
        "provider=excluded.provider, name=excluded.name, prompt_price=excluded.prompt_price, "
        "complete_price=excluded.complete_price, context_length=excluded.context_length, updated_at=excluded.updated_at",
        (model["model_id"], model["provider"], model["name"], model["prompt_price"],
         model["complete_price"], model.get("context_length"), model["updated_at"]),
    )
    conn.commit()


def set_free_expiry(conn: sqlite3.Connection, model_id: str, expires_at: Optional[str]) -> bool:
    if expires_at is not None:
        try:
            datetime.strptime(expires_at, "%Y-%m-%d")
        except ValueError:
            raise ValueError("Invalid date format, use YYYY-MM-DD")
    cur = conn.execute(
        "UPDATE prices SET free_expires_at = ? WHERE model_id = ?",
        (expires_at, model_id),
    )
    conn.commit()
    return cur.rowcount > 0


def get_price_updated_at(conn: sqlite3.Connection) -> Optional[str]:
    row = conn.execute("SELECT MAX(updated_at) FROM prices").fetchone()
    return row[0]


def get_prices(conn: sqlite3.Connection, provider: Optional[str] = None,
               sort: str = "combined_asc") -> list[dict]:
    sort_map = {
        "prompt_asc": "prompt_price ASC",
        "prompt_desc": "prompt_price DESC",
        "complete_asc": "complete_price ASC",
        "combined_asc": "(prompt_price + complete_price) ASC",
    }
    order = sort_map.get(sort, sort_map["combined_asc"])
    query = "SELECT * FROM prices WHERE 1=1"
    params: list = []
    if provider:
        query += " AND provider = ?"
        params.append(provider)
    query += f" ORDER BY {order}"
    return [dict(r) for r in conn.execute(query, params).fetchall()]


def insert_digest_log(conn: sqlite3.Connection, sent_at: str,
                      article_ids: list[str], channels: str) -> int:
    cur = conn.execute(
        "INSERT INTO digest_log (sent_at, article_ids, channels) VALUES (?,?,?)",
        (sent_at, json.dumps(article_ids), channels),
    )
    conn.commit()
    return cur.lastrowid


def get_digest_history(conn: sqlite3.Connection, limit: int = 30) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM digest_log ORDER BY sent_at DESC LIMIT ?", (limit,)
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["article_ids"] = json.loads(d["article_ids"])
        result.append(d)
    return result
