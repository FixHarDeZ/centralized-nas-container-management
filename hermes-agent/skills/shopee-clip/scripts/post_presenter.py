#!/usr/bin/env python3
"""Post-production for Google-Flow `presenter` scenes rendered with NO on-screen text.

Flow burns garbled Thai into its own captions, so the prompt now forbids ALL
on-screen text (block in references/presenter-post.md) and we add text here:
  * EN caption pills (Fredoka-SemiBold 40, pastel boxes)  -- from a plan
  * burned Thai subtitles (Itim 46, libass box)          -- KNOWN script text,
    timed by faster-whisper ASR of Flow's own voiceover + silence snapping
  * head-freeze trim, hook whoosh (+ optional seam whooshes), xfade stitch,
    loudness master via gameplay-clips/scripts/master.sh, FB-safe encode.

Usage:
  uv run --with faster-whisper --with numpy --with pillow --with pythainlp \
      python post_presenter.py plan.json [--workdir DIR] [--out out.mp4] [--sheet]

plan.json:
{
  "scenes": [
    {"video": "scene1_raw.mp4",
     "prompt": "prompt_s1.txt",          # script = text inside  Audio (Thai voiceover): "..."
     # or "script": "น้ำดื่มที่บ้าน... ลองดูอันนี้สิ ..."   (spaces = phrase breaks)
     "pills": [{"text": "Clean Water", "start": 0.4, "end": 2.2}]   # scene-LOCAL secs (after trim)
    },
    {"video": "scene2_raw.mp4", "prompt": "prompt_s2.txt",
     "pills": [{"text": "Mineral Rich", "start": 1.0, "end": 3.0},
               {"text": "Link below!", "start": 7.6, "end": 9.6}]}
  ],
  "xfade": 0.25,            # seconds; 0 = hard cut
  "seam_whoosh": true,      # extra whoosh at each seam (hook whoosh is always on)
  "model": "auto",          # small | medium | auto (small, escalate to medium if CER > 0.35)
  "trim": "auto"            # auto | 0 | <seconds> (single value or list per scene)
}
Outputs in workdir: subs.ass, pills.txt, out.mp4 (mastered), report.json, [sheet.jpg]
"""
import argparse, json, math, os, re, shutil, subprocess, sys, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
GP = os.path.normpath(os.path.join(HERE, "..", "..", "gameplay-clips"))
FONTS = os.path.join(GP, "fonts")
MASTER = os.path.join(GP, "scripts", "master.sh")

