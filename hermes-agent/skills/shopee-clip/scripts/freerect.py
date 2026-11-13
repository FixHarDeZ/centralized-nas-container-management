#!/usr/bin/env python3
"""Free-rect map — find backdrop areas free in EVERY sampled frame.

The fallback when `layout_probe.py` answers `no empty side big enough`
(references/presenter-graphics.md -> Lessons -> Free-rect map).

Usage:
  uv run --with numpy python freerect.py <scene.mp4> <t1,t2,...> [--cell 20] [--thr 26]

Prints one ASCII row per `cell` px (y in the label, x labelled every 100 px):
  '.' free in every sampled frame, '#' busy in at least one.

wall colour per frame = median of the outermost 8 px of the left and right edge
columns over rows 100-1200; a cell is busy when the median per-pixel |px - wall|
summed over RGB exceeds --thr in ANY frame.

Sample times must sit strictly INSIDE the scene (last sample ~0.5 s before the
duration): ffmpeg returns an empty frame at or past the end. Pick the largest free
block outside y186-262 (pill band) and y700-835 (sub band), then vision-check one
frame of the render as usual.
"""
import argparse
import subprocess
import sys

import numpy as np


def ffprobe(path, args):
    return subprocess.run(["ffprobe", "-v", "error"] + args + [path],
                          capture_output=True, text=True, check=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("scene")
    ap.add_argument("times", help="comma-separated seconds, strictly inside the scene")
    ap.add_argument("--cell", type=int, default=20)
    ap.add_argument("--thr", type=float, default=26)
    a = ap.parse_args()

    w, h = (int(v) for v in ffprobe(a.scene, ["-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0"]).split(",")[:2])
    dur = float(ffprobe(a.scene, ["-show_entries", "format=duration", "-of", "csv=p=0"]))

    times = [float(t) for t in a.times.split(",") if t.strip()]
    bad = [t for t in times if t >= dur - 0.05]
    if bad:
        sys.exit(f"sample time(s) {bad} at/past the scene end ({dur:.2f} s) — "
                 f"ffmpeg returns an empty frame there; keep every window end ~0.5 s under it")

    need = w * h * 3
    frames = []
    for t in times:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(t), "-i", a.scene,
                              "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                             capture_output=True).stdout
        if len(raw) != need:
            sys.exit(f"t={t}: got {len(raw)} bytes, expected {need} (empty frame)")
        frames.append(np.frombuffer(raw, np.uint8).reshape(h, w, 3).astype(np.int16))

    # wall colour per frame: median of the outermost 8 px of both edge columns, rows 100-1200
    walls = []
    for f in frames:
        edge = np.concatenate([f[100:1200, :8], f[100:1200, -8:]], axis=0)
        walls.append(np.median(edge.reshape(-1, 3), axis=0))

    cell = a.cell
    cols, rows = w // cell, h // cell
    busy = np.zeros((rows, cols), dtype=bool)
    for f, wall in zip(frames, walls):
        for r in range(rows):
            for c in range(cols):
                block = f[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell]
                d = np.abs(block - wall).sum(axis=2)      # per-pixel |px - wall| over RGB
                busy[r, c] |= float(np.median(d)) > a.thr

    hdr = "      " + "".join(str((c * cell // 100) % 10) if c * cell % 100 == 0 else " "
                             for c in range(cols))
    print(hdr)
    for r in range(rows):
        y = r * cell
        band = "  <- pill band" if 186 <= y < 262 else ("  <- sub band" if 700 <= y < 835 else "")
        print(f"{y:5d} " + "".join("#" if busy[r, c] else "." for c in range(cols)) + band)
    print(f"\ncells {cell}px, busy when median |px-wall| > {a.thr} in any of "
          f"{len(frames)} frames; free = '.' (pick a block outside both bands)")


if __name__ == "__main__":
    main()
