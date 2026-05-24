import asyncio
import json
import logging
import re

from openai import AsyncOpenAI, RateLimitError

import notion
import provider as _provider
from cache import cache as _cache
from config import settings

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 20000

SYSTEM_PROMPT = """You are a personal AI secretary (female). Answer the user's question ONLY using the Notion data provided below. Never use your own training knowledge to answer — you are a lookup tool, not a general assistant.

Rules:
- Always respond in Thai (unless user writes English)
- Use female Thai politeness particles: ค่ะ for statements, คะ for questions — never ครับ
- Be concise and direct
- The Notion data has "pages" (text) and "databases" (table rows)
- If the data contains the answer, state it clearly, mention which page it came from, and end your reply on a new line with 🔗 followed by the page URL from the Notion data (e.g. "🔗 https://notion.so/abc123"). Use the `url` field from the matching page or database in the data.
- Match user queries to data flexibly — "kmotor" matches "K-Motor Help me", "twitter" matches "Twitter (X)", "aia" matches "AIA", etc. Use judgment for abbreviated or partial names
- If the Notion data does not contain the answer — even if you know the answer from your training — say "ไม่พบข้อมูลใน Notion ค่ะ" and nothing else

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

C) To UPDATE an existing row in a simple table — use the [ROW_ID: xxx] shown next to each row:
{"tool": "propose_update_table_row", "row_block_id": "xxx", "table_name": "page name", "cells": ["full_col1", "full_col2", ...], "summary": "Thai description"}
cells must contain ALL columns of the row (unchanged columns keep their original value).

D) To UPDATE an existing database row — use the page id shown in the row data:
{"tool": "propose_update_row", "page_id": "...", "database_name": "...", "properties": {...}, "summary": "Thai description"}

E) To DELETE / REMOVE a row in a simple table (triggered by words like ลบ, เอาออก, ลบออก, ลบทิ้ง, remove, delete) — use the [ROW_ID: xxx] shown next to each row:
{"tool": "propose_delete_table_row", "row_block_id": "xxx", "table_name": "page name", "summary": "Thai description of what will be deleted"}
IMPORTANT: Use DELETE (not update) when the user wants to remove the entire row, not change its content.

F) To DELETE (archive) a database row — same trigger words as E:
{"tool": "propose_delete_row", "page_id": "...", "database_name": "...", "summary": "Thai description of what will be deleted"}

G) To CREATE a new Notion page inside a parent page (triggered when user says สร้าง/เพิ่ม page ใหม่/บันทึกเป็น page ใหม่, or when no table/DB exists but a page does):
{"tool": "propose_create_page", "parent_page_id": "...", "parent_name": "page name", "title": "new page title", "content": "body text (use # heading / - bullet / [ ] todo syntax)", "summary": "Thai description"}
Use the `id` field from the matching page as parent_page_id.
Leave content empty ("") if user only gives a title.

For MULTIPLE rows at once — output a JSON array with one object per row. CRITICAL rules:
- One line of user input = ONE row. Never merge multiple lines into one row.
- Example: user writes "test 12sdafsdfdgs\ntest02 adfsdfafasf" → TWO rows, not one.
[
  {"tool": "propose_add_table_row", "table_block_id": "...", "table_name": "...", "cells": ["test", "12sdafsdfdgs", "", ""], "summary": "เพิ่ม test"},
  {"tool": "propose_add_table_row", "table_block_id": "...", "table_name": "...", "cells": ["test02", "adfsdfafasf", "", ""], "summary": "เพิ่ม test02"}
]

For all other requests, write your Thai answer directly (no JSON)."""


PROPOSE_TOOLS = {
    "propose_create", "propose_add_table_row",
    "propose_update_table_row", "propose_update_row",
    "propose_delete_table_row", "propose_delete_row",
    "propose_create_page",
}

_GENERAL_PROMPT = """You are a helpful AI assistant (female). Answer the user's question using your general knowledge.
- Always respond in Thai (unless user writes English)
- Use female Thai politeness particles: ค่ะ for statements, คะ for questions — never ครับ
- Be concise and direct"""


