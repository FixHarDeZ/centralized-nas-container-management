# line-secretary Note Extensions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** ต่อยอด Quick Note feature — เพิ่ม `/note` command ดูรายการ notes ล่าสุด และ trigger "เพิ่มใน [ชื่อ]" สำหรับ append content เข้า existing note page

**Architecture:** เพิ่ม `list_child_pages()` ใน `notion.py` สำหรับดึง sub-pages, `/note` handler ใน `main.py` ใช้ function นี้โดยตรง, append-to-existing flow ใช้ `pending_note` state เดิมแต่ข้าม `asking_topic` phase ไปเลย (set `waiting_content` ทันที)

**Tech Stack:** Python 3.12 · FastAPI · httpx · pytest · pytest-asyncio

**Prerequisite:** plan `2026-05-18-line-secretary-note-feature.md` ต้อง merged ก่อน (pending_note state + create_page + append_blocks ต้องมีอยู่แล้ว)

---

## File Map

| File | Change |
|---|---|
| `line-secretary/notion.py` | เพิ่ม `list_child_pages()` |
| `line-secretary/main.py` | เพิ่ม `/note` handler, `_parse_append_note()`, append-to-existing handler |
| `line-secretary/tests/test_note_extensions.py` | New — tests ทั้ง 2 features |

---

## Task 1: `list_child_pages()` in `notion.py`

**Files:**
- Modify: `line-secretary/notion.py`
- Test: `line-secretary/tests/test_note_extensions.py`

- [ ] **Step 1: Write failing tests**

Create `line-secretary/tests/test_note_extensions.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import notion


def _mock_get_client(response_json: dict):
    """Mock for httpx.AsyncClient GET requests."""
    mock_response = MagicMock()
    mock_response.json.return_value = response_json
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.get = AsyncMock(return_value=mock_response)
    return mock_client


# ── list_child_pages ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_child_pages_returns_only_child_pages():
    mock_client = _mock_get_client({
        "results": [
            {"id": "p1", "type": "child_page", "child_page": {"title": "ค่าน้ำ"}},
            {"id": "b1", "type": "paragraph", "paragraph": {"rich_text": []}},
            {"id": "p2", "type": "child_page", "child_page": {"title": "ค่าไฟ"}},
            {"id": "d1", "type": "child_database", "child_database": {"title": "DB"}},
        ]
    })
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await notion.list_child_pages("tok", "parent-id")
    assert len(result) == 2
    assert result[0] == {"id": "p1", "title": "ค่าน้ำ"}
    assert result[1] == {"id": "p2", "title": "ค่าไฟ"}


@pytest.mark.asyncio
async def test_list_child_pages_empty_when_no_child_pages():
    mock_client = _mock_get_client({"results": [
        {"id": "b1", "type": "paragraph", "paragraph": {"rich_text": []}}
    ]})
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await notion.list_child_pages("tok", "parent-id")
    assert result == []


@pytest.mark.asyncio
async def test_list_child_pages_handles_missing_title():
    mock_client = _mock_get_client({"results": [
        {"id": "p1", "type": "child_page", "child_page": {}}
    ]})
    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await notion.list_child_pages("tok", "parent-id")
    assert result == [{"id": "p1", "title": "(ไม่มีชื่อ)"}]


@pytest.mark.asyncio
async def test_list_child_pages_calls_correct_endpoint():
    mock_client = _mock_get_client({"results": []})
    with patch("httpx.AsyncClient", return_value=mock_client):
        await notion.list_child_pages("my-token", "page-abc-123")
    args, kwargs = mock_client.get.call_args
    assert args[0].endswith("/blocks/page-abc-123/children")
    assert kwargs["headers"]["Authorization"] == "Bearer my-token"
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd line-secretary && python3 -m pytest tests/test_note_extensions.py -v
```
Expected: `AttributeError: module 'notion' has no attribute 'list_child_pages'`

- [ ] **Step 3: Add `list_child_pages()` to `notion.py`**

Append to the end of `line-secretary/notion.py`:
```python
async def list_child_pages(token: str, parent_page_id: str) -> list[dict]:
    """Return direct child pages (not databases) of a page."""
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{NOTION_API}/blocks/{parent_page_id}/children",
            headers=_headers(token),
            timeout=15,
        )
    blocks = r.json().get("results", [])
    return [
        {
            "id": b["id"],
            "title": b.get("child_page", {}).get("title") or "(ไม่มีชื่อ)",
        }
        for b in blocks
        if b.get("type") == "child_page"
    ]
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd line-secretary && python3 -m pytest tests/test_note_extensions.py -v
```
Expected: 4 passed

- [ ] **Step 5: Run all tests**

