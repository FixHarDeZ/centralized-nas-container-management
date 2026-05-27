# Notion → Qdrant Ingest Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a single-file Python CLI (`ingest.py`) that syncs Notion pages into a Qdrant hybrid-search collection using BGE-M3 embeddings (dense + sparse), with incremental state tracking.

**Architecture:** Single `ingest.py` with clearly delimited sections (CONFIG → STATE DB → NOTION → CONVERT → CHUNK → EMBED → QDRANT → SYNC → CLI). FlagEmbedding's `BGEM3FlagModel` produces both dense (1024d) and sparse vectors in one pass — no Ollama dependency. Runs as a Docker one-shot container, triggered by n8n on schedule.

**Tech Stack:** `notion-client`, `qdrant-client`, `FlagEmbedding`, `tiktoken`, `tenacity`, `python-dotenv`, `sqlite3` (stdlib), `pytest` + `unittest.mock` for testing.

**Spec:** `docs/superpowers/specs/2026-05-27-notion-qdrant-ingest-design.md`

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Create | `secretary/ingest.py` | All logic: CONFIG, STATE DB, NOTION, CONVERT, CHUNK, EMBED, QDRANT, SYNC, CLI |
| Create | `secretary/requirements.txt` | Python dependencies |
| Create | `secretary/Dockerfile` | Container build |
| Create | `secretary/.env.example` | Config template |
| Create | `secretary/tests/__init__.py` | Test package marker |
| Create | `secretary/tests/conftest.py` | Env var setup before import |
| Create | `secretary/tests/test_state.py` | STATE DB tests |
| Create | `secretary/tests/test_convert.py` | Block converter tests |
| Create | `secretary/tests/test_chunk.py` | Chunker + breadcrumb tests |
| Create | `secretary/tests/test_notion.py` | Notion API (mocked) tests |
| Create | `secretary/tests/test_embed.py` | Embedding (mocked model) tests |
| Create | `secretary/tests/test_qdrant.py` | Qdrant (mocked client) tests |
| Create | `secretary/tests/test_sync.py` | Sync logic tests |
| Create | `secretary/tests/test_cli.py` | CLI argparse routing tests |
| Modify | `secretary/docker-compose.yml` | Add `secretary-ingest` service + `hf_cache` volume |
| Create | `secretary/README.md` | Setup + usage docs |

---

## Task 1: Bootstrap — requirements, Dockerfile, .env.example, conftest

**Files:**
- Create: `secretary/requirements.txt`
- Create: `secretary/Dockerfile`
- Create: `secretary/.env.example`
- Create: `secretary/tests/__init__.py`
- Create: `secretary/tests/conftest.py`

- [ ] **Step 1: Create `secretary/requirements.txt`**

```
notion-client>=2.2.0
qdrant-client>=1.9.0
FlagEmbedding>=1.2.10
tiktoken>=0.7.0
tenacity>=8.2.0
python-dotenv>=1.0.0
pytest>=8.0.0
```

- [ ] **Step 2: Create `secretary/Dockerfile`**

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    git build-essential && \
    rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ingest.py .
ENV HF_HOME=/hf_cache
CMD ["python", "ingest.py"]
```

- [ ] **Step 3: Create `secretary/.env.example`**

```env
QDRANT_URL=http://qdrant:6333
COLLECTION_NAME=secretary_notes
STATE_DB=/data/ingest_state.db

NOTION_TOKEN=ntn_xxxxx
NOTION_SOURCE_TYPE=search
NOTION_DATABASE_ID=
NOTION_ROOT_PAGE_ID=
```

- [ ] **Step 4: Create `secretary/tests/__init__.py`** (empty file)

- [ ] **Step 5: Create `secretary/tests/conftest.py`**

```python
import os
os.environ.setdefault("NOTION_TOKEN", "test_token")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("COLLECTION_NAME", "secretary_notes")
os.environ.setdefault("STATE_DB", "/tmp/test_ingest_state.db")
os.environ.setdefault("NOTION_SOURCE_TYPE", "search")
os.environ.setdefault("NOTION_DATABASE_ID", "")
os.environ.setdefault("NOTION_ROOT_PAGE_ID", "")
```

- [ ] **Step 6: Commit**

```bash
git add secretary/requirements.txt secretary/Dockerfile secretary/.env.example secretary/tests/
git commit -m "feat(secretary-ingest): bootstrap project files"
```

---

## Task 2: Skeleton ingest.py + CONFIG section

**Files:**
- Create: `secretary/ingest.py`

- [ ] **Step 1: Write failing import test** in `secretary/tests/test_config.py`

```python
# secretary/tests/test_config.py
def test_import_succeeds():
    import ingest
    assert ingest.QDRANT_URL == "http://localhost:6333"
    assert ingest.COLLECTION_NAME == "secretary_notes"
    assert ingest.NOTION_TOKEN == "test_token"
```

- [ ] **Step 2: Run test to confirm it fails**

```bash
cd secretary && python -m pytest tests/test_config.py -v
```
Expected: `ModuleNotFoundError: No module named 'ingest'`

- [ ] **Step 3: Create `secretary/ingest.py` with CONFIG section**

```python
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

NOTION_TOKEN       = os.getenv("NOTION_TOKEN", "")
NOTION_SOURCE_TYPE = os.getenv("NOTION_SOURCE_TYPE", "search")
NOTION_DATABASE_ID = os.getenv("NOTION_DATABASE_ID", "")
NOTION_ROOT_PAGE_ID = os.getenv("NOTION_ROOT_PAGE_ID", "")

logger = logging.getLogger(__name__)

_api_call_count = 0  # global counter, reset per run
```

- [ ] **Step 4: Run test to confirm it passes**

```bash
cd secretary && python -m pytest tests/test_config.py -v
```
Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add secretary/ingest.py secretary/tests/test_config.py
git commit -m "feat(secretary-ingest): add CONFIG section skeleton"
```

---

## Task 3: STATE DB section

**Files:**
- Modify: `secretary/ingest.py` (append STATE DB section)
- Create: `secretary/tests/test_state.py`

- [ ] **Step 1: Write failing tests** in `secretary/tests/test_state.py`

```python
# secretary/tests/test_state.py
import sqlite3
import pytest
import ingest


@pytest.fixture
def conn():
    c = ingest.init_db(":memory:")
    yield c
    c.close()


def test_init_db_creates_table(conn):
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pages'"
    ).fetchone()
    assert tables is not None


def test_get_state_missing(conn):
    assert ingest.get_state(conn, "nonexistent") is None


def test_upsert_and_get_state(conn):
    ingest.upsert_state(conn, "page1", "2025-01-01T00:00:00.000Z", 5)
    result = ingest.get_state(conn, "page1")
    assert result == {"page_id": "page1", "last_edited_time": "2025-01-01T00:00:00.000Z", "chunk_count": 5}


def test_upsert_overwrites(conn):
    ingest.upsert_state(conn, "page1", "2025-01-01T00:00:00.000Z", 5)
    ingest.upsert_state(conn, "page1", "2025-06-01T00:00:00.000Z", 10)
    result = ingest.get_state(conn, "page1")
    assert result["last_edited_time"] == "2025-06-01T00:00:00.000Z"
    assert result["chunk_count"] == 10


def test_delete_state(conn):
    ingest.upsert_state(conn, "page1", "2025-01-01T00:00:00.000Z", 3)
    ingest.delete_state(conn, "page1")
    assert ingest.get_state(conn, "page1") is None


def test_list_all_pages(conn):
    ingest.upsert_state(conn, "p1", "2025-01-01T00:00:00.000Z", 2)
    ingest.upsert_state(conn, "p2", "2025-02-01T00:00:00.000Z", 4)
    result = ingest.list_all_pages(conn)
    assert result == {
        "p1": "2025-01-01T00:00:00.000Z",
        "p2": "2025-02-01T00:00:00.000Z",
    }
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd secretary && python -m pytest tests/test_state.py -v
```
Expected: `AttributeError: module 'ingest' has no attribute 'init_db'`

