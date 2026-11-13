#!/usr/bin/env python3
"""Shrink images before vision_analyze. A 4 MB PNG sheet costs the upload and buys no accuracy.

Usage: uv run --with pillow python vprep.py IMG [IMG ...] [--max 1600] [--quality 82]
Writes <name>.v.jpg next to each input (longest side <= --max, JPEG) and prints one line per file.
Send the .v.jpg to vision. An input that is already a small JPEG is copied through unchanged.
"""
import argparse
import os
import shutil
import sys

SMALL = 600 * 1024


def out_path(path):
    return os.path.splitext(path)[0] + ".v.jpg"


def prep(path, max_side=1600, quality=82):
    from PIL import Image
    dst = out_path(path)
    with Image.open(path) as im:
        w, h = im.size
        if im.format == "JPEG" and max(w, h) <= max_side and os.path.getsize(path) <= SMALL:
            shutil.copyfile(path, dst)
            return dst, (w, h)
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side), Image.LANCZOS)
        im.save(dst, "JPEG", quality=quality, optimize=True)
        return dst, im.size


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--max", type=int, default=1600)
    ap.add_argument("--quality", type=int, default=82)
    a = ap.parse_args(argv)
    for p in a.images:
        dst, (w, h) = prep(p, a.max, a.quality)
        print(f"{dst} {w}x{h} {os.path.getsize(p) // 1024} KB -> {os.path.getsize(dst) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
