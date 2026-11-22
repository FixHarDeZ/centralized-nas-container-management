#!/usr/bin/env python3
"""box_crop.py — crop candidates for a boxed product (game case, retail box, device) in a listing image.

Why (switch2-oblivion-rd 2026-11-22): the case sat on a red shop banner with the shop wordmark and a search bar;
Hermes wrote four throwaway pixel-probe scripts (~6 min, 20k reasoning chars a turn) to find its edges.
product-image-prep.md's "frame scan" done once, in code:

  1. contours at three Canny thresholds -> rectangles (convex-hull fill >= RECT_FILL) covering 6-92 % of the
     image (the case art, the box face);
  2. each rectangle's sides pushed out to the farthest FULL straight edge line within EXTEND of the image
     (>= LINE_FULL of the side's span crosses a colour step): the case's coloured header / rim that has no
     contour of its own against a same-colour background (oblivion: the red Switch 2 header, art 162 -> case 57);
  3. de-duplicated, ranked by area, the top N cut out and tiled into ONE labelled sheet (C1..Cn) for ONE vision
     call ("which tile is the whole product, no shop marks?"); RapidOCR text per candidate when installed, so a
     leaked shop wordmark shows before the vision call.

  uv run --with opencv-python-headless --with numpy --with pillow [--with rapidocr-onnxruntime] \
      python box_crop.py img1.jpg [--out-dir .] [--n 4] [--pad 0]
  -> box_C<n>.jpg + box_crop_sheet.jpg + box_crop.json; one JSON line on stdout
Exit 1 when no rectangle was found (not a boxed product: crop by position, product-image-prep.md §d).
"""
import argparse
import json
import os
import sys

RECT_FILL = 0.85     # contour convex-hull area / bounding-box area
MIN_AREA, MAX_AREA = 0.06, 0.92
EXTEND = 0.35        # max push of a side, x image size
LINE_FULL = 0.85     # share of the side's span that must cross a colour step for a "full" edge line
STEP = 40.0          # Lab colour distance between neighbouring pixels = an edge
SAME = 0.9           # IoU above this = the same candidate


def iou(a, b):
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ix = max(0, min(ax0 + aw, bx0 + bw) - max(ax0, bx0))
    iy = max(0, min(ay0 + ah, by0 + bh) - max(ay0, by0))
    inter = ix * iy
    return inter / float(aw * ah + bw * bh - inter) if inter else 0.0


def dedupe(rects):
    out = []
    for r in sorted(rects, key=lambda r: -r[2] * r[3]):
        if all(iou(r, o) < SAME for o in out):
            out.append(r)
    return out


def full_line(strength, lo, hi, step, limit):
    """Farthest index from `lo` (moving by `step`, up to `limit` positions) whose line strength >= LINE_FULL."""
    best = None
    for k in range(1, limit + 1):
        i = lo + step * k
        if i < 0 or i >= hi:
            break
        if strength(i) >= LINE_FULL:
            best = i
    return best


def extend(rect, gy, gx, w, h):
    """Push each side of rect out to the farthest full edge line. gy: (h-1, w) row steps, gx: (h, w-1) col steps."""
    x, y, rw, rh = rect
    x0, y0, x1, y1 = x, y, x + rw, y + rh
    span_x = slice(x0 + 3, max(x0 + 4, x1 - 3))
    span_y = slice(y0 + 3, max(y0 + 4, y1 - 3))
    row = lambda i: float((gy[i, span_x] > STEP).mean())      # noqa: E731
    col = lambda j: float((gx[span_y, j] > STEP).mean())      # noqa: E731
    t = full_line(row, y0, h - 1, -1, int(EXTEND * h))
    b = full_line(row, y1 - 1, h - 1, 1, int(EXTEND * h))
    le = full_line(col, x0, w - 1, -1, int(EXTEND * w))
    r = full_line(col, x1 - 1, w - 1, 1, int(EXTEND * w))
    y0 = t if t is not None else y0
    y1 = b + 1 if b is not None else y1
    x0 = le if le is not None else x0
    x1 = r + 1 if r is not None else x1
    return (x0, y0, x1 - x0, y1 - y0)


