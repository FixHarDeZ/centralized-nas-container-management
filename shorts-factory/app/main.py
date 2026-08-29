"""Telegram long-poll loop: the entire interface of this stack.

No HTTP server, no scheduler — see docs/adr/0002.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import httpx

from app import (analytics, backfill, experiment, history, manifest, render,
                 retention, script as script_gen, snapshots, trends, youtube)

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
# Prefix of the 💡 buttons under a /trends list: `pick:<suggested_at>:<index>`.
PICK_CB = "pick"
# The ✋ button under an automatic list: `cancel:<suggested_at>`.
CANCEL_CB = "cancel"
# Hours the bot goes looking for a Topic on its own, no one having asked.
AUTO_HOURS = tuple(
    sorted(int(h) for h in os.environ.get("TRENDS_HOURS", "8,12,17").split(",") if h.strip())
)
# How long the human has to pick one, or press ✋, before the bot picks itself.
AUTO_PICK_MINUTES = int(os.environ.get("AUTO_PICK_MINUTES", "15"))
# How far back /retention walks looking for a Clip YouTube has a curve for.
# ponytail: one Reports call per Clip tried. Skip Clips whose snapshots show
# too few views to have a curve (observed: 361 yes, 27 no) if this gets slow.
RETENTION_TRIES = 10
# How long a /trends list stays creditable for a Topic typed back.
SUGGESTION_LIFETIME = timedelta(days=2)
UPLOAD_KEYBOARD = {
    "inline_keyboard": [[{"text": "⬆️ อัปโหลดขึ้น YouTube", "callback_data": UPLOAD_CB}]]
}
REVIEW_KEYBOARD = {
    "inline_keyboard": [[
        {"text": "🎬 render", "callback_data": RENDER_CB},
        {"text": "🗑 ทิ้ง", "callback_data": DISCARD_CB},
    ]]
}


HELP = """🎬 shorts-factory

ส่งหัวข้อมาเฉยๆ = เริ่มทำคลิปใหม่
ระหว่างรอรีวิวสคริปต์ พิมพ์บอกได้ว่าอยากแก้ตรงไหน (บอทเขียนใหม่ให้)
🎬 render = ลงมือทำคลิป · 🗑 ทิ้ง = เริ่มใหม่ · ⬆️ = อัปขึ้น YouTube (ต้องกดเอง)

/stats — คลิปที่อัปแล้วทำได้แค่ไหน
   เรียงตาม % ที่คนดูจนจบ (ไม่ใช่ยอดวิว) เพราะมันคือตัวที่บอกว่า "เขียนดีขึ้นไหม"
   YouTube ประมวลผลช้ากว่าปัจจุบันหลายวัน คลิปที่เพิ่งอัปจะยังไม่มีตัวเลข

/snapshot — เก็บตัวเลขของวันนี้เดี๋ยวนี้เลย
   ปกติบอทเก็บเองวันละครั้งตอน 10 โมง ไม่ต้องสั่ง — คำสั่งนี้ไว้ใช้ตอนอยากได้เดี๋ยวนั้น
   ตัวเลข ณ วันที่ 7 หลังอัปคือตัวที่ใช้ตัดสินผลทดลอง (เก็บทุกวันแต่ใช้วันที่ 7)

/experiment — ผลการทดลองตอนนี้
   ทุกคลิปถูกสุ่มแบบเปิดเรื่อง: เปิดด้วยตัวเลขช็อก หรือเปิดด้วยคำถาม
   1 ใน 3 คลิปเป็นคลิป "ลองของใหม่" ไม่นับเข้าผลทดลอง (กันไม่ให้ระบบวนอยู่กับของเดิม)
   บอทจะยังไม่ฟันธงว่าฝั่งไหนชนะ จนกว่าจะครบ 10 คลิป + 300 views ทั้งสองฝั่ง
   และต่างกันเกิน 5 จุด — ไม่งั้นตอบ "สรุปไม่ได้" ซึ่งเป็นคำตอบที่ถูกต้อง ไม่ใช่ความล้มเหลว

