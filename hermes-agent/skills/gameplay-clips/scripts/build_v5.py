#!/usr/bin/env python3
"""build_v5.py — LOOK v5 gameplay clip builder, driven by plan.json.

Run:   uv run --with numpy --with pillow python build_v5.py plan.json [--check] [--selftest-zoom]
  --check          validate + resolve (beat snap, timeline, pills) and print it; no render
  --selftest-zoom  prove the push-in transform has no sub-pixel wobble (synthetic target), then exit

Pipeline (one x264 encode): Python decodes every seg as raw RGB (ffmpeg), applies a sub-pixel affine
push-in (window) or a sharp 9:16 centre crop of the ORIGINAL 1080p trailer (hero), composites onto
bg.png, adds seam flashes / logo / loop-tail crossfade, pipes rgb24 @30 fps into ffmpeg, which burns
the EN pills (drawtext) + Thai subs (libass) and mixes audio: per-seg trailer music (exact sample
length, 8 ms edge fades) + seam SFX -> volume -> sidechaincompress keyed by the Thai VO -> amix with VO.

plan.json schema (paths relative to the plan file's directory unless absolute)
{
  "dur": 20.0,                       # clip length (s); last seg absorbs the remainder
  "fps": 30,
  "master": "master.mp4",            # 720x1280 trailer master (720x405 picture at y=320)
  "trailer": "trailer.mp4",          # ORIGINAL trailer (1080p) — hero source
  "bg": "bg.png", "vo": "vo.mp3", "subs": "subs.ass", "vtt": "subs.en.vtt",
  "fonts_dir": "fonts", "pill_font": "Fredoka-SemiBold.ttf",
  "out": "out.mp4",
  "window_y": 280,                   # safe-zones.md: window 280..685
  "pill_y": 210,                     # safe-zones.md: pill box ~196..252
  "sub_style": {"MarginV": 465, "MarginL": 60, "MarginR": 140},
  "sub_text": {"2": "line one\\Nline two"},   # optional per-event text override (0-based event idx)
  "zoom": [1.0, 1.10],               # window push-in start->end scale (per seg, linear)
  "hero_zoom": [1.0, 1.0],           # hero default = no resample beyond the crop (sharp)
  "speech_margin": 0.1,              # seg audio must sit >= this far inside a no-speech gap
  "beats": {"json": "work/beats_all.json", "window": 0.25, "cut_guard": 0.15},
  "release_date": "2026-09-18", "today": null,       # null = system date
  "release_pill": {"start": 0.0, "end": 2.3, "color": "0xFF8FB1"},  # text = D-N | OUT NOW
  "caps": [{"text": "OPEN WORLD", "start": 2.6, "end": 5.0, "color": "0xFFD166"}],
  "cta": {"text": "Link below!", "color": "0xFFD166", "lead": 0.15},   # last seg only
  "logo": {"png": "logo_v5.png", "start": 0.0, "end": 1.5, "w": 300, "y": 36},
  "flash": [0.5, 0.3, 0.12],         # white alpha on the first frames after each seam
  "sfx": {"dir": "<skill>/assets/sfx", "whoosh": 0.30, "impact": 0.45},
  "music_gain": 0.75, "vo_gain": 1.25,
  "vo_shift": [{"at": 13.32, "add": 2.0}],   # insert silence into the VO at VO-time `at`
                                              # (must be a VO pause); subs after `at` move too
  "loop_tail": 0.3,                  # last N s crossfade into output frame 0 (cold open)
  "grade": [1.18, 1.15, 1.04],       # eq gamma/saturation/contrast on all footage (per-seg "grade" overrides);
                                     # trailers are graded dark for TV — on a phone they read muddy
  "segs": [
    {"src": "trailer", "in": 63.55, "dur": 1.6, "mode": "hero", "sfx": "impact"},
    {"src": "master",  "in": 10.6,  "dur": 2.0, "mode": "window"},
    {"src": "trailer", "in": 93.8,  "dur": 4.2, "mode": "window", "audio_src": "master",
     "audio_in": 93.8, "snap": false, "hero_x": 0}
  ]
}
seg keys: src master|trailer|path; in; dur; mode window|hero; optional audio_src (default = master),
  audio_in (default = in), snap (default true: in snapped to a beat and out to the beat nearest
  in+dur, inside the gap, away from hard cuts), sfx whoosh|impact|both|none (default whoosh;
  hero -> both; seg 0 -> impact), hero_x (crop x offset from centre, px of the 1080p source),
  zoom [a,b] override.
Hard failures: seg audio outside a no-speech gap, overlapping pills, pill > 2 words / non-ASCII /
price-like text, CTA anywhere but the last seg, vo_shift not inside a VO pause.
"""
import argparse, datetime, json, os, re, subprocess, sys, time
import numpy as np
from PIL import Image

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 720, 1280
WW, WH = 720, 405
SR = 48000
GRADE = [1.0, 1.0, 1.0]  # set from plan["grade"] in main()


