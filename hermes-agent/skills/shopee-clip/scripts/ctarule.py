#!/usr/bin/env python3
"""The link line closes the clip (Fix 2026-11-17).

shokubutsu-shower-gel shipped with the final shot saying "ลิงก์อยู่ใต้คลิปนะจ๊ะ ไปดูรายละเอียดกันได้เลย
กลิ่นก็มีให้เลือกเพียบ": a selling point AFTER the link line, and the `Link below!` pill (fixed to the
clip's last seconds) on that selling point instead of on the link line.

Shared by clipjob.py (refuses the prompt before credits are spent) and post_presenter.py (ties the pill
to the spoken link line, flags a clip whose audio still ends on something else). Stdlib only.

  ctarule.py shot3.txt        # exit 1 + the reason when a selling point follows the link line
"""
import re
import sys
import unicodedata

# the SCRIPT's spelling (clipjob.CTA_PATTERNS is looser: it reads whisper's spelling of the audio)
LINK = re.compile(r"ลิ[้]?ง[กค]์|ใต้คลิป|คำอธิบาย|พิกัด|ตะกร้า|\blink\b", re.I)
# what may follow the link line: more call-to-action, or a short sign-off
CLOSER = re.compile(r"ไปดู|กดดู|กดเลย|กดสั่ง|ตามไป|จิ้ม|สั่ง|ไปตำ|รายละเอียด|รีบ|"
                    r"(เลย|นะ|จ๊ะ|จ้ะ|จ้า|คะ|ค่ะ|น้า|เนอะ)[!?.…~]*$")


def voiceover(text):
    """The script inside  Audio (Thai voiceover): "..."  — or the text itself when there is no such block."""
    m = re.search(r'Audio \(Thai voiceover\)[^"“]*["“](.+?)["”]', text, re.S)
    return (m.group(1) if m else text).strip()


def phrases(script):
    return [p for p in re.split(r"\s+", script) if p]


def _len(s):
    return sum(1 for c in s if unicodedata.category(c)[0] in "LN" )


def link_span(phr):
    """-> (first, last) phrase index of the link line, or None when the script has no link line."""
    hits = [i for i, p in enumerate(phr) if LINK.search(p)]
    return (hits[0], hits[-1]) if hits else None


def after_link(phr):
    """Phrases after the link line that are NOT a call to action or a sign-off: selling points said too late."""
    span = link_span(phr)
    if not span:
        return []
    return [p for p in phr[span[1] + 1:] if not CLOSER.search(p) and _len(p) > 5]


def problem(script):
    late = after_link(phrases(script))
    if late:
        return ("ประโยคลิงก์ต้องปิดท้ายคลิป แต่ยังมีจุดขายตามหลัง: " + " / ".join(late)
                + " — ย้ายขึ้นไปก่อนประโยคลิงก์")
    return ""


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    why = problem(voiceover(open(sys.argv[1], encoding="utf-8").read()))
    if why:
        sys.exit(why)
    print("ok")
