import asyncio
import json
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

import agent
import line_client
import notion as notion_mod
import provider as _provider
import store
from cache import cache as _cache
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init(settings.DATA_DIR)
    _cache.init(settings.NOTION_TOKEN)
    _cache.start()
    yield


app = FastAPI(title="Line Secretary", lifespan=lifespan)

CONFIRM_WORDS = {"ใช่", "yes", "y", "ตกลง", "ok", "ยืนยัน", "confirm", "ใช"}
CANCEL_WORDS = {"ไม่", "no", "n", "ยกเลิก", "cancel", "ไม่ใช่", "ไม่ครับ", "ไม่ค่ะ"}

_NOTE_INTENT_KEYWORDS = [
    "จดหน่อย", "จดให้หน่อย", "จดให้ด้วย", "จดด้วย",
    "เตรียมจด", "ช่วยจด", "จดไว้", "บันทึกให้หน่อย",
    "note please", "please note", "help me note", "take a note", "make a note",
]


def _is_note_intent(text: str) -> bool:
    t = text.lower().strip()
    return any(k in t for k in _NOTE_INTENT_KEYWORDS)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/webhook")
async def webhook(request: Request, background_tasks: BackgroundTasks):
    body = await request.body()
    signature = request.headers.get("X-Line-Signature", "")

    if not line_client.verify_signature(body, signature, settings.LINE_SECRETARY_CHANNEL_SECRET):
        raise HTTPException(status_code=400, detail="Invalid signature")

    data = json.loads(body)
    for event in data.get("events", []):
        if event.get("type") == "message" and event["message"]["type"] == "text":
            background_tasks.add_task(handle_message, event)

    return {"status": "ok"}


async def handle_message(event: dict) -> None:
    user_id = event["source"]["userId"]
    text = event["message"]["text"].strip()
    token = settings.LINE_SECRETARY_CHANNEL_ACCESS_TOKEN

    if user_id not in settings.allowed_user_ids:
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
        await line_client.push(user_id, reply[:4000], token)
        return

    # /debug2 <query> → full deep search (pages + embedded databases)
    if text.startswith("/debug2 "):
        query = text[8:].strip()
        try:
            result = await agent._deep_search(settings.NOTION_TOKEN, [query])
            reply = f"[DEBUG2] deep_search('{query}'):\n{json.dumps(result, ensure_ascii=False, indent=2)}"
        except Exception as e:
            reply = f"[DEBUG2] Error: {e}"
        await line_client.push(user_id, reply[:4000], token)
        return

    # /debug3 <page_id> → raw blocks of a page
    if text.startswith("/debug3 "):
        page_id = text[8:].strip()
        try:
            result = await notion_mod.get_raw_blocks(settings.NOTION_TOKEN, page_id)
            reply = f"[DEBUG3] blocks({page_id[:8]}...):\n{json.dumps(result, ensure_ascii=False, indent=2)}"
        except Exception as e:
            reply = f"[DEBUG3] Error: {e}"
        await line_client.push(user_id, reply[:4000], token)
        return

    # /debug4 <db_id> → raw database query
    if text.startswith("/debug4 "):
        db_id = text[8:].strip()
        try:
            result = await notion_mod.query_database_raw(settings.NOTION_TOKEN, db_id)
            reply = f"[DEBUG4] query_db_raw({db_id[:8]}...):\n{json.dumps(result, ensure_ascii=False, indent=2)}"
        except Exception as e:
            reply = f"[DEBUG4] Error: {e}"
        await line_client.push(user_id, reply[:4000], token)
        return

    # /provider → show active provider and failover status
    if text == "/provider":
        await line_client.push(user_id, _provider.status_text(settings), token)
        return

    # /help → show available commands and usage tips
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

    # /clear → wipe history + pending for this user (useful when bot gets stuck)
    if text == "/clear":
        store.pop_pending(user_id)
        store.pop_pending_general(user_id)
        store.pop_pending_note(user_id)
        store.clear_history(user_id)
        await line_client.push(user_id, "ล้างประวัติการสนทนาแล้วค่ะ 🗑️", token)
        return

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

    # Handle pending general-knowledge confirmation
    if store.has_pending_general(user_id):
        lower = text.lower()
        if lower in CONFIRM_WORDS:
            question = store.pop_pending_general(user_id)
            try:
                result = await agent.run_general(question, store.get_history(user_id))
            except Exception as e:
                logger.error(f"run_general error: {e}", exc_info=True)
                await line_client.push(user_id, "เกิดข้อผิดพลาดค่ะ ลองใหม่อีกครั้งนะคะ", token)
                return
            reply = result["text"]
            store.add_history(user_id, question, reply)
            await line_client.push(user_id, reply, token)
            return
        if lower in CANCEL_WORDS:
            store.pop_pending_general(user_id)
            await line_client.push(user_id, "ได้ค่ะ ถ้าต้องการข้อมูลอื่นถามได้เลยนะคะ", token)
            return
        # Not a confirm/cancel word — clear and treat as new query
        store.pop_pending_general(user_id)

    # Handle pending write confirmation
    if store.has_pending(user_id):
        lower = text.lower()
        if lower in CONFIRM_WORDS:
            action = store.pop_pending(user_id)
            reply = await agent.execute_write(action)
            await line_client.push(user_id, reply, token)
            return
        if lower in CANCEL_WORDS:
            store.pop_pending(user_id)
            await line_client.push(user_id, "ยกเลิกแล้วค่ะ", token)
            return
        # Not a confirmation word — treat as new query
        store.pop_pending(user_id)

    try:
        result = await agent.run(text, store.get_history(user_id))
    except Exception as e:
        logger.warning(f"Agent first attempt failed for {user_id}: {type(e).__name__}: {e} — retrying in 3s")
        await asyncio.sleep(3)
        try:
            result = await agent.run(text, store.get_history(user_id))
        except Exception as e2:
            logger.error(f"Agent retry also failed for {user_id}: {e2}", exc_info=True)
            await line_client.push(user_id, "เกิดข้อผิดพลาดขึ้นค่ะ ลองใหม่อีกครั้งนะคะ", token)
            return

    if result["type"] == "confirm":
        store.set_pending(user_id, result["pending"])
    elif result["type"] == "ask_general":
        store.set_pending_general(user_id, result["question"])

    reply = result["text"]
    if result["type"] == "answer":
        # Safety: don't store replies that contain raw JSON proposals —
        # those are bad LLM outputs that would poison future context.
        if not agent._parse_propose(reply):
            store.add_history(user_id, text, reply)
    await line_client.push(user_id, reply, token)
