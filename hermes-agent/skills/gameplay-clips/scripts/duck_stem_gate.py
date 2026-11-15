#!/usr/bin/env python3
"""Duck-only delta gate from build_v5 stems (full recipe: references/look-v5.md).

Run from the clip workdir AFTER every build + master:
    uv run --with numpy python <skill>/scripts/duck_stem_gate.py
Re-applies plan music_gain / vo_gain to the RAW stems (work/music_v5.wav,
work/sfx_v5.wav, work/vo_v5.wav), renders duck_only.wav + premaster.wav, and
prints per-VO-phrase delta = RMS(premaster) - RMS(duck_only) in dB.
Gate: min delta >= 6. Exit 0 pass / 1 fail (lower plan music_gain, rebuild,
rerun) / 2 setup error. Regenerate after EVERY build: stems change with the plan.
"""
import json, subprocess, sys, wave
import numpy as np

PLAN = json.load(open("plan.json"))
MG, VG, DUR = PLAN["music_gain"], PLAN["vo_gain"], PLAN["dur"]
TL = json.load(open("work/timeline_v5.json"))
phrases = [(a, b) for a, b, _ in TL["subs"]]


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("ffmpeg failed: " + r.stderr[-1200:])


# input slots: 0 throwaway, 1 music, 2 vo, 3 sfx (build_v5's own indexing)
base = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", str(DUR),
        "-i", "anullsrc=r=48000:cl=stereo",
        "-i", "work/music_v5.wav", "-i", "work/vo_v5.wav", "-i", "work/sfx_v5.wav",
        "-filter_complex"]

pre = (f"[1:a][3:a]amix=inputs=2:normalize=0,volume={MG}[pre];"
       f"[2:a]volume={VG},apad=whole_dur={DUR},asplit=2[mixa][key0];"
       f"[key0]pan=mono|c0=0.5*c0+0.5*c1[key];"
       f"[pre][key]sidechaincompress=threshold=0.04:ratio=4:attack=15:release=500[gduck]")

# duck-only: gduck alone; the dropped VO branch needs an anullsink consumer
run(base + [pre + f";[gduck]apad=whole_dur={DUR}[gd];[mixa]anullsink",
            "-map", "[gd]", "-t", str(DUR), "duck_only.wav"])
# premaster: plain sum of gduck + voiced branch (amix normalize=0)
run(base + [pre + f";[gduck][mixa]amix=inputs=2:normalize=0[pm]",
            "-map", "[pm]", "-t", str(DUR), "premaster.wav"])


def rms_window(path, a, b):
    w = wave.open(path)
    sr = w.getframerate()
    w.setpos(int(a * sr))
    data = np.frombuffer(w.readframes(int((b - a) * sr)), dtype=np.int16).astype(np.float64)
    w.close()
    return np.sqrt(np.mean(data ** 2)) if len(data) else 1e-9


fails = 0
print(f"music_gain={MG} vo_gain={VG}")
for a, b in phrases:
    d, k = rms_window("premaster.wav", a, b), rms_window("duck_only.wav", a, b)
    delta = 20 * np.log10(d / k) if d > 0 and k > 0 else 0.0
    if delta < 6.0:
        fails += 1
    print(f"{a:5.2f}-{b:5.2f} delta={delta:5.1f}{'  <-- FAIL' if delta < 6 else ''}")
print("MIN DELTA", "PASS" if fails == 0 else "FAIL")
sys.exit(0 if fails == 0 else 1)
