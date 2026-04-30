import asyncio
import json
import logging
import re

from openai import AsyncOpenAI

import notion
from cache import cache as _cache
from config import settings

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 20000

# Model names differ per provider
if settings.AI_PROVIDER == "openrouter":
    MAIN_MODEL = "meta-llama/llama-3.3-70b-instruct"
    SMALL_MODEL = "meta-llama/llama-3.1-8b-instruct"
else:  # groq
    MAIN_MODEL = "llama-3.3-70b-versatile"
    SMALL_MODEL = "llama-3.1-8b-instant"


def _make_client() -> AsyncOpenAI:
    if settings.AI_PROVIDER == "openrouter":
        return AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.OPENROUTER_API_KEY,
        )
    return AsyncOpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=settings.GROQ_API_KEY,
    )

SYSTEM_PROMPT = """You are a personal AI secretary (female). Answer the user's question using the Notion data provided below.

Rules:
- Always respond in Thai (unless user writes English)
- Use female Thai politeness particles: ค่ะ for statements, คะ for questions — never ครับ
- Be concise and direct
- The Notion data has "pages" (text) and "databases" (table rows)
- If the data contains the answer, state it clearly and mention which Notion page or database it came from (e.g. "จาก page API Token")
- If the data is empty or has no relevant info, say "ไม่พบข้อมูลใน Notion ค่ะ"

For WRITE requests (user wants to record/save something new), choose based on what the data shows:

A) If the data shows a [TABLE_BLOCK_ID: xxx] [COLUMNS: col1 | col2 | ...] — it's a simple table. Output:
{"tool": "propose_add_table_row", "table_block_id": "xxx", "table_name": "page name", "cells": ["val1", "val2", ...], "summary": "Thai description"}
cells must be in the same order as COLUMNS. Use empty string "" for unknown fields.

B) If the data shows a proper Notion database (with database_id) — output:
{"tool": "propose_create", "database_id": "...", "database_name": "...", "properties": { ... }, "summary": "Thai description"}

Notion property format (for case B):
  Title:  {"Name": {"title": [{"text": {"content": "value"}}]}}
  Text:   {"Note": {"rich_text": [{"text": {"content": "value"}}]}}
  Select: {"Type": {"select": {"name": "value"}}}
  Date:   {"Date": {"date": {"start": "YYYY-MM-DD"}}}
  Number: {"Num": {"number": 42}}

For all other requests, write your Thai answer directly (no JSON)."""


PROPOSE_TOOLS = {"propose_create", "propose_add_table_row"}


def _parse_propose(text: str) -> dict | None:
    text = text.strip()
    if not text.startswith("{"):
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)
        if isinstance(obj, dict) and obj.get("tool") in PROPOSE_TOOLS:
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    return None


async def _search_variants(client: AsyncOpenAI, message: str) -> list[str]:
    """Build search query variants.

    If the message contains English/numbers → fast path (no LLM):
      "ขอข้อมูล book bank ทั้งหมด" → ["book bank", "bookbank", <original>]

    If the message is Thai-only → one LLM call to translate:
      "ขอข้อมูลยื่นภาษี" → ["tax filing", <original>]
    """
    english_words = re.findall(r"[a-zA-Z0-9]+", message)
    variants: list[str] = []

    if english_words:
        variants.append(" ".join(english_words))
        joined = "".join(english_words)
        if joined != " ".join(english_words):
            variants.append(joined)
    else:
        # Pure Thai — extract key term AND English translation (covers Notion pages with bilingual headings)
        r = await client.chat.completions.create(
            model=SMALL_MODEL,
            messages=[{"role": "user", "content": (
                "For this Thai message, output TWO things separated by | :\n"
                "1. Key topic words in Thai (strip ขอ/หน่อย/ทั้งหมด/ข้อมูล)\n"
                "2. English translation of the topic\n"
                "Output ONLY: <thai> | <english>\n"
                f"{message}"
            )}],
            max_tokens=30,
            temperature=0,
        )
        raw = (r.choices[0].message.content or "").strip()
        if "|" in raw:
            thai_part, eng_part = raw.split("|", 1)
            for term in [thai_part.strip(), eng_part.strip()]:
                if term and term != message:
                    variants.append(term)
        elif raw and raw != message:
            variants.append(raw)

    variants.append(message)
    return list(dict.fromkeys(variants))


