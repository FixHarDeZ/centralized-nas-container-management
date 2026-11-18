#!/usr/bin/env python3
"""Poster-style posting cover (Fix 2026-11-17: "แนวนี้โอเคเลยเอาแบบนี้ … gen ปกแบบนี้ให้ทุกคลิป").

Usage:
  uv run --with pillow python make_poster_cover.py spec.json --out cover.jpg

A 1080x1920 JPG: blurred hero behind a rounded card that holds a Thai headline, an optional sub ribbon,
the hero photo (optional corner badge), 0-3 detail circles and a row of selling-point chips.
Recipe, where each picture and each word comes from, and the checks: references/poster-cover.md.

spec.json (paths are relative to the spec file):
  {"hero": "frame.jpg",                  # picture WITHOUT burned text: a raw shot frame, key art, a clean listing photo
   "hero_box": [x0, y0, x1, y1],         # optional crop of the hero, source pixels
   "hero_focus": [0.5, 0.42],            # optional: which part survives the cover-fit crop (0..1, 0..1)
   "title": ["น้ำหอมติดช่องแอร์", "แค่คลิป ก็หอม!"],   # 1-2 lines
   the last line takes the accent colour
   "sub": "เปลี่ยนกลิ่นอับในรถ ให้หอมสดชื่น",             # optional ribbon
   "badge": ["มี 2 สี", "ฟ้า / ดำ"],                    # optional sticker on the hero, 1-2 short lines
   "circles": [{"image": "img1.jpg", "box": [372, 262, 772, 662], "label": "แพ็กเกจสีฟ้า"},   # 0-3 detail slots
               {"image": "case.jpg", "shape": "card", "label": "ปกเกม"}],
   "chips": ["ติดช่องแอร์", "ดีไซน์คริสตัลใส"],          # 2-4
   "theme": "auto"}                      # auto = hue of the hero
   or blue|green|pink|purple|orange|red|teal|gold

Detail slots (Fix 2026-11-18: blurry / meaningless / cropped circles):
  shape "circle" (default) — a square-ish close-up of ONE detail. The source (after box + border trim) must be
    roughly square (w/h 0.8-1.25) and at least as many pixels as the circle shows (no upscaling): a 170 px crop of a
    720p frame is refused — take a listing detail photo instead.
  shape "card" — the WHOLE picture in a rounded rectangle at its own aspect (a game case, a pack, a box art);
    nothing is cut off. Also needs enough pixels.
  A uniform white/black border is trimmed off every picture first (listing photos and screenshots carry them).
  1-2 slots draw bigger than 3.

Every text shrinks to fit down to a floor size
one that still does not fit stops the run and names the
element (shorten it — nothing is ever clipped). Price / discount wording is refused like make_cover.py.
Thai needs Raqm shaping: the run stops when Pillow has none (tone marks would be dropped silently).
"""
import argparse
import colorsys
import json
import math
import os
import re
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, features

W, H = 1080, 1920
PX, PY, PW, PH = 90, 150, 900, 1600          # the card
PAD = 40
FONT = os.environ.get("POSTER_FONT") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "gameplay-clips", "fonts", "Itim-Regular.ttf")
HUES = {"blue": 0.60, "green": 0.36, "pink": 0.92, "purple": 0.75, "orange": 0.07, "red": 0.99, "teal": 0.50, "gold": 0.12}
YEL, WHITE = (255, 214, 92), (255, 255, 255)
BANNED = [
    re.compile(r"\d[\d,.\s]*\s*(%|฿|\$|€|£|¥|baht|thb|บาท|usd)", re.I),
    re.compile(r"[%฿$€£¥]"),
    re.compile(r"\b(price[sd]?|pricing|sale|sales|off|baht|thb|discount|promo|cheap(er|est)?|deal|free)\b", re.I),
    re.compile(r"(ราคา|บาท|ลด|ส่วนลด|โปร|แถม|ฟรี|ถูกสุด|คูปอง)"),
]


class Bad(Exception):
    pass


def font(sz):
    return ImageFont.truetype(FONT, sz, layout_engine=ImageFont.Layout.RAQM)


