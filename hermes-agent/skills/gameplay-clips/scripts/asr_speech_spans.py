#!/usr/bin/env python3
"""ASR a media range with faster-whisper and emit speech spans + a WEBVTT for build_v5.

Why: yt-dlp auto-subs can miss whole stretches of in-game dialogue, so VTT-derived
silent gaps are false. ASR on the audio is the ground truth for "no speech here".

Usage (run through uv, from the work dir):
  uv run --with faster-whisper --with numpy python asr_speech_spans.py SRC.mp4 \
      --start 0 --dur 200 --out-json asr.json --out-vtt speech.vtt [--rebase 0]

  --start/--dur  ASR window on SRC (absolute seconds in SRC).
  --rebase       subtract this from every output time (use the -ss you gave when
                 encoding the master, so speech.vtt matches the master timeline).
  Prints the silent gaps >= 1.5 s (rebased) so you can pick seg windows.

Notes:
  - Raw float32 array path; passing a file path to transcribe() can crash on Py3.14
    with av.open metadata_errors.
  - Whisper hallucinates on music-only audio. A short isolated hit ("Thank you") with
    no frame evidence is noise; keep it out of spans only after a frame check.
  - Pads each span by 0.1 s on each side. Gaps are computed on the same padded spans.
"""
import argparse, json, subprocess
import numpy as np
from faster_whisper import WhisperModel

ap = argparse.ArgumentParser()
ap.add_argument("src")
ap.add_argument("--start", type=float, default=0.0)
ap.add_argument("--dur", type=float, required=True)
ap.add_argument("--rebase", type=float, default=0.0)
ap.add_argument("--out-json", default="asr.json")
ap.add_argument("--out-vtt", default="speech.vtt")
ap.add_argument("--model", default="small")
ap.add_argument("--gap-min", type=float, default=1.5)
args = ap.parse_args()

raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(args.start), "-t", str(args.dur), "-i", args.src,
                      "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                     capture_output=True, check=True).stdout
a = np.frombuffer(raw, np.float32)
m = WhisperModel(args.model, device="cpu", compute_type="int8")
segs, _ = m.transcribe(a, language="en", vad_filter=False, beam_size=1)

rows = []
for s in segs:
    t0 = s.start + args.start - args.rebase
    t1 = s.end + args.start - args.rebase
    rows.append((round(t0, 2), round(t1, 2), s.text.strip()))
json.dump(rows, open(args.out_json, "w", encoding="utf-8"), ensure_ascii=False, indent=0)

def ft(t):
    t = max(0.0, t)
    return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:06.3f}"

lines = ["WEBVTT", ""]
spans = []
for t0, t1, txt in rows:
    a0, a1 = max(0.0, t0 - 0.1), t1 + 0.1
    if spans and a0 <= spans[-1][1] + 0.05:
        spans[-1][1] = max(spans[-1][1], a1)
    else:
        spans.append([a0, a1])
for a0, a1 in spans:
    lines += [f"{ft(a0)} --> {ft(a1)} align:start position:0%", "speech", ""]
open(args.out_vtt, "w", encoding="utf-8").write("\n".join(lines))

print(f"{len(rows)} ASR segments, {len(spans)} speech spans -> {args.out_vtt}")
gaps, prev = [], 0.0
for a0, a1 in spans:
    if a0 - prev >= args.gap_min:
        gaps.append((round(prev, 2), round(a0, 2)))
    prev = max(prev, a1)
end = args.dur + args.start - args.rebase
if end - prev >= args.gap_min:
    gaps.append((round(prev, 2), round(end, 2)))
print("silent gaps >= %.1fs (rebased):" % args.gap_min, gaps)