def _parse_propose(text: str) -> list[dict] | None:
    """Scan LLM output for one or more write proposals.

    Robust to any of these real-world LLM output patterns:
      - Bare JSON object:              {"tool": ...}
      - JSON array:                    [{...}, {...}]
      - Multiple objects on sep lines: {...}\n{...}\n{...}
      - JSON embedded in prose:        "เพิ่ม...\n{...}\nจาก page..."

    Scans left-to-right, collecting every valid proposal found.
    Returns a non-empty list on success, None if nothing found.
    """
    results: list[dict] = []
    decoder = json.JSONDecoder()
    i = 0
    while i < len(text):
        j = text.find("{", i)
        k = text.find("[", i)
        if j == -1 and k == -1:
            break
        if j == -1:
            start = k
        elif k == -1:
            start = j
        else:
            start = min(j, k)
        try:
            obj, end = decoder.raw_decode(text, start)
            if isinstance(obj, dict) and obj.get("tool") in PROPOSE_TOOLS:
                results.append(obj)
            elif isinstance(obj, list):
                results.extend(
                    item for item in obj
                    if isinstance(item, dict) and item.get("tool") in PROPOSE_TOOLS
                )
            i = end
        except (json.JSONDecodeError, ValueError):
            i = start + 1
    return results if results else None


