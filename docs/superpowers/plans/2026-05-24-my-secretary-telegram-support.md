# my-secretary Telegram Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /webhook/telegram` to my-secretary so it responds to Telegram messages using the same agent + Notion logic as LINE, with state isolated per platform via `tg_{chat_id}` key namespace.

**Architecture:** Extract platform-specific concerns (user_id, push_fn) to each webhook handler; refactor `handle_message(user_id, text, push_fn)` to be platform-agnostic; add `telegram_client.py` for Telegram Bot API calls; register Telegram webhook on startup.

**Tech Stack:** FastAPI, httpx, python-telegram-bot token via REST (no SDK), pydantic-settings, pytest-asyncio

---

## File Map

| File | Action | Change |
|---|---|---|
| `my-secretary/telegram_client.py` | Create | `send_message()` + `register_webhook()` |
| `my-secretary/config.py` | Modify | Add `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_ALLOWED_CHAT_IDS` |
| `my-secretary/main.py` | Modify | Refactor `_push_long`, `handle_message`, `handle_non_text_message`; update LINE webhook; add Telegram webhook; update lifespan |
| `my-secretary/.env.example` | Modify | Add Telegram section |
| `my-secretary/tests/conftest.py` | Modify | Add Telegram env defaults |
| `my-secretary/tests/test_telegram.py` | Create | Tests for client + webhook endpoint |
| `my-secretary/README.md` | Modify | Add Telegram setup section |
| `README.md` (root) | Modify | Update my-secretary row description |

---

## Task 1: `telegram_client.py` — Telegram Bot API client

**Files:**
- Create: `my-secretary/telegram_client.py`
- Create: `my-secretary/tests/test_telegram.py`

- [ ] **Step 1.1: Write failing tests for `send_message`**

Create `my-secretary/tests/test_telegram.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch, call
import telegram_client


@pytest.mark.asyncio
async def test_send_message_short():
    with patch("telegram_client.httpx.AsyncClient") as MockClient:
        mock_post = AsyncMock()
        MockClient.return_value.__aenter__.return_value.post = mock_post
        await telegram_client.send_message(12345, "hello", "TOKEN")
        mock_post.assert_called_once_with(
            "https://api.telegram.org/botTOKEN/sendMessage",
            json={"chat_id": 12345, "text": "hello"},
            timeout=10,
        )


@pytest.mark.asyncio
async def test_send_message_splits_at_4096():
    long_text = "x" * 5000
    with patch("telegram_client.httpx.AsyncClient") as MockClient:
        mock_post = AsyncMock()
        MockClient.return_value.__aenter__.return_value.post = mock_post
        await telegram_client.send_message(12345, long_text, "TOKEN")
        assert mock_post.call_count == 2
        first_call_text = mock_post.call_args_list[0].kwargs["json"]["text"]
        second_call_text = mock_post.call_args_list[1].kwargs["json"]["text"]
        assert len(first_call_text) == 4096
        assert len(second_call_text) == 904
        assert first_call_text + second_call_text == long_text


@pytest.mark.asyncio
async def test_register_webhook():
    with patch("telegram_client.httpx.AsyncClient") as MockClient:
        mock_resp = AsyncMock()
        mock_resp.raise_for_status = AsyncMock()
        mock_post = AsyncMock(return_value=mock_resp)
        MockClient.return_value.__aenter__.return_value.post = mock_post
        await telegram_client.register_webhook("TOKEN", "https://nas:8443/webhook/telegram", "SECRET")
        mock_post.assert_called_once_with(
            "https://api.telegram.org/botTOKEN/setWebhook",
            json={
                "url": "https://nas:8443/webhook/telegram",
                "secret_token": "SECRET",
                "allowed_updates": ["message"],
            },
            timeout=15,
        )
        mock_resp.raise_for_status.assert_called_once()
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd my-secretary && python -m pytest tests/test_telegram.py -v
```

Expected: `ModuleNotFoundError: No module named 'telegram_client'`

- [ ] **Step 1.3: Create `telegram_client.py`**

```python
import httpx

TELEGRAM_API = "https://api.telegram.org"


async def send_message(chat_id: int, text: str, token: str) -> None:
    async with httpx.AsyncClient() as client:
        for i in range(0, len(text), 4096):
            await client.post(
                f"{TELEGRAM_API}/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": text[i:i + 4096]},
                timeout=10,
            )


async def register_webhook(token: str, url: str, secret_token: str) -> None:
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{TELEGRAM_API}/bot{token}/setWebhook",
            json={
                "url": url,
                "secret_token": secret_token,
                "allowed_updates": ["message"],
            },
            timeout=15,
        )
        r.raise_for_status()
```

