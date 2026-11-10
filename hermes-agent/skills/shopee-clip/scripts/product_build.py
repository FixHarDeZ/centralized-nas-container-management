#!/usr/bin/env python3
"""Mode 📦 build: approved Flow product b-roll shots + gameplay-style TTS voiceover -> one 9:16 clip.

The voice recipe is the gameplay one Fix already approved (gen_vo_natural.py: Gemini Leda by default,
edge Premwadee + warm EQ when Gemini is out of quota). Flow's own shot audio becomes the bed,
ducked under the VO with the gameplay sidechain. Subs come from the VO timeline (known text), so no ASR
timing is involved. Graphics are NOT added here: run graphics_layer.py on the output with
--report <workdir>/report.json (same as the presenter chain).

Usage:
  uv run --with edge-tts --with faster-whisper --with numpy \
      python product_build.py plan.json [--workdir DIR] [--out out.mp4]

plan.json:
{
  "shots": ["shot1.mp4", "shot2.mp4", "shot3.mp4"],     # `clipjob.py assemble-check JOB` order
  "vo": "vo_plan.json",           # gen_vo_natural plan (engine gemini, voice Leda, edge rate/pitch per phrase)
  # or prebuilt: "vo_mp3": "vo.mp3", "vo_ass": "subs.ass"   (timeline = subs.timeline.json beside the ass)
  "from_take": "gemini_take.wav", # optional: rebuild the VO from a saved take (0 Gemini requests)
  "pills": [{"text": "Soft Tip", "start": 0.4, "end": 2.2}],   # FINAL-timeline seconds, EN <=2 words
  "xfade": 0.25, "bed_gain": 0.75, "tail": 1.6
}
Outputs in workdir: vo.mp3, subs.ass, out.mp4 (mastered, faststart), report.json
  report.json: {flags, out, v_dur, a_dur, vo_end, engine, pills[(t0,t1,text)], subs[(t0,t1,text)]}
  flags = anything Fix must hear about; clipjob.py deliver refuses while flags is non-empty.
"""
import argparse
import itertools
import json
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GP = os.path.normpath(os.path.join(HERE, "..", "..", "gameplay-clips"))
FONTS = os.path.join(GP, "fonts")
MASTER = os.path.join(GP, "scripts", "master.sh")
GEN_VO = os.path.join(GP, "scripts", "gen_vo_natural.py")
PILL_COLORS = ["0xFF8FB1", "0xFFD166", "0x8AC926", "0x7A5CFF"]
PILL_Y = 210
SUB_MARGINV = 465        # full-frame 9:16 layout: subs band y~700-835 (post_presenter default)
WARM_EQ = ("highpass=f=120,equalizer=f=220:g=-7:w=1.2,equalizer=f=2400:g=5:w=1.2,"
           "equalizer=f=4500:g=-4:w=1.3,equalizer=f=7500:g=2.5:w=1.0,"
           "acompressor=threshold=0.2:ratio=2:attack=12:release=200:makeup=1")
MONEY = re.compile(r"฿|\$|%|\d+\s*(บาท|baht)|\b(price|sale|off|discount|promo|cheap)\b", re.I)


def sh(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def ffdur(path, stream="v:0"):
    out = sh(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries", "stream=duration",
              "-of", "csv=p=0", path]).stdout.strip()
    if not out or out == "N/A":
        out = sh(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", path]).stdout.strip()
    return float(out)


def has_audio(path):
    return bool(sh(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                    "-of", "csv=p=0", path]).stdout.strip())


def mean_db(path):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-i", path, "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    m = re.search(r"mean_volume: (-?[\d.]+) dB", err)
    return float(m.group(1)) if m else None


# ---------------------------------------------------------------- pure helpers (tested)
def check_pills(pills, total):
    probs = []
    ps = sorted(pills, key=lambda p: p["start"])
    for p in ps:
        if len(p["text"].split()) > 2 or not p["text"].isascii():
            probs.append(f"pill '{p['text']}': EN only, <=2 words")
        if MONEY.search(p["text"]):
            probs.append(f"pill '{p['text']}': money-shaped")
        if not 0 <= p["start"] < p["end"] <= total + 0.01:
            probs.append(f"pill '{p['text']}' {p['start']}-{p['end']} outside 0-{total:.2f}")
    for x, y in itertools.pairwise(ps):
        if y["start"] < x["end"]:
            probs.append(f"pills overlap: '{x['text']}' / '{y['text']}'")
    return probs