- [ ] **Step 3: Append STATE DB section to `secretary/ingest.py`**

After the CONFIG section, add:

```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd secretary && python -m pytest tests/test_state.py -v
```
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add secretary/ingest.py secretary/tests/test_state.py
git commit -m "feat(secretary-ingest): add STATE DB section"
```

---

## Task 4: CONVERT section — block-to-markdown converter

**Files:**
- Modify: `secretary/ingest.py` (append CONVERT section)
- Create: `secretary/tests/test_convert.py`

- [ ] **Step 1: Write failing tests** in `secretary/tests/test_convert.py`

```python
# secretary/tests/test_convert.py
import ingest


def _block(btype: str, text: str = "hello", **extra) -> dict:
    """Build a minimal Notion block fixture."""
    rt = [{"plain_text": text}]
    data = {"rich_text": rt, **extra}
    return {"type": btype, btype: data, "has_children": False}


def test_rt_extracts_plain_text():
    assert ingest._rt([{"plain_text": "foo"}, {"plain_text": " bar"}]) == "foo bar"


def test_rt_empty():
    assert ingest._rt([]) == ""


def test_paragraph():
    result = ingest.blocks_to_markdown([_block("paragraph", "hello world")])
    assert result == "hello world"


def test_heading_1():
    result = ingest.blocks_to_markdown([_block("heading_1", "Title")])
    assert result == "# Title"


def test_heading_2():
    result = ingest.blocks_to_markdown([_block("heading_2", "Section")])
    assert result == "## Section"


def test_heading_3():
    result = ingest.blocks_to_markdown([_block("heading_3", "Sub")])
    assert result == "### Sub"


def test_bulleted_list():
    result = ingest.blocks_to_markdown([_block("bulleted_list_item", "item")])
    assert result == "- item"


def test_numbered_list():
    blocks = [
        _block("numbered_list_item", "first"),
        _block("numbered_list_item", "second"),
    ]
    result = ingest.blocks_to_markdown(blocks)
    assert result == "1. first\n2. second"


def test_to_do_checked():
    b = _block("to_do", "done", checked=True)
    assert ingest.blocks_to_markdown([b]) == "- [x] done"


def test_to_do_unchecked():
    b = _block("to_do", "todo", checked=False)
    assert ingest.blocks_to_markdown([b]) == "- [ ] todo"


def test_quote():
    assert ingest.blocks_to_markdown([_block("quote", "wise words")]) == "> wise words"


def test_callout_with_emoji():
    b = {"type": "callout", "callout": {"rich_text": [{"plain_text": "note"}], "icon": {"emoji": "💡"}}, "has_children": False}
    assert ingest.blocks_to_markdown([b]) == "> 💡 note"


def test_code():
    b = {"type": "code", "code": {"rich_text": [{"plain_text": "x = 1"}], "language": "python"}, "has_children": False}
    assert ingest.blocks_to_markdown([b]) == "```python\nx = 1\n```"


def test_bookmark():
    b = {"type": "bookmark", "bookmark": {"url": "https://example.com", "caption": []}, "has_children": False}
    assert ingest.blocks_to_markdown([b]) == "[https://example.com](https://example.com)"


def test_image():
    b = {"type": "image", "image": {"external": {"url": "https://img.example.com/a.png"}, "caption": []}, "has_children": False}
    assert ingest.blocks_to_markdown([b]) == "![](https://img.example.com/a.png)"


def test_divider():
    assert ingest.blocks_to_markdown([{"type": "divider", "divider": {}, "has_children": False}]) == "---"


def test_child_page():
    b = {"type": "child_page", "child_page": {"title": "My Sub Page"}, "has_children": False}
    assert ingest.blocks_to_markdown([b]) == "[→ My Sub Page]"


def test_toggle_with_children():
    toggle = {
        "type": "toggle",
        "toggle": {"rich_text": [{"plain_text": "Details"}]},
        "has_children": True,
        "_children": [_block("paragraph", "inner text")],
    }
    result = ingest.blocks_to_markdown([toggle])
    assert "## Details" in result
    assert "inner text" in result


def test_table():
    rows = [
        {"type": "table_row", "table_row": {"cells": [[{"plain_text": "H1"}], [{"plain_text": "H2"}]]}, "has_children": False},
        {"type": "table_row", "table_row": {"cells": [[{"plain_text": "A"}], [{"plain_text": "B"}]]}, "has_children": False},
    ]
    table_block = {
        "type": "table",
        "table": {"has_column_header": True},
        "has_children": True,
        "_children": rows,
    }
    result = ingest.blocks_to_markdown([table_block])
    assert "| H1 | H2 |" in result
    assert "| --- | --- |" in result
    assert "| A | B |" in result


def test_unknown_block_skipped():
    b = {"type": "unsupported_xyz", "unsupported_xyz": {}, "has_children": False}
    result = ingest.blocks_to_markdown([b])
    assert result == ""
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd secretary && python -m pytest tests/test_convert.py -v
```
Expected: `AttributeError: module 'ingest' has no attribute '_rt'`

- [ ] **Step 3: Append CONVERT section to `secretary/ingest.py`**

```python
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
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd secretary && python -m pytest tests/test_convert.py -v
```
Expected: `20 passed`

- [ ] **Step 5: Commit**

```bash
git add secretary/ingest.py secretary/tests/test_convert.py
git commit -m "feat(secretary-ingest): add CONVERT section (block → markdown)"
```

---

## Task 5: CHUNK section

**Files:**
- Modify: `secretary/ingest.py` (append CHUNK section)
- Create: `secretary/tests/test_chunk.py`

- [ ] **Step 1: Write failing tests** in `secretary/tests/test_chunk.py`

```python
# secretary/tests/test_chunk.py
import ingest


def test_build_breadcrumb_title_only():
    assert ingest.build_breadcrumb("My Page") == "My Page"


def test_build_breadcrumb_with_section():
    assert ingest.build_breadcrumb("My Page", "Section A") == "My Page > Section A"


def test_build_breadcrumb_full():
    assert ingest.build_breadcrumb("My Page", "Section A", "Sub 1") == "My Page > Section A > Sub 1"


def test_chunk_empty_text():
    assert ingest.chunk_markdown("", "Page") == []


def test_chunk_whitespace_only():
    assert ingest.chunk_markdown("   \n\n  ", "Page") == []


