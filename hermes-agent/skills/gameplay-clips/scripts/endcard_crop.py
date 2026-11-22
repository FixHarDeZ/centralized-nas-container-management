#!/usr/bin/env python3
"""endcard_crop.py — the trailer's end card: when it is up, and a title-only crop for build_v5.

Why (switch2-oblivion-rd 2026-11-22): Hermes spent ~10 min of hand probes (row-band scans, a card map, two
vision calls) to cut the platform badge and the legal lines off the card, then saved the cut as a 1920x600
file whose `wide` seg stretched it 1.8x and left "OUT NOW" 1 px from the picture edge.

  uv run --with rapidocr-onnxruntime --with numpy --with pillow python endcard_crop.py trailer.mp4 \
      [--tail 15] [--at 101.5,102.5] [--window-h 720] [--out endcard_crop.json] [--preview endcard_crop.jpg]

* Without --at: OCR the last --tail s at 2 fps; the card = the longest run of frames whose title text is up
  (>= 60 % of the most title characters seen). --at = use those times instead (a card mid-trailer).
* Each OCR box is the title (kept) or not: legal / platform / rating / store / date words, anything in the
  bottom 10 % of the frame and the corner logos (publisher, studio) are dropped.
* crop = the kept boxes' union + MARGIN, widened to the window's aspect (it is scaled to the window width,
  never stretched), clamped to the frame, and pulled back from any dropped box it would show.
Prints a table + one JSON line {"in", "dur", "crop", "kept", "dropped", "seg", "problem"}; writes the same
JSON to --out and a preview of the crop as it will sit in the window (--preview, for ONE vision look when the
kept/dropped lists look wrong). Paste "seg" as the LAST seg of plan.json (add audio_src/audio_in).
Exit 1 when there is no title in the scanned span or the crop cannot keep MIN_MARGIN around it.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

FPS = 2.0
MARGIN = 0.05            # x frame height, each side of the title union (54 px on 1080p)
MIN_MARGIN = 12          # px: less than this to a dropped box = the card can't be cut cleanly
MIN_SCORE = 0.5
TITLE_SHARE = 0.6       # a frame is part of the card when it shows this share of the most title characters
CORE_SHARE = 0.9        # ... and the card is FULLY up from here (titles animate in): crop from these frames
LEAD = 0.5              # s of the animate-in kept before the core
WW = 720
DROP_RE = re.compile(
    r"©|\(c\)|™|®|rights?\s*reserved|trade\s*mark|licen[cs]e|all\s*rights|www\.|\.com|\.net|"
    r"nintendo|switch|playstation|ps[45]\b|xbox|steam|epic games|microsoft|sony|"
    r"esrb|pegi|rated|rating|cero|usk|\bage\b|"
    r"pre-?order|available|coming|wishlist|buy now|"
    r"\b(19|20)\d\d\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d", re.I)


def box_rect(box):
    xs = [float(p[0]) for p in box]
    ys = [float(p[1]) for p in box]
    return [min(xs), min(ys), max(xs), max(ys)]


def classify(result, w, h):
    """RapidOCR result -> (kept, dropped): [{"text", "rect"}]. Kept = title / tagline text."""
    kept, dropped = [], []
    for box, text, score in result or []:
        text = (text or "").strip()
        if float(score) < MIN_SCORE or len(text.replace(" ", "")) < 2:
            continue
        r = box_rect(box)
        cx, cy = (r[0] + r[2]) / 2, (r[1] + r[3]) / 2
        corner = (cx < 0.15 * w or cx > 0.85 * w) and cy > 0.6 * h
        alnum = re.sub(r"[^0-9A-Za-z]", "", text)
        badge = len(alnum) <= 3 and any(c.isdigit() for c in alnum)   # oblivion: the Switch 2 badge read "B2"/"92"
        why = ("words" if DROP_RE.search(text) else "badge" if badge else "bottom" if cy > 0.9 * h
               else "corner" if corner else None)
        (dropped if why else kept).append({"text": text, "rect": [round(v) for v in r], **({"why": why} if why else {})})
    return kept, dropped


def union(rects):
    return [min(r[0] for r in rects), min(r[1] for r in rects), max(r[2] for r in rects), max(r[3] for r in rects)]


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def plan_crop(kept, dropped, w, h, window_h):
    """-> ([x, y, cw, ch] ints, problem or None)."""
    u = union([k["rect"] for k in kept])
    m = max(MIN_MARGIN * 2, MARGIN * h)
    x0, y0, x1, y1 = u[0] - m, u[1] - m, u[2] + m, u[3] + m
    # pull back from dropped boxes the margin would show (a badge just under the tagline)
    for d in dropped:
        r = d["rect"]
        if not overlaps([x0, y0, x1, y1], r):
            continue
        if r[1] >= u[3]:
            y1 = min(y1, r[1] - 2)
        elif r[3] <= u[1]:
            y0 = max(y0, r[3] + 2)
        elif r[0] >= u[2]:
            x1 = min(x1, r[0] - 2)
        elif r[2] <= u[0]:
            x0 = max(x0, r[2] + 2)
        else:
            return None, f"dropped '{d['text']}' sits inside the title block — no clean cut; use \"wide\" on the full frame"
    # widen to the window aspect (scaled to the window width, so it must be at least as wide as the window)
    need_w = (y1 - y0) * WW / window_h
    if x1 - x0 < need_w:
        cx = (x0 + x1) / 2
        x0, x1 = cx - need_w / 2, cx + need_w / 2
    if x1 - x0 > w:
        x0, x1 = 0, w
    if x0 < 0:
        x0, x1 = 0, x1 - x0
    if x1 > w:
        x0, x1 = x0 - (x1 - w), w
    y0, y1 = max(0, y0), min(h, y1)
    for d in dropped:                           # widening must not bring a side logo back in
        if overlaps([x0, y0, x1, y1], d["rect"]):
            return None, f"widening to the window aspect shows dropped '{d['text']}' — use \"wide\" on the full frame"
    marg = min(u[0] - x0, u[1] - y0, x1 - u[2], y1 - u[3])
    crop = [round(x0), round(y0), round(x1 - x0) // 2 * 2, round(y1 - y0) // 2 * 2]
    if marg < MIN_MARGIN:
        return crop, f"only {marg:.0f} px between the title and the crop edge (< {MIN_MARGIN}) — check the preview"
    return crop, None


def title_chars(kept):
    return sum(len(k["text"].replace(" ", "")) for k in kept)


def card_run(samples, share=TITLE_SHARE):
    """samples: [(t, kept)] in time order -> (t_start, t_end) of the longest run with >= share of the max
    title characters, or None."""
    best = max((title_chars(k) for _, k in samples), default=0)
    if not best:
        return None
    run, top = None, None
    for t, k in samples:
        if title_chars(k) >= share * best:
            run = (run[0], t) if run else (t, t)
            if not top or run[1] - run[0] > top[1] - top[0]:
                top = run
        else:
            run = None
    return top


def grab(src, t, out):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", src, "-frames:v", "1", "-update", "1", out],
                   capture_output=True)
    return os.path.exists(out) and os.path.getsize(out) > 0


def probe_dur(src):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
                         capture_output=True, text=True).stdout
    return float(out.strip())


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src")
    ap.add_argument("--tail", type=float, default=15.0)
    ap.add_argument("--at", help="comma list of source times showing the card (skips the tail scan)")
    ap.add_argument("--window-h", type=int, default=720, help="plan window_h (720 tall window, 405 = 16:9 band)")
    ap.add_argument("--out", default="endcard_crop.json")
    ap.add_argument("--preview", default="endcard_crop.jpg")
    a = ap.parse_args(argv)
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    dur = probe_dur(a.src)
    if a.at:
        times = [float(x) for x in a.at.split(",")]
    else:
        t0 = max(0.0, dur - a.tail)
        times = [round(t0 + i / FPS, 2) for i in range(int((dur - 0.1 - t0) * FPS) + 1)]
    samples, size = [], None
    with tempfile.TemporaryDirectory() as td:
        for t in times:
            f = os.path.join(td, f"{t}.png")
            if not grab(a.src, t, f):
                continue
            im = Image.open(f)
            size = im.size
            result, _ = ocr(f)
            samples.append((t, *classify(result, *size)))
        if not samples:
            print(json.dumps({"problem": "no frame could be grabbed"}))
            return 1
        tk = [(t, k) for t, k, _ in samples]
        run = card_run(tk) if not a.at else (times[0], times[-1])
        core = card_run(tk, CORE_SHARE) if not a.at else run
        if run and core and not (run[0] <= core[0] <= run[1]):
            core = run                          # the fullest frames are a different run: stay in the long one
        res = {"src": os.path.abspath(a.src)}
        if not run:
            res["problem"] = f"no title text in {times[0]:.1f}-{times[-1]:.1f} s — widen --tail or give --at"
        else:
            sel = [s for s in samples if core[0] <= s[0] <= core[1]]
            kept = [k for _, ks, _ in sel for k in ks]
            dropped = [d for _, _, ds in sel for d in ds]
            crop, problem = plan_crop(kept, dropped, size[0], size[1], a.window_h)
            card_in = round(max(run[0], core[0] - LEAD) if not a.at else times[0], 2)
            card_dur = round(max(0.5, core[1] + 1 / FPS - card_in), 2)
            res.update({"in": card_in, "dur": card_dur, "crop": crop, "problem": problem,
                        "kept": sorted({k["text"] for k in kept}), "dropped": sorted({d["text"] for d in dropped}),
                        "seg": {"src": "trailer", "in": card_in, "dur": card_dur, "mode": "window", "endcard": True,
                                "crop": crop, "snap": False}})
            if crop:
                mid = sel[len(sel) // 2][0]
                f = os.path.join(td, "mid.png")
                if grab(a.src, mid, f):
                    x, y, cw, ch = crop
                    pic = Image.open(f).convert("RGB").crop((x, y, x + cw, y + ch))
                    ph = round(WW * ch / cw / 2) * 2
                    canvas = Image.new("RGB", (WW, a.window_h), (40, 40, 40))
                    canvas.paste(pic.resize((WW, ph), Image.LANCZOS), (0, (a.window_h - ph) // 2))
                    canvas.save(a.preview, "JPEG", quality=85)
                    res["preview"] = os.path.abspath(a.preview)
    for t, k, d in samples:
        print(f"{t:7.2f}  title {title_chars(k):3d}  " + " | ".join(x["text"] for x in k)
              + (f"   [dropped: {' | '.join(x['text'] for x in d)}]" if d else ""))
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False))
    return 1 if res.get("problem") and not res.get("crop") else 0


if __name__ == "__main__":
    sys.exit(main())
