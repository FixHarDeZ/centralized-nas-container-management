#!/usr/bin/env python3
"""Which file is each ingredient chip? Pixel match, no vision call.

Fix 2026-11-23: "เช็คด้วยการวัดพิกเซลแทน" — the chip-identity zoom was one vision_analyze per attach and pushed
plaid-shoulder-blanket to 16 vision calls on a budget of 9. A chip in the live prompt box is the attached image
shown `object-fit: cover` in a rounded square (a character chip also carries a person badge bottom-right), so the
centre square of the source file, scaled to the chip, IS the chip: compare pixels.

    uv run --with pillow --with numpy python -I chipcheck.py \
        --chip c1.png --chip c2.png            # tight chip crops (cdp_shot.py), or:
        --shot shot.png --rects '[{"x":319,"y":574,"w":50,"h":50},…]'     # a full-viewport capture, or
        --shot row.jpg --rects '<same CSS rects>' --origin 300,560 --scale 4  # a cdp_shot.py <out> 300 560 w h 4 crop
        --expect ref1.jpg --expect /opt/data/clips/characters/<name>.jpg [--expect startframe.jpg]
        [--pool other.jpg … | --pool-dir /opt/data/clips/characters]

--expect = every file that must be in the box (refs, the character portrait, the start frame).
--pool   = look-alikes that must NOT be (the other roster portraits, the other colourway, an earlier product).
Exit 0 = every expected file is matched by exactly one chip and no chip matches a pool file;
exit 1 = a wrong / missing chip (fix the attach, nothing to read); exit 3 = a chip it cannot tell apart
(margin too small) — only then is ONE vision read of that chip allowed; exit 4 = NO chip matched anything = the
capture is off (rects vs --origin/--scale, the box scrolled): fix the capture, never touch the attach.
Rects are getBoundingClientRect() CSS px; --origin = the CSS x,y the image starts at (cdp_shot's x y), --scale =
its scale (a capture_screenshot PNG of the viewport: origin 0,0, scale = image width / innerWidth).
"""
import argparse
import hashlib
import json
import os
import sys

import numpy as np
from PIL import Image, ImageFilter

SIDE = 40            # compare at 40x40: a chip is ~50 CSS px, finer detail is JPEG/resample noise
MIN_SCORE = 0.70     # a matched chip scored 0.95-0.98 on real chips; an unrelated file 0.2-0.6
MIN_MARGIN = 0.06    # best minus runner-up below this = cannot tell (two colourways, two similar faces)


def _mask(n=SIDE):
    """Rounded-square interior minus the character badge corner (bottom-right ~30 %)."""
    yy, xx = np.mgrid[0:n, 0:n] + 0.5
    r = 0.22 * n
    cx = np.clip(xx, r, n - r)
    cy = np.clip(yy, r, n - r)
    inside = (xx - cx) ** 2 + (yy - cy) ** 2 <= r ** 2
    badge = (xx > 0.68 * n) & (yy > 0.68 * n)
    return inside & ~badge


MASK = _mask()


def trim_dark(im, thr=40):
    """Drop the dark page margin a loose crop leaves around the chip."""
    a = np.asarray(im.convert("L"), dtype=np.float32)
    rows = np.where(a.mean(axis=1) > thr)[0]
    cols = np.where(a.mean(axis=0) > thr)[0]
    if len(rows) < 4 or len(cols) < 4:
        return im
    return im.crop((int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1))


def cover_square(im):
    w, h = im.size
    s = min(w, h)
    return im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))


def vec(im):
    im = cover_square(im.convert("RGB")).resize((SIDE, SIDE), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.6))
    return np.asarray(im, dtype=np.float32) / 255.0


def score(chip, src):
    """0..1: grey-level correlation (layout) weighted with colour closeness, inside the chip mask."""
    a, b = chip[MASK], src[MASK]
    ga, gb = a.mean(axis=1), b.mean(axis=1)
    ga, gb = ga - ga.mean(), gb - gb.mean()
    den = float(np.sqrt((ga ** 2).sum() * (gb ** 2).sum()))
    corr = float((ga * gb).sum() / den) if den > 1e-6 else 0.0
    colour = 1.0 - float(np.abs(a - b).mean()) * 2.5          # mean |ΔRGB| 0.4 -> 0
    return round(max(0.0, 0.6 * max(corr, 0.0) + 0.4 * max(colour, 0.0)), 3)


def load_chips(a):
    chips = []
    if a.shot:
        shot = Image.open(a.shot)
        for i, r in enumerate(json.loads(a.rects)):
            s, (ox, oy) = a.scale, a.origin
            box = (round((r["x"] - ox) * s), round((r["y"] - oy) * s),
                   round((r["x"] - ox + r["w"]) * s), round((r["y"] - oy + r["h"]) * s))
            if box[0] < 0 or box[1] < 0 or box[2] > shot.width or box[3] > shot.height:
                raise SystemExit(f"rect{i + 1} {box} falls outside the {shot.width}x{shot.height} image: "
                                 "check --origin/--scale against how it was captured")
            chips.append((f"rect{i + 1}", trim_dark(shot.crop(box))))
    for p in a.chip:
        chips.append((p, trim_dark(Image.open(p))))
    return chips


