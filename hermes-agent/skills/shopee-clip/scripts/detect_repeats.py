#!/usr/bin/env python3
"""Find (and optionally cut) phrases Flow repeated in a RAW presenter scene (Fix 2026-11-07).

Flow pads a short voiceover by saying a phrase or word chunk twice ("สเต็ปง่ายๆ สเต็ปง่ายๆ").
post_presenter's prompted ASR HIDES this (it snaps onto the script), so this runs UNPROMPTED,
word-level, vad_filter=False, and looks for an ADJACENT doubled character run that the script
itself does not contain twice.

Usage (one scene at a time - RAM):
  uv run --with faster-whisper --with numpy python detect_repeats.py scene_raw.mp4 \
      --script prompt_s2.txt [--cut scene_cut.mp4] [--fps 24] [--min 4]
--script: a prompt file (text inside  Audio (Thai voiceover): "...") or the plain script.
Prints JSON {repeats:[{text,t0,t1,cut:[a,b]}], cut_file, kept_s}; exit 0 = clean,
3 = repeats found (cut applied when --cut given), 2 = error.
Cut = trim/atrim + concat with 10 ms fades, FB-safe High/yuv420p/L4.0 bt709 faststart.
Edges are the midpoints of the silence gaps around the repeat, snapped DOWN to frame times.
Report every cut (time + text + seconds removed) in the delivery.
"""
import argparse, json, math, os, re, subprocess, sys, tempfile, wave

THAI_MARKS = re.compile(r"[\s\u200b.,!?\"'“”…]+")


def norm(s):
    s = s.replace("ๆ", "")            # ASR writes ง่ายง่าย for ง่ายๆ; compare without the repeat mark
    return THAI_MARKS.sub("", s)


def script_text(path):
    t = open(path, encoding="utf-8").read() if os.path.exists(path) else path
    m = re.search(r'Audio \(Thai voiceover\)[^"“]*["“](.+?)["”]', t, re.S)
    return m.group(1) if m else t


def expand_mai_yamok(s):
    # "ง่ายๆ" -> "ง่ายง่าย" so the script and ASR spell the doubling the same way
    out = re.sub(r"([\u0E00-\u0E7F]{1,6}?)\s*ๆ", r"\1\1", s)
    return THAI_MARKS.sub("", out)


def asr_chars(wav):
    import numpy as np
    from faster_whisper import WhisperModel
    w = wave.open(wav)
    a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768
    m = WhisperModel("small", device="cpu", compute_type="int8")
    segs, _ = m.transcribe(a, language="th", vad_filter=False, word_timestamps=True)
    chars = []          # (char, t0, t1)
    for s in segs:
        for wd in s.words:
            txt = THAI_MARKS.sub("", wd.word)
            if not txt:
                continue
            n = len(txt)
            for k, c in enumerate(txt):
                chars.append((c, wd.start + (wd.end - wd.start) * k / n, wd.start + (wd.end - wd.start) * (k + 1) / n))
    return chars


def find_repeats(chars, script_x, min_len=4, max_len=24):
    s = "".join(c for c, _, _ in chars)
    found, i = [], 0
    while i < len(s):
        hit = None
        for L in range(min(max_len, (len(s) - i) // 2), min_len - 1, -1):
            a, b = s[i:i + L], s[i + L:i + 2 * L]
            if a == b and (a + a) not in script_x:
                hit = L
                break
        if hit:
            j0, j1 = i + hit, i + 2 * hit - 1          # second occurrence = the one we drop
            found.append({"text": s[j0:j1 + 1], "i0": j0, "i1": j1})
            i += 2 * hit
        else:
            i += 1
    return found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video"); ap.add_argument("--script", required=True)
    ap.add_argument("--cut"); ap.add_argument("--fps", type=float, default=24.0)
    ap.add_argument("--min", type=int, default=4)
    a = ap.parse_args()
    wd = tempfile.mkdtemp(prefix="rep_", dir=os.environ.get("TMPDIR", "/opt/data/cache/scratch"))
    wav = os.path.join(wd, "a.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", a.video, "-ac", "1", "-ar", "16000", wav], check=True)
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                a.video], capture_output=True, text=True, check=True).stdout)
    chars = asr_chars(wav)
    sx = expand_mai_yamok(script_text(a.script))
    reps = find_repeats(chars, sx, a.min)
    out = {"asr": "".join(c for c, _, _ in chars), "repeats": [], "cut_file": None, "kept_s": dur}
    fr = 1.0 / a.fps
    cuts = []
    for r in reps:
        t0, t1 = chars[r["i0"]][1], chars[r["i1"]][2]
        prev_end = chars[r["i0"] - 1][2] if r["i0"] > 0 else t0
        next_start = chars[r["i1"] + 1][1] if r["i1"] + 1 < len(chars) else min(dur, t1 + 0.1)
        # never eat into the kept words: start >= previous word's end, end <= next word's start - 30 ms
        ca = max(math.floor(((prev_end + t0) / 2) / fr) * fr, math.ceil(prev_end / fr - 1e-6) * fr)
        cb = math.floor(min((t1 + next_start) / 2, next_start - 0.03) / fr) * fr
        if cb - ca < 0.2:
            continue
        cuts.append((round(ca, 3), round(cb, 3)))
        out["repeats"].append({"text": r["text"], "t0": round(t0, 2), "t1": round(t1, 2), "cut": [round(ca, 3), round(cb, 3)]})
    if cuts and a.cut:
        keep, last = [], 0.0
        for ca, cb in cuts:
            keep.append((last, ca)); last = cb
        keep.append((last, dur))
        fv, fa, cat = [], [], ""
        for k, (x, y) in enumerate(keep):
            fv.append(f"[0:v]trim={x}:{y},setpts=PTS-STARTPTS[v{k}]")
            fa.append(f"[0:a]atrim={x}:{y},asetpts=PTS-STARTPTS,afade=t=in:d=0.01,"
                      f"afade=t=out:st={max(0, y - x - 0.01):.3f}:d=0.01[a{k}]")
            cat += f"[v{k}][a{k}]"
        fc = ";".join(fv + fa) + f";{cat}concat=n={len(keep)}:v=1:a=1[v][a]"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", a.video, "-filter_complex", fc, "-map", "[v]", "-map", "[a]",
                        "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.0",
                        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
                        "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", a.cut], check=True)
        out["cut_file"] = a.cut
        out["kept_s"] = round(sum(y - x for x, y in keep), 3)
    print(json.dumps(out, ensure_ascii=False))
    sys.exit(3 if out["repeats"] else 0)


if __name__ == "__main__":
    main()
