import json
import logging

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

import agent
import line_client
from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Line Secretary")

# In-memory pending confirmations keyed by LINE user_id
# { user_id: {"database_id": str, "properties": dict} }
pending: dict[str, dict] = {}

CONFIRM_WORDS = {"ใช่", "yes", "y", "ตกลง", "ok", "ยืนยัน", "confirm", "ใช"}
CANCEL_WORDS = {"ไม่", "no", "n", "ยกเลิก", "cancel", "ไม่ใช่", "ไม่ครับ"}


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
        import notion as notion_mod
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
            client_dbg = agent._make_client()
            result = await agent._deep_search(client_dbg, settings.NOTION_TOKEN, [query])
            reply = f"[DEBUG2] deep_search('{query}'):\n{json.dumps(result, ensure_ascii=False, indent=2)}"
        except Exception as e:
            reply = f"[DEBUG2] Error: {e}"
        await line_client.push(user_id, reply[:4000], token)
        return

    # /debug3 <page_id> → raw blocks of a page
    if text.startswith("/debug3 "):
        page_id = text[8:].strip()
        import notion as notion_mod
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
        import notion as notion_mod
        try:
            result = await notion_mod.query_database_raw(settings.NOTION_TOKEN, db_id)
            reply = f"[DEBUG4] query_db_raw({db_id[:8]}...):\n{json.dumps(result, ensure_ascii=False, indent=2)}"
        except Exception as e:
            reply = f"[DEBUG4] Error: {e}"
        await line_client.push(user_id, reply[:4000], token)
        return

    # Handle pending confirmation
    if user_id in pending:
        lower = text.lower()
        if lower in CONFIRM_WORDS:
            action = pending.pop(user_id)
            reply = await agent.execute_write(action)
            await line_client.push(user_id, reply, token)
            return
        if lower in CANCEL_WORDS:
            pending.pop(user_id)
            await line_client.push(user_id, "ยกเลิกแล้วครับ", token)
            return
        # Not a confirmation word — treat as new query
        pending.pop(user_id)

    try:
        result = await agent.run(text)
    except Exception as e:
        logger.error(f"Agent error for user {user_id}: {e}", exc_info=True)
        await line_client.push(user_id, f"[DEBUG] Error: {type(e).__name__}: {e}", token)
        return

    if result["type"] == "confirm":
        pending[user_id] = result["pending"]

    await line_client.push(user_id, result["text"], token)