def test_chunk_no_headings():
    text = "This is a single paragraph with some content."
    chunks = ingest.chunk_markdown(text, "My Page")
    assert len(chunks) == 1
    assert chunks[0]["chunk_index"] == 0
    assert chunks[0]["breadcrumb"] == "My Page"
    assert "single paragraph" in chunks[0]["text"]


def test_chunk_splits_on_h2():
    text = "Preamble text.\n## Section One\nContent one.\n## Section Two\nContent two."
    chunks = ingest.chunk_markdown(text, "Doc")
    assert len(chunks) == 3  # preamble + two sections
    assert "Preamble" in chunks[0]["text"]
    assert "Doc > Section One" in chunks[1]["breadcrumb"]
    assert "Doc > Section Two" in chunks[2]["breadcrumb"]


def test_chunk_indices_sequential():
    text = "Intro.\n## A\nAlpha.\n## B\nBeta."
    chunks = ingest.chunk_markdown(text, "Doc")
    indices = [c["chunk_index"] for c in chunks]
    assert indices == list(range(len(chunks)))


def test_chunk_tiny_merged_into_previous():
    # Section B has < 50 tokens — should merge into section A
    text = "## Section A\n" + ("word " * 60) + "\n## Section B\nTiny."
    chunks = ingest.chunk_markdown(text, "Doc")
    # Section B (4 tokens) merges into Section A
    assert len(chunks) == 1
    assert "Tiny" in chunks[0]["text"]
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd secretary && python -m pytest tests/test_chunk.py -v
```
Expected: `AttributeError: module 'ingest' has no attribute 'build_breadcrumb'`

- [ ] **Step 3: Append CHUNK section to `secretary/ingest.py`**

```python
# ── CHUNK ─────────────────────────────────────────────────────────────────────

import tiktoken as _tiktoken

_tokenizer = _tiktoken.get_encoding("cl100k_base")


def _count_tokens(text: str) -> int:
    return len(_tokenizer.encode(text))


def build_breadcrumb(page_title: str, section: str = "", subsection: str = "") -> str:
    parts = [page_title]
    if section:
        parts.append(section)
    if subsection:
        parts.append(subsection)
    return " > ".join(parts)


def chunk_markdown(text: str, page_title: str) -> list[dict]:
    if not text.strip():
        return []

    # Split on ## headings
    raw_sections = re.split(r"\n(?=## )", text)
    chunks: list[dict] = []
    chunk_index = 0

    for section in raw_sections:
        section = section.strip()
        if not section:
            continue

        lines = section.split("\n", 1)
        if lines[0].startswith("## "):
            section_title = lines[0][3:].strip()
            section_body = lines[1] if len(lines) > 1 else ""
        else:
            section_title = ""
            section_body = section

        # If still > 500 tokens, split on ### headings
        if _count_tokens(section) > 500:
            subsections = re.split(r"\n(?=### )", section)
        else:
            subsections = [section]

        for subsection in subsections:
            subsection = subsection.strip()
            if not subsection:
                continue

            sub_lines = subsection.split("\n", 1)
            sub_title = sub_lines[0][4:].strip() if sub_lines[0].startswith("### ") else ""

            breadcrumb = build_breadcrumb(page_title, section_title, sub_title)

            if _count_tokens(subsection) < 50 and chunks:
                chunks[-1]["text"] += "\n" + subsection
            else:
                chunks.append({
                    "text": subsection,
                    "breadcrumb": breadcrumb,
                    "chunk_index": chunk_index,
                })
                chunk_index += 1

    return chunks
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd secretary && python -m pytest tests/test_chunk.py -v
```
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add secretary/ingest.py secretary/tests/test_chunk.py
git commit -m "feat(secretary-ingest): add CHUNK section"
```

---

## Task 6: NOTION section — list_pages + fetch_blocks

**Files:**
- Modify: `secretary/ingest.py` (append NOTION section)
- Create: `secretary/tests/test_notion.py`

- [ ] **Step 1: Write failing tests** in `secretary/tests/test_notion.py`

```python
# secretary/tests/test_notion.py
import os
from unittest.mock import MagicMock, patch, call
import pytest
import ingest


def _make_page(page_id: str, title: str = "Test Page", last_edited: str = "2025-01-01T00:00:00.000Z") -> dict:
    return {
        "id": page_id,
        "object": "page",
        "url": f"https://notion.so/{page_id}",
        "last_edited_time": last_edited,
        "parent": {"type": "workspace", "workspace": True},
        "properties": {
            "Name": {
                "type": "title",
                "title": [{"plain_text": title}],
            }
        },
    }


def test_extract_page_meta_basic():
    page = _make_page("abc", "Hello", "2025-03-01T00:00:00.000Z")
    meta = ingest._extract_page_meta(page)
    assert meta["id"] == "abc"
    assert meta["title"] == "Hello"
    assert meta["last_edited_time"] == "2025-03-01T00:00:00.000Z"
    assert meta["tags"] == []


def test_extract_page_meta_with_tags():
    page = _make_page("abc", "Hello")
    page["properties"]["Tags"] = {
        "type": "multi_select",
        "multi_select": [{"name": "work"}, {"name": "planning"}],
    }
    meta = ingest._extract_page_meta(page)
    assert meta["tags"] == ["work", "planning"]


@patch("ingest._notion_request")
def test_list_pages_search_mode(mock_req):
    os.environ["NOTION_SOURCE_TYPE"] = "search"
    page = _make_page("p1", "Page One")
    mock_req.return_value = {"results": [page], "has_more": False}
    result = ingest.list_pages()
    assert len(result) == 1
    assert result[0]["id"] == "p1"
    assert result[0]["title"] == "Page One"


@patch("ingest._notion_request")
def test_list_pages_database_mode(mock_req):
    os.environ["NOTION_SOURCE_TYPE"] = "database"
    os.environ["NOTION_DATABASE_ID"] = "db123"
    page = _make_page("p2", "Row One")
    mock_req.return_value = {"results": [page], "has_more": False}
    result = ingest.list_pages()
    assert result[0]["id"] == "p2"
    # Restore
    os.environ["NOTION_SOURCE_TYPE"] = "search"


def test_list_pages_database_mode_missing_id():
    os.environ["NOTION_SOURCE_TYPE"] = "database"
    os.environ["NOTION_DATABASE_ID"] = ""
    with pytest.raises(ValueError, match="NOTION_DATABASE_ID"):
        ingest.list_pages()
    os.environ["NOTION_SOURCE_TYPE"] = "search"


@patch("ingest._notion_request")
def test_fetch_blocks_flat(mock_req):
    blocks = [
        {"id": "b1", "type": "paragraph", "paragraph": {"rich_text": [{"plain_text": "hi"}]}, "has_children": False},
    ]
    mock_req.return_value = {"results": blocks, "has_more": False}
    result = ingest.fetch_blocks("page1")
    assert len(result) == 1
    assert result[0]["id"] == "b1"


@patch("ingest._notion_request")
def test_fetch_blocks_recurses_children(mock_req):
    parent_block = {
        "id": "toggle1",
        "type": "toggle",
        "toggle": {"rich_text": [{"plain_text": "Toggle"}]},
        "has_children": True,
    }
    child_block = {
        "id": "para1",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"plain_text": "child content"}]},
        "has_children": False,
    }
    # First call = parent page, second call = toggle children
    mock_req.side_effect = [
        {"results": [parent_block], "has_more": False},
        {"results": [child_block], "has_more": False},
    ]
    result = ingest.fetch_blocks("page1")
    assert result[0]["_children"][0]["id"] == "para1"


@patch("ingest._notion_request")
def test_fetch_blocks_does_not_recurse_child_page(mock_req):
    child_page_block = {
        "id": "cp1",
        "type": "child_page",
        "child_page": {"title": "Sub Page"},
        "has_children": True,
    }
    mock_req.return_value = {"results": [child_page_block], "has_more": False}
    result = ingest.fetch_blocks("page1")
    # child_page blocks should NOT have _children fetched
    assert "_children" not in result[0]
    assert mock_req.call_count == 1
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd secretary && python -m pytest tests/test_notion.py -v
```
Expected: `AttributeError: module 'ingest' has no attribute '_extract_page_meta'`

