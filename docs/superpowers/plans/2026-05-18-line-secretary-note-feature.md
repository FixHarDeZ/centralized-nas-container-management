# Line Secretary — Quick Note Feature Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** เพิ่ม note-taking flow ใน LINE bot — ตรวจ intent → ถามหัวข้อ → สร้าง Notion sub-page → รับเนื้อหา → บันทึก

**Architecture:** New `pending_note` state (2 phases) in `store.py` follows the existing `pending`/`pending_general` pattern. Intent detection is pure keyword matching in `main.py`. Notion API gets two new functions (`create_page`, `append_blocks`) in `notion.py`. No LLM involvement in this flow.

**Tech Stack:** Python 3.12 · FastAPI · httpx · pydantic-settings · Notion API · pytest · pytest-asyncio

---

## File Map

| File | Change |
|---|---|
| `line-secretary/requirements.txt` | Add `pytest`, `pytest-asyncio` |
| `line-secretary/tests/__init__.py` | New — empty, marks package |
| `line-secretary/tests/conftest.py` | New — sys.path + env var setup for all tests |
| `line-secretary/tests/test_store_note.py` | New — tests for pending_note CRUD |
| `line-secretary/tests/test_notion_note.py` | New — tests for create_page, append_blocks |
| `line-secretary/tests/test_main_note.py` | New — tests for _is_note_intent |
| `line-secretary/store.py` | Add `pending_note` key to `_state` + 4 CRUD functions |
| `line-secretary/notion.py` | Add `create_page()` + `append_blocks()` |
| `line-secretary/config.py` | Add `NOTION_QUICK_NOTE_PAGE_ID: str = ""` |
| `line-secretary/main.py` | Add `_NOTE_INTENT_KEYWORDS`, `_is_note_intent()`, note flow handler, update `/clear` + `/help` |

---

## Task 1: Test Infrastructure

**Files:**
- Create: `line-secretary/requirements.txt` (modify)
- Create: `line-secretary/tests/__init__.py`
- Create: `line-secretary/tests/conftest.py`

- [ ] **Step 1: Add test dependencies to requirements.txt**

Open `line-secretary/requirements.txt` and append:
```
pytest==8.3.4
pytest-asyncio==0.24.0
```

- [ ] **Step 2: Create tests package**

Create `line-secretary/tests/__init__.py` — empty file.

- [ ] **Step 3: Create conftest.py**

Create `line-secretary/tests/conftest.py`:
```python
import os
import sys

# Allow test files to import from line-secretary/
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Set required env vars before any module imports Settings()
os.environ.setdefault("LINE_SECRETARY_CHANNEL_SECRET", "test_secret")
os.environ.setdefault("LINE_SECRETARY_CHANNEL_ACCESS_TOKEN", "test_token")
os.environ.setdefault("LINE_SECRETARY_ALLOWED_USER_IDS", "U123test")
os.environ.setdefault("NOTION_TOKEN", "test_notion_token")
os.environ.setdefault("NOTION_QUICK_NOTE_PAGE_ID", "test-quick-note-page-id")
```

- [ ] **Step 4: Verify pytest discovers conftest**

Run from `line-secretary/`:
```bash
cd line-secretary && python -m pytest tests/ --collect-only
```
Expected: `no tests ran` (no tests yet, but no import errors)

- [ ] **Step 5: Commit**

```bash
git add line-secretary/requirements.txt line-secretary/tests/
git commit -m "test: add pytest infrastructure for line-secretary"
```

---

## Task 2: `pending_note` CRUD in `store.py`

**Files:**
- Modify: `line-secretary/store.py`
- Create: `line-secretary/tests/test_store_note.py`

- [ ] **Step 1: Write failing tests**

