#!/bin/bash
# master.sh <file> [target_I_LUFS] [ceiling_dBFS]
# Measure integrated loudness -> linear gain -> hard limit (no auto-level) -> keep A/V durations equal.
# REF clip (Fix 2026-11-02 sample): I=-14.1 LUFS, LRA 1.1, TP 0.0. Target -13.7 so the limiter
# (which eats ~0.4 dB) lands the final at ~-14.1. House gate: whole-clip max_volume BELOW -3 dBFS,
# pitfall wants ~1.5 dB headroom -> default ceiling -4.5 (measured after AAC lands ~ -4.3).
set -e
F="$1"; T="${2:--13.7}"; C="${3:--4.5}"
[ -f "$F" ] || { echo "no file $F"; exit 1; }

I=$(ffmpeg -hide_banner -i "$F" -af ebur128 -f null - 2>&1 | awk '/Integrated loudness/{f=1} f&&/I:/{print $2; exit}')
[ -n "$I" ] || { echo "loudness measure failed"; exit 1; }
GAIN=$(awk -v i="$I" -v t="$T" 'BEGIN{printf "%.1f", t-i}')
LIN=$(awk -v c="$C" 'BEGIN{printf "%.4f", 10^(c/20)}')
VDUR=$(ffprobe -v error -select_streams v:0 -show_entries stream=duration -of csv=p=0 "$F")
[ -n "$VDUR" ] || VDUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$F")

TMP="${F%.mp4}_master.mp4"
ffmpeg -y -v error -i "$F" \
  -af "volume=${GAIN}dB,alimiter=limit=${LIN}:level=0,apad=whole_dur=${VDUR}" \
  -t "$VDUR" -c:v copy -c:a aac -b:a 192k -ar 48000 -ac 2 "$TMP"
mv "$TMP" "$F"

I2=$(ffmpeg -hide_banner -i "$F" -af ebur128 -f null - 2>&1 | awk '/Integrated loudness/{f=1} f&&/I:/{print $2; exit}')
TP=$(ffmpeg -hide_banner -i "$F" -af ebur128=peak=true -f null - 2>&1 | awk '/True peak/{f=1} f&&/Peak:/{print $2; exit}')
MV=$(ffmpeg -hide_banner -i "$F" -af volumedetect -f null - 2>&1 | awk -F': ' '/mean_volume/{m=$2} /max_volume/{x=$2} END{print m" / max "x}')
AV=$(ffprobe -v error -select_streams a:0 -show_entries stream=duration -of csv=p=0 "$F")
echo "mastered $F: I_before=$I gain=${GAIN}dB -> I=$I2 TP=$TP [$MV] a_dur=$AV v_dur=$VDUR"
