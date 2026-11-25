"""Numbers as they are SPOKEN in Thai, for lining up a script with a Whisper transcript.

ps2-hdd-175 (2026-11-24): the line "เลือกได้ 175 225 275 เกม" broke the subtitles twice.
- post_presenter.norm() mapped only the whole tokens 0..10 to words and then kept letters only, so "175,225,275"
  normalised to "" — the phrase had no characters to align, its subtitle got a zero-width slot after the speech,
  and "เลือกได้" stayed on screen for 4 s while she read the numbers.
- gen_vo_natural.align_bounds() weighed each phrase by its `say` length (Thai words: "หนึ่งร้อยเจ็ดสิบห้า" =
  19 chars) against Whisper's text ("175" = 3 chars), so every boundary estimate after the numbers slid early
  (sub 1 ended at 1.38 s; she spoke it until 3.55 s).
Whisper also splits a number across word tokens (" 22" + "5", " 27" + "5"): `merge_digit_tokens` joins them.

Both sides of an alignment go through `digits_to_thai`, so it only has to be consistent, not perfect Thai
grammar. Comma rule: one comma, or a 1-2 digit first group = thousands (1,290 / 12,000 / 2,500,000); two or more
commas after a 3-digit group = a LIST read number by number (175,225,275). Thai digits (U+0E50-0E59) count.
"""
import re
import unicodedata

DIG = ["ศูนย์", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
POS = ["", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน"]
THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")
NUM = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?%?")
DIGITISH = re.compile(r"^[\d,.]+%?$")


def _below_million(n):
    s, out = str(n), []
    for i, ch in enumerate(s):
        d, p = int(ch), len(s) - i - 1
        if d == 0:
            continue
        if p == 1:
            out.append({1: "สิบ", 2: "ยี่สิบ"}.get(d, DIG[d] + "สิบ"))
        elif p == 0 and d == 1 and n > 10:
            out.append("เอ็ด")
        else:
            out.append(DIG[d] + POS[p])
    return "".join(out)


def int_to_thai(n):
    """175 -> หนึ่งร้อยเจ็ดสิบห้า, 21 -> ยี่สิบเอ็ด, 2_500_000 -> สองล้านห้าแสน."""
    if n == 0:
        return DIG[0]
    if n >= 1_000_000:
        hi, lo = divmod(n, 1_000_000)
        return int_to_thai(hi) + "ล้าน" + (_below_million(lo) if lo else "")
    return _below_million(n)


def read_number(tok):
    """One numeric token as spoken: '1,290' / '2.5' / '97%' / '175,225,275' (a list)."""
    pct = tok.endswith("%")
    tok = tok.rstrip("%")
    groups = tok.split(".")[0].split(",")
    if len(groups) > 2 and len(groups[0]) == 3:               # 175,225,275 = three numbers
        words = "".join(int_to_thai(int(g)) for g in groups)
    else:
        whole, _, frac = tok.replace(",", "").partition(".")
        words = int_to_thai(int(whole)) + ("จุด" + "".join(DIG[int(c)] for c in frac) if frac else "")
    return words + ("เปอร์เซ็นต์" if pct else "")


def digits_to_thai(text):
    """Every number in `text` replaced by its spoken Thai words (the rest unchanged)."""
    return NUM.sub(lambda m: read_number(m.group()), text.translate(THAI_DIGITS))


def spoken_len(text):
    """Letters a line is spoken with: numbers read out, spaces / punctuation / digits gone."""
    return sum(1 for c in digits_to_thai(text) if unicodedata.category(c)[0] in "LM")


def merge_digit_tokens(words):
    """[(text, t0, t1)] -> the same with a number Whisper split over tokens (' 22', '5') joined into one.
    A token that starts with a space starts a new word; a digit token glued to a digit token is one number."""
    out = []
    for text, t0, t1 in words:
        tok = text.translate(THAI_DIGITS)
        if out and DIGITISH.match(tok.strip() or "x") and not tok[:1].isspace() \
                and DIGITISH.match(out[-1][0].strip() or "x"):
            prev = out.pop()
            out.append((prev[0] + tok, prev[1], t1))
            continue
        out.append((tok, t0, t1))
    return out


# ---------------------------------------------------------------- display (subtitles show digits)
UNITS = sorted("""ปี เดือน วัน สัปดาห์ อาทิตย์ ชั่วโมง นาที วินาที วิ กรัม กิโลกรัม กิโล มิลลิกรัม มก มิลลิลิตร มล ลิตร ซอง
ชิ้น ขวด กล่อง หลอด แพ็ค แพ็ก ชุด คู่ อัน ตัว คน ครั้ง เท่า สี รส แบบ ช่อง ด้าน ขนาด ระดับ โหมด เกม นิ้ว เซนติเมตร
ซม เมตร วัตต์ องศา ปุ่ม ข้อ ใบ แผ่น ม้วน เม็ด แคปซูล ลูก ช่อ ห้อง ชั้น เครื่อง""".split(), key=len, reverse=True)
NUM_WORDS = re.compile("((?:หนึ่ง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า|ยี่|สิบ|เอ็ด|ร้อย|พัน|หมื่น)+)(?=(?:"
                       + "|".join(UNITS) + "))")
_WORD_INT = {}


def word_to_int(words):
    """'ยี่สิบ' -> 20; None unless int_to_thai gives the same words back (ร้อยแปด, สองสาม stay words)."""
    if not _WORD_INT:
        _WORD_INT.update({int_to_thai(n): n for n in range(1, 20001)})
    return _WORD_INT.get(words)


def display_numbers(text):
    """A spelled count before a unit shows as digits on screen: หนึ่งปีขึ้นไป -> 1 ปีขึ้นไป, สามพันมิลลิกรัม ->
    3,000 มิลลิกรัม (promom-cal-d-kiiz 2026-11-25: the sub read หนึ่งปีขึ้นไป under a 1 ปีขึ้นไป label). Only an
    exact Thai reading followed by a unit word changes; the VO line itself is not touched."""
    def sub(m):
        n = word_to_int(m.group(1))
        if n is None:
            return m.group(0)
        lead = " " if m.start() and unicodedata.category(text[m.start() - 1])[0] in "LM" else ""
        return f"{lead}{n:,} "
    return NUM_WORDS.sub(sub, text)


def is_number(text):
    """A phrase that is only a count: '20', '3,000', '97%', 'ยี่สิบ'."""
    t = text.strip().translate(THAI_DIGITS)
    return bool(t) and (bool(DIGITISH.match(t)) or word_to_int(t) is not None)
