"""Product Clips (docs/adr/0015): a Brief in, a Pitch out, a caption to paste.

A Brief is what the human sends after /shop — photos from the Shopee app and
the listing text they copied. A Pitch is what mimo writes from it: Beats (a
badge, the narration split into on-screen lines, which photo to show) and an
end card. Nothing here touches the Topic pipeline's Manifest, history or
Experiment; the record of a Product Clip is `shop.json` beside its files.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

from app import mimo, model_choice, render
from app import script as script_gen

logger = logging.getLogger(__name__)

# Not the explainer channel's voice, so the two do not sound like one account.
VOICE = os.environ.get("SHOP_TTS_VOICE", "th-TH-PremwadeeNeural")
MAX_PHOTOS = 6
MIN_BEATS, MAX_BEATS = 3, 6
# A subtitle line must fit the frame at this size or larger. Measured in
# pixels, not characters: Thai vowels and tone marks take no width, so a count
# rejected lines that fit with room to spare (2026-10-13, two in a row).
SUBTITLE_MIN_SIZE = 54
SUBTITLE_WIDTH = render.W - 2 * 60
# Off the container (no Waree/Raqm) the count is all there is.
FALLBACK_LINE_CHARS = 32
TARGET_LINE_CHARS = "15-25"
MAX_BADGE_CHARS = 20
MAX_TITLE_CHARS = 80
CTA = "กดลิงก์ในคอมเมนต์ / ตะกร้า"
DISCLOSURE = "#ad มีลิงก์ affiliate — ซื้อผ่านลิงก์นี้ คนทำคลิปได้ค่าคอมเล็กน้อย ราคาเท่าเดิม"

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
LATIN = re.compile(r"[A-Za-z]")
# A price read out in Thai words is a number the digit gate cannot see.
NUMBER_WORDS = re.compile(r"ร้อย|พัน|หมื่น|แสน")
LINK = re.compile(r"https?://\S+", re.IGNORECASE)
SHOPEE_LINK = re.compile(r"https?://(?:[\w-]+\.)*(?:shopee\.co\.th|shp\.ee)\S*", re.IGNORECASE)
BUDGET_SECONDS = float(os.environ.get("SHOP_PITCH_TIMEOUT_SECONDS", str(mimo.budget())))
MIN_ATTEMPT = 60.0


class PitchError(script_gen.ScriptError):
    """A Pitch that breaks the rules; the message goes back to the model."""


def new_id(now: datetime | None = None) -> str:
    """Also the Sub ID the caption suggests: letters and digits only."""
    return f"p{(now or datetime.now()):%y%m%d%H%M%S}"


def link_in(text: str) -> str | None:
    """The affiliate link in a Brief: a Shopee one if there is one."""
    found = SHOPEE_LINK.search(text) or LINK.search(text)
    return found.group(0).rstrip(").,") if found else None


def _norm(number: str) -> str:
    return number.replace(",", "").rstrip(".")


def numbers(text: str) -> list[str]:
    return [_norm(n) for n in NUMBER.findall(text)]


def unsourced(text: str, brief: str) -> list[str]:
    """Every number in `text` that the Brief never had — single digits too.

    Stricter than ADR 0014's sheet check on purpose: in an explainer a lone
    digit is usually a count, here "4.9 ดาว" or "5 ปี" is a claim about a
    product someone is about to pay for.
    """
    known = set(numbers(LINK.sub(" ", brief)))
    return [n for n in numbers(text) if n not in known]


def discount(price: str, old_price: str) -> int | None:
    """Whole-percent discount, computed — never written by the model."""
    try:
        now, before = float(_norm(price)), float(_norm(old_price))
    except ValueError:
        return None
    if before <= 0 or now <= 0 or now >= before:
        return None
    return round((before - now) / before * 100)


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)


SYSTEM_PROMPT = f"""คุณเขียนสคริปต์คลิปรีวิวสินค้าสั้นแนวตั้ง (Shopee Video / Reels / Shorts) ภาษาไทย
ผู้พากย์เป็น**ผู้หญิง** ใช้ "ค่ะ/คะ" เท่านั้น ห้ามใช้ "ครับ"

