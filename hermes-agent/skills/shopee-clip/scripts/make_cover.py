#!/usr/bin/env python3
"""Cover / thumbnail generator for 9:16 Shopee clips.

Usage:
  uv run --with pillow --with numpy python make_cover.py \
      --video out.mp4 --t auto --text "OPEN WORLD" [--sub "Link below"] --out cover.jpg

- Prefer a source WITHOUT burned subs/pills when one exists (e.g. the pre-ass concat);
  out.mp4 works but its own captions show through.
- --t SECONDS or 'auto' (sample --samples frames over --range, default 5%..80% = skip CTA tail, score =
  Laplacian variance (sharpness) x mean HSV saturation (colour), dark frames penalised).
- Output 1080x1920 JPG: source frame upscaled with LANCZOS + mild UnsharpMask.
- Big Fredoka-SemiBold EN text (<=3 words) with thick dark stroke on a pastel rounded box,
  placed inside the all-platform safe zone (gameplay-clips/references/safe-zones.md):
  clear box x 120..888, y 288..1248 on 1080x1920 (never top 14% / bottom 35%).
  --cy auto puts the title (+ --sub) on the band with least detail + least skin tone
  (blurred bg / wall, not faces or gameplay). Titles stay on one line when they fit at >=60% size.
  --sub is put above or below the title, whichever side covers less. 2-line titles are capped
  at ~68% size (~300 px box). Gameplay layout (window y~480..1088 of 1920): only ~190 px of
  safe area sits above the window, so skip --sub (or use a 1-word title) to keep faces clear.
  Faces are found by a YCbCr skin heuristic only (no face detector) — vision-check the result.
- Refuses price/discount wording (house rule): digits+currency/%, any %, currency symbols,
  and the words price/sale/off/baht/discount/promo/cheap (+ Thai ราคา/บาท/ลด/ส่วนลด).
"""
import argparse, io, re, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1080, 1920
SAFE_X0, SAFE_X1 = 120, 888          # YT right reserve 192, TikTok left 120
SAFE_Y0, SAFE_Y1 = 288, 1248         # YT top 15%, Meta/YT bottom 35%
FONT = "/opt/data/skills/gameplay-clips/fonts/FredokaSB-Static.ttf"   # static wght 600; the variable Fredoka-SemiBold.ttf loads its DEFAULT (lighter) instance in PIL
PASTELS = {"pink": (255, 143, 177), "yellow": (255, 209, 102), "green": (138, 201, 38),
           "purple": (122, 92, 255), "blue": (120, 190, 255)}
STROKE = (58, 26, 48)

BANNED = [
    re.compile(r"\d[\d,.\s]*\s*(%|฿|\$|€|£|¥|baht|thb|บาท|usd)", re.I),
    re.compile(r"[%฿$€£¥]"),
    re.compile(r"\b(price[sd]?|pricing|sale|sales|off|baht|thb|discount|promo|cheap(er|est)?|deal|free)\b", re.I),
    re.compile(r"(ราคา|บาท|ลด|ส่วนลด|โปร)"),
]


def check_text(s, label, max_words):
    if s is None:
        return
    for rx in BANNED:
        m = rx.search(s)
        if m:
            sys.exit(f"REFUSED {label}: '{s}' contains price/discount wording ({m.group(0)!r}) — house rule")
    if re.search(r"[^\x00-\x7F]", s):
        sys.exit(f"REFUSED {label}: '{s}' must be EN/ASCII only")
    n = len(s.split())
    if n == 0 or n > max_words:
        sys.exit(f"REFUSED {label}: '{s}' has {n} words (max {max_words})")


def duration(video):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                          "-of", "default=nw=1:nk=1", video], capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def grab(video, t):
    r = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
                        "-f", "image2pipe", "-vcodec", "png", "-"], capture_output=True, check=True)
    if not r.stdout:
        raise RuntimeError(f"no frame at {t}")
    return Image.open(io.BytesIO(r.stdout)).convert("RGB")


