"""Turns a Topic into a Script by asking mimo."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time

from openai import AsyncOpenAI

MIN_CARDS, MAX_CARDS = 5, 7
MAX_LINES_PER_CARD = 4
# What the model is asked to aim for. Not enforced: the renderer measures real
# pixel width and shrinks the font to fit, and character count is a poor proxy
# anyway — Thai glyphs are narrower than Latin ones.
TARGET_CHARS_PER_LINE = 22
# Enforced, and measured rather than guessed: at the renderer's smallest font
# (40px Waree) 34 full-width Thai consonants come to 976px against 994px of
# usable card width, and 36 overflow. Real Thai runs far narrower because vowels
# and tone marks carry no advance. 34 is the worst case that still fits — raised
# from 30 after the model kept producing 31-33 character lines and losing whole
# scripts to the retry.
HARD_MAX_CHARS_PER_LINE = 34

LATIN = re.compile(r"[A-Za-z]+")

SYSTEM_PROMPT = f"""คุณเป็นคนเขียนสคริปต์ YouTube Shorts ภาษาไทย

หัวข้ออะไรก็ได้ตามที่สั่ง (เทค การเงิน สุขภาพ ไลฟ์สไตล์ ความรู้รอบตัว ฯลฯ)
เขียนแบบคนที่รู้เรื่องนั้นจริงและเล่าให้เพื่อนฟัง ไม่ใช่ท่องสารานุกรม

**ห้ามกล่าวอ้างเรื่องบุคคลจริง (ดารา นักการเมือง นักกีฬา) ข่าวสด คดีความ หรือผลการแข่งขัน**
ถ้าหัวข้อพาไปทางนั้น ให้เล่าเฉพาะแง่มุมที่เป็นความรู้ทั่วไปซึ่งตรวจสอบได้

เขียนสคริปต์คลิปแนวตั้ง ยาว 40-50 วินาที แบ่งเป็น card ละ 6-9 วินาที

กฎ:
- มี {MIN_CARDS}-{MAX_CARDS} card
- card แรกคือ hook ต้องหยุดนิ้วคนดูใน 3 วินาที ตั้งคำถามหรือชี้ความเจ็บปวดที่คนดูเจอจริง ห้ามเกริ่นแบบ "วันนี้เราจะมาพูดถึง"
- card สุดท้ายสรุปสั้นๆ ให้คนดูเอาไปใช้ต่อได้
- แต่ละ card มี lines = ข้อความบนจอ 1-{MAX_LINES_PER_CARD} บรรทัด บรรทัดละราวๆ {TARGET_CHARS_PER_LINE} ตัวอักษร (ห้ามเกิน {HARD_MAX_CHARS_PER_LINE})
  **สำคัญ: ต้องตัดบรรทัดตรงรอยต่อคำภาษาไทยเอง** เพราะโปรแกรมวาดตัวอักษรตามที่ให้มาเป๊ะๆ ตัดผิดที่แล้วคำจะขาดกลางคำ
- narration = ประโยคของ card นั้น เขียนแบบพูด ไม่ใช่แบบเขียน ยาวพอให้อ่าน 6-9 วินาที
  คำอังกฤษเขียนเป็นอังกฤษตามปกติ (ใช้ขึ้นซับบนจอ) ห้ามใส่ emoji หรือสัญลักษณ์ที่อ่านออกเสียงไม่ได้
  **ใส่จุลภาคคั่นตรงจุดที่คนพูดจะหยุดหายใจ** ประมาณทุก 10-15 คำ
- spoken = narration ประโยคเดียวกันเป๊ะ แต่**เขียนด้วยอักษรไทยล้วน ห้ามมีตัวอักษรละติน (a-z, A-Z) แม้แต่ตัวเดียว**
  ทับศัพท์คำอังกฤษทุกคำ เช่น Docker → ด็อกเกอร์, log → ล็อก, container → คอนเทนเนอร์,
  AI → เอไอ, CPU → ซีพียู, Netflix → เน็ตฟลิกซ์, cliffhanger → คลิฟแฮงเกอร์
  เพราะเครื่องอ่านจะสลับไปสำเนียงอังกฤษกลางประโยค พูดรัวจนฟังไม่ทันและไม่ชัด
  ตัวเลขให้เขียนเป็นคำอ่านไทย เช่น 2024 → สองพันยี่สิบสี่, 1-2 นาที → หนึ่งถึงสองนาที
  คำสั่ง/แฟลกที่ทับศัพท์แล้วงง (เช่น --log-opt) ให้เลี่ยงไปพูดเป็นคำอธิบายแทน
