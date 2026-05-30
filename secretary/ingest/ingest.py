import argparse
import logging
import os
import sqlite3
import time
import uuid
from typing import Optional

import tiktoken
from FlagEmbedding import BGEM3FlagModel
from notion_client import Client as NotionClient
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    SparseIndexParams,
    SparseVector,
    SparseVectorParams,
    VectorParams,
)
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_fixed

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

QDRANT_URL = os.environ["QDRANT_URL"]
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "secretary_notes")
STATE_DB = os.environ.get("STATE_DB", "/data/ingest_state.db")
NOTION_TOKEN = os.environ["SECRETARY_NOTION_TOKEN"]
NOTION_SOURCE_TYPE = os.environ.get("NOTION_SOURCE_TYPE", "search")
NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")
NOTION_ROOT_PAGE_ID = os.environ.get("NOTION_ROOT_PAGE_ID", "")

# Fixed namespace so UUID5 is stable across runs; changing this orphans all existing points
_UUID_NS = uuid.UUID("b3d1c2a0-4f5e-6789-abcd-ef0123456789")

TOKENIZER = tiktoken.get_encoding("cl100k_base")

embed_model = BGEM3FlagModel("BAAI/bge-m3")

notion = NotionClient(auth=NOTION_TOKEN)
qdrant = QdrantClient(url=QDRANT_URL)


# ---------------------------------------------------------------------------
# Qdrant helpers
# ---------------------------------------------------------------------------

def ensure_collection() -> None:
    existing = [c.name for c in qdrant.get_collections().collections]
    if COLLECTION_NAME in existing:
        return
    qdrant.create_collection(
        collection_name=COLLECTION_NAME,
        vectors_config={
            "dense": VectorParams(size=1024, distance=Distance.COSINE),
        },
        sparse_vectors_config={
            "sparse": SparseVectorParams(index=SparseIndexParams()),
        },
    )
    log.info("Created collection: %s", COLLECTION_NAME)


def delete_page_points(page_id: str) -> None:
    from qdrant_client.models import Filter, FieldCondition, MatchValue
    qdrant.delete(
        collection_name=COLLECTION_NAME,
        points_selector=Filter(
            must=[FieldCondition(key="page_id", match=MatchValue(value=page_id))]
        ),
    )


# ---------------------------------------------------------------------------
# State DB helpers
# ---------------------------------------------------------------------------

