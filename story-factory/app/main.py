"""Telegram long-poll loop: the entire interface of this stack.

No HTTP server, no dashboard, no scheduler. The only trust boundary is the chat
id filter, exactly as in shorts-factory's ADR 0002.

The shape of a Story, per ADR 0010: a subject arrives, the bot sends the Outline
and waits — that is the only blocking human step. After approval it writes seven
Chapters, voices them, renders, and reports a path. The prose goes out as a
`.txt` attachment which nobody is required to read.

One job at a time. The job is an asyncio Task held in `_current`; `/cancel`
cancels it, which kills whatever ffmpeg it was waiting on (see `render.run`).
Everything the job has finished so far is already on disk (`app/story.py`), so
cancelling — or crashing — loses at most the Chapter in flight.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx

from . import config, render, script as script_gen, story, telegram, timeline, topics, tts

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("story-factory")


STATE_PATH = config.data_dir() / "state.json"
# A Story is ~470 MB against a 50 MB sendVideo ceiling, so the file never goes
# to the phone. The bot reports where it is instead.
APPROVE_CB = "approve"
DISCARD_CB = "discard"
RESUME_CB = "resume"
DROP_RESUME_CB = "drop_resume"

HELP = """เล่าเรื่องยาว

/story <หัวข้อ> — เริ่มเรื่องใหม่ บอทจะส่ง Outline มาให้อนุมัติก่อน
/resume — ทำเรื่องที่ค้างไว้ต่อ (ไม่เขียนบทที่เขียนแล้วซ้ำ ไม่จ่ายเสียงซ้ำ)
/cancel — หยุดงานที่กำลังทำ หรือทิ้ง Outline ที่รออนุมัติ
/help — ข้อความนี้