- [ ] **Step 3: Append NOTION section to `secretary/ingest.py`**

```python
# ── NOTION ────────────────────────────────────────────────────────────────────

from notion_client import Client as _NotionClient
from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception


class _TokenBucket:
    def __init__(self, rate: float = 3.0):
        self._rate = rate
        self._tokens = rate
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self):
        with self._lock:
            now = time.monotonic()
            self._tokens = min(self._rate, self._tokens + (now - self._last) * self._rate)
            self._last = now
            if self._tokens >= 1:
                self._tokens -= 1
                return
        time.sleep(1.0 / self._rate)
        self.acquire()


_bucket = _TokenBucket(rate=3.0)


def _is_rate_limit(exc: Exception) -> bool:
    try:
        from notion_client.errors import APIResponseError
        return isinstance(exc, APIResponseError) and exc.status in (429, 500)
    except ImportError:
        return False


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
    retry=retry_if_exception(_is_rate_limit),
    reraise=True,
)
def _notion_request(fn, *args, **kwargs):
    global _api_call_count
    _bucket.acquire()
    _api_call_count += 1
    return fn(*args, **kwargs)


def _notion_client() -> _NotionClient:
    if not NOTION_TOKEN:
        raise ValueError("NOTION_TOKEN env var is required")
    return _NotionClient(auth=NOTION_TOKEN)


def _extract_page_meta(page: dict) -> dict:
    props = page.get("properties", {})
    title_prop = next((v for v in props.values() if v.get("type") == "title"), None)
    title = (
        "".join(rt["plain_text"] for rt in title_prop.get("title", []))
        if title_prop
        else "Untitled"
    )
    tags: list[str] = []
    for prop in props.values():
        if prop.get("type") == "multi_select":
            tags = [o["name"] for o in prop.get("multi_select", [])]
            break
    parent = page.get("parent", {})
    parent_type = parent.get("type", "")
    parent_id = parent.get(parent_type, "") if parent_type else ""
    return {
        "id": page["id"],
        "title": title,
        "url": page.get("url", ""),
        "last_edited_time": page.get("last_edited_time", ""),
        "parent_id": parent_id,
        "parent_type": parent_type,
        "tags": tags,
    }


def _list_pages_search(client: _NotionClient) -> list[dict]:
    results = []
    cursor = None
    while True:
        kwargs: dict = {"filter": {"property": "object", "value": "page"}, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = _notion_request(client.search, **kwargs)
        for item in resp.get("results", []):
            if item.get("object") == "page":
                results.append(_extract_page_meta(item))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return results


def _list_pages_database(client: _NotionClient, database_id: str) -> list[dict]:
    results = []
    cursor = None
    while True:
        kwargs: dict = {"database_id": database_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = _notion_request(client.databases.query, **kwargs)
        for item in resp.get("results", []):
            results.append(_extract_page_meta(item))
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return results


def _list_pages_from_page(
    client: _NotionClient, root_page_id: str, _visited: Optional[set] = None
) -> list[dict]:
    if _visited is None:
        _visited = set()
    if root_page_id in _visited:
        return []
    _visited.add(root_page_id)
    results = []
    cursor = None
    while True:
        kwargs: dict = {"block_id": root_page_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = _notion_request(client.blocks.children.list, **kwargs)
        for block in resp.get("results", []):
            if block.get("type") == "child_page":
                child_id = block["id"]
                try:
                    page_obj = _notion_request(client.pages.retrieve, page_id=child_id)
                    results.append(_extract_page_meta(page_obj))
                    results.extend(_list_pages_from_page(client, child_id, _visited))
                except Exception as exc:
                    logger.warning(f"Could not retrieve child page {child_id}: {exc}")
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return results


def list_pages() -> list[dict]:
    client = _notion_client()
    if NOTION_SOURCE_TYPE == "search":
        return _list_pages_search(client)
    if NOTION_SOURCE_TYPE == "database":
        if not NOTION_DATABASE_ID:
            raise ValueError("NOTION_DATABASE_ID required for source_type=database")
        return _list_pages_database(client, NOTION_DATABASE_ID)
    if NOTION_SOURCE_TYPE == "page":
        if not NOTION_ROOT_PAGE_ID:
            raise ValueError("NOTION_ROOT_PAGE_ID required for source_type=page")
        return _list_pages_from_page(client, NOTION_ROOT_PAGE_ID)
    raise ValueError(f"Unknown NOTION_SOURCE_TYPE: {NOTION_SOURCE_TYPE!r}")


def fetch_blocks(page_id: str, _depth: int = 0) -> list[dict]:
    if _depth > 5:
        return []
    client = _notion_client()
    blocks: list[dict] = []
    cursor = None
    while True:
        kwargs: dict = {"block_id": page_id, "page_size": 100}
        if cursor:
            kwargs["start_cursor"] = cursor
        resp = _notion_request(client.blocks.children.list, **kwargs)
        for block in resp.get("results", []):
            blocks.append(block)
            if block.get("has_children") and block.get("type") not in ("child_page", "child_database"):
                block["_children"] = fetch_blocks(block["id"], _depth + 1)
        if not resp.get("has_more"):
            break
        cursor = resp.get("next_cursor")
    return blocks
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd secretary && python -m pytest tests/test_notion.py -v
```
Expected: `8 passed`

- [ ] **Step 5: Commit**

```bash
git add secretary/ingest.py secretary/tests/test_notion.py
git commit -m "feat(secretary-ingest): add NOTION section (list_pages + fetch_blocks)"
```

---

## Task 7: EMBED section

**Files:**
- Modify: `secretary/ingest.py` (append EMBED section)
- Create: `secretary/tests/test_embed.py`

- [ ] **Step 1: Write failing tests** in `secretary/tests/test_embed.py`