- code = บล็อกโค้ด/คำสั่งสั้นๆ ไม่เกิน 4 บรรทัด ใส่เฉพาะ card ที่มีคำสั่งจริงให้ดู ถ้าไม่มีให้เป็น null
- query = **คำค้นภาษาอังกฤษ 2-4 คำ** สำหรับหาคลิป stock footage มาเป็นพื้นหลังของ card นั้น
  ต้องเป็นสิ่งที่**ถ่ายเป็นวิดีโอได้จริง** เช่น "server room racks", "developer typing keyboard",
  "data center lights" ห้ามใช้คำนามธรรมที่ถ่ายไม่ได้ เช่น "docker configuration", "log rotation"
- title/description/hashtags = สำหรับอัปขึ้น YouTube, hashtags 3-5 ตัว ขึ้นต้นด้วย #
- category = หมวดของคลิปนี้ คำสั้นๆ ภาษาไทย เช่น เทค, การเงิน, สุขภาพ, ไลฟ์สไตล์, เกม,
  ความรู้รอบตัว — ใช้บันทึกว่าหมวดไหนคนดูเยอะ ไม่ได้โชว์ในคลิป

ตอบเป็น JSON อย่างเดียว ห้ามมีข้อความอื่นนอก JSON:
{{"title": "...", "description": "...", "hashtags": ["#..."], "category": "...",
  "cards": [{{"lines": ["..."], "code": null, "query": "...",
             "narration": "...", "spoken": "..."}}]}}"""


TRENDS_PROMPT = """คุณเป็นคนเลือกหัวข้อคลิป YouTube Shorts ภาษาไทย

จะได้รับรายการ "สิ่งที่คนไทยกำลังค้นหา/กำลังดู" ตอนนี้ หน้าที่คุณคือแปลงเป็น
**หัวข้อคลิปที่ทำได้จริง 5 หัวข้อ**

กฎเหล็ก:
- **ห้ามเสนอหัวข้อที่เป็นข่าวสด การเมือง คดีความ ผลการแข่งขัน หรือเรื่องของบุคคลจริง**
  (ดารา นักการเมือง นักกีฬา) เพราะคลิปจะกลายเป็นการกล่าวอ้างเรื่องคนจริงโดยไม่มีหลักฐาน
  ถ้ากระแสนั้นเป็นข่าวคน ให้**ข้ามไปเลย** หรือดึงเฉพาะแง่มุมที่อธิบายได้แบบไม่พาดพิงใคร
  เช่น กระแส "ชิป M6" → "ชิป M6 ต่างจาก M4 ยังไง" (โอเค),
  กระแส "นายก..." → ข้าม
- **ห้ามตั้งหัวข้อที่เป็นการคาดเดา/ยืนยันเรื่องของคนจริงเด็ดขาด** เช่น
  "ดาราคนนั้นจะกลับมาเล่นจริงไหม", "นักร้องคนนี้เลิกกับใคร", "ผู้บริหารคนนั้นจะลาออกไหม"
  — พวกนี้คือข่าวลือ บอทไม่มีทางรู้ แล้วจะเดาใส่ปากคนจริง
  ถ้ากระแสมาจากหนัง/ซีรีส์/เกม ให้เล่า**ตัวงาน**แทน เช่น "จักรวาลนี้เล่าเรื่องอะไรมาบ้าง"
  ไม่ใช่ "ใครจะกลับมาแสดง"
- เอาหัวข้อที่**อธิบายได้ด้วยข้อเท็จจริงที่อยู่ตัวแล้ว** ไม่ใช่เรื่องที่ต้องรู้ข่าวล่าสุดถึงจะพูดถูก
- หัวข้อละ 1 บรรทัด เขียนแบบที่พิมพ์ส่งให้บอทเขียนสคริปต์ได้ทันที
- kind = "evergreen" ถ้าเรื่องนี้ยังน่าดูอีก 6 เดือน, "spike" ถ้าตายพร้อมกระแส
- category = หมวดสั้นๆ ภาษาไทย เช่น เทค, การเงิน, สุขภาพ, ไลฟ์สไตล์, เกม, ความรู้รอบตัว
- from = คำ/ชื่อคลิปต้นทางที่จุดประกายหัวข้อนี้ (ก๊อปมาจากรายการที่ให้)
- why = เหตุผลสั้นๆ ว่าทำไมคนน่าจะดู

