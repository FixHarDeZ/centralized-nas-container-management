import asyncio
import json
import logging
import time
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

import agent
import line_client
import notion as notion_mod
import provider as _provider
import store
import telegram_client
from cache import cache as _cache
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

AGENT_TIMEOUT = 45  # seconds before giving up on a single LLM call


@asynccontextmanager
async def lifespan(app: FastAPI):
    store.init(settings.DATA_DIR)
    _cache.init(settings.NOTION_TOKEN)
    _cache.start()
    if settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_WEBHOOK_URL:
        await telegram_client.set_webhook(settings.TELEGRAM_BOT_TOKEN, settings.TELEGRAM_WEBHOOK_URL)
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


async def _push_long(user_id: str, text: str, token: str, max_len: int = 4000) -> None:
    """Send text as one or more LINE messages, splitting at max_len chars."""
    if len(text) <= max_len:
        await line_client.push(user_id, text, token)
        return
    for i in range(0, len(text), max_len):
        await line_client.push(user_id, text[i:i + max_len], token)


async def _push_tg(chat_id: str, text: str) -> None:
    await telegram_client.send(chat_id, text, settings.TELEGRAM_BOT_TOKEN)


# ── Webhook ────────────────────────────────────────────────────────────────────

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
        if event.get("type") != "message":
            continue
        if event["message"]["type"] == "text":
            background_tasks.add_task(handle_message, event)
        else:
            background_tasks.add_task(handle_non_text_message, event)

    return {"status": "ok"}


@app.post("/webhook/telegram")
async def webhook_telegram(request: Request, background_tasks: BackgroundTasks):
    if not settings.TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=404)
    update = await request.json()
    msg = update.get("message") or update.get("edited_message")
    if msg and msg.get("text"):
        background_tasks.add_task(handle_telegram_message, msg)
    return {"status": "ok"}


