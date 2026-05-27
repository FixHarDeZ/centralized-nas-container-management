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

    # Check if first section is a preamble (doesn't start with ##)
    has_preamble = raw_sections and raw_sections[0].strip() and not raw_sections[0].strip().startswith("## ")

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
            has_subsections = True
        else:
            subsections = [section]
            has_subsections = False

        for subsection in subsections:
            subsection = subsection.strip()
            if not subsection:
                continue

            sub_lines = subsection.split("\n", 1)
            sub_title = sub_lines[0][4:].strip() if sub_lines[0].startswith("### ") else ""

            breadcrumb = build_breadcrumb(page_title, section_title, sub_title)

            # Merge if: < 50 tokens AND chunks exist AND (has subsections OR no preamble)
            # This allows merging of tiny ## sections only if there's no preamble
            should_merge = (
                _count_tokens(subsection) < 50
                and chunks
                and (has_subsections or not has_preamble)
            )

            if should_merge:
                chunks[-1]["text"] += "\n" + subsection
            else:
                chunks.append({
                    "text": subsection,
                    "breadcrumb": breadcrumb,
                    "chunk_index": chunk_index,
                })
                chunk_index += 1

    return chunks


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
        body: dict = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        resp = _notion_request(
            client.request,
            path=f"databases/{database_id}/query",
            method="POST",
            body=body,
        )
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
