import httpx

NOTION_API = "https://api.notion.com/v1"
MAX_CONTENT_CHARS = 6000


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _extract_title(item: dict) -> str:
    if item["object"] == "database":
        parts = item.get("title", [])
    else:
        props = item.get("properties", {})
        title_prop = next((v for v in props.values() if v.get("type") == "title"), None)
        parts = title_prop.get("title", []) if title_prop else []
    return "".join(p.get("plain_text", "") for p in parts)


def _prop_value(prop: dict):
    ptype = prop.get("type", "")
    val = prop.get(ptype)
    if ptype == "title":
        return "".join(rt.get("plain_text", "") for rt in (val or []))
    if ptype == "rich_text":
        return "".join(rt.get("plain_text", "") for rt in (val or []))
    if ptype in ("number", "checkbox"):
        return val
    if ptype == "select":
        return val.get("name") if val else None
    if ptype == "multi_select":
        return [o["name"] for o in (val or [])]
    if ptype == "date":
        return val.get("start") if val else None
    if ptype == "url":
        return val
    return str(val) if val is not None else None



async def search(token: str, query: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{NOTION_API}/search",
            headers=_headers(token),
            json={"query": query, "page_size": 8},
            timeout=15,
        )
        return [
            {
                "id": item["id"],
                "type": item["object"],
                "title": _extract_title(item),
                "url": item.get("url", ""),
            }
            for item in r.json().get("results", [])
        ]


async def get_page_content(token: str, page_id: str, _depth: int = 0) -> str:
    if _depth > 2:
        return ""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{NOTION_API}/blocks/{page_id}/children",
            headers=_headers(token),
            timeout=15,
        )
        blocks = r.json().get("results", [])

    lines = []
    for block in blocks:
        btype = block.get("type", "")
        if btype == "table":
            table_text = await _read_table(token, block["id"], block.get("table", {}).get("has_column_header", False))
            if table_text:
                lines.append(table_text)
        elif btype == "child_database":
            title = block.get("child_database", {}).get("title", "")
            lines.append(f'[EMBEDDED DATABASE: "{title}" database_id={block["id"]}]')
        elif btype == "child_page":
            title = block.get("child_page", {}).get("title", "")
            lines.append(f'[CHILD PAGE: "{title}" page_id={block["id"]}]')
        else:
            content = block.get(btype, {})
            text = "".join(rt.get("plain_text", "") for rt in content.get("rich_text", []))
            if text:
                lines.append(text)
            # Recursively fetch children of container blocks (toggle, columns, etc.)
            if block.get("has_children"):
                child_text = await get_page_content(token, block["id"], _depth + 1)
                if child_text:
                    lines.append(child_text)

    result = "\n".join(lines)
    return result[:MAX_CONTENT_CHARS] + ("..." if len(result) > MAX_CONTENT_CHARS else "")


async def _read_table(token: str, table_block_id: str, has_header: bool) -> str:
    """Read a Notion simple table block and return rows as text with TABLE_BLOCK_ID header."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{NOTION_API}/blocks/{table_block_id}/children",
            headers=_headers(token),
            timeout=15,
        )
    rows = r.json().get("results", [])
    if not rows:
        return ""

    header: list[str] = []
    lines: list[str] = []
    for i, row in enumerate(rows):
        if row.get("type") != "table_row":
            continue
        cells = [
            "".join(rt.get("plain_text", "") for rt in cell)
            for cell in row["table_row"]["cells"]
        ]
        if has_header and i == 0:
            header = cells
        else:
            if header:
                lines.append(", ".join(f"{header[j]}: {cells[j]}" for j in range(min(len(header), len(cells)))))
            else:
                lines.append(" | ".join(cells))

    prefix = f"[TABLE_BLOCK_ID: {table_block_id}]"
    if header:
        prefix += f" [COLUMNS: {' | '.join(header)}]"
    return prefix + "\n" + "\n".join(lines)


async def add_table_row(token: str, table_block_id: str, cells: list[str]) -> dict:
    """Append a new row to a Notion simple table block."""
    async with httpx.AsyncClient() as client:
        r = await client.patch(
            f"{NOTION_API}/blocks/{table_block_id}/children",
            headers=_headers(token),
            json={
                "children": [{
                    "object": "block",
                    "type": "table_row",
                    "table_row": {
                        "cells": [[{"type": "text", "text": {"content": c}}] for c in cells]
                    },
                }]
            },
            timeout=15,
        )
        return r.json()


async def get_database_schema(token: str, database_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{NOTION_API}/databases/{database_id}",
            headers=_headers(token),
            timeout=15,
        )
        data = r.json()
        return {
            "id": database_id,
            "title": "".join(p.get("plain_text", "") for p in data.get("title", [])),
            "properties": {name: prop["type"] for name, prop in data.get("properties", {}).items()},
        }


async def query_database(token: str, database_id: str) -> list[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{NOTION_API}/databases/{database_id}/query",
            headers=_headers(token),
            json={"page_size": 20},
            timeout=15,
        )
        rows = []
        for page in r.json().get("results", []):
            row = {"id": page["id"], "properties": {}}
            for name, prop in page.get("properties", {}).items():
                row["properties"][name] = _prop_value(prop)
            rows.append(row)
        return rows


async def get_page_headers(token: str, page_id: str) -> str:
    """Read only top-level block text (no recursion) — fast shallow scan for keyword matching."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{NOTION_API}/blocks/{page_id}/children",
            headers=_headers(token),
            timeout=15,
        )
    lines = []
    for block in r.json().get("results", []):
        btype = block.get("type", "")
        content = block.get(btype, {})
        text = "".join(rt.get("plain_text", "") for rt in content.get("rich_text", []))
        if text:
            lines.append(text)
    return "\n".join(lines)


async def list_all_pages(token: str, limit: int = 20) -> list[dict]:
    """Return all accessible pages (used as fallback when search returns nothing)."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{NOTION_API}/search",
            headers=_headers(token),
            json={"filter": {"value": "page", "property": "object"}, "page_size": limit},
            timeout=15,
        )
        return [
            {"id": item["id"], "type": "page", "title": _extract_title(item)}
            for item in r.json().get("results", [])
        ]


async def get_raw_blocks(token: str, page_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{NOTION_API}/blocks/{page_id}/children",
            headers=_headers(token),
            timeout=15,
        )
        return r.json()


async def query_database_raw(token: str, database_id: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{NOTION_API}/databases/{database_id}/query",
            headers=_headers(token),
            json={"page_size": 5},
            timeout=15,
        )
        return r.json()


async def create_row(token: str, database_id: str, properties: dict) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{NOTION_API}/pages",
            headers=_headers(token),
            json={"parent": {"database_id": database_id}, "properties": properties},
            timeout=15,
        )
        return r.json()