SAME_IMAGE = 0.95    # two candidate files this alike are one picture (ref2 = ref_back upscaled 2.2x on genme)


def groups(cands, vecs):
    """Candidate -> its group's representative (first listed; an expect file before any pool file)."""
    rep = {}
    for i, (p, _) in enumerate(cands):
        rep[p] = next((q for q, _ in cands[:i] if rep[q] == q and score(vecs[p], vecs[q]) >= SAME_IMAGE), p)
    return rep


def check(chips, expect, pool):
    seen, cands = {}, []
    for p, kind in [(p, "expect") for p in expect] + [(p, "pool") for p in pool]:
        h = hashlib.sha256(open(p, "rb").read()).hexdigest()
        if h in seen:                       # same bytes under another name: one candidate, expect wins
            continue
        seen[h] = p
        cands.append((p, kind))
    vecs = {p: vec(Image.open(p)) for p, _ in cands}
    rep = groups(cands, vecs)
    kind_of = dict(cands)
    expect = list(dict.fromkeys(rep[seen[hashlib.sha256(open(p, "rb").read()).hexdigest()]] for p in expect))
    rows, unsure, wrong = [], [], []
    for name, im in chips:
        cv = vec(im)
        best_of = {}                        # one score per picture: the best of its files
        for p, _ in cands:
            best_of[rep[p]] = max(best_of.get(rep[p], 0.0), score(cv, vecs[p]))
        ranked = sorted(((sc, p) for p, sc in best_of.items()), reverse=True)
        best, second = ranked[0], (ranked[1] if len(ranked) > 1 else (0.0, None))
        margin = round(best[0] - second[0], 3)
        if best[0] < MIN_SCORE:
            verdict = "no-match"            # not any candidate: a stray chip, or a file you did not list
        elif margin < MIN_MARGIN:
            verdict = "unsure"
        else:
            verdict = "match" if kind_of[best[1]] == "expect" else "WRONG"
        row = {"chip": name, "verdict": verdict, "best": os.path.basename(best[1]), "score": round(best[0], 3),
               "runner_up": os.path.basename(second[1]) if second[1] else None, "margin": margin}
        rows.append((row, best[1]))
        (unsure if verdict == "unsure" else wrong if verdict in ("WRONG", "no-match") else []).append(name)
    matched = [p for row, p in rows if row["verdict"] == "match"]
    missing = [os.path.basename(p) for p in expect if p not in matched]
    doubled = sorted({os.path.basename(p) for p in matched if matched.count(p) > 1})
    ok = not wrong and not unsure and not missing and not doubled
    out = {"ok": ok, "chips": [r for r, _ in rows], "missing": missing, "doubled": doubled}
    if ok:
        out["next"] = "chips verified by pixels — no vision read"
    elif wrong or missing or doubled:
        out["next"] = ("fix the attach: remove a WRONG chip with its cancel icon, attach what is missing, then rerun. "
                       "A no-match chip is a stray from an earlier clip or a file you did not list (the start frame?) "
                       "- list it with --expect if it belongs. No vision read")
    else:
        out["next"] = f"one vision read of chip(s) {', '.join(unsure)} only (runner-up too close)"
    if rows and all(r["verdict"] == "no-match" for r, _ in rows):
        out["next"] = ("no chip matched ANY file: the capture is off (rects vs --origin/--scale, the box scrolled "
                       "or closed). Fix the capture and rerun — do NOT remove or re-attach chips, do NOT run trouble")
        return out, 4
    return out, (0 if ok else 1 if (wrong or missing or doubled) else 3)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--chip", action="append", default=[])
    ap.add_argument("--shot")
    ap.add_argument("--rects")
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--origin", type=lambda v: tuple(float(x) for x in v.split(",")), default=(0.0, 0.0))
    ap.add_argument("--expect", action="append", default=[], required=True)
    ap.add_argument("--pool", action="append", default=[])
    ap.add_argument("--pool-dir")
    a = ap.parse_args(argv)
    if bool(a.shot) != bool(a.rects):
        ap.error("--shot needs --rects (CSS px from getBoundingClientRect) and the reverse")
    pool = list(a.pool)
    if a.pool_dir:
        pool += sorted(os.path.join(a.pool_dir, f) for f in os.listdir(a.pool_dir)
                       if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")) and not f.startswith("_"))
    chips = load_chips(a)
    if not chips:
        ap.error("no chip: --chip FILE or --shot PNG --rects JSON")
    res, rc = check(chips, [os.path.abspath(p) for p in a.expect], [os.path.abspath(p) for p in pool])
    print(json.dumps(res, ensure_ascii=False, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
