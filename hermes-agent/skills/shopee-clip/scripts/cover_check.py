#!/usr/bin/env python3
"""Poster-cover gate by pixels: price / promo text and QR codes inside the pictures, tofu in the typed text.

The cover's `check_sheet` vision call asked these and timed out at 420 s on huawei-watchfit5 and ps5-discdrive
(2026-11-23; median vision call 55 s, cover reads the slowest). Typed text is already gated by
make_poster_cover.py (BANNED price wording); what it cannot see is text and codes INSIDE the hero and slot
pictures. This reads them, with no vision call:

  uv run -q --with rapidocr-onnxruntime --with "opencv-python-headless<5" --with numpy --with pillow \
      python cover_check.py cover_spec.json [--qr-ok "<what the code is, e.g. the watch's own pay screen>"]

- every picture the cover shows (hero after `hero_box`, each circle after `box`) -> RapidOCR: a currency sign,
  a price-shaped number (1,290 / 990.- / 199฿), a minus-percent (-50%) or a promo word (SALE, OFF, COUPON,
  CODE, FREE, ลด, ส่วนลด, คูปอง, โค้ด, ส่งฟรี, ราคา, บาท) = hit. A plain "97%" or "10:08" on a product screen passes.
- OpenCV QR detector on each picture: a QR = hit unless --qr-ok says what it is (a shop's QR never ships;
  the product's own screen showing a code may, and the ack is printed into the verdict).
- every character of the typed strings must have a glyph in the cover font (an empty box / tofu otherwise).
Last line = JSON verdict {"ok", "hits", "vision"}; exit 0 clean, 1 hit, 2 usage. `vision` tells whether the
one vision call is still needed: only for detail slots (does each show its label's thing), never for a
hero-only cover.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CURRENCY = re.compile(r"[฿$€£¥]|\bTHB\b|บาท", re.I)
PRICE = re.compile(r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\b\d{2,6}\s*\.-|\b\d{2,6}\s*[฿บ]")
MINUS_PCT = re.compile(r"[-\u2212\u2013]\s*\d{1,2}\s*%|\d{1,2}\s*%\s*(?:off|ลด)|(?:ลด|off|save)\s*\d{1,2}\s*%", re.I)
PROMO = re.compile(r"\b(?:sale|off|coupon|code|voucher|free\s*ship\w*|discount|promo)\b|ส่วนลด|คูปอง|โค้ด|ส่งฟรี|"
                   r"ราคา|ลดราคา|ลดเหลือ|โปรโมชั่น|แถมฟรี", re.I)


def price_hits(text):
    """Which price / promo signals a piece of OCR text carries ([] = clean)."""
    out = []
    for name, rx in (("currency", CURRENCY), ("price", PRICE), ("discount %", MINUS_PCT), ("promo word", PROMO)):
        m = rx.search(text)
        if m:
            out.append(f"{name} {m.group(0)!r}")
    return out


def missing_glyphs(strings, font):
    """Characters the font draws as its .notdef box (tofu). Spaces and joiners are skipped."""
    ref = font.getmask("\U0010FFFD")
    ref_box, ref_bytes = ref.getbbox(), bytes(ref)
    bad = []
    for s in strings:
        for ch in s:
            if ch.isspace() or ch in "​‌‍":
                continue
            m = font.getmask(ch)
            if m.getbbox() == ref_box and bytes(m) == ref_bytes and ch not in bad:
                bad.append(ch)
    return bad


def spec_strings(spec):
    title = spec.get("title") or []
    badge = spec.get("badge") or []
    out = [title] if isinstance(title, str) else list(title)
    out += [badge] if isinstance(badge, str) else list(badge)
    out += [spec.get("sub") or "", *(spec.get("chips") or [])]
    out += [c.get("label") or "" for c in spec.get("circles") or []]
    return [s for s in out if s]


def pictures(spec, base):
    import make_poster_cover as mpc
    from PIL import Image

    def path(p):
        return p if os.path.isabs(p) else os.path.join(base, p)
    pics = [("hero", mpc.crop_box(Image.open(path(spec["hero"])).convert("RGB"), spec.get("hero_box"), "hero_box"))]
    for i, c in enumerate(spec.get("circles") or []):
        pics.append((f"slot {i + 1} ({c.get('label')})",
                     mpc.crop_box(Image.open(path(c["image"])).convert("RGB"), c.get("box"), f"circle {i + 1}")))
    return pics


def ocr_texts(ocr, im):
    import numpy as np
    s = min(1.0, 1600 / max(im.size))
    if s < 1:
        im = im.resize((round(im.width * s), round(im.height * s)))
    found, _ = ocr(np.asarray(im)[:, :, ::-1])
    return [(t, float(c)) for _, t, c in (found or [])]


def has_qr(im):
    import cv2
    import numpy as np
    a = np.asarray(im)[:, :, ::-1]
    det = cv2.QRCodeDetector()
    # decoded only: detect() alone took cable-knit, a car dash and game-cover art for QR codes on 5 of 32 real
    # covers; a shop's code is printed to be scanned, so it decodes
    for img in (a, cv2.resize(a, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)):
        try:
            data, pts, _ = det.detectAndDecode(img)
        except cv2.error:
            continue
        if data:
            return True
    return False


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("spec")
    ap.add_argument("--qr-ok", metavar="WHAT")
    a = ap.parse_args(argv)
    try:
        with open(a.spec, encoding="utf-8") as f:
            spec = json.load(f)
    except (OSError, ValueError) as e:
        print(json.dumps({"ok": False, "error": str(e)}))
        return 2
    import make_poster_cover as mpc
    from rapidocr_onnxruntime import RapidOCR
    ocr, hits, notes = RapidOCR(), [], []
    for name, im in pictures(spec, os.path.dirname(os.path.abspath(a.spec))):
        for text, conf in ocr_texts(ocr, im):
            if conf < 0.5:
                continue
            why = price_hits(text)
            if why:
                hits.append(f"{name}: text {text!r} ({', '.join(why)})")
        if has_qr(im):
            if a.qr_ok:
                notes.append(f"{name}: QR code acked ({a.qr_ok})")
            else:
                hits.append(f"{name}: QR code — crop it out or pick another frame; --qr-ok \"<what>\" only when it "
                            "is the product's own screen, never a shop's code")
    tofu = missing_glyphs(spec_strings(spec), mpc.font(60))
    if tofu:
        hits.append(f"typed text: no glyph for {[f'U+{ord(c):04X}' for c in tofu]} (draws as an empty box) — retype")
    n = len(spec.get("circles") or [])
    vision = (f"ONE call on check_sheet: name what each of the {n} detail picture(s) shows" if n else
              "none: a hero-only cover needs no vision call")
    for h in hits:
        print("HIT", h)
    print(json.dumps({"ok": not hits, "hits": hits, "notes": notes, "vision": vision}, ensure_ascii=False))
    return 0 if not hits else 1


if __name__ == "__main__":
    sys.exit(main())