```python
# secretary/tests/test_embed.py
import numpy as np
from unittest.mock import MagicMock, patch
import ingest


def _mock_model(n: int):
    model = MagicMock()
    model.encode.return_value = {
        "dense_vecs": np.random.rand(n, 1024).astype(np.float32),
        "lexical_weights": [{0: 0.5, 1: 0.3} for _ in range(n)],
    }
    return model


def test_embed_chunks_empty():
    result = ingest.embed_chunks([])
    assert result == {"dense": [], "sparse": []}


@patch("ingest.load_model")
def test_embed_chunks_returns_correct_structure(mock_load):
    mock_load.return_value = _mock_model(3)
    result = ingest.embed_chunks(["text1", "text2", "text3"])
    assert len(result["dense"]) == 3
    assert len(result["sparse"]) == 3
    assert len(result["dense"][0]) == 1024


@patch("ingest.load_model")
def test_embed_chunks_sparse_vector_structure(mock_load):
    mock_load.return_value = _mock_model(1)
    result = ingest.embed_chunks(["hello world"])
    sparse = result["sparse"][0]
    # qdrant_client SparseVector has .indices and .values
    assert hasattr(sparse, "indices")
    assert hasattr(sparse, "values")
    assert all(isinstance(v, float) for v in sparse.values)


@patch("ingest.load_model")
def test_embed_chunks_calls_model_once(mock_load):
    model = _mock_model(2)
    mock_load.return_value = model
    ingest.embed_chunks(["a", "b"])
    model.encode.assert_called_once()
    call_args = model.encode.call_args
    assert call_args[0][0] == ["a", "b"]
    assert call_args[1].get("return_dense") is True
    assert call_args[1].get("return_sparse") is True
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd secretary && python -m pytest tests/test_embed.py -v
```
Expected: `AttributeError: module 'ingest' has no attribute 'embed_chunks'`

- [ ] **Step 3: Append EMBED section to `secretary/ingest.py`**

```python
# ── EMBED ─────────────────────────────────────────────────────────────────────

from qdrant_client.http.models import SparseVector as _SparseVector

_model_instance = None


def load_model():
    global _model_instance
    if _model_instance is None:
        from FlagEmbedding import BGEM3FlagModel
        logger.info("Loading BGEM3FlagModel (first load may take several minutes)...")
        _model_instance = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)
    return _model_instance


def embed_chunks(texts: list[str]) -> dict:
    if not texts:
        return {"dense": [], "sparse": []}
    model = load_model()
    output = model.encode(
        texts,
        return_dense=True,
        return_sparse=True,
        return_colbert_vecs=False,
        batch_size=12,
    )
    dense = output["dense_vecs"].tolist()
    sparse = [
        _SparseVector(
            indices=[int(k) for k in lw.keys()],
            values=[float(v) for v in lw.values()],
        )
        for lw in output["lexical_weights"]
    ]
    return {"dense": dense, "sparse": sparse}
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd secretary && python -m pytest tests/test_embed.py -v
```
Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add secretary/ingest.py secretary/tests/test_embed.py
git commit -m "feat(secretary-ingest): add EMBED section"
```

---

## Task 8: QDRANT section

**Files:**
- Modify: `secretary/ingest.py` (append QDRANT section)
- Create: `secretary/tests/test_qdrant.py`

- [ ] **Step 1: Write failing tests** in `secretary/tests/test_qdrant.py`

```python
# secretary/tests/test_qdrant.py
import numpy as np
from unittest.mock import MagicMock, patch, call
from qdrant_client.http.models import SparseVector
import ingest


def _make_embeddings(n: int) -> dict:
    return {
        "dense": np.random.rand(n, 1024).tolist(),
        "sparse": [SparseVector(indices=[0, 1], values=[0.5, 0.3]) for _ in range(n)],
    }


def _make_page_meta(page_id: str = "p1") -> dict:
    return {
        "id": page_id,
        "title": "Test Page",
        "url": "https://notion.so/test",
        "last_edited_time": "2025-01-01T00:00:00.000Z",
        "parent_id": "",
        "parent_type": "workspace",
        "tags": ["work"],
    }


def _make_chunks(n: int) -> list[dict]:
    return [
        {"text": f"chunk {i}", "breadcrumb": f"Test Page > Section {i}", "chunk_index": i}
        for i in range(n)
    ]


@patch("ingest._qdrant")
def test_ensure_collection_creates_if_absent(mock_qdrant_fn):
    client = MagicMock()
    client.get_collections.return_value.collections = []
    mock_qdrant_fn.return_value = client
    ingest.ensure_collection()
    client.create_collection.assert_called_once()
    call_kwargs = client.create_collection.call_args[1]
    assert call_kwargs["collection_name"] == "secretary_notes"
    assert "dense" in call_kwargs["vectors_config"]
    assert "sparse" in call_kwargs["sparse_vectors_config"]


@patch("ingest._qdrant")
def test_ensure_collection_skips_if_exists(mock_qdrant_fn):
    client = MagicMock()
    existing = MagicMock()
    existing.name = "secretary_notes"
    client.get_collections.return_value.collections = [existing]
    mock_qdrant_fn.return_value = client
    ingest.ensure_collection()
    client.create_collection.assert_not_called()


@patch("ingest._qdrant")
def test_delete_page_points(mock_qdrant_fn):
    client = MagicMock()
    mock_qdrant_fn.return_value = client
    ingest.delete_page_points("page123")
    client.delete.assert_called_once()
    call_kwargs = client.delete.call_args[1]
    assert call_kwargs["collection_name"] == "secretary_notes"


@patch("ingest._qdrant")
def test_upsert_chunks_sends_correct_count(mock_qdrant_fn):
    client = MagicMock()
    mock_qdrant_fn.return_value = client
    chunks = _make_chunks(3)
    embeddings = _make_embeddings(3)
    ingest.upsert_chunks(_make_page_meta(), chunks, embeddings)
    client.upsert.assert_called_once()
    points = client.upsert.call_args[1]["points"]
    assert len(points) == 3


@patch("ingest._qdrant")
def test_upsert_chunks_payload_fields(mock_qdrant_fn):
    client = MagicMock()
    mock_qdrant_fn.return_value = client
    chunks = _make_chunks(1)
    embeddings = _make_embeddings(1)
    meta = _make_page_meta("abc123")
    ingest.upsert_chunks(meta, chunks, embeddings)
    point = client.upsert.call_args[1]["points"][0]
    assert point.payload["source"] == "notion"
    assert point.payload["page_id"] == "abc123"
    assert point.payload["tags"] == ["work"]
    assert "dense" in point.vector
    assert "sparse" in point.vector


@patch("ingest._qdrant")
def test_upsert_chunks_dry_run_skips_write(mock_qdrant_fn):
    client = MagicMock()
    mock_qdrant_fn.return_value = client
    ingest.upsert_chunks(_make_page_meta(), _make_chunks(2), _make_embeddings(2), dry_run=True)
    client.upsert.assert_not_called()


@patch("ingest._qdrant")
def test_upsert_chunks_deterministic_id(mock_qdrant_fn):
    client = MagicMock()
    mock_qdrant_fn.return_value = client
    chunks = _make_chunks(1)
    embeddings = _make_embeddings(1)
    ingest.upsert_chunks(_make_page_meta("pid"), chunks, embeddings)
    point = client.upsert.call_args[1]["points"][0]
    import uuid
    expected_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "pid0"))
    assert point.id == expected_id
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd secretary && python -m pytest tests/test_qdrant.py -v
```
Expected: `AttributeError: module 'ingest' has no attribute 'ensure_collection'`

- [ ] **Step 3: Append QDRANT section to `secretary/ingest.py`**

```python
# ── QDRANT ────────────────────────────────────────────────────────────────────

from qdrant_client import QdrantClient as _QdrantClient
from qdrant_client.http.models import (
    VectorParams,
    Distance,
    SparseVectorParams,
    SparseIndexParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)