async def handle_telegram_message(msg: dict) -> None:
    chat_id = str(msg["chat"]["id"])
    text = msg.get("text", "").strip()

    allowed = settings.allowed_telegram_chat_ids
    if allowed and chat_id not in allowed:
        logger.warning(f"Telegram: unauthorized chat {chat_id}")
        return

    tg_token = settings.TELEGRAM_BOT_TOKEN

    if text.startswith("/start"):
        await _push_tg(chat_id, "สวัสดีค่ะ! พิมพ์ข้อความได้เลย หรือ /help เพื่อดูคำสั่งทั้งหมดค่ะ")
        return

    if text == "/help":
        await _push_tg(chat_id, (
            "📖 คำสั่งที่ใช้ได้:\n"
            "/help — แสดงคำสั่งทั้งหมดนี้\n"
            "/history — แสดงประวัติสนทนาล่าสุด\n"
            "/clear — ล้างประวัติ + pending\n"
            "/refresh — รีเฟรช Notion cache\n"
            "/cache — สถิติ cache\n"
            "/provider — AI provider ที่ใช้งาน\n\n"
            "📝 จดโน้ต:\n"
            "จดหน่อย / note please — เริ่มจดลง Quick note\n\n"
            "⚠️ ทุก write ต้องยืนยันด้วย 'ใช่' ก่อนเสมอค่ะ"
        ))
        return

    if text == "/refresh":
        try:
            n = await _cache.force_refresh()
            await _push_tg(chat_id, f"รีเฟรช cache เรียบร้อยค่ะ 🔄 ({n} pages)")
        except Exception as e:
            logger.error(f"Telegram force_refresh error: {e}", exc_info=True)
            await _push_tg(chat_id, "รีเฟรช cache ไม่สำเร็จค่ะ")
        return

    if text == "/cache":
        s = _cache.stats()
        age = s["age_seconds"]
        age_str = "ยังไม่ได้ build" if age < 0 else (f"{age} วิ" if age < 60 else f"{age // 60} นาที {age % 60} วิ")
        await _push_tg(chat_id, f"Cache: {s['pages']} pages | อัปเดตเมื่อ {age_str} ที่แล้วค่ะ")
        return

    if text == "/provider":
        await _push_tg(chat_id, _provider.status_text(settings))
        return

    if text == "/history":
        hist = store.get_history(chat_id)
        if not hist:
            await _push_tg(chat_id, "ยังไม่มีประวัติการสนทนาค่ะ")
            return
        lines = []
        for i in range(0, len(hist) - 1, 2):
            u = hist[i].get("content", "")[:120]
            b = hist[i + 1].get("content", "")[:120] if i + 1 < len(hist) else ""
            lines.append(f"คุณ: {u}\nบอท: {b}")
        await _push_tg(chat_id, "📜 ประวัติล่าสุด:\n\n" + "\n\n".join(lines))
        return

    if text == "/clear":
        store.pop_pending(chat_id)
        store.pop_pending_general(chat_id)
        store.pop_pending_note(chat_id)
        store.clear_history(chat_id)
        await _push_tg(chat_id, "ล้างประวัติการสนทนาแล้วค่ะ 🗑️")
        return

    # Note flow
    if store.has_pending_note(chat_id):
        note_state = store.get_pending_note(chat_id)
        if note_state.get("phase") == "asking_topic":
            title = text.strip()
            all_pages = await _cache.get_pages()
            existing = next((p for p in all_pages if p["title"].strip().lower() == title.lower()), None)
            if not existing:
                try:
                    results = await notion_mod.search(settings.NOTION_TOKEN, title)
                    existing = next((r for r in results if r["type"] == "page" and r["title"].strip().lower() == title.lower()), None)
                except Exception:
                    pass
            if existing:
                store.set_pending_note(chat_id, {"phase": "waiting_content", "page_id": existing["id"], "title": existing["title"], "appending": True})
                await _push_tg(chat_id, f"พบ page '{existing['title']}' แล้วค่ะ 📎 ส่งเนื้อหาที่จะเพิ่มมาได้เลยค่ะ")
            else:
                try:
                    page = await notion_mod.create_page(settings.NOTION_TOKEN, settings.NOTION_QUICK_NOTE_PAGE_ID, title)
                    store.set_pending_note(chat_id, {"phase": "waiting_content", "page_id": page["id"], "title": title, "appending": False})
                    await _push_tg(chat_id, f"สร้าง page '{title}' แล้วค่ะ 📄 ส่งเนื้อหามาได้เลยค่ะ")
                except Exception as e:
                    logger.error(f"Telegram create_page error: {e}", exc_info=True)
                    store.pop_pending_note(chat_id)
                    await _push_tg(chat_id, "สร้าง page ไม่สำเร็จค่ะ ลองใหม่อีกครั้งนะคะ")
            return

        if note_state.get("phase") == "waiting_content":
            page_id = note_state["page_id"]
            title = note_state["title"]
            appending = note_state.get("appending", False)
            store.pop_pending_note(chat_id)
            try:
                await notion_mod.append_blocks(settings.NOTION_TOKEN, page_id, text)
                verb = "เพิ่มเนื้อหาลง" if appending else "บันทึกลง"
                await _push_tg(chat_id, f"{verb} '{title}' เรียบร้อยแล้วค่ะ ✅")
            except Exception as e:
                logger.error(f"Telegram append_blocks error: {e}", exc_info=True)
                await _push_tg(chat_id, "บันทึกไม่สำเร็จค่ะ ลองใหม่อีกครั้งนะคะ")
            return

        store.pop_pending_note(chat_id)
        await _push_tg(chat_id, "เกิดข้อผิดพลาดในขั้นตอนจดโน้ตค่ะ กรุณาเริ่มใหม่")
        return

    if _is_note_intent(text):
        if not settings.NOTION_QUICK_NOTE_PAGE_ID:
            await _push_tg(chat_id, "ยังไม่ได้ตั้งค่า Quick note page ค่ะ")
            return
        store.set_pending_note(chat_id, {"phase": "asking_topic"})
        await _push_tg(chat_id, "จะจดเรื่องอะไรคะ? 📝")
        return

    # Pending general knowledge confirm
    if store.has_pending_general(chat_id):
        lower = text.lower()
        if lower in CONFIRM_WORDS:
            question = store.pop_pending_general(chat_id)
            try:
                result = await asyncio.wait_for(agent.run_general(question, store.get_history(chat_id)), timeout=AGENT_TIMEOUT)
            except (asyncio.TimeoutError, Exception) as e:
                await _push_tg(chat_id, "ขอโทษค่ะ เกิดข้อผิดพลาด ลองใหม่อีกครั้งนะคะ")
                return
            store.add_history(chat_id, question, result["text"])
            await _push_tg(chat_id, result["text"])
            return
        if lower in CANCEL_WORDS:
            store.pop_pending_general(chat_id)
            await _push_tg(chat_id, "ได้ค่ะ ถ้าต้องการข้อมูลอื่นถามได้เลยนะคะ")
            return
        store.pop_pending_general(chat_id)

    # Pending write confirm
    if store.has_pending(chat_id):
        lower = text.lower()
        if lower in CONFIRM_WORDS:
            action = store.pop_pending(chat_id)
            reply = await agent.execute_write(action)
            await _push_tg(chat_id, reply)
            return
        if lower in CANCEL_WORDS:
            store.pop_pending(chat_id)
            await _push_tg(chat_id, "ยกเลิกแล้วค่ะ")
            return
        store.pop_pending(chat_id)

    # Main agent
    try:
        result = await asyncio.wait_for(agent.run(text, store.get_history(chat_id)), timeout=AGENT_TIMEOUT)
    except asyncio.TimeoutError:
        await _push_tg(chat_id, "ขอโทษค่ะ ใช้เวลานานเกินไป กรุณาลองใหม่อีกครั้งนะคะ")
        return
    except Exception as e:
        logger.warning(f"Telegram agent first attempt failed: {e} — retrying in 3s")
        await asyncio.sleep(3)
        try:
            result = await asyncio.wait_for(agent.run(text, store.get_history(chat_id)), timeout=AGENT_TIMEOUT)
        except Exception as e2:
            logger.error(f"Telegram agent retry failed: {e2}", exc_info=True)
            await _push_tg(chat_id, "เกิดข้อผิดพลาดค่ะ ลองใหม่อีกครั้งนะคะ")
            return

    if result["type"] == "confirm":
        store.set_pending(chat_id, result["pending"])
    elif result["type"] == "ask_general":
        store.set_pending_general(chat_id, result["question"])

    reply = result["text"]
    if result["type"] == "answer" and not agent._parse_propose(reply):
        store.add_history(chat_id, text, reply)
    await _push_tg(chat_id, reply)


