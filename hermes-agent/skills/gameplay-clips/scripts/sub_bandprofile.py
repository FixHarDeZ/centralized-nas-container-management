#!/usr/bin/env python3
"""Adjudicate a sub_linecheck mismatch without vision.

Renders subs.ass onto a black plate (same probe as sub_linecheck.py), samples every
Dialogue event at its midpoint and prints, per event:
  * the lit-row bands (what sub_linecheck counts: LIT=120, group gap <=4px)
  * the DENSE fill blocks (rows with >= max(30, 45% of the event's peak count) =
    the actual glyph bodies of each line)
  * the separation between fill blocks and the sparse rows bridging them

Why: a 2-line event whose upper vowels / tone marks and descenders occupy the rows
between the two lines merges into ONE band and FAILs linecheck even though the
layout is correct. The line bodies themselves stay ~25-35 px apart; only sparse
rows (marks, tails) bridge the gap, so the fill blocks do not merge.

Verdict:
  bands == want                                  -> OK
  bands < want and >=2 fills >=16 px apart       -> FALSE POSITIVE (marks bridging):
                                                    pass the gate, record the reason in notes
  anything else                                  -> REAL defect: fix the sub text
                                                    (split with \\N / shorten), exit 1

Usage: uv run --with pillow python sub_bandprofile.py [workdir]
       (workdir must contain subs.ass; uses fonts/ when present)
Exit 0 = no real defect, 1 = real defect or unexplained.
"""
import os
import subprocess
import sys

from PIL import Image

LIT = 120          # fill threshold, same as sub_linecheck (outline would bridge lines)
MIN_SEP = 16       # px between two line bodies that still counts as two lines
BAND_GAP = 4       # row gap that merges bands (sub_linecheck's rule)


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
        ev.append((sec(parts[1]), sec(parts[2]), ",".join(parts[9:])))
    return ev


def row_profile(png):
    """-> [(y, n_lit, x0, x1)] for lit rows in y640-1080 of the plate."""
    im = Image.open(png).convert("L")
    px = im.load()
    out = []
    for y in range(640, 1080):
        xs = [x for x in range(720) if px[x, y] > LIT]
        if len(xs) > 3:
            out.append((y, len(xs), min(xs), max(xs)))
    return out


def group(rows, gap):
    g = []
    for r in rows:
        if g and r[0] - g[-1][-1][0] <= gap:
            g[-1].append(r)
        else:
            g.append([r])
    return g


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
    probe = os.path.join(wd, ".bandprobe.mp4")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi",
                    "-i", f"color=black:s=720x1280:d={dur}:r=30",
                    "-vf", f"ass={ass}:fontsdir={fd}:shaping=complex",
                    "-c:v", "libx264", "-t", str(dur), probe], check=True)

    tmp = os.path.join(wd, ".bandprobe.png")
    real_defect = 0
    for i, (s, e, text) in enumerate(ev):
        want = text.count("\\N") + 1
        t = (s + e) / 2
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", probe,
                        "-frames:v", "1", "-update", "1", tmp], check=True)
        rows = row_profile(tmp)
        if not rows:
            print(f"event {i} t={t:.2f}: NO LIT ROWS (blank plate?)")
            real_defect += 1
            continue
        bands = group(rows, BAND_GAP)
        peak = max(r[1] for r in rows)
        fill_thr = max(30, int(0.45 * peak))
        fills = group([r for r in rows if r[1] >= fill_thr], 6)

        desc_b = [(b[0][0], b[-1][0]) for b in bands]
        desc_f = [(f[0][0], f[-1][0], min(r[2] for r in f), max(r[3] for r in f))
                  for f in fills]
        line = (f"event {i} t={t:.2f}: bands={len(bands)} want={want} "
                f"ybands={desc_b} fills(y0,y1,x0,x1)={desc_f}")
        if len(bands) == want:
            print(line + "  OK")
            continue
        if len(bands) < want and len(fills) >= 2:
            seps = [fills[k + 1][0][0] - fills[k][-1][0] for k in range(len(fills) - 1)]
            mid = [r for r in rows
                   if fills[0][-1][0] < r[0] < fills[1][0][0]]
            mid_max = max((r[1] for r in mid), default=0)
            if min(seps) >= MIN_SEP:
                print(line + f"  FALSE POSITIVE (fills {min(seps)}px apart, "
                             f"bridging rows sparse, peak={mid_max})")
                continue
            print(line + f"  REAL: fills only {min(seps)}px apart (peak={mid_max})")
        else:
            print(line + "  UNEXPLAINED (see gameplay-pitfalls: Latin word in a "
                         "Thai line splits one band into two)")
        real_defect += 1

    os.remove(tmp)
    os.remove(probe)
    print("NO REAL DEFECT" if real_defect == 0 else f"REAL DEFECT ({real_defect})")
    sys.exit(0 if real_defect == 0 else 1)


main()