PILL_COLORS = ["0xFF8FB1", "0xFFD166", "0x8AC926", "0x7A5CFF"]
CTA = "Link below!"
SUB_FONT, SUB_SIZE = "Itim", 46
SUB_MAXW = 480            # px per subtitle line: text area x60-580 (safe-zones.md) - 2*16 box outline - slack
STYLE_HDR = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Itim,48,&H0066D1FF,&H0066D1FF,&H00203050,&H60203050,1,0,0,0,100,100,0,0,1,5,2.5,2,60,140,{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def sh(cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw)


def ffdur(path, stream="v:0"):
    out = sh(["ffprobe", "-v", "error", "-select_streams", stream, "-show_entries",
              "stream=duration", "-of", "csv=p=0", path]).stdout.strip()
    return float(out)


# ---------------------------------------------------------------- 1. head freeze
def head_freeze(video, noise=0.003, mind=0.08):
    """-> seconds of static video at t=0 (0 when none / not at head)."""
    err = subprocess.run(["ffmpeg", "-hide_banner", "-t", "1.5", "-i", video, "-an", "-vf",
                          f"freezedetect=n={noise}:d={mind}", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    st = re.findall(r"freeze_start: ([\d.]+)", err)
    du = re.findall(r"freeze_duration: ([\d.]+)", err)
    if st and float(st[0]) < 0.05 and du:
        return float(du[0])
    if st and float(st[0]) < 0.05:          # freeze still running at 1.5s cut
        return 1.5
    return 0.0


# ---------------------------------------------------------------- 2. ASR + alignment
TH_DIGIT = {"0": "ศูนย์", "1": "หนึ่ง", "2": "สอง", "3": "สาม", "4": "สี่", "5": "ห้า",
            "6": "หก", "7": "เจ็ด", "8": "แปด", "9": "เก้า", "10": "สิบ"}


def expand_mai_yamok(s):
    """`ใสๆ` -> `ใสใส`: the VO repeats the word, so the script must too, or the
    repeat shows up as a bogus 'Flow said something not in the script' insertion."""
    while "ๆ" in s:
        i = s.index("ๆ")
        head = s[:i].rstrip()
        try:
            from pythainlp.tokenize import word_tokenize
            last = word_tokenize(head, engine="newmm")[-1] if head else ""
        except Exception:
            last = head[-2:]
        s = head + last + s[i + 1:]
    return s


def norm(s):
    s = re.sub(r"\d+", lambda m: TH_DIGIT.get(m.group(), m.group()), s)
    s = expand_mai_yamok(s).lower()
    return "".join(c for c in s if unicodedata.category(c)[0] in "LM")


def base_len(s):  # visible width proxy: chars that are not combining marks
    return sum(1 for c in s if unicodedata.category(c) != "Mn")


def script_from_prompt(path):
    t = open(path, encoding="utf-8").read()
    m = re.search(r'Audio \(Thai voiceover\):\s*\n?\s*"(.+?)"', t, re.S)
    if not m:
        raise SystemExit(f"no `Audio (Thai voiceover): \"...\"` block in {path}")
    return m.group(1).strip()


def pcm16k(video, ss, dur):
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", video,
                          "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


_MODELS = {}


def asr(audio, model_name, prompt=None):
    from faster_whisper import WhisperModel
    if model_name not in _MODELS:
        # one model in RAM at a time: small + medium together reached ~3.5 GB and the gateway's
        # 4 GB cgroup killed the run twice (2026-11-12). A reload costs seconds.
        _MODELS.clear()
        import gc
        gc.collect()
        _MODELS[model_name] = WhisperModel(model_name, device="cpu", compute_type="int8")
    segs, _ = _MODELS[model_name].transcribe(audio, language="th", word_timestamps=True,
                                              beam_size=5, vad_filter=False, initial_prompt=prompt)
    segs = list(segs)
    chars = []   # (normalized char, t0, t1)
    for s in segs:
        for w in s.words:
            n = norm(w.word)
            if not n:
                continue
            step = (w.end - w.start) / len(n)
            for k, c in enumerate(n):
                chars.append((c, w.start + k * step, w.start + (k + 1) * step))
    return {"text": "".join(s.text for s in segs).strip(),
            "segments": [(s.start, s.end, s.text.strip()) for s in segs], "chars": chars}


def lev_align(a, b):
    """Levenshtein alignment -> list of (i or None, j or None, op) with op in M/S/D/I."""
    n, m = len(a), len(b)
    D = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        D[i][0] = i
    for j in range(m + 1):
        D[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            D[i][j] = min(D[i-1][j-1] + (a[i-1] != b[j-1]), D[i-1][j] + 1, D[i][j-1] + 1)
    i, j, path = n, m, []
    while i or j:
        if i and j and D[i][j] == D[i-1][j-1] + (a[i-1] != b[j-1]):
            path.append((i-1, j-1, "M" if a[i-1] == b[j-1] else "S")); i -= 1; j -= 1
        elif i and D[i][j] == D[i-1][j] + 1:
            path.append((i-1, None, "D")); i -= 1
        else:
            path.append((None, j-1, "I")); j -= 1
    return path[::-1], D[n][m]


def align_script(phrases, A, speech, subs_as_ins=False):
    """phrases: [display str]; A: asr chars; speech: (t0, t1) of voiced region.
    -> per-phrase dicts {text,t0,t1,ratio,status}, inserted flags, mode."""
    S, owner = [], []
    for k, p in enumerate(phrases):
        for c in norm(p):
            S.append(c); owner.append(k)
    a_str = "".join(c for c, _, _ in A)
    path, dist = lev_align(S, a_str) if A else ([], len(S))
    sim = sum(1 for _, _, op in path if op == "M") / max(1, len(S))
    res = [{"text": p, "idx": [], "m": 0, "n": len(norm(p))} for p in phrases]
    for i, j, op in path:
        if i is not None and j is not None:
            res[owner[i]]["idx"].append(j)
            res[owner[i]]["m"] += op == "M"
    inserted, run = [], []
    for i, j, op in path + [(0, None, "END")]:
        if op == "I" or (subs_as_ins and op == "S"):
            run.append(j)
        else:
            if len(run) >= 3:
                inserted.append({"asr": "".join(a_str[x] for x in run),
                                 "t0": round(A[run[0]][1], 2), "t1": round(A[run[-1]][2], 2)})
            run = []
    mode = "aligned" if sim >= 0.5 else "proportional"
    total = max(1, len(S))
    if mode == "proportional":
        # ASR text too far from script: spread phrases over the voiced span by char share
        t0, t1 = speech
        pos = 0
        for r in res:
            r["t0"] = t0 + (t1 - t0) * pos / total
            pos += r["n"]
            r["t1"] = t0 + (t1 - t0) * pos / total
            r["ratio"] = r["m"] / max(1, r["n"])
            r["status"] = "proportional"
        return res, inserted, mode, sim, dist
    for r in res:
        r["ratio"] = r["m"] / max(1, r["n"])
        good = [j for j in r["idx"]]
        if r["ratio"] >= 0.3 and good:
            r["t0"], r["t1"] = A[min(good)][1], A[max(good)][2]
            r["status"] = "matched" if r["ratio"] >= 0.6 else "partial"
        else:
            r["t0"] = r["t1"] = None
            r["status"] = "unmatched"
    # fallback: unmatched phrase -> proportional slot between timed neighbours
    for k, r in enumerate(res):
        if r["t0"] is not None:
            continue
        lo = next((res[x]["t1"] for x in range(k - 1, -1, -1) if res[x]["t0"] is not None), speech[0])
        hi = next((res[x]["t0"] for x in range(k + 1, len(res)) if res[x]["t0"] is not None), speech[1])
        grp = [x for x in range(len(res)) if res[x]["t0"] is None and
               all(res[y]["t0"] is None for y in range(min(x, k), max(x, k) + 1))]
        tot = sum(res[x]["n"] for x in grp) or 1
        before = sum(res[x]["n"] for x in grp if x < k)
        r["t0"] = lo + (hi - lo) * before / tot
        r["t1"] = lo + (hi - lo) * (before + r["n"]) / tot
        # nothing audible in that slot -> Flow skipped the phrase
        r["status"] = "SKIPPED" if (r["t1"] - r["t0"]) < 0.06 * r["n"] else "fallback"
    return res, inserted, mode, sim, dist


def silences(video, ss, dur, noise=-30, d=0.08):
    err = subprocess.run(["ffmpeg", "-hide_banner", "-ss", f"{ss:.3f}", "-t", f"{dur:.3f}", "-i", video,
                          "-vn", "-af", f"silencedetect=noise={noise}dB:d={d}", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    st = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", err)]
    en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", err)]
    while len(en) < len(st):
        en.append(dur)
    return [(max(0.0, a), b) for a, b in zip(st, en)]


def timing_error(A, sil, dur):
    """ASR char boundaries vs silencedetect pauses (internal pauses only)."""
    errs = []
    gaps = [(A[i][2], A[i+1][1]) for i in range(len(A) - 1)]
    for s0, s1 in sil:
        if s0 <= 0.01 or s1 >= dur - 0.05:
            continue
        mid = (s0 + s1) / 2
        if not gaps:
            break
        g = min(gaps, key=lambda g: abs((g[0] + g[1]) / 2 - mid))
        errs.append({"pause": (round(s0, 2), round(s1, 2)), "asr_gap": (round(g[0], 2), round(g[1], 2)),
                     "err_end_of_speech": round(g[0] - s0, 3), "err_start_of_speech": round(g[1] - s1, 3)})
    onset = None
    if sil and sil[0][0] <= 0.01 and A:
        onset = round(A[0][1] - sil[0][1], 3)
    return errs, onset


def snap(t, edges, win):
    best = min(edges, key=lambda e: abs(e - t), default=None)
    return best if best is not None and abs(best - t) <= win else None


# ---------------------------------------------------------------- subtitle layout
_FONT = None


def text_w(s):
    global _FONT
    from PIL import ImageFont
    if _FONT is None:
        _FONT = ImageFont.truetype(os.path.join(FONTS, "Itim-Regular.ttf"), SUB_SIZE)
    return _FONT.getlength(s) * 1.06   # Bold=1 in the style -> libass faux-bold widens ~5%


def split_thai(s):
    """Split one long Thai phrase into 2 lines at a word boundary near the middle."""
    try:
        from pythainlp.tokenize import word_tokenize
        words = word_tokenize(s, engine="newmm")
    except Exception:
        words = list(s)
    best, bi = None, None
    acc = ""
    for k in range(1, len(words)):
        acc += words[k - 1]
        rest = "".join(words[k:])
        cost = max(text_w(acc), text_w(rest))
        if best is None or cost < best:
            best, bi = cost, acc
    return [bi, s[len(bi):]] if bi else [s]


def build_events(phr, max_dur=3.2, max_gap=0.35):
    """Greedy merge of consecutive timed phrases into <=2-line events."""
    ev = []
    for p in phr:
        if p["status"] == "SKIPPED":
            continue
        if ev:
            e = ev[-1]
            cand = e["lines"][-1] + " " + p["text"]
            gap = p["t0"] - e["t1"]
            if gap < max_gap and p["t1"] - e["t0"] <= max_dur:
                if text_w(cand) <= SUB_MAXW:
                    e["lines"][-1] = cand; e["t1"] = p["t1"]; e["src"].append(p["text"]); continue
                if len(e["lines"]) == 1 and text_w(p["text"]) <= SUB_MAXW:
                    e["lines"].append(p["text"]); e["t1"] = p["t1"]; e["src"].append(p["text"]); continue
        lines = [p["text"]] if text_w(p["text"]) <= SUB_MAXW else split_thai(p["text"])
        ev.append({"t0": p["t0"], "t1": p["t1"], "lines": lines, "src": [p["text"]]})
    return ev


def ts(t):
    t = max(t, 0.0)
    return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"


# ---------------------------------------------------------------- 4. whoosh
def make_whoosh(path, dur=0.55, f0=250, f1=4500):
    steps, lines = 28, []
    for k in range(steps + 1):
        x = k / steps
        f = f0 * (f1 / f0) ** (math.sin(math.pi * x) if x < 0.5 else 1.0 - 0.6 * (x - 0.5) * 2)
        lines.append(f"{dur * x:.3f} bandpass@bp f {f:.0f};")
    cmd = path + ".cmd"
    open(cmd, "w").write("\n".join(lines) + "\n")
    sh(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"anoisesrc=d={dur}:c=pink:r=48000:a=0.9",
        "-af", f"asendcmd=f={cmd},bandpass@bp=f={f0}:width_type=q:w=1.4,"
               f"afade=t=in:d={dur*0.45:.3f}:curve=exp,afade=t=out:st={dur*0.45:.3f}:d={dur*0.55:.3f}:curve=log,"
               f"aecho=0.6:0.5:40:0.25,loudnorm=I=-20:TP=-6,aformat=channel_layouts=stereo",
        "-ar", "48000", path])
    os.remove(cmd)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan")
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--out", default="out.mp4")
    ap.add_argument("--sheet", action="store_true", help="also write sheet.jpg contact sheet")
    ap.add_argument("--sub-marginv", type=int, default=465,
                    help="465 = 2-line box bottom ~y830, inside the y832 bottom-UI band (safe-zones.md)")
    ap.add_argument("--pill-y", type=int, default=210,
                    help="210 = pill box ~y196-252, below the y192 top-UI band (safe-zones.md)")
    ap.add_argument("--whoosh-gain", type=float, default=0.35, help="linear gain of whoosh vs VO bed")
    a = ap.parse_args()
    import heavylock
    heavylock.acquire("post_presenter")
    plan = json.load(open(a.plan, encoding="utf-8"))
    pdir = os.path.dirname(os.path.abspath(a.plan))
    wd = os.path.abspath(a.workdir or pdir)
    os.makedirs(os.path.join(wd, "fonts"), exist_ok=True)
    for f in ("Itim-Regular.ttf", "Fredoka-SemiBold.ttf"):
        shutil.copy(os.path.join(FONTS, f), os.path.join(wd, "fonts", f))
    P = lambda p: p if os.path.isabs(p) else os.path.join(pdir, p)
    scenes = plan["scenes"]
    xf = float(plan.get("xfade", 0.25)) if len(scenes) > 1 else 0.0
    trims = plan.get("trim", "auto")
    model_pref = plan.get("model", "auto")
    report = {"scenes": [], "flags": []}

    # ---- per scene: trim, ASR, align
    gstart, events, pills = 0.0, [], []
    for k, sc in enumerate(scenes):
        v = P(sc["video"])
        vd = ffdur(v)
        tr = trims[k] if isinstance(trims, list) else trims
        fz = head_freeze(v)
        T = (min(fz, 0.8) if fz >= 0.08 else 0.0) if tr == "auto" else float(tr)
        D = round(vd - T, 3)
        if sc.get("silent"):
            # H / B-roll shot with no voiceover (music + SFX only): no ASR, no subs, pills only
            for pl in sc.get("pills", []):
                pills.append({"text": pl["text"], "t0": gstart + pl["start"], "t1": gstart + pl["end"], "scene": k})
            report["scenes"].append({"video": sc["video"], "silent": True, "freeze_head_s": round(fz, 3),
                                     "trim_s": round(T, 3), "dur_s": D, "global_start": round(gstart, 3),
                                     "events": 0})
            gstart += D - (xf if k < len(scenes) - 1 else 0.0)
            sc["_T"], sc["_D"] = T, D
            continue
        script = sc.get("script") or script_from_prompt(P(sc["prompt"]))
        phrases = [p for p in re.split(r"\s+", script) if p]
        audio = pcm16k(v, T, D)
        models = ["small", "medium"] if model_pref == "auto" else [model_pref]
        cerf = lambda r: round(lev_align(norm(script), "".join(c for c, _, _ in r["chars"]))[1]
                               / max(1, len(norm(script))), 3)
        best = None
        for mn in models:
            # pass 1, UNPROMPTED: honest check of what Flow actually said (CER, skips, insertions)
            r = asr(audio, mn)
            r.update(model=mn, cer=cerf(r))
            if best is None or r["cer"] < best["cer"]:
                best = r
            if r["cer"] <= 0.35:
                break
        # pass 2, VOCAB-PROMPTED: Whisper then spells brand names / loanwords the script's way
        # (Giferin->กิฟฟารีน), so far more phrases align -> better timing. The prompt is the
        # distinct phrases, longest first, comma-joined - NOT the script verbatim: a verbatim
        # prompt (or hotwords=script) makes Whisper treat the opening as "already said" and drop
        # it (scene1: first 5 phrases vanished, CER 0.62). Never use pass 2 for the "did Flow
        # say it" check: the prompt biases the transcript.
        vocab = ", ".join(sorted(dict.fromkeys(phrases), key=len, reverse=True))
        rp = asr(audio, best["model"], prompt=vocab)
        rp["cer"] = cerf(rp)
        A = rp["chars"] if rp["chars"] and rp["cer"] <= best["cer"] else best["chars"]
        sil = silences(v, T, D)
        sp0 = sil[0][1] if sil and sil[0][0] <= 0.01 else (A[0][1] if A else 0.0)
        sp1 = sil[-1][0] if sil and sil[-1][1] >= D - 0.05 else (A[-1][2] if A else D)
        # prompted transcript spells script words the script's way, so any run of >=3 ASR chars
        # it cannot match (I or S) is speech Flow added (scene2b: a repeated "สองปี")
        phr, ins_p, mode, sim, _ = align_script(phrases, A, (sp0, sp1), subs_as_ins=A is rp["chars"])
        free, ins, _, _, _ = align_script(phrases, best["chars"], (sp0, sp1))  # unprompted view
        for x in ins_p:
            if not any(x["t0"] < y["t1"] and y["t0"] < x["t1"] for y in ins):
                ins.append(x)
        for p, f in zip(phr, free):
            p["free_status"] = f["status"]
            if f["status"] == "SKIPPED" and p["status"] != "matched":
                p["status"] = "SKIPPED"
        terr, onset = timing_error(A, sil, D)

        # silence snapping: speech edges from silencedetect beat Whisper's cross-attention times
        starts = [b for a_, b in sil]           # speech resumes
        ends = [a_ for a_, b in sil]            # speech stops
        evs = build_events(phr)
        nsnap = 0
        for e in evs:
            s = snap(e["t0"], starts, 0.30)
            if s is not None:
                e["t0"] = max(0.0, s - 0.05); nsnap += 1
            else:
                e["t0"] = max(0.0, e["t0"] - 0.05)
            s = snap(e["t1"], ends, 0.35)
            if s is not None:
                e["t1"] = s + 0.10; nsnap += 1
            else:
                e["t1"] = e["t1"] + 0.12
            e["t1"] = min(e["t1"], D)
        for e in evs:
            e["t0"] += gstart; e["t1"] += gstart; e["scene"] = k
        events += evs

        for pl in sc.get("pills", []):
            pills.append({"text": pl["text"], "t0": gstart + pl["start"], "t1": gstart + pl["end"], "scene": k})

        st = {"video": sc["video"], "freeze_head_s": round(fz, 3), "trim_s": round(T, 3), "dur_s": D,
              "global_start": round(gstart, 3), "asr_model": best["model"], "asr_text": best["text"],
              "cer": best["cer"], "cer_prompted": rp["cer"], "asr_text_prompted": rp["text"],
              "timing_from": "prompted" if A is rp["chars"] else "unprompted", "align_mode": mode, "char_match": round(sim, 3),
              "phrases_total": len(phrases),
              "phrases_matched": sum(p["status"] == "matched" for p in phr),
              "phrases_partial": sum(p["status"] == "partial" for p in phr),
              "phrases_matched_unprompted": sum(p["free_status"] == "matched" for p in phr),
              "phrases": [{"text": p["text"], "status": p["status"], "free": p["free_status"],
                           "ratio": round(p["ratio"], 2),
                           "t0": round(p["t0"], 2), "t1": round(p["t1"], 2)} for p in phr],
              "inserted_by_flow": ins, "speech_onset_err_s": onset, "pause_errors": terr,
              "boundaries_snapped": nsnap, "events": len(evs)}
        for p in phr:
            if p["status"] == "SKIPPED":
                report["flags"].append(f"scene{k+1}: script phrase '{p['text']}' SKIPPED - no audio "
                                       f"left for it between its neighbours; subtitle dropped")
            elif p["status"] == "partial":
                report["flags"].append(f"scene{k+1}: script phrase '{p['text']}' only {p['ratio']:.0%} heard "
                                       f"@{p['t0']:.2f}-{p['t1']:.2f}s - Flow probably dropped part of it; the "
                                       f"subtitle still shows the full phrase -> listen, reroll or edit")
            elif p["status"] == "fallback":
                report["flags"].append(f"scene{k+1}: script phrase '{p['text']}' timing interpolated "
                                       f"{p['t0']:.2f}-{p['t1']:.2f}s (ASR spelled it differently, e.g. "
                                       f"Latin brand name, or Flow garbled it) - listen to confirm")
        for i in ins:
            report["flags"].append(f"scene{k+1}: Flow said '{i['asr']}' @{i['t0']}-{i['t1']}s "
                                   f"(ASR) - not in script, no subtitle shown")
        report["scenes"].append(st)
        gstart += D - (xf if k < len(scenes) - 1 else 0.0)
        sc["_T"], sc["_D"] = T, D
    total = round(gstart, 3)

    # ---- resolve event overlaps (xfade seams / tight merges)
    events.sort(key=lambda e: e["t0"])
    for i in range(len(events) - 1):
        a_, b_ = events[i], events[i + 1]
        if a_["t1"] > b_["t0"] - 0.04:
            a_["t1"] = b_["t0"] - 0.04
    events = [e for e in events if e["t1"] - e["t0"] >= 0.3]
    with open(os.path.join(wd, "subs.ass"), "w", encoding="utf-8") as f:
        f.write(STYLE_HDR.format(mv=a.sub_marginv))
        for e in events:
            f.write(f"Dialogue: 0,{ts(e['t0'])},{ts(e['t1'])},Sub,,0,0,0,,{'\\N'.join(e['lines'])}\n")

    # ---- 3. pills: validate
    last = len(scenes) - 1
    # NO_AUTO_CTA=1 skips the auto-added final pill (clips where Fix ruled out the link line)
    if not os.environ.get("NO_AUTO_CTA") and not any(p["text"] == CTA for p in pills if p["scene"] == last):
        sc = scenes[last]
        t1 = total - 0.15
        pills.append({"text": CTA, "t0": t1 - 2.2, "t1": t1, "scene": last})
        report["flags"].append(f"no CTA pill in final scene -> auto-added '{CTA}' {t1-2.2:.2f}-{t1:.2f}")
    pills.sort(key=lambda p: p["t0"])
    for p in pills:
        if len(p["text"].split()) > 2:
            raise SystemExit(f"pill '{p['text']}' has >2 words")
        if re.search(r"[\u0E00-\u0E7F]", p["text"]):
            raise SystemExit(f"pill '{p['text']}' contains Thai glyphs (banned on pills)")
        if p["text"] == CTA and p["scene"] != last:
            raise SystemExit(f"CTA pill in scene {p['scene']+1}; only the final scene may carry it")
        p["t1"] = min(p["t1"], total)
    for x, y in zip(pills, pills[1:]):
        if y["t0"] < x["t1"]:
            raise SystemExit(f"pills overlap: '{x['text']}' {x['t1']:.2f} > '{y['text']}' {y['t0']:.2f}")
    chain = []
    for i, p in enumerate(pills):
        tf = os.path.join(wd, f"pill_{i}.txt")
        open(tf, "w", encoding="utf-8").write(p["text"])
        chain.append(f"drawtext=fontfile={wd}/fonts/Fredoka-SemiBold.ttf:textfile={tf}:fontcolor=white:"
                     f"fontsize=40:borderw=3:bordercolor=0x5A2A4A:box=1:"
                     f"boxcolor={PILL_COLORS[i % 4]}@0.92:boxborderw=14:x=(w-text_w)/2:y={a.pill_y}:"
                     f"enable='between(t,{p['t0']:.3f},{p['t1']:.3f})'")
    with open(os.path.join(wd, "pills.txt"), "w") as f:
        for p in pills:
            f.write(f"{p['t0']:.2f}-{p['t1']:.2f}\t{p['text']}\n")

    # ---- 4. whoosh track
    wh = os.path.join(wd, "whoosh.wav")
    make_whoosh(wh)
    hits = [0.0]
    if plan.get("seam_whoosh", True):
        hits += [s["global_start"] - 0.25 for s in report["scenes"][1:]]

    # ---- filter graph
    ins, fv, fa = [], [], []
    for k, sc in enumerate(scenes):
        ins += ["-i", P(sc["video"])]
        fv.append(f"[{k}:v]trim=start={sc['_T']}:duration={sc['_D']},setpts=PTS-STARTPTS,"
                  f"fps=24,format=yuv420p,settb=AVTB[v{k}]")
        fa.append(f"[{k}:a]atrim=start={sc['_T']}:duration={sc['_D']},asetpts=PTS-STARTPTS,"
                  f"aresample=48000,aformat=channel_layouts=stereo[a{k}]")
    n = len(scenes)
    vl, al, off = "v0", "a0", 0.0
    for k in range(1, n):
        off += scenes[k-1]["_D"] - xf
        if xf > 0:
            fv.append(f"[{vl}][v{k}]xfade=transition=fade:duration={xf}:offset={off:.3f}[vx{k}]")
            fa.append(f"[{al}][a{k}]acrossfade=d={xf}[ax{k}]")
        else:
            fv.append(f"[{vl}][v{k}]concat=n=2:v=1:a=0[vx{k}]")
            fa.append(f"[{al}][a{k}]concat=n=2:v=0:a=1[ax{k}]")
        vl, al = f"vx{k}", f"ax{k}"
    ins += ["-i", wh]
    fa.append(f"[{n}:a]volume={a.whoosh_gain},asplit={len(hits)}" + "".join(f"[w{i}]" for i in range(len(hits))))
    for i, h in enumerate(hits):
        fa.append(f"[w{i}]adelay={int(max(0, h) * 1000)}:all=1[wd{i}]")
    fa.append(f"[{al}]" + "".join(f"[wd{i}]" for i in range(len(hits))) +
              f"amix=inputs={len(hits)+1}:duration=first:normalize=0,apad=whole_dur={total}[aout]")
    # Flow tags its mp4s sRGB (trc iec61966-2-1); frame props beat -color_trc, so retag here
    vchain = (",".join(chain) + "," if chain else "") + (f"ass={wd}/subs.ass:fontsdir={wd}/fonts:shaping=complex,format=yuv420p,"
              f"setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv")
    fv.append(f"[{vl}]{vchain}[vout]")
    pre = os.path.join(wd, "premaster.mp4")
    enc = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
           "-profile:v", "high", "-level", "4.0", "-colorspace", "bt709", "-color_primaries", "bt709",
           "-color_trc", "bt709", "-color_range", "tv"]
    sh(["ffmpeg", "-y", "-v", "error", *ins, "-filter_complex", ";".join(fv + fa),
        "-map", "[vout]", "-map", "[aout]", *enc, "-c:a", "alac", "-ar", "48000", "-ac", "2",
        "-t", f"{total}", pre], timeout=1200)

    # ---- 5. loudness master (gameplay-clips/scripts/master.sh, in place) + faststart remux
    m = sh(["bash", MASTER, pre]).stdout.strip()
    out = a.out if os.path.isabs(a.out) else os.path.join(wd, a.out)
    sh(["ffmpeg", "-y", "-v", "error", "-i", pre, "-c", "copy", "-movflags", "+faststart", out])
    os.remove(pre)
    report["master"] = m
    report["out"] = out
    report["duration_target"] = total
    report["v_dur"] = ffdur(out, "v:0")
    report["a_dur"] = ffdur(out, "a:0")
    report["pills"] = [(round(p["t0"], 2), round(p["t1"], 2), p["text"]) for p in pills]
    report["subs"] = [(round(e["t0"], 2), round(e["t1"], 2), " / ".join(e["lines"])) for e in events]
    report["whoosh_at"] = [round(h, 2) for h in hits]
    json.dump(report, open(os.path.join(wd, "report.json"), "w"), ensure_ascii=False, indent=1)

    if a.sheet:
        contact_sheet(out, pills, events, os.path.join(wd, "sheet.jpg"))

    # ---- console summary
    for s in report["scenes"]:
        if s.get("silent"):
            print(f"{s['video']}: trim={s['trim_s']}s SILENT (no ASR/subs)")
            continue
        pe = [abs(x["err_end_of_speech"]) for x in s["pause_errors"]] + \
             [abs(x["err_start_of_speech"]) for x in s["pause_errors"]]
        print(f"{s['video']}: trim={s['trim_s']}s model={s['asr_model']} CER={s['cer']} "
              f"(prompted {s['cer_prompted']}, timing from {s['timing_from']}) "
              f"match={s['phrases_matched']}+{s['phrases_partial']}p/{s['phrases_total']} mode={s['align_mode']} "
              f"pause_err mean={sum(pe)/len(pe) if pe else 0:.3f}s max={max(pe) if pe else 0:.3f}s "
              f"onset_err={s['speech_onset_err_s']} snapped={s['boundaries_snapped']}")
    for f in report["flags"]:
        print("FLAG:", f)
    print(m)
    print(f"OUT {out} v={report['v_dur']:.3f} a={report['a_dur']:.3f} target={total}")


def contact_sheet(video, pills, events, path):
    from PIL import Image, ImageDraw
    pts = [((p["t0"] + p["t1"]) / 2, "pill " + p["text"]) for p in pills]
    pts += [((e["t0"] + e["t1"]) / 2, f"sub {i}") for i, e in enumerate(events)]
    pts.sort()
    tiles = []
    for t, lab in pts:
        f = path + f".{t:.2f}.png"
        sh(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.3f}", "-i", video, "-frames:v", "1",
            "-vf", "scale=240:-2", f])
        im = Image.open(f).convert("RGB"); os.remove(f)
        d = ImageDraw.Draw(im)
        d.rectangle((0, 0, 240, 18), fill=(0, 0, 0)); d.text((3, 3), f"{t:.2f}s {lab}"[:38], fill=(255, 255, 0))
        tiles.append(im)
    cols = 6
    rows = math.ceil(len(tiles) / cols)
    W, H = tiles[0].size
    sheet = Image.new("RGB", (cols * W, rows * H), (40, 40, 40))
    for i, im in enumerate(tiles):
        sheet.paste(im, ((i % cols) * W, (i // cols) * H))
    sheet.save(path, quality=88)
    print("sheet:", path, [f"{t:.2f} {l}" for t, l in pts])


if __name__ == "__main__":
    main()
