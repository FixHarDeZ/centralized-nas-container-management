"""Telegram long-poll loop: the entire interface of this stack.

No HTTP server, no scheduler — see docs/adr/0002.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

import httpx

from app import render, script as script_gen, youtube

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("shorts-factory")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/output"))
STATE_PATH = DATA_DIR / "state.json"
WORK_DIR = DATA_DIR / "work"

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = int(os.environ["TELEGRAM_CHAT_ID"])
API = f"https://api.telegram.org/bot{TOKEN}"

RENDER_CB, DISCARD_CB, UPLOAD_CB = "render", "discard", "upload"
UPLOAD_KEYBOARD = {
    "inline_keyboard": [[{"text": "⬆️ อัปโหลดขึ้น YouTube", "callback_data": UPLOAD_CB}]]
}
REVIEW_KEYBOARD = {
    "inline_keyboard": [[
        {"text": "🎬 render", "callback_data": RENDER_CB},
        {"text": "🗑 ทิ้ง", "callback_data": DISCARD_CB},
    ]]
}


# --- state -------------------------------------------------------------------

def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("state.json อ่านไม่ได้ เริ่มใหม่")
    return {"mode": "idle", "offset": 0}


def save_state(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


# --- telegram ----------------------------------------------------------------

async def api(client: httpx.AsyncClient, method: str, **payload):
    reply = await client.post(f"{API}/{method}", json=payload, timeout=60)
    body = reply.json()
    if not body.get("ok"):
        logger.error("telegram %s: %s", method, body.get("description"))
    return body.get("result")


async def say(client: httpx.AsyncClient, text: str, **extra):
    return await api(client, "sendMessage", chat_id=CHAT_ID, text=text, **extra)


async def send_video(client: httpx.AsyncClient, path: Path, caption: str, **extra) -> dict | None:
    with path.open("rb") as handle:
        data = {"chat_id": CHAT_ID, "caption": caption[:1024], "supports_streaming": "true"}
        data.update({k: json.dumps(v) for k, v in extra.items()})
        reply = await client.post(
            f"{API}/sendVideo",
            data=data,
            files={"video": (path.name, handle, "video/mp4")},
            timeout=600,
        )
    body = reply.json()
    if not body.get("ok"):
        logger.error("sendVideo: %s", reply.text[:400])
        await say(client, "ส่งไฟล์เข้า Telegram ไม่ผ่าน แต่คลิปอยู่บน NAS แล้ว")
        return None
    return body.get("result")


async def close_prompt(client: httpx.AsyncClient, message_id: int | None, note: str) -> None:
    """Retire a message's buttons in place.

    editMessageText fires no notification, so anything the human must see is
    sent as a fresh message afterwards — same rule torrentwatch follows.
    """
    if message_id and note:
        await api(client, "editMessageText", chat_id=CHAT_ID, message_id=message_id, text=note)


# --- presentation ------------------------------------------------------------

def format_script(script: dict) -> str:
    parts = [f"📝 {script['title']}", ""]
    for i, card in enumerate(script["cards"], 1):
        label = "hook" if i == 1 else f"card {i}"
        parts.append(f"[{label}] {' / '.join(card['lines'])}")
        parts.append(f"   🔊 {card['narration']}")
        if (card.get("code") or "").strip():
            parts.append(f"   ```{card['code'].strip()}```")
    parts += ["", " ".join(script["hashtags"]), "", "พิมพ์บอกได้เลยว่าอยากแก้ตรงไหน"]
    return "\n".join(parts)[:4096]


def metadata_text(script: dict) -> str:
    return (
        f"{script['title']}\n\n{script['description']}\n\n{' '.join(script['hashtags'])}\n"
    )


def slugify(title: str) -> str:
    """Filename-safe stem. Thai characters are kept; separators are not."""
    cleaned = re.sub(r"[^\w฀-๿ -]", "", title).strip().replace(" ", "-")
    return (cleaned or "clip")[:60]


# --- pipeline ----------------------------------------------------------------

async def deliver(client: httpx.AsyncClient, state: dict, script: dict, clip: Path) -> None:
    """Copy the Clip and its metadata to /output, then send it to Telegram."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = f"{datetime.now():%Y%m%d-%H%M}-{slugify(script['title'])}"
    final = OUTPUT_DIR / f"{stem}.mp4"
    shutil.copy2(clip, final)
    (OUTPUT_DIR / f"{stem}.txt").write_text(metadata_text(script), encoding="utf-8")

    # Publishing is outward-facing and cannot be undone quietly, so it stays
    # behind a button even though everything up to here is automatic.
    offer_upload = youtube.configured()
    sent = await send_video(
        client, final, metadata_text(script),
        **({"reply_markup": UPLOAD_KEYBOARD} if offer_upload else {}),
    )
    await say(client, f"✅ เสร็จแล้ว เก็บไว้ที่ {final}")
    state.update(
        last_clip=str(final),
        last_script=script,
        upload_message_id=(sent or {}).get("message_id") if offer_upload else None,
    )
    save_state(state)


