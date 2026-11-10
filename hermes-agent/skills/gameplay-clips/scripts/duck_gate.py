#!/usr/bin/env python3
"""Duck-only delta gate for build_v5 clips (>= 6 dB required per VO phrase).

build_v5 exports raw, PRE-gain stems at work/music_v5.wav, work/sfx_v5.wav and
work/vo_v5.wav — re-apply music_gain/vo_gain in the graph (full recipe:
references/look-v5.md -> Duck-only render). This script is the fallback that
rebuilds the same audio chain from master.mp4 + vo.mp3 instead (omits the seam SFX):
  1. music   = master audio over the seg ranges (concatenated), x music_gain
  2. duck    = music sidechain-compressed by the VO (key = vo.mp3)
  3. mix     = duck + vo * 1.25 (vo_gain)
Delta per VO phrase = RMS(mix) - RMS(duck), in dB. The gate needs min delta >= 6.

Usage (from the work dir, with master.mp4, vo.mp3 present):
  uv run --with numpy python3 duck_gate.py --master master.mp4 --vo vo.mp3 \
      --gain 0.33 --dur 20 \
      --segs 1.2-2.8,2.8-8.5,8.5-14.3,20.9-22.3,38.9-44.4 \
      --phrases 0.05-4.7,5.0-8.9,9.2-12.5,12.8-15.2,15.4-16.9,17.1-18.3
  --segs    master-time ranges used by the seg list (audio_in .. audio_in+dur)
  --phrases VO phrase windows (take from work/timeline_v5.json or the gen_vo_natural log)
Exit 0 = pass, 1 = min delta below 6 dB (lower --gain and rerun), 2 = setup error.
"""
import argparse, math, os, struct, subprocess, sys, tempfile, wave

ap = argparse.ArgumentParser()
ap.add_argument("--master", required=True)
ap.add_argument("--vo", required=True)
ap.add_argument("--gain", type=float, required=True, help="plan music_gain")
ap.add_argument("--vo-gain", type=float, default=1.25)
ap.add_argument("--dur", type=float, required=True)
ap.add_argument("--segs", required=True, help="comma list of a-b master-time ranges")
ap.add_argument("--phrases", required=True, help="comma list of a-b VO phrase windows")
ap.add_argument("--min-delta", type=float, default=6.0)
args = ap.parse_args()

for p in (args.master, args.vo):
    if not os.path.exists(p):
        sys.exit(f"missing {p}")

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit("ffmpeg failed: " + r.stderr[-800:])

ranges = [tuple(float(x) for x in s.split("-")) for s in args.segs.split(",")]
parts, labels = [], []
for i, (a, b) in enumerate(ranges):
    parts.append(f"[0:a]atrim={a}:{b},asetpts=PTS-STARTPTS[a{i}]")
    labels.append(f"[a{i}]")
graph = ";".join(parts) + ";" + "".join(labels) + \
    f"concat=n={len(ranges)}:v=0:a=1,volume={args.gain},aformat=sample_rates=48000:channel_layouts=stereo[m]"

tmp = tempfile.mkdtemp(prefix="duckgate_", dir=os.environ.get("TMPDIR", "/opt/data/cache/scratch"))
music = os.path.join(tmp, "music.wav")
duck = os.path.join(tmp, "duck.wav")
mix = os.path.join(tmp, "mix.wav")

run(["ffmpeg", "-y", "-v", "error", "-i", args.master, "-filter_complex", graph,
     "-map", "[m]", "-t", str(args.dur), music])
run(["ffmpeg", "-y", "-v", "error", "-i", music, "-i", args.vo, "-filter_complex",
     "[1:a]aformat=sample_rates=48000:channel_layouts=stereo[k];"
     "[0:a][k]sidechaincompress=threshold=0.04:ratio=4:release=500[d]",
     "-map", "[d]", "-t", str(args.dur), duck])
run(["ffmpeg", "-y", "-v", "error", "-i", duck, "-i", args.vo, "-filter_complex",
     f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume={args.vo_gain}[v];"
     "[0:a][v]amix=inputs=2:duration=first:normalize=0",
     "-t", str(args.dur), mix])

def load(path):
    w = wave.open(path)
    n, sr, ch = w.getnframes(), w.getframerate(), w.getnchannels()
    raw = struct.unpack("<%dh" % (n * ch), w.readframes(n))
    return [raw[i * ch] / 32768.0 for i in range(n)], sr

d, sr = load(duck)
m, _ = load(mix)

def rms_db(x, a, b):
    seg = x[int(a * sr):int(b * sr)]
    return 20 * math.log10(math.sqrt(sum(v * v for v in seg) / max(1, len(seg))) + 1e-12)

deltas = []
for s in args.phrases.split(","):
    a, b = (float(v) for v in s.split("-"))
    dd, mm = rms_db(d, a, b), rms_db(m, a, b)
    deltas.append(mm - dd)
    print(f"{a:6.2f}-{b:6.2f} duck={dd:7.1f} mix={mm:7.1f} delta={mm - dd:5.1f}")
mn = min(deltas)
print(f"min delta {mn:.1f} dB (gate >= {args.min_delta})")
print(f"stems kept in {tmp}")
sys.exit(0 if mn >= args.min_delta else 1)