```bash
cd line-secretary && python3 -m pytest tests/ -v 2>&1 | tail -5
```
Expected: passes (number depends on quick-wins plan completion)

- [ ] **Step 6: Commit**

```bash
git add line-secretary/notion.py line-secretary/tests/test_note_extensions.py
git commit -m "feat(line-secretary): add list_child_pages to notion.py"
```

---

## Task 2: `/note` Command (List Recent Notes)

**Files:**
- Modify: `line-secretary/main.py`
- Test: `line-secretary/tests/test_note_extensions.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `line-secretary/tests/test_note_extensions.py`:
```python
import main


# ── /note command helpers ─────────────────────────────────────────

def test_parse_append_note_thai():
    assert main._parse_append_note("เพิ่มใน ค่าน้ำ") == "ค่าน้ำ"
    assert main._parse_append_note("เพิ่มเนื้อหาใน ค่าไฟ เดือนมีนา") == "ค่าไฟ เดือนมีนา"


def test_parse_append_note_english():
    assert main._parse_append_note("add to note Meeting notes") == "Meeting notes"


def test_parse_append_note_no_match():
    assert main._parse_append_note("จดหน่อย") is None
    assert main._parse_append_note("เพิ่ม api token") is None
    assert main._parse_append_note("") is None
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd line-secretary && python3 -m pytest tests/test_note_extensions.py::test_parse_append_note_thai -v
```
Expected: `AttributeError: module 'main' has no attribute '_parse_append_note'`

- [ ] **Step 3: Add `_parse_append_note()` to `main.py`**

In `line-secretary/main.py`, add `import re` if not already present (it's not in main.py — check first). Then add after the `_is_note_intent()` function:

```python
_APPEND_NOTE_RE = re.compile(
    r"^(?:เพิ่มใน|เพิ่มเนื้อหาใน|add to note)\s+(.+)$",
    re.IGNORECASE,
)


def _parse_append_note(text: str) -> str | None:
    """Return page title if text matches append-to-existing-note pattern, else None."""
    m = _APPEND_NOTE_RE.match(text.strip())
    return m.group(1).strip() if m else None
```

Also add `import re` at the top of `main.py` if missing.

- [ ] **Step 4: Run tests — expect pass**

```bash
cd line-secretary && python3 -m pytest tests/test_note_extensions.py::test_parse_append_note_thai tests/test_note_extensions.py::test_parse_append_note_english tests/test_note_extensions.py::test_parse_append_note_no_match -v
```
Expected: 3 passed

- [ ] **Step 5: Add `/note` handler to `main.py`**

In `line-secretary/main.py`, find the `/refresh` handler (or `/provider` if quick-wins not done). Insert this block immediately before it:

```python
    # /note → list recent Quick note pages
    if text in ("/note", "/note list"):
        if not settings.NOTION_QUICK_NOTE_PAGE_ID:
            await line_client.push(user_id, "ยังไม่ได้ตั้งค่า Quick note page ค่ะ (NOTION_QUICK_NOTE_PAGE_ID)", token)
            return
        try:
            pages = await notion_mod.list_child_pages(
                settings.NOTION_TOKEN,
                settings.NOTION_QUICK_NOTE_PAGE_ID,
            )
        except Exception as e:
            logger.error(f"list_child_pages error: {e}", exc_info=True)
            await line_client.push(user_id, "โหลดรายการ note ไม่สำเร็จค่ะ ลองใหม่อีกครั้งนะคะ", token)
            return
        if not pages:
            await line_client.push(user_id, "ยังไม่มี note ค่ะ 📝\nพิม 'จดหน่อย' เพื่อสร้างใหม่", token)
            return
        lines = [f"📝 Quick notes ({len(pages)} รายการ):"]
        for p in pages[:10]:
            lines.append(f"• {p['title']}")
        if len(pages) > 10:
            lines.append(f"... และอีก {len(pages) - 10} รายการ")
        await line_client.push(user_id, "\n".join(lines), token)
        return

```

- [ ] **Step 6: Add `/note` to `/help` text**

Find in `/help` handler:
```python
            "📝 จดโน้ต:\n"
            "จดหน่อย / note please / take a note — เริ่มจดลง Quick note\n\n"
```

Replace with:
```python
            "📝 จดโน้ต:\n"
            "จดหน่อย / note please / take a note — เริ่มจดลง Quick note\n"
            "/note — ดูรายการ Quick notes ล่าสุด\n"
            "เพิ่มใน [ชื่อ] — เพิ่มเนื้อหาเข้า note ที่มีอยู่\n\n"
```

- [ ] **Step 7: Run all tests**

```bash
cd line-secretary && python3 -m pytest tests/ -v 2>&1 | tail -5
```
Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add line-secretary/main.py line-secretary/tests/test_note_extensions.py
git commit -m "feat(line-secretary): add /note list command and _parse_append_note"
```