def die(msg):
    sys.exit("PLAN ERROR: " + msg)


def run(cmd, **kw):
    return subprocess.run(cmd, check=True, **kw)


def probe_dur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                 "-of", "csv=p=0", p], capture_output=True, text=True).stdout.strip())


# ---------------------------------------------------------------- speech gaps (vtt)
def vtt_gaps(path, total, margin):
    def sec(t):
        h, m, s = t.split(":") if t.count(":") == 2 else ("0",) + tuple(t.split(":"))
        return int(h) * 3600 + int(m) * 60 + float(s)
    txt = open(path, encoding="utf-8").read()
    speech = []
    for blk in re.split(r"\n\s*\n", txt):
        lines = blk.strip().splitlines()
        hdr = [l for l in lines if "-->" in l]
        if not hdr:
            continue
        a, b = hdr[0].split("-->")
        a, b = sec(a.strip().split()[0]), sec(b.strip().split()[0])
        body = " ".join(lines[lines.index(hdr[0]) + 1:])
        body = re.sub(r"<[^>]+>", "", body)
        if ">>" in body:
            speech.append((a, b)); continue
        body = re.sub(r"\[[^\]]*\]", "", body)
        if re.search(r"[A-Za-z]", body):
            speech.append((a, b))
    speech.sort()
    gaps, t = [], 0.0
    for a, b in speech:
        if a - margin > t + (margin if t > 0 else 0):
            gaps.append((t + (margin if t > 0 else 0), a - margin))
        t = max(t, b)
    if total - t > margin:
        gaps.append((t + margin, total))
    return gaps


def in_gap(gaps, a, b):
    return next((g for g in gaps if g[0] - 1e-6 <= a and b <= g[1] + 1e-6), None)


# ---------------------------------------------------------------- beats + hard cuts
def seg_windows(plan, pad=4.0):
    """Master-time ranges the plan actually touches (+pad). Beats/cuts are only needed there;
    scanning a whole long source (50-min gameplay capture) OOM-killed beats.py and load_cuts."""
    w = []
    for s in plan["segs"]:
        a = float(s.get("audio_in", s["in"]))
        d = float(s.get("dur", plan["dur"]))
        w.append((max(0.0, a - pad), a + d + pad))
    w.sort()
    out = []
    for a, b in w:
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def load_beats(plan, base, master):
    bj = plan.get("beats", {}).get("json", "work/beats_all.json")
    bj = os.path.join(base, bj)
    if not os.path.exists(bj):
        os.makedirs(os.path.dirname(bj), exist_ok=True)
        allb = []
        for a, b in seg_windows(plan):
            tmp = f"{bj}.{int(a)}.json"
            run([sys.executable, os.path.join(SKILL, "scripts", "beats.py"), master,
                 "--start", f"{a:.3f}", "--end", f"{b:.3f}", "--json", tmp], stdout=subprocess.DEVNULL)
            allb += json.load(open(tmp))["beats"]
        json.dump({"beats": sorted(set(round(x, 4) for x in allb))}, open(bj, "w"))
    return np.array(json.load(open(bj))["beats"])