_probe = ImageDraw.Draw(Image.new("RGB", (8, 8)))


def width(s, sz, stroke=0):
    return _probe.textlength(s, font=font(sz)) + 2 * stroke


def fit_size(s, maxw, start, floor, what, stroke_ratio=0.0):
    """Largest size in [floor, start] at which `s` is no wider than maxw."""
    for sz in range(start, floor - 1, -2):
        if width(s, sz, round(sz * stroke_ratio)) <= maxw:
            return sz
    raise Bad(f"{what} does not fit: '{s}' is wider than {maxw} px even at {floor} px — shorten it")


def check_text(s, what):
    if not isinstance(s, str) or not s.strip():
        raise Bad(f"{what} is empty")
    for rx in BANNED:
        m = rx.search(s)
        if m:
            raise Bad(f"REFUSED {what}: '{s}' contains price/discount wording ({m.group(0)!r}) — house rule")


def cover_fit(im, w, h, cx=0.5, cy=0.5):
    s = max(w / im.width, h / im.height)
    r = im.resize((max(w, round(im.width * s)), max(h, round(im.height * s))), Image.LANCZOS)
    x, y = round((r.width - w) * cx), round((r.height - h) * cy)
    return r.crop((x, y, x + w, y + h))


def crop_box(im, box, what):
    if box is None:
        return im
    if len(box) != 4:
        raise Bad(f"{what}: box must be [x0, y0, x1, y1]")
    x0, y0, x1, y1 = (int(v) for v in box)
    if not (0 <= x0 < x1 <= im.width and 0 <= y0 < y1 <= im.height):
        raise Bad(f"{what}: box {box} is outside the {im.width}x{im.height} image")
    return im.crop((x0, y0, x1, y1))


def trim_border(im, tol=18):
    """Drop a uniform near-white or near-black frame (a listing photo's padding, a screenshot's bar).
    Only a border whose colour is near white or near black is cut; a coloured edge is picture."""
    for edge in ((255, 255, 255), (0, 0, 0)):
        corners = [im.getpixel(p) for p in ((0, 0), (im.width - 1, 0), (0, im.height - 1), (im.width - 1, im.height - 1))]
        if not any(max(abs(a - b) for a, b in zip(c, edge)) <= tol for c in corners):
            continue
        diff = ImageChops.difference(im, Image.new("RGB", im.size, edge)).convert("L").point(lambda v: 255 if v > tol else 0)
        bb = diff.getbbox()
        if bb and (bb[2] - bb[0]) * (bb[3] - bb[1]) >= 0.25 * im.width * im.height:
            im = im.crop(bb)
    return im


def need_pixels(im, w, h, what):
    """Refuse a picture shown bigger than it is (upscaled = mush)."""
    if im.width < 0.9 * w or im.height < 0.9 * h:
        raise Bad(f"{what} is too small: {im.width}x{im.height} px shown at {round(w)}x{round(h)} would be upscaled "
                  f"(blurry) — use a bigger box or a higher-resolution picture (a listing detail photo)")


def contain(im, w, h):
    s = min(w / im.width, h / im.height)
    return im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)


def rounded(im, rad):
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, im.width, im.height), rad, fill=255)
    im = im.convert("RGBA")
    im.putalpha(m)
    return im


def shadow(base, box, rad, blur=14, off=8, colour=(10, 30, 60, 110)):
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle((box[0], box[1] + off, box[2], box[3] + off), rad, fill=colour)
    base.alpha_composite(sh.filter(ImageFilter.GaussianBlur(blur)))


def hero_hue(im):
    """Mean hue of the saturated pixels (circular mean)
    None for a grey picture."""
    small = im.resize((64, 64)).convert("HSV")
    sx = sy = n = 0.0
    raw = small.tobytes()
    for h, s, v in zip(raw[0::3], raw[1::3], raw[2::3]):
        if s > 70 and v > 60:
            a = h / 255 * 2 * math.pi
            sx += math.cos(a) * s
            sy += math.sin(a) * s
            n += s
    if n < 64 * 64 * 0.04 * 70:
        return None
    return (math.atan2(sy, sx) / (2 * math.pi)) % 1.0


