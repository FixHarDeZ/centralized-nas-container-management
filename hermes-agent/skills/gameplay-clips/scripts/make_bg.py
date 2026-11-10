#!/usr/bin/env python3
"""Build the 720x1280 background plate for a gameplay-style clip (v4 look).

Cover-fits the game key art, blurs/darkens it, then pastes transparent
illustrations above the gameplay window and along the bottom edge.
Usage:
  uv run python make_bg.py --art art.jpg --ill ill.png --strip strip.png --out bg.png
  --ill/--strip are optional; omit when the game has no usable RGBA art.
"""
import argparse
from PIL import Image, ImageFilter, ImageEnhance

W, H = 720, 1280

p = argparse.ArgumentParser()
p.add_argument("--art", required=True, help="game key art (any size, will cover-fit)")
p.add_argument("--ill", default=None, help="transparent illustration placed above the window")
p.add_argument("--strip", default=None, help="transparent strip pinned to the bottom edge")
p.add_argument("--ill-y", type=int, default=140)
p.add_argument("--ill-w", type=int, default=320)
p.add_argument("--out", default="bg.png")
args = p.parse_args()

bg = Image.open(args.art).convert("RGB")
scale = max(W / bg.width, H / bg.height)
bg = bg.resize((int(bg.width * scale) + 1, int(bg.height * scale) + 1), Image.LANCZOS)
left = (bg.width - W) // 2
top = (bg.height - H) // 2
bg = bg.crop((left, top, left + W, top + H))
bg = bg.filter(ImageFilter.GaussianBlur(radius=24))
bg = ImageEnhance.Brightness(bg).enhance(0.92)
bg = ImageEnhance.Color(bg).enhance(1.08)

scrim = Image.new("RGB", (W, H), (10, 12, 20))
bg = Image.blend(bg, scrim, 0.18)

if args.ill:
    ill = Image.open(args.ill).convert("RGBA")
    iw = args.ill_w
    ill = ill.resize((iw, int(ill.height * iw / ill.width)), Image.LANCZOS)
    bg.paste(ill, ((W - iw) // 2, args.ill_y), ill)

if args.strip:
    st = Image.open(args.strip).convert("RGBA")
    sw = W
    st = st.resize((sw, int(st.height * sw / st.width)), Image.LANCZOS)
    bg.paste(st, (0, H - st.height), st)

bg.save(args.out)
print(args.out, bg.size)
