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

from app import (analytics, backfill, experiment, history, manifest, render,
                 retention, script as script_gen, snapshots, youtube)

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
# How far back /retention walks looking for a Clip YouTube has a curve for.
# ponytail: one Reports call per Clip tried. Skip Clips whose snapshots show
# too few views to have a curve (observed: 361 yes, 27 no) if this gets slow.
RETENTION_TRIES = 10
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

    srt = clip.parent / "captions.srt"
    final_srt = OUTPUT_DIR / f"{stem}.srt"
    if srt.exists():
        shutil.copy2(srt, final_srt)

    # Publishing is outward-facing and cannot be undone quietly, so it stays
    # behind a button even though everything up to here is automatic.
    offer_upload = youtube.configured()
    sent = await send_video(
        client, final, metadata_text(script),
        **({"reply_markup": UPLOAD_KEYBOARD} if offer_upload else {}),
    )
    await say(client, f"✅ เสร็จแล้ว เก็บไว้ที่ {final}")
    # The upload button outlives this Topic — the human can send a new one and
    # press upload on an older clip afterwards. Everything the upload needs is
    # snapshotted here for that reason; reading the live `clip_id`/`topic`
    # would stamp the new Topic's Manifest with the old clip's video id.
    state.update(
        last_clip=str(final),
        last_srt=str(final_srt) if srt.exists() else None,
        last_script=script,
        last_clip_id=state.get("clip_id"),
        last_topic=state.get("topic"),
        upload_message_id=(sent or {}).get("message_id") if offer_upload else None,
    )
    save_state(state)


async def make_script(client: httpx.AsyncClient, state: dict, topic: str, feedback: str = "") -> None:
    previous = state.get("script") if feedback else None
    # A revision belongs to the Manifest already open for this Topic; only a
    # fresh Topic starts a new one.
    if previous is None:
        state["clip_id"] = manifest.start(topic)
        # Assigned before the Script exists and never re-rolled: a Script
        # rewritten on feedback keeps the Variant it was born with, or the
        # human's taste would quietly pick the winner (docs/adr/0004).
        assignment = experiment.assign()
        manifest.update(state["clip_id"], **assignment)
        state["style"] = assignment["style"]
    # Retire the buttons on the script being replaced. Two live keyboards would
    # let the human approve the message they are looking at and get a different
    # script rendered, since state.message_id only tracks the newest one.
    await close_prompt(client, state.get("message_id"), f"📝 {previous['title']} — กำลังแก้ตามที่บอก" if previous else "")
    state["message_id"] = None

    await say(client, "🤔 กำลังเขียนสคริปต์...")
    try:
        script = await script_gen.generate(
            topic,
            previous=previous,
            feedback=feedback,
            avoid=history.recent_titles(),
            winners=await analytics.winning_examples(),
            style=state.get("style", ""),
        )
    except Exception as exc:
        logger.exception("generate failed")
        if previous is not None:
            # A blip during a revision must not throw away the script being
            # worked on; re-post it so its buttons come back.
            sent = await say(client, format_script(previous), reply_markup=REVIEW_KEYBOARD)
            state["message_id"] = (sent or {}).get("message_id")
        else:
            # A Topic that never produced a Script is not a Clip. Recorded so
            # the Gate cannot be reached on failures, and so a clause that
            # makes the model return junk shows up as its own number.
            manifest.update(state.get("clip_id"), outcome="generate_failed",
                            error=str(exc)[:500])
            state.update(mode="idle", script=None, clip_id=None, style="")
        save_state(state)
        await say(client, f"เขียนสคริปต์ไม่สำเร็จ: {exc}")
        return

    manifest.add_script(state.get("clip_id"), script)
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
        clip, details = await render.build(script, workdir)
        manifest.update(state.get("clip_id"), outcome="rendered", render=details)
        await deliver(client, state, script, clip)
    except Exception as exc:
        logger.exception("render failed")
        manifest.update(state.get("clip_id"), outcome="render_failed", error=str(exc)[:500])
        await say(client, f"render ล้มเหลว: {exc}")
    finally:
        # Intermediate PNG/audio dwarf the mp4; never leave them behind.
        shutil.rmtree(workdir, ignore_errors=True)
        state.update(mode="idle", script=None, topic=None, clip_id=None, style="")
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

    # Off by default: the Shorts feed and the channel grid ignore custom
    # thumbnails and show a frame YouTube picks itself, so setting one only
    # reaches search and suggestions. Kept behind a flag rather than deleted.
    thumbnail_note = ""
    if os.environ.get("YOUTUBE_SET_THUMBNAIL", "").lower() in ("1", "true", "yes"):
        try:
            cover = render.first_frame(clip, clip.with_suffix(".jpg"))
            await youtube.set_thumbnail(video_id, cover)
            thumbnail_note = "\nปก: เฟรมแรกของคลิป"
        except Exception as exc:
            logger.exception("thumbnail failed")
            thumbnail_note = f"\n⚠️ ตั้งปกไม่ได้: {exc} (คลิปขึ้นแล้ว ตั้งเองใน Studio ได้)"

    captions_note = ""
    srt = Path(state.get("last_srt") or "")
    if srt.is_file():
        try:
            await youtube.add_captions(video_id, srt)
            captions_note = "\nซับ: ใส่แล้ว"
        except Exception as exc:
            logger.exception("captions failed")
            captions_note = f"\n⚠️ ใส่ซับไม่ได้: {exc}"

    history.record(video_id, script, state.get("last_topic") or "")
    manifest.update(
        state.get("last_clip_id"),
        published=True,
        video_id=video_id,
        privacy=privacy,
        published_at=datetime.now().isoformat(timespec="seconds"),
    )

    url = f"https://youtu.be/{video_id}"
    note = (
        f"⬆️ ขึ้นช่องแล้ว: {url}\n"
        f"สถานะ: {privacy}{thumbnail_note}{captions_note}\n\n"
        # The Shorts feed ignores custom thumbnails and picks its own frame, and
        # there is no API for that cover — only the mobile app can set it, where
        # the first option is the opening frame.
        "ปกในฟีด Shorts ตั้งผ่าน API ไม่ได้ — เปิดในแอป YouTube → Edit → Cover → เลือกอันแรก"
    )
    if privacy != os.environ.get("YOUTUBE_PRIVACY", "public"):
        # Google forces uploads from an unaudited project to private.
        note += "\n⚠️ YouTube เปลี่ยนสถานะเอง — โปรเจกต์ยังไม่ผ่าน API audit"
    await say(client, note)
    state.update(
        last_clip=None, last_srt=None, last_script=None,
        last_clip_id=None, last_topic=None,
    )
    save_state(state)


