import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config

_TZ = ZoneInfo(config.TZ)

_DEFAULT_SETTINGS = {
    "seed_min":                    "10",
    "leech_min":                   "10",
    "completed_min":               "20",
    "filter_mode":                 "or",   # "and" or "or"
    "scrape_sticky":               "1",    # "0" = skip sticky/pinned, "1" = include them
    "line_notify_keyword_enabled": "0",    # "0" = off, "1" = push LINE on keyword match
    "auto_download_nas":           "0",    # "0" = off, "1" = auto-save keyword matches to /downloads
    "retention_days":              "7",    # days to keep torrent records before weekly cleanup
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
                label      TEXT DEFAULT '',
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
                completed        INTEGER DEFAULT 0,
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

        # Migration: force scrape_sticky=1 for all existing installs (was "0" before 2026-05-12)
        c.execute("UPDATE settings SET value='1' WHERE key='scrape_sticky' AND value='0'")

        # Ensure filter_mode exists (new setting)
        c.execute("INSERT OR IGNORE INTO settings(key,value) VALUES ('filter_mode','and')")
        # Remove obsolete settings
        for k in ("line_notify_enabled", "line_notify_keyword_only", "line_notify_summary",
                  "nas_path", "scrape_interval", "scrape_all_day"):
            c.execute("DELETE FROM settings WHERE key=?", (k,))

        # Migrate: add new columns if missing (existing installs)
        for col_sql in [
            "ALTER TABLE sources ADD COLUMN label TEXT DEFAULT ''",
            "ALTER TABLE torrents ADD COLUMN posted_at   TEXT DEFAULT ''",
            "ALTER TABLE torrents ADD COLUMN category    TEXT DEFAULT ''",
            "ALTER TABLE torrents ADD COLUMN file_count  INTEGER DEFAULT 0",
            "ALTER TABLE torrents ADD COLUMN file_size   TEXT DEFAULT ''",
            "ALTER TABLE torrents ADD COLUMN completed   INTEGER DEFAULT 0",
            "ALTER TABLE torrents ADD COLUMN is_sticky   INTEGER DEFAULT 0",
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


def rename_source(source_id: int, label: str):
    with _conn() as c:
        c.execute("UPDATE sources SET label = ? WHERE id = ?", (label.strip(), source_id))


def sync_stickies(source_id: int, seen_site_ids: set[str], today: str):
    """Keep sticky entries in sync with what bearbit currently shows as pinned.
    - Still pinned (site_id in seen_site_ids) → refresh date_posted to today so they
      stay visible in the Today tab even across midnight.
    - No longer pinned (site_id absent) → clear is_sticky flag and backdate so the
      entry leaves the Today tab on the next page load.
    - Newly pinned (site_id in seen_site_ids but is_sticky=0 in DB) → promote to sticky
      and set date_posted=today (safety net for upsert_torrent edge cases).
    """
    if not seen_site_ids:
        print("[db] sync_stickies: seen_site_ids is empty — nothing to sync")
        return
    print(f"[db] sync_stickies: seen_site_ids={seen_site_ids}")
    with _conn() as c:
        # Promote: entries that bearbit now shows as pinned but DB still has is_sticky=0
        placeholders = ",".join("?" * len(seen_site_ids))
        c.execute(
            f"UPDATE torrents SET is_sticky=1, date_posted=? "
            f"WHERE source_id=? AND is_sticky=0 AND site_id IN ({placeholders})",
            (today, source_id, *seen_site_ids)
        )
        if c.rowcount > 0:
            print(f"[db] sync_stickies: PROMOTED {c.rowcount} entries to sticky")

        # Refresh still-pinned / demote un-pinned
        rows = c.execute(
            "SELECT id, site_id FROM torrents WHERE source_id=? AND is_sticky=1",
            (source_id,)
        ).fetchall()
        promoted = demoted = 0
        for row in rows:
            if row["site_id"] in seen_site_ids:
                c.execute("UPDATE torrents SET date_posted=? WHERE id=?", (today, row["id"]))
                promoted += 1
            else:
                # Bearbit un-pinned this entry — remove sticky badge but keep date_posted
                # so a 1-time detection miss doesn't immediately drop it from Today.
                # If truly un-pinned, the entry will age out naturally on the next day.
                print(f"[db] sync_stickies: DEMOTING site_id={row['site_id']} — not in seen_site_ids (keeping date_posted)")
                c.execute(
                    "UPDATE torrents SET is_sticky=0 WHERE id=?",
                    (row["id"],)
                )
                demoted += 1
        print(f"[db] sync_stickies: refreshed={promoted} demoted={demoted}")


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
                """UPDATE torrents
                   SET seeds=?, leeches=?, completed=?, date_posted=?, category=?, is_sticky=?, last_updated_at=?
                   WHERE id=?""",
                (data["seeds"], data["leeches"], data.get("completed", 0),
                 data["date_posted"], data.get("category", ""),
                 1 if data.get("is_sticky") else 0, now, existing["id"])
            )
            return False, existing["id"]
        else:
            c.execute(
                """INSERT INTO torrents
                   (source_id, site_id, title, detail_url, torrent_url, cover_url,
                    seeds, leeches, date_posted, posted_at, category,
                    file_count, file_size, completed, is_sticky, first_seen_at, last_updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (source_id, site_id, data["title"], data["detail_url"], data["torrent_url"],
                 data.get("cover_url"), data["seeds"], data["leeches"],
                 data["date_posted"], data.get("posted_at", ""), data.get("category", ""),
                 data.get("file_count", 0), data.get("file_size", ""),
                 data.get("completed", 0), 1 if data.get("is_sticky") else 0, now, now)
            )
            return True, c.execute("SELECT last_insert_rowid()").fetchone()[0]


def _sort_order(sort: str) -> str:
    return {"leeches": "leeches DESC", "date": "posted_at DESC", "completed": "completed DESC"}.get(sort, "seeds DESC")


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


# ─── Utilities ────────────────────────────────────────────────────────────────

def torrent_filename(title: str) -> str:
    """Filesystem-safe ASCII filename for a torrent (strips non-ASCII, max 80 chars)."""
    safe = re.sub(r'[^\x00-\x7F]', '_', title).strip("_ ")[:80]
    return (safe or "torrent") + ".torrent"


# ─── Debug / Admin ────────────────────────────────────────────────────────────

def clear_source_today(source_id: int, today: str):
    with _conn() as c:
        c.execute("DELETE FROM torrents WHERE source_id=? AND date_posted=?", (source_id, today))


def clear_source_all(source_id: int):
    with _conn() as c:
        c.execute("DELETE FROM torrents WHERE source_id=?", (source_id,))


# ─── Cleanup ──────────────────────────────────────────────────────────────────

def cleanup_old_records(days: int = 7) -> int:
    cutoff = (datetime.now(_TZ) - timedelta(days=days)).strftime("%Y-%m-%d")
    with _conn() as c:
        result = c.execute("DELETE FROM torrents WHERE date_posted < ?", (cutoff,))
        return result.rowcount
