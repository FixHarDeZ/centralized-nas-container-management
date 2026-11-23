#!/usr/bin/env python3
"""Deterministic sub structure check — line bands per event, blank gaps, no OCR.

Renders subs.ass onto a black 720x1280 plate, samples every Dialogue event
at its midpoint and counts "text bands" (contiguous rows holding lit pixels,
grouped when <=4px apart) inside y680-1060, then samples the midpoint of
every inter-event gap (and one point after the last event).

Verdict:
  * each event: band count == number of lines in its Text field  (\\N + 1). A 2-line Thai event whose
    upper vowels / tone marks bridge the rows between its lines merges into ONE lit band; it still
    passes when its DENSE fill blocks (the glyph bodies: rows with >= max(30, 45 % of the peak) lit
    pixels) number exactly the lines wanted and sit >= MIN_SEP px apart — printed as "OK (marks
    bridge …)". This is sub_bandprofile.py's verdict, folded in after it settled 3 of 4 false
    FAILs on 2026-11-23 (chihuahua, tinzshop-zelda, ps5) by hand.
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
BAND_GAP = 4       # rows this close belong to one band
FILL_GAP = 6       # fill rows this close belong to one line body
MIN_SEP = 16       # px between two line bodies that still counts as two lines
Y0, Y1 = 680, 1060


def lit_rows(png):
    """-> [(y, n_lit, x_min, x_max)] of rows holding lit text pixels in Y0-Y1."""
    im = Image.open(png).convert("L").crop((0, Y0, 720, Y1))
    px = im.load()
    w, h = im.size
    rows = []
    for y in range(h):
        xs = [x for x in range(w) if px[x, y] > LIT]
        if len(xs) > 3:
            rows.append((y + Y0, len(xs), min(xs), max(xs)))
    return rows


def group(rows, gap):
    g = []
    for r in rows:
        if g and r[0] - g[-1][-1][0] <= gap:
            g[-1].append(r)
        else:
            g.append([r])
    return g


def bands_of(rows):
    """-> [(y0, y1, x_min, x_max)] of lit bands."""
    return [(g[0][0], g[-1][0], min(r[2] for r in g), max(r[3] for r in g))
            for g in group(rows, BAND_GAP)]


def fills_of(rows):
    """-> [(y0, y1)] of the dense glyph-body blocks."""
    if not rows:
        return []
    thr = max(30, int(0.45 * max(r[1] for r in rows)))
    return [(g[0][0], g[-1][0]) for g in group([r for r in rows if r[1] >= thr], FILL_GAP)]


def verdict(rows, want):
    """-> (ok, note) for one sample's lit rows against the wanted line count."""
    b = bands_of(rows)
    if len(b) == want:
        return True, ""
    if want >= 2 and len(b) < want:
        f = fills_of(rows)
        if len(f) == want:
            sep = min(f[k + 1][0] - f[k][1] for k in range(len(f) - 1))
            if sep >= MIN_SEP:
                return True, f"marks bridge {want} lines, bodies {sep}px apart"
            return False, f"line bodies only {sep}px apart"
    return False, ""


def bands(png):
    """-> [(y0, y1, x_min, x_max)] of lit text bands in Y0-Y1."""
    return bands_of(lit_rows(png))


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
        rows = lit_rows(tmp)
        b = bands_of(rows)
        ok, note = verdict(rows, want)
        fail += 0 if ok else 1
        ext = [(x0, x1) for _, _, x0, x1 in b]
        tag = ("OK" if ok else "FAIL") + (f" ({note})" if note else "")
        print(f"{kind} {idx} t={t:.2f}: bands={len(b)} want={want} {tag} x={ext}")
    os.remove(tmp)
    os.remove(probe)
    print("SUB STRUCTURE PASS" if fail == 0 else f"SUB STRUCTURE FAIL ({fail})")
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
