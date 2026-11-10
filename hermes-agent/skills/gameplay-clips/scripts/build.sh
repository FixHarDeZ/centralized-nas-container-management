#!/bin/bash
# Assemble a gameplay-style clip: windowed footage over the bg plate,
# Fredoka caption pills, burned Thai subs, trailer audio ducked under TTS.
# Usage:
#   D=$PWD SEGS="seg_0 seg_1 ... seg_7" DUR=20.05 CAPS="..." bash build.sh
# SEGS: segment basenames (seg_0.mp4 ...) in play order, D = work dir.
# DUR:  target duration in seconds (apad whole_dur + -t).
# CAPS: optional comma-joined drawtext pill chain, e.g.
#   drawtext=fontfile=$D/Fredoka-SemiBold.ttf:text='Hook':fontcolor=white:fontsize=40:borderw=3:bordercolor=0x5A2A4A:box=1:boxcolor=0xFF8FB1@0.92:boxborderw=14:x=(w-text_w)/2:y=52:enable='between(t,2.1,4.4)'
# requires: vo.mp3 subs.ass bg.png + Fredoka/Itim fonts in $D
set -e
: "${D:=$(pwd)}"
: "${DUR:=20.05}"
: "${CAPS:=}"

mkdir -p "$D/fonts"
cp -f "$D"/*.ttf "$D/fonts/" 2>/dev/null || true

IN=""; VA=""; N=0
for s in $SEGS; do IN="$IN -i $D/$s.mp4"; VA="$VA[$N:v]"; N=$((N+1)); done
AA=""
for i in $(seq 0 $((N-1))); do AA="$AA[$i:a]"; done

VID="${VA}concat=n=$N:v=1:a=0[vcat];\
[vcat]crop=720:405:0:320[game];\
[$((N+1)):v]scale=720:1280,fps=30,format=yuv420p[bg];\
[bg][game]overlay=0:320:eof_action=pass:shortest=1[e1];"
if [ -n "$CAPS" ]; then VID="${VID}[e1]${CAPS}[e4];"; else VID="${VID}[e1]null[e4];"; fi
VID="${VID}[e4]ass=$D/subs.ass:fontsdir=$D/fonts:shaping=complex[v];"

AUD="${AA}concat=n=$N:v=0:a=1[ga];\
[ga]volume=0.75[pre];\
[$((N)):a]aresample=48000,volume=1.25,apad=whole_dur=$DUR,asplit=2[voa][vok];\
[vok]pan=mono|c0=0.5*c0+0.5*c1[key];\
[pre][key]sidechaincompress=threshold=0.04:ratio=4:attack=15:release=500[gduck];\
[gduck][voa]amix=inputs=2:duration=longest:normalize=0[aout]"

ffmpeg -y -v error $IN -i "$D/vo.mp3" -loop 1 -i "$D/bg.png" \
  -filter_complex "$VID$AUD" -map "[v]" -map "[aout]" \
  -c:v libx264 -preset medium -crf 19 -c:a aac -b:a 160k -ar 48000 -ac 2 \
  -t "$DUR" "$D/out.mp4"

ffprobe -v error -show_entries format=duration,size \
  -show_entries stream=codec_name,width,height,nb_frames -of default=nw=1 "$D/out.mp4"
