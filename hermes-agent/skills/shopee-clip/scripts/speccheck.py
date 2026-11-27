#!/usr/bin/env python3
"""Spec numbers: the listing title against what Fix's photos print.

keem-herm-loud-800a (2026-11-27): the listing title said "คีมเชื่อมลวด 800A", the product in Fix's first photo is
printed "300A ELECTRODE HOLDER". Hermes saw both (it searched "300A 800A") and still put 800A into the board, the
voiceover, a pill and the cover, and never told Fix — product-image-prep's "listing and the art disagree" rule says
keep the number out and say so. This module turns that rule into a gate:

  * spec_tokens(text)      -> {"A": {"800"}, "V": {"20"}} : a number + a unit (A V W kW mAh Ah Wh Nm rpm Hz GB TB,
                              Thai แอมป์ / โวลต์ / วัตต์ too). "999VF" / "2A2" (a letter or digit glued after the unit: a model code) is not a spec.
  * conflicts(title, imgs) -> per unit, the listing's values when NONE of them is printed on any photo while a photo
                              prints another value of that unit. A photo that prints both (a variant chart) = no
                              conflict; a unit only one side names = no conflict.
  * banned(conf, ok)       -> the tokens a clip may not say or show ("800A", "300A") unless Fix confirmed one.
  * hits(text, banned)     -> the banned tokens a text contains, digits or Thai words ("แปดร้อยแอมป์").

CLI (clipjob.py board / deliver run it; RapidOCR):
  uv run -q --with rapidocr-onnxruntime --with numpy --with pillow python speccheck.py scan --title "…" img1.jpg …
  uv run -q --with rapidocr-onnxruntime --with numpy --with pillow python speccheck.py ocr cover.jpg
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import thainum

UNIT_MAP = {"a": "A", "amp": "A", "amps": "A", "แอมป์": "A", "แอมแปร์": "A", "แอมป": "A",
            "v": "V", "volt": "V", "volts": "V", "โวลต์": "V", "โวลท์": "V",
            "w": "W", "watt": "W", "watts": "W", "วัตต์": "W", "kw": "KW",
            "mah": "MAH", "ah": "AH", "wh": "WH", "nm": "NM", "n.m": "NM", "n·m": "NM", "rpm": "RPM", "hz": "HZ",
            "gb": "GB", "tb": "TB"}
_UNITS = sorted(UNIT_MAP, key=len, reverse=True)
SPEC_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s?(" + "|".join(re.escape(u) for u in _UNITS)
                     + r")(?![A-Za-z0-9])", re.I)
THAI_UNIT = {"A": ("แอมป์", "แอมแปร์", "แอมป"), "V": ("โวลต์", "โวลท์"), "W": ("วัตต์",), "KW": ("กิโลวัตต์",),
             "MAH": ("มิลลิแอมป์",)}


def _num(s):
    v = float(s.replace(",", ""))
    return str(int(v)) if v == int(v) else f"{v:g}"


def spec_tokens(text):
    """{unit: {value}} of every number + unit in `text` (Thai digits read as Arabic)."""
    out = {}
    for m in SPEC_RE.finditer((text or "").translate(thainum.THAI_DIGITS)):
        out.setdefault(UNIT_MAP[m.group(2).lower()], set()).add(_num(m.group(1)))
    return out


def merge(*maps):
    out = {}
    for m in maps:
        for u, vs in m.items():
            out.setdefault(u, set()).update(vs)
    return out


def _near(v, tv):
    """A photo value of the same order as a listing value (300 vs 800, not a stray '2A' read off a charger)."""
    return any(float(t) > 0 and 0.1 <= float(v) / float(t) <= 10 for t in tv)


def conflicts(title, images):
    """title / images = spec_tokens maps -> {unit: {"listing": [...], "photos": [...]}}."""
    out = {}
    for u, tv in title.items():
        iv = {v for v in images.get(u) or set() if _near(v, tv)}
        if iv and not (tv & iv):
            out[u] = {"listing": sorted(tv), "photos": sorted(iv)}
    return out


def banned(conf, ok=()):
    """Tokens ("800A") of every conflicting unit, both sides, minus the ones Fix confirmed."""
    ok = {t.upper().replace(" ", "") for t in ok}
    out = set()
    for u, c in conf.items():
        for v in c["listing"] + c["photos"]:
            out.add(f"{v}{u}")
    return sorted(out - ok)


def _split(tok):
    m = re.match(r"^([\d.]+)([A-Z]+)$", tok)
    return (m.group(1), m.group(2)) if m else (None, None)


def hits(text, ban):
    """The banned tokens `text` contains, as digits + unit or as Thai number words + Thai unit."""
    if not ban or not text:
        return []
    have = {f"{v}{u}" for u, vs in spec_tokens(text).items() for v in vs}
    found = {t for t in ban if t in have}
    flat = re.sub(r"\s+", "", text)
    for t in ban:
        v, u = _split(t)
        if v is None or "." in v:
            continue
        words = thainum.int_to_thai(int(v))
        if any(words + w in flat for w in THAI_UNIT.get(u, ())) or any(f"{v}{w}" in flat for w in THAI_UNIT.get(u, ())):
            found.add(t)
    return sorted(found)


def describe(conf):
    return "; ".join(f"listing says {'/'.join(v + u for v in c['listing'])}, the photos print "
                     f"{'/'.join(v + u for v in c['photos'])}" for u, c in conf.items())


# ---------------------------------------------------------------- OCR (RapidOCR, in a uv env)
# a rating printed along a slanted product (keem img1: "300A ELECTRODE HOLDER" on the holder's barrel) reads only
# once the picture is turned: 0 deg found nothing, 30 / 45 / -45 read "300A" at 0.88-0.99
ANGLES = (0, 30, -30, 45, -45, 90)
MAX_SIDE = 1100


def ocr_text(path, ocr=None, angles=ANGLES):
    import tempfile

    from PIL import Image
    if ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()
    im = Image.open(path).convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    out = []
    with tempfile.TemporaryDirectory() as d:
        for a in angles:
            f = os.path.join(d, f"r{a}.png")
            (im.rotate(a, expand=True, fillcolor="white") if a else im).save(f)
            found, _ = ocr(f)
            out += [t for _, t, s in (found or []) if float(s) >= 0.5]
    return " ".join(out)


def scan(title, images):
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    per = {}
    for p in images:
        try:
            txt = ocr_text(p, ocr)
        except Exception as e:                       # an unreadable image is reported, never fatal
            per[p] = {"error": str(e)[:120]}
            continue
        per[p] = {u: sorted(v) for u, v in spec_tokens(txt).items()}
    imgs = merge(*({u: set(v) for u, v in d.items()} for d in per.values() if "error" not in d))
    conf = conflicts(spec_tokens(title), imgs)
    return {"title": {u: sorted(v) for u, v in spec_tokens(title).items()}, "images": per, "conflicts": conf}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["scan"]:
        i = argv.index("--title")
        title = argv[i + 1]
        imgs = [a for k, a in enumerate(argv[1:], 1) if k not in (i, i + 1)]
        print(json.dumps(scan(title, imgs), ensure_ascii=False))
        return 0
    if argv[:1] == ["ocr"]:                          # a rendered cover / frame: upright text only
        print(json.dumps({"text": ocr_text(argv[1], angles=(0,))}, ensure_ascii=False))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
