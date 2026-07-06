import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS titles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  slug TEXT UNIQUE NOT NULL,
  title TEXT NOT NULL,
  tags TEXT DEFAULT '',
  pages INTEGER DEFAULT 0,
  file_size INTEGER,
  status TEXT NOT NULL DEFAULT 'new',
  source_url TEXT DEFAULT '',
  downloaded_at TEXT NOT NULL,
  expires_at TEXT
);
CREATE TABLE IF NOT EXISTS scrape_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TEXT NOT NULL,
  found INTEGER DEFAULT 0,
  downloaded INTEGER DEFAULT 0,
  error TEXT
);
"""


def _connect():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def now_iso() -> str:
    return datetime.now(ZoneInfo(config.TZ)).isoformat(timespec="seconds")


def init_db():
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with _connect() as conn:
        conn.executescript(SCHEMA)


def cbz_path(tid: int) -> str:
    return os.path.join(config.LIBRARY_DIR, f"{tid}.cbz")


def cover_path(tid: int) -> str:
    return os.path.join(config.COVERS_DIR, f"{tid}.jpg")


def known_slugs() -> set[str]:
    with _connect() as conn:
        return {r["slug"] for r in conn.execute("SELECT slug FROM titles")}


def add_title(slug, title, tags, pages, file_size, source_url) -> int:
    expires = (
        datetime.now(ZoneInfo(config.TZ)) + timedelta(days=config.RETENTION_DAYS)
    ).isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO titles (slug, title, tags, pages, file_size, source_url,"
            " downloaded_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
            (slug, title, tags, pages, file_size, source_url, now_iso(), expires),
        )
        return cur.lastrowid


def get_title(tid: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM titles WHERE id=?", (tid,)).fetchone()
        return dict(row) if row else None


def list_titles(status: str | None = None) -> list[dict]:
    q = "SELECT * FROM titles"
    args: tuple = ()
    if status:
        q += " WHERE status=?"
        args = (status,)
    q += " ORDER BY downloaded_at DESC, id DESC"
    with _connect() as conn:
        return [dict(r) for r in conn.execute(q, args)]


def keep_title(tid: int) -> bool:
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE titles SET status='kept', expires_at=NULL WHERE id=? AND status='new'",
            (tid,),
        )
        return cur.rowcount > 0


def purge_title(tid: int) -> bool:
    """Delete files from disk and tombstone the row."""
    for p in (cbz_path(tid), cover_path(tid)):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE titles SET status='deleted', expires_at=NULL, file_size=NULL"
            " WHERE id=? AND status != 'deleted'",
            (tid,),
        )
        return cur.rowcount > 0


def expired_ids() -> list[int]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id FROM titles WHERE status='new' AND expires_at < ?",
            (now_iso(),),
        )
        return [r["id"] for r in rows]


def log_scrape(found: int, downloaded: int, error: str | None = None):
    with _connect() as conn:
        conn.execute(
            "INSERT INTO scrape_log (run_at, found, downloaded, error) VALUES (?,?,?,?)",
            (now_iso(), found, downloaded, error),
        )


def last_scrape() -> dict | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM scrape_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


def stats() -> dict:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count, COALESCE(SUM(file_size),0) AS size"
            " FROM titles GROUP BY status"
        )
        out = {s: {"count": 0, "size": 0} for s in ("new", "kept", "deleted")}
        for r in rows:
            out[r["status"]] = {"count": r["count"], "size": r["size"]}
        return out
