"""thainum (numbers as spoken) and post_presenter's script/ASR alignment of a line with numbers."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import post_presenter as pp
import thainum as tn


def test_readings():
    assert tn.read_number("175") == "หนึ่งร้อยเจ็ดสิบห้า"
    assert tn.read_number("21") == "ยี่สิบเอ็ด"
    assert tn.read_number("10") == "สิบ"
    assert tn.read_number("1,290") == "หนึ่งพันสองร้อยเก้าสิบ"
    assert tn.read_number("2.5") == "สองจุดห้า"
    assert tn.read_number("97%") == "เก้าสิบเจ็ดเปอร์เซ็นต์"
    assert tn.read_number("2,500,000") == "สองล้านห้าแสน"
    # a comma list (three game counts), not 175 million
    assert tn.read_number("175,225,275") == "หนึ่งร้อยเจ็ดสิบห้าสองร้อยยี่สิบห้าสองร้อยเจ็ดสิบห้า"
    assert tn.digits_to_thai("๑๗๕ เกม") == "หนึ่งร้อยเจ็ดสิบห้า เกม"


def test_merge_digit_tokens_joins_a_split_number_only():
    toks = [("ได", 0, 1), (" 175", 1.5, 2.3), (" 22", 2.3, 2.9), ("5", 2.9, 3.4), (" เก", 4.3, 4.4), ("ม", 4.4, 4.7)]
    assert tn.merge_digit_tokens(toks) == [("ได", 0, 1), (" 175", 1.5, 2.3), (" 225", 2.3, 3.4),
                                           (" เก", 4.3, 4.4), ("ม", 4.4, 4.7)]


def test_norm_keeps_a_number_phrase():
    """ps2-hdd-175-pres: norm('175,225,275') was '' -> zero-width fallback subtitle after the speech."""
    assert pp.norm("175,225,275") == pp.norm("หนึ่งร้อยเจ็ดสิบห้า สองร้อยยี่สิบห้า สองร้อยเจ็ดสิบห้า")
    assert len(pp.norm("175,225,275")) > 30


def chars(words):
    """Whisper-like (text, t0, t1) words -> post_presenter's per-char list (the asr() inner loop)."""
    out = []
    for word, w0, w1 in tn.merge_digit_tokens(words):
        n = pp.norm(word)
        for k, c in enumerate(n):
            out.append((c, w0 + k * (w1 - w0) / len(n), w0 + (k + 1) * (w1 - w0) / len(n)))
    return out


def test_align_times_the_number_phrase_where_it_is_spoken():
    """Real tokens of shot 2 (medium): she says เลือกได้ to ~1.5 s, the numbers 1.54-4.22 s, then เกม."""
    words = [("เล", 0.0, 0.0), ("ื", 0.0, 0.0), ("อก", 0.0, 1.08), ("ได", 1.08, 1.32), ("้", 1.32, 1.54),
             (" 175", 1.54, 2.32), (" 22", 2.32, 2.94), ("5", 2.94, 3.36), (" 27", 3.36, 3.76), ("5", 3.76, 4.22),
             (" เก", 4.36, 4.36), ("ม", 4.36, 4.7), ("ล", 4.7, 4.8), ("ิ", 4.8, 4.8), ("ง", 4.8, 4.92),
             ("ใ", 4.92, 5.02), ("ต", 5.02, 5.08), ("้", 5.08, 5.16), ("ค", 5.16, 5.22), ("ล", 5.22, 5.22),
             ("ิ", 5.22, 5.3), ("ป", 5.3, 5.36), ("เลย", 5.36, 5.64)]
    phr, ins, mode, _, _ = pp.align_script(["เลือกได้", "175,225,275", "เกม", "ลิงก์ใต้คลิปเลย"],
                                           chars(words), (0.0, 5.7))
    assert mode == "aligned" and ins == []
    sel, num = phr[0], phr[1]
    assert num["status"] == "matched" and abs(num["t0"] - 1.54) < 0.1 and abs(num["t1"] - 4.22) < 0.1
    assert sel["t1"] <= 1.6                       # was 4.07: เลือกได้ sat on screen through the numbers