def load_cuts(plan, base, master):
    """Hard cuts inside the seg windows only, streamed frame by frame (bounded memory)."""
    cj = os.path.join(base, "work", "cuts.json")
    if os.path.exists(cj):
        return np.array(json.load(open(cj))["cuts"])
    fs = 64 * 36
    cuts = []
    for a, b in seg_windows(plan):
        p = subprocess.Popen(["ffmpeg", "-v", "error", "-ss", f"{a:.3f}", "-t", f"{b - a:.3f}", "-i", master,
                              "-vf", "crop=720:405:0:320,scale=64:36,format=gray", "-r", "30",
                              "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
        prev, i = None, 0
        while True:
            buf = p.stdout.read(fs)
            if len(buf) < fs:
                break
            f = np.frombuffer(buf, np.uint8).astype(np.int16)
            if prev is not None and np.abs(f - prev).mean() > 12:
                cuts.append(round(a + i / 30, 3))
            prev, i = f, i + 1
        p.wait()
    os.makedirs(os.path.dirname(cj), exist_ok=True)
    json.dump({"cuts": cuts}, open(cj, "w"))
    return np.array(cuts)


def snap_seg(s, beats, cuts, gaps, win, guard, fps, last):
    p, d = s["in"], s["dur"]
    def cut_near(a, b):
        return bool(((cuts > a) & (cuts <= b)).any())
    best = None
    for b in beats[np.abs(beats - p) <= win]:
        if cut_near(b - 1e-3, b + guard):
            continue
        # out: a beat near in+dur (phrase-complete), or the planned length (+0.3 penalty);
        # the seam itself is on-beat either way because the NEXT seg starts on a beat.
        outs = [(b + d, 0.3)]
        if not last:
            outs += [(e, 0.0) for e in beats[(beats > b + 0.8) & (np.abs(beats - (b + d)) <= 0.45)]]
        bq = round(b * fps) / fps
        for e, pen in outs:
            e = bq + round((e - bq) * fps) / fps   # judge the frame-quantised range
            if not last and cut_near(e - guard, e - 1e-3):
                continue
            if not in_gap(gaps, bq, e):
                continue
            sc = abs(b - p) + 1.5 * abs((e - b) - d) + pen
            if best is None or sc < best[0]:
                best = (sc, b, e)
    if best is None:
        return p, d, False
    _, b, e = best
    b = round(b * fps) / fps
    return b, round((e - b) * fps) / fps, True


# ---------------------------------------------------------------- pills
PRICE = re.compile(r"[$฿€£¥%]|\b(baht|thb|usd|sale|off|free|discount|price)\b|\d+\s*(k|บาท)", re.I)


def check_pill(text):
    if len(text.split()) > 2:
        die(f"pill '{text}' > 2 words")
    if not all(32 <= ord(c) < 127 for c in text):
        die(f"pill '{text}' not plain ASCII English")
    if PRICE.search(text):
        die(f"pill '{text}' looks price/discount-like")


def release_text(plan):
    rd = datetime.date.fromisoformat(plan["release_date"])
    td = datetime.date.fromisoformat(plan["today"]) if plan.get("today") else datetime.date.today()
    n = (rd - td).days
    return f"D-{n}" if n > 0 else "OUT NOW"


def esc_dt(t):
    return t.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\u2019").replace("%", "\\%")


# ---------------------------------------------------------------- subs / vo
def ass_time(s):
    h = int(s // 3600); m = int(s % 3600 // 60); x = s - h * 3600 - m * 60
    return f"{h}:{m:02d}:{x:05.2f}"


def ass_sec(t):
    h, m, s = t.split(":"); return int(h) * 3600 + int(m) * 60 + float(s)


# v5 layout default (safe-zones.md): subs must sit in y700-835, the band graphics_layer
# checks stickers against. A source .ass carrying the old v4 MarginV 290 (y~945-1014)
# silently lands the subs OUTSIDE that band, so a game-cover sticker placed "below the
# subs" overlaps them (Ratatan 2026-11-11). Default here; plan.sub_style overrides.
SUB_STYLE_V5 = {"MarginV": 465, "MarginL": 60, "MarginR": 140}


def write_subs(src, dst, plan, shifts):
    st = dict(SUB_STYLE_V5)
    st.update(plan.get("sub_style", {}))
    over = {int(k): v for k, v in plan.get("sub_text", {}).items()}
    fmt, out, ev, k = None, [], [], 0
    for ln in open(src, encoding="utf-8").read().splitlines():
        if ln.startswith("Format:") and fmt is None and "Fontname" in ln:
            fmt = [x.strip() for x in ln[7:].split(",")]
        if ln.startswith("Style:") and fmt:
            f = [x.strip() for x in ln[6:].split(",")]
            for key, v in st.items():
                f[fmt.index(key)] = str(v)
            ln = "Style: " + ",".join(f)
        if ln.startswith("Dialogue:"):
            parts = ln.split(",", 9)
            a, b = ass_sec(parts[1]), ass_sec(parts[2])
            add = sum(x["add"] for x in shifts if a >= x["at"] - 1e-6)
            add_b = sum(x["add"] for x in shifts if b > x["at"] + 1e-6)
            if add != add_b:
                die(f"vo_shift at {shifts} splits sub event {k}")
            parts[1], parts[2] = ass_time(a + add), ass_time(b + add)
            if k in over:
                parts[9] = over[k]
            ev.append((a + add, b + add, parts[9]))
            ln = ",".join(parts); k += 1
        out.append(ln)
    open(dst, "w", encoding="utf-8").write("\n".join(out) + "\n")
    return ev


def decode_audio(path, ss=None, t=None):
    cmd = ["ffmpeg", "-v", "error"]
    if ss is not None:
        cmd += ["-ss", f"{ss:.4f}"]
    if t is not None:
        cmd += ["-t", f"{t:.4f}"]
    cmd += ["-i", path, "-vn", "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"]
    a = np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, np.float32)
    return a.reshape(-1, 2).copy()


def write_wav(path, a):
    a = np.clip(a, -1, 1)
    p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "f32le", "-ar", str(SR), "-ac", "2",
                          "-i", "-", "-c:a", "pcm_f32le", path], stdin=subprocess.PIPE)
    p.communicate(a.astype(np.float32).tobytes())
    if p.returncode:
        die(f"wav write failed {path}")


