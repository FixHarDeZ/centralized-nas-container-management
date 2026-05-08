import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import config

_TZ = ZoneInfo(config.TZ)

_DEFAULT_SETTINGS = {
    "seed_min":                "5",
    "leech_min":               "10",
    "nas_path":                config.NAS_DOWNLOADS_DIR,
    "line_notify_enabled":     "0",
    "line_notify_keyword_only":"0",
    "line_notify_summary":     "1",
    "scrape_interval":         "30",   # minutes: "30" or "60"
    "scrape_all_day":          "0",    # "0" = 19:00-01:00 only, "1" = all day
}


@contextmanager
def _conn():
    c = sqlite3.connect(config.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.close()


def init_db():
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS sources (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                url        TEXT UNIQUE NOT NULL,
                enabled    INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS torrents (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id        INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                site_id          TEXT NOT NULL,
                title            TEXT NOT NULL,
                detail_url       TEXT NOT NULL,
                torrent_url      TEXT NOT NULL,
                cover_url        TEXT,
                seeds            INTEGER DEFAULT 0,
                leeches          INTEGER DEFAULT 0,
                date_posted      TEXT NOT NULL,
                posted_at        TEXT DEFAULT '',
                category         TEXT DEFAULT '',
                file_count       INTEGER DEFAULT 0,
                file_size        TEXT DEFAULT '',
                first_seen_at    TEXT NOT NULL,
                last_updated_at  TEXT NOT NULL,
                downloaded_local INTEGER DEFAULT 0,
                downloaded_nas   INTEGER DEFAULT 0,
                UNIQUE(source_id, site_id)
            );

            CREATE TABLE IF NOT EXISTS keywords (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                source_id  INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
                keyword    TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(source_id, keyword)
            );

            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_torrents_source_date
                ON torrents(source_id, date_posted);
        """)

        # Seed default settings (INSERT new keys only)
        for key, val in _DEFAULT_SETTINGS.items():
            c.execute("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (key, val))

        # Apply new defaults (force-update to match current _DEFAULT_SETTINGS)
        c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('seed_min','5')")
        c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('leech_min','10')")
        c.execute("INSERT OR REPLACE INTO settings(key,value) VALUES ('line_notify_enabled','0')")

        # Migrate: add new columns if missing (existing installs)
        for col_sql in [
            "ALTER TABLE torrents ADD COLUMN posted_at   TEXT DEFAULT ''",
            "ALTER TABLE torrents ADD COLUMN category    TEXT DEFAULT ''",
            "ALTER TABLE torrents ADD COLUMN file_count  INTEGER DEFAULT 0",
            "ALTER TABLE torrents ADD COLUMN file_size   TEXT DEFAULT ''",
        ]:
            try:
                c.execute(col_sql)
            except Exception:
                pass


def seed_default_sources(urls: list[str]):
    if not urls:
        return
    with _conn() as c:
        existing = {r["url"] for r in c.execute("SELECT url FROM sources").fetchall()}
        if not existing:
            now = _now()
            for url in urls:
                c.execute("INSERT OR IGNORE INTO sources(url, enabled, created_at) VALUES (?, 1, ?)", (url, now))


def _now() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")


# ─── Sources ─────────────────────────────────────────────────────────────────

def get_sources() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM sources ORDER BY id").fetchall()]


def add_source(url: str) -> dict:
    with _conn() as c:
        c.execute("INSERT INTO sources(url, enabled, created_at) VALUES (?, 1, ?)", (url, _now()))
        row = c.execute("SELECT * FROM sources WHERE url = ?", (url,)).fetchone()
        return dict(row)


def remove_source(source_id: int):
    with _conn() as c:
        c.execute("DELETE FROM sources WHERE id = ?", (source_id,))


def toggle_source(source_id: int, enabled: bool):
    with _conn() as c:
        c.execute("UPDATE sources SET enabled = ? WHERE id = ?", (1 if enabled else 0, source_id))


def get_enabled_sources() -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM sources WHERE enabled = 1 ORDER BY id").fetchall()]


# ─── Torrents ─────────────────────────────────────────────────────────────────

def upsert_torrent(source_id: int, site_id: str, data: dict) -> tuple[bool, int]:
    """Returns (is_new, torrent_id)."""
    now = _now()
    with _conn() as c:
        existing = c.execute(
            "SELECT id FROM torrents WHERE source_id = ? AND site_id = ?",
            (source_id, site_id)
        ).fetchone()

        if existing:
            c.execute(
                "UPDATE torrents SET seeds=?, leeches=?, last_updated_at=? WHERE id=?",
                (data["seeds"], data["leeches"], now, existing["id"])
            )
            return False, existing["id"]
        else:
            c.execute(
                """INSERT INTO torrents
                   (source_id, site_id, title, detail_url, torrent_url, cover_url,
                    seeds, leeches, date_posted, posted_at, category,
                    file_count, file_size, first_seen_at, last_updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (source_id, site_id, data["title"], data["detail_url"], data["torrent_url"],
                 data.get("cover_url"), data["seeds"], data["leeches"],
                 data["date_posted"], data.get("posted_at", ""), data.get("category", ""),
                 data.get("file_count", 0), data.get("file_size", ""), now, now)
            )
            return True, c.execute("SELECT last_insert_rowid()").fetchone()[0]


def _sort_order(sort: str) -> str:
    return {"leeches": "leeches DESC", "date": "posted_at DESC"}.get(sort, "seeds DESC")


def get_today_torrents(source_id: int, today: str, sort: str = "seeds") -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            f"SELECT * FROM torrents WHERE source_id = ? AND date_posted = ? ORDER BY {_sort_order(sort)}",
            (source_id, today)
        ).fetchall()
        return [dict(r) for r in rows]


def get_history_torrents(source_id: int, date: str, sort: str = "seeds") -> list[dict]:
    order = _sort_order(sort)  # noqa: reuse
    with _conn() as c:
        rows = c.execute(
            f"SELECT * FROM torrents WHERE source_id = ? AND date_posted = ? ORDER BY {order}",
            (source_id, date)
        ).fetchall()
        return [dict(r) for r in rows]


def get_history_dates(source_id: int) -> list[str]:
    with _conn() as c:
        rows = c.execute(
            "SELECT DISTINCT date_posted FROM torrents WHERE source_id = ? ORDER BY date_posted DESC",
            (source_id,)
        ).fetchall()
        return [r[0] for r in rows]


def get_torrent(torrent_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM torrents WHERE id = ?", (torrent_id,)).fetchone()
        return dict(row) if row else None


def mark_downloaded_local(torrent_id: int):
    with _conn() as c:
        c.execute("UPDATE torrents SET downloaded_local = 1 WHERE id = ?", (torrent_id,))


def mark_downloaded_nas(torrent_id: int):
    with _conn() as c:
        c.execute("UPDATE torrents SET downloaded_nas = 1 WHERE id = ?", (torrent_id,))


# ─── Keywords ─────────────────────────────────────────────────────────────────

def get_keywords(source_id: int) -> list[dict]:
    with _conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM keywords WHERE source_id = ? ORDER BY keyword", (source_id,)
        ).fetchall()]


