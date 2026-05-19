# line-secretary Quick Wins Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** เพิ่ม 3 improvements เล็กๆ ที่ไม่แตะ state machine — URL ใน reply, `/refresh` command, และ long reply splitter

**Architecture:** แก้ 3 จุดอิสระกัน: (1) `agent.py` เพิ่ม `url` ใน context dict + update system prompt ให้ LLM include 🔗, (2) `cache.py` เพิ่ม `force_refresh()`, `main.py` เพิ่ม handler, (3) `main.py` เพิ่ม `_push_long()` แทน direct push ที่ท้าย `handle_message()`

**Tech Stack:** Python 3.12 · FastAPI · httpx · pytest · pytest-asyncio

---

## File Map

| File | Change |
|---|---|
| `line-secretary/agent.py` | เพิ่ม `url` field ใน page/db dicts ใน `_process_item()`, update `SYSTEM_PROMPT` |
| `line-secretary/cache.py` | เพิ่ม `force_refresh() -> int` |
| `line-secretary/main.py` | เพิ่ม `/refresh` handler, `_push_long()` helper, replace final reply push, update `/help` |
| `line-secretary/tests/test_quick_wins.py` | New — tests ทั้ง 3 features |

---

## Task 1: URL in Answers

**Files:**
- Modify: `line-secretary/agent.py`
- Test: `line-secretary/tests/test_quick_wins.py`

- [ ] **Step 1: Write failing tests**

Create `line-secretary/tests/test_quick_wins.py`:
```python
import agent


# ── URL in context ────────────────────────────────────────────────

def test_rank_context_preserves_url():
    pages = [
        {"id": "abc-123", "title": "API Token", "content": "groq key here", "url": "https://notion.so/abc123"}
    ]
    result = agent._rank_context({"pages": pages, "databases": []}, ["groq"], 50000)
    assert result["pages"][0].get("url") == "https://notion.so/abc123"


def test_rank_context_preserves_db_url():
    dbs = [
        {"id": "db-1", "title": "Passwords", "rows": [], "url": "https://notion.so/db1"}
    ]
    result = agent._rank_context({"pages": [], "databases": dbs}, ["pass"], 50000)
    assert result["databases"][0].get("url") == "https://notion.so/db1"


def test_system_prompt_has_url_instruction():
    assert "🔗" in agent.SYSTEM_PROMPT
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd line-secretary && python3 -m pytest tests/test_quick_wins.py::test_rank_context_preserves_url tests/test_quick_wins.py::test_rank_context_preserves_db_url tests/test_quick_wins.py::test_system_prompt_has_url_instruction -v
```
Expected: `test_rank_context_preserves_url` FAIL (no `url` key), `test_system_prompt_has_url_instruction` FAIL

- [ ] **Step 3: Add `url` field in `_process_item()` in `agent.py`**

Find `_process_item()` (line ~344). Replace the entire function body with:

```python
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
```

- [ ] **Step 4: Update `SYSTEM_PROMPT` in `agent.py`**

Find this line in `SYSTEM_PROMPT`:
```
- If the data contains the answer, state it clearly and mention which Notion page or database it came from (e.g. "จาก page API Token")
```

Replace with:
```
- If the data contains the answer, state it clearly, mention which page it came from, and end your reply on a new line with 🔗 followed by the page URL from the Notion data (e.g. "🔗 https://notion.so/abc123"). Use the `url` field from the matching page or database in the data.
```

- [ ] **Step 5: Run tests — expect pass**

```bash
cd line-secretary && python3 -m pytest tests/test_quick_wins.py::test_rank_context_preserves_url tests/test_quick_wins.py::test_rank_context_preserves_db_url tests/test_quick_wins.py::test_system_prompt_has_url_instruction -v
```
Expected: 3 passed

- [ ] **Step 6: Run all tests — no regressions**

```bash
cd line-secretary && python3 -m pytest tests/ -v 2>&1 | tail -5
```
Expected: 21 passed

- [ ] **Step 7: Commit**

```bash
git add line-secretary/agent.py line-secretary/tests/test_quick_wins.py
git commit -m "feat(line-secretary): include Notion page URL in agent replies"
```

---

## Task 2: `/refresh` Command

**Files:**
- Modify: `line-secretary/cache.py`
- Modify: `line-secretary/main.py`
- Test: `line-secretary/tests/test_quick_wins.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `line-secretary/tests/test_quick_wins.py`:
```python
import pytest
from cache import PageCache


# ── /refresh ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_force_refresh_calls_rebuild_and_returns_count():
    c = PageCache()
    c._token = "test_token"

    async def mock_rebuild(self=None):
        c._pages = [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]

    c._rebuild = mock_rebuild
    n = await c.force_refresh()

    assert n == 3


@pytest.mark.asyncio
async def test_force_refresh_replaces_stale_pages():
    c = PageCache()
    c._token = "test_token"
    c._pages = [{"id": "old"}]

    async def mock_rebuild(self=None):
        c._pages = [{"id": "new1"}, {"id": "new2"}]

    c._rebuild = mock_rebuild
    n = await c.force_refresh()

    assert n == 2
    assert c._pages[0]["id"] == "new1"
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd line-secretary && python3 -m pytest tests/test_quick_wins.py::test_force_refresh_calls_rebuild_and_returns_count -v
```
Expected: `AttributeError: 'PageCache' object has no attribute 'force_refresh'`

- [ ] **Step 3: Add `force_refresh()` to `cache.py`**

In `line-secretary/cache.py`, add this method inside `PageCache` class, after `get_header()`:

```python
    async def force_refresh(self) -> int:
        """Immediately rebuild the cache. Returns number of pages indexed."""
        await self._rebuild()
        return len(self._pages)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd line-secretary && python3 -m pytest tests/test_quick_wins.py::test_force_refresh_calls_rebuild_and_returns_count tests/test_quick_wins.py::test_force_refresh_replaces_stale_pages -v
