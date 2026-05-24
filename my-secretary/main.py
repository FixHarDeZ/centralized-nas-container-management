import asyncio
import hmac
import json
import logging
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


app = FastAPI(title="my-secretary", lifespan=lifespan)

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


async def _push_long(text: str, push_fn, max_len: int = 4000) -> None:
    """Send text in chunks, splitting at max_len chars."""
    if len(text) <= max_len:
        await push_fn(text)
        return
    for i in range(0, len(text), max_len):
        await push_fn(text[i:i + max_len])


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


async def handle_message(user_id: str, text: str, push_fn) -> None:
    # LINE users are checked against whitelist; Telegram users (tg_ prefix) are
    # already verified in webhook_telegram before reaching here.
    if not user_id.startswith("tg_") and user_id not in settings.allowed_user_ids:
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