/retention — คนดูหนีตอนไหน
   ส่งกราฟมาให้ พร้อมบอกว่าวินาทีที่คนหนีเยอะสุดคือ card ไหน พูดอะไรอยู่
   ใส่ id ต่อท้ายได้ เช่น /retention abc123 — ไม่ใส่ = ไล่หาคลิปล่าสุดที่มีข้อมูล
   YouTube ทำกราฟนี้ให้เฉพาะคลิปที่มีคนดูมากพอ (วัดแล้ว: 361 views มี, 27 views ไม่มี)

/trends — ตอนนี้คนไทยค้นอะไร ดูอะไรกันอยู่
   ดึงจาก Google Trends (ประเทศไทย) + ชาร์ตคลิปฮิตของ YouTube ไทย
   ส่งของดิบมาให้ดูด้วย แล้วค่อยเสนอหัวข้อที่ทำได้จริง 5 อัน — ชอบอันไหนกดปุ่มเลขได้เลย
   (พิมพ์หัวข้อเองก็ยังได้เหมือนเดิม ปุ่มเป็นแค่ทางลัด)
   ข่าวสด การเมือง คดี ผลแข่ง และเรื่องของคนจริง ถูกกรองทิ้ง (บอทจะแต่งข้อมูลมั่ว)
   🌱 evergreen = ดูได้อีกนาน · ⚡️ spike = ตายพร้อมกระแส
   บอทสั่ง /trends เองวันละ 3 รอบ (ตั้งไว้ที่ TRENDS_HOURS) — รอบอัตโนมัติจะมีปุ่ม ✋
   ไม่กดอะไรเลยภายใน AUTO_PICK_MINUTES นาที = บอทสุ่มหัวข้อมา 1 อัน เขียนสคริปต์แล้ว
   render ให้เองเลย (อัปขึ้น YouTube ยังต้องกดปุ่มเองเหมือนเดิม)

