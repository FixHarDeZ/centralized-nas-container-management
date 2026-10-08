"""Words to listen for in a Script, derived from text rather than audio.

The writer supplies exact narration/spoken pairs for semantic cases such as
Thai loanwords. Local extraction keeps Latin terms from disappearing when the
optional metadata is missing; it never guesses their transliterations.
"""
from __future__ import annotations

import re

KINDS = {
    "acronym": (0, "ตัวย่อ: ฟังคำอ่านหรือการสะกด ไม่ให้รวบเสียง"),
    "model_name": (0, "ชื่อรุ่น: ฟังตัวอักษรและเลขรุ่นติดกัน"),
    "proper_name": (1, "ชื่อเฉพาะ: ฟังการแบ่งพยางค์และจังหวะ"),
    "loanword": (2, "คำทับศัพท์: ฟังจังหวะและเสียงท้ายคำ"),
}
LATIN_TERM = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z]\.){2,}"
    r"|(?<![A-Za-z0-9_])[A-Za-z0-9]*[A-Za-z][A-Za-z0-9]*"
    r"(?:\+\+\d*|#\d*)?(?:[._+/-][A-Za-z0-9]+)*"
)


def _pattern(term: str) -> re.Pattern:
    # A Thai substring is useful inside unspaced Thai. A Latin substring is
    # not: AI inside RAID does not refer to AI.
    left = r"(?<![A-Za-z0-9_])" if term[0].isascii() and term[0].isalnum() else ""
    right = r"(?![A-Za-z0-9_])" if term[-1].isascii() and term[-1].isalnum() else ""
    return re.compile(left + re.escape(term) + right, re.IGNORECASE)


def _valid_checks(card: dict) -> list[dict]:
    checks = card.get("pronunciation_checks")
    if not isinstance(checks, list):
        return []
    narration = card.get("narration") or ""
    spoken = card.get("spoken") or narration
    valid = []
    for entry in checks:
        if not isinstance(entry, dict):
            continue
        term, reading, kind = (entry.get(k) for k in ("term", "spoken", "kind"))
        if not all(isinstance(value, str) and value.strip() for value in (term, reading, kind)):
            continue
        term, reading, kind = term.strip(), reading.strip(), kind.strip()
        if kind in KINDS and _pattern(term).search(narration) and reading in spoken:
            valid.append({"term": term, "spoken": reading, "kind": kind})
    return valid


def normalize(script: dict) -> dict:
    """Sanitize optional metadata in place; leave narration/voice text intact."""
    for card in script.get("cards") or []:
        if "pronunciation_checks" in card:
            card["pronunciation_checks"] = _valid_checks(card)
    return script


def _kind(term: str) -> str:
    if re.fullmatch(r"\d+[A-Z]{1,3}", term):
        return "acronym"
    if any(char.isdigit() for char in term):
        return "model_name"
    if "+" in term or "#" in term:
        return "proper_name"
    letters = re.sub(r"[^A-Za-z]", "", term)
    if len(letters) >= 2 and letters.isupper():
        return "acronym"
    return "loanword"


def _fallback(narration: str, checks: list[dict], locale: str) -> list[dict]:
    covered = [match.span() for check in checks for match in _pattern(check["term"]).finditer(narration)]
    tokens = [match for match in LATIN_TERM.finditer(narration)
              if not any(start <= match.start() and match.end() <= end for start, end in covered)]
    out = []
    i = 0
    while i < len(tokens):
        match = tokens[i]
        term, end = match.group(), match.end()
        kind = _kind(term)
        i += 1
        # Preserve ordinary multiword names (Google Flow, OpenAI ChatGPT) in
        # Thai fallback; do not merge adjacent initialisms such as CPU RAM.
        if locale != "en" and kind == "loanword" and term[0].isupper():
            while i < len(tokens):
                next_match = tokens[i]
                next_term = next_match.group()
                gap = narration[end:next_match.start()]
                if not gap.isspace() or not next_term[0].isupper() or _kind(next_term) != "loanword":
                    break
                term += gap + next_term
                end = next_match.end()
                i += 1
            if " " in term:
                kind = "proper_name"
        if locale != "en" or kind in {"acronym", "model_name"} or "+" in term or "#" in term:
            out.append({"term": term, "spoken": "", "kind": kind})
    return out


def collect(script: dict, locale: str = "th") -> list[dict]:
    """Validated terms, grouped by spelling/reading, with 1-based Card indices."""
    grouped: dict[tuple[str, str], dict] = {}
    for number, card in enumerate(script.get("cards") or [], 1):
        checks = _valid_checks(card)
        narration = card.get("narration") or ""
        context = card.get("spoken") or narration
        for entry in checks + _fallback(narration, checks, locale):
            key = (entry["term"].casefold(), entry["spoken"])
            item = grouped.setdefault(key, {**entry, "cards": [], "contexts": {}})
            if number not in item["cards"]:
                item["cards"].append(number)
                item["contexts"][number] = context
            if KINDS[entry["kind"]][0] < KINDS[item["kind"]][0]:
                item["kind"] = entry["kind"]
    return sorted(grouped.values(), key=lambda item: KINDS[item["kind"]][0])


def format_checks(script: dict, locale: str = "th") -> str:
    """A separate Telegram message; `say()` handles size limits, not slicing."""
    parts = [f"🎧 คำที่ควรลองฟัง — {script.get('title', '')}"]
    checks = collect(script, locale)
    for item in checks:
        cards = ", ".join(str(number) for number in item["cards"])
        label = item["term"]
        if item["spoken"]:
            label += f" → {item['spoken']}"
        parts.append(f"• {label}\n  card {cards} · {KINDS[item['kind']][1]}")
        if not item["spoken"]:
            parts.append("  ต้องตรวจการจับคู่คำอ่าน — ข้อความที่อ่านในสคริปต์:")
            parts.extend(f"  card {number}: {text}" for number, text in item["contexts"].items())
    if not checks:
        parts.append("ไม่พบคำที่เข้าข่ายในข้อความ — ยังควรฟังคลิปก่อนอัปโหลด")
    parts.extend([
        "รายการนี้คัดจากข้อความ ยังไม่ได้ตรวจเสียงจริง",
        "คำอ่านเป็นข้อความในสคริปต์; ค่าที่ตั้งไว้ใน /say อาจแทนที่ตอน render",
        "เสียงเพี้ยน: /say <คำอ่านที่ผิด> = <คำอ่านที่ต้องการ> แล้ว /redo",
    ])
    # The shared transport cuts a single over-limit line rather than retaining
    # its tail. Wrap display lines here so even unusually long model text is
    # delivered in full, without changing the Script or the TTS wording.
    lines = []
    for line in "\n\n".join(parts).split("\n"):
        lines.extend(line[start:start + 4096] for start in range(0, max(1, len(line)), 4096))
    return "\n".join(lines)