async def make_script(client: httpx.AsyncClient, state: dict, topic: str, feedback: str = "") -> None:
    previous = state.get("script") if feedback else None
    # Retire the buttons on the script being replaced. Two live keyboards would
    # let the human approve the message they are looking at and get a different
    # script rendered, since state.message_id only tracks the newest one.
    await close_prompt(client, state.get("message_id"), f"📝 {previous['title']} — กำลังแก้ตามที่บอก" if previous else "")
    state["message_id"] = None

    await say(client, "🤔 กำลังเขียนสคริปต์...")
    try:
        script = await script_gen.generate(topic, previous=previous, feedback=feedback)
    except Exception as exc:
        logger.exception("generate failed")
        if previous is not None:
            # A blip during a revision must not throw away the script being
            # worked on; re-post it so its buttons come back.
            sent = await say(client, format_script(previous), reply_markup=REVIEW_KEYBOARD)
            state["message_id"] = (sent or {}).get("message_id")
        else:
            state.update(mode="idle", script=None)
        save_state(state)
        await say(client, f"เขียนสคริปต์ไม่สำเร็จ: {exc}")
        return

    sent = await say(client, format_script(script), reply_markup=REVIEW_KEYBOARD)
    state.update(
        mode="review", topic=topic, script=script, message_id=(sent or {}).get("message_id")
    )
    save_state(state)


async def do_render(client: httpx.AsyncClient, state: dict) -> None:
    script = state["script"]
    await close_prompt(client, state.get("message_id"), f"📝 {script['title']} — กำลัง render")
    state.update(mode="rendering", message_id=None)
    save_state(state)

    workdir = WORK_DIR / datetime.now().strftime("%Y%m%d-%H%M%S")
    try:
        clip = await render.build(script, workdir)
        await deliver(client, state, script, clip)
    except Exception as exc:
        logger.exception("render failed")
        await say(client, f"render ล้มเหลว: {exc}")
    finally:
        # Intermediate PNG/audio dwarf the mp4; never leave them behind.
        shutil.rmtree(workdir, ignore_errors=True)
        state.update(mode="idle", script=None, topic=None)
        save_state(state)


async def retire_buttons(client: httpx.AsyncClient, message_id: int | None) -> None:
    """Drop a message's keyboard.

    `editMessageText` cannot touch a video message — that carries a caption,
    not text — so removing the markup is the one edit that works on both.
    """
    if message_id:
        await api(
            client, "editMessageReplyMarkup",
            chat_id=CHAT_ID, message_id=message_id, reply_markup={"inline_keyboard": []},
        )