def open_state_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(STATE_DB), exist_ok=True)
    conn = sqlite3.connect(STATE_DB)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS page_state (
            page_id TEXT PRIMARY KEY,
            last_edited_time TEXT,
            chunk_count INTEGER
        )
        """
    )
    conn.commit()
    return conn


def get_stored_state(conn: sqlite3.Connection, page_id: str) -> Optional[tuple]:
    row = conn.execute(
        "SELECT last_edited_time, chunk_count FROM page_state WHERE page_id=?",
        (page_id,),
    ).fetchone()
    return row


def upsert_state(conn: sqlite3.Connection, page_id: str, last_edited: str, chunk_count: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO page_state (page_id, last_edited_time, chunk_count) VALUES (?,?,?)",
        (page_id, last_edited, chunk_count),
    )
    conn.commit()


def delete_state(conn: sqlite3.Connection, page_id: str) -> None:
    conn.execute("DELETE FROM page_state WHERE page_id=?", (page_id,))
    conn.commit()


def all_stored_page_ids(conn: sqlite3.Connection) -> set:
    rows = conn.execute("SELECT page_id FROM page_state").fetchall()
    return {r[0] for r in rows}


# ---------------------------------------------------------------------------
# Notion fetch helpers (with rate limiting + retry)
# ---------------------------------------------------------------------------

def _sleep_rate():
    time.sleep(0.34)


def _is_retryable(exc: BaseException) -> bool:
    # Only retry on rate-limit or transient server errors, not auth/logic failures
    status = getattr(exc, "status", None) or getattr(exc, "code", None)
    return status in (429, 500, 502, 503, 504)


_retry_notion = retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
)


@_retry_notion
def _notion_search(cursor: Optional[str]) -> dict:
    kwargs = {"filter": {"property": "object", "value": "page"}, "page_size": 100}
    if cursor:
        kwargs["start_cursor"] = cursor
    _sleep_rate()
    return notion.search(**kwargs)


@_retry_notion
def _notion_db_query(db_id: str, cursor: Optional[str]) -> dict:
    kwargs = {"database_id": db_id, "page_size": 100}
    if cursor:
        kwargs["start_cursor"] = cursor
    _sleep_rate()
    return notion.databases.query(**kwargs)


@_retry_notion
def _notion_blocks_list(block_id: str, cursor: Optional[str]) -> dict:
    kwargs = {"block_id": block_id, "page_size": 100}
    if cursor:
        kwargs["start_cursor"] = cursor
    _sleep_rate()
    return notion.blocks.children.list(**kwargs)


@_retry_notion
def _notion_page_children(page_id: str, cursor: Optional[str]) -> dict:
    kwargs = {"block_id": page_id, "page_size": 100}
    if cursor:
        kwargs["start_cursor"] = cursor
    _sleep_rate()
    return notion.blocks.children.list(**kwargs)


@_retry_notion
def _notion_page_retrieve(page_id: str) -> dict:
    _sleep_rate()
    return notion.pages.retrieve(page_id=page_id)


def fetch_all_blocks(block_id: str) -> list:
    blocks = []
    cursor = None
    while True:
        resp = _notion_blocks_list(block_id, cursor)
        blocks.extend(resp["results"])
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]
    for block in blocks:
        if block.get("has_children") and block["type"] not in ("child_page", "child_database"):
            block["_children"] = fetch_all_blocks(block["id"])
    return blocks


def list_source_pages() -> list[dict]:
    """Return list of page objects depending on NOTION_SOURCE_TYPE."""
    pages = []
    if NOTION_SOURCE_TYPE == "search":
        cursor = None
        while True:
            resp = _notion_search(cursor)
            pages.extend(resp["results"])
            if not resp.get("has_more"):
                break
            cursor = resp["next_cursor"]

    elif NOTION_SOURCE_TYPE == "database":
        cursor = None
        while True:
            resp = _notion_db_query(NOTION_DATABASE_ID, cursor)
            pages.extend(resp["results"])
            if not resp.get("has_more"):
                break
            cursor = resp["next_cursor"]

    elif NOTION_SOURCE_TYPE == "page":
        pages = _collect_child_pages(NOTION_ROOT_PAGE_ID)

    return [p for p in pages if p.get("object") == "page"]


def _collect_child_pages(root_id: str) -> list[dict]:
    result = []
    cursor = None
    while True:
        resp = _notion_page_children(root_id, cursor)
        for block in resp["results"]:
            if block["type"] == "child_page":
                # Retrieve full page object so properties/url/tags are available
                full_page = _notion_page_retrieve(block["id"])
                result.append(full_page)
                result.extend(_collect_child_pages(block["id"]))
        if not resp.get("has_more"):
            break
        cursor = resp["next_cursor"]
    return result


# ---------------------------------------------------------------------------
# Page metadata extraction
# ---------------------------------------------------------------------------

def get_page_title(page: dict) -> str:
    props = page.get("properties", {})
    for key in ("Name", "Title", "title"):
        prop = props.get(key)
        if prop and prop.get("type") == "title":
            parts = prop["title"]
            return "".join(p.get("plain_text", "") for p in parts).strip()
    if "_title" in page:
        return page["_title"]
    return page.get("id", "Untitled")


def get_page_tags(page: dict) -> list[str]:
    props = page.get("properties", {})
    tags = []
    for prop in props.values():
        if prop.get("type") == "multi_select":
            tags.extend(o["name"] for o in prop.get("multi_select", []))
    return tags


def get_page_url(page: dict) -> str:
    return page.get("url", "")


# ---------------------------------------------------------------------------
# Block → Markdown converter
# ---------------------------------------------------------------------------

def _rich_text_to_str(rich_texts: list) -> str:
    return "".join(rt.get("plain_text", "") for rt in rich_texts)


def _block_to_md(block: dict, depth: int = 0) -> str:
    btype = block["type"]
    content = block.get(btype, {})
    children = block.get("_children", [])

    if btype == "heading_1":
        return "# " + _rich_text_to_str(content.get("rich_text", [])) + "\n"
    if btype == "heading_2":
        return "## " + _rich_text_to_str(content.get("rich_text", [])) + "\n"
    if btype == "heading_3":
        return "### " + _rich_text_to_str(content.get("rich_text", [])) + "\n"
    if btype == "paragraph":
        text = _rich_text_to_str(content.get("rich_text", []))
        child_md = _blocks_to_md(children, depth)
        return (text + "\n" if text else "") + child_md
    if btype == "bulleted_list_item":
        prefix = "  " * depth + "- "
        text = _rich_text_to_str(content.get("rich_text", []))
        child_md = _blocks_to_md(children, depth + 1)
        return prefix + text + "\n" + child_md
    if btype == "numbered_list_item":
        prefix = "  " * depth + "1. "
        text = _rich_text_to_str(content.get("rich_text", []))
        child_md = _blocks_to_md(children, depth + 1)
        return prefix + text + "\n" + child_md
    if btype == "to_do":
        checked = content.get("checked", False)
        box = "[x]" if checked else "[ ]"
        text = _rich_text_to_str(content.get("rich_text", []))
        return f"- {box} {text}\n"
    if btype == "quote":
        text = _rich_text_to_str(content.get("rich_text", []))
        return "> " + text + "\n"
    if btype == "callout":
        text = _rich_text_to_str(content.get("rich_text", []))
        child_md = _blocks_to_md(children, depth)
        return "> " + text + "\n" + child_md
    if btype == "code":
        lang = content.get("language", "")
        text = _rich_text_to_str(content.get("rich_text", []))
        return f"```{lang}\n{text}\n```\n"
    if btype == "table":
        return _table_to_md(block)
    if btype == "toggle":
        title = _rich_text_to_str(content.get("rich_text", []))
        child_md = _blocks_to_md(children, depth)
        return f"## {title}\n{child_md}"
    if btype in ("bookmark", "link_preview"):
        url = content.get("url", "")
        caption = _rich_text_to_str(content.get("caption", []))
        label = caption or url
        return f"[{label}]({url})\n"
    if btype == "image":
        img_content = content.get("external") or content.get("file") or {}
        url = img_content.get("url", "")
        return f"![]({url})\n"
    if btype == "child_page":
        return ""
    if btype in ("column_list", "column"):
        return _blocks_to_md(children, depth)
    if btype == "synced_block":
        synced_from = content.get("synced_from")
        if synced_from is None:
            return _blocks_to_md(children, depth)
        return _blocks_to_md(children, depth)
    if btype == "divider":
        return "---\n"

    # Unknown block types: attempt to extract any rich_text, else skip
    rich = content.get("rich_text", [])
    if rich:
        return _rich_text_to_str(rich) + "\n"
    return ""


def _blocks_to_md(blocks: list, depth: int = 0) -> str:
    return "".join(_block_to_md(b, depth) for b in blocks)


def _table_to_md(block: dict) -> str:
    rows = block.get("_children", [])
    if not rows:
        return ""
    lines = []
    for i, row in enumerate(rows):
        cells = row.get("table_row", {}).get("cells", [])
        cell_texts = [_rich_text_to_str(c) for c in cells]
        lines.append("| " + " | ".join(cell_texts) + " |")
        if i == 0:
            lines.append("| " + " | ".join(["---"] * len(cell_texts)) + " |")
    return "\n".join(lines) + "\n"


def page_to_markdown(page_id: str) -> str:
    blocks = fetch_all_blocks(page_id)
    return _blocks_to_md(blocks)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _count_tokens(text: str) -> int:
    return len(TOKENIZER.encode(text))


def _split_by_paragraph(text: str, max_tokens: int = 500) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks = []
    current = []
    current_tokens = 0
    for para in paragraphs:
        t = _count_tokens(para)
        if current_tokens + t > max_tokens and current:
            chunks.append("\n\n".join(current))
            current = [para]
            current_tokens = t
        else:
            current.append(para)
            current_tokens += t
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _first_h3(text: str) -> str:
    """Extract the first ### heading from text, if any."""
    import re
    m = re.search(r"^### (.+)$", text, re.MULTILINE)
    return m.group(1).strip() if m else ""


