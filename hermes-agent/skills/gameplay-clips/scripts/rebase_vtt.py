#!/usr/bin/env python3
"""Rebase a speech WEBVTT (absolute source times) onto a master encoded from `-ss S`.

Usage:  python3 rebase_vtt.py speech.vtt S subs.en.vtt
  - Subtracts S from every cue, drops cues that end before S, clamps starts to 0.
  - Output keeps the `HH:MM:SS.mmm --> HH:MM:SS.mmm align:start position:0%` header
    and the cue body lines, which is the format build_v5.py's vtt_gaps() parses.
Use it when asr_speech_spans.py was run on the full source (no --rebase), but the
master was encoded from a window starting at S.
"""
import sys


def sec(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def fmt(x):
    h = int(x // 3600)
    m = int((x - h * 3600) // 60)
    s = x - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


if __name__ == "__main__":
    src, start, dst = sys.argv[1], float(sys.argv[2]), sys.argv[3]
    out = ["WEBVTT", ""]
    for blk in open(src, encoding="utf-8").read().split("\n\n")[1:]:
        lines = blk.strip().splitlines()
        if not lines or "-->" not in lines[0]:
            continue
        a, b = [sec(x.strip().split()[0]) for x in lines[0].split("-->")]
        a, b = a - start, b - start
        if b <= 0:
            continue
        out += [f"{fmt(max(a, 0.0))} --> {fmt(b)} align:start position:0%", *lines[1:], ""]
    open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")
    print(f"wrote {dst}")
