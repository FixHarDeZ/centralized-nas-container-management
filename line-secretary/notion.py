import asyncio
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
    """Read a Notion simple table block.

    Each data row is prefixed with [ROW_ID: <block_id>] so the LLM can
    reference it when proposing an update.
    """
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
            row_prefix = f"[ROW_ID: {row['id']}] "
            if header:
                lines.append(row_prefix + ", ".join(
                    f"{header[j]}: {cells[j]}" for j in range(min(len(header), len(cells)))
                ))
            else:
                lines.append(row_prefix + " | ".join(cells))

    prefix = f"[TABLE_BLOCK_ID: {table_block_id}]"
    if header:
        prefix += f" [COLUMNS: {' | '.join(header)}]"
    return prefix + "\n" + "\n".join(lines)


async def update_table_row(token: str, row_block_id: str, cells: list[str]) -> dict:
    """Replace all cells in an existing table_row block.

    Fetches the current row first so the cells list can be padded to the
    correct table width — prevents Notion's 'cells must match table width' error
    when the LLM sends a partial cell list.
    """
    async with httpx.AsyncClient() as client:
        # Fetch current row to get actual column count
        current = await client.get(
            f"{NOTION_API}/blocks/{row_block_id}",
            headers=_headers(token),
            timeout=15,
        )
        current_data = current.json()
        current_cells = current_data.get("table_row", {}).get("cells", [])
        table_width = len(current_cells)

        # Pad or truncate to match table width
        padded = list(cells) + [""] * max(0, table_width - len(cells))
        padded = padded[:table_width]

        r = await client.patch(
            f"{NOTION_API}/blocks/{row_block_id}",
            headers=_headers(token),
            json={
                "table_row": {
                    "cells": [[{"type": "text", "text": {"content": c}}] for c in padded]
                }
            },
            timeout=15,
        )
        return r.json()


async def update_row(token: str, page_id: str, properties: dict) -> dict:
    """Update properties of an existing Notion database page (row)."""
    async with httpx.AsyncClient() as client:
        r = await client.patch(
            f"{NOTION_API}/pages/{page_id}",
            headers=_headers(token),
            json={"properties": properties},
            timeout=15,
        )
        return r.json()