Create `line-secretary/tests/test_store_note.py`:
```python
import os
import tempfile
import store


def _fresh_store(tmpdir):
    """Re-initialise store with a clean temp directory."""
    store._state["pending"] = {}
    store._state["pending_general"] = {}
    store._state["pending_note"] = {}
    store._state["history"] = {}
    store.init(tmpdir)


def test_pending_note_starts_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        _fresh_store(tmpdir)
        assert not store.has_pending_note("U001")
        assert store.get_pending_note("U001") is None


def test_pending_note_set_and_get():
    with tempfile.TemporaryDirectory() as tmpdir:
        _fresh_store(tmpdir)
        store.set_pending_note("U001", {"phase": "asking_topic"})
        assert store.has_pending_note("U001")
        assert store.get_pending_note("U001") == {"phase": "asking_topic"}


def test_pending_note_overwrite():
    with tempfile.TemporaryDirectory() as tmpdir:
        _fresh_store(tmpdir)
        store.set_pending_note("U001", {"phase": "asking_topic"})
        store.set_pending_note("U001", {"phase": "waiting_content", "page_id": "abc", "title": "T"})
        assert store.get_pending_note("U001")["phase"] == "waiting_content"


def test_pending_note_pop():
    with tempfile.TemporaryDirectory() as tmpdir:
        _fresh_store(tmpdir)
        store.set_pending_note("U001", {"phase": "asking_topic"})
        val = store.pop_pending_note("U001")
        assert val == {"phase": "asking_topic"}
        assert not store.has_pending_note("U001")


def test_pending_note_pop_missing_returns_none():
    with tempfile.TemporaryDirectory() as tmpdir:
        _fresh_store(tmpdir)
        assert store.pop_pending_note("U_MISSING") is None


def test_pending_note_persists_to_disk():
    with tempfile.TemporaryDirectory() as tmpdir:
        _fresh_store(tmpdir)
        store.set_pending_note("U002", {"phase": "waiting_content", "page_id": "p1", "title": "Saved"})

        # Simulate restart: wipe in-memory state and reload from disk
        store._state["pending_note"] = {}
        store.init(tmpdir)

        assert store.has_pending_note("U002")
        assert store.get_pending_note("U002")["title"] == "Saved"


def test_pending_note_does_not_affect_pending():
    with tempfile.TemporaryDirectory() as tmpdir:
        _fresh_store(tmpdir)
        store.set_pending("U003", {"op": "write"})
        store.set_pending_note("U003", {"phase": "asking_topic"})

        store.pop_pending_note("U003")
        assert store.has_pending("U003")
        assert not store.has_pending_note("U003")
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd line-secretary && python -m pytest tests/test_store_note.py -v
```
Expected: `AttributeError: module 'store' has no attribute 'has_pending_note'`

- [ ] **Step 3: Add `pending_note` to `_state` in `store.py`**

In `store.py`, find the `_state` dict (line ~25) and add the new key:
```python
_state: dict = {
    "pending": {},
    "pending_general": {},
    "pending_note": {},
    "history": {},
}
```

(The `init()` function already iterates `_state` keys generically, so `pending_note` is loaded from disk automatically — no other change needed in `init()`.)

- [ ] **Step 4: Add CRUD functions to `store.py`**

Append after the `# ── pending_general ──` block (after line ~100):
```python
# ── pending_note ──────────────────────────────────────────────────

def get_pending_note(user_id: str) -> dict | None:
    return _state["pending_note"].get(user_id)


def set_pending_note(user_id: str, payload: dict) -> None:
    _state["pending_note"][user_id] = payload
    _save()


def pop_pending_note(user_id: str) -> dict | None:
    val = _state["pending_note"].pop(user_id, None)
    if val is not None:
        _save()
    return val


def has_pending_note(user_id: str) -> bool:
    return user_id in _state["pending_note"]
```

- [ ] **Step 5: Run tests — expect all pass**

```bash
cd line-secretary && python -m pytest tests/test_store_note.py -v
```
Expected: `7 passed`

- [ ] **Step 6: Commit**

```bash
git add line-secretary/store.py line-secretary/tests/test_store_note.py
git commit -m "feat(line-secretary): add pending_note state to store"
```

---

## Task 3: `create_page()` in `notion.py`

**Files:**
- Modify: `line-secretary/notion.py`
- Create: `line-secretary/tests/test_notion_note.py`

- [ ] **Step 1: Write failing test**

