"""Talking to mimo: the Outline first, then one Chapter at a time.

Two habits are carried over from shorts-factory, both bought with incidents:

  * every model call is wrapped in `asyncio.wait_for`. httpx's `timeout` is
    per-read, not a ceiling on the whole call, so a server that dribbles bytes
    never times out — and this bot's poll loop would hang with it.
  * `max_tokens` is never used to bound a call. mimo-v2.5-pro spends reasoning
    tokens against that budget first and returns `content=''`.

The budget is a deadline shared across every retry, not a per-attempt timeout:
a fast bad answer used to burn a whole attempt while 400 seconds went unused.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from . import config, mimo, sources

MAX_ATTEMPTS = 4


class ScriptError(Exception):
    pass


class ScriptStalled(ScriptError):
    """Every request went silent inside the budget. Observed in shorts-factory
    as a window rather than a per-request fault — hedging never once rescued it,
    and waiting did. The caller sleeps and tries the subject again, once."""


@dataclass
class Chapter:
    title: str
    passages: list[sources.Passage]

    @property
    def prose(self) -> str:
        return "\n\n".join(p.text for p in self.passages)


async def _ask(messages: list[dict], deadline: mimo.Deadline) -> str:
    """One model call, bounded by the shared deadline."""
    try:
        return await mimo.complete(mimo.client(), messages, within=deadline.remaining)
    except mimo.Stalled as stalled:
        raise ScriptStalled(str(stalled)) from stalled
    except mimo.Truncated as truncated:
        raise ScriptError(str(truncated)) from truncated


def _json(raw: str) -> dict:
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end < 0:
        raise ScriptError("model did not return JSON")
    return json.loads(raw[start : end + 1])


OUTLINE_PROMPT = """คุณเขียนสารคดีเสียงภาษาไทยความยาว 30-40 นาที

หัวข้อ: {subject}

ส่ง JSON เท่านั้น:
{{"subject": "...", "chapters": ["ชื่อบทที่ 1", ...]}}

ต้องมี {count} บท เรียงตามลำดับการเล่า
บทแรกคือการเปิดเรื่อง บทสุดท้ายคือการสรุปที่ทิ้งคำถามไว้
ชื่อบทเป็นภาษาไทย สั้น ไม่ใช่ประโยคเต็ม"""


CHAPTER_PROMPT = """เขียนบท "{title}" ของสารคดีเรื่อง "{subject}" ประมาณ {words} คำ

บทก่อนหน้าเล่าไปแล้วว่า:
{so_far}

โทน: อุ่น นิ่ง เล่าช้า แบบสารคดี ไม่ใช่เสียงกล่อมนอน ไม่มีคำทักทาย ไม่มีการเกริ่นว่านี่คือบทที่เท่าไร

ส่ง JSON เท่านั้น:
{{"passages": [{{"text": "...", "source": "ชื่อแหล่งอ้างอิง หรือเว้นว่างถ้าไม่มี"}}]}}

กติกาที่ตรวจด้วยโปรแกรม ไม่ใช่ขอความร่วมมือ:
- ข้อความที่มี source พูดเป็นข้อเท็จจริงได้
- ข้อความที่ไม่มี source ต้องขึ้นต้นหรือมีคำว่าเล่ากันว่า/ว่ากันว่า/เชื่อกันว่า
- ข้อความที่ไม่มี source ห้ามมีตัวเลข ปี พ.ศ. หรือ ค.ศ. เด็ดขาด
- ใส่ source เฉพาะแหล่งที่มีอยู่จริงและคุณจำได้ ห้ามแต่งชื่อแหล่ง"""


async def outline(subject: str) -> list[str]:
    deadline = mimo.Deadline()
    prompt = OUTLINE_PROMPT.format(subject=subject, count=config.chapters_per_story())

    for _ in range(MAX_ATTEMPTS):
        try:
            data = _json(await _ask([{"role": "user", "content": prompt}], deadline))
        except ScriptStalled:
            raise
        except (ScriptError, json.JSONDecodeError):
            continue
        chapters = data.get("chapters") or []
        if len(chapters) == config.chapters_per_story():
            return [str(c) for c in chapters]

    raise ScriptStalled("no usable Outline inside the budget")


async def chapter(subject: str, title: str, so_far: str) -> Chapter:
    """Write one Chapter, rejecting and rewriting it until the Source note rule
    holds. The human is never asked about this — under ADR 0010 nobody is
    required to read the prose, so a validator that only warned would warn to
    nobody."""
    deadline = mimo.Deadline()
    messages = [
        {
            "role": "user",
            "content": CHAPTER_PROMPT.format(
                title=title,
                subject=subject,
                words=config.words_per_chapter(),
                so_far=so_far or "(ยังไม่มี นี่คือบทแรก)",
            ),
        },
    ]

    for _ in range(MAX_ATTEMPTS):
        try:
            raw = await _ask(messages, deadline)
            data = _json(raw)
        except ScriptStalled:
            raise
        except (ScriptError, json.JSONDecodeError):
            continue

        passages = [
            sources.Passage(str(p.get("text", "")), str(p.get("source", "")))
            for p in data.get("passages", [])
        ]
        if not passages:
            continue

        verdict = sources.check(passages, config.max_request_bytes())
        if verdict:
            return Chapter(title, passages)

        messages += [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": sources.rewrite_note(verdict)},
        ]

    raise ScriptError(f"บท {title} ผ่านกติกา Source note ไม่ได้สักรอบ")
