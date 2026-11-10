#!/usr/bin/env bash
# Duck-only loudness gate for build_v5 gameplay clips.
# Measures how far the VO sits above the ducked music, phrase by phrase.
# Gate: min delta >= 6 dB. If it fails, LOWER plan.json music_gain (the sidechain
# key is the VO, so music_gain moves the music only) and rebuild.
#
# Usage (run in the work dir that holds master.mp4, vo.mp3, plan.json):
#   bash duck_gate.sh <music_gain> '<seg list>' '<phrase list>'
#   seg list    = master-time ranges of the audio the segs use: "1.2-2.8,2.8-8.5,8.5-14.3"
#   phrase list = VO phrase windows in seconds (from the build's timeline print): "0.05-4.7,5.0-8.9"
# Example: bash duck_gate.sh 0.33 '1.2-2.8,2.8-8.5,8.5-14.3,20.9-22.3,38.9-44.4' '0.05-4.7,5.0-8.9,9.2-12.5'
# The seg list must match plan.json's segs (master-time `in` .. `in+dur`, audio_in for hero).
set -euo pipefail
GAIN=${1:?music_gain}; SEGS=${2:?seg list}; PHR=${3:?phrase list}
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 vo.mp3)

F=""; N=0; LABELS=""
IFS=',' read -ra S <<< "$SEGS"
for r in "${S[@]}"; do
  a=${r%-*}; b=${r#*-}
  F+="[0:a]atrim=${a}:${b},asetpts=PTS-STARTPTS[a${N}];"; LABELS+="[a${N}]"; N=$((N+1))
done
ffmpeg -y -v error -i master.mp4 -filter_complex "${F}${LABELS}concat=n=${N}:v=0:a=1,volume=${GAIN},aformat=sample_rates=48000:channel_layouts=stereo[m]" -map '[m]' -t "$DUR" music_raw.wav
ffmpeg -y -v error -i music_raw.wav -i vo.mp3 -filter_complex "[1:a]aformat=sample_rates=48000:channel_layouts=stereo[k];[0:a][k]sidechaincompress=threshold=0.04:ratio=4:release=500[d]" -map '[d]' -t "$DUR" duck_only.wav
ffmpeg -y -v error -i duck_only.wav -i vo.mp3 -filter_complex "[1:a]aformat=sample_rates=48000:channel_layouts=stereo,volume=1.25[v];[0:a][v]amix=inputs=2:duration=first:normalize=0" -t "$DUR" mix_approx.wav

python3 -I - "$PHR" <<'PY'
import sys, wave, struct, math
def load(p):
    w = wave.open(p); n = w.getnframes(); sr = w.getframerate(); ch = w.getnchannels()
    s = struct.unpack("<%dh" % (n * ch), w.readframes(n))
    return [s[i * ch] / 32768.0 for i in range(n)], sr
d, sr = load("duck_only.wav"); m, _ = load("mix_approx.wav")
def rms(x, a, b):
    seg = x[int(a * sr):int(b * sr)]
    return 20 * math.log10(math.sqrt(sum(v * v for v in seg) / max(1, len(seg))) + 1e-12)
ph = [tuple(float(t) for t in p.split('-')) for p in sys.argv[1].split(',')]
deltas = []
for a, b in ph:
    dd, mm = rms(d, a, b), rms(m, a, b); deltas.append(mm - dd)
    print(f"{a:5.2f}-{b:5.2f} duck={dd:6.1f} mix={mm:6.1f} delta={mm-dd:5.1f}")
print("min delta", round(min(deltas), 1), "PASS" if min(deltas) >= 6 else "FAIL (lower music_gain)")
PY