Create `line-secretary/tests/test_notion_note.py`:
```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import notion


def _mock_client(response_json: dict):
    """Return a context-manager mock for httpx.AsyncClient."""
    mock_response = MagicMock()
    mock_response.json.return_value = response_json

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.patch = AsyncMock(return_value=mock_response)
    return mock_client


@pytest.mark.asyncio
async def test_create_page_calls_correct_endpoint():
    mock_client = _mock_client({"id": "new-page-id", "object": "page", "url": "https://notion.so/x"})

    with patch("httpx.AsyncClient", return_value=mock_client):
        result = await notion.create_page("tok", "parent-page-id", "My Title")

    assert result["id"] == "new-page-id"
    mock_client.post.assert_called_once()
    args, kwargs = mock_client.post.call_args
    assert args[0].endswith("/pages")
    assert kwargs["json"]["parent"]["page_id"] == "parent-page-id"
    title_content = kwargs["json"]["properties"]["title"]["title"][0]["text"]["content"]
    assert title_content == "My Title"


@pytest.mark.asyncio
async def test_append_blocks_single_line():
    mock_client = _mock_client({"results": []})

    with patch("httpx.AsyncClient", return_value=mock_client):
        await notion.append_blocks("tok", "page-id", "Hello world")

    args, kwargs = mock_client.patch.call_args
    children = kwargs["json"]["children"]
    assert len(children) == 1
    assert children[0]["type"] == "paragraph"
    assert children[0]["paragraph"]["rich_text"][0]["text"]["content"] == "Hello world"


@pytest.mark.asyncio
async def test_append_blocks_multiline():
    mock_client = _mock_client({"results": []})

    with patch("httpx.AsyncClient", return_value=mock_client):
        await notion.append_blocks("tok", "page-id", "Line 1\nLine 2\nLine 3")

    args, kwargs = mock_client.patch.call_args
    children = kwargs["json"]["children"]
    assert len(children) == 3
    assert children[0]["paragraph"]["rich_text"][0]["text"]["content"] == "Line 1"
    assert children[2]["paragraph"]["rich_text"][0]["text"]["content"] == "Line 3"


@pytest.mark.asyncio
async def test_append_blocks_skips_empty_lines():
    mock_client = _mock_client({"results": []})

    with patch("httpx.AsyncClient", return_value=mock_client):
        await notion.append_blocks("tok", "page-id", "A\n\n\nB")

    args, kwargs = mock_client.patch.call_args
    children = kwargs["json"]["children"]
    assert len(children) == 2
    assert children[0]["paragraph"]["rich_text"][0]["text"]["content"] == "A"
    assert children[1]["paragraph"]["rich_text"][0]["text"]["content"] == "B"


@pytest.mark.asyncio
async def test_append_blocks_all_whitespace_falls_back():
    mock_client = _mock_client({"results": []})

    with patch("httpx.AsyncClient", return_value=mock_client):
        await notion.append_blocks("tok", "page-id", "   \n  \n   ")

    args, kwargs = mock_client.patch.call_args
    children = kwargs["json"]["children"]
    # Falls back to original text as single block
    assert len(children) == 1


@pytest.mark.asyncio
async def test_append_blocks_truncates_long_line():
    mock_client = _mock_client({"results": []})
    long_line = "x" * 3000

    with patch("httpx.AsyncClient", return_value=mock_client):
        await notion.append_blocks("tok", "page-id", long_line)

    args, kwargs = mock_client.patch.call_args
    children = kwargs["json"]["children"]
    assert len(children[0]["paragraph"]["rich_text"][0]["text"]["content"]) == 2000
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd line-secretary && python -m pytest tests/test_notion_note.py -v
```
Expected: `AttributeError: module 'notion' has no attribute 'create_page'` (or similar)

- [ ] **Step 3: Add `create_page()` to `notion.py`**

