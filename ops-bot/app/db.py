from __future__ import annotations

from typing import Optional

import aiosqlite

from app.config import get_config

_db: Optional[aiosqlite.Connection] = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kuma_event_id TEXT,
    service_name TEXT NOT NULL,
    container_name TEXT,
    status TEXT NOT NULL,
    alert_message TEXT,
    is_watchtower_update BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS diagnostics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER REFERENCES incidents(id),
    step_name TEXT NOT NULL,
    raw_output TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER REFERENCES incidents(id),
    root_cause TEXT,
    severity TEXT,
    suggested_fix TEXT,
    fix_commands TEXT,
    llm_tokens_used INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER REFERENCES incidents(id),
    action_type TEXT NOT NULL,
    commands_executed TEXT,
    result_output TEXT,
    success BOOLEAN,
    executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


async def init_db() -> None:
    global _db
    cfg = get_config()
    _db = await aiosqlite.connect(cfg.db_path)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    await _db.commit()


async def get_db() -> aiosqlite.Connection:
    global _db
    if _db is None:
        await init_db()
    return _db


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None