def fit(footage_s, vo_end, tail):
    """-> (total, hold_s, flags). Footage shorter than the VO is held on its last frame;
    longer footage is trimmed to the VO."""
    total = round(vo_end + tail, 3)
    hold = round(max(0.0, total - footage_s), 3)
    flags = []
    if hold > 2.0:
        flags.append(f"footage {footage_s:.1f}s is {hold:.1f}s shorter than the VO ({total:.1f}s) — "
                     "last frame frozen that long; add a shot or cut VO phrases")
    if footage_s - total > 4.0:
        flags.append(f"footage {footage_s:.1f}s runs {footage_s - total:.1f}s past the VO — "
                     "the last shot is mostly cut; add VO or drop a shot")
    return total, hold, flags


def set_marginv(ass_text, mv):
    out = []
    for line in ass_text.splitlines():
        if line.startswith("Style: "):
            f = line[7:].split(",")
            if len(f) >= 22:
                f[21] = str(mv)
                line = "Style: " + ",".join(f)
        out.append(line)
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--workdir")
    ap.add_argument("--out", default="out.mp4")
    a = ap.parse_args()
    plan = json.load(open(a.plan, encoding="utf-8"))
    wd = os.path.abspath(a.workdir or os.path.dirname(os.path.abspath(a.plan)))
    os.makedirs(wd, exist_ok=True)
    base = os.path.dirname(os.path.abspath(a.plan))

    def P(p):
        return p if os.path.isabs(p) else os.path.join(base, p)

    shots = [P(s) for s in plan["shots"]]
    if not shots or any(not os.path.exists(s) for s in shots):
        sys.exit(f"missing shot files: {[s for s in shots if not os.path.exists(s)]}")
    flags, notes = [], []
    fdir = os.path.join(wd, "fonts")
    os.makedirs(fdir, exist_ok=True)
    for f in os.listdir(FONTS):
        if f.endswith(".ttf"):
            shutil.copy2(os.path.join(FONTS, f), fdir)

    # ---- 1. voiceover (gameplay recipe)
    vo_mp3, vo_ass = os.path.join(wd, "vo.mp3"), os.path.join(wd, "subs.ass")
    engine = "prebuilt"
    if plan.get("vo"):
        cmd = ["uv", "run", "--with", "edge-tts", "--with", "faster-whisper", "--with", "numpy", "python", GEN_VO,
               P(plan["vo"]), "--out-mp3", vo_mp3, "--out-ass", vo_ass, "--take-out", os.path.join(wd, "gemini_take.wav")]
        if plan.get("from_take"):
            cmd += ["--from-take", P(plan["from_take"])]
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=wd, timeout=900)
        print(r.stdout[-2500:])
        if r.returncode:
            sys.exit(f"gen_vo_natural failed: {r.stderr[-800:]}")
        engine = open(os.path.join(wd, "vo.engine")).read().strip() if os.path.exists(os.path.join(wd, "vo.engine")) else "?"
        for line in r.stdout.splitlines():
            if line.startswith("GATE WARN"):
                flags.append("VO " + line)
    else:
        shutil.copy2(P(plan["vo_mp3"]), vo_mp3)
        shutil.copy2(P(plan["vo_ass"]), vo_ass)
        tl_src = os.path.splitext(P(plan["vo_ass"]))[0] + ".timeline.json"
        shutil.copy2(tl_src, os.path.join(wd, "subs.timeline.json"))
    timeline = json.load(open(os.path.splitext(vo_ass)[0] + ".timeline.json", encoding="utf-8"))
    vo_end = float(timeline[-1]["end"])
    open(vo_ass, "w", encoding="utf-8").write(set_marginv(open(vo_ass, encoding="utf-8").read(), SUB_MARGINV))
    if engine == "edge":    # voice A fallback: warm EQ, level-matched (gameplay pitfall "เสียงเหมือน AI")
        warm = os.path.join(wd, "vo_warm.mp3")
        before = mean_db(vo_mp3)
        sh(["ffmpeg", "-y", "-v", "error", "-i", vo_mp3, "-af", WARM_EQ, warm])
        after = mean_db(warm)
        g = (before - after) if (before is not None and after is not None) else 0.0
        sh(["ffmpeg", "-y", "-v", "error", "-i", warm, "-af", f"volume={g:.2f}dB,alimiter=limit=0.9:level=0",
            "-codec:a", "libmp3lame", "-q:a", "2", vo_mp3])
        os.remove(warm)
        notes.append("voice A (edge + warm EQ) — Gemini quota out; tell Fix in the delivery")

    # ---- 2. timeline
    xf = float(plan.get("xfade", 0.25))
    durs = [ffdur(s) for s in shots]
    footage = sum(durs) - xf * (len(shots) - 1)
    total, hold, fit_flags = fit(footage, vo_end, float(plan.get("tail", 1.6)))
    flags += fit_flags
    pills = plan.get("pills", [])
    flags += check_pills(pills, total)

    # ---- 3. graph
    ins, fv, fa = [], [], []
    for k, s in enumerate(shots):
        ins += ["-i", s]
        fv.append(f"[{k}:v]scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280,setsar=1,"
                  f"fps=30,format=yuv420p,settb=AVTB[v{k}]")
        if has_audio(s):
            fa.append(f"[{k}:a]aresample=48000,aformat=channel_layouts=stereo,atrim=0:{durs[k]:.3f}[a{k}]")
        else:
            fa.append(f"anullsrc=r=48000:cl=stereo,atrim=0:{durs[k]:.3f}[a{k}]")
    n = len(shots)
    vl, al, off = "v0", "a0", 0.0
    for k in range(1, n):
        off += durs[k - 1] - xf
        fv.append(f"[{vl}][v{k}]xfade=transition=fade:duration={xf}:offset={off:.3f}[vx{k}]")
        fa.append(f"[{al}][a{k}]acrossfade=d={xf}[ax{k}]")
        vl, al = f"vx{k}", f"ax{k}"
    chain = [f"tpad=stop_mode=clone:stop_duration={hold + 0.5:.3f}", f"trim=0:{total:.3f}", "setpts=PTS-STARTPTS"]
    for i, p in enumerate(sorted(pills, key=lambda p: p["start"])):
        tf = os.path.join(wd, f"pill_{i}.txt")
        open(tf, "w", encoding="utf-8").write(p["text"])
        chain.append(f"drawtext=fontfile={fdir}/Fredoka-SemiBold.ttf:textfile={tf}:fontcolor=white:fontsize=40:"
                     f"borderw=3:bordercolor=0x5A2A4A:box=1:boxcolor={PILL_COLORS[i % 4]}@0.92:boxborderw=14:"
                     f"x=(w-text_w)/2:y={PILL_Y}:enable='between(t,{p['start']:.3f},{p['end']:.3f})'")
    chain.append(f"ass={vo_ass}:fontsdir={fdir}:shaping=complex,format=yuv420p,"
                 "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv")
    fv.append(f"[{vl}]" + ",".join(chain) + "[vout]")
    ins += ["-i", vo_mp3]
    bed_gain = float(plan.get("bed_gain", 0.75))
    fa.append(f"[{al}]apad=whole_dur={total:.3f},atrim=0:{total:.3f},volume={bed_gain}[bed]")
    fa.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,apad=whole_dur={total:.3f},"
              f"atrim=0:{total:.3f},asplit=2[voa][vok]")
    fa.append("[vok]pan=mono|c0=0.5*c0+0.5*c1[key]")
    fa.append("[bed][key]sidechaincompress=threshold=0.04:ratio=4:attack=15:release=500[gduck]")
    fa.append("[gduck][voa]amix=inputs=2:duration=first:normalize=0[aout]")
    pre = os.path.join(wd, "premaster.mp4")
    enc = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-level", "4.0", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-color_range", "tv", "-threads", "3"]
    sh(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", ";".join(fv + fa), "-map", "[vout]", "-map", "[aout]",
        *enc, "-c:a", "alac", "-ar", "48000", "-ac", "2", "-t", f"{total:.3f}", pre], timeout=1500)

    # ---- 4. master + faststart (gameplay master.sh)
    m = sh(["bash", MASTER, pre]).stdout.strip()
    out = a.out if os.path.isabs(a.out) else os.path.join(wd, a.out)
    sh(["ffmpeg", "-y", "-v", "error", "-i", pre, "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", out])
    os.remove(pre)
    report = {"flags": flags, "notes": notes, "out": out, "master": m, "engine": engine, "vo_end": vo_end,
              "duration_target": total, "footage_s": round(footage, 3), "held_last_frame_s": hold,
              "v_dur": ffdur(out, "v:0"), "a_dur": ffdur(out, "a:0"),
              "pills": [(p["start"], p["end"], p["text"]) for p in pills],
              "subs": [(round(e["start"], 2), round(e["end"], 2), e.get("sub", e.get("say", ""))) for e in timeline]}
    if abs(report["v_dur"] - report["a_dur"]) > 0.1:
        report["flags"].append(f"audio {report['a_dur']:.2f}s != video {report['v_dur']:.2f}s")
    json.dump(report, open(os.path.join(wd, "report.json"), "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: report[k] for k in ("out", "engine", "vo_end", "duration_target", "v_dur", "a_dur", "flags", "notes")},
                     ensure_ascii=False, indent=1))
    for fl in report["flags"]:
        print("FLAG:", fl)


if __name__ == "__main__":
    main()