ข้อมูลสินค้ามีแค่ที่ผู้ใช้ส่งมา (Brief) เท่านั้น — **ห้ามแต่งข้อมูลที่ไม่มีใน Brief**
ทั้งสเปก ตัวเลข รีวิว ดาว ยอดขาย ระยะประกัน หรือสรรพคุณ ถ้า Brief บอกน้อยก็พูดน้อย
ห้ามเคลมเกินจริง ห้ามอ้างผลทางการแพทย์/ลดน้ำหนัก/รักษาโรค ห้ามคำว่า "ดีที่สุด" "อันดับ 1" ถ้า Brief ไม่ได้บอก

ความยาวรวม 25-40 วินาที แบ่งเป็น {MIN_BEATS}-{MAX_BEATS} beat + การ์ดท้าย 1 ใบ

ตอบเป็น JSON อย่างเดียว รูปแบบ:
{{
  "title": "ชื่อโพสต์สั้นๆ ไม่เกิน {MAX_TITLE_CHARS} ตัวอักษร",
  "beats": [
    {{
      "badge": "ป้ายสั้นบนสุดของจอ ไม่เกิน {MAX_BADGE_CHARS} ตัวอักษร เช่น จุดขาย หรือราคา",
      "lines": ["บรรทัดซับที่ 1", "บรรทัดซับที่ 2 (ถ้ามี)"],
      "narration": "ประโยคที่พูดใน beat นี้",
      "spoken": "narration เดิม แต่ทับศัพท์คำอังกฤษเป็นอักษรไทย",
      "photo": 1
    }}
  ],
  "price": "ราคาขายเป็นตัวเลขล้วน เช่น 299 หรือ \\"\\" ถ้า Brief ไม่มีราคา",
  "old_price": "ราคาก่อนลดเป็นตัวเลขล้วน หรือ \\"\\"",
  "end_badge": "ป้ายบนการ์ดท้าย ไม่เกิน {MAX_BADGE_CHARS} ตัวอักษร",
  "end_narration": "ประโยคปิด ชวนกดลิงก์ในคอมเมนต์หรือกดตะกร้า",
  "end_spoken": "end_narration ทับศัพท์เป็นอักษรไทย",
  "caption": "ข้อความโพสต์ 1-3 ประโยค ไม่ต้องใส่ลิงก์และแฮชแท็ก",
  "hashtags": ["#แฮชแท็ก", "ไม่เกิน 6 อัน"]
}}

กฎ:
- beat แรกคือ hook ต้องหยุดนิ้วใน 2 วินาที เปิดด้วยปัญหาที่สินค้านี้แก้ หรือสิ่งที่ทำให้สะดุดตา
  ห้ามเกริ่น "วันนี้จะมารีวิว" ห้ามขึ้นต้นเหมือนคลิปก่อนๆ ในรายการที่ให้ไว้
- **lines คือ narration ของ beat นั้นเป๊ะ ตัดเป็น 1-2 บรรทัด** ต่อกันแล้วต้องได้ narration ทุกตัวอักษร
  บรรทัดละประมาณ {TARGET_LINE_CHARS} ตัวอักษร ตัดตรงรอยต่อคำ ถ้า narration ยาวเกิน 2 บรรทัดให้แยกเป็น beat ใหม่
- photo = หมายเลขรูปจาก Brief (เริ่มที่ 1) เลือกรูปที่ตรงกับสิ่งที่พูด ใช้รูปซ้ำได้
- spoken: ห้ามมีอักษรละติน (a-z) แม้แต่ตัวเดียว ทับศัพท์ทุกคำ เช่น USB-C → ยูเอสบีซี
  **ตัวเลขใน spoken ให้คงเป็นตัวเลขอารบิกเหมือนใน narration** ห้ามเขียนเป็นคำ (ห้าม "สองร้อย")
  ห้ามใส่สัญลักษณ์ ฿ ใน spoken ให้เขียน "บาท"
