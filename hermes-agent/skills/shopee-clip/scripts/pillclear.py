#!/usr/bin/env python3
"""Keep a caption pill off the presenter's face.

The pill band is fixed (y 196-252, centred). In a close-up the face fills that band and the pill lands on her
forehead or nose (venita-sunscreen shot 2, 2026-11-16: `GEL TEXTURE` across the eyes for 2.5 s). This module
measures how much of the pill's rectangle is skin over the scene and moves the pill, inside its own scene, to
the nearest window where it is not. No window = the pill is dropped and the report says so; it is never left
on the face and never moved to another scene.

Measured on the real scenes: hair and wall under the pill read 0.15-0.57 skin, a close-up face 0.69-0.93.

Skin share alone misses a medium / full-body shot (yuedpao-rushbag 2026-11-25: her ~140 px face plus orange hair
under a 230 px pill read 0.44-0.65, so `No Bounce` and `Link below!` sat on her forehead and eyes). So the pill
also slides SIDEWAYS: the head box (Haar face, padded for hair) is measured over the pill's window, and a pill
that would touch it moves left or right of the head inside the same band (y 196-252, so every reader of the
pill band stays right), shrinking from 40 to 30 pt to fit. The band's sides are free on every app (the right
rails start at y 560, the top bars end at y 192); X_MIN/X_MAX keep Meta's 6 % side margin. No room beside the
head = the old path: move in time inside the scene, or drop (the CTA goes to autogfx as a headline instead).

  pillclear.py scene.mp4 [--text "GEL TEXTURE"]      # prints the skin share every 0.25 s (debug)
  pillclear.py faces scene.mp4 [--ss S] [--dur D]    # head boxes every 0.25 s as JSON (needs cv2)
"""
import json
import os
import subprocess
import sys

W, H = 720, 1280
PILL_Y, PILL_H = 196, 56
STEP = 0.25
ON_FACE = 0.62          # mean skin share of the pill rect over its window
ON_FACE_PEAK = 0.75     # or any single sample above this
MIN_DUR = 1.5
GAP = 0.2               # kept between two pills
X_MIN, X_MAX = 60, 660  # pill box inside these columns when it slides beside the head
FONTS = (40, 38, 36, 34, 32, 30)    # biggest that fits beside the head (yuedpao: `No Bounce` 32, `Link below!` 30;
                                    # the CTA otherwise becomes a headline on her torso)
HAIR_X, HAIR_TOP = 0.2, 0.5     # head = Haar face box widened by 0.2 w a side and raised by 0.5 h (yuedpao: hair
SLOT_GAP = 10                   # top 57 px over a 140 px box, hair 21-29 px beside it in the pill rows)
FACE_MIN = 60           # Haar minSize: a full-body face is 103-145 px (yuedpao); smaller hits were hands / shirt
SKIN_MIN = 0.35         # facecheck.py: middle 60 % of a real face box is 0.82-0.98 skin, knit / phone 0.00-0.08


def pill_width(text):
    """Fredoka 40 runs ~24 px a glyph; the box adds 14 px each side."""
    return int(min(560, max(120, 24 * len(text) + 28)))


def on_face(series, t0, t1, step=STEP):
    """series = skin share sampled every `step` s from the scene's first kept frame."""
    i0, i1 = int(t0 / step + 0.999), int(t1 / step)
    s = series[i0:i1 + 1]
    if not len(s):
        return False
    return sum(s) / len(s) > ON_FACE or max(s) > ON_FACE_PEAK


def place(series, t0, t1, lo, hi, taken=(), step=STEP):
    """Where a pill planned for scene-local [t0, t1] may show: the same window when it is clear of the face,
    else the nearest clear window inside [lo, hi] that misses every `taken` span (first at full length, then
    shorter down to MIN_DUR). Returns (t0, t1) or None when the scene has no such window."""
    got = relocate(lambda a, b: None if on_face(series, a, b, step) else True, t0, t1, lo, hi, taken, step)
    return got and got[:2]


def relocate(fit, t0, t1, lo, hi, taken=(), step=STEP):
    """place() for any test: `fit(a, b)` -> a slot (truthy) or None. Returns (t0, t1, slot) or None."""
    def free(a, b):
        return all(b + GAP <= x0 or a >= x1 + GAP for x0, x1 in taken)

    got = fit(t0, t1)
    if got is not None:
        return (t0, t1, got)
    dur = t1 - t0
    while dur >= MIN_DUR - 1e-6:
        best, a = None, lo
        while a + dur <= hi + 1e-6:
            if free(a, a + dur) and (best is None or abs(a - t0) < abs(best[0] - t0)):
                got = fit(a, a + dur)
                if got is not None:
                    best = (a, got)
            a = round(a + step, 3)
        if best is not None:
            return (round(best[0], 2), round(best[0] + dur, 2), best[1])
        dur = round(dur - 0.5, 3)
    return None