def palette(theme, hero):
    if theme in (None, "auto"):
        hue = hero_hue(hero)
        hue = HUES["blue"] if hue is None else hue
    elif theme in HUES:
        hue = HUES[theme]
    else:
        raise Bad(f"theme '{theme}' unknown: auto or one of {', '.join(sorted(HUES))}")
    def rgb(lum, sat):
        return tuple(round(c * 255) for c in colorsys.hls_to_rgb(hue, lum, sat))

    return {"dark": rgb(0.26, 0.62), "mid": rgb(0.53, 0.62), "top": rgb(0.95, 0.9), "bottom": rgb(0.78, 0.8)}


def chip_rows(chips, maxw):
    """-> (font size, rows of (text, width)). One row when it fits at >=30 px, else two."""
    for nrows in (1, 2):
        for sz in range(40, 28, -2):
            ws = [width(c, sz) + 92 for c in chips]
            if max(ws) > maxw:
                continue
            rows, cur, used = [], [], 0
            for c, w in zip(chips, ws):
                if cur and used + 18 + w > maxw:
                    rows.append(cur)
                    cur, used = [], 0
                used += w + (18 if cur else 0)
                cur.append((c, w))
            rows.append(cur)
            if len(rows) <= nrows:
                return sz, rows
    raise Bad(f"chips do not fit in two rows of {maxw} px: {chips} — shorten them or drop one")