Append to `line-secretary/notion.py` (after the last function):
```python
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


async def append_blocks(token: str, page_id: str, text: str) -> dict:
    lines = [line[:2000] for line in text.split("\n") if line.strip()]
    if not lines:
        lines = [text[:2000]]
    children = [
        {
            "object": "block",
            "type": "paragraph",
            "paragraph": {
                "rich_text": [{"type": "text", "text": {"content": line}}]
            },
        }
        for line in lines[:100]
    ]
    async with httpx.AsyncClient() as client:
        r = await client.patch(
            f"{NOTION_API}/blocks/{page_id}/children",
            headers=_headers(token),
            json={"children": children},
            timeout=15,
        )
        return r.json()
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
cd line-secretary && python -m pytest tests/test_notion_note.py -v
```
Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add line-secretary/notion.py line-secretary/tests/test_notion_note.py
git commit -m "feat(line-secretary): add create_page and append_blocks to notion.py"
```

---

## Task 4: `NOTION_QUICK_NOTE_PAGE_ID` in `config.py`

**Files:**
- Modify: `line-secretary/config.py`

- [ ] **Step 1: Add field to Settings**

In `line-secretary/config.py`, add `NOTION_QUICK_NOTE_PAGE_ID` before `DATA_DIR`:
```python
class Settings(BaseSettings):
    LINE_SECRETARY_CHANNEL_SECRET: str
    LINE_SECRETARY_CHANNEL_ACCESS_TOKEN: str
    LINE_SECRETARY_ALLOWED_USER_IDS: str
    NOTION_TOKEN: str

    AI_PROVIDER: str = "auto"
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""

    NOTION_QUICK_NOTE_PAGE_ID: str = ""

    DATA_DIR: str = "/data"

    model_config = SettingsConfigDict(extra="ignore")

    @property
    def allowed_user_ids(self) -> set[str]:
        return {uid.strip() for uid in self.LINE_SECRETARY_ALLOWED_USER_IDS.split(",")}
```

- [ ] **Step 2: Verify import still works**

```bash
cd line-secretary && python -c "from config import settings; print('ok')"
```
Expected: `ok` (will use env vars or defaults — `NOTION_QUICK_NOTE_PAGE_ID` defaults to `""`)

- [ ] **Step 3: Commit**

```bash
git add line-secretary/config.py
git commit -m "feat(line-secretary): add NOTION_QUICK_NOTE_PAGE_ID to config"
```

---

## Task 5: `_is_note_intent()` in `main.py`

**Files:**
- Modify: `line-secretary/main.py`
- Create: `line-secretary/tests/test_main_note.py`

- [ ] **Step 1: Write failing test**

Create `line-secretary/tests/test_main_note.py`:
```python
import main


def test_note_intent_thai_exact():
    assert main._is_note_intent("จดหน่อย") is True
    assert main._is_note_intent("จดให้หน่อย") is True
    assert main._is_note_intent("จดให้ด้วย") is True
    assert main._is_note_intent("จดด้วย") is True
    assert main._is_note_intent("เตรียมจด") is True
    assert main._is_note_intent("ช่วยจด") is True
    assert main._is_note_intent("จดไว้") is True
    assert main._is_note_intent("บันทึกให้หน่อย") is True


def test_note_intent_english():
    assert main._is_note_intent("note please") is True
    assert main._is_note_intent("please note") is True
    assert main._is_note_intent("help me note") is True
    assert main._is_note_intent("take a note") is True
    assert main._is_note_intent("make a note") is True


def test_note_intent_case_insensitive():
    assert main._is_note_intent("NOTE PLEASE") is True
    assert main._is_note_intent("Take A Note") is True


def test_note_intent_substring_match():
    assert main._is_note_intent("จดหน่อยนะคะ") is True
    assert main._is_note_intent("ช่วยจดให้หน่อยได้ไหม") is True
    assert main._is_note_intent("can you please note this for me") is True


def test_note_intent_no_match():
    assert main._is_note_intent("สวัสดี") is False
    assert main._is_note_intent("ขอ user pass jira") is False
    assert main._is_note_intent("ค่าน้ำ") is False
    assert main._is_note_intent("/clear") is False
    assert main._is_note_intent("") is False
```

- [ ] **Step 2: Run tests — expect failure**

```bash
cd line-secretary && python -m pytest tests/test_main_note.py -v
```
Expected: `AttributeError: module 'main' has no attribute '_is_note_intent'`

- [ ] **Step 3: Add keyword list and function to `main.py`**

In `line-secretary/main.py`, add after the `CANCEL_WORDS` line (after line ~31):
```python
_NOTE_INTENT_KEYWORDS = [
    "จดหน่อย", "จดให้หน่อย", "จดให้ด้วย", "จดด้วย",
    "เตรียมจด", "ช่วยจด", "จดไว้", "บันทึกให้หน่อย",
    "note please", "please note", "help me note", "take a note", "make a note",
]