def chunk_document(title: str, markdown: str) -> list[dict]:
    """Split by ## headings, then by paragraph if oversized, then merge tiny sections."""
    import re

    sections = re.split(r"(?=^## )", markdown, flags=re.MULTILINE)
    raw_sections = []
    for sec in sections:
        sec = sec.strip()
        if not sec:
            continue
        lines = sec.splitlines()
        heading = lines[0].lstrip("#").strip() if lines[0].startswith("#") else ""
        body = "\n".join(lines[1:]).strip() if heading else sec
        raw_sections.append({"heading": heading, "body": body, "text": sec})

    expanded = []
    for sec in raw_sections:
        tok = _count_tokens(sec["text"])
        if tok > 500:
            sub_chunks = _split_by_paragraph(sec["body"], max_tokens=500)
            for sub in sub_chunks:
                expanded.append({"heading": sec["heading"], "text": sub})
        else:
            expanded.append({"heading": sec["heading"], "text": sec["text"]})

    # Merge tiny sections (<50 tokens) with the next sibling
    merged = []
    i = 0
    while i < len(expanded):
        sec = expanded[i]
        if _count_tokens(sec["text"]) < 50 and i + 1 < len(expanded):
            next_sec = expanded[i + 1]
            merged.append({
                "heading": sec["heading"] or next_sec["heading"],
                "text": sec["text"] + "\n\n" + next_sec["text"],
            })
            i += 2
        else:
            merged.append(sec)
            i += 1

    chunks = []
    current_h2 = ""
    for idx, sec in enumerate(merged):
        if sec["heading"]:
            current_h2 = sec["heading"]

        # 3-level breadcrumb: Title > H2 > H3 (H3 extracted from chunk body)
        h3 = _first_h3(sec["text"])
        breadcrumb_parts = [title]
        if current_h2:
            breadcrumb_parts.append(current_h2)
        if h3 and h3 != current_h2:
            breadcrumb_parts.append(h3)
        breadcrumb = " > ".join(breadcrumb_parts)

        chunks.append({
            "text": sec["text"],
            "breadcrumb": breadcrumb,
            "chunk_index": idx,
        })

    return chunks