async def run(user_message: str) -> dict:
    client = _make_client()

    search_queries = await _search_variants(client, user_message)
    logger.info(f"Search queries: {search_queries}")
    notion_data = await _deep_search(client, settings.NOTION_TOKEN, search_queries)
    ranked = _rank_context(notion_data, search_queries, MAX_CONTEXT_CHARS)
    context = json.dumps(ranked, ensure_ascii=False)

    response = await client.chat.completions.create(
        model=MAIN_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"{user_message}\n\n[Notion data]\n{context}"},
        ],
        max_tokens=1024,
        temperature=0.3,
    )
    output = (response.choices[0].message.content or "").strip()
    proposal = _parse_propose(output)

    if proposal:
        tool = proposal.get("tool", "")
        summary = proposal.get("summary", "?")

        if tool == "propose_add_table_row":
            location = proposal.get("table_name", "?")
            pending = {
                "write_type": "table",
                "table_block_id": proposal.get("table_block_id"),
                "cells": proposal.get("cells", []),
            }
        else:
            location = proposal.get("database_name", "?")
            pending = {
                "write_type": "database",
                "database_id": proposal.get("database_id"),
                "properties": proposal.get("properties", {}),
            }

        return {
            "type": "confirm",
            "text": (
                f"จะบันทึก {summary} ใน '{location}' ใช่ไหมคะ?\n\n"
                "ตอบ 'ใช่' เพื่อยืนยัน หรือ 'ไม่' เพื่อยกเลิก"
            ),
            "pending": pending,
        }

    return {"type": "answer", "text": output or "ไม่มีคำตอบค่ะ"}


async def _process_item(token: str, item: dict) -> tuple[list, list]:
    """Process one search result item — returns (pages, databases)."""
    item_pages: list[dict] = []
    item_dbs: list[dict] = []

    if item["type"] == "database":
        rows = await notion.query_database(token, item["id"])
        item_dbs.append({"id": item["id"], "title": item["title"], "rows": rows})

    elif item["type"] == "page":
        rows = await notion.query_database(token, item["id"])
        if rows:
            item_dbs.append({"id": item["id"], "title": item["title"], "rows": rows})
        else:
            content = await notion.get_page_content(token, item["id"])
            if content:
                item_pages.append({"id": item["id"], "title": item["title"], "content": content})
            for db_name, db_id in re.findall(
                r'\[EMBEDDED DATABASE: "([^"]+)" database_id=([a-f0-9-]+)\]', content or ""
            ):
                try:
                    db_rows = await notion.query_database(token, db_id)
                    item_dbs.append({"id": db_id, "title": db_name, "rows": db_rows})
                except Exception as e:
                    logger.error(f"query embedded db {db_id} error: {e}")

    return item_pages, item_dbs


async def _fallback_scan(token: str, keywords: list[str]) -> dict:
    """Two-phase fallback — served from in-memory cache when warm.

    Phase 1: headers from cache (0 Notion API calls on cache-hit).
    Phase 2: Match keywords → full deep read of matched pages only.
    """
    all_pages = await _cache.get_pages()
    if not all_pages:
        return {"pages": [], "databases": []}

    # Phase 1: headers from cache (parallel fetch only on cold start)
    headers = await asyncio.gather(*[_cache.get_header(p["id"]) for p in all_pages])

    # Build keyword set (space-split words) from all search query variants
    kw_set = {w.lower() for kw in keywords for w in re.split(r"[\s,|]+", kw) if len(w) > 2}

    # Also build 4-char Thai sliding windows — catches cases where LLM extracts
    # a synonym (e.g. "ไฟฟ้า") instead of the exact query term (e.g. "ค่าไฟ")
    thai_re = re.compile(r"[฀-๿]+")
    win4: set[str] = set()
    for kw in keywords:
        thai = "".join(thai_re.findall(kw))
        win4.update(thai[i:i + 4] for i in range(len(thai) - 3))

    logger.info(f"Fallback kw_set: {kw_set} | win4 sample: {list(win4)[:5]}")

    def _header_matches(header: str) -> bool:
        h = header.lower()
        return any(kw in h for kw in kw_set) or any(w in h for w in win4)

    # Phase 2: full deep read only for pages whose headers match
    candidates = [page for page, header in zip(all_pages, headers) if _header_matches(header)]
    if not candidates:
        candidates = all_pages[:5]  # no match → read top 5 recent pages
    logger.info(f"Fallback candidates: {[p['title'] for p in candidates]}")

    processed = await asyncio.gather(*[_process_item(token, p) for p in candidates])
    pages: list[dict] = []
    databases: list[dict] = []
    for p, d in processed:
        pages.extend(p)
        databases.extend(d)
    return {"pages": pages, "databases": databases}