async def add_table_row(token: str, table_block_id: str, cells: list[str]) -> dict:
    """Append a new row to a Notion simple table block.

    Fetches the table's column count first and pads/truncates the cells list
    to match — prevents Notion's 'cells must match table width' error when the
    LLM sends fewer cells than the table has columns.
    """
    async with httpx.AsyncClient() as client:
        # Fetch table block to get table_width
        table_block = await client.get(
            f"{NOTION_API}/blocks/{table_block_id}",
            headers=_headers(token),
            timeout=15,
        )
        table_width = table_block.json().get("table", {}).get("table_width", len(cells))

        padded = list(cells) + [""] * max(0, table_width - len(cells))
        padded = padded[:table_width]

        r = await client.patch(
            f"{NOTION_API}/blocks/{table_block_id}/children",
            headers=_headers(token),
            json={
                "children": [{
                    "object": "block",
                    "type": "table_row",
                    "table_row": {
                        "cells": [[{"type": "text", "text": {"content": c}}] for c in padded]
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


async def get_database_rows_with_dates(token: str, database_id: str) -> list[dict]:
    """Return rows that have at least one date property, with title + dates + url."""
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{NOTION_API}/databases/{database_id}/query",
            headers=_headers(token),
            json={"page_size": 100},
            timeout=15,
        )
    if r.status_code != 200:
        raise ValueError(f"Notion API {r.status_code} for DB {database_id}: {r.json().get('message', r.text)}")
    results = []
    for page in r.json().get("results", []):
        title = ""
        dates: dict[str, str] = {}
        for name, prop in page.get("properties", {}).items():
            ptype = prop.get("type", "")
            if ptype == "title":
                title = "".join(rt.get("plain_text", "") for rt in (prop.get("title") or []))
            elif ptype == "date":
                val = prop.get("date")
                if val and val.get("start"):
                    dates[name] = val["start"]
        if dates:
            results.append({"title": title or "?", "dates": dates, "url": page.get("url", "")})
    return results


async def get_page_headers(token: str, page_id: str) -> str:
    """Read block text + table rows, including tables nested one level inside toggle/container blocks.

    Two-pass for containers with children:
      Pass 1: list top-level children — collect text, top-level table IDs, container IDs.
      Pass 2: list each container's children — collect any nested table IDs (parallel).
    Then fetch first 6 rows of all discovered tables in parallel.
    """
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{NOTION_API}/blocks/{page_id}/children",
            headers=_headers(token),
            timeout=15,
        )
    blocks = r.json().get("results", [])
    lines: list[str] = []
    table_ids: list[str] = []
    container_ids: list[str] = []  # any block with children that may hide nested tables

    for block in blocks:
        btype = block.get("type", "")
        if btype == "table":
            table_ids.append(block["id"])
        elif btype in ("child_database", "child_page"):
            pass
        else:
            content = block.get(btype, {})
            text = "".join(rt.get("plain_text", "") for rt in content.get("rich_text", []))
            if text:
                lines.append(text)
            if block.get("has_children"):
                container_ids.append(block["id"])

    async def _read_container(container_id: str) -> tuple[list[str], list[str]]:
        """Return (nested_table_ids, text_lines) from one level inside a container block."""
        async with httpx.AsyncClient() as c:
            resp = await c.get(
                f"{NOTION_API}/blocks/{container_id}/children",
                headers=_headers(token),
                timeout=15,
            )
        nested_tables: list[str] = []
        nested_texts: list[str] = []
        for b in resp.json().get("results", []):
            btype = b.get("type", "")
            if btype == "table":
                nested_tables.append(b["id"])
            elif btype not in ("child_database", "child_page"):
                text = "".join(rt.get("plain_text", "") for rt in b.get(btype, {}).get("rich_text", []))
                if text:
                    nested_texts.append(text)
        return nested_tables, nested_texts

    async def _table_preview(table_id: str) -> str:
        async with httpx.AsyncClient() as c:
            resp = await c.get(
                f"{NOTION_API}/blocks/{table_id}/children",
                headers=_headers(token),
                params={"page_size": "6"},
                timeout=15,
            )
        cells = []
        for row in resp.json().get("results", []):
            if row.get("type") == "table_row":
                for cell in row["table_row"]["cells"]:
                    t = "".join(rt.get("plain_text", "") for rt in cell)
                    if t:
                        cells.append(t)
        return " ".join(cells)

    # Read children of containers in parallel — collect nested tables AND plain text
    if container_ids:
        results = await asyncio.gather(*[_read_container(cid) for cid in container_ids])
        for nested_table_ids, nested_texts in results:
            table_ids.extend(nested_table_ids)
            lines.extend(nested_texts)

    if table_ids:
        previews = await asyncio.gather(*[_table_preview(tid) for tid in table_ids])
        lines.extend(p for p in previews if p)

    return "\n".join(lines)


async def list_all_pages(token: str, limit: int = 50) -> list[dict]:
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


async def delete_table_row(token: str, row_block_id: str) -> dict:
    """Permanently delete a table_row block."""
    async with httpx.AsyncClient() as client:
        r = await client.delete(
            f"{NOTION_API}/blocks/{row_block_id}",
            headers=_headers(token),
            timeout=15,
        )
        return r.json()


async def archive_row(token: str, page_id: str) -> dict:
    """Archive (soft-delete / move to trash) a Notion database page."""
    async with httpx.AsyncClient() as client:
        r = await client.patch(
            f"{NOTION_API}/pages/{page_id}",
            headers=_headers(token),
            json={"archived": True},
            timeout=15,
        )
        return r.json()


async def create_page(token: str, parent_page_id: str, title: str) -> dict:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{NOTION_API}/pages",
            headers=_headers(token),
            json={
                "parent": {"page_id": parent_page_id},
                "properties": {
                    "title": {
                        "title": [{"type": "text", "text": {"content": title}}]
                    }
                },
            },
            timeout=15,
        )
        return r.json()


def _line_to_block(line: str) -> dict:
    """Convert a single text line to a Notion block based on Markdown-like prefix."""
    if line.startswith("### "):
        return {"object": "block", "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": line[4:]}}]}}
    if line.startswith("## "):
        return {"object": "block", "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": line[3:]}}]}}
    if line.startswith("# "):
        return {"object": "block", "type": "heading_1",
                "heading_1": {"rich_text": [{"type": "text", "text": {"content": line[2:]}}]}}
    if line.startswith(("- ", "* ")):
        return {"object": "block", "type": "bulleted_list_item",
                "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": line[2:]}}]}}
    if line.startswith(("[ ] ", "- [ ] ")):
        content = line.split("] ", 1)[-1]
        return {"object": "block", "type": "to_do",
                "to_do": {"rich_text": [{"type": "text", "text": {"content": content}}], "checked": False}}
    if line.startswith(("[x] ", "- [x] ")):
        content = line.split("] ", 1)[-1]
        return {"object": "block", "type": "to_do",
                "to_do": {"rich_text": [{"type": "text", "text": {"content": content}}], "checked": True}}
    return {"object": "block", "type": "paragraph",
            "paragraph": {"rich_text": [{"type": "text", "text": {"content": line}}]}}


async def append_blocks(token: str, page_id: str, text: str) -> dict:
    lines = [line[:2000] for line in text.split("\n") if line.strip()]
    if not lines:
        lines = [text[:2000]]
    children = [_line_to_block(line) for line in lines[:100]]
    async with httpx.AsyncClient() as client:
        r = await client.patch(
            f"{NOTION_API}/blocks/{page_id}/children",
            headers=_headers(token),
            json={"children": children},
            timeout=15,
        )
        return r.json()
