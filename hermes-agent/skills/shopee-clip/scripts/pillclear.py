#!/usr/bin/env python3
"""Keep a caption pill off the presenter's face.

The pill band is fixed (y 196-252, centred). In a close-up the face fills that band and the pill lands on her
forehead or nose (venita-sunscreen shot 2, 2026-11-16: `GEL TEXTURE` across the eyes for 2.5 s). This module
measures how much of the pill's rectangle is skin over the scene and moves the pill, inside its own scene, to
the nearest window where it is not. No window = the pill is dropped and the report says so; it is never left
on the face and never moved to another scene.

Measured on the real scenes: hair and wall under the pill read 0.15-0.57 skin, a close-up face 0.69-0.93.

  pillclear.py scene.mp4 [--text "GEL TEXTURE"]      # prints the skin share every 0.25 s (debug)
"""
import subprocess
import sys

W, H = 720, 1280
PILL_Y, PILL_H = 196, 56
STEP = 0.25
ON_FACE = 0.62          # mean skin share of the pill rect over its window
ON_FACE_PEAK = 0.75     # or any single sample above this
MIN_DUR = 1.5
GAP = 0.2               # kept between two pills


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
    def free(a, b):
        return all(b + GAP <= x0 or a >= x1 + GAP for x0, x1 in taken)

    if not on_face(series, t0, t1, step):
        return (t0, t1)
    dur = t1 - t0
    while dur >= MIN_DUR - 1e-6:
        best, a = None, lo
        while a + dur <= hi + 1e-6:
            clear = free(a, a + dur) and not on_face(series, a, a + dur, step)
            if clear and (best is None or abs(a - t0) < abs(best - t0)):
                best = a
            a = round(a + step, 3)
        if best is not None:
            return (round(best, 2), round(best + dur, 2))
        dur = round(dur - 0.5, 3)
    return None


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
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    cr = 128 + 0.5 * r - 0.4187 * g - 0.0813 * b
    cb = 128 - 0.1687 * r - 0.3313 * g + 0.5 * b
    y = 0.299 * r + 0.587 * g + 0.114 * b
    skin = (cr > 135) & (cr < 175) & (cb > 85) & (cb < 128) & (y > 90)
    return [round(float(v), 3) for v in skin.reshape(n, -1).mean(axis=1)]


if __name__ == "__main__":
    text = sys.argv[sys.argv.index("--text") + 1] if "--text" in sys.argv else "GEL TEXTURE"
    print(" ".join(f"{int(v * 100)}" for v in skin_series(sys.argv[1], text)))