async def _search_variants(client: AsyncOpenAI, small_model: str, message: str) -> list[str]:
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
        # Pure Thai — extract key term AND English translation
        translate_msgs = [{"role": "user", "content": (
            "For this Thai message, output TWO things separated by | :\n"
            "1. Key topic words in Thai (strip ขอ/หน่อย/ทั้งหมด/ข้อมูล)\n"
            "2. English translation of the topic\n"
            "Output ONLY: <thai> | <english>\n"
            f"{message}"
        )}]
        try:
            r = await client.chat.completions.create(
                model=small_model, messages=translate_msgs, max_tokens=30, temperature=0,
            )
        except RateLimitError as e:
            if not settings.OPENROUTER_API_KEY:
                raise
            client, _, small_model = _provider.on_groq_rate_limit(e, settings)
            r = await client.chat.completions.create(
                model=small_model, messages=translate_msgs, max_tokens=30, temperature=0,
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


def _extract_prop_preview(props: dict) -> list[str]:
    """Extract human-readable values from a Notion properties dict for confirm preview."""
    vals: list[str] = []
    for v in props.values():
        if not isinstance(v, dict):
            continue
        for content in v.values():
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text", {}).get("content", "")
                        if text:
                            vals.append(text)
            elif isinstance(content, dict):
                text = str(content.get("name") or content.get("start") or "")
                if text:
                    vals.append(text)
    return vals


async def run(user_message: str, history: list[dict] | None = None) -> dict:
    client, main_model, small_model = _provider.get_client(settings)

    search_queries = await _search_variants(client, small_model, user_message)
    logger.info(f"Search queries: {search_queries}")
    notion_data = await _deep_search(settings.NOTION_TOKEN, search_queries)
    ranked = _rank_context(notion_data, search_queries, MAX_CONTEXT_CHARS)
    context = json.dumps(ranked, ensure_ascii=False)

    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *(history or []),
        {"role": "user", "content": f"{user_message}\n\n[Notion data]\n{context}"},
    ]
    try:
        response = await client.chat.completions.create(
            model=main_model, messages=msgs, max_tokens=2048, temperature=0.3,
        )
    except RateLimitError as e:
        if not settings.OPENROUTER_API_KEY:
            raise
        client, main_model, _ = _provider.on_groq_rate_limit(e, settings)
        response = await client.chat.completions.create(
            model=main_model, messages=msgs, max_tokens=2048, temperature=0.3,
        )
    output = (response.choices[0].message.content or "").strip()
    proposals = _parse_propose(output)

    if proposals:
        pending_list: list[dict] = []
        preview_lines: list[str] = []

        for proposal in proposals:
            tool = proposal.get("tool", "")
            cells = proposal.get("cells", [])
            props = proposal.get("properties", {})

            if tool == "propose_add_table_row":
                pending_list.append({
                    "write_type": "table",
                    "table_block_id": proposal.get("table_block_id"),
                    "cells": cells,
                })
                cell_preview = " | ".join(c for c in cells if c)
                preview_lines.append(f"• [เพิ่ม] [{cell_preview}]")

            elif tool == "propose_update_table_row":
                pending_list.append({
                    "write_type": "table_update",
                    "row_block_id": proposal.get("row_block_id"),
                    "cells": cells,
                })
                cell_preview = " | ".join(c for c in cells if c)
                preview_lines.append(f"• [แก้ไข] [{cell_preview}]")

            elif tool == "propose_update_row":
                pending_list.append({
                    "write_type": "database_update",
                    "page_id": proposal.get("page_id"),
                    "properties": props,
                })
                prop_vals = _extract_prop_preview(props)
                preview_lines.append(f"• [แก้ไข] {' | '.join(prop_vals)}")

            elif tool == "propose_delete_table_row":
                pending_list.append({
                    "write_type": "table_delete",
                    "row_block_id": proposal.get("row_block_id"),
                })
                preview_lines.append(f"• [🗑️ ลบ] {proposal.get('summary', '?')}")

            elif tool == "propose_delete_row":
                pending_list.append({
                    "write_type": "database_delete",
                    "page_id": proposal.get("page_id"),
                })
                preview_lines.append(f"• [🗑️ ลบ] {proposal.get('summary', '?')}")

            elif tool == "propose_create_page":
                pending_list.append({
                    "write_type": "new_page",
                    "parent_page_id": proposal.get("parent_page_id"),
                    "title": proposal.get("title", ""),
                    "content": proposal.get("content", ""),
                })
                preview_lines.append(f"• [สร้าง page] '{proposal.get('title', '?')}' ใน '{proposal.get('parent_name', '?')}'")

            else:  # propose_create
                pending_list.append({
                    "write_type": "database",
                    "database_id": proposal.get("database_id"),
                    "properties": props,
                })
                prop_vals = _extract_prop_preview(props)
                preview_lines.append(f"• [เพิ่ม] {' | '.join(prop_vals)}")

        loc_name = (proposals[0].get("table_name") or proposals[0].get("database_name") or "?")
        preview = "\n".join(preview_lines)
        n = len(pending_list)

        _delete_types = {"table_delete", "database_delete"}
        all_delete = all(p.get("write_type") in _delete_types for p in pending_list)
        has_delete = any(p.get("write_type") in _delete_types for p in pending_list)

        if all_delete:
            action_verb = f"⚠️ จะลบ {n} รายการ ออกจาก '{loc_name}' (ไม่สามารถกู้คืนได้)"
        elif has_delete:
            action_verb = f"จะดำเนินการ {n} รายการ ใน '{loc_name}'"
        else:
            action_verb = f"จะบันทึก {n} รายการ ลงใน '{loc_name}'"

        confirm_text = (
            f"{action_verb}:\n{preview}\n\n"
            "ตอบ 'ใช่' เพื่อยืนยัน หรือ 'ไม่' เพื่อยกเลิก"
        )

        return {
            "type": "confirm",
            "text": confirm_text,
            "pending": pending_list,
        }

    # Offer general knowledge when Notion has no relevant data
    if output.startswith("ไม่พบ"):
        return {
            "type": "ask_general",
            "text": f"{output}\n\nต้องการให้ตอบจากความรู้ทั่วไปได้ไหมคะ?",
            "question": user_message,
        }

    # If output looks like a JSON proposal but failed to parse (e.g. truncated
    # by token limit), don't leak raw JSON to the user — ask them to retry.
    if output.lstrip().startswith(("{", "[")):
        logger.warning(f"Malformed proposal output (truncated?): {output[:120]}")
        return {"type": "answer", "text": "ขอโทษค่ะ ข้อความยาวเกินไปทำให้ประมวลผลไม่สำเร็จ ลองพิมพ์ใหม่อีกครั้งนะคะ"}

    return {"type": "answer", "text": output or "ไม่มีคำตอบค่ะ"}


async def run_general(user_message: str, history: list[dict] | None = None) -> dict:
    client, main_model, _ = _provider.get_client(settings)
    msgs = [
        {"role": "system", "content": _GENERAL_PROMPT},
        *(history or []),
        {"role": "user", "content": user_message},
    ]
    try:
        response = await client.chat.completions.create(
            model=main_model, messages=msgs, max_tokens=1024, temperature=0.5,
        )
    except RateLimitError as e:
        if not settings.OPENROUTER_API_KEY:
            raise
        client, main_model, _ = _provider.on_groq_rate_limit(e, settings)
        response = await client.chat.completions.create(
            model=main_model, messages=msgs, max_tokens=1024, temperature=0.5,
        )
    output = (response.choices[0].message.content or "").strip()
    return {"type": "answer", "text": output or "ไม่มีคำตอบค่ะ"}