async def do_upload(client: httpx.AsyncClient, state: dict) -> None:
    clip = Path(state.get("last_clip") or "")
    script = state.get("last_script")
    if not script or not clip.is_file():
        await say(client, "ไม่เจอคลิปที่จะอัปแล้ว (บอทน่าจะรีสตาร์ทไป) ลอง render ใหม่")
        return

    await retire_buttons(client, state.get("upload_message_id"))
    state["upload_message_id"] = None
    save_state(state)
    await say(client, "⬆️ กำลังอัปโหลด...")

    try:
        video_id, privacy = await youtube.upload(clip, script)
    except Exception as exc:
        logger.exception("upload failed")
        await say(client, f"อัปโหลดไม่สำเร็จ: {exc}")
        return

    # The video is already up; a thumbnail problem must not read as a failure.
    thumbnail_note = ""
    try:
        cover = render.first_frame(clip, clip.with_suffix(".jpg"))
        await youtube.set_thumbnail(video_id, cover)
        thumbnail_note = "\nปก: เฟรมแรกของคลิป"
    except Exception as exc:
        logger.exception("thumbnail failed")
        thumbnail_note = f"\n⚠️ ตั้งปกไม่ได้: {exc} (คลิปขึ้นแล้ว ตั้งเองใน Studio ได้)"

    url = f"https://youtu.be/{video_id}"
    note = f"⬆️ ขึ้นช่องแล้ว: {url}\nสถานะ: {privacy}{thumbnail_note}"
    if privacy != os.environ.get("YOUTUBE_PRIVACY", "public"):
        # Google forces uploads from an unaudited project to private.
        note += "\n⚠️ YouTube เปลี่ยนสถานะเอง — โปรเจกต์ยังไม่ผ่าน API audit"
    await say(client, note)
    state.update(last_clip=None, last_script=None)
    save_state(state)


# --- dispatch ----------------------------------------------------------------

async def on_text(client: httpx.AsyncClient, state: dict, text: str) -> None:
    mode = state.get("mode", "idle")
    if mode == "rendering":
        await say(client, "⏳ กำลัง render อยู่ รอให้เสร็จก่อนนะ")
    elif mode == "review":
        # A pending Script is work in progress: plain text revises it rather
        # than silently discarding it. Starting over is the 🗑 button.
        await make_script(client, state, state["topic"], feedback=text)
    else:
        await make_script(client, state, text)


async def on_callback(client: httpx.AsyncClient, state: dict, query: dict) -> None:
    await api(client, "answerCallbackQuery", callback_query_id=query["id"])
    if query.get("data") != UPLOAD_CB and state.get("mode") != "review":
        return
    if query.get("data") == UPLOAD_CB:
        await do_upload(client, state)
        return
    if query.get("data") == RENDER_CB:
        await do_render(client, state)
    elif query.get("data") == DISCARD_CB:
        await close_prompt(client, state.get("message_id"), "🗑 ทิ้งสคริปต์แล้ว")
        state.update(mode="idle", script=None, topic=None, message_id=None)
        save_state(state)
        await say(client, "ทิ้งแล้ว ส่งหัวข้อใหม่มาได้เลย")


def is_ours(update: dict) -> bool:
    """The only trust boundary this stack has — see docs/adr/0002."""
    message = update.get("message") or update.get("callback_query", {}).get("message") or {}
    return message.get("chat", {}).get("id") == CHAT_ID


async def handle(client: httpx.AsyncClient, state: dict, update: dict) -> None:
    if not is_ours(update):
        logger.warning("ทิ้ง update จาก chat อื่น")
        return
    if "callback_query" in update:
        await on_callback(client, state, update["callback_query"])
        return
    text = (update.get("message") or {}).get("text", "").strip()
    if text:
        await on_text(client, state, text)


async def main() -> None:
    state = load_state()
    if state.get("mode") == "rendering":
        # Crashed or restarted mid-render; the workdir is gone either way.
        state.update(mode="idle", script=None, topic=None)
        save_state(state)

    async with httpx.AsyncClient() as client:
        await say(client, "🎬 shorts-factory พร้อมแล้ว ส่งหัวข้อมาได้เลย")
        while True:
            try:
                updates = await api(
                    client, "getUpdates", offset=state.get("offset", 0), timeout=30
                ) or []
            except Exception:
                logger.exception("getUpdates ล้มเหลว")
                await asyncio.sleep(5)
                continue

            for update in updates:
                state["offset"] = update["update_id"] + 1
                save_state(state)
                try:
                    await handle(client, state, update)
                except Exception:
                    logger.exception("handle ล้มเหลว")


if __name__ == "__main__":
    asyncio.run(main())