def head_box(boxes):
    """Face boxes [x0, y0, x1, y1] sampled over one window (None = no face in that sample) -> her head with
    hair as one rect, or None when no sample found a face. One stray box (shirt, hand) is dropped by the median."""
    fl = [b for b in boxes if b]
    if not fl:
        return None
    med = [sorted(c)[len(c) // 2] for c in zip(*fl)]
    ok = [b for b in fl if all(abs(v - m) < 80 for v, m in zip(b, med))] or fl
    w, h = med[2] - med[0], med[3] - med[1]
    return [int(min(b[0] for b in ok) - HAIR_X * w), int(min(b[1] for b in ok) - HAIR_TOP * h),
            int(max(b[2] for b in ok) + HAIR_X * w), int(max(b[3] for b in ok))]


def _hits(head, x0, x1):
    return head[1] < PILL_Y + PILL_H and head[3] > PILL_Y and head[0] < x1 and head[2] > x0


def slot(head, width):
    """-> (x of the pill box's left edge, font) or None. `width(font)` = the box width in px. Centred at 40 pt
    when that misses the head (x None = keep ffmpeg's own centring), else beside the head on the side with more
    room at the biggest font that fits."""
    w = width(40)
    if head is None or not _hits(head, (W - w) // 2 - SLOT_GAP, (W + w) // 2 + SLOT_GAP):
        return (None, 40)
    for f in FONTS:
        w = width(f)
        rooms = [(lo, hi) for lo, hi in ((X_MIN, head[0] - SLOT_GAP), (head[2] + SLOT_GAP, X_MAX)) if hi - lo >= w]
        if rooms:
            lo, hi = max(rooms, key=lambda r: r[1] - r[0])
            return ((lo + hi - w) // 2, f)
    return None


def width_fn(font_path):
    """Pill box width per font size: Fredoka advance + boxborderw 14 a side + borderw 3 a side."""
    try:
        from PIL import ImageFont
        fonts = {}

        def width(text, size):
            if size not in fonts:
                fonts[size] = ImageFont.truetype(font_path, size)
            return int(round(fonts[size].getlength(text))) + 34
        width("x", 40)
        return width
    except Exception:
        return lambda text, size: int(pill_width(text) * size / 40)


def _skin(r, g, b):
    cr = 128 + 0.5 * r - 0.4187 * g - 0.0813 * b
    cb = 128 - 0.1687 * r - 0.3313 * g + 0.5 * b
    y = 0.299 * r + 0.587 * g + 0.114 * b
    return (cr > 135) & (cr < 175) & (cb > 85) & (cb < 128) & (y > 90)


def face_boxes(video, ss=0.0, dur=None, step=STEP):
    """The biggest Haar face whose middle is skin, one sample every `step` s from `ss`: [[x0, y0, x1, y1] | None].
    Needs cv2 (opencv-python-headless<5 ships the cascades); post_presenter calls measure_faces()."""
    import cv2
    import numpy as np
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}", "-i", video]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-vf", f"fps={1 / step},scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    casc = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    out = []
    for i in range(len(raw) // (W * H * 3)):
        img = np.frombuffer(raw[i * W * H * 3:(i + 1) * W * H * 3], np.uint8).reshape(H, W, 3)
        g = cv2.equalizeHist(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY))
        box = None
        for x, y, w, h in sorted(casc.detectMultiScale(g, 1.1, 5, minSize=(FACE_MIN, FACE_MIN)),
                                 key=lambda r: -r[2] * r[3]):
            a = img[y + h // 5:y + h - h // 5, x + w // 5:x + w - w // 5].astype(np.float32)
            if a.size and _skin(a[..., 2], a[..., 1], a[..., 0]).mean() >= SKIN_MIN:
                box = [int(x), int(y), int(x + w), int(y + h)]
                break
        out.append(box)
    return out


def measure_faces(video, ss=0.0, dur=None, step=STEP):
    """face_boxes() in a uv subprocess (post_presenter's own env has no cv2). None = not measured."""
    cmd = ["uv", "run", "-q", "--with", "opencv-python-headless<5", "--with", "numpy", "python",
           os.path.abspath(__file__), "faces", video, "--ss", str(ss), "--step", str(step)]
    if dur:
        cmd += ["--dur", str(dur)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=True)
        return json.loads(r.stdout)
    except Exception:
        return None


def window(samples, a, b, step=STEP):
    """The samples of scene-local [a, b] (same indexing as on_face)."""
    return samples[int(a / step + 0.999):int(b / step) + 1]


def skin_series(video, text, ss=0.0, dur=None, step=STEP):
    """Skin share of the pill's rectangle, one value every `step` s of `video` from `ss`."""
    import numpy as np
    w = pill_width(text)
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}", "-i", video]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-vf", f"fps={1 / step},scale={W}:{H},crop={w}:{PILL_H}:{(W - w) // 2}:{PILL_Y}",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    n = len(raw) // (w * PILL_H * 3)
    if not n:
        return []
    a = np.frombuffer(raw[:n * w * PILL_H * 3], np.uint8).reshape(n, PILL_H, w, 3).astype(np.float32)
    skin = _skin(a[..., 0], a[..., 1], a[..., 2])
    return [round(float(v), 3) for v in skin.reshape(n, -1).mean(axis=1)]


def _arg(name, default=None):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


if __name__ == "__main__":
    if sys.argv[1] == "faces":
        d = _arg("--dur")
        print(json.dumps(face_boxes(sys.argv[2], float(_arg("--ss", 0)), float(d) if d else None,
                                    float(_arg("--step", STEP)))))
    else:
        print(" ".join(f"{int(v * 100)}" for v in skin_series(sys.argv[1], _arg("--text", "GEL TEXTURE"))))