- **ตัวเลขทุกตัวต้องมีอยู่ใน Brief** ห้ามคำนวณหรือปัดเอง **ห้ามเขียนเปอร์เซ็นต์ส่วนลด (%)** โปรแกรมคำนวณให้เอง
- ห้าม emoji ห้ามใส่ลิงก์ในข้อความใดๆ"""


def system_prompt() -> str:
    return SYSTEM_PROMPT


def line_too_wide(line: str) -> bool:
    """Whether a subtitle line cannot be drawn at a readable size."""
    try:
        font = render._font(render.THAI_BOLD, SUBTITLE_MIN_SIZE)
    except (OSError, RuntimeError):
        return len(line) > FALLBACK_LINE_CHARS
    return font.getlength(line) > SUBTITLE_WIDTH


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _check_voice(narration: str, spoken: str, where: str, brief: str) -> None:
    if not narration:
        raise PitchError(f"{where}: narration ว่าง")
    if not spoken:
        raise PitchError(f"{where}: spoken ว่าง")
    for text in (narration, spoken):
        if "ครับ" in text:
            raise PitchError(f"{where}: ผู้พากย์เป็นผู้หญิง ห้ามใช้ ครับ")
    if LATIN.search(spoken):
        raise PitchError(f"{where}: spoken มีอักษรละติน ต้องทับศัพท์เป็นไทย")
    if "฿" in spoken:
        raise PitchError(f"{where}: spoken ห้ามมี ฿ ให้เขียน บาท")
    if numbers(spoken) != numbers(narration):
        raise PitchError(f"{where}: ตัวเลขใน spoken ต้องตรงกับ narration และเป็นตัวเลขอารบิก")
    if NUMBER_WORDS.search(spoken) and not NUMBER_WORDS.search(narration):
        raise PitchError(f"{where}: spoken เขียนตัวเลขเป็นคำ ให้ใช้ตัวเลขอารบิกเหมือน narration")
    made_up = unsourced(narration, brief)
    if made_up:
        raise PitchError(f"{where}: ตัวเลข {', '.join(made_up)} ไม่มีใน Brief ห้ามแต่งเอง")


def validate(pitch: dict, brief: str, photos: int) -> dict:
    """The Pitch, normalised, or PitchError with what to fix."""
    if not isinstance(pitch, dict):
        raise PitchError("ต้องตอบเป็น JSON object")
    title = _text(pitch.get("title"))
    if not title or len(title) > MAX_TITLE_CHARS:
        raise PitchError(f"title ต้องมีและไม่เกิน {MAX_TITLE_CHARS} ตัวอักษร")
    beats = pitch.get("beats")
    if not isinstance(beats, list) or not MIN_BEATS <= len(beats) <= MAX_BEATS:
        raise PitchError(f"ต้องมี {MIN_BEATS}-{MAX_BEATS} beat")

    clean_beats = []
    for i, beat in enumerate(beats, 1):
        where = f"beat {i}"
        if not isinstance(beat, dict):
            raise PitchError(f"{where}: ต้องเป็น object")
        badge = _text(beat.get("badge"))
        if not badge or len(badge) > MAX_BADGE_CHARS:
            raise PitchError(f"{where}: badge ต้องมีและไม่เกิน {MAX_BADGE_CHARS} ตัวอักษร")
        lines = [_text(line) for line in beat.get("lines") or [] if _text(line)]
        if not 1 <= len(lines) <= 2:
            raise PitchError(f"{where}: lines ต้องมี 1-2 บรรทัด")
        wide = [line for line in lines if line_too_wide(line)]
        if wide:
            raise PitchError(f"{where}: บรรทัดซับยาวเกินจอ ({wide[0]}) ตัดให้สั้นลงหรือแยก beat")
        narration, spoken = _text(beat.get("narration")), _text(beat.get("spoken"))
        # Burned in for viewers with the sound off: the subtitle must be what
        # the voice says, not a paraphrase of it.
        if _squash("".join(lines)) != _squash(narration):
            raise PitchError(f"{where}: lines ต่อกันต้องได้ narration ทุกตัวอักษร")
        _check_voice(narration, spoken, where, brief)
        made_up = unsourced(badge, brief)
        if made_up:
            raise PitchError(f"{where}: ตัวเลข {', '.join(made_up)} ใน badge ไม่มีใน Brief")
        try:
            photo = int(beat.get("photo"))
        except (TypeError, ValueError):
            raise PitchError(f"{where}: photo ต้องเป็นเลขรูป 1-{photos}") from None
        if not 1 <= photo <= photos:
            raise PitchError(f"{where}: photo ต้องเป็นเลขรูป 1-{photos}")
        clean_beats.append({"badge": badge, "lines": lines, "narration": narration,
                            "spoken": spoken, "photo": photo})

    prices = {}
    for key in ("price", "old_price"):
        value = _norm(_text(str(pitch.get(key) or "")).lstrip("฿").strip())
        if value and (not NUMBER.fullmatch(value) or unsourced(value, brief)):
            raise PitchError(f"{key} ต้องเป็นตัวเลขที่มีใน Brief หรือว่าง")
        prices[key] = value
    if prices["old_price"] and not prices["price"]:
        raise PitchError("มี old_price แต่ไม่มี price")

    end_badge = _text(pitch.get("end_badge"))
    if not end_badge or len(end_badge) > MAX_BADGE_CHARS:
        raise PitchError(f"end_badge ต้องมีและไม่เกิน {MAX_BADGE_CHARS} ตัวอักษร")
    end_narration, end_spoken = _text(pitch.get("end_narration")), _text(pitch.get("end_spoken"))
    _check_voice(end_narration, end_spoken, "การ์ดท้าย", brief)

    caption = _text(pitch.get("caption"))
    if not caption:
        raise PitchError("caption ว่าง")
    hashtags = [_text(h) for h in pitch.get("hashtags") or [] if _text(h)]
    if not 1 <= len(hashtags) <= 6 or not all(h.startswith("#") for h in hashtags):
        raise PitchError("hashtags ต้องมี 1-6 อัน ขึ้นต้นด้วย #")

    written = " ".join([title, end_badge, caption, *hashtags])
    made_up = unsourced(written, brief)
    if made_up:
        raise PitchError(f"ตัวเลข {', '.join(made_up)} ใน title/caption ไม่มีใน Brief")
    everything = written + " " + " ".join(b["badge"] + b["narration"] for b in clean_beats) + end_narration
    if "%" in everything:
        raise PitchError("ห้ามเขียนเปอร์เซ็นต์ โปรแกรมคำนวณส่วนลดให้เอง")
    if LINK.search(everything):
        raise PitchError("ห้ามใส่ลิงก์ในข้อความ โปรแกรมใส่ให้เอง")

    return {"title": title, "beats": clean_beats, **prices, "end_badge": end_badge,
            "end_narration": end_narration, "end_spoken": end_spoken,
            "caption": caption, "hashtags": hashtags}


def _avoid_note(recent: list[str]) -> str:
    if not recent:
        return ""
    listed = "\n".join(f"- {line}" for line in recent)
    return ("hook ของคลิปสินค้าก่อนๆ ห้ามขึ้นต้นเหมือนหรือคล้ายกัน "
            "(แพลตฟอร์มลดการมองเห็นคลิปที่ซ้ำกัน):\n" + listed)


async def generate(brief: str, photos: int, previous: dict | None = None,
                   feedback: str = "", recent: list[str] | None = None) -> dict:
    """Write (or rewrite) a Pitch from the Brief. Same retry shape as Scripts:
    one wall-clock budget, a broken answer goes back to the model with why."""
    messages = [{"role": "system", "content": system_prompt()}]
    note = _avoid_note(recent or [])
    if note:
        messages.append({"role": "system", "content": note})
    messages.append({"role": "user", "content": f"Brief (มีรูป {photos} รูป):\n{brief}"})
    if previous is not None:
        messages.append({"role": "assistant", "content": json.dumps(previous, ensure_ascii=False)})
        messages.append({"role": "user", "content": f"แก้ตามนี้: {feedback}"})

    client = script_gen._client()
    deadline = time.monotonic() + BUDGET_SECONDS
    last_error: Exception | None = None
    for attempt in range(3):
        left = deadline - time.monotonic()
        if left < MIN_ATTEMPT:
            break
        model = model_choice.primary() if attempt == 0 else model_choice.fallback()
        try:
            raw = await script_gen._say(client, messages, temperature=0.8, budget=left, model=model)
        except TimeoutError:
            # Keep what went wrong before the stall: a run of rejected Pitches
            # that ends in a timeout is a prompt problem, not a slow model.
            stalled = f"mimo ไม่ตอบภายใน {BUDGET_SECONDS:.0f} วินาที"
            last_error = script_gen.ScriptStalled(
                f"{stalled} — รอบก่อนหน้า: {last_error}" if last_error else stalled)
            continue
        except script_gen.ScriptError as exc:
            last_error = exc
            continue
        try:
            parsed = script_gen._parse(raw)
        except script_gen.ScriptError as exc:
            last_error = exc
            continue
        try:
            return validate(parsed, brief, photos)
        except PitchError as exc:
            logger.warning("Pitch ผิดกติกา: %s", exc)
            last_error = exc
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"ผิดกติกา: {exc} — ส่ง JSON ใหม่ให้ถูกกติกา"},
            ]
    raise last_error or PitchError("ไม่มีคำตอบ")


def format_pitch(pitch: dict) -> str:
    """The review message: what will be on screen and what will be said."""
    parts = [f"🛍 {pitch['title']}", ""]
    for i, beat in enumerate(pitch["beats"], 1):
        parts.append(f"[{i}] 🏷 {beat['badge']} · 📷 รูป {beat['photo']}")
        parts.append(f"   💬 {' / '.join(beat['lines'])}")
        if _squash(beat["spoken"]) != _squash(beat["narration"]):
            parts.append(f"   🗣 {beat['spoken']}")
    price = pitch.get("price")
    off = discount(price or "", pitch.get("old_price") or "")
    tail = f"฿{price}" if price else "ไม่มีราคา"
    if off:
        tail = f"฿{pitch['old_price']} → {tail} (ลด {off}%)"
    parts += ["", f"[ท้าย] 🏷 {pitch['end_badge']} · {tail}", f"   🔊 {pitch['end_narration']}",
              "", pitch["caption"], " ".join(pitch["hashtags"]),
              "", "พิมพ์บอกได้เลยว่าอยากแก้ตรงไหน"]
    return "\n".join(parts)


def caption_text(pitch: dict, link: str | None) -> str:
    """The post text, ready to paste. The disclosure is not optional."""
    parts = [pitch["title"], "", pitch["caption"]]
    if link:
        parts += ["", f"🛒 {link}"]
    parts += ["", DISCLOSURE, " ".join(pitch["hashtags"])]
    return "\n".join(parts)


def recent_hooks(root: Path, limit: int = 15) -> list[str]:
    """The opening lines of the latest Product Clips, newest first."""
    hooks = []
    for record in sorted(root.glob("*/shop.json"), reverse=True)[:limit]:
        try:
            pitch = json.loads(record.read_text("utf-8")).get("pitch") or {}
            hooks.append(pitch["beats"][0]["narration"])
        except (OSError, ValueError, KeyError, IndexError, TypeError):
            continue
    return hooks
