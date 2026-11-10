#!/usr/bin/env python3
"""Measure the metrics used to match Fix's reference clip
(references/audio-reference-matching.md).

Usage:
  uv run --with numpy python measure_audio.py <clip-or-audio> [...]

Per input prints: duration, integrated loudness / true peak / LRA
(ffmpeg ebur128), F0 mean/std/p10/p90 (autocorrelation, conf>0.40,
120-400 Hz), the 5-band profile relative to the 80-8000 Hz total over
the loudest 60% of frames, and pause fraction (frames below peak-30 dB).
Decode every input identically (16 kHz mono) or the comparison is
meaningless.
"""
import os
import re
import subprocess
import sys
import tempfile
import wave

import numpy as np

BANDS = {"80-300": (80, 300), "300-1k": (300, 1000), "1k-3k": (1000, 3000),
         "3k-6k": (3000, 6000), "6k-8k": (6000, 8000)}


def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)


def to_wav(src):
    dst = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    sh('ffmpeg -y -v error -i "%s" -ac 1 -ar 16000 "%s"' % (src, dst))
    return dst


def load(path):
    w = wave.open(path, "rb")
    sr = w.getframerate()
    x = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    if w.getnchannels() == 2:
        x = x.reshape(-1, 2).mean(axis=1)
    return x, sr


def loudness(src):
    o = sh('ffmpeg -hide_banner -i "%s" -af ebur128=peak=true -f null - 2>&1' % src).stdout
    i = re.findall(r"I:\s+(-?[\d.]+) LUFS", o)
    tp = re.findall(r"Peak:\s+(-?[\d.]+) dBFS", o)
    lra = re.findall(r"LRA:\s+(-?[\d.]+) LU", o)
    return (i[-1] if i else "?", tp[-1] if tp else "?", lra[-1] if lra else "?")


def f0_stats(x, sr, hop=160, wlen=480):
    vals = []
    for i in range(0, len(x) - wlen, hop):
        fr = x[i:i + wlen]
        if np.sqrt(np.mean(fr ** 2)) < 0.01:
            continue
        fr = fr - fr.mean()
        ac = np.correlate(fr, fr, "full")[wlen - 1:]
        lo, hi = int(sr / 400), int(sr / 110)
        k = int(np.argmax(ac[lo:hi])) + lo
        if ac[k] / (ac[0] + 1e-9) > 0.40 and 120 <= sr / k <= 400:
            vals.append(sr / k)
    g = np.array(vals)
    if len(g) < 10:
        return None
    return (round(float(g.mean()), 1), round(float(g.std()), 1),
            round(float(np.percentile(g, 10)), 1), round(float(np.percentile(g, 90)), 1))


def bands(x, sr, hop=320, wlen=1024):
    win = np.hanning(wlen)
    frames, lev = [], []
    for i in range(0, len(x) - wlen, hop):
        fr = x[i:i + wlen]
        lev.append(20 * np.log10(np.sqrt(np.mean(fr ** 2)) + 1e-9))
        frames.append(fr * win)
    lev = np.array(lev)
    act = np.where(lev > np.percentile(lev, 60))[0]
    if len(act) < 10:
        return None
    S = np.mean([np.abs(np.fft.rfft(frames[i])) for i in act], axis=0)
    f = np.fft.rfftfreq(wlen, 1 / sr)

    def bd(lo, hi):
        m = (f >= lo) & (f < hi)
        return 20 * np.log10(S[m].mean() + 1e-12)

    tot = bd(80, 8000)
    return dict((k, round(float(bd(*v) - tot), 1)) for k, v in BANDS.items())


def pause_frac(x, sr, hop=160, wlen=320):
    e = np.array([20 * np.log10(np.sqrt(np.mean(x[i:i + wlen] ** 2)) + 1e-9)
                  for i in range(0, len(x) - wlen, hop)])
    return round(float(np.mean(e < e.max() - 30)), 3)


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    for src in sys.argv[1:]:
        wav = to_wav(src)
        try:
            x, sr = load(wav)
            i, tp, lra = loudness(src)
            f0 = f0_stats(x, sr)
            b = bands(x, sr)
            print(os.path.basename(src))
            print("  dur=%.2fs  I=%s LUFS  TP=%s dBFS  LRA=%s LU" % (len(x) / sr, i, tp, lra))
            if f0:
                print("  F0 mean=%s std=%s p10=%s p90=%s Hz" % f0)
            if b:
                print("  bands(rel 80-8k):", b)
            print("  pause_frac=%s" % pause_frac(x, sr))
        finally:
            os.unlink(wav)


if __name__ == "__main__":
    main()