def shift_vo(vo, shifts):
    out, pos = [], 0
    for x in sorted(shifts, key=lambda x: x["at"]):
        i = int(round(x["at"] * SR))
        w = vo[max(0, i - int(0.06 * SR)): i + int(0.06 * SR)]
        rms = float(np.sqrt((w ** 2).mean())) if len(w) else 0
        if rms > 0.01:
            die(f"vo_shift at {x['at']} is not in a VO pause (rms {rms:.4f}); pick a phrase gap")
        out += [vo[pos:i], np.zeros((int(round(x["add"] * SR)), 2), np.float32)]
        pos = i
    out.append(vo[pos:])
    return np.concatenate(out)


# ---------------------------------------------------------------- video
def affine_zoom(img, z, cx, cy):
    """Scale `img` by z about (cx, cy) with sub-pixel bicubic sampling (no integer rounding)."""
    a = 1.0 / z
    return img.transform(img.size, Image.AFFINE, (a, 0, cx - cx * a, 0, a, cy - cy * a),
                         resample=Image.BICUBIC)


def seg_frames(s, paths, n, fps):
    src = paths.get(s["src"]) or s["src"]
    if s["mode"] == "hero":
        cw = int(round(1080 * 9 / 16 / 2)) * 2  # 608 for 1080p
        hx = s.get("hero_x", 0)
        vf = (f"fps={fps},scale=-2:1080:flags=lanczos,crop={cw}:1080:(iw-{cw})/2+{hx}:0,"
              f"scale={W}:{H}:flags=lanczos")
        w, h = W, H
    else:
        if src == paths["master"]:
            vf = f"fps={fps},crop={WW}:{WH}:0:320"
        else:
            vf = f"fps={fps},scale={WW}:{WH}:flags=lanczos"
        w, h = WW, WH
    g = s.get("grade", GRADE)  # [gamma, saturation, contrast] — lifts dark trailer footage
    if g and list(g) != [1.0, 1.0, 1.0]:
        # format=rgb24 BEFORE eq: eq straight after crop on yuv420p emits a short/misaligned
        # rawvideo (65448000 B for 75 frames of 720x405 rgb, not 65610000) -> reshape crash.
        vf += f",format=rgb24,eq=gamma={g[0]}:saturation={g[1]}:contrast={g[2]}"
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{s['in']:.4f}", "-i", src, "-t", f"{n / fps + 0.5:.4f}",
           "-vf", vf + ",format=rgb24", "-frames:v", str(n), "-f", "rawvideo", "-"]
    raw = subprocess.run(cmd, capture_output=True, check=True).stdout
    fr = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)
    if len(fr) < n:
        fr = np.concatenate([fr, np.repeat(fr[-1:], n - len(fr), 0)])
    return fr