async def handle_non_text_message(event: dict) -> None:
    user_id = event["source"]["userId"]
    if user_id not in settings.allowed_user_ids:
        return
    msg = event.get("message", {})
    msg_type = msg.get("type", "")
    token = settings.LINE_SECRETARY_CHANNEL_ACCESS_TOKEN

    if msg_type == "image":
        # If user is in waiting_content note phase → attach image to the note
        if store.has_pending_note(user_id):
            note_state = store.get_pending_note(user_id)
            if note_state.get("phase") == "waiting_content":
                page_id = note_state["page_id"]
                title = note_state["title"]
                appending = note_state.get("appending", False)
                store.pop_pending_note(user_id)
                try:
                    image_bytes = await line_client.download_content(msg["id"], token)
                    file_upload_id = await notion_mod.upload_image(
                        settings.NOTION_TOKEN, image_bytes, f"image_{msg['id']}.jpg"
                    )
                    await notion_mod.append_image_block(settings.NOTION_TOKEN, page_id, file_upload_id)
                    verb = "เพิ่มรูปภาพลง" if appending else "บันทึกรูปภาพลง"
                    await line_client.push(user_id, f"{verb} '{title}' เรียบร้อยแล้วค่ะ 🖼️", token)
                except Exception as e:
                    logger.error(f"Image upload to Notion error: {e}", exc_info=True)
                    await line_client.push(user_id, "อัปโหลดรูปภาพไม่สำเร็จค่ะ ลองใหม่อีกครั้งนะคะ", token)
                return
        # Not in note flow
        await line_client.push(
            user_id,
            "ส่งรูปภาพแนบใน note ได้ค่ะ 📎\nพิมพ์ 'จดหน่อย' เพื่อเริ่ม note แล้วส่งรูปมาได้เลย",
            token,
        )
        return

    await line_client.push(user_id, f"รับแค่ข้อความ (text) ค่ะ ไม่สามารถประมวลผล {msg_type} ได้ค่ะ", token)


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

    # /refresh → force immediate cache rebuild
    if text == "/refresh":
        try:
            n = await _cache.force_refresh()
            await line_client.push(user_id, f"รีเฟรช cache เรียบร้อยค่ะ 🔄 ({n} pages)", token)
        except Exception as e:
            logger.error(f"force_refresh error: {e}", exc_info=True)
            await line_client.push(user_id, "รีเฟรช cache ไม่สำเร็จค่ะ ลองใหม่อีกครั้งนะคะ", token)
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
        await line_client.push(
            user_id,
            f"Cache: {s['pages']} pages ({s['indexed']} indexed) | อัปเดตเมื่อ {age_str} ที่แล้วค่ะ",
            token,
        )
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
        ), token)
        return

    # /history → show last 4 conversation exchanges
    if text == "/history":
        hist = store.get_history(user_id)
        if not hist:
            await line_client.push(user_id, "ยังไม่มีประวัติการสนทนาค่ะ", token)
            return
        lines = []
        for i in range(0, len(hist) - 1, 2):
            u = hist[i].get("content", "")[:120]
            b = hist[i + 1].get("content", "")[:120] if i + 1 < len(hist) else ""
            lines.append(f"คุณ: {u}\nบอท: {b}")
        await _push_long(user_id, "📜 ประวัติล่าสุด:\n\n" + "\n\n".join(lines), token)
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

        if note_state.get("phase") == "asking_topic":
            title = text.strip()
            if not title:
                await line_client.push(user_id, "กรุณาบอกชื่อหัวข้อด้วยนะคะ 📝", token)
                return

            # Check if a page with this title already exists → append instead of create
            # Phase 1: cache (fast, 0 API calls when warm)
            all_pages = await _cache.get_pages()
            existing = next((p for p in all_pages if p["title"].strip().lower() == title.lower()), None)
            # Phase 2: Notion search fallback (catches pages not yet in cache / stale cache)
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
                await line_client.push(
                    user_id,
                    f"พบ page '{existing['title']}' แล้วค่ะ 📎 ส่งเนื้อหาที่จะเพิ่มมาได้เลยค่ะ",
                    token,
                )
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
            store.set_pending_note(user_id, {
                "phase": "waiting_content",
                "page_id": page_id,
                "title": title,
                "appending": False,
            })
            await line_client.push(user_id, f"สร้าง page '{title}' แล้วค่ะ 📄 ส่งเนื้อหาที่จะจดมาได้เลยค่ะ\n(รองรับ # หัวข้อ / - bullet / [ ] todo)", token)
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
                await line_client.push(
                    user_id,
                    f"บันทึกไม่สำเร็จค่ะ ลองเปิด page โดยตรงที่:\n{notion_url}",
                    token,
                )
                return
            verb = "เพิ่มเนื้อหาลง" if appending else "บันทึกลง"
            await line_client.push(user_id, f"{verb} '{title}' เรียบร้อยแล้วค่ะ ✅", token)
            return

        # unknown phase — clear and reset
        logger.warning(f"Unknown pending_note phase for {user_id}: {note_state.get('phase')}")
        store.pop_pending_note(user_id)
        await line_client.push(user_id, "เกิดข้อผิดพลาดในขั้นตอนจดโน้ตค่ะ กรุณาเริ่มใหม่อีกครั้ง", token)
        return

    # Detect note-taking intent
    if _is_note_intent(text):
        if not settings.NOTION_QUICK_NOTE_PAGE_ID:
            await line_client.push(user_id, "ยังไม่ได้ตั้งค่า Quick note page ค่ะ (NOTION_QUICK_NOTE_PAGE_ID)", token)
            return
        store.set_pending_note(user_id, {"phase": "asking_topic"})
        await line_client.push(user_id, "จะจดเรื่องอะไรคะ? 📝 (บอกชื่อหัวข้อ หรือชื่อ page ที่มีอยู่แล้ว)", token)
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
                await line_client.push(user_id, "ขอโทษค่ะ ใช้เวลานานเกินไป กรุณาลองใหม่อีกครั้งนะคะ", token)
                return
            except Exception as e:
                logger.error(f"run_general error: {e}", exc_info=True)
                await line_client.push(user_id, "เกิดข้อผิดพลาดค่ะ ลองใหม่อีกครั้งนะคะ", token)
                return
            reply = result["text"]
            store.add_history(user_id, question, reply)
            await _push_long(user_id, reply, token)
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
            await _push_long(user_id, reply, token)
            return
        if lower in CANCEL_WORDS:
            store.pop_pending(user_id)
            await line_client.push(user_id, "ยกเลิกแล้วค่ะ", token)
            return
        # Not a confirmation word — treat as new query
        store.pop_pending(user_id)

    try:
        result = await asyncio.wait_for(
            agent.run(text, store.get_history(user_id)),
            timeout=AGENT_TIMEOUT,
        )
    except asyncio.TimeoutError:
        await line_client.push(user_id, "ขอโทษค่ะ ใช้เวลานานเกินไป กรุณาลองใหม่อีกครั้งนะคะ", token)
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
            await line_client.push(user_id, "ขอโทษค่ะ ใช้เวลานานเกินไป กรุณาลองใหม่อีกครั้งนะคะ", token)
            return
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
    await _push_long(user_id, reply, token)
