#!/usr/bin/env python3
"""beats.py — beat/onset times for a time range of a media file's audio (numpy only).

Usage:
  uv run --with numpy python beats.py master.mp4 [--start 60 --end 70] [--pad 4] [--bpm-min 70 --bpm-max 180] [--json out.json]

Method:
  1. ffmpeg decodes mono 22050 Hz float32 for [start-pad, end+pad] (pad gives the tracker context).
  2. STFT (2048 win, 512 hop ~ 23 ms) -> log-magnitude spectral flux (positive diff, summed over bins)
     -> onset envelope, mean-removed, half-wave rectified, normalised.
  3. Tempo = argmax of the onset-envelope autocorrelation in [bpm-min, bpm-max], weighted by a
     log-gaussian prior centred on 120 BPM (avoids picking half/double tempo); parabolic refinement.
  4. Beat phase = offset that maximises summed envelope on the period grid; each grid beat is then
     snapped to the strongest envelope peak within +-12% of a period (keeps the grid but follows the music).
  5. Onsets = local maxima of the envelope above mean+1 std (useful for impact-style cuts).
Output (stdout, JSON): {"start","end","bpm","period","beats":[abs seconds...],"onsets":[...],"strength":[per beat 0..1]}
Times are absolute in the source file and limited to [start, end].
"""
import argparse, json, subprocess, sys
import numpy as np

SR = 22050
HOP = 512
WIN = 2048


def load(path, t0, t1):
    dur = max(0.1, t1 - t0)
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{t0:.3f}", "-t", f"{dur:.3f}", "-i", path,
           "-vn", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).astype(np.float64)


def onset_env(x):
    if len(x) < WIN:
        x = np.pad(x, (0, WIN - len(x)))
    n = 1 + (len(x) - WIN) // HOP
    idx = np.arange(WIN)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx] * np.hanning(WIN)[None, :]
    mag = np.abs(np.fft.rfft(frames, axis=1))
    logm = np.log1p(1000.0 * mag)
    flux = np.maximum(0.0, np.diff(logm, axis=0)).sum(axis=1)
    flux = np.concatenate([[0.0], flux])
    # light smoothing (3 frames) and adaptive mean removal (~0.5 s)
    flux = np.convolve(flux, np.ones(3) / 3, mode="same")
    k = max(1, int(0.5 * SR / HOP))
    loc = np.convolve(flux, np.ones(k) / k, mode="same")
    env = np.maximum(0.0, flux - loc)
    if env.max() > 0:
        env = env / env.max()
    return env  # frame i is at time i*HOP/SR


def tempo(env, bpm_min, bpm_max):
    fps = SR / HOP
    e = env - env.mean()
    ac = np.correlate(e, e, mode="full")[len(e) - 1:]
    ac = ac / (ac[0] + 1e-9)
    lags = np.arange(len(ac))
    lo = int(fps * 60 / bpm_max)
    hi = min(len(ac) - 2, int(fps * 60 / bpm_min))
    if hi <= lo + 1:
        return 120.0, 0.0
    bpm = 60 * fps / np.maximum(lags[lo:hi + 1], 1)
    prior = np.exp(-0.5 * (np.log2(bpm / 120.0) / 0.9) ** 2)
    score = ac[lo:hi + 1] * prior
    i = int(np.argmax(score)) + lo
    # parabolic refinement of the peak
    if lo < i < hi:
        a, b, c = ac[i - 1], ac[i], ac[i + 1]
        den = a - 2 * b + c
        off = 0.5 * (a - c) / den if abs(den) > 1e-12 else 0.0
    else:
        off = 0.0
    lag = i + off
    return 60 * fps / lag, float(ac[i])


def track(env, period_frames):
    n = len(env)
    p = period_frames
    best, best_phase = -1, 0.0
    for ph in np.arange(0, p, 0.25):
        pos = np.arange(ph, n, p)
        s = env[np.clip(np.round(pos).astype(int), 0, n - 1)].sum()
        if s > best:
            best, best_phase = s, ph
    beats = []
    w = max(1, int(round(0.12 * p)))
    for g in np.arange(best_phase, n, p):
        gi = int(round(g))
        a, b = max(0, gi - w), min(n, gi + w + 1)
        if a >= b:
            continue
        j = a + int(np.argmax(env[a:b]))
        # only move off-grid when the peak is clearly stronger than the grid point
        beats.append(j if env[j] > 1.3 * env[min(gi, n - 1)] + 1e-6 else gi)
    return np.array(beats, dtype=float)


def analyse(path, start, end, pad=4.0, bpm_min=70, bpm_max=180):
    t0 = max(0.0, start - pad)
    x = load(path, t0, end + pad)
    env = onset_env(x)
    fps = SR / HOP
    bpm, conf = tempo(env, bpm_min, bpm_max)
    period = 60.0 / bpm
    bf = track(env, period * fps)
    beats = t0 + bf / fps
    strength = env[np.clip(bf.astype(int), 0, len(env) - 1)]
    keep = (beats >= start - 1e-6) & (beats <= end + 1e-6)
    thr = env.mean() + env.std()
    pk = [i for i in range(1, len(env) - 1) if env[i] > thr and env[i] >= env[i - 1] and env[i] > env[i + 1]]
    ons = [round(t0 + i / fps, 3) for i in pk if start <= t0 + i / fps <= end]
    return {"start": start, "end": end, "bpm": round(bpm, 2), "period": round(period, 4),
            "tempo_conf": round(conf, 3),
            "beats": [round(float(b), 3) for b in beats[keep]],
            "strength": [round(float(s), 3) for s in strength[keep]],
            "onsets": ons}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("media")
    ap.add_argument("--start", type=float, default=0.0)
    ap.add_argument("--end", type=float, default=None)
    ap.add_argument("--pad", type=float, default=4.0)
    ap.add_argument("--bpm-min", type=float, default=70)
    ap.add_argument("--bpm-max", type=float, default=180)
    ap.add_argument("--json")
    a = ap.parse_args()
    end = a.end
    if end is None:
        d = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", a.media],
                           capture_output=True, text=True).stdout.strip()
        end = float(d)
    r = analyse(a.media, a.start, end, a.pad, a.bpm_min, a.bpm_max)
    s = json.dumps(r)
    if a.json:
        open(a.json, "w").write(s)
    print(s)


if __name__ == "__main__":
    main()
