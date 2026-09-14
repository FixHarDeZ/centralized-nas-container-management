"""Turns a Topic into a Script by asking mimo."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time

from openai import AsyncOpenAI

from app import locales, mimo, render

logger = logging.getLogger(__name__)

MIN_CARDS, MAX_CARDS = 5, 7
MAX_LINES_PER_CARD = 4
# What the model is asked to aim for. Not enforced: the renderer measures real
# pixel width and shrinks the font to fit, and character count is a poor proxy
# anyway — Thai glyphs are narrower than Latin ones.
TARGET_CHARS_PER_LINE = locales.get("th")["target_chars"]
# Told to the model, which cannot measure pixels, and used as the fallback rule
# wherever the font is unavailable. The real gate is _too_wide(): a character
# count is a poor proxy for Thai, where vowels and tone marks carry no advance
# width. Measured over every line this bot has written (209 lines, 2026-08-29):
# the widest came to 719px at 33 characters, well inside the 864px available.
HARD_MAX_CHARS_PER_LINE = locales.get("th")["hard_max_chars"]

LATIN = re.compile(r"[A-Za-z]+")
THAI = re.compile(r"[\u0e00-\u0e7f]+")
# What `spoken` may not contain, per Locale. A Thai voice handed a Latin word
# switches accent mid-sentence and rushes it; an English voice handed Thai
# script cannot say it at all.
FORBIDDEN_IN_SPOKEN = {"thai": LATIN, "latin": THAI}

SYSTEM_PROMPT_TH = f"""คุณเป็นคนเขียนสคริปต์ YouTube Shorts ภาษาไทย

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
  ถ้าคำอังกฤษเป็นการเล่นคำที่อ่านเป็นไทยได้ ให้ใช้คำอ่านนั้น ไม่ใช่สะกดทีละตัวอักษร
  เช่น TH-AI Passport → ไทยพาสปอร์ต (ไม่ใช่ ทีเอไอพาสปอร์ต)
  **ห้ามมีขีดกลาง (-) ใน spoken** เครื่องอ่านจะหยุดเงียบตรงขีด ชื่อรุ่นให้เขียนติดกัน
  เช่น F-35 → เอฟสามสิบห้า, GPT-4 → จีพีทีโฟร์
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


TRENDS_PROMPT_TH = """คุณเป็นคนเลือกหัวข้อคลิป YouTube Shorts ภาษาไทย

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


# The English prompt is written in English on purpose: an English Script asked
# for in Thai comes back translated rather than written, and it reads like it.
# `spoken` survives the crossing — an English voice does not need words
# transliterated, but it does need numbers, symbols and initialisms spelled the
# way they are said.
EN = locales.get("en")
SYSTEM_PROMPT_EN = f"""You write YouTube Shorts scripts in English for a US audience.

Any topic goes (tech, money, health, lifestyle, general knowledge). Write like
someone who actually knows the subject telling a friend, not an encyclopedia.

**Never make claims about real people (celebrities, politicians, athletes),
breaking news, court cases or match results.** If the topic points that way,
cover only the checkable general-knowledge angle.

Write a vertical clip 40-50 seconds long, split into cards of 6-9 seconds.

Rules:
- {MIN_CARDS}-{MAX_CARDS} cards
- the first card is the hook: it must stop a thumb within 3 seconds by asking a
  question or naming a pain the viewer really has. Never open with "today we're
  going to talk about"
- the last card is a short takeaway the viewer can use
- each card has lines = 1-{MAX_LINES_PER_CARD} lines of on-screen text, about
  {EN["target_chars"]} characters each (never more than {EN["hard_max_chars"]})
  **Break the lines yourself at word boundaries.** The renderer draws exactly
  what you send; a line over the limit is rejected, and a long line shrinks the
  font until it is unreadable on a phone.
- narration = the sentence for that card, spoken English rather than written
  English, long enough to read aloud in 6-9 seconds. No emoji and no symbols
  that cannot be read out loud.
  **Put a comma wherever a speaker would draw breath**, roughly every 10-15 words.
