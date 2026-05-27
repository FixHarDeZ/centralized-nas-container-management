"""Notion → Qdrant hybrid-search ingest service."""
from __future__ import annotations

import logging
import os
import re
import sqlite3
import threading
import time
import uuid
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

# ── CONFIG ───────────────────────────────────────────────────────────────────

QDRANT_URL      = os.getenv("QDRANT_URL", "http://qdrant:6333")
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "secretary_notes")
STATE_DB        = os.getenv("STATE_DB", "/data/ingest_state.db")

NOTION_TOKEN        = os.getenv("NOTION_TOKEN", "")
NOTION_SOURCE_TYPE  = os.getenv("NOTION_SOURCE_TYPE", "search")
NOTION_DATABASE_ID  = os.getenv("NOTION_DATABASE_ID", "")
NOTION_ROOT_PAGE_ID = os.getenv("NOTION_ROOT_PAGE_ID", "")

logger = logging.getLogger(__name__)

_api_call_count = 0  # global counter, reset per run


# ── STATE DB ─────────────────────────────────────────────────────────────────

def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pages (
            page_id          TEXT PRIMARY KEY,
            last_edited_time TEXT NOT NULL,
            chunk_count      INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    return conn


def get_state(conn: sqlite3.Connection, page_id: str) -> Optional[dict]:
    row = conn.execute(
        "SELECT page_id, last_edited_time, chunk_count FROM pages WHERE page_id = ?",
        (page_id,),
    ).fetchone()
    if not row:
        return None
    return {"page_id": row[0], "last_edited_time": row[1], "chunk_count": row[2]}


def upsert_state(conn: sqlite3.Connection, page_id: str, last_edited_time: str, chunk_count: int):
    conn.execute(
        "INSERT OR REPLACE INTO pages (page_id, last_edited_time, chunk_count) VALUES (?, ?, ?)",
        (page_id, last_edited_time, chunk_count),
    )
    conn.commit()


def delete_state(conn: sqlite3.Connection, page_id: str):
    conn.execute("DELETE FROM pages WHERE page_id = ?", (page_id,))
    conn.commit()


def list_all_pages(conn: sqlite3.Connection) -> dict[str, str]:
    rows = conn.execute("SELECT page_id, last_edited_time FROM pages").fetchall()
    return {row[0]: row[1] for row in rows}