def candidates(img):
    import cv2
    import numpy as np
    h, w = img.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), (5, 5), 0)
    raw = []
    for lo, hi in ((30, 90), (50, 150), (80, 200)):
        e = cv2.dilate(cv2.Canny(gray, lo, hi), np.ones((3, 3), np.uint8))
        cs, _ = cv2.findContours(e, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for c in cs:
            x, y, cw, ch = cv2.boundingRect(c)
            a = cw * ch
            if not MIN_AREA * w * h <= a <= MAX_AREA * w * h:
                continue
            if cv2.contourArea(cv2.convexHull(c)) / a >= RECT_FILL:
                raw.append((x, y, cw, ch))
    raw = dedupe(raw)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float32)
    gy = np.abs(np.diff(lab, axis=0)).sum(axis=2)
    gx = np.abs(np.diff(lab, axis=1)).sum(axis=2)
    ext = [extend(r, gy, gx, w, h) for r in raw]
    return dedupe(ext + raw)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("image")
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--pad", type=int, default=0, help="px added around each crop (clamped to the image)")
    a = ap.parse_args(argv)
    import cv2
    from PIL import Image, ImageDraw, ImageFont
    img = cv2.imread(a.image)
    if img is None:
        print(json.dumps({"problem": f"cannot read {a.image}"}))
        return 1
    h, w = img.shape[:2]
    rects = candidates(img)[: a.n]
    if not rects:
        print(json.dumps({"image": a.image, "candidates": [], "problem": "no rectangle: not a boxed product shot"}))
        return 1
    try:
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()
    except ImportError:
        ocr = None
    src = Image.open(a.image).convert("RGB")
    out, tiles = [], []
    for i, (x, y, cw, ch) in enumerate(rects, 1):
        x0, y0 = max(0, x - a.pad), max(0, y - a.pad)
        x1, y1 = min(w, x + cw + a.pad), min(h, y + ch + a.pad)
        path = os.path.join(a.out_dir, f"box_C{i}.jpg")
        crop = src.crop((x0, y0, x1, y1))
        crop.save(path, "JPEG", quality=92)
        row = {"n": i, "file": path, "rect": [x0, y0, x1 - x0, y1 - y0], "wh": [x1 - x0, y1 - y0],
               "touches_edge": x0 == 0 or y0 == 0 or x1 == w or y1 == h}
        if ocr:
            found, _ = ocr(path)
            row["text"] = [t.strip() for _, t, sc in (found or []) if float(sc) >= 0.6 and t.strip()]
        out.append(row)
        tiles.append((f"C{i} {x1 - x0}x{y1 - y0}", crop))
    th = 420
    sized = [(lab, im.resize((max(1, round(im.width * th / im.height)), th))) for lab, im in tiles]
    sheet = Image.new("RGB", (sum(im.width for _, im in sized) + 12 * (len(sized) + 1), th + 40), (30, 30, 30))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 22)
    except OSError:
        font = ImageFont.load_default()
    x = 12
    for lab, im in sized:
        sheet.paste(im, (x, 36))
        d.text((x, 6), lab, fill="yellow", font=font)
        x += im.width + 12
    sheet.thumbnail((1600, 1600))
    sheet_path = os.path.join(a.out_dir, "box_crop_sheet.jpg")
    sheet.save(sheet_path, "JPEG", quality=85)
    res = {"image": a.image, "size": [w, h], "candidates": out, "sheet": sheet_path,
           "ask_vision": "Tiles C1..Cn are crops of one listing photo. Which ONE shows the WHOLE product (no part cut "
                         "off) with no shop wordmark, price, search bar or banner? Answer the tile label, or NONE "
                         "and what is wrong."}
    with open(os.path.join(a.out_dir, "box_crop.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    for r in out:
        print(f"C{r['n']} rect={r['rect']}" + (" EDGE" if r["touches_edge"] else "")
              + (f" text={r['text']}" if r.get("text") else ""))
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
