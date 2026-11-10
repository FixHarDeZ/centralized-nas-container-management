#!/bin/bash
# make_sfx.sh [out_dir] — synthesize the v5 seam SFX with ffmpeg only (no downloads, no samples).
#   whoosh.wav : 0.45 s band-limited noise swell, PEAK AT 0.30 s (build_v5 starts it seam-0.30)
#   impact.wav : 0.60 s low thump (chirp 105->45 Hz, exp decay) + short soft transient, starts AT the seam
# Both 48 kHz stereo s16, peak ~ -6 dBFS; build_v5 mixes them low (gains in plan.json) into the
# music bus BEFORE the sidechain duck, so they sit under the Thai VO.
set -e
OUT="${1:-$(cd "$(dirname "$0")/.." && pwd)/assets/sfx}"
mkdir -p "$OUT"

# whoosh: white noise -> bandpass 300-2500 Hz -> envelope rise (0..0.30 s, t^2) / fall (0.30..0.45 s)
ffmpeg -y -v error -f lavfi -i "anoisesrc=d=0.45:c=pink:r=48000:a=0.9:seed=7" \
  -af "highpass=f=250,lowpass=f=2600,\
volume='if(lt(t,0.30),pow(t/0.30,2),pow(max(0,1-(t-0.30)/0.15),1.5))':eval=frame,\
volume=9dB,aformat=channel_layouts=stereo,alimiter=limit=0.5:level=0" \
  -ar 48000 -ac 2 -c:a pcm_s16le "$OUT/whoosh.wav"

# impact: phase of f(t)=45+60*exp(-20t) is 2*pi*(45t + 3*(1-exp(-20t)))
ffmpeg -y -v error -f lavfi -i \
  "aevalsrc='0.8*sin(2*PI*(45*t+3*(1-exp(-20*t))))*exp(-7*t)+0.25*(random(0)*2-1)*exp(-70*t)':s=48000:d=0.6" \
  -af "lowpass=f=1800,afade=t=out:st=0.5:d=0.1,aformat=channel_layouts=stereo,alimiter=limit=0.5:level=0" \
  -ar 48000 -ac 2 -c:a pcm_s16le "$OUT/impact.wav"

for f in whoosh impact; do
  printf '%s: ' "$f"
  ffmpeg -hide_banner -i "$OUT/$f.wav" -af volumedetect -f null - 2>&1 | awk -F': ' '/mean_volume/{m=$2} /max_volume/{x=$2} END{print "mean "m" max "x}'
done
ls -la "$OUT"
