import os
import re
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from PIL import Image

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
  source TEXT DEFAULT 'doujinth',
  downloaded_at TEXT NOT NULL,
  expires_at TEXT
);
CREATE TABLE IF NOT EXISTS scrape_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TEXT NOT NULL,
  found INTEGER DEFAULT 0,
  downloaded INTEGER DEFAULT 0,
  error TEXT,
  source TEXT DEFAULT 'all'
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

# Runtime-tunable settings (dashboard). Env vars only seed the defaults.
DEFAULT_SETTINGS = {
    "retention_days": config.RETENTION_DAYS,
    "min_pages": 30,
}
SETTING_LIMITS = {
    "retention_days": (1, 3650),
    "min_pages": (1, 1000),
}


def get_settings() -> dict:
    with _connect() as conn:
        stored = dict(conn.execute("SELECT key, value FROM settings"))
    return {k: int(stored.get(k, d)) for k, d in DEFAULT_SETTINGS.items()}


def update_settings(changes: dict) -> dict:
    """Validate + persist settings. Changing retention_days recomputes
    expires_at for every live title so the new window applies retroactively."""
    updates = {}
    for key, (lo, hi) in SETTING_LIMITS.items():
        if key not in changes:
            continue
        try:
            val = int(changes[key])
        except (TypeError, ValueError):
            raise ValueError(f"{key} must be an integer")
        if not lo <= val <= hi:
            raise ValueError(f"{key} must be between {lo} and {hi}")
        updates[key] = val
    old = get_settings()
    with _connect() as conn:
        for k, v in updates.items():
            conn.execute(
                "INSERT INTO settings (key, value) VALUES (?,?)"
                " ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (k, str(v)),
            )
        if updates.get("retention_days") not in (None, old["retention_days"]):
            days = updates["retention_days"]
            rows = conn.execute(
                "SELECT id, downloaded_at FROM titles WHERE status='new'"
            ).fetchall()
            for r in rows:
                exp = (
                    datetime.fromisoformat(r["downloaded_at"]) + timedelta(days=days)
                ).isoformat(timespec="seconds")
                conn.execute("UPDATE titles SET expires_at=? WHERE id=?", (exp, r["id"]))
    return get_settings()


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
        # Migration: add source column if missing
        for table, col, default in [
            ("titles", "source", "doujinth"),
            ("scrape_log", "source", "all"),
        ]:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} TEXT DEFAULT '{default}'")
            except sqlite3.OperationalError:
                pass  # column already exists
        # Migration: prefix existing slugs that lack source prefix.
        # Old doujin-th slugs were bare numeric IDs (e.g. "111").
        # New format is "doujinth-111". Delete old rows where the
        # namespaced version already exists, then prefix the rest.
        existing = {
            r[0] for r in conn.execute(
                "SELECT slug FROM titles WHERE slug LIKE 'doujinth-%'"
            )
        }
        bare = [
            r[0] for r in conn.execute(
                "SELECT slug FROM titles WHERE slug NOT LIKE '%-%' AND source='doujinth'"
            )
        ]
        for slug in bare:
            ns = f"doujinth-{slug}"
            if ns in existing:
                conn.execute("DELETE FROM titles WHERE slug=?", (slug,))
            else:
                conn.execute("UPDATE titles SET slug=? WHERE slug=?", (ns, slug))
        # Migration: kept feature removed — kept rows go back to 'new' with a
        # fresh expiry window instead of expiring immediately.
        row = conn.execute(
            "SELECT value FROM settings WHERE key='retention_days'"
        ).fetchone()
        days = int(row[0]) if row else config.RETENTION_DAYS
        expires = (
            datetime.now(ZoneInfo(config.TZ)) + timedelta(days=days)
        ).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE titles SET status='new', expires_at=? WHERE status='kept'",
            (expires,),
        )


def cbz_path(tid: int) -> str:
    return os.path.join(config.LIBRARY_DIR, f"{tid}.cbz")


def cover_path(tid: int) -> str:
    return os.path.join(config.COVERS_DIR, f"{tid}.jpg")


def known_slugs() -> set[str]:
    with _connect() as conn:
        return {r["slug"] for r in conn.execute("SELECT slug FROM titles")}