async def send_photo(client: httpx.AsyncClient, path: Path, caption: str) -> None:
    with path.open("rb") as handle:
        reply = await client.post(
            f"{API}/sendPhoto",
            data={"chat_id": CHAT_ID, "caption": caption[:1024]},
            files={"photo": (path.name, handle, "image/png")},
            timeout=120,
        )
    if not reply.json().get("ok"):
        logger.error("sendPhoto: %s", reply.text[:400])
        await say(client, caption)


# --- dispatch ----------------------------------------------------------------

async def on_stats(client: httpx.AsyncClient) -> None:
    await say(client, "📊 กำลังดึงสถิติ...")
    try:
        rows = await analytics.performance()
        as_of = await analytics.latest_data_date() if not rows else None
        await say(client, analytics.format_report(rows, as_of))
    except Exception as exc:
        logger.exception("stats failed")
        await say(client, f"ดึงสถิติไม่ได้: {exc}")


async def take_snapshots(client: httpx.AsyncClient, state: dict, announce: bool = False) -> None:
    """Record today's numbers. Never fatal — the bot's job is making clips."""
    try:
        written = await snapshots.run()
        logger.info("snapshot %d คลิป", written)
        if announce:
            await say(client, f"📸 บันทึกตัวเลขของ {written} คลิปแล้ว")
    except Exception as exc:
        logger.exception("snapshot failed")
        if announce:
            await say(client, f"เก็บ snapshot ไม่ได้: {exc}")
    finally:
        # Stamped even on failure. `due()` is checked on every poll tick, so a
        # dead refresh token (ADR 0001) would otherwise mean a token request
        # every 30 seconds until someone noticed. Losing a day costs nothing:
        # day7() takes the first reading at age 7 or later.
        state["last_snapshot"] = datetime.now().date().isoformat()
        save_state(state)


async def on_retention(client: httpx.AsyncClient, video_id: str = "") -> None:
    """The retention curve of one Clip, read against its own Cards.

    Without an id it walks back from the newest published Clip until one has a
    curve: YouTube only builds them once a Clip has been watched enough, so the
    newest is usually not the one with data.
    """
    published = [r for r in manifest.load_all() if r.get("video_id")]
    published.sort(key=lambda r: r.get("published_at") or "", reverse=True)
    if video_id:
        published = [r for r in published if r["video_id"] == video_id]
    if not published:
        await say(client, "ไม่เจอคลิปที่อัปแล้วในบันทึก")
        return

    await say(client, "📉 กำลังดึงเส้น retention...")
    last_error = "ยังไม่มีคลิปไหนมีเส้น retention"
    # One session for the whole walk: refreshing the access token once per
    # Clip is three requests where one will do.
    async with httpx.AsyncClient(timeout=60) as session:
        for record in published[:RETENTION_TRIES]:
            details = record.get("render") or {}
            cards = details.get("cards") or []
            duration = details.get("seconds") or 0
            if not duration:
                continue
            try:
                rows = await retention.fetch(record["video_id"], session)
            except retention.NoCurve as exc:
                last_error = str(exc)
                continue
            except Exception as exc:
                logger.exception("retention failed")
                await say(client, f"ดึงเส้น retention ไม่ได้: {exc}")
                return

            title = record.get("title") or (record.get("scripts") or [{}])[-1].get(
                "script", {}
            ).get("title", record["video_id"])
            png = DATA_DIR / f"retention-{record['video_id']}.png"
            retention.chart(rows, duration, cards, png, title)
            await send_photo(
                client, png,
                f"📉 {title}\n{retention.summary(rows, duration, cards)}",
            )
            return

    await say(client, last_error)


async def on_text(client: httpx.AsyncClient, state: dict, text: str) -> None:
    if text.startswith("/stats"):
        await on_stats(client)
        return
    if text.startswith("/snapshot"):
        await take_snapshots(client, state, announce=True)
        return
    if text.startswith("/experiment"):
        await say(client, experiment.report(manifest.load_all()))
        return
    if text.startswith("/retention"):
        await on_retention(client, text.split(maxsplit=1)[1].strip() if " " in text else "")
        return

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
        manifest.update(state.get("clip_id"), outcome="discarded")
        state.update(mode="idle", script=None, topic=None, message_id=None, clip_id=None, style="")
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

    restored = backfill.run()
    if restored:
        logger.info("สร้าง manifest ย้อนหลัง %d คลิป", restored)

    async with httpx.AsyncClient() as client:
        await say(client, "🎬 shorts-factory พร้อมแล้ว ส่งหัวข้อมาได้เลย")
        while True:
            # The daily pull rides the poll loop rather than a scheduler
            # thread: getUpdates already wakes every 30s. See app/snapshots.py.
            if snapshots.due(state):
                await take_snapshots(client, state)
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
