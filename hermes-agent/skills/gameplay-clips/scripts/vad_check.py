#!/usr/bin/env python3
"""vad_check.py — second opinion on whether a window contains speech.

Run: uv run --with faster-whisper --with numpy python vad_check.py SRC START DUR

Decodes [START, START+DUR) to 16 kHz mono f32le and runs faster-whisper's silero VAD
(vad_filter=True, no transcription), so music-only audio reports zero spans. Use it when
ASR came back with only round-time ghost hits: no VAD speech AND no auto-captions
(yt-dlp --list-subs) = the window is music-only and safe to cut (footage-sourcing §3).
Prints each detected speech span in absolute source times, or "no speech detected".
"""
import subprocess
import sys

import numpy as np
from faster_whisper import WhisperModel

src, start, dur = sys.argv[1], float(sys.argv[2]), float(sys.argv[3])
raw = subprocess.run(
    ["ffmpeg", "-v", "error", "-ss", str(start), "-t", str(dur), "-i", src,
     "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
    capture_output=True, check=True).stdout
arr = np.frombuffer(raw, dtype=np.float32)
print(f"src={src} window={start}-{start + dur:.2f} samples={len(arr)} dur={len(arr) / 16000:.2f}")
if len(arr) < 1600:
    sys.exit("window too short")
model = WhisperModel("small", device="cpu", compute_type="int8")
segments, _ = model.transcribe(arr, language="en", vad_filter=True, beam_size=1)
spans = 0
for s in segments:
    spans += 1
    print(f"  VAD-speech {start + s.start:.2f}-{start + s.end:.2f}: {s.text!r}")
print("VAD: no speech detected" if spans == 0 else f"VAD: {spans} span(s)")