```
Expected: 2 passed

- [ ] **Step 5: Add `/refresh` handler to `main.py`**

In `line-secretary/main.py`, find the `/provider` handler:
```python
    # /provider → show active provider and failover status
    if text == "/provider":
```

Insert this block immediately **before** that line:

```python
    # /refresh → force immediate cache rebuild
    if text == "/refresh":
        try:
            n = await _cache.force_refresh()
            await line_client.push(user_id, f"รีเฟรช cache เรียบร้อยค่ะ 🔄 ({n} pages)", token)
        except Exception as e:
            logger.error(f"force_refresh error: {e}", exc_info=True)
            await line_client.push(user_id, "รีเฟรช cache ไม่สำเร็จค่ะ ลองใหม่อีกครั้งนะคะ", token)
        return

```

- [ ] **Step 6: Add `/refresh` to `/help` text in `main.py`**

Find this line in the `/help` handler:
```python
            "/clear — ล้างประวัติสนทนา + pending (ใช้เมื่อบอทติด)\n"
```

Replace with:
```python
            "/clear — ล้างประวัติสนทนา + pending (ใช้เมื่อบอทติด)\n"
            "/refresh — รีเฟรช Notion page cache ทันที\n"
```

- [ ] **Step 7: Run all tests**

```bash
cd line-secretary && python3 -m pytest tests/ -v 2>&1 | tail -5
```
Expected: 23 passed

- [ ] **Step 8: Commit**

```bash
git add line-secretary/cache.py line-secretary/main.py line-secretary/tests/test_quick_wins.py
git commit -m "feat(line-secretary): add /refresh command to force cache rebuild"
```

---

## Task 3: Long Reply Splitter

**Files:**
- Modify: `line-secretary/main.py`
- Test: `line-secretary/tests/test_quick_wins.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `line-secretary/tests/test_quick_wins.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch
import main


# ── _push_long ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_push_long_short_text_single_call():
    with patch("line_client.push", new_callable=AsyncMock) as mock_push:
        await main._push_long("U1", "สั้นๆ", "tok")
    mock_push.assert_called_once_with("U1", "สั้นๆ", "tok")


@pytest.mark.asyncio
async def test_push_long_exactly_at_limit_single_call():
    with patch("line_client.push", new_callable=AsyncMock) as mock_push:
        text = "x" * 4000
        await main._push_long("U1", text, "tok", max_len=4000)
    mock_push.assert_called_once()
    assert len(mock_push.call_args[0][1]) == 4000


@pytest.mark.asyncio
async def test_push_long_over_limit_splits():
    with patch("line_client.push", new_callable=AsyncMock) as mock_push:
        text = "x" * 8001
        await main._push_long("U1", text, "tok", max_len=4000)
    assert mock_push.call_count == 3
    assert len(mock_push.call_args_list[0][0][1]) == 4000
    assert len(mock_push.call_args_list[1][0][1]) == 4000
    assert len(mock_push.call_args_list[2][0][1]) == 1


@pytest.mark.asyncio
async def test_push_long_empty_string():
    with patch("line_client.push", new_callable=AsyncMock) as mock_push:
        await main._push_long("U1", "", "tok")
    mock_push.assert_called_once_with("U1", "", "tok")
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd line-secretary && python3 -m pytest tests/test_quick_wins.py::test_push_long_short_text_single_call -v
```
Expected: `AttributeError: module 'main' has no attribute '_push_long'`

- [ ] **Step 3: Add `_push_long()` to `main.py`**

In `line-secretary/main.py`, add after the `_is_note_intent()` function (around line 43):

```python
async def _push_long(user_id: str, text: str, token: str, max_len: int = 4000) -> None:
    """Send text as one or more LINE messages, splitting at max_len chars."""
    if len(text) <= max_len:
        await line_client.push(user_id, text, token)
        return
    for i in range(0, len(text), max_len):
        await line_client.push(user_id, text[i:i + max_len], token)
```

- [ ] **Step 4: Replace final reply push in `handle_message()`**

At the very end of `handle_message()`, find:
```python
    await line_client.push(user_id, reply, token)
```

Replace with:
```python
    await _push_long(user_id, reply, token)
```

- [ ] **Step 5: Run tests — expect pass**

```bash
cd line-secretary && python3 -m pytest tests/test_quick_wins.py -v 2>&1 | grep -E "PASSED|FAILED|ERROR"
```
Expected: all 4 `_push_long` tests PASSED

- [ ] **Step 6: Run all tests**

```bash
cd line-secretary && python3 -m pytest tests/ -v 2>&1 | tail -5
```
Expected: 27 passed

- [ ] **Step 7: Commit**

```bash
git add line-secretary/main.py line-secretary/tests/test_quick_wins.py
git commit -m "feat(line-secretary): add _push_long to handle LINE 5000-char limit"
```

---

## Self-Review

**Spec coverage:**
- [x] URL in answers → Task 1 (`_process_item` + `SYSTEM_PROMPT`)
- [x] `/refresh` command → Task 2 (`force_refresh` + handler + help text)
- [x] Long reply splitter → Task 3 (`_push_long` + replace final push)

**Placeholder scan:** No TBD/TODO found.

**Type consistency:**
- `force_refresh() -> int` defined in Task 2 Step 3, called in Task 2 Step 5 — match ✓
- `_push_long(user_id, text, token, max_len=4000)` defined in Task 3 Step 3, called in Task 3 Step 4 — match ✓
- `url` key added in Task 1 Step 3, checked in test Task 1 Step 1 — match ✓