- [ ] **Step 1.4: Run tests to verify they pass**

```bash
cd my-secretary && python -m pytest tests/test_telegram.py -v
```

Expected: 3 passed

- [ ] **Step 1.5: Commit**

```bash
git add my-secretary/telegram_client.py my-secretary/tests/test_telegram.py
git commit -m "feat(my-secretary): add telegram_client with send_message + register_webhook"
```

---

## Task 2: `config.py` — add Telegram settings

**Files:**
- Modify: `my-secretary/config.py`
- Modify: `my-secretary/tests/conftest.py`

- [ ] **Step 2.1: Add tests for new settings**

Append to `my-secretary/tests/test_telegram.py`:

```python
from config import Settings


def test_telegram_allowed_chat_ids_parsed():
    s = Settings(
        LINE_SECRETARY_CHANNEL_SECRET="s",
        LINE_SECRETARY_CHANNEL_ACCESS_TOKEN="t",
        LINE_SECRETARY_ALLOWED_USER_IDS="U1",
        NOTION_TOKEN="n",
        TELEGRAM_ALLOWED_CHAT_IDS="111,222, 333",
    )
    assert s.telegram_allowed_chat_ids == {"111", "222", "333"}


def test_telegram_allowed_chat_ids_empty():
    s = Settings(
        LINE_SECRETARY_CHANNEL_SECRET="s",
        LINE_SECRETARY_CHANNEL_ACCESS_TOKEN="t",
        LINE_SECRETARY_ALLOWED_USER_IDS="U1",
        NOTION_TOKEN="n",
    )
    assert s.telegram_allowed_chat_ids == set()
```

- [ ] **Step 2.2: Run tests to verify they fail**

```bash
cd my-secretary && python -m pytest tests/test_telegram.py::test_telegram_allowed_chat_ids_parsed tests/test_telegram.py::test_telegram_allowed_chat_ids_empty -v
```

Expected: `ValidationError` or `TypeError` — new fields don't exist yet

- [ ] **Step 2.3: Update `config.py`**

Replace the full contents of `my-secretary/config.py`:

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    LINE_SECRETARY_CHANNEL_SECRET: str
    LINE_SECRETARY_CHANNEL_ACCESS_TOKEN: str
    LINE_SECRETARY_ALLOWED_USER_IDS: str  # comma-separated LINE user IDs
    NOTION_TOKEN: str

    AI_PROVIDER: str = "auto"
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""

    NOTION_QUICK_NOTE_PAGE_ID: str = ""

    DATA_DIR: str = "/data"

    # Telegram — optional; disabled if TELEGRAM_BOT_TOKEN is empty
    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_WEBHOOK_URL: str = ""
    TELEGRAM_WEBHOOK_SECRET: str = ""
    TELEGRAM_ALLOWED_CHAT_IDS: str = ""  # comma-separated chat IDs; empty = all allowed

    model_config = SettingsConfigDict(extra="ignore")

    @property
    def allowed_user_ids(self) -> set[str]:
        return {uid.strip() for uid in self.LINE_SECRETARY_ALLOWED_USER_IDS.split(",")}

    @property
    def telegram_allowed_chat_ids(self) -> set[str]:
        if not self.TELEGRAM_ALLOWED_CHAT_IDS:
            return set()
        return {cid.strip() for cid in self.TELEGRAM_ALLOWED_CHAT_IDS.split(",")}


settings = Settings()
```

- [ ] **Step 2.4: Run tests to verify they pass**

```bash
cd my-secretary && python -m pytest tests/test_telegram.py -v
```

Expected: 5 passed

- [ ] **Step 2.5: Commit**

```bash
git add my-secretary/config.py my-secretary/tests/test_telegram.py
git commit -m "feat(my-secretary): add Telegram settings to config"
```

---

## Task 3: Refactor `main.py` — platform-agnostic handlers

Refactor `_push_long`, `handle_message`, `handle_non_text_message`, and the LINE webhook to use `push_fn` callbacks. **No behaviour change for LINE** — existing tests must continue passing.

**Files:**
- Modify: `my-secretary/main.py`

- [ ] **Step 3.1: Run existing tests as baseline**

```bash
cd my-secretary && python -m pytest tests/ -v --ignore=tests/test_telegram.py
```

Record the passing count (should be 27). All must pass after refactor.

- [ ] **Step 3.2: Refactor `_push_long`**

Replace the existing `_push_long` function (lines ~48–54) with:

```python
async def _push_long(text: str, push_fn, max_len: int = 4000) -> None:
    """Send text in chunks, splitting at max_len chars."""
    if len(text) <= max_len:
        await push_fn(text)
        return
    for i in range(0, len(text), max_len):
        await push_fn(text[i:i + max_len])
