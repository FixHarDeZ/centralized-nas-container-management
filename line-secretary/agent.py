import asyncio
import json
import logging
import re

from groq import AsyncGroq

import notion
from config import settings

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 20000
SMALL_MODEL = "llama-3.1-8b-instant"   # 500K TPD — used for cheap helper tasks
MAIN_MODEL = "llama-3.3-70b-versatile"  # 100K TPD — used only for final answer

SYSTEM_PROMPT = """You are a personal AI secretary. Answer the user's question using the Notion data provided below.

Rules:
- Always respond in Thai (unless user writes English)
- Be concise and direct
- The Notion data has "pages" (text) and "databases" (table rows)
- If the data contains the answer, state it clearly and mention which Notion page or database it came from (e.g. "จาก page API Token")
- If the data is empty or has no relevant info, say "ไม่พบข้อมูลใน Notion ครับ"

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


async def _search_variants(client: AsyncGroq, message: str) -> list[str]:
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
        # Pure Thai — extract the core search term (keep in Thai, strip request words)
        r = await client.chat.completions.create(
            model=SMALL_MODEL,
            messages=[{"role": "user", "content": (
                "Extract only the key topic words from this message for Notion search. "
                "Keep the original language (Thai). Strip request words like ขอ/หน่อย/ทั้งหมด/ข้อมูล. "
                "Output ONLY the topic words, nothing else.\n"
                f"{message}"
            )}],
            max_tokens=20,
            temperature=0,
        )
        extracted = (r.choices[0].message.content or "").strip()
        if extracted and extracted != message:
            variants.append(extracted)

    variants.append(message)
    return list(dict.fromkeys(variants))


async def run(user_message: str) -> dict:
    client = AsyncGroq(api_key=settings.GROQ_API_KEY)

    search_queries = await _search_variants(client, user_message)
    logger.info(f"Search queries: {search_queries}")
    notion_data = await _deep_search(client, settings.NOTION_TOKEN, search_queries)
    context = json.dumps(notion_data, ensure_ascii=False)
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "..."

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
                f"จะบันทึก {summary} ใน '{location}' ใช่ไหมครับ?\n\n"
                "ตอบ 'ใช่' เพื่อยืนยัน หรือ 'ไม่' เพื่อยกเลิก"
            ),
            "pending": pending,
        }

    return {"type": "answer", "text": output or "ไม่มีคำตอบครับ"}


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


FALLBACK_EXCERPT = 600  # chars per page in fallback scan


async def _fallback_scan(token: str) -> dict:
    """Read ALL accessible pages with short excerpts — used when search returns nothing.
    Each page is truncated to FALLBACK_EXCERPT chars so 20 pages ≈ 12K chars total.
    """
    all_pages = await notion.list_all_pages(token)
    if not all_pages:
        return {"pages": [], "databases": []}

    async def _read_short(item: dict) -> tuple[list, list]:
        item_pages: list[dict] = []
        item_dbs: list[dict] = []
        rows = await notion.query_database(token, item["id"])
        if rows:
            item_dbs.append({"id": item["id"], "title": item["title"], "rows": rows})
        else:
            content = await notion.get_page_content(token, item["id"])
            if content:
                item_pages.append({
                    "id": item["id"],
                    "title": item["title"],
                    "content": content[:FALLBACK_EXCERPT],
                })
        return item_pages, item_dbs

    processed = await asyncio.gather(*[_read_short(p) for p in all_pages])
    pages: list[dict] = []
    databases: list[dict] = []
    for p, d in processed:
        pages.extend(p)
        databases.extend(d)
    logger.info(f"Fallback scan read {len(pages)} pages, {len(databases)} databases")
    return {"pages": pages, "databases": databases}


async def _deep_search(client: AsyncGroq, token: str, queries: list[str] | str) -> dict:
    """Search Notion with multiple queries (parallel) → auto-read pages → auto-query embedded databases."""
    if isinstance(queries, str):
        queries = [queries]

    # All searches in parallel
    search_batches = await asyncio.gather(*[notion.search(token, q) for q in queries])

    seen_ids: set[str] = set()
    candidates: list[dict] = []
    for items in search_batches:
        for item in items:
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                candidates.append(item)

    if not candidates:
        logger.info("Search returned nothing — running fallback scan of all pages")
        return await _fallback_scan(token)

    # All page reads in parallel
    processed = await asyncio.gather(*[_process_item(token, item) for item in candidates])

    pages: list[dict] = []
    databases: list[dict] = []
    for item_pages, item_dbs in processed:
        pages.extend(item_pages)
        databases.extend(item_dbs)

    return {"pages": pages, "databases": databases}


async def execute_write(pending: dict) -> str:
    token = settings.NOTION_TOKEN
    try:
        if pending.get("write_type") == "table":
            result = await notion.add_table_row(token, pending["table_block_id"], pending["cells"])
            if result.get("object") == "list":
                return "บันทึกเรียบร้อยแล้วครับ"
            return f"เกิดข้อผิดพลาด: {result.get('message', 'unknown error')}"
        else:
            result = await notion.create_row(token, pending["database_id"], pending["properties"])
            if result.get("object") == "page":
                return "บันทึกเรียบร้อยแล้วครับ"
            return f"เกิดข้อผิดพลาด: {result.get('message', 'unknown error')}"
    except Exception as e:
        logger.error(f"execute_write error: {e}")
        return "บันทึกไม่สำเร็จครับ ลองใหม่อีกครั้งนะครับ"
