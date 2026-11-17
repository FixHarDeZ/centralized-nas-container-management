#!/usr/bin/env python3
"""ocr_scan.py — timed OCR text map of a video window (the §5d gate).

Run: uv run --with rapidocr-onnxruntime --with numpy --with pillow \
         python ocr_scan.py SRC START END OUT.json [STEP]

STEP defaults to 1.0 s; pass 0.5 when a short caption is suspected (sub-second
check the 1 fps map can miss). Extracts one frame per step with ffmpeg and runs
RapidOCR on each, writing {t: [{text, box, score}]} (times in source seconds) plus
one stdout line per frame WITH text, so the map can be read without opening files.
On a long source scan only the speech-gap windows (±1 s), never the whole file.
Keep text printed ON the scene (costume/device logos), drop burned-in supers —
footage-sourcing §5d.
"""
import json
import os
import subprocess
import sys

from rapidocr_onnxruntime import RapidOCR

src, t0, t1, out = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
step = float(sys.argv[5]) if len(sys.argv) > 5 else 1.0

ocr = RapidOCR()
times = []
t = t0
while t < t1:
    times.append(round(t, 2))
    t += step

result = {}
for t in times:
    frame = f"_ocr_{t}.jpg"
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(t), "-i", src,
                    "-frames:v", "1", "-update", "1", frame], check=True)
    try:
        found, _ = ocr(frame)
        items = []
        if found:
            for box, txt, score in found:
                if txt.strip():
                    items.append({"text": txt.strip(),
                                  "box": [[int(v) for v in p] for p in box],
                                  "score": round(float(score), 3)})
        if items:
            result[str(t)] = items
    finally:
        if os.path.exists(frame):
            os.remove(frame)

json.dump(result, open(out, "w"), ensure_ascii=False, indent=1)
print(f"src={src} step={step} {len(times)} frames, {len(result)} with text -> {out}")
for t in sorted(result, key=float):
    print(f"{t} | " + " / ".join(i["text"] for i in result[t])[:140])
