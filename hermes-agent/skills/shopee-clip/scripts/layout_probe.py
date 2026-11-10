#!/usr/bin/env python3
"""Auto layout probe for presenter graphics (Fix 2026-11-07) - replaces per-frame vision reads.

For each time WINDOW it samples frames every --step s and returns, in 720x1280 coords:
  face   - union of detected faces over the window (OpenCV Haar, padded for hair) -> use as `avoid`
  empty_left / empty_right - the largest backdrop rectangle touching that frame edge that is
           free of person/props in EVERY sampled frame, within the band y 260-640 (below the pill
           band, above the subtitle band)
  overlay  - suggested {x, y, h} (centre + height) for a product cutout in the bigger empty side,
           sized to the product image's aspect when --product is given
Backdrop detection assumes Flow's plain pastel studio wall: a pixel is "busy" when it differs
from the wall colour sampled at the top corners. Vision-check ONE frame of the final render
anyway; this probe only removes the guesswork.

Usage:
  uv run --with "opencv-python-headless<5" --with numpy python layout_probe.py scene.mp4 \
      --window 0 1.4 --window 0.9 2.4 [--product bottle.jpg] [--offset 9.777] [--step 0.25]
--offset adds a constant to the printed window times (scene-local -> final timeline).
NOTE: opencv-python-headless 5.x ships NO Haar cascades - pin <5.
"""
import argparse, json, subprocess, sys
import numpy as np
import cv2

W, H = 720, 1280
BAND = (260, 640)       # below the pill band; bottom kept clear of the subtitle band AND the right-rail icons (y>=560 on TikTok/Shopee)
X_EDGE = 24             # keep the cutout this far from the frame edge (Reels side margin)
S = 4                     # work at 180x320


def frame(video, t):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
                          "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3)


CASC = None


def faces(img):
    global CASC
    if CASC is None:
        CASC = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    g = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    f = CASC.detectMultiScale(g, 1.1, 5, minSize=(90, 90))
    if len(f) == 0:
        return None
    x, y, w, h = max(f, key=lambda r: r[2] * r[3])
    # pad for hair / bangs / chin
    return [int(x), int(y - 0.12 * h), int(x + w), int(y + 1.05 * h)]   # Haar box is already wide; pad only bangs/chin


def busy(img, thr=34):
    sm = cv2.GaussianBlur(cv2.resize(img, (W // S, H // S), interpolation=cv2.INTER_AREA), (5, 5), 0).astype(np.int16)
    lab = cv2.cvtColor(sm.astype(np.uint8), cv2.COLOR_BGR2LAB).astype(np.int16)
    c = np.concatenate([lab[2:14, 2:14].reshape(-1, 3), lab[2:14, -14:-2].reshape(-1, 3)])
    wall = np.median(c, axis=0)
    # Flow walls are mottled + vignetted (darker toward the bottom/edges): estimate the wall per ROW
    # from the outermost columns, falling back to the corner colour where a person touches the edge
    edge = np.concatenate([lab[:, :3], lab[:, -3:]], axis=1)          # (rows, 6, 3)
    roww = np.median(edge, axis=1)                                     # (rows, 3)
    bad = np.sqrt(((roww - wall) ** 2).sum(axis=1)) > 30
    roww[bad] = wall
    # smooth the per-row wall vertically
    roww = cv2.GaussianBlur(roww.astype(np.float32).reshape(-1, 1, 3), (1, 21), 0).reshape(-1, 3)
    d = np.sqrt(((lab - roww[:, None, :]) ** 2).sum(axis=2))
    m = (d > thr).astype(np.uint8)
    return cv2.dilate(m, np.ones((5, 5), np.uint8))       # ~20 px safety margin


def best_edge_rect(empty, side, aspect=None):
    """Largest all-empty rectangle touching the left (side='L') or right edge, inside BAND."""
    y0, y1 = BAND[0] // S, BAND[1] // S
    sub = empty[y0:y1]
    rows, cols = sub.shape
    best = (0, None)
    # width from the edge per row = run length of empty cells from that edge
    run = np.zeros(rows, int)
    for r in range(rows):
        row = sub[r] if side == "L" else sub[r][::-1]
        k = 0
        while k < cols and row[k]:
            k += 1
        run[r] = k
    for top in range(rows):          # O(rows^2) is fine at ~110 rows
        mw = 10 ** 9
        for bot in range(top, rows):
            mw = min(mw, run[bot])
            if mw == 0:
                break
            rw, rh = mw * S, (bot - top + 1) * S
            # score = the cutout height this rect can actually hold (border+shadow ~42 px, edge inset)
            area = min(rh - 62, (min(rw, W) - 2 * X_EDGE - 54) / aspect) if aspect else rw * rh
            if area > best[0]:
                best = (area, (top, bot, mw))
    if not best[1]:
        return None
    top, bot, mw = best[1]
    ry0, ry1 = (top + y0) * S, (bot + 1 + y0) * S
    return [0, ry0, mw * S, ry1] if side == "L" else [W - mw * S, ry0, W, ry1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--window", nargs=2, type=float, action="append", required=True)
    ap.add_argument("--product"); ap.add_argument("--step", type=float, default=0.25)
    ap.add_argument("--offset", type=float, default=0.0)
    a = ap.parse_args()
    aspect = None
    if a.product:
        p = cv2.imread(a.product)
        aspect = p.shape[1] / p.shape[0]
    out = []
    for s, e in a.window:
        ts = list(np.arange(s, e + 1e-6, a.step)) or [s]
        acc, fl = None, []
        for t in ts:
            img = frame(a.video, float(t))
            b = busy(img)
            acc = b if acc is None else (acc | b)
            f = faces(img)
            if f:
                fl.append(f)
        # median box (robust to one false detection), then widen to cover the spread of real ones
        fu = None
        if fl:
            arr = np.array(fl)
            med = np.median(arr, axis=0)
            ok = arr[(np.abs(arr - med) < 80).all(axis=1)]
            ok = ok if len(ok) else arr
            fu = [int(ok[:, 0].min()), int(ok[:, 1].min()), int(ok[:, 2].max()), int(ok[:, 3].max())]
        empty = acc == 0
        L, R = best_edge_rect(empty, "L", aspect), best_edge_rect(empty, "R", aspect)
        area = (lambda r: 0 if not r else min(r[3] - r[1] - 62, (r[2] - r[0] - 2 * X_EDGE - 54) / aspect)) if aspect \
            else (lambda r: 0 if not r else (r[2] - r[0]) * (r[3] - r[1]))
        side = R if area(R) >= area(L) else L
        ov = None
        if side:
            # inset 12 px from the edge, 10 px vertically; cutout adds ~42 px of border/shadow
            side = [max(side[0], X_EDGE), side[1], min(side[2], W - X_EDGE), side[3]]
            bw, bh = side[2] - side[0] - 12, side[3] - side[1] - 20
            h = bh - 42
            if aspect:
                h = int(min(h, (bw - 42) / aspect))
            is_r = side[2] >= W - X_EDGE
            cx = (side[0] + side[2]) // 2
            ov = {"x": int(cx), "y": int((side[1] + side[3]) // 2), "h": int(max(0, h)), "side": "right" if is_r else "left"}
        out.append({"window": [round(s + a.offset, 3), round(e + a.offset, 3)], "face": fu,
                    "empty_left": L, "empty_right": R, "overlay": ov,
                    "note": None if (ov and ov["h"] >= 150) else "no empty side big enough - skip the overlay or shorten it"})
    for o in out:
        print(json.dumps(o, ensure_ascii=False, default=int))


if __name__ == "__main__":
    main()