def selftest_zoom():
    img = Image.new("RGB", (WW, WH), (0, 0, 0))
    a = np.zeros((WH, WW, 3), np.uint8)
    yy, xx = np.mgrid[0:WH, 0:WW]
    a[((xx - 560) ** 2 + (yy - 100) ** 2) < 12 ** 2] = 255   # off-centre target
    img = Image.fromarray(a)
    n = 60
    xs = []
    for i in range(n):
        z = 1.0 + 0.10 * i / (n - 1)
        f = np.asarray(affine_zoom(img, z, WW / 2, WH / 2).convert("L")).astype(float)
        m = f.sum()
        xs.append(((f * xx).sum() / m, (f * yy).sum() / m))
    xs = np.array(xs)
    ideal = np.array([[WW / 2 + (560 - WW / 2) * (1 + 0.1 * i / (n - 1)),
                       WH / 2 + (100 - WH / 2) * (1 + 0.1 * i / (n - 1))] for i in range(n)])
    err = np.abs(xs - ideal).max()
    d2 = np.abs(np.diff(xs, 2, axis=0)).max()
    mono = bool((np.diff(xs[:, 0]) > 0).all() and (np.diff(xs[:, 1]) < 0).all())
    ok = err < 0.6 and d2 < 0.05 and mono
    print(f"zoom selftest: max |pos-ideal|={err:.3f}px  max 2nd-diff={d2:.4f}px/frame^2  "
          f"monotonic={mono}  -> {'PASS' if ok else 'FAIL'}")
    return ok


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("plan", nargs="?")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--selftest-zoom", action="store_true")
    a = ap.parse_args()
    if a.selftest_zoom:
        sys.exit(0 if selftest_zoom() else 1)
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "shopee-clip", "scripts"))
    import heavylock
    heavylock.acquire("build_v5")
    if not a.plan:
        ap.error("plan.json required")
    plan = json.load(open(a.plan))
    base = os.path.dirname(os.path.abspath(a.plan))
    P = lambda k, d=None: (lambda v: v if v is None or os.path.isabs(v) else os.path.join(base, v))(plan.get(k, d))
    global GRADE
    GRADE = plan.get("grade", GRADE)
    fps = plan.get("fps", 30)
    DUR = float(plan["dur"])
    NT = int(round(DUR * fps))
    paths = {"master": P("master", "master.mp4"), "trailer": P("trailer", "trailer.mp4")}
    total = probe_dur(paths["master"])
    gaps = vtt_gaps(P("vtt", "subs.en.vtt"), total, plan.get("speech_margin", 0.1))
    bcfg = plan.get("beats", {})
    beats = load_beats(plan, base, paths["master"])
    cuts = load_cuts(plan, base, paths["master"])
    segs = plan["segs"]

    # ---- resolve segs (snap) and timeline
    rows, nfr, errs = [], [], []
    for i, s in enumerate(segs):
        s = dict(s); s.setdefault("mode", "window"); s.setdefault("src", "master")
        last = i == len(segs) - 1
        if last:
            s["dur"] = (NT - sum(nfr)) / fps
        snapped = False
        if s.get("snap", True):
            s["in"], d2, snapped = snap_seg(s, beats, cuts, gaps, bcfg.get("window", 0.25),
                                            bcfg.get("cut_guard", 0.15), fps, last)
            if not last:
                s["dur"] = d2
        n = NT - sum(nfr) if last else int(round(s["dur"] * fps))
        if n < fps * 0.8:
            die(f"seg {i} too short ({n} frames) — total of earlier segs exceeds dur?")
        s["n"] = n
        ain = s.get("audio_in", s["in"])
        g = in_gap(gaps, ain, ain + n / fps)
        if not g:
            errs.append(f"seg {i} audio {ain:.2f}-{ain + n / fps:.2f} not inside a no-speech gap")
            g = (float("nan"), float("nan"))
        s["t0"] = sum(nfr) / fps
        nfr.append(n)
        bo = float(np.abs(beats - s["in"]).min())
        rows.append(s)
        print(f"seg{i} {s['mode']:6s} {os.path.basename(paths.get(s['src'], s['src'])):11s} in={s['in']:.3f} "
              f"dur={n / fps:.3f} -> t {s['t0']:.3f}-{s['t0'] + n / fps:.3f}  gap={g[0]:.2f}-{g[1]:.2f} "
              f"beat_off={bo * 1000:.0f}ms {'SNAP' if snapped else 'plan'}")
    if errs:
        die("; ".join(errs) + f"  gaps={[(round(x, 2), round(y, 2)) for x, y in gaps]}")
    segs = rows
    seams = [s["t0"] for s in segs[1:]]

    # ---- pills
    pills = []
    if plan.get("release_pill"):
        rp = plan["release_pill"]
        pills.append({"text": release_text(plan), "start": rp["start"], "end": rp["end"],
                      "color": rp.get("color", "0xFF8FB1")})
    for c in plan.get("caps", []):
        if re.search(r"link|below|cart|basket|bio", c["text"], re.I):
            die(f"CTA-like pill '{c['text']}' outside the last seg — use plan.cta")
        pills.append(dict(c))
    if plan.get("cta"):
        c = plan["cta"]; ls = segs[-1]
        pills.append({"text": c["text"], "start": round(ls["t0"] + c.get("lead", 0.15), 3),
                      "end": round(DUR - plan.get("loop_tail", 0.3), 3), "color": c.get("color", "0xFFD166")})
    pills.sort(key=lambda p: p["start"])
    for p in pills:
        check_pill(p["text"])
    for p, q in zip(pills, pills[1:]):
        if q["start"] < p["end"] - 1e-6:
            die(f"pills overlap: {p} / {q}")
    for p in pills:
        print(f"pill {p['start']:5.2f}-{p['end']:5.2f}  {p['text']}")

    # ---- VO + subs
    shifts = plan.get("vo_shift", [])
    subs_out = os.path.join(base, "subs_v5.ass")
    ev = write_subs(P("subs", "subs.ass"), subs_out, plan, shifts)
    vo = decode_audio(P("vo", "vo.mp3"))
    vo = shift_vo(vo, shifts)
    vo_end = len(vo) / SR
    for s0, e0, txt in ev:
        print(f"sub {s0:5.2f}-{e0:5.2f}  {txt}")
    print(f"VO end {vo_end:.2f} (dur-1.5 = {DUR - 1.5:.2f}) {'OK' if ev[-1][1] <= DUR - 1.5 else 'LATE'}")
    print(f"seams {[round(x, 3) for x in seams]}")
    if a.check:
        return

    work = os.path.join(base, "work"); os.makedirs(work, exist_ok=True)
    vo_wav = os.path.join(work, "vo_v5.wav"); write_wav(vo_wav, vo)

    # ---- music bed (exact length) + sfx
    mus = []
    fade = int(0.008 * SR)
    for s in segs:
        ns = int(round(s["n"] / fps * SR))
        asrc = s.get("audio_src", "master")
        apath = paths.get(asrc) or (asrc if os.path.isabs(asrc) else os.path.join(base, asrc))
        x = decode_audio(apath, s.get("audio_in", s["in"]), s["n"] / fps + 0.1)[:ns]
        if len(x) < ns:
            x = np.concatenate([x, np.zeros((ns - len(x), 2), np.float32)])
        r = np.linspace(0, 1, fade)[:, None]
        x[:fade] *= r; x[-fade:] *= r[::-1]
        mus.append(x)
    mus = np.concatenate(mus)
    NS = int(round(NT / fps * SR))
    mus = np.concatenate([mus, np.zeros((max(0, NS - len(mus)), 2), np.float32)])[:NS]
    sfxcfg = plan.get("sfx", {})
    sdir = sfxcfg.get("dir", os.path.join(SKILL, "assets", "sfx")).replace("<skill>", SKILL)
    if not os.path.exists(os.path.join(sdir, "whoosh.wav")):
        run(["bash", os.path.join(SKILL, "scripts", "make_sfx.sh"), sdir], stdout=subprocess.DEVNULL)
    wh = decode_audio(os.path.join(sdir, "whoosh.wav")) * sfxcfg.get("whoosh", 0.30)
    im = decode_audio(os.path.join(sdir, "impact.wav")) * sfxcfg.get("impact", 0.45)
    sfx = np.zeros_like(mus)
    def put(clip, t):
        i = int(round(t * SR))
        if i < 0:
            clip, i = clip[-i:], 0
        j = min(len(sfx), i + len(clip))
        sfx[i:j] += clip[:j - i]
    for k, s in enumerate(segs):
        kind = s.get("sfx", "impact" if k == 0 else ("both" if s["mode"] == "hero" else "whoosh"))
        if kind in ("whoosh", "both") and k > 0:
            put(wh, s["t0"] - 0.30)
        if kind in ("impact", "both"):
            put(im, s["t0"])
    mus_wav = os.path.join(work, "music_v5.wav"); write_wav(mus_wav, mus)
    sfx_wav = os.path.join(work, "sfx_v5.wav"); write_wav(sfx_wav, sfx)

    # ---- video frames
    bg = np.asarray(Image.open(P("bg", "bg.png")).convert("RGB").resize((W, H)), np.uint8)
    wy = plan.get("window_y", 280)
    flash = plan.get("flash", [0.5, 0.3, 0.12])
    lg = plan.get("logo")
    logo = None
    if lg:
        li = Image.open(os.path.join(base, lg["png"])).convert("RGBA")
        lw = lg.get("w", 300)
        li = li.resize((lw, int(round(li.height * lw / li.width))), Image.LANCZOS)
        logo = (li, ((W - lw) // 2, lg.get("y", 36)), lg["start"], lg["end"])
    zw = plan.get("zoom", [1.0, 1.10]); zh = plan.get("hero_zoom", [1.0, 1.0])
    tail = int(round(plan.get("loop_tail", 0.3) * fps))

    fontfile = os.path.join(base, plan.get("pill_font", "Fredoka-SemiBold.ttf"))
    py = plan.get("pill_y", 210)
    dts = []
    for p in pills:
        col = p.get("color", "0xFF8FB1")
        if "@" not in col:
            col += "@0.92"
        dts.append(f"drawtext=fontfile={fontfile}:text='{esc_dt(p['text'])}':fontcolor=white:fontsize=40:"
                   f"borderw=3:bordercolor=0x5A2A4A:box=1:boxcolor={col}:boxborderw=14:"
                   f"x=(w-text_w)/2:y={py}:enable='between(t,{p['start']:.3f},{p['end']:.3f})'")
    # libass loads EVERY file in fontsdir as a font candidate. A fontsdir that also holds the
    # trailer/master (e.g. "." = the work dir) pulled ~2.7 GB into ffmpeg and the NAS cgroup
    # OOM-killed the encode (BrokenPipe on frame 0). Always hand libass a fonts-only copy.
    src_fd = P("fonts_dir", "fonts")
    fontsdir = os.path.join(work, "fonts_only")
    os.makedirs(fontsdir, exist_ok=True)
    nf = 0
    for fn in os.listdir(src_fd):
        if fn.lower().endswith((".ttf", ".otf", ".ttc")):
            dst = os.path.join(fontsdir, fn)
            if not os.path.exists(dst):
                import shutil; shutil.copy2(os.path.join(src_fd, fn), dst)
            nf += 1
    if not nf:
        die(f"no .ttf/.otf in fonts_dir {src_fd}")
    vchain = ",".join(dts + [f"ass={subs_out}:fontsdir={fontsdir}:shaping=complex", "format=yuv420p"])
    mg, vg = plan.get("music_gain", 0.75), plan.get("vo_gain", 1.25)
    afc = (f"[1:a]aresample={SR}[m];[3:a]aresample={SR}[sx];[m][sx]amix=inputs=2:duration=first:normalize=0,"
           f"volume={mg}[pre];"
           f"[2:a]aresample={SR},volume={vg},apad=whole_dur={DUR},asplit=2[voa][vok];"
           f"[vok]pan=mono|c0=0.5*c0+0.5*c1[key];"
           f"[pre][key]sidechaincompress=threshold=0.04:ratio=4:attack=15:release=500[gduck];"
           f"[gduck][voa]amix=inputs=2:duration=longest:normalize=0,apad=whole_dur={DUR}[aout]")
    out = P("out", "out.mp4")
    log = open(os.path.join(work, "ffmpeg_v5.log"), "w")
    enc = subprocess.Popen(
        ["ffmpeg", "-y", "-v", "warning", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-framerate", str(fps), "-i", "-", "-i", mus_wav, "-i", vo_wav, "-i", sfx_wav,
         "-filter_complex", f"[0:v]{vchain}[v];{afc}", "-map", "[v]", "-map", "[aout]",
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-profile:v", "high", "-level:v", "4.0",
         "-pix_fmt", "yuv420p", "-r", str(fps), "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-ac", "2",
         "-t", f"{NT / fps:.4f}", "-movflags", "+faststart", out],
        stdin=subprocess.PIPE, stderr=log)
    first = None
    fidx = 0
    tail_buf = []
    for k, s in enumerate(segs):
        fr = seg_frames(s, paths, s["n"], fps)
        z = s.get("zoom", zh if s["mode"] == "hero" else zw)
        for j in range(s["n"]):
            if s["mode"] == "hero":
                f = Image.fromarray(fr[j])
                if z[0] != 1.0 or z[1] != 1.0:
                    f = affine_zoom(f, z[0] + (z[1] - z[0]) * j / max(1, s["n"] - 1), W / 2, H / 2)
                frame = np.asarray(f, np.uint8).copy()
            else:
                f = affine_zoom(Image.fromarray(fr[j]), z[0] + (z[1] - z[0]) * j / max(1, s["n"] - 1),
                                WW / 2, WH / 2)
                frame = bg.copy(); frame[wy:wy + WH] = np.asarray(f, np.uint8)
            tt = fidx / fps
            if logo and logo[2] <= tt < logo[3]:
                pi = Image.fromarray(frame).convert("RGBA")
                pi.alpha_composite(logo[0], logo[1]); frame = np.asarray(pi.convert("RGB")).copy()
            if k > 0 and j < len(flash):
                frame = (frame * (1 - flash[j]) + 255 * flash[j]).astype(np.uint8)
            if fidx == 0:
                first = frame.copy()
            if fidx >= NT - tail and tail > 0:
                al = (fidx - (NT - tail) + 1) / (tail + 1)
                frame = (frame * (1 - al) + first * al).astype(np.uint8)
            enc.stdin.write(frame.tobytes())
            fidx += 1
            if fidx % 60 == 0:
                print(f"frame {fidx}/{NT}", flush=True)
    enc.stdin.close(); enc.wait(); log.close()
    if enc.returncode:
        die("final encode failed — see work/ffmpeg_v5.log")
    json.dump({"segs": segs, "seams": seams, "pills": pills, "subs": ev, "vo_end": vo_end,
               "dur": NT / fps, "frames": fidx}, open(os.path.join(work, "timeline_v5.json"), "w"), indent=1,
              default=float)
    print(f"wrote {out}: {fidx} frames ({NT / fps:.3f}s); timeline -> work/timeline_v5.json")


if __name__ == "__main__":
    main()
