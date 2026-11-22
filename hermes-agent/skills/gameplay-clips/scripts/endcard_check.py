#!/usr/bin/env python3
"""End-card fit check for a finished 🎬 clip: is any text in the last seconds cut by the frame edge?

2026-11-20/21: ffr-swt-dec04 ended on "L FANTASY RESONANCE" (a pre-cropped 836x470 endcard file, `wide` on a crop)
and sniper-elite3-sw on "NIPER ELITE" (the logo card in the 1:1 window). gotg-encore-gp's full 1920x1080 card with
`"wide": true` was whole. A word touching the left or right edge of the 720-wide frame is a cut word: subtitles,
pills and the sticker sit well inside.

2026-11-22: switch2-oblivion-rd's card sat in the window with "OUT NOW" 1 px above the picture's bottom edge —
the frame edge never saw it. --rect x0,y0,x1,y1 (build_v5's work/timeline_v5.json "endcard_rect" = a "crop"
end card's picture in the 720x1280 frame) adds that picture's top and bottom: text whose box centre is inside the
picture and that ends within 4 px of its top or bottom = cut. Not for a full-frame card: its top/bottom are the
trailer's own edges and titles sit there by design (gotg-encore-gp: MARVEL 2 px from the top, whole).

  uv run --with rapidocr-onnxruntime --with numpy --with pillow python endcard_check.py final.mp4 \
      [--at 0.4,1.0,1.6] [--rect 0,348,720,832]

Prints one JSON line {"ok", "w", "rect", "hits": [{"t", "text", "side", "x0", "x1"}]}; exit 1 when a word is cut.
clipjob.py deliver runs it for every 🎬 job with the rect from the job's timeline (ENDCARD_OK=1 skips it when
the edge text is HUD, not a title).
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile

EDGE = 0.0055       # 720 px frame -> a box within 4 px of the edge (gotg-encore-gp: a whole card's text ends 5 px in)
MIN_SCORE = 0.5
MIN_CHARS = 3
RECT_EDGE = 4       # px: text this close to the end-card picture's top / bottom = cut by the crop / window


def duration(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    return float(p.stdout.strip())


def cut_boxes(result, w, t, rect=None):
    """RapidOCR result -> the boxes that touch the left/right frame edge, or (rect = x0, y0, x1, y1 of the end-card
    picture) its top / bottom edge."""
    hits = []
    for box, text, score in result or []:
        text = (text or "").strip()
        if float(score) < MIN_SCORE or len(text.replace(" ", "")) < MIN_CHARS:
            continue
        xs = [float(p[0]) for p in box]
        x0, x1 = min(xs), max(xs)
        side = "left" if x0 <= w * EDGE else "right" if x1 >= w * (1 - EDGE) else None
        if not side and rect:
            ys = [float(p[1]) for p in box]
            y0, y1 = min(ys), max(ys)
            if rect[0] <= (x0 + x1) / 2 <= rect[2] and rect[1] <= (y0 + y1) / 2 <= rect[3]:
                side = "top" if y0 <= rect[1] + RECT_EDGE else "bottom" if y1 >= rect[3] - RECT_EDGE else None
        if side:
            hits.append({"t": t, "text": text, "side": side, "x0": round(x0), "x1": round(x1)})
    return hits


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("video")
    ap.add_argument("--at", default="0.4,1.0,1.6", help="seconds before the end to sample")
    ap.add_argument("--rect", help="x0,y0,x1,y1 of the end-card picture in the frame (timeline_v5 endcard_rect)")
    a = ap.parse_args(argv)
    rect = [float(v) for v in a.rect.split(",")] if a.rect else None
    from PIL import Image
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    dur = duration(a.video)
    hits, w = [], None
    with tempfile.TemporaryDirectory() as td:
        for back in (float(x) for x in a.at.split(",")):
            t = round(max(0.0, dur - back), 2)
            f = os.path.join(td, f"f{t}.png")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", a.video, "-frames:v", "1", f],
                           check=False)
            if not os.path.exists(f):
                continue
            w = Image.open(f).width
            result, _ = ocr(f)
            hits += cut_boxes(result, w, t, rect)
    print(json.dumps({"ok": not hits, "w": w, "rect": rect, "hits": hits}, ensure_ascii=False))
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