- spoken = the same sentence, written the way it is said, and it must contain
  **no Thai characters at all**. Spell out anything the voice would stumble on:
  numbers as words (2026 -> twenty twenty six, 1-2 minutes -> one to two
  minutes), symbols as words (%, $, & -> percent, dollars, and), and
  initialisms with spaces so they are read letter by letter (CPU -> C P U).
  **No hyphens in spoken** — the voice pauses on them. GPT-4 -> GPT four.
  If nothing needs respelling, repeat narration verbatim.
- code = a short command or code block, at most 4 lines, only on a card that
  really shows one. Otherwise null.
- query = **2-4 English words** to search stock footage for that card's
  background. It must be something a camera can film: "server room racks",
  "developer typing keyboard", "data center lights". Never abstract phrases
  like "docker configuration" or "log rotation".
- title/description/hashtags = for the YouTube upload; 3-5 hashtags, each
  starting with #
- category = a short English word for what this clip is about (tech, money,
  health, lifestyle, gaming, general) — recorded to see which category holds
  viewers, never shown in the clip

Answer with JSON only, nothing outside the JSON:
{{"title": "...", "description": "...", "hashtags": ["#..."], "category": "...",
  "cards": [{{"lines": ["..."], "code": null, "query": "...",
             "narration": "...", "spoken": "..."}}]}}"""


TRENDS_PROMPT_EN = """You pick topics for English-language YouTube Shorts aimed at a US audience.

You will be given a list of what people in the US are searching for and
watching right now. Turn it into **5 topics that can actually be made**.

Hard rules:
- **Never propose a topic that is breaking news, politics, a court case, a
  match result, or anything about a real person** (celebrity, politician,
  athlete): the clip would end up asserting things about real people with no
  source. If a trend is about a person, **skip it**, or take only the angle
  that can be explained without naming anyone. Trend "M6 chip" -> "how the M6
  differs from the M4" (fine); trend "<politician>" -> skip.