ตอบเป็น JSON อย่างเดียว:
{"topics": [{"topic": "...", "kind": "evergreen", "category": "...", "from": "...", "why": "..."}]}"""


class ScriptError(ValueError):
    """The model returned something we cannot render."""


# Latency here tracks how much the model decides to think, not the network.
# Measured on the NAS, same prompt: 93s/3,092 completion tokens, 112s/4,016,
# 197s/7,010, 207s/5,415, 347s/10,585 — about 30 tokens a second, every time.
# It does not stall at random; it thinks for longer. So a wall-clock cap is the
# right shape after all, it was simply set at 240s where a long think needs
# ~350s, and the retry doubled the wait on top.
#
# Streaming was tried and abandoned: reading the same answer as a stream took
# 400s against 137s unstreamed, so the idle-detection it buys costs three times
# the wall clock it was meant to save.
BUDGET_SECONDS = float(os.environ.get("MIMO_TIMEOUT_SECONDS", "600"))
# Below this there is no point starting another attempt.
MIN_ATTEMPT = 90.0


def _client() -> AsyncOpenAI:
    # httpx logs "200 OK" when the headers arrive, so a response that stalls
    # mid-body reads as a success in the log while the call hangs.
    return AsyncOpenAI(
        api_key=os.environ["MIMO_API_KEY"],
        base_url=os.environ["MIMO_BASE_URL"],
        timeout=float(os.environ.get("MIMO_TIMEOUT_SECONDS", "180")),
        max_retries=1,
    )


async def _say(client: AsyncOpenAI, messages: list[dict], temperature: float,
               budget: float) -> str:
    """One completion, under a wall-clock deadline.

    The deadline is enforced here rather than left to httpx, whose timeout is
    per read: a server that trickles bytes resets that clock forever and the
    call never returns.
    """
    reply = await asyncio.wait_for(
        client.chat.completions.create(
            model=os.environ.get("MIMO_MODEL", "mimo-v2.5-pro"),
            messages=messages,
            temperature=temperature,
            # This is a reasoning model and its thinking budget drives the
            # latency: measured 161s / 10457 tokens at the default against
            # 79s / 3796 at "low", for a better script. "minimal" is rejected
            # with a 400.
            reasoning_effort=os.environ.get("MIMO_REASONING_EFFORT", "low"),
        ),
        timeout=budget,
    )
    return reply.choices[0].message.content or ""


def validate(script: dict) -> dict:
    """Reject a Script the renderer would mangle. Raises ScriptError."""
    for key in ("title", "description", "hashtags", "cards", "category"):
        if key not in script:
            raise ScriptError(f"ไม่มีฟิลด์ {key}")

    cards = script["cards"]
    if not isinstance(cards, list) or not MIN_CARDS <= len(cards) <= MAX_CARDS:
        raise ScriptError(f"ต้องมี {MIN_CARDS}-{MAX_CARDS} card แต่ได้ {len(cards) if isinstance(cards, list) else '?'}")

    for i, card in enumerate(cards, 1):
        lines = card.get("lines")
        if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES_PER_CARD:
            raise ScriptError(f"card {i}: lines ต้องมี 1-{MAX_LINES_PER_CARD} บรรทัด")
        for line in lines:
            if not isinstance(line, str) or not line.strip():
                raise ScriptError(f"card {i}: มีบรรทัดว่าง")
            if len(line) > HARD_MAX_CHARS_PER_LINE:
                raise ScriptError(
                    f"card {i}: บรรทัดยาว {len(line)} ตัว เกิน {HARD_MAX_CHARS_PER_LINE}"
                )
        if not str(card.get("narration", "")).strip():
            raise ScriptError(f"card {i}: ไม่มี narration")
        spoken = str(card.get("spoken", "")).strip()
        if not spoken:
            raise ScriptError(f"card {i}: ไม่มี spoken (narration ฉบับทับศัพท์ไทยล้วน)")
        # A Latin word makes the voice switch accent mid-sentence: it reads the
        # English at English pace, which lands as a rushed, unclear burst inside
        # Thai speech. The screen keeps the real spelling; only the voice gets
        # the transliteration.
        if LATIN.search(spoken):
            raise ScriptError(
                f"card {i}: spoken มีตัวอักษรละติน ({LATIN.findall(spoken)[:3]}) ต้องทับศัพท์เป็นไทยทั้งหมด"
            )
        if not str(card.get("query", "")).strip():
            raise ScriptError(f"card {i}: ไม่มี query สำหรับหา footage")
    return script


def _parse(raw: str) -> dict:
    """Pull the JSON object out of a model reply that may be fenced."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        text = text[4:] if text.startswith("json") else text
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ScriptError("โมเดลไม่ได้ตอบเป็น JSON")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ScriptError(f"JSON พัง: {exc}") from exc