def build(spec, base="."):
    if not features.check("raqm"):
        raise Bad("Pillow has no Raqm here: Thai tone marks would be dropped. Run inside the Hermes container "
                  "(uv run --with pillow) — never on a machine without libraqm")
    def path(p):
        return p if os.path.isabs(p) else os.path.join(base, p)

    title = spec.get("title") or []
    title = [title] if isinstance(title, str) else list(title)
    if not 1 <= len(title) <= 2:
        raise Bad("title needs 1 or 2 lines")
    sub, badge = spec.get("sub"), spec.get("badge")
    badge = [badge] if isinstance(badge, str) else list(badge or [])
    circles, chips = list(spec.get("circles") or []), list(spec.get("chips") or [])
    if len(badge) > 2:
        raise Bad("badge takes at most 2 lines")
    if len(circles) > 3:
        raise Bad("at most 3 circles")
    if not 2 <= len(chips) <= 4:
        raise Bad("chips: 2 to 4 selling points")
    for i, t in enumerate(title):
        check_text(t, f"title line {i + 1}")
    if sub is not None:
        check_text(sub, "sub")
    for i, t in enumerate(badge):
        check_text(t, f"badge line {i + 1}")
    for i, c in enumerate(circles):
        check_text(c.get("label"), f"circle {i + 1} label")
    for i, t in enumerate(chips):
        check_text(t, f"chip {i + 1}")
    if not spec.get("hero"):
        raise Bad("spec needs a hero image")
    for i, c in enumerate(circles):
        if c.get("shape", "circle") not in ("circle", "card"):
            raise Bad(f"circle {i + 1}: shape must be 'circle' or 'card', not {c.get('shape')!r}")
    hero = trim_border(crop_box(Image.open(path(spec["hero"])).convert("RGB"), spec.get("hero_box"), "hero_box"))
    fx, fy = spec.get("hero_focus") or (0.5, 0.42)
    pal = palette(spec.get("theme"), hero)
    DARK, MID = pal["dark"], pal["mid"]
    inner = PW - 2 * PAD

    # ---- measure everything first: the hero takes what is left
    tsz = [fit_size(t, inner, 124 if i == len(title) - 1 and len(title) > 1 else 108, 60, f"title line {i + 1}", 0.09)
           for i, t in enumerate(title)]
    ssz = fit_size(sub, inner - 68, 46, 32, "sub") if sub else 0
    csz, rows = chip_rows(chips, PW - 24)
    n = len(circles)
    R = {1: 170, 2: 160}.get(n, 122)              # 1-2 detail slots draw bigger
    step = {2: 380, 3: 285}.get(n, 0)             # centre-to-centre
    slot_w = {1: 640, 2: 360, 3: 262}.get(n, 0)   # widest a card may be
    lsz = [fit_size(c["label"], slot_w if n == 1 else 2 * R + 30, 40, 32, f"circle {i + 1} label")
           for i, c in enumerate(circles)]
    slots = []                                    # (shape, picture ready to paste)
    for i, c in enumerate(circles):
        what = f"circle {i + 1} ('{c['label']}')"
        src = trim_border(crop_box(Image.open(path(c["image"])).convert("RGB"), c.get("box"), what))
        if c.get("shape", "circle") == "circle":
            ratio = src.width / src.height
            if not 0.8 <= ratio <= 1.25:
                raise Bad(f"{what}: a circle needs a square-ish picture, this one is {src.width}x{src.height} "
                          f"(w/h {ratio:.2f}) and the circle would cut most of it off — give a square box around the "
                          f"detail, or \"shape\": \"card\" to show the whole picture")
            need_pixels(src, 2 * R, 2 * R, what)
            im = cover_fit(src, 2 * R, 2 * R).convert("RGBA")
            m = Image.new("L", (2 * R, 2 * R), 0)
            ImageDraw.Draw(m).ellipse((0, 0, 2 * R, 2 * R), fill=255)
            im.putalpha(m)
            slots.append(("circle", im))
        else:
            dw = min(slot_w, 2 * R * src.width / src.height)
            dh = dw * src.height / src.width
            need_pixels(src, dw, dh, what)
            slots.append(("card", rounded(contain(src, dw, dh), 24)))
    bsz = [fit_size(t, 260, 54 if i == 0 else 42, 30, f"badge line {i + 1}") for i, t in enumerate(badge)]
    y = 28
    title_y = []
    for sz in tsz:
        title_y.append(y + round(sz * 0.62))
        y += round(sz * 1.2)
    sub_y = None
    if sub:
        sub_y = y + 6
        y = sub_y + 68
    hero_top = y + 22
    chips_h = len(rows) * 78 + (len(rows) - 1) * 14
    chips_y = PH - 52 - chips_h
    circ_cy = chips_y - 56 - 44 - R if circles else None
    hero_bot = (circ_cy - R - 26) if circles else (chips_y - 40)
    if hero_bot - hero_top < 420:
        raise Bad(f"only {hero_bot - hero_top} px left for the hero photo — drop a title line, the sub or the circles")

    # ---- paint
    bg = cover_fit(hero, W, H, fx, fy).filter(ImageFilter.GaussianBlur(28)).convert("RGBA")
    bg.alpha_composite(Image.new("RGBA", (W, H), (*(c // 3 for c in DARK), 95)))
    shadow(bg, (PX, PY, PX + PW, PY + PH), 44, 30, 16, (0, 0, 0, 150))
    grad = Image.new("RGB", (1, PH))
    for gy in range(PH):
        t = gy / PH
        grad.putpixel((0, gy), tuple(round(a + (b - a) * t) for a, b in zip(pal["top"], pal["bottom"])))
    card = grad.resize((PW, PH)).convert("RGBA")
    hb = (PAD, hero_top, PW - PAD, hero_bot)
    shadow(card, hb, 36)
    card.alpha_composite(rounded(cover_fit(hero, hb[2] - hb[0], hb[3] - hb[1], fx, fy), 36), hb[:2])
    d = ImageDraw.Draw(card)
    d.rounded_rectangle(hb, 36, outline=WHITE, width=8)
    soft = (*DARK, 140)
    for i, (t, sz, ty) in enumerate(zip(title, tsz, title_y)):
        f, sw = font(sz), round(sz * 0.09)
        fill = YEL if (i == len(title) - 1 and len(title) > 1) else WHITE
        d.text((PW // 2 + 4, ty + 6), t, font=f, fill=soft, anchor="mm", stroke_width=sw, stroke_fill=soft)
        d.text((PW // 2, ty), t, font=f, fill=fill, anchor="mm", stroke_width=sw, stroke_fill=DARK)
    if sub:
        tw = width(sub, ssz)
        d.rounded_rectangle((PW / 2 - tw / 2 - 34, sub_y, PW / 2 + tw / 2 + 34, sub_y + 68), 34, fill=DARK)
        d.text((PW // 2, sub_y + 32), sub, font=font(ssz), fill=WHITE, anchor="mm")
    if badge:
        bw = max(width(t, sz) for t, sz in zip(badge, bsz)) + 56
        bh = 36 + sum(round(sz * 1.15) for sz in bsz)
        sb = (hb[2] - bw + 14, hb[1] + 24, hb[2] + 14, hb[1] + 24 + bh)
        shadow(card, sb, 30, 10, 6)
        d = ImageDraw.Draw(card)
        d.rounded_rectangle(sb, 30, fill=YEL, outline=DARK, width=6)
        by = sb[1] + 18
        for t, sz in zip(badge, bsz):
            d.text(((sb[0] + sb[2]) // 2, by + round(sz * 0.55)), t, font=font(sz), fill=DARK, anchor="mm")
            by += round(sz * 1.15)
    for i, (c, sz, (shape, im)) in enumerate(zip(circles, lsz, slots)):
        cx = PW // 2 + round((i - (n - 1) / 2) * step)
        if shape == "circle":
            shadow(card, (cx - R, circ_cy - R, cx + R, circ_cy + R), R)
            card.alpha_composite(im, (cx - R, circ_cy - R))
            d = ImageDraw.Draw(card)
            d.ellipse((cx - R, circ_cy - R, cx + R, circ_cy + R), outline=WHITE, width=9)
            d.ellipse((cx - R - 5, circ_cy - R - 5, cx + R + 5, circ_cy + R + 5), outline=MID, width=4)
        else:
            x0, y0 = cx - im.width // 2, circ_cy + R - im.height     # bottom-aligned, label sits on its foot
            box = (x0, y0, x0 + im.width, y0 + im.height)
            shadow(card, box, 24)
            card.alpha_composite(im, (x0, y0))
            d = ImageDraw.Draw(card)
            d.rounded_rectangle(box, 24, outline=WHITE, width=8)
            d.rounded_rectangle((box[0] - 5, box[1] - 5, box[2] + 5, box[3] + 5), 28, outline=MID, width=4)
        tw = width(c["label"], sz)
        d.rounded_rectangle((cx - tw / 2 - 20, circ_cy + R - 14, cx + tw / 2 + 20, circ_cy + R + 44), 28,
                            fill=WHITE, outline=MID, width=4)
        d.text((cx, circ_cy + R + 14), c["label"], font=font(sz), fill=DARK, anchor="mm")
    cy = chips_y
    for row in rows:
        x = (PW - sum(w for _, w in row) - 18 * (len(row) - 1)) / 2
        for t, w in row:
            d.rounded_rectangle((x, cy, x + w, cy + 78), 39, fill=WHITE, outline=DARK, width=4)
            d.ellipse((x + 14, cy + 14, x + 64, cy + 64), fill=MID)
            d.line((x + 27, cy + 40, x + 36, cy + 50, x + 52, cy + 29), fill=WHITE, width=6, joint="curve")
            d.text((x + 74, cy + 37), t, font=font(csz), fill=DARK, anchor="lm")
            x += w + 18
        cy += 78 + 14
    bg.alpha_composite(rounded(card, 44), (PX, PY))
    ImageDraw.Draw(bg).rounded_rectangle((PX, PY, PX + PW, PY + PH), 44, outline=WHITE, width=6)
    return bg.convert("RGB")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    try:
        with open(a.spec, encoding="utf-8") as f:
            spec = json.load(f)
        img = build(spec, os.path.dirname(os.path.abspath(a.spec)))
    except (Bad, OSError, ValueError, KeyError, TypeError) as e:
        print(f"make_poster_cover: {e}", file=sys.stderr)
        return 1
    img.save(a.out, quality=92)
    print(json.dumps({"ok": True, "out": os.path.abspath(a.out), "size": list(img.size)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