/help — หน้านี้"""


# Work that outlives one poll tick. Writing a Script takes 1-7 minutes and
# rendering takes longer; awaiting either inline froze the whole bot, so
# `/stats` or even `/help` would sit unanswered until it finished.
BUSY_MODES = {"writing", "rendering"}
_running: set[asyncio.Task] = set()


def spawn(coro, label: str) -> asyncio.Task:
    """Run something long off the poll loop, and never lose its exception."""
    task = asyncio.create_task(coro, name=label)
    _running.add(task)

    def done(finished: asyncio.Task) -> None:
        _running.discard(finished)
        if not finished.cancelled() and finished.exception():
            logger.error("%s ล้ม", label, exc_info=finished.exception())

    task.add_done_callback(done)
    return task


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


# --- the unattended run ------------------------------------------------------

def auto_slot(state: dict, now: datetime | None = None) -> str | None:
    """The /trends slot that is owed, or None. Same shape as snapshots.due().

    Only the newest passed hour is ever owed: a bot that was down all day comes
    back and runs once, not three times. A restart late in the evening does run
    the 17:00 slot late — the list is still worth having.
    """
    now = now or datetime.now()
    passed = [hour for hour in AUTO_HOURS if now.hour >= hour]
    if not passed:
        return None
    slot = f"{now.date().isoformat()}T{max(passed):02d}"
    return None if state.get("last_auto_trends") == slot else slot


def auto_pick_due(state: dict, now: datetime | None = None) -> bool:
    """Whether the wait for a human choice has run out."""
    pending = state.get("auto_pick") or {}
    try:
        return (now or datetime.now()) >= datetime.fromisoformat(pending["deadline"])
    except (KeyError, TypeError, ValueError):
        return False


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


def trend_origin(state: dict, topic: str) -> dict | None:
    """Whether this Topic came off the last /trends list, and from where.

    Matched loosely on purpose: the human retypes or trims a suggestion rather
    than copying it byte for byte.
    """
    # state.json outlives restarts, so an ancient list would credit a Topic to
    # a trend it has nothing to do with — corrupting the one field that exists
    # to answer whether trend topics did better.
    try:
        age = datetime.now() - datetime.fromisoformat(state.get("suggested_at", ""))
    except (TypeError, ValueError):
        return None
    if age > SUGGESTION_LIFETIME:
        return None

    head = topic.strip()[:16]
    for suggestion in state.get("suggested") or []:
        text = str(suggestion.get("topic", ""))
        if head and (head in text or text[:16] in topic):
            return {
                "from": suggestion.get("from", ""),
                "kind": suggestion.get("kind", ""),
                "category": suggestion.get("category", ""),
            }
    return None


async def make_script(client: httpx.AsyncClient, state: dict, topic: str,
                      feedback: str = "", auto: bool = False) -> None:
    # Every way a Topic can start routes through here, and any of them means a
    # pending automatic pick is no longer wanted.
    state.pop("auto_pick", None)
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
        origin = trend_origin(state, topic)
        if origin:
            manifest.update(state["clip_id"], trend=origin)
    # Retire the buttons on the script being replaced. Two live keyboards would
    # let the human approve the message they are looking at and get a different
    # script rendered, since state.message_id only tracks the newest one.
    await close_prompt(client, state.get("message_id"), f"📝 {previous['title']} — กำลังแก้ตามที่บอก" if previous else "")
    state["message_id"] = None

    # Claimed before the first await: the poll loop keeps running now, so a
    # second Topic could otherwise arrive mid-generation and overwrite this
    # one's clip_id and Variant.
    state["mode"] = "writing"
    save_state(state)
    await say(client, "🤔 กำลังเขียนสคริปต์... (ระหว่างนี้ใช้คำสั่งอื่นได้)")
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
            state.update(mode="review", script=previous,
                         message_id=(sent or {}).get("message_id"))
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
    # An unattended Script gets no review keyboard and no tracked message id:
    # nobody is going to press anything, and do_render() would overwrite the
    # message with "กำลัง render", erasing the only copy of what it rendered.
    sent = await say(client, format_script(script),
                     **({} if auto else {"reply_markup": REVIEW_KEYBOARD}))
    state.update(
        mode="review", topic=topic, script=script,
        message_id=None if auto else (sent or {}).get("message_id"),
    )
    save_state(state)
    if auto:
        # Inside the success path on purpose: a generate failure returns above
        # with no Script in state, and rendering that is a KeyError.
        await do_render(client, state)


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


def format_topics(topics: list[dict]) -> str:
    lines = ["💡 หัวข้อที่น่าทำ (กดเลขข้างล่าง หรือพิมพ์หัวข้อเองก็ได้)", ""]
    for i, topic in enumerate(topics, 1):
        tag = "🌱 evergreen" if topic.get("kind") == "evergreen" else "⚡️ spike"
        lines.append(f"{i}. {topic['topic']}")
        lines.append(
            f"    {tag} · {topic.get('category', '?')} · มาจาก: {topic.get('from', '?')[:40]}"
        )
        if topic.get("why"):
            lines.append(f"    {topic['why'][:90]}")
    return "\n".join(lines)


async def on_trends(client: httpx.AsyncClient, state: dict, auto: bool = False) -> None:
    """What Thailand is searching for and watching, turned into Topics.

    The raw list is sent too: a suggestion that drifted from its source is only
    catchable against the thing it came from.
    """
    await say(client, "📈 กำลังดู trend...")
    rows = await trends.collect()
    await say(client, trends.format_raw(rows))
    if not rows:
        return
    try:
        topics = await script_gen.suggest_topics(rows)
    except Exception as exc:
        logger.exception("suggest_topics failed")
        await say(client, f"แปลง trend เป็นหัวข้อไม่สำเร็จ: {exc}")
        return

    # Remembered so a Topic typed back gets its origin recorded — the point of
    # the whole exercise is answering "did trend topics do better?" later.
    state["suggested"] = topics
    state["suggested_at"] = datetime.now().isoformat(timespec="seconds")
    keyboard = topics_keyboard(topics, state["suggested_at"])
    if auto:
        deadline = datetime.now() + timedelta(minutes=AUTO_PICK_MINUTES)
        state["auto_pick"] = {"deadline": deadline.isoformat(timespec="seconds")}
        keyboard["inline_keyboard"].append([{
            "text": f"✋ ไม่ต้องทำรอบนี้ (ไม่กด = สุ่มทำเองใน {AUTO_PICK_MINUTES} นาที)",
            "callback_data": f"{CANCEL_CB}:{state['suggested_at']}",
        }])
    save_state(state)
    sent = await say(client, format_topics(topics), reply_markup=keyboard)
    if auto:
        state["trends_message_id"] = (sent or {}).get("message_id")
        save_state(state)


async def auto_pick(client: httpx.AsyncClient, state: dict) -> None:
    """Nobody chose and nobody said no: take one at random and make the clip.

    The Topic goes in verbatim so trend_origin() still credits the list it came
    from — an unattended clip is the same kind of record as a chosen one.
    """
    topics = state.get("suggested") or []
    if not topics:
        return
    topic = str(random.choice(topics).get("topic", "")).strip()
    if not topic:
        return
    await retire_buttons(client, state.pop("trends_message_id", None))
    await say(client, f"🎲 ไม่มีใครเลือก สุ่มได้: {topic}\nเขียนสคริปต์แล้ว render ให้เลย")
    await make_script(client, state, topic, auto=True)


def topics_keyboard(topics: list[dict], stamp: str) -> dict:
    """One button per suggestion, each carrying the list it belongs to."""
    return {"inline_keyboard": [[
        {"text": str(i), "callback_data": f"{PICK_CB}:{stamp}:{i - 1}"}
        for i in range(1, len(topics) + 1)
    ]]}


def picked(state: dict, data: str) -> str | None:
    """The Topic behind a 💡 button, or None if its list is no longer the live one.

    The index alone means nothing: run /trends twice and button 3 on the older
    message points into the newer list, so the bot would start writing a Topic
    nobody chose. The list's timestamp travels in the callback data and a tap
    on a superseded message is refused instead.
    """
    stamp, _, index = data[len(PICK_CB) + 1:].rpartition(":")
    if not stamp or stamp != state.get("suggested_at"):
        return None
    # Same expiry the recorder uses: past it, trend_origin() refuses to credit
    # the Topic, so accepting the tap would write a Clip with no trend field —
    # losing the one number /trends exists to produce.
    if datetime.now() - datetime.fromisoformat(stamp) > SUGGESTION_LIFETIME:
        return None
    try:
        return str((state.get("suggested") or [])[int(index)]["topic"])
    except (ValueError, IndexError, KeyError, TypeError):
        return None


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
    if text.startswith("/help") or text.startswith("/start"):
        # No parse_mode: Telegram's Markdown rejects unbalanced markers and
        # answers 400, which would leave the help unreachable.
        await say(client, HELP)
        return
    if text.startswith("/stats"):
        await on_stats(client)
        return
    if text.startswith("/snapshot"):
        await take_snapshots(client, state, announce=True)
        return
    if text.startswith("/trends"):
        spawn(on_trends(client, state), "on_trends")
        return
    if text.startswith("/experiment"):
        await say(client, experiment.report(manifest.load_all()))
        return
    if text.startswith("/retention"):
        await on_retention(client, text.split(maxsplit=1)[1].strip() if " " in text else "")
        return

    mode = state.get("mode", "idle")
    if mode in BUSY_MODES:
        job = "เขียนสคริปต์" if mode == "writing" else "render"
        await say(client, f"⏳ กำลัง{job}อยู่ รอให้เสร็จก่อนนะ")
    elif mode == "review":
        # A pending Script is work in progress: plain text revises it rather
        # than silently discarding it. Starting over is the 🗑 button.
        spawn(make_script(client, state, state["topic"], feedback=text), "make_script")
    else:
        spawn(make_script(client, state, text), "make_script")


async def on_callback(client: httpx.AsyncClient, state: dict, query: dict) -> None:
    await api(client, "answerCallbackQuery", callback_query_id=query["id"])
    data = query.get("data") or ""
    if data.startswith(f"{PICK_CB}:"):
        await on_pick(client, state, data)
        return
    if data.startswith(f"{CANCEL_CB}:"):
        # Above the mode guard below: the bot is idle while a list is pending,
        # so that guard would drop this tap without a word.
        await on_cancel(client, state, data[len(CANCEL_CB) + 1:])
        return
    if query.get("data") != UPLOAD_CB and state.get("mode") != "review":
        return
    if query.get("data") == UPLOAD_CB:
        spawn(do_upload(client, state), "do_upload")
        return
    if query.get("data") == RENDER_CB:
        spawn(do_render(client, state), "do_render")
    elif query.get("data") == DISCARD_CB:
        await close_prompt(client, state.get("message_id"), "🗑 ทิ้งสคริปต์แล้ว")
        manifest.update(state.get("clip_id"), outcome="discarded")
        state.update(mode="idle", script=None, topic=None, message_id=None, clip_id=None, style="")
        save_state(state)
        await say(client, "ทิ้งแล้ว ส่งหัวข้อใหม่มาได้เลย")


async def on_cancel(client: httpx.AsyncClient, state: dict, stamp: str) -> None:
    """✋ on an automatic list: drop the pending pick, keep the list usable.

    The stamp travels in the callback data for the same reason picked() checks
    it — a tap on an older message must not call off today's run.
    """
    if not stamp or stamp != state.get("suggested_at"):
        await say(client, "ลิสต์นี้เก่าแล้ว สั่ง /trends ใหม่ก่อนนะ")
        return
    cancelled = state.pop("auto_pick", None)
    message_id = state.pop("trends_message_id", None)
    save_state(state)
    # Only the ✋ row goes; the 💡 numbers stay pressable if the human changes
    # their mind, and editMessageReplyMarkup leaves the list text alone.
    if message_id:
        await api(client, "editMessageReplyMarkup", chat_id=CHAT_ID, message_id=message_id,
                  reply_markup=topics_keyboard(state.get("suggested") or [], stamp))
    await say(client, "ได้ ไม่ทำรอบนี้" if cancelled else "รอบนี้ยกเลิกไปแล้ว")


async def on_pick(client: httpx.AsyncClient, state: dict, data: str) -> None:
    """A suggestion tapped instead of retyped. Same path as a Topic sent by hand."""
    topic = picked(state, data)
    if topic is None:
        await say(client, "ลิสต์นี้เก่าแล้ว สั่ง /trends ใหม่ก่อนนะ")
        return
    mode = state.get("mode", "idle")
    if mode in BUSY_MODES:
        job = "เขียนสคริปต์" if mode == "writing" else "render"
        await say(client, f"⏳ กำลัง{job}อยู่ รอให้เสร็จก่อนนะ")
        return
    if mode == "review":
        # Starting a new Topic here would abandon the pending Script without
        # marking it discarded, leaving an outcome-less record in the Manifest.
        await say(client, "ยังมีสคริปต์ค้างอยู่ กด 🗑 ทิ้งก่อนแล้วค่อยเลือกหัวข้อใหม่")
        return
    # Verbatim, so trend_origin matches it and the origin gets recorded.
    await say(client, f"👍 {topic}")
    spawn(make_script(client, state, topic), "make_script")


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
    if state.get("mode") in BUSY_MODES:
        # Crashed or restarted mid-job; the workdir is gone either way.
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
            slot = auto_slot(state)
            if slot:
                # Stamped before the work: suggest_topics() can take minutes and
                # runs off the loop, so an unstamped slot fires again in 30s.
                state["last_auto_trends"] = slot
                save_state(state)
                spawn(on_trends(client, state, auto=True), "auto_trends")
            if auto_pick_due(state):
                pending = state.pop("auto_pick", None)
                save_state(state)
                # A human already busy with a Script of their own does not get a
                # second one queued behind it; the pending pick is simply dropped.
                if pending and state.get("mode", "idle") == "idle":
                    spawn(auto_pick(client, state), "auto_pick")
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