def _context_note(avoid: list[str], winners: list[str]) -> str:
    """Tell the model what has been made already and what worked."""
    parts = []
    if avoid:
        parts.append(
            "เคยทำคลิปเรื่องพวกนี้ไปแล้ว ห้ามเขียนซ้ำมุมเดิม ถ้าหัวข้อใกล้เคียงให้หามุมใหม่:\n"
            + "\n".join(f"- {title}" for title in avoid)
        )
    if winners:
        parts.append(
            "คลิปที่คนดูจนจบมากที่สุดคือเรื่องพวกนี้ เขียนให้ใกล้เคียงแนวนี้:\n"
            + "\n".join(f"- {title}" for title in winners)
        )
    return "\n\n".join(parts)


async def suggest_topics(rows: list[dict]) -> list[dict]:
    """Turn raw trend rows into Topics the bot could actually be given.

    Kept separate from `generate()`: this decides *what* to make, which is the
    human's call, so its output is a list to choose from and never an input to
    a Script (docs/adr/0004).
    """
    listing = "\n".join(
        f"- [{row['source']}] {row['term']} ({row['traffic']:,})"
        + (f" — ข่าว: {row['headline']}" if row.get("headline") else "")
        for row in rows
    )
    raw = await _say(
        _client(),
        [{"role": "system", "content": TRENDS_PROMPT},
         {"role": "user", "content": listing}],
        temperature=0.7,
        budget=BUDGET_SECONDS,
    )
    parsed = _parse(raw)
    topics = parsed.get("topics")
    if not isinstance(topics, list) or not topics:
        raise ScriptError("โมเดลไม่ได้เสนอหัวข้อมาเลย")
    return [t for t in topics if str(t.get("topic", "")).strip()][:5]


async def generate(
    topic: str,
    previous: dict | None = None,
    feedback: str = "",
    avoid: list[str] | None = None,
    winners: list[str] | None = None,
    style: str = "",
) -> dict:
    """Write a Script for `topic`, optionally revising `previous` per `feedback`.

    `style` is the clause the running Experiment assigned to this Clip. It is
    appended rather than folded into SYSTEM_PROMPT so the Manifest can record
    the exact words that produced this Script — the base prompt will drift, and
    a Variant name alone would not say what it meant at the time.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    note = _context_note(avoid or [], winners or [])
    if note:
        messages.append({"role": "system", "content": note})
    if style:
        messages.append({"role": "system", "content": style})
    messages.append({"role": "user", "content": f"หัวข้อ: {topic}"})
    if previous is not None:
        messages.append({"role": "assistant", "content": json.dumps(previous, ensure_ascii=False)})
        messages.append({"role": "user", "content": f"แก้ตามนี้: {feedback}"})

    client = _client()
    last_error: Exception | None = None
    # The budget is shared across attempts, not granted afresh to each one:
    # two full-length attempts is twenty minutes of a human staring at
    # "กำลังเขียนสคริปต์...".
    deadline = time.monotonic() + BUDGET_SECONDS
    # One retry: a schema slip is usually fixed by telling the model what broke.
    for _ in range(2):
        left = deadline - time.monotonic()
        if left < MIN_ATTEMPT:
            break
        try:
            raw = await _say(client, messages, temperature=0.8, budget=left)
        except asyncio.TimeoutError:
            last_error = ScriptError(
                f"mimo ไม่ตอบภายใน {BUDGET_SECONDS:.0f} วินาที "
                "(ปกติใช้ 90-350 วินาทีตามความยาวที่โมเดลคิด)"
            )
            continue
        try:
            return validate(_parse(raw))
        except ScriptError as exc:
            last_error = exc
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"สคริปต์ผิดกติกา: {exc} — ส่ง JSON ใหม่ให้ถูกกติกา"},
            ]
    raise ScriptError(str(last_error))