```

- [ ] **Step 3.3: Refactor `handle_message` signature and body**

Replace the entire `handle_message` function with the version below. Key changes:
- Signature: `(event: dict)` → `(user_id: str, text: str, push_fn)`
- Remove `user_id`, `text`, `token` extraction at the top
- All `await line_client.push(user_id, X, token)` → `await push_fn(X)`
- All `await _push_long(user_id, X, token)` → `await _push_long(X, push_fn)`

```python
async def handle_message(user_id: str, text: str, push_fn) -> None:
    if user_id not in settings.allowed_user_ids and not user_id.startswith("tg_"):
        logger.warning(f"Unauthorized user: {user_id}")
        return

    # Telegram users bypass LINE whitelist — already checked in webhook_telegram
    if user_id.startswith("tg_"):
        pass
    elif user_id not in settings.allowed_user_ids:
        logger.warning(f"Unauthorized user: {user_id}")
        return

    # /debug <query> → raw Notion search
    if text.startswith("/debug "):
        query = text[7:].strip()
        try:
            results = await notion_mod.search(settings.NOTION_TOKEN, query)
            reply = f"[DEBUG] search('{query}'):\n{json.dumps(results, ensure_ascii=False, indent=2)}"
        except Exception as e:
            reply = f"[DEBUG] Error: {e}"
        await push_fn(reply[:4000])
        return

    # /debug2 <query> → full deep search (pages + embedded databases)
    if text.startswith("/debug2 "):
        query = text[8:].strip()
        try:
            result = await agent._deep_search(settings.NOTION_TOKEN, [query])
            reply = f"[DEBUG2] deep_search('{query}'):\n{json.dumps(result, ensure_ascii=False, indent=2)}"
        except Exception as e:
            reply = f"[DEBUG2] Error: {e}"
        await push_fn(reply[:4000])
        return

    # /debug3 <page_id> → raw blocks of a page
    if text.startswith("/debug3 "):
        page_id = text[8:].strip()
        try:
            result = await notion_mod.get_raw_blocks(settings.NOTION_TOKEN, page_id)
            reply = f"[DEBUG3] blocks({page_id[:8]}...):\n{json.dumps(result, ensure_ascii=False, indent=2)}"
        except Exception as e:
            reply = f"[DEBUG3] Error: {e}"
        await push_fn(reply[:4000])
        return

    # /debug4 <db_id> → raw database query
    if text.startswith("/debug4 "):
        db_id = text[8:].strip()
        try:
            result = await notion_mod.query_database_raw(settings.NOTION_TOKEN, db_id)
            reply = f"[DEBUG4] query_db_raw({db_id[:8]}...):\n{json.dumps(result, ensure_ascii=False, indent=2)}"
        except Exception as e:
            reply = f"[DEBUG4] Error: {e}"
        await push_fn(reply[:4000])
        return

    # /refresh → force immediate cache rebuild
    if text == "/refresh":
        try:
            n = await _cache.force_refresh()
            await push_fn(f"รีเฟรช cache เรียบร้อยค่ะ 🔄 ({n} pages)")
        except Exception as e:
            logger.error(f"force_refresh error: {e}", exc_info=True)
            await push_fn("รีเฟรช cache ไม่สำเร็จค่ะ ลองใหม่อีกครั้งนะคะ")
        return

    # /cache → show cache stats
    if text == "/cache":
        s = _cache.stats()
        age = s["age_seconds"]
        if age < 0:
            age_str = "ยังไม่ได้ build"
        elif age < 60:
            age_str = f"{age} วินาที"
        else:
            age_str = f"{age // 60} นาที {age % 60} วิ"
        await push_fn(
            f"Cache: {s['pages']} pages ({s['indexed']} indexed) | อัปเดตเมื่อ {age_str} ที่แล้วค่ะ"
        )
        return

    # /provider → show active provider and failover status
    if text == "/provider":
        await push_fn(_provider.status_text(settings))
        return

    # /help → show available commands and usage tips
    if text == "/help":
        await push_fn(
            "📖 คำสั่งที่ใช้ได้:\n"
            "/help — แสดงคำสั่งทั้งหมดนี้\n"
            "/history — แสดงประวัติสนทนาล่าสุด 4 รอบ\n"
            "/clear — ล้างประวัติสนทนา + pending (ใช้เมื่อบอทติด)\n"
            "/refresh — รีเฟรช Notion page cache ทันที\n"
            "/cache — แสดงสถิติ cache (จำนวน page + เวลาอัปเดต)\n"
            "/provider — ดู AI provider ที่ใช้งานอยู่\n"
            "/debug <query> — ค้นหา Notion ดิบๆ\n"
            "/debug2 <query> — deep search (รวม embedded tables)\n"
            "/debug3 <page_id> — ดู raw blocks ของ page\n"
            "/debug4 <db_id> — ดู raw rows ของ database\n\n"
            "📝 จดโน้ต:\n"
            "จดหน่อย / note please / take a note — เริ่มจดลง Quick note\n"
            "รองรับ Markdown: # หัวข้อ / - bullet / [ ] todo\n\n"
            "💬 วิธีใช้งาน:\n"
            "• ถามข้อมูล: \"ขอ user pass Jira\", \"API token ของ groq คืออะไร\"\n"
            "• เพิ่มข้อมูล: \"เพิ่ม api token...\", \"บันทึก...\"\n"
            "• แก้ไขข้อมูล: \"แก้ ... ให้เป็น ...\"\n"
            "• ลบข้อมูล: \"ลบ ... ออก\"\n\n"
            "⚠️ ทุก write (เพิ่ม/แก้/ลบ) ต้องยืนยันด้วย 'ใช่' ก่อนเสมอค่ะ\n"
            "⏰ pending ที่ไม่ได้ยืนยันจะหมดอายุใน 6 ชั่วโมงอัตโนมัติค่ะ"
        )
        return

    # /history → show last 4 conversation exchanges
    if text == "/history":
        hist = store.get_history(user_id)
        if not hist:
            await push_fn("ยังไม่มีประวัติการสนทนาค่ะ")
            return
        lines = []
        for i in range(0, len(hist) - 1, 2):
            u = hist[i].get("content", "")[:120]
            b = hist[i + 1].get("content", "")[:120] if i + 1 < len(hist) else ""
            lines.append(f"คุณ: {u}\nบอท: {b}")
        await _push_long("📜 ประวัติล่าสุด:\n\n" + "\n\n".join(lines), push_fn)
        return

    # /clear → wipe history + pending for this user (useful when bot gets stuck)
    if text == "/clear":
        store.pop_pending(user_id)
        store.pop_pending_general(user_id)
        store.pop_pending_note(user_id)
        store.clear_history(user_id)
        await push_fn("ล้างประวัติการสนทนาแล้วค่ะ 🗑️")
        return

    # Handle pending note flow
    if store.has_pending_note(user_id):
        note_state = store.get_pending_note(user_id)

        if note_state.get("phase") == "asking_topic":
            title = text.strip()
            if not title:
                await push_fn("กรุณาบอกชื่อหัวข้อด้วยนะคะ 📝")
                return

            all_pages = await _cache.get_pages()
            existing = next((p for p in all_pages if p["title"].strip().lower() == title.lower()), None)
            if not existing:
                try:
                    search_results = await notion_mod.search(settings.NOTION_TOKEN, title)
                    existing = next(
                        (r for r in search_results
                         if r["type"] == "page" and r["title"].strip().lower() == title.lower()),
                        None,
                    )
                except Exception as e:
                    logger.warning(f"Note title search error: {e}")

            if existing:
                store.set_pending_note(user_id, {
                    "phase": "waiting_content",
                    "page_id": existing["id"],
                    "title": existing["title"],
                    "appending": True,
                })
                await push_fn(f"พบ page '{existing['title']}' แล้วค่ะ 📎 ส่งเนื้อหาที่จะเพิ่มมาได้เลยค่ะ")
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
                await push_fn("สร้าง page ไม่สำเร็จค่ะ ลองใหม่อีกครั้งนะคะ")
                return
            store.set_pending_note(user_id, {
                "phase": "waiting_content",
                "page_id": page_id,
                "title": title,
                "appending": False,
            })
            await push_fn(f"สร้าง page '{title}' แล้วค่ะ 📄 ส่งเนื้อหาที่จะจดมาได้เลยค่ะ\n(รองรับ # หัวข้อ / - bullet / [ ] todo)")
            return

        if note_state.get("phase") == "waiting_content":
            page_id = note_state["page_id"]
            title = note_state["title"]
            appending = note_state.get("appending", False)
            store.pop_pending_note(user_id)
            try:
                await notion_mod.append_blocks(settings.NOTION_TOKEN, page_id, text)
            except Exception as e:
                logger.error(f"append_blocks error: {e}", exc_info=True)
                notion_url = f"https://notion.so/{page_id.replace('-', '')}"
                await push_fn(f"บันทึกไม่สำเร็จค่ะ ลองเปิด page โดยตรงที่:\n{notion_url}")
                return
            verb = "เพิ่มเนื้อหาลง" if appending else "บันทึกลง"
            await push_fn(f"{verb} '{title}' เรียบร้อยแล้วค่ะ ✅")
            return

        logger.warning(f"Unknown pending_note phase for {user_id}: {note_state.get('phase')}")
        store.pop_pending_note(user_id)
        await push_fn("เกิดข้อผิดพลาดในขั้นตอนจดโน้ตค่ะ กรุณาเริ่มใหม่อีกครั้ง")
        return

    # Detect note-taking intent
    if _is_note_intent(text):
        if not settings.NOTION_QUICK_NOTE_PAGE_ID:
            await push_fn("ยังไม่ได้ตั้งค่า Quick note page ค่ะ (NOTION_QUICK_NOTE_PAGE_ID)")
            return
        store.set_pending_note(user_id, {"phase": "asking_topic"})
        await push_fn("จะจดเรื่องอะไรคะ? 📝 (บอกชื่อหัวข้อ หรือชื่อ page ที่มีอยู่แล้ว)")
        return

    # Handle pending general-knowledge confirmation
    if store.has_pending_general(user_id):
        lower = text.lower()
        if lower in CONFIRM_WORDS:
            question = store.pop_pending_general(user_id)
            try:
                result = await asyncio.wait_for(
                    agent.run_general(question, store.get_history(user_id)),
                    timeout=AGENT_TIMEOUT,
                )
            except asyncio.TimeoutError:
                await push_fn("ขอโทษค่ะ ใช้เวลานานเกินไป กรุณาลองใหม่อีกครั้งนะคะ")
                return
            except Exception as e:
                logger.error(f"run_general error: {e}", exc_info=True)
                await push_fn("เกิดข้อผิดพลาดค่ะ ลองใหม่อีกครั้งนะคะ")
                return
            reply = result["text"]
            store.add_history(user_id, question, reply)
            await _push_long(reply, push_fn)
            return
        if lower in CANCEL_WORDS:
            store.pop_pending_general(user_id)
            await push_fn("ได้ค่ะ ถ้าต้องการข้อมูลอื่นถามได้เลยนะคะ")
            return
        store.pop_pending_general(user_id)

    # Handle pending write confirmation
    if store.has_pending(user_id):
        lower = text.lower()
        if lower in CONFIRM_WORDS:
            action = store.pop_pending(user_id)
            reply = await agent.execute_write(action)
            await _push_long(reply, push_fn)
            return
        if lower in CANCEL_WORDS:
            store.pop_pending(user_id)
            await push_fn("ยกเลิกแล้วค่ะ")
            return
        store.pop_pending(user_id)

    try:
        result = await asyncio.wait_for(
            agent.run(text, store.get_history(user_id)),
            timeout=AGENT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        await push_fn("ขอโทษค่ะ ใช้เวลานานเกินไป กรุณาลองใหม่อีกครั้งนะคะ")
        return
    except Exception as e:
        logger.warning(f"Agent first attempt failed for {user_id}: {type(e).__name__}: {e} — retrying in 3s")
        await asyncio.sleep(3)
        try:
            result = await asyncio.wait_for(
                agent.run(text, store.get_history(user_id)),
                timeout=AGENT_TIMEOUT,
            )
        except asyncio.TimeoutError:
            await push_fn("ขอโทษค่ะ ใช้เวลานานเกินไป กรุณาลองใหม่อีกครั้งนะคะ")
            return
        except Exception as e2:
            logger.error(f"Agent retry also failed for {user_id}: {e2}", exc_info=True)
            await push_fn("เกิดข้อผิดพลาดขึ้นค่ะ ลองใหม่อีกครั้งนะคะ")
            return

    if result["type"] == "confirm":
        store.set_pending(user_id, result["pending"])
    elif result["type"] == "ask_general":
        store.set_pending_general(user_id, result["question"])

    reply = result["text"]
    if result["type"] == "answer":
        if not agent._parse_propose(reply):
            store.add_history(user_id, text, reply)
    await _push_long(reply, push_fn)
```

> **Note on LINE whitelist check:** The original `handle_message` checked `user_id not in settings.allowed_user_ids` at the top. Telegram users use `tg_` prefix so they don't match the LINE whitelist. The refactored function skips the whitelist for `tg_` users — Telegram auth is handled in `webhook_telegram` before calling `handle_message`.

- [ ] **Step 3.4: Refactor `handle_non_text_message`**

Replace the existing `handle_non_text_message` function with:

```python
async def handle_non_text_message(user_id: str, msg: dict, push_fn, download_fn=None) -> None:
    msg_type = msg.get("type", "")

    if msg_type == "image":
        if store.has_pending_note(user_id) and download_fn is not None:
            note_state = store.get_pending_note(user_id)
            if note_state.get("phase") == "waiting_content":
                page_id = note_state["page_id"]
                title = note_state["title"]
                appending = note_state.get("appending", False)
                store.pop_pending_note(user_id)
                try:
                    image_bytes = await download_fn(msg["id"])
                    file_upload_id = await notion_mod.upload_image(
                        settings.NOTION_TOKEN, image_bytes, f"image_{msg['id']}.jpg"
                    )
                    await notion_mod.append_image_block(settings.NOTION_TOKEN, page_id, file_upload_id)
                    verb = "เพิ่มรูปภาพลง" if appending else "บันทึกรูปภาพลง"
                    await push_fn(f"{verb} '{title}' เรียบร้อยแล้วค่ะ 🖼️")
                except Exception as e:
                    logger.error(f"Image upload to Notion error: {e}", exc_info=True)
                    await push_fn("อัปโหลดรูปภาพไม่สำเร็จค่ะ ลองใหม่อีกครั้งนะคะ")
                return
        await push_fn(
            "ส่งรูปภาพแนบใน note ได้ค่ะ 📎\nพิมพ์ 'จดหน่อย' เพื่อเริ่ม note แล้วส่งรูปมาได้เลย"
        )
        return

    await push_fn(f"รับแค่ข้อความ (text) ค่ะ ไม่สามารถประมวลผล {msg_type} ได้ค่ะ")
```

- [ ] **Step 3.5: Update LINE webhook to build `push_fn` and call refactored handlers**

Replace the existing `POST /webhook` handler body:

```python
@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not line_client.verify_signature(body, signature, settings.LINE_SECRETARY_CHANNEL_SECRET):
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = json.loads(body)
    token = settings.LINE_SECRETARY_CHANNEL_ACCESS_TOKEN
    for event in data.get("events", []):
        if event.get("type") != "message":
            continue
        user_id = event["source"]["userId"]
        push_fn = lambda t, _uid=user_id: line_client.push(_uid, t, token)
        if event["message"]["type"] == "text":
            text = event["message"]["text"].strip()
            background_tasks.add_task(handle_message, user_id, text, push_fn)
        else:
            msg = event.get("message", {})
            download_fn = lambda mid: line_client.download_content(mid, token)
            background_tasks.add_task(handle_non_text_message, user_id, msg, push_fn, download_fn)

    return {"status": "ok"}
```

- [ ] **Step 3.6: Verify existing tests still pass**

```bash
cd my-secretary && python -m pytest tests/ -v --ignore=tests/test_telegram.py
```

Expected: same count as Step 3.1 (27 passed), 0 failures

- [ ] **Step 3.7: Commit**

```bash
git add my-secretary/main.py
git commit -m "refactor(my-secretary): extract push_fn from handle_message for multi-platform support"
```

---

## Task 4: Add Telegram webhook endpoint + lifespan registration

**Files:**
- Modify: `my-secretary/main.py`
- Modify: `my-secretary/tests/conftest.py`
- Modify: `my-secretary/tests/test_telegram.py`

- [ ] **Step 4.1: Add Telegram env defaults to conftest**

Add to bottom of `my-secretary/tests/conftest.py`:

```python
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test_tg_token")
os.environ.setdefault("TELEGRAM_WEBHOOK_SECRET", "test_tg_secret")
os.environ.setdefault("TELEGRAM_ALLOWED_CHAT_IDS", "9999")
```

- [ ] **Step 4.2: Write failing tests for the Telegram webhook endpoint**

Append to `my-secretary/tests/test_telegram.py`:

```python
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock
import main


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def _tg_payload(chat_id: int, text: str) -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": chat_id, "type": "private"},
            "text": text,
        },
    }


