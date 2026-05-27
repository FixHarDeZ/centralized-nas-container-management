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


# ── CONVERT ──────────────────────────────────────────────────────────────────

def _rt(rich_text: list) -> str:
    return "".join(rt.get("plain_text", "") for rt in (rich_text or []))


def _table_to_markdown(children: list[dict]) -> str:
    if not children:
        return ""
    md_rows = []
    for i, row in enumerate(children):
        cells = row.get("table_row", {}).get("cells", [])
        cell_texts = [_rt(cell) for cell in cells]
        md_rows.append("| " + " | ".join(cell_texts) + " |")
        if i == 0:
            md_rows.append("| " + " | ".join(["---"] * len(cell_texts)) + " |")
    return "\n".join(md_rows)


def blocks_to_markdown(blocks: list[dict], _depth: int = 0) -> str:
    lines = []
    numbered_counter = 0

    for block in blocks:
        btype = block.get("type", "")
        data = block.get(btype, {})
        children = block.get("_children", [])
        text = _rt(data.get("rich_text", []))

        if btype == "paragraph":
            lines.append(text)
        elif btype == "heading_1":
            lines.append(f"# {text}")
        elif btype == "heading_2":
            lines.append(f"## {text}")
        elif btype == "heading_3":
            lines.append(f"### {text}")
        elif btype == "bulleted_list_item":
            lines.append(f"- {text}")
            if children:
                lines.append(blocks_to_markdown(children, _depth + 1))
        elif btype == "numbered_list_item":
            numbered_counter += 1
            lines.append(f"{numbered_counter}. {text}")
            if children:
                lines.append(blocks_to_markdown(children, _depth + 1))
        elif btype == "to_do":
            checked = "x" if data.get("checked") else " "
            lines.append(f"- [{checked}] {text}")
        elif btype == "quote":
            lines.append(f"> {text}")
        elif btype == "callout":
            emoji = (data.get("icon") or {}).get("emoji", "")
            lines.append(f"> {emoji} {text}".strip())
        elif btype == "code":
            lang = data.get("language", "")
            lines.append(f"```{lang}\n{text}\n```")
        elif btype in ("bookmark", "embed", "link_preview"):
            url = data.get("url", "")
            caption = _rt(data.get("caption", [])) or url
            lines.append(f"[{caption}]({url})")
        elif btype == "image":
            img = data.get("external") or data.get("file") or {}
            url = img.get("url", "")
            caption = _rt(data.get("caption", []))
            lines.append(f"![{caption}]({url})")
        elif btype == "divider":
            lines.append("---")
        elif btype == "child_page":
            title = data.get("title", "")
            lines.append(f"[→ {title}]")
        elif btype == "toggle":
            lines.append(f"## {text}")
            if children:
                lines.append(blocks_to_markdown(children, _depth + 1))
        elif btype in ("column_list", "column", "synced_block"):
            if children:
                lines.append(blocks_to_markdown(children, _depth + 1))
        elif btype == "table":
            lines.append(_table_to_markdown(children))
        # unknown types: silently skip

        if btype not in ("bulleted_list_item", "numbered_list_item"):
            numbered_counter = 0

    return "\n".join(line for line in lines if line)