def add_title(slug, title, tags, pages, file_size, source_url, source="doujinth") -> int:
    expires = (
        datetime.now(ZoneInfo(config.TZ))
        + timedelta(days=get_settings()["retention_days"])
    ).isoformat(timespec="seconds")
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO titles (slug, title, tags, pages, file_size, source_url,"
            " source, downloaded_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (slug, title, tags, pages, file_size, source_url, source, now_iso(), expires),
        )
        return cur.lastrowid


def get_title(tid: int) -> dict | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM titles WHERE id=?", (tid,)).fetchone()
        return dict(row) if row else None


def list_titles(status: str | None = None, source: str | None = None) -> list[dict]:
    q = "SELECT * FROM titles"
    conditions, args = [], []
    if status:
        conditions.append("status=?")
        args.append(status)
    if source:
        conditions.append("source=?")
        args.append(source)
    if conditions:
        q += " WHERE " + " AND ".join(conditions)
    q += " ORDER BY downloaded_at DESC, id DESC"
    with _connect() as conn:
        return [dict(r) for r in conn.execute(q, args)]


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


def last_scrape() -> dict:
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM scrape_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row:
            d = dict(row)
            if d["run_at"]:
                d["run_at"] = int(datetime.fromisoformat(d["run_at"]).timestamp())
            return d
        return {"run_at": 0, "found": 0, "downloaded": 0, "error": None, "source": "all"}


def stats() -> dict:
    min_pages = get_settings()["min_pages"]
    with _connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count, COALESCE(SUM(file_size),0) AS size"
            " FROM titles GROUP BY status"
        )
        out = {s: {"count": 0, "size": 0} for s in ("new", "deleted")}
        for r in rows:
            out[r["status"]] = {"count": r["count"], "size": r["size"]}
        long_row = conn.execute(
            "SELECT COUNT(*) AS count FROM titles"
            " WHERE status != 'deleted' AND pages >= ?",
            (min_pages,),
        ).fetchone()
        out["long"] = {"count": long_row["count"], "size": 0}
        return out


def _normalize_title(title: str) -> str:
    t = title.lower()
    return re.sub(r"[\s\-_.,!?()\[\]【】「」『』:：]+", "", t)


def _ahash(path: str, hash_size: int = 8) -> int | None:
    """Average-hash of cover image for cheap visual similarity check."""
    try:
        img = Image.open(path).convert("L").resize((hash_size, hash_size), Image.LANCZOS)
    except Exception:
        return None
    pixels = list(img.getdata())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for p in pixels:
        bits = (bits << 1) | (1 if p >= avg else 0)
    return bits


def dedupe_titles(hash_threshold: int = 10) -> list[int]:
    """Purge titles that share a normalized name + a visually similar cover
    with an earlier title. Cross-source re-uploads are the main case (same
    doujin scraped from two sites under the same Thai title).
    Returns purged ids.
    """
    with _connect() as conn:
        rows = [
            dict(r) for r in conn.execute(
                "SELECT id, title, downloaded_at FROM titles"
                " WHERE status != 'deleted' ORDER BY downloaded_at ASC"
            )
        ]
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(_normalize_title(r["title"]), []).append(r)

    purged = []
    for group in groups.values():
        if len(group) < 2:
            continue
        keeper = group[0]  # earliest download wins
        keeper_hash = _ahash(cover_path(keeper["id"]))
        for r in group[1:]:
            h = _ahash(cover_path(r["id"]))
            # can't confirm visually (cover missing/unreadable) -> skip rather
            # than delete on title text alone
            if keeper_hash is None or h is None:
                continue
            if bin(keeper_hash ^ h).count("1") <= hash_threshold:
                if purge_title(r["id"]):
                    purged.append(r["id"])
    return purged


def source_stats() -> dict:
    """Per-source title counts and sizes."""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT source, COUNT(*) AS count, COALESCE(SUM(file_size),0) AS size"
            " FROM titles WHERE status != 'deleted' GROUP BY source"
        )
        return {r["source"]: {"count": r["count"], "size": r["size"]} for r in rows}