async def _process_item(token: str, item: dict) -> tuple[list, list]:
    """Process one search result item — returns (pages, databases)."""
    item_pages: list[dict] = []
    item_dbs: list[dict] = []
    url = item.get("url") or f"https://notion.so/{item['id'].replace('-', '')}"

    if item["type"] == "database":
        rows = await notion.query_database(token, item["id"])
        item_dbs.append({"id": item["id"], "title": item["title"], "rows": rows, "url": url})

    elif item["type"] == "page":
        rows = await notion.query_database(token, item["id"])
        if rows:
            item_dbs.append({"id": item["id"], "title": item["title"], "rows": rows, "url": url})
        else:
            content = await notion.get_page_content(token, item["id"])
            if content:
                item_pages.append({"id": item["id"], "title": item["title"], "content": content, "url": url})
            for db_name, db_id in re.findall(
                r'\[EMBEDDED DATABASE: "([^"]+)" database_id=([a-f0-9-]+)\]', content or ""
            ):
                try:
                    db_rows = await notion.query_database(token, db_id)
                    db_url = f"https://notion.so/{db_id.replace('-', '')}"
                    item_dbs.append({"id": db_id, "title": db_name, "rows": db_rows, "url": db_url})
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

    # Hyphen-stripped variants — "kmotor" matches "k-motor", "kmotor" matches "k motor"
    kw_compact = {re.sub(r"[-_\s]", "", kw) for kw in kw_set if kw.isascii()}

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
        h_compact = re.sub(r"[-_\s]", "", h)
        return (
            any(kw in h for kw in kw_set) or
            any(kw in h_compact for kw in kw_compact) or
            any(w in h for w in win4)
        )

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


async def _deep_search(token: str, queries: list[str] | str) -> dict:
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


async def _write_one(token: str, item: dict) -> str | None:
    """Execute a single write. Returns None on success, error string on failure."""
    try:
        write_type = item.get("write_type", "")

        if write_type == "table":
            result = await notion.add_table_row(token, item["table_block_id"], item["cells"])
            ok = result.get("object") == "list"

        elif write_type == "table_update":
            result = await notion.update_table_row(token, item["row_block_id"], item["cells"])
            ok = result.get("object") == "block"

        elif write_type == "database_update":
            result = await notion.update_row(token, item["page_id"], item["properties"])
            ok = result.get("object") == "page"

        elif write_type == "new_page":
            result = await notion.create_page(token, item["parent_page_id"], item["title"])
            ok = result.get("object") == "page"
            if ok and item.get("content"):
                await notion.append_blocks(token, result["id"], item["content"])

        elif write_type == "table_delete":
            result = await notion.delete_table_row(token, item["row_block_id"])
            ok = result.get("object") == "block"

        elif write_type == "database_delete":
            result = await notion.archive_row(token, item["page_id"])
            ok = result.get("object") == "page" and result.get("archived") is True

        else:  # "database" — insert new row
            result = await notion.create_row(token, item["database_id"], item["properties"])
            ok = result.get("object") == "page"

        if ok:
            return None
        err = result.get("message") or result.get("code") or str(result)
        logger.error(f"_write_one failed ({write_type}): {result}")
        return err

    except Exception as e:
        logger.error(f"_write_one exception: {e}")
        return str(e)


async def execute_write(pending: list[dict]) -> str:
    """Execute all pending writes in parallel. pending is always a list."""
    token = settings.NOTION_TOKEN
    errors: list[str | None] = await asyncio.gather(*[_write_one(token, item) for item in pending])

    succeeded = sum(1 for e in errors if e is None)
    total = len(errors)
    failed_msgs = [e for e in errors if e is not None]

    if succeeded == total:
        return "บันทึกเรียบร้อยแล้วค่ะ" if total == 1 else f"บันทึกเรียบร้อยทั้ง {total} รายการค่ะ"
    if succeeded == 0:
        return f"บันทึกไม่สำเร็จค่ะ: {failed_msgs[0]}"
    return f"บันทึกสำเร็จ {succeeded}/{total} รายการค่ะ\nข้อผิดพลาด: {'; '.join(failed_msgs)}"
