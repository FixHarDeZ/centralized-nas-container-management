#!/usr/bin/env python3
"""Deterministic sub structure check — line bands per event, blank gaps, no OCR.

Renders subs.ass onto a black 720x1280 plate, samples every Dialogue event
at its midpoint and counts "text bands" (contiguous rows holding lit pixels,
grouped when <=4px apart) inside y680-1060, then samples the midpoint of
every inter-event gap (and one point after the last event).

Verdict:
  * each event: band count == number of lines in its Text field  (\\N + 1)
  * every gap sample: 0 bands
  * x-extent per band is printed, so a truncated line shows up as a width
    far shorter than the other band of the same event.

Exit 0 = structure OK, 1 = mismatch. Do NOT try to catch this with vision
OCR instead: it tends to report only the first line either way.

Usage: uv run --with pillow python sub_linecheck.py [workdir]
        (workdir must contain subs.ass; uses fonts/ when present)
"""
import os
import subprocess
import sys

from PIL import Image


def parse_events(path):
    """-> [(start_s, end_s, text)] from a Dialogue line (Text may hold commas)."""
    def sec(t):
        h, m, s = t.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    ev = []
    for ln in open(path, encoding="utf-8"):
        if not ln.startswith("Dialogue:"):
            continue
        parts = ln.rstrip("\n").split(",")
        # Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text...
        ev.append((sec(parts[1]), sec(parts[2]), ",".join(parts[9:])))
    return ev


def grab(probe, t, out):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", probe,
                    "-frames:v", "1", "-update", "1", out], check=True)


# fill-only threshold: pastel-yellow fill ~210 lum, dark outline/shadow ~55 (outline would
# bridge the two lines into one band at >40)
LIT = 120


def bands(png):
    """-> [(y0, y1, x_min, x_max)] of lit text bands in y680-1060."""
    im = Image.open(png).convert("L").crop((0, 680, 720, 1060))
    px = im.load()
    w, h = im.size
    rows = []
    for y in range(h):
        xs = [x for x in range(w) if px[x, y] > LIT]
        if len(xs) > 3:
            rows.append((y + 680, min(xs), max(xs)))
    groups = []
    for y, x0, x1 in rows:
        if groups and y - groups[-1][-1][0] <= 4:
            groups[-1].append((y, x0, x1))
        else:
            groups.append([(y, x0, x1)])
    return [(g[0][0], g[-1][0], min(r[1] for r in g), max(r[2] for r in g))
            for g in groups]


def main():
    wd = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    ass = os.path.join(wd, "subs.ass")
    if not os.path.exists(ass):
        raise SystemExit(f"no subs.ass in {wd}")
    ev = parse_events(ass)
    if not ev:
        raise SystemExit("no Dialogue events parsed")
    dur = ev[-1][1] + 2.0
    fonts = os.path.join(wd, "fonts")
    fd = fonts if os.path.isdir(fonts) else wd
    probe = os.path.join(wd, ".sublineprobe.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"color=black:s=720x1280:d={dur}:r=30",
                    "-vf", f"ass={ass}:fontsdir={fd}:shaping=complex",
                    "-c:v", "libx264", "-t", str(dur), probe], check=True)

    samples = [("event", i, (s + e) / 2, t.count("\\N") + 1)
               for i, (s, e, t) in enumerate(ev)]
    for i in range(len(ev) - 1):
        g0, g1 = ev[i][1], ev[i + 1][0]
        if g1 - g0 >= 0.12:
            samples.append(("gap", i, (g0 + g1) / 2, 0))
    if dur - ev[-1][1] >= 0.5:
        samples.append(("gap", "tail", min(ev[-1][1] + 0.5, dur - 0.1), 0))

    fail = 0
    tmp = os.path.join(wd, ".subline.png")
    for kind, idx, t, want in samples:
        grab(probe, t, tmp)
        b = bands(tmp)
        ok = len(b) == want
        fail += 0 if ok else 1
        ext = [(x0, x1) for _, _, x0, x1 in b]
        print(f"{kind} {idx} t={t:.2f}: bands={len(b)} want={want} "
              f"{'OK' if ok else 'FAIL'} x={ext}")
    os.remove(tmp)
    os.remove(probe)
    print("SUB STRUCTURE PASS" if fail == 0 else f"SUB STRUCTURE FAIL ({fail})")
    sys.exit(0 if fail == 0 else 1)


main()
