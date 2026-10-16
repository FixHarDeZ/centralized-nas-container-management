"""SQLite storage for lotto-picker.

New ``draws`` rows hold complete results (see ``lotto.is_complete``). Legacy
rows missing last2 can receive that field from a complete official payload.
``nodraw`` remembers past days GLO answered null for, so a history backfill
never probes the same day twice.
"""

from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from . import lotto

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
DB_PATH = DATA_DIR / "lotto.db"

DEFAULT_SETTINGS = {
    "draws": 2,
    "picks": 5,
    "scope": "all",
    "permute": False,
    "notify": True,
}


def init() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS draws (
                date       TEXT PRIMARY KEY,
                prizes     TEXT NOT NULL,
                fetched_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
            );
            CREATE TABLE IF NOT EXISTS nodraw (date TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS picks (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
                source      TEXT NOT NULL,
                numbers     TEXT NOT NULL,
                settings    TEXT NOT NULL,
                based_on    TEXT,
                result_draw TEXT,
                result      TEXT
            );
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """
        )


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


# --- draws -----------------------------------------------------------------


def add_draw(draw: dict) -> bool:
    """Insert a complete draw. True only when the row is new."""
    with conn() as c:
        cur = c.execute(
            "INSERT OR IGNORE INTO draws (date, prizes) VALUES (?, ?)",
            (draw["date"], json.dumps(draw["prizes"])),
        )
        return cur.rowcount == 1


def repair_last2(draw: dict) -> bool:
    """Fill a legacy cached last2 only from a complete, same-date payload.

    Existing three-digit prizes, fetched timestamp and saved pick results stay
    intact. A repair is never an insertion and must not trigger announcements.
    """
    if not lotto.is_complete(draw["prizes"]):
        return False
    with conn() as c:
        row = c.execute("SELECT prizes FROM draws WHERE date = ?", (draw["date"],)).fetchone()
        if row is None:
            return False
        prizes = json.loads(row["prizes"])
        if lotto.has_last2(prizes):
            return False
        prizes["last2"] = draw["prizes"]["last2"]
        c.execute(
            "UPDATE draws SET prizes = ? WHERE date = ?",
            (json.dumps(prizes), draw["date"]),
        )
        return True


def draws(limit: int | None = None) -> list[dict]:
    sql = "SELECT date, prizes FROM draws ORDER BY date DESC"
    args: tuple = ()
    if limit is not None:
        sql += " LIMIT ?"
        args = (limit,)
    with conn() as c:
        return [
            {"date": r["date"], "prizes": json.loads(r["prizes"])}
            for r in c.execute(sql, args)
        ]


def draw_dates() -> set[str]:
    with conn() as c:
        return {r[0] for r in c.execute("SELECT date FROM draws")}


def nodraw_dates() -> set[str]:
    with conn() as c:
        return {r[0] for r in c.execute("SELECT date FROM nodraw")}


def add_nodraw(date: str) -> None:
    with conn() as c:
        c.execute("INSERT OR IGNORE INTO nodraw (date) VALUES (?)", (date,))


# --- picks -----------------------------------------------------------------


def _pick_row(r: sqlite3.Row) -> dict:
    settings = json.loads(r["settings"])
    settings["digits"] = settings.get("digits") or 3
    return {
        "id": r["id"],
        "created_at": r["created_at"],
        "source": r["source"],
        "numbers": json.loads(r["numbers"]),
        "settings": settings,
        "based_on": r["based_on"],
        "result_draw": r["result_draw"],
        "result": json.loads(r["result"]) if r["result"] else None,
    }


def add_pick(source: str, numbers: list[str], settings: dict, based_on: str | None) -> int:
    with conn() as c:
        cur = c.execute(
            "INSERT INTO picks (source, numbers, settings, based_on) VALUES (?, ?, ?, ?)",
            (source, json.dumps(numbers), json.dumps(settings), based_on),
        )
        return cur.lastrowid


def picks(limit: int = 50, digits: int | None = None) -> list[dict]:
    sql = "SELECT * FROM picks"
    args = []
    if digits is not None:
        sql += " WHERE COALESCE(json_extract(settings, '$.digits'), 3) = ?"
        args.append(digits)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    with conn() as c:
        rows = c.execute(sql, args)
        return [_pick_row(r) for r in rows]


def unchecked_picks() -> list[dict]:
    with conn() as c:
        rows = c.execute("SELECT * FROM picks WHERE result_draw IS NULL ORDER BY id")
        return [_pick_row(r) for r in rows]


def set_result(pick_id: int, draw_date: str, result: dict) -> None:
    with conn() as c:
        c.execute(
            "UPDATE picks SET result_draw = ?, result = ? WHERE id = ?",
            (draw_date, json.dumps(result), pick_id),
        )


def delete_pick(pick_id: int) -> bool:
    with conn() as c:
        return c.execute("DELETE FROM picks WHERE id = ?", (pick_id,)).rowcount == 1


def checked_picks(digits: int | None = None) -> list[dict]:
    sql = "SELECT * FROM picks WHERE result IS NOT NULL"
    args = ()
    if digits is not None:
        sql += " AND COALESCE(json_extract(settings, '$.digits'), 3) = ?"
        args = (digits,)
    sql += " ORDER BY id"
    with conn() as c:
        rows = c.execute(sql, args)
        return [_pick_row(r) for r in rows]


# --- kv: settings + bookkeeping -------------------------------------------


def get(key: str, default=None):
    with conn() as c:
        r = c.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
    return json.loads(r[0]) if r else default


def put(key: str, value) -> None:
    with conn() as c:
        c.execute(
            "INSERT INTO kv (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )


def settings(digits: int = 3) -> dict:
    key = "settings_2" if digits == 2 else "settings"
    defaults = {**DEFAULT_SETTINGS, "notify": False} if digits == 2 else DEFAULT_SETTINGS
    profile = {**defaults, **get(key, {}), "digits": digits}
    if digits == 2:
        profile["scope"] = "last2"
    return profile