ใส่ ! นำหน้าหัวข้อ = ข้ามด่านกันหัวข้อศาสนา (docs/adr/0011)"""

#: The one job in flight. `/cancel` cancels it; startup finds it None.
_current: asyncio.Task | None = None


def load_state() -> dict:
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {"mode": "idle", "stories_rendered": 0}


def save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def begin(state: dict, coro) -> None:
    """Stamp busy and start the one job.

    Stamped here, synchronously, not inside the task: two commands arriving
    before the first task is scheduled would both pass the idle check.
    shorts-factory learned this with `trends_running`.
    """
    global _current
    state["mode"] = "working"
    save_state(state)
    _current = asyncio.create_task(coro)


def busy() -> bool:
    return _current is not None and not _current.done()


# --- Outline ------------------------------------------------------------------

async def make_outline(bot: telegram.Bot, state: dict, subject: str):
    """The caller has already stamped `mode` busy, so every exit from here has
    to hand it back — an Outline that fails must not wedge the bot."""
    try:
        await _outline(bot, state, subject)
    except asyncio.CancelledError:
        await bot.say("ยกเลิก Outline แล้ว")
    finally:
        if state.get("mode") == "working":
            state["mode"] = "idle"
            save_state(state)


async def _outline(bot: telegram.Bot, state: dict, subject: str):
    try:
        topics.check(
            subject,
            state.get("stories_rendered", 0),
            config.religion_gate_until_stories(),
        )
    except topics.Blocked as blocked:
        await bot.say(str(blocked))
        return

    subject = topics.strip_override(subject)
    await bot.say(f"กำลังวาง Outline ของ «{subject}» …")

    try:
        chapters = await script_gen.outline(subject)
    except script_gen.ScriptError as error:
        await bot.say(f"เขียน Outline ไม่สำเร็จ: {error}")
        return

    state["pending"] = {"subject": subject, "chapters": chapters}
    state["mode"] = "awaiting_approval"
    save_state(state)

    listing = "\n".join(f"{i}. {t}" for i, t in enumerate(chapters, 1))
    await bot.say(
        f"«{subject}»\n\n{listing}\n\nอนุมัติแล้วบอทเขียนต่อจนจบ ไม่ถามอีก",
        reply_markup={
            "inline_keyboard": [
                [
                    {"text": "✅ เขียนเลย", "callback_data": APPROVE_CB},
                    {"text": "🗑 ทิ้ง", "callback_data": DISCARD_CB},
                ],
            ],
        },
    )


# --- Story --------------------------------------------------------------------

async def make_story(bot: telegram.Bot, state: dict, job: story.Job):
    """Everything after the one approval, from wherever `job` left off.

    Every Chapter is checkpointed the moment it is written and again once it
    is voiced, so a failure or a `/cancel` here costs at most the step in
    flight. The next `/resume` picks up from the checkpoint.
    """
    total = len(job.titles)
    # Speech for Chapter N runs while the model writes Chapter N+1. Writing is
    # sequential (each Chapter gets the ones before it as context); voicing
    # is not, and it is roughly a third of the wall clock before the encode.
    voices: list[asyncio.Task] = []
    try:
        for index in range(total):
            title = job.titles[index]
            if index >= job.next_index:
                await bot.say(f"บทที่ {index + 1}/{total}: {title}")
                so_far = "\n\n".join(c.prose for c in job.chapters)
                chapter = await script_gen.chapter(job.subject, title, so_far)
                job.chapters.append(story.Done(
                    title,
                    [{"text": p.text, "source": p.source} for p in chapter.passages],
                ))
                job.save()

            if not job.voiced(index):
                voices.append(asyncio.create_task(_voice(job, index)))

        await asyncio.gather(*voices)

        narration = await render.concat(
            [job.audio(i) for i in range(total)], job.workdir / "narration.wav",
        )

        markers = timeline.markers(
            job.titles, [c.duration or 0.0 for c in job.chapters],
        )
        dest = config.output_dir() / f"{int(job.started)}-{job.subject[:40]}.mp4"
        backdrop = await _backdrop(job.workdir)
        # 0.61x realtime measured on the NAS (app/render.py header).
        eta = sum(markers_durations(job)) / 60 / 0.61
        await bot.say(f"กำลัง render (~{eta:.0f} นาที) …")
        await render.build(backdrop, narration, dest)

        prose_path = job.workdir / "story.txt"
        prose_path.write_text(
            "\n\n\n".join(f"{c.title}\n\n{c.prose}" for c in job.chapters),
        )
        await bot.send_document(
            prose_path,
            "ตัวบทเต็ม — ไม่ต้องอ่านก็ได้ มีไว้เผื่ออยากเช็ค (docs/adr/0010)",
        )
        await bot.say(
            f"เสร็จแล้ว\n\nไฟล์: {dest}\n"
            f"ขนาดประมาณ {dest.stat().st_size / 1_000_000:.0f} MB "
            f"(ใหญ่เกินส่งเข้า Telegram ต้องไปหยิบจากเครื่อง)\n\n"
            f"Timestamps:\n{timeline.description_block(markers)}",
        )
        job.outcome, job.output = "finished", str(dest)
        job.save()
        story.prune()
        state["stories_rendered"] = state.get("stories_rendered", 0) + 1
    except asyncio.CancelledError:
        await bot.say(
            f"หยุดแล้ว ค้างที่บท {job.next_index}/{total} — "
            f"/resume ทำต่อได้ ไม่เขียนซ้ำ ไม่จ่ายเสียงซ้ำ",
        )
    except Exception as error:  # noqa: BLE001 — the bot must survive any failure
        logger.exception("story failed")
        await bot.say(
            f"พังระหว่างทำ: {error}\n\n"
            f"ค้างที่บท {job.next_index}/{total} — /resume ทำต่อได้",
        )
    finally:
        # A voice task still running past this point would write into a
        # workdir that `/resume` is about to reopen.
        for voice in voices:
            voice.cancel()
        state["mode"] = "idle"
        save_state(state)


async def _voice(job: story.Job, index: int) -> None:
    done = job.chapters[index]
    done.duration = await tts.voice_chapter(done.prose, job.audio(index), job.scratch(index))
    job.save()


def markers_durations(job: story.Job) -> list[float]:
    return [c.duration or 0.0 for c in job.chapters]


async def _backdrop(workdir: Path) -> Path:
    """The Flow clip for this Story, looped forwards and backwards.

    Flow footage is generated by the human (docs/adr/0005); dropping the file in
    is how it arrives. With none, a still stands in.
    """
    supplied = config.output_dir() / "backdrop.mp4"
    if supplied.exists():
        return await render.ping_pong(supplied, workdir / "backdrop-loop.mp4")
    still = config.output_dir() / "backdrop.png"
    if still.exists():
        return still
    raise FileNotFoundError(
        f"ไม่มี Backdrop — วาง backdrop.mp4 (ยาวไม่เกิน "
        f"{config.backdrop_max_seconds():.0f} วิ) หรือ backdrop.png ไว้ที่ "
        f"{config.output_dir()}",
    )


async def offer_resume(bot: telegram.Bot, job: story.Job) -> None:
    await bot.say(
        f"มีเรื่องค้างอยู่: «{job.subject}» เขียนแล้ว {job.next_index}/{len(job.titles)} บท\n"
        f"ทำต่อไหม",
        reply_markup={
            "inline_keyboard": [
                [
                    {"text": "▶ ทำต่อ", "callback_data": RESUME_CB},
                    {"text": "🗑 ทิ้ง", "callback_data": DROP_RESUME_CB},
                ],
            ],
        },
    )


def start_resume(bot: telegram.Bot, state: dict) -> str:
    """Resume the newest unfinished Job, if any. Returns what to tell the human."""
    if busy():
        return "ยังทำเรื่องเดิมอยู่ รอให้จบก่อน หรือ /cancel"
    job = story.unfinished()
    if job is None:
        return "ไม่มีเรื่องค้าง"
    state.pop("pending", None)
    begin(state, make_story(bot, state, job))
    return f"ทำต่อ «{job.subject}» จากบท {job.next_index + 1}/{len(job.titles)}"


# --- Commands -----------------------------------------------------------------

async def handle(bot: telegram.Bot, state: dict, update: dict):
    message = update.get("message") or {}
    callback = update.get("callback_query")

    if callback:
        await bot.answer(callback)
        data = callback["data"]
        if data == APPROVE_CB and state.get("pending") and not busy():
            # Pop here, not inside the task: a second tap finds no `pending`
            # and does nothing, instead of starting a second Story.
            pending = state.pop("pending")
            job = story.new(pending["subject"], pending["chapters"])
            begin(state, make_story(bot, state, job))
        elif data == DISCARD_CB:
            state.pop("pending", None)
            if not busy():
                state["mode"] = "idle"
            save_state(state)
            await bot.say("ทิ้งแล้ว")
        elif data == RESUME_CB:
            await bot.say(start_resume(bot, state))
        elif data == DROP_RESUME_CB:
            job = story.unfinished()
            if job is not None:
                job.outcome = "abandoned"
                job.save()
                await bot.say(f"ทิ้ง «{job.subject}» แล้ว ไฟล์ยังอยู่ที่ {job.workdir}")
        return

    text = (message.get("text") or "").strip()
    if not text:
        return

    if text.startswith("/story"):
        subject = text[len("/story"):].strip()
        if not subject:
            await bot.say("ใส่หัวข้อมาด้วย: /story เมกะโลดอนยังมีชีวิตอยู่ไหม")
        elif busy() or state.get("mode") != "idle":
            await bot.say("ยังทำเรื่องเดิมอยู่ รอให้จบก่อน หรือ /cancel")
        else:
            begin(state, make_outline(bot, state, subject))
    elif text.startswith("/resume"):
        await bot.say(start_resume(bot, state))
    elif text.startswith("/cancel"):
        if busy():
            # The task's own handler reports what was kept; ffmpeg dies with it.
            _current.cancel()
            return
        if state.get("mode") == "awaiting_approval":
            state.pop("pending", None)
            state["mode"] = "idle"
            save_state(state)
            await bot.say("ทิ้ง Outline แล้ว")
        else:
            await bot.say("ไม่มีอะไรให้ยกเลิก")
    elif text.startswith("/help") or text.startswith("/start"):
        await bot.say(HELP)
    elif text.startswith("/"):
        # Never fall through to treating this as a subject: shorts-factory ended
        # up with a Story named `/stat` that way.
        await bot.say("ไม่รู้จักคำสั่ง — /help")


async def run() -> None:
    tts.write_credentials()
    state = load_state()
    # `finally` does not run when the container is killed, so a mode left mid-
    # flight has to be cleared on the way up rather than trusted. The work
    # itself is not lost: it is in the workdir, and offered back below.
    state["mode"] = "idle"
    save_state(state)

    offset = 0
    async with httpx.AsyncClient(timeout=60) as client:
        bot = telegram.Bot.from_env(client)
        job = story.unfinished()
        if job is not None:
            await offer_resume(bot, job)

        while True:
            try:
                for update in await bot.updates(offset):
                    offset = update["update_id"] + 1
                    if not bot.mine(update):
                        continue
                    await handle(bot, state, update)
            except Exception:  # noqa: BLE001 — the loop outlives any one update
                logger.exception("poll failed")
                await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(run())
