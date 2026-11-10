#!/usr/bin/env python3
"""Thai-language ASR of a voiceover take — verifies what the TTS actually said.

Why this exists: `asr_speech_spans.py` hardcodes `language="en"` (it is for English
trailers). Pointed at a Thai `vo.mp3` it returns fluent-looking garbage — the same short
ASCII token repeated for every phrase — which reads like a clean transcript at a glance
and hides skipped or invented words.

Usage (run through uv, from the work dir):
  uv run --with faster-whisper --with numpy python asr_th.py vo.mp3 [--model small]

Prints `start end text` per segment. Compare line by line against the `say` lines of the
VO plan: a phrase whose text is missing, doubled or shorter than its neighbours means the
engine skipped words — regenerate or cut, never build on it.
Note: whisper small renders Thai spelling roughly and can hallucinate the final particle;
call endings are checked by ear or with `--model medium`, not from this output alone.
"""
import argparse
import subprocess

import numpy as np
from faster_whisper import WhisperModel

ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("--model", default="small")
ap.add_argument("--language", default="th")
args = ap.parse_args()

# raw float32 array path: passing a file path to transcribe() crashes on Py3.14
# (av.open metadata_errors), so decode to PCM first.
raw = subprocess.run(["ffmpeg", "-v", "error", "-i", args.src, "-vn", "-ac", "1", "-ar", "16000",
                      "-f", "f32le", "-"], capture_output=True, check=True).stdout
a = np.frombuffer(raw, np.float32)
print(f"dur {len(a) / 16000:.2f}s language={args.language}")

m = WhisperModel(args.model, device="cpu", compute_type="int8")
segs, _ = m.transcribe(a, language=args.language, vad_filter=False, beam_size=5)
for s in segs:
    print(f"{s.start:6.2f} {s.end:6.2f} {s.text.strip()}")
