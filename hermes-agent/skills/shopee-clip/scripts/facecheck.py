#!/usr/bin/env python3
"""facecheck.py — is the presenter's face in this still? (start-frame pick for the next 🧑 shot)

  uv run --with 'opencv-python-headless<5' --with numpy python facecheck.py frame.jpg
  -> {"face": true|false, "box": [x0, y0, x1, y1] | null, "hits": [[x, y, w, h, skin], ...]} on stdout, exit 0;
     exit 2 = unreadable image

Why (uneed-pb-1, 2026-11-18): shot 2 was hands only, its last frame became shot 3's start frame, and Flow
drew a new woman for shot 3 three times running ("Gen ยังไงก็หน้าไม่ตรง"). clipjob.py uses this to take the
start frame from the newest earlier shot whose last frame still shows her face.

Haar alone is not enough: on that hands-only frame it boxed the cardigan's knit (97 px). A hit counts only
when the middle of its box is mostly skin (YCrCb, the same thresholds as pillclear.py) and it is at least
MIN_PX wide (a palm held to the camera is skin too, but small).
"""
import json
import sys

import cv2
import numpy as np

W, H = 720, 1280
MIN_PX = 150         # measured 2026-11-19 on 6 shots (52 frames): her face 230-505 px; palms boxed at 94-140 px
SKIN_MIN = 0.35      # middle 60 % of the box: faces 0.82-0.98, knit/phone false hits 0.00-0.08


def skin_share(img, x, y, w, h):
    """img BGR. Middle 60 % of the box: hair and background at the box edge are not counted."""
    a = img[y + h // 5: y + h - h // 5, x + w // 5: x + w - w // 5].astype(np.float32)
    if not a.size:
        return 0.0
    b, g, r = a[..., 0], a[..., 1], a[..., 2]
    cr = 128 + 0.5 * r - 0.4187 * g - 0.0813 * b
    cb = 128 - 0.1687 * r - 0.3313 * g + 0.5 * b
    luma = 0.299 * r + 0.587 * g + 0.114 * b
    skin = (cr > 135) & (cr < 175) & (cb > 85) & (cb < 128) & (luma > 90)
    return float(skin.mean())


def detect(img):
    """-> (box or None, hits). img = BGR at any size; scaled to 720x1280 like every clip frame."""
    img = cv2.resize(img, (W, H))
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    g = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
    hits = [[int(x), int(y), int(w), int(h), round(skin_share(img, x, y, w, h), 3)]
            for x, y, w, h in casc.detectMultiScale(g, 1.1, 5, minSize=(MIN_PX, MIN_PX))]
    real = [h for h in hits if h[4] >= SKIN_MIN]
    if not real:
        return None, hits
    x, y, w, h, _ = max(real, key=lambda r: r[2] * r[3])
    return [x, y, x + w, y + h], hits


def main():
    img = cv2.imread(sys.argv[1]) if len(sys.argv) == 2 else None
    if img is None:
        print(json.dumps({"error": "unreadable image"}))
        return 2
    box, hits = detect(img)
    print(json.dumps({"face": box is not None, "box": box, "hits": hits}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