def score(img):
    small = img.resize((360, 640), Image.BILINEAR)
    g = np.asarray(small.convert("L"), dtype=np.float32)
    lap = (-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    sharp = float(lap.var())
    sat = float(np.asarray(small.convert("HSV"), dtype=np.float32)[..., 1].mean()) / 255.0
    lum = float(g.mean()) / 255.0
    dark = 1.0 if lum > 0.18 else lum / 0.18          # penalise near-black / fade frames
    return sharp * (0.15 + sat) * dark, sharp, sat, lum


def pick_auto(video, n, lo, hi):
    d = duration(video)
    best = None
    for i in range(n):
        t = d * (lo + (hi - lo) * i / max(1, n - 1))
        try:
            img = grab(video, t)
        except Exception:
            continue
        s, sh, sa, lu = score(img)
        print(f"  t={t:6.2f}  score={s:9.1f}  lapvar={sh:8.1f}  sat={sa:.2f}  lum={lu:.2f}")
        if best is None or s > best[0]:
            best = (s, t, img)
    if best is None:
        sys.exit("no frames could be sampled")
    print(f"auto pick t={best[1]:.2f}")
    return best[1], best[2]


def detail_map(img):
    g = np.asarray(img.convert("L").resize((W // 4, H // 4), Image.BILINEAR), dtype=np.float32)
    lap = np.zeros_like(g)
    lap[1:-1, 1:-1] = np.abs(-4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:])
    return lap


def skin_map(img):
    """Rough YCbCr skin mask (1 = skin-like). Faces are smooth, so detail alone puts
    the title right on them; this term pushes it off faces/hands."""
    small = img.resize((W // 4, H // 4), Image.BILINEAR)
    ycc = np.asarray(small.convert("YCbCr"), dtype=np.float32)
    rgb = np.asarray(small, dtype=np.float32)
    y, cb, cr = ycc[..., 0], ycc[..., 1], ycc[..., 2]
    # tight range + R clearly above B: rejects beige walls / lavender knit that the loose range caught
    return ((y > 80) & (cb > 85) & (cb < 120) & (cr > 142) & (cr < 170)
            & (rgb[..., 0] - rgb[..., 2] > 25)).astype(np.float32)


def band_cost(lap, skin, cy, h):
    x0, x1 = SAFE_X0 // 4, SAFE_X1 // 4
    y0, y1 = max(0, int((cy - h / 2) / 4)), min(H // 4, int((cy + h / 2) / 4))
    if y1 <= y0:
        return 1e9
    det = float(lap[y0:y1, x0:x1].mean())
    sk = float(skin[y0:y1, x0:x1].mean())
    return (det + 120.0 * sk) * (1 + 0.6 * abs(cy / H - 0.40)), det, sk


def auto_cy(img, block_h):
    """Centre y (inside the safe zone) of the band with least detail + least skin for a
    block of height block_h: title (and sub) go on blurred bg / plain wall, not faces/gameplay.
    Slight bias toward 0.40*H."""
    lap, skin = detail_map(img), skin_map(img)
    lo, hi = SAFE_Y0 + block_h / 2, SAFE_Y1 - block_h / 2
    best = None
    for cy in np.linspace(lo, max(lo, hi), 24):
        cost, det, sk = band_cost(lap, skin, cy, block_h)
        print(f"  cy={cy:6.0f} ({cy / H:.2f})  detail={det:6.2f}  skin={sk:.2f}  cost={cost:6.2f}")
        if best is None or cost < best[0]:
            best = (cost, cy)
    return best[1]


def fit_lines(draw, words, max_w, size_hi, size_lo, stroke_ratio, two_cap=0.68):
    """Return (font, lines, stroke). Prefer ONE line down to ~60% of size_hi (a short
    box hides less of the frame); otherwise 2 lines, capped at two_cap*size_hi so a
    2-line title stays ~300 px tall instead of covering half the frame."""
    one_floor = max(size_lo, int(size_hi * 0.6))
    def try_(size, cands):
        f = ImageFont.truetype(FONT, size)
        sw = max(4, int(size * stroke_ratio))
        for lines in cands:
            if all(draw.textbbox((0, 0), ln, font=f, stroke_width=sw)[2] <= max_w for ln in lines):
                return f, lines, sw
    one = [[" ".join(words)]]
    two = [[" ".join(words[:k]), " ".join(words[k:])] for k in range(1, len(words))]
    for size in range(size_hi, one_floor - 1, -4):
        r = try_(size, one)
        if r:
            return r
    for size in range(max(size_lo, int(size_hi * two_cap)), size_lo - 1, -4):
        r = try_(size, one + two)
        if r:
            return r
    f = ImageFont.truetype(FONT, size_lo)
    return f, [" ".join(words)], max(4, int(size_lo * stroke_ratio))


class Block:
    """Measured text block; line height = real glyph bbox (caps have no empty ascender gap)."""
    def __init__(self, text, size_hi, size_lo, max_w, pad_x, pad_y, stroke_ratio):
        d = ImageDraw.Draw(Image.new("RGB", (8, 8)))
        self.f, self.lines, self.sw = fit_lines(d, text.split(), max_w - 2 * pad_x, size_hi, size_lo, stroke_ratio)
        ref = d.textbbox((0, 0), "HXg" if any(c.islower() for c in text) else "HX", font=self.f, stroke_width=self.sw)
        self.top, self.lh = ref[1], ref[3] - ref[1]
        self.gap = int(self.lh * 0.12)
        self.widths = [d.textbbox((0, 0), ln, font=self.f, stroke_width=self.sw)[2] for ln in self.lines]
        self.pad_x, self.pad_y = pad_x, pad_y
        self.w = max(self.widths) + 2 * pad_x
        self.h = len(self.lines) * self.lh + (len(self.lines) - 1) * self.gap + 2 * pad_y


def draw_block(base, blk, cy, color, radius, alpha=235):
    ov = Image.new("RGBA", base.size, (0, 0, 0, 0))
    bw, bh = blk.w, blk.h
    x0, y0 = W // 2 - bw // 2, int(cy - bh / 2)
    x0 = max(SAFE_X0, min(x0, SAFE_X1 - bw))
    y0 = max(SAFE_Y0, min(y0, SAFE_Y1 - bh))
    sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).rounded_rectangle([x0 + 8, y0 + 12, x0 + bw + 8, y0 + bh + 12], radius, fill=(0, 0, 0, 110))
    ov = Image.alpha_composite(ov, sh.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(ov)
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius, fill=color + (alpha,), outline=STROKE + (255,), width=max(4, blk.sw // 2))
    y = y0 + blk.pad_y
    for ln, wd in zip(blk.lines, blk.widths):
        d.text((x0 + (bw - wd) // 2, y - blk.top), ln, font=blk.f, fill=(255, 255, 255, 255),
               stroke_width=blk.sw, stroke_fill=STROKE + (255,))
        y += blk.lh + blk.gap
    return Image.alpha_composite(base, ov), (x0, y0, x0 + bw, y0 + bh)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--video", required=True)
    ap.add_argument("--t", default="auto")
    ap.add_argument("--samples", type=int, default=24)
    ap.add_argument("--text", required=True, help="EN, <=3 words")
    ap.add_argument("--sub", default=None, help="optional small EN line (<=4 words)")
    ap.add_argument("--color", default="pink", choices=sorted(PASTELS))
    ap.add_argument("--cy", default="auto", help="'auto' (least-detail band in safe zone) or fraction of H for the main text centre")
    ap.add_argument("--range", default="0.05,0.80", help="auto-t sampling window as fractions of duration (default skips the CTA tail)")
    ap.add_argument("--guides", action="store_true", help="also write <out>_guides.jpg with safe-zone bands")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    check_text(a.text, "--text", 3)
    check_text(a.sub, "--sub", 4)

    if a.t == "auto":
        lo, hi = (float(x) for x in a.range.split(","))
        t, img = pick_auto(a.video, a.samples, lo, hi)
    else:
        t = float(a.t)
        img = grab(a.video, t)
    img = img.resize((W, H), Image.LANCZOS).filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))

    max_w = SAFE_X1 - SAFE_X0 - 2 * 24   # breathing room inside the safe box
    main = Block(a.text.upper(), 190, 88, max_w, pad_x=44, pad_y=30, stroke_ratio=0.085)
    sub = Block(a.sub, 72, 44, max_w, pad_x=30, pad_y=16, stroke_ratio=0.06) if a.sub else None
    GAP = 28
    total = main.h + (GAP + sub.h if sub else 0)
    bc = auto_cy(img, total) if a.cy == "auto" else float(a.cy) * H
    bc = max(SAFE_Y0 + total / 2, min(SAFE_Y1 - total / 2, bc))
    sub_above = False
    if sub:
        # sub goes on whichever side of the title covers less detail/skin
        lap, skin = detail_map(img), skin_map(img)
        top = bc - total / 2
        below = band_cost(lap, skin, top + main.h + GAP + sub.h / 2, sub.h)[0]
        above = band_cost(lap, skin, top + sub.h / 2, sub.h)[0]
        sub_above = above < below
    top = bc - total / 2
    main_cy = top + (sub.h + GAP if sub_above else 0) + main.h / 2
    print(f"block centre y={bc:.0f} ({bc / H:.2f})  main {main.w}x{main.h} lines={main.lines}"
          + (f"  sub {'above' if sub_above else 'below'}" if sub else ""))
    base = img.convert("RGBA")
    base, box = draw_block(base, main, main_cy, PASTELS[a.color], radius=48, alpha=248)
    if sub:
        sub_cy = box[1] - GAP - sub.h / 2 if sub_above else box[3] + GAP + sub.h / 2
        base, sbox = draw_block(base, sub, sub_cy, (40, 24, 40), radius=34, alpha=200)
        if not (sbox[3] <= box[1] or sbox[1] >= box[3]):
            sys.exit("layout error: sub overlaps main text")
    out = base.convert("RGB")
    out.save(a.out, "JPEG", quality=92, optimize=True)
    print(f"wrote {a.out} {out.size} from t={t:.2f}s main_box={box}")

    if a.guides:
        g = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        gd = ImageDraw.Draw(g)
        red = (255, 0, 0, 90)
        gd.rectangle([0, 0, W, SAFE_Y0], fill=red); gd.rectangle([0, SAFE_Y1, W, H], fill=red)
        gd.rectangle([0, SAFE_Y0, SAFE_X0, SAFE_Y1], fill=red); gd.rectangle([SAFE_X1, SAFE_Y0, W, SAFE_Y1], fill=red)
        gp = a.out.rsplit(".", 1)[0] + "_guides.jpg"
        Image.alpha_composite(out.convert("RGBA"), g).convert("RGB").save(gp, quality=85)
        print(f"wrote {gp}")


if __name__ == "__main__":
    main()