def _qdrant() -> _QdrantClient:
    return _QdrantClient(url=QDRANT_URL)


def ensure_collection():
    client = _qdrant()
    existing_names = [c.name for c in client.get_collections().collections]
    if COLLECTION_NAME in existing_names:
        return
    client.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={"dense": VectorParams(size=1024, distance=Distance.COSINE)},
        sparse_vectors_config={
            "sparse": SparseVectorParams(index=SparseIndexParams(on_disk=False))
        },
    )
    logger.info(f"Created collection '{COLLECTION_NAME}'")


def delete_page_points(page_id: str):
    client = _qdrant()
    client.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[FieldCondition(key="page_id", match=MatchValue(value=page_id))]
        ),
    )


def upsert_chunks(
    page_meta: dict,
    chunks: list[dict],
    embeddings: dict,
    dry_run: bool = False,
):
    if dry_run:
        return
    client = _qdrant()
    points = []
    for chunk, dense_vec, sparse_vec in zip(
        chunks, embeddings["dense"], embeddings["sparse"]
    ):
        point_id = str(
            uuid.uuid5(uuid.NAMESPACE_DNS, page_meta["id"] + str(chunk["chunk_index"]))
        )
        payload = {
            "source": "notion",
            "page_id": page_meta["id"],
            "page_url": page_meta["url"],
            "page_title": page_meta["title"],
            "breadcrumb": chunk["breadcrumb"],
            "text": chunk["text"],
            "chunk_index": chunk["chunk_index"],
            "last_edited_time": page_meta["last_edited_time"],
            "parent_id": page_meta.get("parent_id", ""),
            "parent_type": page_meta.get("parent_type", ""),
            "tags": page_meta.get("tags", []),
        }
        points.append(
            PointStruct(
                id=point_id,
                vector={"dense": dense_vec, "sparse": sparse_vec},
                payload=payload,
            )
        )
    client.upsert(collection_name=COLLECTION_NAME, points=points)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd secretary && python -m pytest tests/test_qdrant.py -v
```
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add secretary/ingest.py secretary/tests/test_qdrant.py
git commit -m "feat(secretary-ingest): add QDRANT section"
```

---

## Task 9: SYNC section

**Files:**
- Modify: `secretary/ingest.py` (append SYNC section)
- Create: `secretary/tests/test_sync.py`

- [ ] **Step 1: Write failing tests** in `secretary/tests/test_sync.py`

```python
# secretary/tests/test_sync.py
import sqlite3
import os
from unittest.mock import MagicMock, patch
from qdrant_client.http.models import SparseVector
import ingest


def _conn():
    return ingest.init_db(":memory:")


def _page(page_id: str = "p1", title: str = "Page", ts: str = "2025-01-01T00:00:00.000Z") -> dict:
    return {
        "id": page_id, "title": title, "url": "https://notion.so/p1",
        "last_edited_time": ts, "parent_id": "", "parent_type": "workspace", "tags": [],
    }


def _mock_embeddings(n: int) -> dict:
    import numpy as np
    return {
        "dense": [[0.1] * 1024 for _ in range(n)],
        "sparse": [SparseVector(indices=[0], values=[0.5]) for _ in range(n)],
    }


@patch("ingest.upsert_chunks")
@patch("ingest.embed_chunks")
@patch("ingest.chunk_markdown")
@patch("ingest.blocks_to_markdown")
@patch("ingest.fetch_blocks")
def test_sync_page_new(mock_fetch, mock_md, mock_chunk, mock_embed, mock_upsert):
    conn = _conn()
    mock_fetch.return_value = []
    mock_md.return_value = "## Section\nContent here."
    mock_chunk.return_value = [{"text": "Content here.", "breadcrumb": "Page > Section", "chunk_index": 0}]
    mock_embed.return_value = _mock_embeddings(1)
    result = ingest.sync_page(_page(), conn)
    assert result["status"] == "updated"
    assert result["chunks"] == 1
    mock_upsert.assert_called_once()
    assert ingest.get_state(conn, "p1") is not None


@patch("ingest.upsert_chunks")
@patch("ingest.embed_chunks")
@patch("ingest.chunk_markdown")
@patch("ingest.blocks_to_markdown")
@patch("ingest.fetch_blocks")
def test_sync_page_unchanged_skips(mock_fetch, mock_md, mock_chunk, mock_embed, mock_upsert):
    conn = _conn()
    ingest.upsert_state(conn, "p1", "2025-01-01T00:00:00.000Z", 3)
    result = ingest.sync_page(_page("p1", ts="2025-01-01T00:00:00.000Z"), conn)
    assert result["status"] == "skipped"
    mock_fetch.assert_not_called()
    mock_upsert.assert_not_called()


@patch("ingest.delete_page_points")
@patch("ingest.upsert_chunks")
@patch("ingest.embed_chunks")
@patch("ingest.chunk_markdown")
@patch("ingest.blocks_to_markdown")
@patch("ingest.fetch_blocks")
def test_sync_page_changed_deletes_old_points(mock_fetch, mock_md, mock_chunk, mock_embed, mock_upsert, mock_delete):
    conn = _conn()
    ingest.upsert_state(conn, "p1", "2025-01-01T00:00:00.000Z", 3)
    mock_fetch.return_value = []
    mock_md.return_value = "## New\nUpdated content."
    mock_chunk.return_value = [{"text": "Updated content.", "breadcrumb": "Page > New", "chunk_index": 0}]
    mock_embed.return_value = _mock_embeddings(1)
    result = ingest.sync_page(_page("p1", ts="2025-06-01T00:00:00.000Z"), conn)
    assert result["status"] == "updated"
    mock_delete.assert_called_once_with("p1")


@patch("ingest.upsert_chunks")
@patch("ingest.embed_chunks")
@patch("ingest.chunk_markdown")
@patch("ingest.blocks_to_markdown")
@patch("ingest.fetch_blocks")
def test_sync_page_empty_skips(mock_fetch, mock_md, mock_chunk, mock_embed, mock_upsert):
    conn = _conn()
    mock_fetch.return_value = []
    mock_md.return_value = ""
    result = ingest.sync_page(_page(), conn)
    assert result["status"] == "skipped"
    mock_upsert.assert_not_called()


@patch("ingest.fetch_blocks")
def test_sync_page_error_returns_error_status(mock_fetch):
    conn = _conn()
    mock_fetch.side_effect = RuntimeError("network failure")
    result = ingest.sync_page(_page(), conn)
    assert result["status"] == "error"
    assert "network failure" in result["error"]


@patch("ingest.upsert_chunks")
@patch("ingest.embed_chunks")
@patch("ingest.chunk_markdown")
@patch("ingest.blocks_to_markdown")
@patch("ingest.fetch_blocks")
def test_sync_page_dry_run_no_writes(mock_fetch, mock_md, mock_chunk, mock_embed, mock_upsert):
    conn = _conn()
    mock_fetch.return_value = []
    mock_md.return_value = "## Section\nContent."
    mock_chunk.return_value = [{"text": "Content.", "breadcrumb": "Page > Section", "chunk_index": 0}]
    mock_embed.return_value = _mock_embeddings(1)
    ingest.sync_page(_page(), conn, dry_run=True)
    mock_upsert.assert_called_once()
    # upsert_chunks is called with dry_run=True — Qdrant write is skipped inside it
    assert mock_upsert.call_args[1].get("dry_run") is True
    # state DB should NOT be updated
    assert ingest.get_state(conn, "p1") is None


@patch("ingest.sync_page")
@patch("ingest.delete_page_points")
@patch("ingest.delete_state")
@patch("ingest.ensure_collection")
@patch("ingest.list_pages")
@patch("ingest.init_db")
def test_run_incremental_deletes_removed_pages(
    mock_db, mock_list, mock_ensure, mock_del_state, mock_del_points, mock_sync
):
    conn = _conn()
    ingest.upsert_state(conn, "old_page", "2025-01-01T00:00:00.000Z", 2)
    mock_db.return_value = conn
    mock_list.return_value = []  # Notion returns no pages → old_page was deleted
    mock_sync.return_value = {"status": "skipped", "chunks": 0}
    ingest.run_incremental()
    mock_del_points.assert_called_once_with("old_page")
    mock_del_state.assert_called_once_with(conn, "old_page")
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd secretary && python -m pytest tests/test_sync.py -v
```
Expected: `AttributeError: module 'ingest' has no attribute 'sync_page'`