def get_keywords_for_source(source_id: int) -> list[str]:
    with _conn() as c:
        rows = c.execute("SELECT keyword FROM keywords WHERE source_id = ?", (source_id,)).fetchall()
        return [r[0].lower() for r in rows]


def add_keyword(source_id: int, keyword: str) -> dict:
    with _conn() as c:
        c.execute(
            "INSERT INTO keywords(source_id, keyword, created_at) VALUES (?, ?, ?)",
            (source_id, keyword.strip(), _now())
        )
        row = c.execute(
            "SELECT * FROM keywords WHERE source_id = ? AND keyword = ?",
            (source_id, keyword.strip())
        ).fetchone()
        return dict(row)


def remove_keyword(keyword_id: int):
    with _conn() as c:
        c.execute("DELETE FROM keywords WHERE id = ?", (keyword_id,))


# ─── Settings ─────────────────────────────────────────────────────────────────

def get_settings() -> dict:
    with _conn() as c:
        rows = c.execute("SELECT key, value FROM settings").fetchall()
        return {r["key"]: r["value"] for r in rows}


def update_settings(data: dict):
    with _conn() as c:
        for key, val in data.items():
            if key in _DEFAULT_SETTINGS:
                c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES (?, ?)", (key, str(val)))


# ─── Cleanup ──────────────────────────────────────────────────────────────────

def cleanup_old_records(days: int = 7) -> int:
    cutoff = (datetime.now(_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
    with _conn() as c:
        result = c.execute("DELETE FROM torrents WHERE date_posted < ?", (cutoff,))
        return result.rowcount