def test_telegram_webhook_wrong_secret(client):
    resp = client.post(
        "/webhook/telegram",
        json=_tg_payload(9999, "hello"),
        headers={"X-Telegram-Bot-Api-Secret-Token": "WRONG"},
    )
    assert resp.status_code == 403


def test_telegram_webhook_missing_secret(client):
    resp = client.post("/webhook/telegram", json=_tg_payload(9999, "hello"))
    assert resp.status_code == 403


def test_telegram_webhook_no_message(client):
    resp = client.post(
        "/webhook/telegram",
        json={"update_id": 1},
        headers={"X-Telegram-Bot-Api-Secret-Token": "test_tg_secret"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_telegram_webhook_no_text(client):
    payload = {
        "update_id": 1,
        "message": {
            "message_id": 1,
            "chat": {"id": 9999, "type": "private"},
            "sticker": {"file_id": "abc"},
        },
    }
    resp = client.post(
        "/webhook/telegram",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": "test_tg_secret"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_telegram_webhook_unauthorized_chat(client):
    resp = client.post(
        "/webhook/telegram",
        json=_tg_payload(8888, "hello"),  # 8888 not in allowed list (only 9999)
        headers={"X-Telegram-Bot-Api-Secret-Token": "test_tg_secret"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_telegram_webhook_dispatches_handle_message(client):
    with patch("main.handle_message", new_callable=AsyncMock) as mock_handle:
        resp = client.post(
            "/webhook/telegram",
            json=_tg_payload(9999, "สวัสดีค่ะ"),
            headers={"X-Telegram-Bot-Api-Secret-Token": "test_tg_secret"},
        )
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    mock_handle.assert_called_once()
    call_args = mock_handle.call_args
    assert call_args.args[0] == "tg_9999"
    assert call_args.args[1] == "สวัสดีค่ะ"
```

- [ ] **Step 4.3: Run tests to verify they fail**

```bash
cd my-secretary && python -m pytest tests/test_telegram.py -v -k "webhook"
```

Expected: `404 Not Found` or `AssertionError` — endpoint doesn't exist yet

- [ ] **Step 4.4: Add `import hmac` and `import telegram_client` to `main.py`**

At the top of `my-secretary/main.py`, add after the existing imports:

```python
import hmac
import telegram_client
```

- [ ] **Step 4.5: Add `POST /webhook/telegram` endpoint to `main.py`**

Insert after the existing `POST /webhook` handler:

```python
@app.post("/webhook/telegram")
async def webhook_telegram(request: Request, background_tasks: BackgroundTasks):
    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=404)

    secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    if settings.TELEGRAM_WEBHOOK_SECRET and not hmac.compare_digest(
        secret, settings.TELEGRAM_WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=403, detail="Invalid secret")

    data = await request.json()
    message = data.get("message")
    if not message or not message.get("text"):
        return {"ok": True}

    chat_id = message["chat"]["id"]
    text = message["text"].strip()

    allowed = settings.telegram_allowed_chat_ids
    if allowed and str(chat_id) not in allowed:
        logger.warning(f"Unauthorized Telegram chat: {chat_id}")
        return {"ok": True}

    token = settings.TELEGRAM_BOT_TOKEN
    push_fn = lambda t: telegram_client.send_message(chat_id, t, token)
    background_tasks.add_task(handle_message, f"tg_{chat_id}", text, push_fn)
    return {"ok": True}
```

- [ ] **Step 4.6: Update `lifespan` to register Telegram webhook on startup**

Replace the existing `lifespan` function:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init(settings.DATA_DIR)
    _cache.init(settings.NOTION_TOKEN)
    _cache.start()
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_WEBHOOK_URL:
        try:
            await telegram_client.register_webhook(
                settings.TELEGRAM_BOT_TOKEN,
                settings.TELEGRAM_WEBHOOK_URL,
                settings.TELEGRAM_WEBHOOK_SECRET,
            )
            logger.info("Telegram webhook registered: %s", settings.TELEGRAM_WEBHOOK_URL)
        except Exception as e:
            logger.warning("Telegram webhook registration failed: %s", e)
    yield
```

- [ ] **Step 4.7: Run all tests**

```bash
cd my-secretary && python -m pytest tests/ -v
```

Expected: all tests pass (27 existing + new Telegram tests)

- [ ] **Step 4.8: Commit**

```bash
git add my-secretary/main.py my-secretary/tests/conftest.py my-secretary/tests/test_telegram.py
git commit -m "feat(my-secretary): add POST /webhook/telegram with whitelist + secret validation"
```

---

## Task 5: `.env.example`, README updates, and deploy

**Files:**
- Modify: `my-secretary/.env.example`
- Modify: `my-secretary/README.md`
- Modify: `README.md` (root)

- [ ] **Step 5.1: Update `my-secretary/.env.example`**

Replace full file contents:

```bash
# my-secretary stack — AI Bot (LINE + Telegram) + Notion tools
# Copy to .env and fill in real values

# ─── LINE Messaging API ───────────────────────────────────────────────────────
LINE_SECRETARY_CHANNEL_SECRET=
LINE_SECRETARY_CHANNEL_ACCESS_TOKEN=
# Comma-separated list of allowed LINE user IDs
LINE_SECRETARY_ALLOWED_USER_IDS=

# ─── Telegram Bot API ─────────────────────────────────────────────────────────
# Bot token from @BotFather
TELEGRAM_BOT_TOKEN=
# Full HTTPS URL Telegram will POST updates to (allowed ports: 443, 80, 88, 8443)
TELEGRAM_WEBHOOK_URL=https://<NAS_HOST>:8443/webhook/telegram
# Secret token sent in X-Telegram-Bot-Api-Secret-Token header for validation
TELEGRAM_WEBHOOK_SECRET=
# Comma-separated numeric chat IDs allowed to use the bot (leave empty = all allowed)
TELEGRAM_ALLOWED_CHAT_IDS=

# ─── AI Provider ─────────────────────────────────────────────────────────────
# "auto" → Groq primary, OpenRouter fallback when rate-limited
# "groq" → Groq only
# "openrouter" → OpenRouter only
AI_PROVIDER=auto

# Groq — free at console.groq.com
GROQ_API_KEY=

# OpenRouter — supports Claude, GPT, Llama, etc.
OPENROUTER_API_KEY=

# ─── Notion ──────────────────────────────────────────────────────────────────
# Internal Integration Token from notion.so/my-integrations
NOTION_TOKEN=
NOTION_QUICK_NOTE_PAGE_ID=
```

- [ ] **Step 5.2: Update `my-secretary/README.md`**

Find the existing README and add a **Telegram Setup** section after the LINE setup section. Insert the following block:

```markdown
## Telegram Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token to `TELEGRAM_BOT_TOKEN`
2. Set `TELEGRAM_WEBHOOK_URL` to your NAS HTTPS endpoint (Synology Reverse Proxy → port 8443):
   ```
   https://<NAS_HOST>:8443/webhook/telegram
   ```
3. Set `TELEGRAM_WEBHOOK_SECRET` to any random string (used to validate Telegram's requests)
4. Set `TELEGRAM_ALLOWED_CHAT_IDS` to your Telegram numeric chat ID (find it via [@userinfobot](https://t.me/userinfobot))
5. Deploy and restart — the bot registers its webhook automatically on startup

> **Note:** LINE and Telegram maintain separate conversation histories. Chatting on LINE does not share context with Telegram.
```

- [ ] **Step 5.3: Update root `README.md` — my-secretary row**

Find the row for `my-secretary` in the stacks table and update the description to reflect Telegram support. Change:

```
| my-secretary | AI Bot เลขาส่วนตัว | 5057 / 15057 |
```

to include `LINE + Telegram` in the description (exact text depends on current README — match the column style).

- [ ] **Step 5.4: Commit docs + .env.example**

```bash
git add my-secretary/.env.example my-secretary/README.md README.md
git commit -m "docs(my-secretary): add Telegram setup to README and .env.example"
```

- [ ] **Step 5.5: Deploy and test on NAS**

```bash
bash scripts/deploy.sh -s my-secretary -y
```

Then send a message to the bot on Telegram and verify a reply arrives.

- [ ] **Step 5.6: Update `.notes/daily_log.md` and `00_INDEX.md`**

Add entry to `my-secretary/.notes/daily_log.md` summarising what was implemented. Update `my-secretary/.notes/00_INDEX.md` to document the new Telegram platform, new env vars, and new file `telegram_client.py`.

- [ ] **Step 5.7: Final commit**

```bash
git add my-secretary/.notes/
git commit -m "docs(my-secretary): update .notes for Telegram support"
```
