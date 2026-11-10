"""Short footage clip (<=15 s) builder: VO + subs + pills + ducked music, one ffmpeg graph.

Copy this file into the work dir, edit the constants below, then run:
    uv run --with edge-tts python build.py
See references/short-clip-ffmpeg.md for why each filter is written the way it is.
Fonts: copy Itim-Regular.ttf and Fredoka-SemiBold.ttf into ./fonts/ first.
"""
import asyncio, os, subprocess
import edge_tts

W = os.path.dirname(os.path.abspath(__file__))
os.chdir(W)
SRC = "source.mp4"          # footage (any resolution; output is 720x1280)
T0, DUR = 178.0, 12.0       # window start (s) and clip length (s)
VOICE = "th-TH-PremwadeeNeural"
PILL = [(0.3, 4.0, "PRE-ORDER"), (4.2, 8.0, "18 MAR")]   # EN pills, <=2 words each
CTA = (10.3, "Link below!")                                 # last seg only
PHRASES = [                                                 # (planned start s, Thai line)
    (0.4, "ประโยคแรกของคลิปนะ"),
    (4.2, "ประโยคที่สองเลย"),
    (8.2, "ประโยคสุดท้าย"),
]
MUSIC_GAIN, VO_GAIN = 0.6, 1.3


async def gen_all():
    durs = []
    for i, (_, text) in enumerate(PHRASES):
        out = f"vo_{i}.mp3"
        await edge_tts.Communicate(text, VOICE, rate="+0%", pitch="+12Hz").save(out)
        d = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                  "-of", "csv=p=0", out], capture_output=True, text=True).stdout)
        durs.append(d)
    return durs


durs = asyncio.run(gen_all())
ends = [s + d for (s, _), d in zip(PHRASES, durs)]
print("phrase ends", [round(e, 2) for e in ends])
assert max(ends) <= DUR - 1.0, "VO too long for the clip: cut words, do not speed up"

# 1) VO track: adelay each phrase, amix, pad to exact length
ins, parts = [], []
for i, (s, _) in enumerate(PHRASES):
    ins += ["-i", f"vo_{i}.mp3"]
    ms = int(s * 1000)
    parts.append(f"[{i}:a]adelay={ms}|{ms},aformat=sample_rates=48000:channel_layouts=stereo[p{i}]")
mix = (";".join(parts) + ";" + "".join(f"[p{i}]" for i in range(len(PHRASES)))
       + f"amix=inputs={len(PHRASES)}:normalize=0,apad=whole_dur={DUR},atrim=0:{DUR}[vo]")
subprocess.run(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", mix, "-map", "[vo]",
                "-ar", "48000", "-ac", "2", "vo.wav"], check=True)

# 2) subtitles (Itim, yellow, dark outline, no box); MarginV 465 = safe zone
def ts(t):
    h = int(t // 3600); m = int(t % 3600 // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"

hdr = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 0

[V4+ Styles]
Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding
Style: Default,Itim,48,&H0066D1FF,&H0066D1FF,&H00203050,&H00000000,0,0,0,0,100,100,0,0,1,5,2.5,2,60,140,465,1

[Events]
Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text
"""
lines = [f"Dialogue: 0,{ts(s)},{ts(s + d)},Default,,0,0,0,,{t}" for (s, t), d in zip(PHRASES, durs)]
open("subs.ass", "w", encoding="utf-8").write(hdr + "\n".join(lines) + "\n")

# 3) picture: blurred fill + window at y=280, EN pills at y=210, CTA last
pill_chain = ""
for a, b, txt in PILL:
    pill_chain += (f"drawtext=fontfile=fonts/Fredoka-SemiBold.ttf:text='{txt}':fontsize=40:"
                   f"fontcolor=0xFFD166:box=1:boxcolor=0x5A2A4A@0.8:boxborderw=14:"
                   f"x=(w-text_w)/2:y=210:enable='between(t,{a},{b})',")
pill_chain += (f"drawtext=fontfile=fonts/Fredoka-SemiBold.ttf:text='{CTA[1]}':fontsize=40:"
               f"fontcolor=0xFFD166:box=1:boxcolor=0x5A2A4A@0.8:boxborderw=14:"
               f"x=(w-text_w)/2:y=210:enable='gte(t,{CTA[0]})',")
vf = ("[0:v]split=2[a][b];"
      "[a]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,boxblur=20:5,"
      "eq=brightness=-0.12:saturation=0.9[bg];"
      "[b]scale=720:405,setsar=1[w];"
      "[bg][w]overlay=0:280[v0];"
      f"[v0]{pill_chain}ass=subs.ass:shaping=complex,format=yuv420p[v]")

# 4) audio: music (padded, exact length) ducked by VO, then VO on top
ac = (f"[0:a]volume={MUSIC_GAIN},apad=whole_dur={DUR},atrim=0:{DUR}[m];"
      f"[1:a]volume={VO_GAIN},apad=whole_dur={DUR},atrim=0:{DUR},asplit=2[vo][vok];"
      "[m][vok]sidechaincompress=threshold=0.04:ratio=4:release=500[duck];"
      f"[duck][vo]amix=inputs=2:duration=longest:normalize=0,apad=whole_dur={DUR},atrim=0:{DUR}[aout]")

subprocess.run([
    "ffmpeg", "-y", "-v", "error", "-ss", str(T0), "-t", str(DUR), "-i", SRC, "-i", "vo.wav",
    "-filter_complex", vf.replace("[0:v]", "[0:v]") + ";" + ac,
    "-map", "[v]", "-map", "[aout]", "-t", str(DUR), "-r", "30",
    "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p",
    "-profile:v", "high", "-level", "4.0", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
    "-ac", "2", "-movflags", "+faststart", "out.mp4"], check=True)
print("rendered out.mp4")