- **Never propose a topic that speculates about a real person** ("is that actor
  coming back", "who did they break up with", "will that CEO resign") — that is
  rumour, the bot cannot know, and it would put words in a real person's mouth.
  If the trend comes from a film, series or game, cover **the work itself**.
- Take topics explainable from settled facts, not ones that need today's news
  to get right.
- One line per topic, written so it can be sent straight to the script writer.
- kind = "evergreen" if it is still worth watching in 6 months, "spike" if it
  dies with the trend.
- category = short English word: tech, money, health, lifestyle, gaming, general
- from = the term or video title that sparked it (copied from the list given)
- why = one short line on why people would watch

Answer with JSON only:
{"topics": [{"topic": "...", "kind": "evergreen", "category": "tech", "from": "...", "why": "..."}]}"""

SYSTEM_PROMPTS = {"th": SYSTEM_PROMPT_TH, "en": SYSTEM_PROMPT_EN}
TRENDS_PROMPTS = {"th": TRENDS_PROMPT_TH, "en": TRENDS_PROMPT_EN}


def system_prompt(locale: str = locales.DEFAULT) -> str:
    return SYSTEM_PROMPTS.get(locale, SYSTEM_PROMPT_TH)


def trends_prompt(locale: str = locales.DEFAULT) -> str:
    return TRENDS_PROMPTS.get(locale, TRENDS_PROMPT_TH)


class ScriptError(ValueError):
    """The model returned something we cannot render."""


class ScriptStalled(ScriptError):
    """Nobody answered inside the budget — a different failure from a bad reply.

    Worth its own type because the answer to it is different: a malformed
    script is the model doing its best on this prompt and will come back
    malformed again, while a stall is the endpoint being sick for a few
    minutes and the same prompt succeeds afterwards.
    """


# Latency here tracks how much the model decides to think, not the network:
# ~30 tokens/s whatever the length (see app/mimo.py). The budget is a wall
# clock shared across every retry of one Script, not granted afresh per call.
BUDGET_SECONDS = mimo.budget()
# Below this there is no point starting another attempt.
MIN_ATTEMPT = 90.0
# Hedging — a twin request fired at 240s, and a third at 360s — was here from
# 2026-08-27 to 2026-09-14 and, across every case in the logs, never once
# rescued a call: the twins hung together (07/09 19:02 the primary answered
# on its own at 268s; 08/09 08:02 primary and hedge were both silent at 600s).
# A stall is a window, not a request. It is now `ScriptStalled` and a cooldown
# in main.make_script(), and the smaller model is used only where it earns
# its place: a retry with just the tail of the budget left.
FALLBACK_MODEL = mimo.fallback_model()
PRIMARY_MODEL = mimo.model()


# The prompt a human pastes into Google Flow is short and is written while
# they wait, so it gets its own, much smaller budget than a Script.
FLOW_BUDGET_SECONDS = float(os.environ.get("FLOW_PROMPT_TIMEOUT_SECONDS", "180"))

FLOW_SYSTEM_PROMPT = """คุณเขียน prompt ภาษาอังกฤษให้คนเอาไปวางใน Google Flow (โมเดล Veo)
เพื่อสร้างวิดีโอพื้นหลังแนวตั้ง 8 วินาที สำหรับการ์ดหนึ่งใบของคลิป YouTube Shorts

ตอบกลับมาเป็น prompt เดียว ภาษาอังกฤษ ย่อหน้าเดียว ไม่เกิน 60 คำ
ห้ามมีหัวข้อ ห้ามมีคำอธิบาย ห้ามมีเครื่องหมายคำพูดครอบ ห้ามใส่หมายเลขข้อ

กติกา:
- 9:16 vertical. บอกช็อต มุมกล้อง แสง และการเคลื่อนกล้องให้ชัด (slow push in, static wide ฯลฯ)
- **ห้ามมีตัวหนังสือใดๆ ในภาพ** (no text, no captions, no UI, no logos, no signage)
  เพราะโปรแกรมจะวาดข้อความไทยทับอีกชั้น ตัวหนังสือซ้อนกันอ่านไม่ออก
- **ห้ามมีใบหน้าที่ระบุตัวตนได้ และห้ามอ้างอิงบุคคลจริง** — ถ่ายมือ ไหล่ เงา ฉากหลัง หรือระยะไกลแทน
- กลางจอต้องโล่ง ให้ subject อยู่ริมเฟรมหรือเป็นฉากกว้าง เพราะข้อความจะทับตรงกลาง
- ห้ามพูดถึงเสียง เพลง หรือคำบรรยาย เสียงทั้งหมดมาจากที่อื่น"""


def _client() -> AsyncOpenAI:
    return mimo.client()


async def _say(client: AsyncOpenAI, messages: list[dict], temperature: float,
               budget: float, model: str | None = None) -> str:
    """One completion inside `budget` seconds, or `asyncio.TimeoutError`.

    The deadline is enforced by `mimo.complete`, not left to httpx, whose
    timeout is per read: a server that trickles bytes resets that clock
    forever and the call never returns.
    """
    try:
        return await mimo.complete(client, messages, within=budget,
                                   model_name=model or PRIMARY_MODEL,
                                   temperature=temperature)
    except mimo.Stalled as stalled:
        raise asyncio.TimeoutError(str(stalled)) from stalled
    except mimo.Truncated as truncated:
        # Junk would otherwise be returned as if it were an answer; the retry
        # loop treats this like any other failed attempt instead of parsing it.
        raise ScriptError(str(truncated)) from truncated


def _too_wide(line: str, locale: str = locales.DEFAULT) -> int:
    """Characters to cut so the renderer can draw the line, 0 if it already can.

    The renderer shrinks the font until the text fits, so the line it cannot
    draw at all is one still too wide at its smallest size. Measured against
    the narrower of the two draw paths: text over footage is laid out at the
    1080px frame, not the oversized 1210px gradient card.

    That pixel floor is the whole test for Thai, whose glyphs fit at full size
    anyway (34 characters came to 719px of 864 at size 92). It is not enough
    for Latin, which runs about 50px a character against Thai's 21: a 38-
    character English line clears the floor at size 40 and is then *drawn* at
    size 40, unreadable on a phone. So a Locale can also hold the model to its
    character count, and the answer is whichever cut is larger.
    """
    spec = locales.get(locale)
    counted = max(0, len(line) - spec["hard_max_chars"]) if spec.get("enforce_char_count") else 0
    try:
        font = render._font(render.THAI_BOLD, render.MIN_TEXT_SIZE)
    except (OSError, RuntimeError):
        # No Waree, or Pillow without Raqm — off the container. The renderer
        # refuses to run at all in that state, so fall back to the count
        # rather than let every line through.
        return max(counted, len(line) - spec["hard_max_chars"], 0)
    usable = render.W - render.MARGIN * 2
    width = font.getlength(line)
    if width <= usable:
        return counted
    return max(counted, 1, round(len(line) * (width - usable) / width))


def _rewrap(lines: list[str], spec: dict) -> list[str]:
    """Break the over-long lines of one card at word boundaries.

    Only the offending line is touched, and only where the Locale has spaces
    to break on. The lines that already fit are left exactly as the model sent
    them: they are usually a deliberate grouping — an enumeration, a
    before/after — and re-flowing the whole card as one paragraph destroys it.

    A word longer than the limit is left on a line of its own; there is nowhere
    to break it, and the pixel check downstream still gets to refuse it.
    """
    limit = spec["hard_max_chars"]
    out: list[str] = []
    for line in lines:
        if len(line) <= limit:
            out.append(line)
            continue
        current = ""
        for word in line.split():
            candidate = f"{current} {word}".strip()
            if current and len(candidate) > limit:
                out.append(current)
                current = word
            else:
                current = candidate
        if current:
            out.append(current)
    return out


def validate(script: dict, locale: str = locales.DEFAULT) -> dict:
    """Reject a Script the renderer would mangle. Raises ScriptError.

    Messages stay in Thai even for an English Script: they are read by the
    human in Telegram, and the model is fed them as a correction, which it
    handles in either language.
    """
    spec = locales.get(locale)
    for key in ("title", "description", "hashtags", "cards", "category"):
        if key not in script:
            raise ScriptError(f"ไม่มีฟิลด์ {key}")

    cards = script["cards"]
    if not isinstance(cards, list) or not MIN_CARDS <= len(cards) <= MAX_CARDS:
        raise ScriptError(f"ต้องมี {MIN_CARDS}-{MAX_CARDS} card แต่ได้ {len(cards) if isinstance(cards, list) else '?'}")

    # Every card is checked before anything is raised. Reporting only the first
    # slip costs a full round trip per line: on 2026-09-09 an English Clip burnt
    # all four attempts that way, each reply fixing the line the message named
    # and overflowing another. The model can only fix what it is shown.
    problems: list[str] = []

    for i, card in enumerate(cards, 1):
        lines = card.get("lines")
        if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES_PER_CARD:
            problems.append(f"card {i}: lines ต้องมี 1-{MAX_LINES_PER_CARD} บรรทัด")
            lines = []
        if lines and spec.get("wrap_lines") and all(isinstance(x, str) for x in lines):
            # Fix the width ourselves where the script has word boundaries to
            # break on, rather than spending an attempt asking. Only if the
            # rewrap needs more lines than a card holds is this the model's
            # problem, and then the total — not any one line — is what has to
            # come down.
            wrapped = _rewrap(lines, spec)
            if len(wrapped) > MAX_LINES_PER_CARD:
                total = sum(len(x) for x in lines)
                budget = MAX_LINES_PER_CARD * spec["hard_max_chars"]
                problems.append(
                    f"card {i}: ข้อความบนจอยาวเกินการ์ด ({total} ตัวอักษร) "
                    f"ต้องเหลือไม่เกิน {budget} ตัวอักษรรวมทุกบรรทัด"
                )
            else:
                lines = wrapped
                card["lines"] = wrapped
        for line in lines:
            if not isinstance(line, str) or not line.strip():
                problems.append(f"card {i}: มีบรรทัดว่าง")
                continue
            over = _too_wide(line, locale)
            if over:
                # Say how much to cut: this message is fed back to the model on
                # the retry, and it cannot measure the line itself. Only offer
                # the extra line where the card has one left to give — and never
                # where we do the wrapping ourselves, since the invitation is
                # what pushed one reply to five lines on 2026-09-09.
                room = (
                    " (ขึ้นบรรทัดใหม่ได้ ไม่ทำให้คลิปยาวขึ้น)"
                    if len(lines) < MAX_LINES_PER_CARD and not spec.get("wrap_lines")
                    else ""
                )
                problems.append(
                    f"card {i}: บรรทัดกว้างเกินการ์ด ต้องตัดออกอีกราว {over} ตัว{room}: {line}"
                )
        if not str(card.get("narration", "")).strip():
            problems.append(f"card {i}: ไม่มี narration")
        spoken = str(card.get("spoken", "")).strip()
        if not spoken:
            problems.append(f"card {i}: ไม่มี spoken (narration ฉบับที่เสียงอ่านได้)")
        # A Latin word makes the Thai voice switch accent mid-sentence: it reads
        # the English at English pace, which lands as a rushed, unclear burst
        # inside Thai speech. The screen keeps the real spelling; only the voice
        # gets the transliteration. Mirrored for English, where Thai script in
        # `spoken` is something the voice simply cannot pronounce.
        forbidden = FORBIDDEN_IN_SPOKEN[spec["spoken_script"]]
        found = forbidden.findall(spoken)
        if found:
            wrong = "ละติน" if spec["spoken_script"] == "thai" else "ไทย"
            problems.append(
                f"card {i}: spoken มีตัวอักษร{wrong} ({found[:3]}) ต้องเขียนเป็น"
                f"{'ไทย' if spec['spoken_script'] == 'thai' else 'อังกฤษ'}ทั้งหมด"
            )
        if not str(card.get("query", "")).strip():
            problems.append(f"card {i}: ไม่มี query สำหรับหา footage")

    if problems:
        raise ScriptError(" | ".join(problems))
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


NOTES = {
    "th": (
        "เคยทำคลิปเรื่องพวกนี้ไปแล้ว ห้ามเขียนซ้ำมุมเดิม ถ้าหัวข้อใกล้เคียงให้หามุมใหม่:\n",
        "คลิปที่คนดูจนจบมากที่สุดคือเรื่องพวกนี้ เขียนให้ใกล้เคียงแนวนี้:\n",
    ),
    "en": (
        "These clips have already been made. Do not repeat the same angle; find "
        "a new one if the topic is close:\n",
        "These are the clips people watched furthest through. Write in that "
        "direction:\n",
    ),
}


SIBLING_NOTES = {
    "th": (
        "คลิปเรื่องเดียวกันนี้เขียนไว้แล้วอีกภาษาหนึ่ง (ข้างล่าง) "
        "ให้เล่ามุมเดียวกันและใช้ข้อเท็จจริงชุดเดียวกัน "
        "แต่**เขียนใหม่เป็นภาษาไทยให้เป็นธรรมชาติ ห้ามแปลตรงตัว** "
        "ความยาวบรรทัดและจังหวะให้เป็นไปตามกฎของภาษานี้:\n"
    ),
    "en": (
        "The same clip has already been written in another language (below). "
        "Cover the same angle and the same facts, but **write it natively in "
        "English — do not translate**. Line lengths, the hook and the rhythm "
        "follow this language's own rules:\n"
    ),
}


def _sibling_note(sibling: dict, locale: str) -> str:
    """The already-approved half of a pair, as context for the other half."""
    head = SIBLING_NOTES.get(locale, SIBLING_NOTES["en"])
    lines = [f"title: {sibling.get('title', '')}"]
    for i, card in enumerate(sibling.get("cards") or [], 1):
        lines.append(f"card {i}: {card.get('narration', '')}")
    return head + "\n".join(lines)


def _context_note(avoid: list[str], winners: list[str],
                  locale: str = locales.DEFAULT) -> str:
    """Tell the model what has been made already and what worked."""
    avoid_note, winners_note = NOTES.get(locale, NOTES["th"])
    parts = []
    if avoid:
        parts.append(avoid_note + "\n".join(f"- {title}" for title in avoid))
    if winners:
        parts.append(winners_note + "\n".join(f"- {title}" for title in winners))
    return "\n\n".join(parts)


async def suggest_topics(rows: list[dict], locale: str = locales.DEFAULT) -> list[dict]:
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
    messages = [{"role": "system", "content": trends_prompt(locale)},
                {"role": "user", "content": listing}]
    client = _client()
    # A reply in prose instead of JSON is a coin flip this model loses now and
    # then, and the whole round is thrown away over it — the automatic /trends
    # rounds have nobody watching to ask again. Saying what came back wrong is
    # what fixes it; the same listing asked twice usually parses the second
    # time (seen 2026-09-13, an 08:36 automatic round).
    for attempt in (1, 2):
        raw = await _say(client, messages, temperature=0.7, budget=BUDGET_SECONDS)
        try:
            parsed = _parse(raw)
            topics = parsed.get("topics")
            if not isinstance(topics, list) or not topics:
                raise ScriptError("โมเดลไม่ได้เสนอหัวข้อมาเลย")
            return [t for t in topics if str(t.get("topic", "")).strip()][:5]
        except ScriptError as exc:
            if attempt == 2:
                raise
            logger.warning("trends: %s — ขอใหม่อีกครั้ง", exc)
            messages = messages + [
                {"role": "assistant", "content": raw[:2000]},
                {"role": "user", "content":
                 f"คำตอบก่อนหน้าใช้ไม่ได้ ({exc}) ตอบใหม่เป็น JSON object ล้วนๆ "
                 'ขึ้นต้นด้วย { และมีคีย์ "topics" เท่านั้น ห้ามมีข้อความอื่นนอก JSON'},
            ]
    raise AssertionError("unreachable")


async def generate(
    topic: str,
    previous: dict | None = None,
    feedback: str = "",
    avoid: list[str] | None = None,
    winners: list[str] | None = None,
    style: str = "",
    locale: str = locales.DEFAULT,
    sibling: dict | None = None,
) -> dict:
    """Write a Script for `topic`, optionally revising `previous` per `feedback`.

    `style` is the clause the running Experiment assigned to this Clip. It is
    appended rather than folded into SYSTEM_PROMPT so the Manifest can record
    the exact words that produced this Script — the base prompt will drift, and
    a Variant name alone would not say what it meant at the time.
    """
    messages = [{"role": "system", "content": system_prompt(locale)}]
    note = _context_note(avoid or [], winners or [], locale)
    if note:
        messages.append({"role": "system", "content": note})
    if sibling:
        # The other half of a Locale pair, already approved. Handed over as
        # context rather than as text to translate: the line width, the hook
        # rules and what lands with the audience all differ, so a translation
        # comes back overflowing and flat. What must carry across is the
        # angle — the same Topic told the same way, written natively.
        messages.append({"role": "system", "content": _sibling_note(sibling, locale)})
    if style:
        messages.append({"role": "system", "content": style})
    label = "หัวข้อ" if locale == "th" else "Topic"
    messages.append({"role": "user", "content": f"{label}: {topic}"})
    if previous is not None:
        messages.append({"role": "assistant", "content": json.dumps(previous, ensure_ascii=False)})
        messages.append({"role": "user", "content": f"แก้ตามนี้: {feedback}"})

    client = _client()
    last_error: Exception | None = None
    # The budget is shared across attempts, not granted afresh to each one:
    # two full-length attempts is twenty minutes of a human staring at
    # "กำลังเขียนสคริปต์...".
    deadline = time.monotonic() + BUDGET_SECONDS
    # Deadline-driven, not a fixed attempt count: a garbage 60-char reply can
    # come back in seconds, and stopping at two tries then leaves most of a
    # 600s budget unspent while a plain retry would have succeeded (observed
    # 2026-09-04). Capped at 4 so a client that always fails fast cannot spin
    # forever inside one budget.
    attempt = 0
    while attempt < 4:
        left = deadline - time.monotonic()
        if left < MIN_ATTEMPT:
            break
        # The retry only ever gets the remainder of the shared budget, and the
        # first attempt can eat almost all of it: measured 2026-08-29, a Script
        # came back after 343s and failed validate(), leaving 257s against a
        # worst case think of 347s — a retry that could not finish. So every
        # attempt after the first leads with the smaller model (149s measured
        # on the same prompt) and hedges back to the pro. Fixing JSON to match
        # a schema it has already been shown is not work that needs the pro
        # model; finishing inside the leftovers is.
        model = PRIMARY_MODEL if attempt == 0 else FALLBACK_MODEL
        attempt += 1
        try:
            raw = await _say(client, messages, temperature=0.8, budget=left,
                             model=model)
        except asyncio.TimeoutError:
            # Say what went wrong the *first* time too. A retry inherits
            # whatever is left of the shared budget, so a first attempt that
            # answered slowly and then failed validation leaves too little
            # time for the second — and reporting only the timeout hides the
            # schema slip that actually started it.
            timed_out = (
                f"mimo ไม่ตอบภายใน {BUDGET_SECONDS:.0f} วินาที "
                "(ปกติใช้ 90-350 วินาทีตามความยาวที่โมเดลคิด)"
            )
            if last_error is not None:
                timed_out += f" — รอบก่อนหน้า: {last_error}"
            last_error = ScriptStalled(timed_out)
            continue
        except ScriptError as exc:
            # _say itself rejected the reply (truncated by finish_reason or
            # empty) before it ever became text to parse. Same shape as an
            # unparseable reply below: retry with messages untouched, there is
            # nothing sane to feed back for a reply that was not really an
            # answer.
            last_error = ScriptError(
                f"{exc} — รอบก่อนหน้า: {last_error}" if last_error is not None else str(exc)
            )
            continue
        try:
            parsed = _parse(raw)
        except ScriptError as exc:
            # Parsing failed outright: raw is not JSON at all (the 60-char
            # garbage reply that started this). Feeding it back as an
            # "assistant" turn only pollutes the conversation the *next*
            # model reads, and it is not JSON the model itself agreed to, so
            # retry with messages unchanged instead of the append-and-correct
            # below.
            excerpt = raw[:300]
            logger.warning(
                "โมเดลไม่ตอบเป็น JSON: %s (raw %d ตัวอักษร): %r",
                exc, len(raw), excerpt,
            )
            msg = f"{exc} (raw {len(raw)} ตัวอักษร): {excerpt}"
            last_error = ScriptError(
                f"{msg} — รอบก่อนหน้า: {last_error}" if last_error is not None else msg
            )
            continue
        try:
            return validate(parsed, locale)
        except ScriptError as exc:
            excerpt = raw[:300]
            logger.warning(
                "สคริปต์ผิดกติกา: %s (raw %d ตัวอักษร): %r", exc, len(raw), excerpt,
            )
            # Chained the same as the other two failure shapes above: without
            # this, a fallback model's schema slip overwrites the pro model's
            # earlier failure and the final message shows only the symptom,
            # not the cause (observed 2026-09-04).
            msg = f"{exc} (raw {len(raw)} ตัวอักษร): {excerpt}"
            last_error = ScriptError(
                f"{msg} — รอบก่อนหน้า: {last_error}" if last_error is not None else msg
            )
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"สคริปต์ผิดกติกา: {exc} — ส่ง JSON ใหม่ให้ถูกกติกา"},
            ]
    # The shape of the *last* failure decides, so a stall that was retried into
    # a schema slip is reported as the schema slip and not retried again later.
    raise type(last_error or ScriptError("ไม่มีคำตอบ"))(str(last_error))


async def flow_prompt(topic: str, card: dict) -> str:
    """The English Veo prompt a human pastes into Google Flow for one Card.

    Asked for on demand rather than folded into the Script: a Script already
    takes 90-350s to think, most Clips never go the Flow route, and every extra
    field on the schema is latency every Clip pays.
    """
    user = "\n".join([
        f"หัวข้อคลิป: {topic}",
        f"ข้อความบนจอของการ์ดนี้: {' / '.join(card.get('lines') or [])}",
        f"คำที่จะพูดทับ: {card.get('narration', '')}",
        f"คำค้น footage ที่เคยคิดไว้: {card.get('query', '')}",
    ])
    raw = await _say(
        _client(),
        [{"role": "system", "content": FLOW_SYSTEM_PROMPT},
         {"role": "user", "content": user}],
        temperature=0.8,
        budget=FLOW_BUDGET_SECONDS,
    )
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        text = text[4:] if text.startswith("json") else text
    text = text.strip().strip('"').strip()
    if not text:
        raise ScriptError("โมเดลไม่ได้ตอบ prompt กลับมา")
    return text[:1200]