def _is_note_intent(text: str) -> bool:
    t = text.lower().strip()
    return any(k in t for k in _NOTE_INTENT_KEYWORDS)
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
cd line-secretary && python -m pytest tests/test_main_note.py -v
```
Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add line-secretary/main.py line-secretary/tests/test_main_note.py
git commit -m "feat(line-secretary): add _is_note_intent keyword detection"
```

---

## Task 6: Note Flow Handler in `main.py`

**Files:**
- Modify: `line-secretary/main.py`

- [ ] **Step 1: Add `import store` note functions awareness**

`store` is already imported in `main.py` — no new import needed. Verify `notion as notion_mod` is also already imported (it is, line 8).

- [ ] **Step 2: Update `/clear` to reset `pending_note`**

Find the `/clear` handler block in `handle_message()` (around line 133):
```python
if text == "/clear":
    store.pop_pending(user_id)
    store.pop_pending_general(user_id)
    store.clear_history(user_id)
    await line_client.push(user_id, "ล้างประวัติการสนทนาแล้วค่ะ 🗑️", token)
    return
```

Replace with:
```python
if text == "/clear":
    store.pop_pending(user_id)
    store.pop_pending_general(user_id)
    store.pop_pending_note(user_id)
    store.clear_history(user_id)
    await line_client.push(user_id, "ล้างประวัติการสนทนาแล้วค่ะ 🗑️", token)
    return
```

- [ ] **Step 3: Add note flow handler before `has_pending_general()` check**

Find the comment `# Handle pending general-knowledge confirmation` in `handle_message()` (around line 142). Insert the following block **before** that comment:

```python
    # Handle pending note flow
    if store.has_pending_note(user_id):
        note_state = store.get_pending_note(user_id)

        if note_state["phase"] == "asking_topic":
            title = text.strip()
            if not settings.NOTION_QUICK_NOTE_PAGE_ID:
                store.pop_pending_note(user_id)
                await line_client.push(user_id, "ยังไม่ได้ตั้งค่า Quick note page ค่ะ (NOTION_QUICK_NOTE_PAGE_ID)", token)
                return
            try:
                page = await notion_mod.create_page(
                    settings.NOTION_TOKEN,
                    settings.NOTION_QUICK_NOTE_PAGE_ID,
                    title,
                )
                page_id = page["id"]
            except Exception as e:
                logger.error(f"create_page error: {e}", exc_info=True)
                store.pop_pending_note(user_id)
                await line_client.push(user_id, "สร้าง page ไม่สำเร็จค่ะ ลองใหม่อีกครั้งนะคะ", token)
                return
            store.set_pending_note(user_id, {"phase": "waiting_content", "page_id": page_id, "title": title})
            await line_client.push(user_id, f"สร้าง page '{title}' แล้วค่ะ 📄 ส่งเนื้อหาที่จะจดมาได้เลยค่ะ", token)
            return

        if note_state["phase"] == "waiting_content":
            page_id = note_state["page_id"]
            title = note_state["title"]
            store.pop_pending_note(user_id)
            try:
                await notion_mod.append_blocks(settings.NOTION_TOKEN, page_id, text)
            except Exception as e:
                logger.error(f"append_blocks error: {e}", exc_info=True)
                notion_url = f"https://notion.so/{page_id.replace('-', '')}"
                await line_client.push(
                    user_id,
                    f"บันทึกไม่สำเร็จค่ะ ลองเปิด page โดยตรงที่:\n{notion_url}",
                    token,
                )
                return
            await line_client.push(user_id, f"บันทึกเรียบร้อยแล้วค่ะ ✅", token)
            return

    # Detect note-taking intent
    if _is_note_intent(text):
        store.set_pending_note(user_id, {"phase": "asking_topic"})
        await line_client.push(user_id, "จะจดเรื่องอะไรคะ? 📝", token)
        return
```

- [ ] **Step 4: Update `/help` text**