# ---------------------------------------------------------------------------
# Embedding
# ---------------------------------------------------------------------------

def embed_texts(texts: list[str]) -> list[dict]:
    result = embed_model.encode(texts, return_dense=True, return_sparse=True)
    dense_vecs = result["dense_vecs"]
    sparse_dicts = result["lexical_weights"]

    output = []
    for dense, sparse_dict in zip(dense_vecs, sparse_dicts):
        indices = []
        values = []
        for token_id_str, weight in sparse_dict.items():
            w = float(weight)
            if w == 0.0:
                continue
            indices.append(int(token_id_str))
            values.append(w)
        output.append({
            "dense": dense.tolist(),
            "sparse": SparseVector(indices=indices, values=values),
        })
    return output


# ---------------------------------------------------------------------------
# Qdrant upsert
# ---------------------------------------------------------------------------

def upsert_chunks(page: dict, chunks: list[dict]) -> None:
    if not chunks:
        return
    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(texts)

    page_id = page["id"]
    page_title = get_page_title(page)
    page_url = get_page_url(page)
    tags = get_page_tags(page)
    last_edited = page.get("last_edited_time", "")

    points = []
    for chunk, emb in zip(chunks, embeddings):
        point_id = str(uuid.uuid5(_UUID_NS, page_id + str(chunk["chunk_index"])))
        points.append(
            PointStruct(
                id=point_id,
                vector={
                    "dense": emb["dense"],
                    "sparse": emb["sparse"],
                },
                payload={
                    "source": "notion",
                    "page_id": page_id,
                    "page_url": page_url,
                    "page_title": page_title,
                    "breadcrumb": chunk["breadcrumb"],
                    "text": chunk["text"],
                    "chunk_index": chunk["chunk_index"],
                    "last_edited_time": last_edited,
                    "tags": tags,
                },
            )
        )

    qdrant.upsert(collection_name=COLLECTION_NAME, points=points)