def _rank_context(notion_data: dict, queries: list[str], max_chars: int) -> dict:
    """Score each page/db by keyword hits, pack highest-scoring items first.

    Uses continue (not break) so a single oversized item doesn't block smaller
    high-relevance items from being included.
    """
    kw_set = {w.lower() for q in queries for w in re.split(r"[\s,|]+", q) if len(w) > 1}

    def _count(text: str) -> int:
        if not kw_set:
            return 0
        t = text.lower()
        return sum(t.count(kw) for kw in kw_set)

    scored: list[tuple[int, str, dict]] = []
    for p in notion_data.get("pages", []):
        s = _count(p.get("title", "") + " " + p.get("content", ""))
        scored.append((s, "page", p))
    for d in notion_data.get("databases", []):
        rows_text = " ".join(
            " ".join(str(v) for v in row.get("properties", {}).values() if v is not None)
            for row in d.get("rows", [])
        )
        s = _count(d.get("title", "") + " " + rows_text)
        scored.append((s, "database", d))

    scored.sort(key=lambda x: x[0], reverse=True)

    result: dict = {"pages": [], "databases": []}
    used = 0
    for _, kind, item in scored:
        chunk = json.dumps(item, ensure_ascii=False)
        if used + len(chunk) > max_chars:
            continue  # skip oversized item, keep trying smaller ones
        result["pages" if kind == "page" else "databases"].append(item)
        used += len(chunk)
    return result


async def _deep_search(client: AsyncOpenAI, token: str, queries: list[str] | str) -> dict:
    """Always run Notion search AND two-phase fallback in parallel, then merge results.
    This ensures nested toggle content (not indexed by Notion) is always found via fallback.
    """
    if isinstance(queries, str):
        queries = [queries]

    # Run search AND fallback simultaneously — no conditional
    search_batches, fallback_data = await asyncio.gather(
        asyncio.gather(*[notion.search(token, q) for q in queries]),
        _fallback_scan(token, list(queries)),
    )

    # Process unique pages from Notion search
    seen_ids: set[str] = set()
    search_items: list[dict] = []
    for items in search_batches:
        for item in items:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                search_items.append(item)

    if search_items:
        processed = await asyncio.gather(*[_process_item(token, item) for item in search_items])
        search_pages: list[dict] = []
        search_dbs: list[dict] = []
        for p, d in processed:
            search_pages.extend(p)
            search_dbs.extend(d)
    else:
        search_pages, search_dbs = [], []

    # Merge: add fallback pages/dbs not already covered by search
    search_page_ids = {p["id"] for p in search_pages}
    search_db_ids = {d["id"] for d in search_dbs}
    merged_pages = search_pages + [p for p in fallback_data["pages"] if p["id"] not in search_page_ids]
    merged_dbs = search_dbs + [d for d in fallback_data["databases"] if d["id"] not in search_db_ids]

    return {"pages": merged_pages, "databases": merged_dbs}


async def execute_write(pending: dict) -> str:
    token = settings.NOTION_TOKEN
    try:
        if pending.get("write_type") == "table":
            result = await notion.add_table_row(token, pending["table_block_id"], pending["cells"])
            if result.get("object") == "list":
                return "บันทึกเรียบร้อยแล้วค่ะ"
            return f"เกิดข้อผิดพลาด: {result.get('message', 'unknown error')}"
        else:
            result = await notion.create_row(token, pending["database_id"], pending["properties"])
            if result.get("object") == "page":
                return "บันทึกเรียบร้อยแล้วค่ะ"
            return f"เกิดข้อผิดพลาด: {result.get('message', 'unknown error')}"
    except Exception as e:
        logger.error(f"execute_write error: {e}")
        return "บันทึกไม่สำเร็จค่ะ ลองใหม่อีกครั้งนะคะ"
