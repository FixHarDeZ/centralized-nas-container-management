#!/usr/bin/env python3
"""hero_pick.py — pick the poster-cover hero frame by measurement, no vision call.

  uv run --with numpy --with pillow python hero_pick.py <raw shot or trailer.mp4> [--times 1.5,2.5,5.5] \
      [--n 8] [--out hero.jpg] [--sheet cand.jpg]
  -> one row per candidate (time, sharpness, skin, verdict) + JSON on the last line; the winner is written
     to --out (full resolution). Exit 0 = picked, 1 = every candidate was blank / dark / a white flash,
     2 = unreadable video.

Why (2026-11-23): the cover pick was the slowest vision call of the day — pepita cover_pick 390 s, zelda
hero_grid 420 s timeout, ps5 cover_sheet 420 s timeout — and the grid read only chooses a letter. The
rule Hermes wrote into poster-cover.md the same day is the measurement: sharpest frame wins (Laplacian
variance of the grey frame), and among frames within TIE of the sharpest the LOWEST skin share wins
(less face, more product). The cover's single `check_sheet` vision call still validates the result.

--times: the moments the frame check named as product-forward (raw-shot seconds). Default: --n times
spread over the clip, 0.3 s off both ends. Frames with mean luma < DARK or a white flash (mean > 225,
std < 12, the windows.py rule) never win.
"""
import argparse
import json
import os
import subprocess
import sys

import numpy as np
from PIL import Image

TIE = 0.85          # within 85 % of the sharpest = tied on sharpness
DARK = 25.0
WASH_MEAN, WASH_STD = 225.0, 12.0
EDGE = 0.3


def probe_dur(src):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
                         capture_output=True, text=True)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def grab(src, t, out):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1",
                    "-q:v", "2", out], check=True)
    return Image.open(out).convert("RGB")


def sharpness(grey):
    """Variance of the 4-neighbour Laplacian on a 360-px-wide grey frame (scale-independent enough)."""
    g = grey.astype(np.float32)
    lap = -4 * g[1:-1, 1:-1] + g[:-2, 1:-1] + g[2:, 1:-1] + g[1:-1, :-2] + g[1:-1, 2:]
    return float(lap.var())


def skin(rgb):
    """Share of skin pixels (YCrCb, facecheck.py / pillclear.py thresholds)."""
    a = rgb.astype(np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    cr = 128 + 0.5 * r - 0.4187 * g - 0.0813 * b
    cb = 128 - 0.1687 * r - 0.3313 * g + 0.5 * b
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    return float(((cr > 135) & (cr < 175) & (cb > 85) & (cb < 128) & (luma > 90)).mean())


def score(im):
    small = im.resize((360, round(360 * im.height / im.width)))
    rgb = np.asarray(small)
    grey = np.asarray(small.convert("L"), dtype=np.float32)
    m, sd = float(grey.mean()), float(grey.std())
    bad = "dark" if m < DARK else ("flash" if m > WASH_MEAN and sd < WASH_STD else "")
    return {"sharp": round(sharpness(grey), 1), "skin": round(skin(rgb), 3), "luma": round(m, 1), "bad": bad}


def rank(rows):
    """rows: dicts with sharp/skin/bad. -> index of the winner or None."""
    ok = [i for i, r in enumerate(rows) if not r["bad"]]
    if not ok:
        return None
    top = max(rows[i]["sharp"] for i in ok)
    tied = [i for i in ok if rows[i]["sharp"] >= TIE * top]
    return min(tied, key=lambda i: (rows[i]["skin"], -rows[i]["sharp"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src")
    ap.add_argument("--times")
    ap.add_argument("--n", type=int, default=8)
    ap.add_argument("--out", default="hero.jpg")
    ap.add_argument("--sheet")
    a = ap.parse_args(argv)

    dur = probe_dur(a.src)
    if not dur:
        print(f"unreadable: {a.src}")
        return 2
    if a.times:
        times = [float(t) for t in a.times.split(",") if t.strip()]
    else:
        span = max(0.0, dur - 2 * EDGE)
        times = [round(EDGE + span * (k + 0.5) / a.n, 2) for k in range(a.n)]
    times = [t for t in times if 0 <= t < dur]
    tmpdir = os.path.join(os.path.dirname(os.path.abspath(a.out)), ".hero_pick")
    os.makedirs(tmpdir, exist_ok=True)
    rows, ims = [], []
    for t in times:
        im = grab(a.src, t, os.path.join(tmpdir, f"h_{t:.2f}.jpg"))
        r = score(im)
        r["t"] = t
        rows.append(r)
        ims.append(im)
    win = rank(rows)
    print("   t    sharp   skin  luma  verdict")
    for i, r in enumerate(rows):
        v = r["bad"] or ("HERO" if i == win else "")
        print(f"{r['t']:6.2f} {r['sharp']:8.1f} {r['skin']:6.3f} {r['luma']:5.0f}  {v}")
    if a.sheet and ims:
        th = [im.resize((240, round(240 * im.height / im.width))) for im in ims]
        sheet = Image.new("RGB", (240 * len(th), max(t.height for t in th)), "white")
        for k, t in enumerate(th):
            sheet.paste(t, (240 * k, 0))
        sheet.save(a.sheet, quality=88)
    for f in os.listdir(tmpdir):
        os.remove(os.path.join(tmpdir, f))
    os.rmdir(tmpdir)
    if win is None:
        print(json.dumps({"hero": None, "why": "every candidate dark / flash", "rows": rows}))
        return 1
    ims[win].save(a.out, quality=95)
    print(json.dumps({"hero": a.out, "t": rows[win]["t"], "rows": rows}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