# ---------------------------------------------------------------------------
# Core ingest logic
# ---------------------------------------------------------------------------

def ingest_page(page: dict, conn: sqlite3.Connection, dry_run: bool, full: bool) -> dict:
    page_id = page["id"]
    page_title = get_page_title(page)
    last_edited = page.get("last_edited_time", "")

    stored = get_stored_state(conn, page_id)
    if not full and stored and stored[0] == last_edited:
        log.info("↷ Skipped: %s", page_title)
        return {"status": "skipped"}

    try:
        markdown = page_to_markdown(page_id)
        if not markdown.strip():
            log.info("↷ Skipped (empty): %s", page_title)
            return {"status": "skipped"}

        chunks = chunk_document(page_title, markdown)
        if not chunks:
            log.info("↷ Skipped (no chunks): %s", page_title)
            return {"status": "skipped"}

        if dry_run:
            log.info("[dry-run] Would update: %s (%d chunks)", page_title, len(chunks))
            return {"status": "dry-run", "chunks": len(chunks)}

        delete_page_points(page_id)
        upsert_chunks(page, chunks)
        upsert_state(conn, page_id, last_edited, len(chunks))
        log.info("✓ Updated: %s (%d chunks)", page_title, len(chunks))
        return {"status": "updated", "chunks": len(chunks)}

    except Exception as exc:
        log.error("✗ Error: %s — %s", page_title, exc)
        return {"status": "error"}


def remove_deleted_pages(live_ids: set, conn: sqlite3.Connection, dry_run: bool) -> int:
    stored_ids = all_stored_page_ids(conn)
    deleted_ids = stored_ids - live_ids
    count = 0
    for pid in deleted_ids:
        if dry_run:
            log.info("[dry-run] Would delete page: %s", pid)
        else:
            delete_page_points(pid)
            delete_state(conn, pid)
            log.info("Deleted removed page: %s", pid)
        count += 1
    return count


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Notion → Qdrant ingestion")
    parser.add_argument("--full", action="store_true", help="Re-ingest all pages")
    parser.add_argument("--page", metavar="ID", help="Ingest a single page by Notion ID")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    args = parser.parse_args()

    ensure_collection()
    conn = open_state_db()

    start = time.time()
    stats = {"processed": 0, "updated": 0, "skipped": 0, "errors": 0, "chunks": 0, "deleted": 0}

    if args.page:
        page = _notion_page_retrieve(args.page)
        result = ingest_page(page, conn, dry_run=args.dry_run, full=True)
        stats["processed"] = 1
        stats[result["status"]] = stats.get(result["status"], 0) + 1
        if "chunks" in result:
            stats["chunks"] += result["chunks"]
    else:
        pages = list_source_pages()
        live_ids = {p["id"] for p in pages}

        for page in pages:
            result = ingest_page(page, conn, dry_run=args.dry_run, full=args.full)
            stats["processed"] += 1
            status = result["status"]
            if status == "updated":
                stats["updated"] += 1
                stats["chunks"] += result.get("chunks", 0)
            elif status == "skipped":
                stats["skipped"] += 1
            elif status == "error":
                stats["errors"] += 1

        stats["deleted"] = remove_deleted_pages(live_ids, conn, dry_run=args.dry_run)

    elapsed = time.time() - start
    log.info(
        "\nSummary — pages: %d | updated: %d | skipped: %d | chunks: %d | deleted: %d | errors: %d | time: %.1fs",
        stats["processed"], stats["updated"], stats["skipped"],
        stats["chunks"], stats["deleted"], stats["errors"], elapsed,
    )

    conn.close()


if __name__ == "__main__":
    main()