- [ ] **Step 3: Append SYNC section to `secretary/ingest.py`**

```python
# ── SYNC ──────────────────────────────────────────────────────────────────────

import time as _time


def _print_summary(stats: dict, total: int, elapsed: float):
    print("\n" + "─" * 48)
    print(f"Pages processed:   {total}")
    print(f"  ✓ Updated:       {stats['updated']}  ({stats['chunks']} chunks created/updated)")
    print(f"  ↷ Skipped:       {stats['skipped']}")
    print(f"  ✗ Errors:        {stats['errors']}")
    print(f"  🗑 Deleted:       {stats['deleted']}")
    print(f"Notion API calls:  {_api_call_count}")
    print(f"Total time:        {elapsed:.1f}s")
    print("─" * 48 + "\n")


def sync_page(
    page_meta: dict,
    conn: sqlite3.Connection,
    dry_run: bool = False,
) -> dict:
    page_id = page_meta["id"]
    title = page_meta["title"]

    state = get_state(conn, page_id)
    if state and state["last_edited_time"] == page_meta["last_edited_time"]:
        logger.info(f"↷ Skipped (unchanged): {title}")
        return {"status": "skipped", "chunks": 0}

    try:
        blocks = fetch_blocks(page_id)
        markdown = blocks_to_markdown(blocks)

        if not markdown.strip():
            logger.info(f"↷ Skipped (empty): {title}")
            return {"status": "skipped", "chunks": 0}

        chunks = chunk_markdown(markdown, title)
        if not chunks:
            logger.info(f"↷ Skipped (no chunks): {title}")
            return {"status": "skipped", "chunks": 0}

        texts = [c["text"] for c in chunks]
        embeddings = embed_chunks(texts)

        if state and not dry_run:
            delete_page_points(page_id)

        upsert_chunks(page_meta, chunks, embeddings, dry_run=dry_run)

        if not dry_run:
            upsert_state(conn, page_id, page_meta["last_edited_time"], len(chunks))

        logger.info(f"✓ Updated: {title} ({len(chunks)} chunks)")
        return {"status": "updated", "chunks": len(chunks)}

    except Exception as exc:
        logger.error(f"✗ Error: {title} — {exc}")
        return {"status": "error", "chunks": 0, "error": str(exc)}


def run_incremental(dry_run: bool = False):
    global _api_call_count
    _api_call_count = 0
    t0 = _time.monotonic()
    conn = init_db(STATE_DB)
    ensure_collection()

    notion_pages = list_pages()
    notion_ids = {p["id"] for p in notion_pages}
    known_pages = list_all_pages(conn)

    stats = {"updated": 0, "skipped": 0, "errors": 0, "chunks": 0, "deleted": 0}

    for page_id in set(known_pages.keys()) - notion_ids:
        logger.info(f"🗑 Deleted: {page_id}")
        if not dry_run:
            delete_page_points(page_id)
            delete_state(conn, page_id)
        stats["deleted"] += 1

    for page_meta in notion_pages:
        result = sync_page(page_meta, conn, dry_run=dry_run)
        stats[result["status"]] += 1
        stats["chunks"] += result.get("chunks", 0)

    _print_summary(stats, len(notion_pages), _time.monotonic() - t0)


def run_full(dry_run: bool = False):
    global _api_call_count
    _api_call_count = 0
    t0 = _time.monotonic()
    conn = init_db(STATE_DB)
    ensure_collection()

    notion_pages = list_pages()
    stats = {"updated": 0, "skipped": 0, "errors": 0, "chunks": 0, "deleted": 0}

    for page_meta in notion_pages:
        if not dry_run:
            state = get_state(conn, page_meta["id"])
            if state:
                delete_page_points(page_meta["id"])
                delete_state(conn, page_meta["id"])
        result = sync_page(page_meta, conn, dry_run=dry_run)
        stats[result["status"]] += 1
        stats["chunks"] += result.get("chunks", 0)

    _print_summary(stats, len(notion_pages), _time.monotonic() - t0)


def run_single(page_id: str, dry_run: bool = False):
    global _api_call_count
    _api_call_count = 0
    t0 = _time.monotonic()
    conn = init_db(STATE_DB)
    ensure_collection()

    client = _notion_client()
    page_obj = _notion_request(client.pages.retrieve, page_id=page_id)
    page_meta = _extract_page_meta(page_obj)

    stats = {"updated": 0, "skipped": 0, "errors": 0, "chunks": 0, "deleted": 0}
    result = sync_page(page_meta, conn, dry_run=dry_run)
    stats[result["status"]] += 1
    stats["chunks"] += result.get("chunks", 0)
    _print_summary(stats, 1, _time.monotonic() - t0)
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
cd secretary && python -m pytest tests/test_sync.py -v
```
Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add secretary/ingest.py secretary/tests/test_sync.py
git commit -m "feat(secretary-ingest): add SYNC section"
```

---

## Task 10: CLI section

**Files:**
- Modify: `secretary/ingest.py` (append CLI section)
- Create: `secretary/tests/test_cli.py`

- [ ] **Step 1: Write failing tests** in `secretary/tests/test_cli.py`

```python
# secretary/tests/test_cli.py
from unittest.mock import patch, call
import sys
import ingest


