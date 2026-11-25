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

4. no rectangle (or --panels): PANELS — a collage / how-to sheet / catalog page split at its uniform gutters
   (recursive XY cut: a row or column whose pixels sit within GUTTER_TOL of their median >= GUTTER_NEAR is a
   gutter). ps2-hdd-175 (2026-11-24): a product photo above a strip of three numbered step panels on white;
   no contour rectangle, so Hermes wrote ~15 scratch pixel probes (50 min) to find the photo's extent and
   cropped flush against the cable loop (x 779, content ends at 782). Tiles carry `"src": "panel"`; a
   trimmed margin keeps MARGIN px.
5. a promo BADGE (a saturated disc: "x2", a quantity / sale sticker) crossing a candidate's edge is listed in that
   candidate's `badges`, and the tile label says +badge. cal-d-protein-1mo (2026-11-25): a red "x2" disc on each
   box's top-right corner plus a 1-px grey screenshot border (which `extend` took for the farthest edge line, so
   every candidate ran the full image height) cost 3 h of hand pixel probes. `--paint-badge` inpaints the discs
   before cropping (flat-faced packaging only, and only when Fix chose "ระบายออก" in the photo-gate clarify:
   it repaints the product's own pixels); painted tiles say so (`painted`, label "painted").
Exit 1 when neither a rectangle nor a panel was found (crop by position, product-image-prep.md §d).
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
GUTTER_TOL = 6       # grey levels from the line median
GUTTER_NEAR = 0.98   # share of a line within GUTTER_TOL = a gutter line (a page margin, a white band)
GUTTER_RUN = 4       # consecutive gutter lines needed to cut
PANEL_MIN = 0.08     # a panel side >= this share of the image side (drops icons, text lines)
MARGIN = 12          # px of a trimmed uniform margin kept around a panel
BORDER = 2           # lines this close to the image edge are the screenshot's own border, never the product's
BADGE_SAT, BADGE_VAL = 110, 50
BADGE_R = (0.015, 0.09)   # disc radius as a share of the image width
BADGE_ROUND = 0.6    # component area / its enclosing circle's area


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
        if i < BORDER or i >= hi - BORDER + 1:
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


def badges(img):
    """Saturated, round blobs: promo stickers ("x2", "-50%") pasted on a listing. -> [(cx, cy, r)]."""
    import cv2
    import numpy as np
    w = img.shape[1]
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    m = ((hsv[..., 1] >= BADGE_SAT) & (hsv[..., 2] >= BADGE_VAL)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    out = []
    for c in cs:
        (cx, cy), r = cv2.minEnclosingCircle(c)
        if not BADGE_R[0] * w <= r <= BADGE_R[1] * w:
            continue
        if cv2.contourArea(cv2.convexHull(c)) / (np.pi * r * r) >= BADGE_ROUND:
            out.append((int(cx), int(cy), int(r)))
    return out


def edge_badges(rect, discs):
    """Discs that cross or touch the rect's boundary: a sticker on the product's edge, not printed art inside it."""
    x, y, w, h = rect
    out = []
    for cx, cy, r in discs:
        inside = x - r < cx < x + w + r and y - r < cy < y + h + r
        to_edge = min(abs(cx - x), abs(cx - x - w), abs(cy - y), abs(cy - y - h))
        if inside and to_edge <= r + 2:
            out.append({"center": [cx, cy], "r": r})
    return out


def paint(img, discs):
    import cv2
    import numpy as np
    mask = np.zeros(img.shape[:2], np.uint8)
    for cx, cy, r in discs:
        cv2.circle(mask, (cx, cy), r + 4, 255, -1)
    return cv2.inpaint(img, mask, 7, cv2.INPAINT_TELEA)


def gutter_lines(region, axis):
    """Boolean per row (axis=1) or column (axis=0): the line is a uniform gutter."""
    import numpy as np
    med = np.median(region, axis=axis, keepdims=True)
    return (np.abs(region - med) <= GUTTER_TOL).mean(axis=axis) >= GUTTER_NEAR


def split_runs(flags):
    """[start, end) pieces between gutter runs of >= GUTTER_RUN; leading/trailing gutters are trimmed off."""
    n, pieces, start, k = len(flags), [], None, 0
    while k < n:
        if flags[k]:
            j = k
            while j < n and flags[j]:
                j += 1
            if j - k >= GUTTER_RUN or k == 0 or j == n:
                if start is not None:
                    pieces.append((start, k))
                    start = None
                k = j
                continue
            k = j
            continue
        if start is None:
            start = k
        k += 1
    if start is not None:
        pieces.append((start, n))
    return pieces


def cells(pieces, n):
    """Each piece widened to the middle of the gutters around it (the first / last to the region's ends)."""
    out = []
    for i, (a, b) in enumerate(pieces):
        lo = 0 if i == 0 else (pieces[i - 1][1] + a) // 2
        hi = n if i == len(pieces) - 1 else (b + pieces[i + 1][0]) // 2
        out.append((lo, hi))
    return out


def panels(gray, depth=4):
    """Recursive XY cut of a 2-D grey array at uniform gutters -> leaf rects (x, y, w, h), biggest first.
    A region is cut into cells at the middle of its gutters; a cell whose content trims down to something too
    small (a small object on a plain tile) is kept whole. Trimmed margins keep MARGIN px of breathing room so
    an edge of the product is never flush with the crop."""
    h, w = gray.shape
    out = []

    def fits(rw, rh):
        return rw >= PANEL_MIN * w and rh >= PANEL_MIN * h and rw * rh >= MIN_AREA * w * h

    def cut(x0, y0, x1, y1, d):
        tx0, ty0, tx1, ty1 = x0, y0, x1, y1
        for _ in range(2):          # twice: a white band under a photo hides the photo's plain side margin
            rows = split_runs(gutter_lines(gray[ty0:ty1, tx0:tx1], 1))
            if not rows:
                return 0
            ty0, ty1 = ty0 + rows[0][0], ty0 + rows[-1][1]
            cols = split_runs(gutter_lines(gray[ty0:ty1, tx0:tx1], 0))
            if not cols:
                return 0
            tx0, tx1 = tx0 + cols[0][0], tx0 + cols[-1][1]
        rows = split_runs(gutter_lines(gray[ty0:ty1, tx0:tx1], 1))
        cols = split_runs(gutter_lines(gray[ty0:ty1, tx0:tx1], 0))
        n = 0
        if d > 0 and len(rows) > 1:
            n = sum(cut(tx0, ty0 + a, tx1, ty0 + b, d - 1) for a, b in cells(rows, ty1 - ty0))
        elif d > 0 and len(cols) > 1:
            n = sum(cut(tx0 + a, ty0, tx0 + b, ty1, d - 1) for a, b in cells(cols, tx1 - tx0))
        if n:
            return n
        rx0, ry0 = max(x0, tx0 - MARGIN), max(y0, ty0 - MARGIN)
        rx1, ry1 = min(x1, tx1 + MARGIN), min(y1, ty1 + MARGIN)
        if not fits(rx1 - rx0, ry1 - ry0):
            if not fits(x1 - x0, y1 - y0) or (x1 - x0) * (y1 - y0) >= 0.9 * w * h:
                return 0
            rx0, ry0, rx1, ry1 = x0, y0, x1, y1                 # a small object on a plain tile: the tile
        out.append((rx0, ry0, rx1 - rx0, ry1 - ry0))
        return 1

    cut(0, 0, w, h, depth)
    if len(out) == 1 and out[0][2] * out[0][3] >= 0.9 * w * h:
        return []                                   # no real gutter: one photo, nothing to offer
    big = max(out, key=lambda r: r[2] * r[3])
    return [big, *sorted((r for r in out if r != big), key=lambda r: (r[1] // 40, r[0]))]   # then reading order


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("image")
    ap.add_argument("--out-dir", default=".")
    ap.add_argument("--n", type=int, default=4)
    ap.add_argument("--pad", type=int, default=0, help="px added around each crop (clamped to the image)")
    ap.add_argument("--paint-badge", action="store_true",
                    help="inpaint promo discs before cropping (only after Fix chose it; repaints product pixels)")
    ap.add_argument("--panels", action="store_true",
                    help="also offer gutter-split panels when rectangles were found (always on when none were)")
    a = ap.parse_args(argv)
    import cv2
    from PIL import Image, ImageDraw, ImageFont
    img = cv2.imread(a.image)
    if img is None:
        print(json.dumps({"problem": f"cannot read {a.image}"}))
        return 1
    h, w = img.shape[:2]
    import numpy as np
    boxes = candidates(img)
    pans = panels(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)) if a.panels or not boxes else []
    src_of = {r: "panel" for r in pans}
    src_of.update({r: "box" for r in boxes})
    rects = dedupe(boxes + pans)[: a.n] if a.panels else (boxes or pans)[: a.n]
    if not rects:
        print(json.dumps({"image": a.image, "candidates": [],
                          "problem": "no rectangle and no panel gutter: crop by position (product-image-prep.md §d)"}))
        return 1
    try:
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()
    except ImportError:
        ocr = None
    discs = badges(img)                           # printed art on the box is round and saturated too
    sticker = sorted({tuple(b["center"] + [b["r"]]) for r in rects for b in edge_badges(r, discs)})
    painted = bool(a.paint_badge and sticker)     # paint ONLY discs that cross a candidate's edge
    src = (Image.fromarray(cv2.cvtColor(paint(img, sticker), cv2.COLOR_BGR2RGB)) if painted
           else Image.open(a.image).convert("RGB"))
    out, tiles = [], []
    for i, (x, y, cw, ch) in enumerate(rects, 1):
        x0, y0 = max(0, x - a.pad), max(0, y - a.pad)
        x1, y1 = min(w, x + cw + a.pad), min(h, y + ch + a.pad)
        path = os.path.join(a.out_dir, f"box_C{i}.jpg")
        crop = src.crop((x0, y0, x1, y1))
        crop.save(path, "JPEG", quality=92)
        row = {"n": i, "file": path, "rect": [x0, y0, x1 - x0, y1 - y0], "wh": [x1 - x0, y1 - y0],
               "touches_edge": x0 == 0 or y0 == 0 or x1 == w or y1 == h,
               "src": src_of.get((x, y, cw, ch), "box")}
        on_edge = edge_badges((x, y, cw, ch), discs)
        if on_edge:
            row["badges"] = on_edge
            row["painted"] = painted
        if ocr:
            found, _ = ocr(path)
            row["text"] = [t.strip() for _, t, sc in (found or []) if float(sc) >= 0.6 and t.strip()]
        out.append(row)
        tiles.append((f"C{i} {x1 - x0}x{y1 - y0}" + ((" painted" if painted else " +badge") if on_edge else ""), crop))
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
           **({"badges": [list(d) for d in sticker]} if sticker else {}),
           "ask_vision": "Tiles C1..Cn are crops of one listing photo. Which ONE shows the WHOLE product (no part cut "
                         "off) with no shop wordmark, price, search bar or banner? Answer the tile label, or NONE "
                         "and what is wrong."}
    with open(os.path.join(a.out_dir, "box_crop.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    for r in out:
        print(f"C{r['n']} {r['src']} rect={r['rect']}" + (" EDGE" if r["touches_edge"] else "")
              + (f" text={r['text']}" if r.get("text") else ""))
    print(json.dumps(res, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
