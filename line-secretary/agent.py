import json
import logging
import re

from groq import AsyncGroq

import notion
from config import settings

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 12000

SYSTEM_PROMPT = """You are a personal AI secretary. Answer the user's question using the Notion data provided below.

Rules:
- Always respond in Thai (unless user writes English)
- Be concise and direct
- The Notion data has "pages" (text) and "databases" (table rows)
- If the data contains the answer, state it clearly and mention which Notion page or database it came from (e.g. "จาก page API Token")
- If the data is empty or has no relevant info, say "ไม่พบข้อมูลใน Notion ครับ"

For WRITE requests (user wants to record/save something new):
Output ONLY this JSON — infer the schema from existing database rows shown in the data:
{"tool": "propose_create", "database_id": "...", "database_name": "...", "properties": { ... }, "summary": "Thai description of what will be saved"}

Notion property format:
  Title:  {"Name": {"title": [{"text": {"content": "value"}}]}}
  Text:   {"Note": {"rich_text": [{"text": {"content": "value"}}]}}
  Select: {"Type": {"select": {"name": "value"}}}
  Date:   {"Date": {"date": {"start": "YYYY-MM-DD"}}}
  Number: {"Num": {"number": 42}}

For all other requests, write your Thai answer directly (no JSON)."""


def _parse_propose(text: str) -> dict | None:
    text = text.strip()
    if not text.startswith("{"):
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(text)
        if isinstance(obj, dict) and obj.get("tool") == "propose_create":
            return obj
    except (json.JSONDecodeError, ValueError):
        pass
    return None


def _search_variants(message: str) -> list[str]:
    """Build search query variants without any LLM call.

    For "ขอข้อมูล book bank ทั้งหมด" produces:
      ["book bank", "bookbank", "ขอข้อมูล book bank ทั้งหมด"]
    """
    english_words = re.findall(r"[a-zA-Z0-9]+", message)
    variants: list[str] = []
    if english_words:
        variants.append(" ".join(english_words))       # "book bank"
        joined = "".join(english_words)
        if joined != " ".join(english_words):
            variants.append(joined)                    # "bookbank"
    variants.append(message)                           # full original as fallback
    return list(dict.fromkeys(variants))               # dedup, preserve order


async def run(user_message: str) -> dict:
    client = AsyncGroq(api_key=settings.GROQ_API_KEY)

    search_queries = _search_variants(user_message)
    logger.info(f"Search queries: {search_queries}")
    notion_data = await _deep_search(settings.NOTION_TOKEN, search_queries)
    context = json.dumps(notion_data, ensure_ascii=False)
    if len(context) > MAX_CONTEXT_CHARS:
        context = context[:MAX_CONTEXT_CHARS] + "..."

    response = await client.chat.completions.create(
        model="llama-3.3-70b-versatile",
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
        return {
            "type": "confirm",
            "text": (
                f"จะบันทึก {proposal.get('summary', '?')} "
                f"ใน database '{proposal.get('database_name', '?')}' ใช่ไหมครับ?\n\n"
                "ตอบ 'ใช่' เพื่อยืนยัน หรือ 'ไม่' เพื่อยกเลิก"
            ),
            "pending": {
                "database_id": proposal.get("database_id"),
                "properties": proposal.get("properties", {}),
            },
        }

    return {"type": "answer", "text": output or "ไม่มีคำตอบครับ"}


async def _deep_search(token: str, queries: list[str] | str) -> dict:
    """Search Notion with multiple queries → auto-read pages → auto-query embedded databases."""
    if isinstance(queries, str):
        queries = [queries]

    seen_ids: set[str] = set()
    results: list[dict] = []
    for q in queries:
        for item in await notion.search(token, q):
            if item["id"] not in seen_ids:
                seen_ids.add(item["id"])
                results.append(item)

    pages = []
    databases = []

    for item in results:
        if item["type"] == "database":
            rows = await notion.query_database(token, item["id"])
            databases.append({"id": item["id"], "title": item["title"], "rows": rows})

        elif item["type"] == "page":
            # Full-page databases appear as "page" in search but share the same ID.
            # Try querying as a database first; fall back to reading page content.
            rows = await notion.query_database(token, item["id"])
            if rows:
                databases.append({"id": item["id"], "title": item["title"], "rows": rows})
            else:
                content = await notion.get_page_content(token, item["id"])
                if content:
                    pages.append({"id": item["id"], "title": item["title"], "content": content})

                for db_name, db_id in re.findall(
                    r'\[EMBEDDED DATABASE: "([^"]+)" database_id=([a-f0-9-]+)\]', content if not rows else ""
                ):
                    try:
                        db_rows = await notion.query_database(token, db_id)
                        databases.append({"id": db_id, "title": db_name, "rows": db_rows})
                    except Exception as e:
                        logger.error(f"query embedded db {db_id} error: {e}")

    return {"pages": pages, "databases": databases}


async def execute_create_row(database_id: str, properties: dict) -> str:
    try:
        result = await notion.create_row(settings.NOTION_TOKEN, database_id, properties)
        if result.get("object") == "page":
            return "บันทึกเรียบร้อยแล้วครับ"
        return f"เกิดข้อผิดพลาด: {result.get('message', 'unknown error')}"
    except Exception as e:
        logger.error(f"create_row error: {e}")
        return "บันทึกไม่สำเร็จครับ ลองใหม่อีกครั้งนะครับ"