@patch("ingest.run_incremental")
def test_cli_default_runs_incremental(mock_run, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ingest.py"])
    ingest.main()
    mock_run.assert_called_once_with(dry_run=False)


@patch("ingest.run_full")
def test_cli_full_flag(mock_run, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--full"])
    ingest.main()
    mock_run.assert_called_once_with(dry_run=False)


@patch("ingest.run_single")
def test_cli_page_flag(mock_run, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--page", "abc123"])
    ingest.main()
    mock_run.assert_called_once_with("abc123", dry_run=False)


@patch("ingest.run_incremental")
def test_cli_dry_run_flag(mock_run, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--dry-run"])
    ingest.main()
    mock_run.assert_called_once_with(dry_run=True)


@patch("ingest.run_full")
def test_cli_full_dry_run(mock_run, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["ingest.py", "--full", "--dry-run"])
    ingest.main()
    mock_run.assert_called_once_with(dry_run=True)
```

- [ ] **Step 2: Run to confirm failure**

```bash
cd secretary && python -m pytest tests/test_cli.py -v
```
Expected: `AttributeError: module 'ingest' has no attribute 'main'`

- [ ] **Step 3: Append CLI section to `secretary/ingest.py`**

```python
# ── CLI ───────────────────────────────────────────────────────────────────────

import argparse


def main():
    parser = argparse.ArgumentParser(description="Notion → Qdrant hybrid-search ingest")
    parser.add_argument("--full", action="store_true", help="Re-ingest all pages, ignore state")
    parser.add_argument("--page", metavar="PAGE_ID", help="Ingest a single Notion page by ID")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    if args.page:
        run_single(args.page, dry_run=args.dry_run)
    elif args.full:
        run_full(dry_run=args.dry_run)
    else:
        run_incremental(dry_run=args.dry_run)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s")
    main()
```

- [ ] **Step 4: Run all tests to confirm full suite passes**

```bash
cd secretary && python -m pytest tests/ -v
```
Expected: all tests pass (no failures)

- [ ] **Step 5: Commit**

```bash
git add secretary/ingest.py secretary/tests/test_cli.py
git commit -m "feat(secretary-ingest): add CLI section — ingest.py complete"
```

---

## Task 11: Docker compose update + README

**Files:**
- Modify: `secretary/docker-compose.yml`
- Create: `secretary/README.md`

- [ ] **Step 1: Add `secretary-ingest` service and `hf_cache` volume to `secretary/docker-compose.yml`**

Append to the existing `services:` block and add a top-level `volumes:` key:

```yaml
  secretary-ingest:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: secretary-ingest
    depends_on:
      - qdrant
    volumes:
      - ./ingest_data:/data
      - hf_cache:/hf_cache
    env_file: .env
    restart: "no"

volumes:
  hf_cache:
```

The full file after edit:

```yaml
services:
  qdrant:
    image: qdrant/qdrant:latest
    container_name: secretary-qdrant
    restart: unless-stopped
    ports:
      - "6333:6333"
    volumes:
      - ./qdrant_storage:/qdrant/storage

  ollama:
    image: ollama/ollama:latest
    container_name: secretary-ollama
    restart: unless-stopped
    ports:
      - "11434:11434"
    volumes:
      - ./ollama_data:/root/.ollama

  n8n:
    image: n8nio/n8n:latest
    container_name: secretary-n8n
    user: root
    restart: unless-stopped
    ports:
      - "5678:5678"
    environment:
      - N8N_BASIC_AUTH_ACTIVE=true
      - N8N_BASIC_AUTH_USER=${N8N_BASIC_AUTH_USER}
      - N8N_BASIC_AUTH_PASSWORD=${N8N_BASIC_AUTH_PASSWORD}
      - WEBHOOK_URL=${N8N_WEBHOOK_URL}
    volumes:
      - ./n8n_data:/home/node/.n8n

  secretary-ingest:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: secretary-ingest
    depends_on:
      - qdrant
    volumes:
      - ./ingest_data:/data
      - hf_cache:/hf_cache
    env_file: .env
    restart: "no"

volumes:
  hf_cache:
```

- [ ] **Step 2: Create `secretary/README.md`**

```markdown
# secretary-ingest

Syncs Notion pages into a Qdrant collection with hybrid search (dense 1024d + sparse via BGE-M3).

## Quick start

1. Copy env template and fill values:
   ```bash
   cp secretary/.env.example secretary/.env
   ```

2. Build and run incremental sync:
   ```bash
   docker compose -f secretary/docker-compose.yml run --rm secretary-ingest
   ```

3. Full re-ingest (ignore state):
   ```bash
   docker compose -f secretary/docker-compose.yml run --rm secretary-ingest python ingest.py --full
   ```

4. Dry-run (preview only):
   ```bash
   docker compose -f secretary/docker-compose.yml run --rm secretary-ingest python ingest.py --dry-run
   ```

5. Single page:
   ```bash
   docker compose -f secretary/docker-compose.yml run --rm secretary-ingest python ingest.py --page <NOTION_PAGE_ID>
   ```

## Creating a Notion Integration

1. Go to https://www.notion.so/profile/integrations → **New integration**
2. Name it (e.g. "secretary-ingest"), select your workspace, set type = Internal
3. Copy the **Internal Integration Secret** → set as `NOTION_TOKEN` in `.env`
4. Open each page/database you want to index → click **...** → **Connections** → add your integration

## Source modes

| `NOTION_SOURCE_TYPE` | What it indexes | Required env var |
|---|---|---|
| `search` (default) | All pages the integration can access | — |
| `database` | Rows of one specific database | `NOTION_DATABASE_ID` |
| `page` | All child pages under a root page | `NOTION_ROOT_PAGE_ID` |

## n8n trigger (scheduled sync)

In n8n, add a **Schedule Trigger** + **Execute Command** node:
```
docker compose -f /volume2/docker/secretary/docker-compose.yml run --rm secretary-ingest
```

## First run note

BGE-M3 (~2GB) is downloaded on first run and cached in the `hf_cache` Docker volume. Subsequent runs start in seconds.

## State database

Incremental state is stored at `/data/ingest_state.db` (SQLite). Reset it to force a full re-ingest without `--full`:
```bash
docker compose -f secretary/docker-compose.yml run --rm secretary-ingest python -c "import os; os.remove('/data/ingest_state.db')"
```
```

- [ ] **Step 3: Commit**

```bash
git add secretary/docker-compose.yml secretary/README.md
git commit -m "feat(secretary-ingest): add docker-compose service + README"
```

---

## Task 12: Smoke test — build image locally

**Files:** (none modified)

- [ ] **Step 1: Build the Docker image**

```bash
cd secretary && docker build -t secretary-ingest:local .
```
Expected: `Successfully built ...` (no errors). First build takes several minutes — pip installing FlagEmbedding.

- [ ] **Step 2: Verify `--help` works inside the image**

```bash
docker run --rm secretary-ingest:local python ingest.py --help
```
Expected output:
```
usage: ingest.py [-h] [--full] [--page PAGE_ID] [--dry-run]

Notion → Qdrant hybrid-search ingest

options:
  -h, --help       show this help message and exit
  --full           Re-ingest all pages, ignore state
  --page PAGE_ID   Ingest a single Notion page by ID
  --dry-run        Show changes without writing
```

- [ ] **Step 3: Run full test suite one final time**

```bash
cd secretary && python -m pytest tests/ -v --tb=short
```
Expected: all tests pass.

- [ ] **Step 4: Commit smoke test confirmation** (no code change — just mark done)

```bash
git log --oneline -6
```
Verify all feature commits are present.

---

## Post-implementation: Update stack notes

After implementation is complete, update the secretary stack notes as required by CLAUDE.md:

- Write a summary entry to `secretary/.notes/daily_log.md` (create the file if absent)
- Create/update `secretary/.notes/00_INDEX.md` with the new service details

---

*Spec: `docs/superpowers/specs/2026-05-27-notion-qdrant-ingest-design.md`*