Find the `/help` handler. Add note-taking documentation after the write confirmation line:
```python
    if text == "/help":
        await line_client.push(user_id, (
            "📖 คำสั่งที่ใช้ได้:\n"
            "/help — แสดงคำสั่งทั้งหมดนี้\n"
            "/clear — ล้างประวัติสนทนา + pending (ใช้เมื่อบอทติด)\n"
            "/provider — ดู AI provider ที่ใช้งานอยู่\n"
            "/debug <query> — ค้นหา Notion ดิบๆ\n"
            "/debug2 <query> — deep search (รวม embedded tables)\n"
            "/debug3 <page_id> — ดู raw blocks ของ page\n"
            "/debug4 <db_id> — ดู raw rows ของ database\n\n"
            "📝 จดโน้ต:\n"
            "จดหน่อย / note please / take a note — เริ่มจดลง Quick note\n\n"
            "💬 วิธีใช้งาน:\n"
            "• ถามข้อมูล: \"ขอ user pass Jira\", \"API token ของ groq คืออะไร\"\n"
            "• เพิ่มข้อมูล: \"เพิ่ม api token...\", \"บันทึก...\"\n"
            "• แก้ไขข้อมูล: \"แก้ ... ให้เป็น ...\"\n"
            "• ลบข้อมูล: \"ลบ ... ออก\"\n\n"
            "⚠️ ทุก write (เพิ่ม/แก้/ลบ) ต้องยืนยันด้วย 'ใช่' ก่อนเสมอค่ะ"
        ), token)
        return
```

- [ ] **Step 5: Run all tests to verify no regressions**

```bash
cd line-secretary && python -m pytest tests/ -v
```
Expected: all tests pass (7 + 6 + 5 = 18 passed)

- [ ] **Step 6: Commit**

```bash
git add line-secretary/main.py
git commit -m "feat(line-secretary): add quick note flow — intent detection + pending_note handler"
```

---

## Task 7: `.env` documentation + README

**Files:**
- Modify: `line-secretary/README.md` (add `NOTION_QUICK_NOTE_PAGE_ID` to env table)

- [ ] **Step 1: Update README env table**

In `line-secretary/README.md`, find the environment variables section and add:
```
| `NOTION_QUICK_NOTE_PAGE_ID` | Notion page ID ของ "Quick note" page (parent สำหรับ note feature) | Optional — note feature จะ error ถ้าไม่ตั้ง |
```

- [ ] **Step 2: Add env var to root `.env` (local only — do NOT commit)**

```env
NOTION_QUICK_NOTE_PAGE_ID=<paste-your-quick-note-page-id-here>
```

หา page ID ของ Quick note: เปิด Notion → Quick note page → copy link → ID คือส่วนหลังสุดของ URL (32 hex chars)

- [ ] **Step 3: Commit README only**

```bash
git add line-secretary/README.md
git commit -m "docs(line-secretary): document NOTION_QUICK_NOTE_PAGE_ID env var"
```

---

## Self-Review

**Spec coverage:**
- [x] Intent keywords (จดหน่อย, note please, etc.) → Task 5 + 6
- [x] Bot asks topic → Task 6 Step 3 (`asking_topic` phase)
- [x] Create Notion page with topic as title → Task 3 + Task 6 Step 3
- [x] Wait for content → Task 6 Step 3 (`waiting_content` phase)
- [x] Append content as paragraph blocks → Task 3 + Task 6 Step 3
- [x] `/clear` resets pending_note → Task 6 Step 2
- [x] `NOTION_QUICK_NOTE_PAGE_ID` env var → Task 4 + Task 7
- [x] Error handling: page create fail → Task 6 Step 3
- [x] Error handling: append fail → Task 6 Step 3 (returns Notion URL)
- [x] Error handling: env var not set → Task 6 Step 3
- [x] `/help` updated → Task 6 Step 4

**Placeholder scan:** No TBD/TODO found.

**Type consistency:** `pending_note` payload `{"phase": ..., "page_id": ..., "title": ...}` used consistently across Task 2 (store), Task 6 (main handler). `store.get_pending_note` / `store.set_pending_note` / `store.pop_pending_note` / `store.has_pending_note` match across all tasks.
