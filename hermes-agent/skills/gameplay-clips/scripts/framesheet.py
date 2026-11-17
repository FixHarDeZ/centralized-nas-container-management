#!/usr/bin/env python3
"""framesheet.py — one labelled contact sheet from explicit frame times.

Run: uv run --with pillow python framesheet.py SRC "12.5,30.0,44.5" OUT.jpg \
         [--cols 6] [--width 360]

Extracts one frame per time from SRC (always pass the file you actually cut from —
helpers copied between jobs hardcode `trailer.mp4` and can silently sheet the wrong
source), labels each tile with its time from the code (never trust labels burned by
fps filters), and writes one sheet for one vision call. Run shopee-clip's vprep.py on
OUT before sending. Times are source-absolute; for a window-encoded master subtract
the -ss offset first. Tile index -> time comes from the times list you pass in.
"""
import argparse
import os
import subprocess

from PIL import Image, ImageDraw

ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("times", help="comma-separated seconds, e.g. 12.5,30.0,44.5")
ap.add_argument("out")
ap.add_argument("--cols", type=int, default=6)
ap.add_argument("--width", type=int, default=360)
a = ap.parse_args()

times = [float(t) for t in a.times.split(",") if t.strip()]
tiles = []
for i, t in enumerate(times):
    frame = f"_fs_{i}.png"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", a.src,
                    "-frames:v", "1", "-update", "1", frame], check=True)
    im = Image.open(frame).convert("RGB")
    os.remove(frame)
    im.thumbnail((a.width, a.width))
    tiles.append((t, im))

C = a.cols
R = (len(tiles) + C - 1) // C
tw, th = a.width + 10, a.width + 30
sheet = Image.new("RGB", (C * tw, R * th), "white")
d = ImageDraw.Draw(sheet)
for i, (t, im) in enumerate(tiles):
    x = (i % C) * tw + 5
    y = (i // C) * th + 22
    sheet.paste(im, (x, y))
    d.rectangle([x, y - 18, x + 90, y], fill="black")
    d.text((x + 3, y - 16), f"{t}s", fill="yellow")
sheet.save(a.out, quality=88)
print(f"src={a.src} tiles={len(tiles)} -> {a.out} {sheet.size}")