---

## Task 3: Append to Existing Note

**Files:**
- Modify: `line-secretary/main.py`

หมายเหตุ: task นี้ไม่เพิ่ม Notion API ใหม่ — ใช้ `list_child_pages()` (Task 1) + `append_blocks()` (existing) + `pending_note` state เดิม

- [ ] **Step 1: เข้าใจ flow ก่อน implement**

Flow ใหม่:
```
user: "เพิ่มใน ค่าน้ำ"
  → _parse_append_note() = "ค่าน้ำ"
  → list_child_pages() → หา page ชื่อ "ค่าน้ำ"
  → ถ้าเจอ: set pending_note = {"phase": "waiting_content", "page_id": "...", "title": "ค่าน้ำ"}
             reply: "เจอ page 'ค่าน้ำ' แล้วค่ะ 📄 ส่งเนื้อหาที่จะเพิ่มมาได้เลยค่ะ"
  → ถ้าไม่เจอ: reply: "ไม่เจอ page 'ค่าน้ำ' ค่ะ ลองพิม 'จดหน่อย' เพื่อสร้างใหม่นะคะ"

user: "200 บาท จ่าย 15/5"
  → pending_note["phase"] == "waiting_content" → append_blocks → confirm (existing handler)
```

Title matching: case-insensitive, strip whitespace — `title.lower().strip() == query.lower().strip()`

- [ ] **Step 2: Add append-to-existing handler in `main.py`**

In `handle_message()`, find the `# Detect note-taking intent` block:
```python
    # Detect note-taking intent
    if _is_note_intent(text):
```

Insert this block immediately **before** `# Detect note-taking intent`:

```python
    # Detect append-to-existing-note intent
    append_title = _parse_append_note(text)
    if append_title:
        if not settings.NOTION_QUICK_NOTE_PAGE_ID:
            await line_client.push(user_id, "ยังไม่ได้ตั้งค่า Quick note page ค่ะ (NOTION_QUICK_NOTE_PAGE_ID)", token)
            return
        try:
            pages = await notion_mod.list_child_pages(
                settings.NOTION_TOKEN,
                settings.NOTION_QUICK_NOTE_PAGE_ID,
            )
        except Exception as e:
            logger.error(f"list_child_pages error: {e}", exc_info=True)
            await line_client.push(user_id, "โหลดรายการ note ไม่สำเร็จค่ะ ลองใหม่อีกครั้งนะคะ", token)
            return
        matched = next(
            (p for p in pages if p["title"].lower().strip() == append_title.lower().strip()),
            None,
        )
        if matched is None:
            await line_client.push(
                user_id,
                f"ไม่เจอ page '{append_title}' ค่ะ ลองพิม 'จดหน่อย' เพื่อสร้างใหม่นะคะ",
                token,
            )
            return
        store.set_pending_note(user_id, {
            "phase": "waiting_content",
            "page_id": matched["id"],
            "title": matched["title"],
        })
        await line_client.push(
            user_id,
            f"เจอ page '{matched['title']}' แล้วค่ะ 📄 ส่งเนื้อหาที่จะเพิ่มมาได้เลยค่ะ",
            token,
        )
        return

```

- [ ] **Step 3: Run all tests**

```bash
cd line-secretary && python3 -m pytest tests/ -v 2>&1 | tail -5
```
Expected: all pass (no new tests needed — _parse_append_note already tested in Task 2)

- [ ] **Step 4: Commit**

```bash
git add line-secretary/main.py
git commit -m "feat(line-secretary): add append-to-existing note flow (เพิ่มใน [ชื่อ])"
```

---

## Self-Review

**Spec coverage:**
- [x] `list_child_pages()` → Task 1
- [x] `/note` command → Task 2 Step 5
- [x] `_parse_append_note()` → Task 2 Step 3
- [x] Append-to-existing flow → Task 3
- [x] `/help` updated → Task 2 Step 6
- [x] NOTION_QUICK_NOTE_PAGE_ID guard in all new paths → Task 2 Step 5, Task 3 Step 2

**Placeholder scan:** ไม่มี TBD/TODO

**Type consistency:**
- `list_child_pages(token, parent_page_id) -> list[dict]` defined Task 1 Step 3, used Task 2 Step 5 + Task 3 Step 2 — match ✓
- `_parse_append_note(text) -> str | None` defined Task 2 Step 3, tested Task 2 Step 1, used Task 3 Step 2 — match ✓
- `pending_note` payload `{"phase": "waiting_content", "page_id": ..., "title": ...}` — same shape as existing note flow — match ✓
