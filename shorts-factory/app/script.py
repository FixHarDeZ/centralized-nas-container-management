"""Turns a Topic into a Script by asking mimo."""
from __future__ import annotations

import json
import os

from openai import AsyncOpenAI

MIN_CARDS, MAX_CARDS = 5, 7
MAX_LINES_PER_CARD = 4
# What the model is asked to aim for. Not enforced: the renderer measures real
# pixel width and shrinks the font to fit, and character count is a poor proxy
# anyway — Thai glyphs are narrower than Latin ones.
TARGET_CHARS_PER_LINE = 22
# Enforced, and measured rather than guessed: at the renderer's smallest font
# (44px Waree) 30 full-width Thai consonants come to 947px against 994px of
# usable card width, and 32 overflow. Real Thai runs far narrower — a natural
# 34-character line measures ~788px — because vowels and tone marks carry no
# advance. So 30 is the worst case that is still guaranteed to fit.
HARD_MAX_CHARS_PER_LINE = 30

SYSTEM_PROMPT = f"""คุณเป็นคนเขียนสคริปต์ YouTube Shorts ภาษาไทย สายเทค (DevOps / AI / โครงสร้างพื้นฐาน)

เขียนสคริปต์คลิปแนวตั้ง ยาว 40-50 วินาที แบ่งเป็น card ละ 6-9 วินาที

กฎ:
- มี {MIN_CARDS}-{MAX_CARDS} card
- card แรกคือ hook ต้องหยุดนิ้วคนดูใน 3 วินาที ตั้งคำถามหรือชี้ความเจ็บปวดที่คนทำงานสายนี้เจอจริง ห้ามเกริ่นแบบ "วันนี้เราจะมาพูดถึง"
- card สุดท้ายสรุปสั้นๆ ให้คนดูเอาไปใช้ต่อได้
- แต่ละ card มี lines = ข้อความบนจอ 1-{MAX_LINES_PER_CARD} บรรทัด บรรทัดละราวๆ {TARGET_CHARS_PER_LINE} ตัวอักษร (ห้ามเกิน {HARD_MAX_CHARS_PER_LINE})
  **สำคัญ: ต้องตัดบรรทัดตรงรอยต่อคำภาษาไทยเอง** เพราะโปรแกรมวาดตัวอักษรตามที่ให้มาเป๊ะๆ ตัดผิดที่แล้วคำจะขาดกลางคำ
- narration = ประโยคที่จะอ่านออกเสียงของ card นั้น เขียนแบบพูด ไม่ใช่แบบเขียน ยาวพอให้อ่าน 6-9 วินาที
  ห้ามใส่ emoji หรือสัญลักษณ์ที่อ่านออกเสียงไม่ได้ลงใน narration
  **narration ต้องเขียนให้เครื่องอ่านออกเสียงเพราะๆ ตามกฎ 2 ข้อนี้:**
  1. **ทับศัพท์คำอังกฤษเป็นอักษรไทยทั้งหมด** เช่น Docker → ด็อกเกอร์, log → ล็อก,
     container → คอนเทนเนอร์, AI → เอไอ, CPU → ซีพียู
     เพราะเครื่องอ่านจะสลับสำเนียงไทย-อังกฤษกลางประโยคแล้วฟังสะดุด
     (**เฉพาะใน narration เท่านั้น — ใน lines ให้คงคำอังกฤษไว้ตามเดิม** เพราะบนจอต้องอ่านง่าย)
  2. **ใส่จุลภาคคั่นตรงจุดที่คนพูดจะหยุดหายใจ** ประมาณทุก 10-15 คำ
     เช่น "ปัญหาคือ ด็อกเกอร์ ไม่ได้จำกัดขนาด ล็อก ให้เราตั้งแต่แรก, มันจะเขียนไปเรื่อยๆ, จนกว่าดิสก์จะเต็ม"
  คำสั่ง/แฟลกที่ทับศัพท์แล้วงง (เช่น --log-opt) ให้เลี่ยงไปพูดเป็นคำอธิบายแทน
- code = บล็อกโค้ด/คำสั่งสั้นๆ ไม่เกิน 4 บรรทัด ใส่เฉพาะ card ที่มีคำสั่งจริงให้ดู ถ้าไม่มีให้เป็น null
- query = **คำค้นภาษาอังกฤษ 2-4 คำ** สำหรับหาคลิป stock footage มาเป็นพื้นหลังของ card นั้น
  ต้องเป็นสิ่งที่**ถ่ายเป็นวิดีโอได้จริง** เช่น "server room racks", "developer typing keyboard",
  "data center lights" ห้ามใช้คำนามธรรมที่ถ่ายไม่ได้ เช่น "docker configuration", "log rotation"
- title/description/hashtags = สำหรับอัปขึ้น YouTube, hashtags 3-5 ตัว ขึ้นต้นด้วย #

ตอบเป็น JSON อย่างเดียว ห้ามมีข้อความอื่นนอก JSON:
{{"title": "...", "description": "...", "hashtags": ["#..."],
  "cards": [{{"lines": ["..."], "code": null, "query": "...", "narration": "..."}}]}}"""


class ScriptError(ValueError):
    """The model returned something we cannot render."""


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=os.environ["MIMO_API_KEY"],
        base_url=os.environ["MIMO_BASE_URL"],
    )


def validate(script: dict) -> dict:
    """Reject a Script the renderer would mangle. Raises ScriptError."""
    for key in ("title", "description", "hashtags", "cards"):
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


async def generate(topic: str, previous: dict | None = None, feedback: str = "") -> dict:
    """Write a Script for `topic`, optionally revising `previous` per `feedback`."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"หัวข้อ: {topic}"},
    ]
    if previous is not None:
        messages.append({"role": "assistant", "content": json.dumps(previous, ensure_ascii=False)})
        messages.append({"role": "user", "content": f"แก้ตามนี้: {feedback}"})

    client = _client()
    last_error: Exception | None = None
    # One retry: a schema slip is usually fixed by telling the model what broke.
    for _ in range(2):
        reply = await client.chat.completions.create(
            model=os.environ.get("MIMO_MODEL", "mimo-v2.5-pro"),
            messages=messages,
            temperature=0.8,
        )
        raw = reply.choices[0].message.content or ""
        try:
            return validate(_parse(raw))
        except ScriptError as exc:
            last_error = exc
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"สคริปต์ผิดกติกา: {exc} — ส่ง JSON ใหม่ให้ถูกกติกา"},
            ]
    raise ScriptError(str(last_error))
