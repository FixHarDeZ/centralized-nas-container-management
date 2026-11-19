#!/usr/bin/env python3
"""windows.py — every usable footage window of one trailer, measured, in one run.

Run (in the container, from the clip workdir):
  uv run --with faster-whisper --with rapidocr-onnxruntime --with numpy --with pillow \
      python <skill>/scripts/windows.py tr_x.mp4 [--vtt subs_x.en.vtt] [--rebase S] [--min 1.2]
  -> tr_x_windows.json + tr_x_windows.jpg (one labelled sheet, already vision-sized) + a table on stdout

Why (lego-hp-switch2-gameplay 2026-11-17, 535 min): Hermes found the windows by hand — ASR, VTT, OCR,
luma, VAD and vision maps read and re-read in its head for 6.5 hours, 100-200k chars of reasoning a
turn. This script does that join once. A window here is a run of the source that is
  * speech-free: silero VAD (no transcription, so music cannot hallucinate words the way whisper's
    "do do do" did) united with the auto-caption cues when --vtt is given, each padded PAD s;
  * not dark: per-frame luma (4 fps, whole frame) >= DARK; a black dip at a cut never starts a seg;
  * text-free: RapidOCR at 1 s over the candidates only, every text run's edges re-scanned at 0.25 s.
    A string seen on >= half the scanned frames is a persistent overlay (watermark, HUD, rating bug):
    reported, never dirty. One-character hits are listed as `suspect`, never dirty.
Each window also carries its motion (mean frame difference; `static` = a card or a still), the hard
cuts inside it and the best 3 tile times. The sheet shows those tiles labelled `W<n> <t>`, for ONE
vision call: gameplay / cutscene / card / logo per window. Pick segs from the table; don't re-measure.

--rebase S: the master was encoded from `-ss S`; table and JSON also give master times (t - S).
Exit 0 always when it ran; the last line says USABLE (>= 15 s) or STOP (ask Fix, SKILL.md rule).
"""
import argparse
import json
import os
import re
import subprocess
import sys

PAD = 0.15          # speech padding each side (auto-captions lag VAD by up to ~1 s; both are kept)
DARK = 25.0         # mean luma below this = black dip / fade (footage-sourcing §5c)
FPS = 4             # frame-stat rate
OCR_STEP = 1.0
REFINE = (0.25, 0.5, 0.75)
MIN_SCORE = 0.6     # RapidOCR confidence for a hit
STATIC = 1.5        # mean abs frame diff (0-255, 160x90 gray) under this = static card / still
CUT_MIN = 20.0      # a frame diff above max(CUT_MIN, 6 x median) = hard cut
USABLE_S = 15.0


# ---------------------------------------------------------------- span arithmetic (pure)
def merge(spans, join=0.0):
    out = []
    for a, b in sorted((float(a), float(b)) for a, b in spans if b > a):
        if out and a <= out[-1][1] + join:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(round(a, 3), round(b, 3)) for a, b in out]


def subtract(base, bad):
    """base minus bad, both span lists."""
    bad = merge(bad)
    out = []
    for a, b in merge(base):
        cur = a
        for x, y in bad:
            if y <= cur or x >= b:
                continue
            if x > cur:
                out.append((cur, x))
            cur = max(cur, y)
        if cur < b:
            out.append((cur, b))
    return [(round(a, 3), round(b, 3)) for a, b in out if b - a > 1e-6]


def pad(spans, p, lo, hi):
    return merge([(max(lo, a - p), min(hi, b + p)) for a, b in spans])


# ---------------------------------------------------------------- OCR map rules (pure)
def norm(text):
    return re.sub(r"[^0-9A-Z]", "", text.upper())


def overlays(ocr_map):
    """Strings on >= half the scanned frames (and >= 4 of them): watermark / HUD / rating bug."""
    n = len(ocr_map)
    seen = {}
    for items in ocr_map.values():
        for k in {norm(i["text"]) for i in items if norm(i["text"])}:
            seen[k] = seen.get(k, 0) + 1
    failed = norm(GRAB_FAILED)          # a run of failed grabs is never a "persistent overlay"
    return sorted(k for k, c in seen.items() if n >= 4 and c >= max(4, n / 2) and k != failed)


def classify(items, skip):
    """-> ('text', [strings]) | ('suspect', [strings]) | ('clean', [])"""
    real, sus = [], []
    for i in items:
        k = norm(i["text"])
        if not k or k in skip or float(i.get("score", 1)) < MIN_SCORE:
            continue
        (real if len(k) >= 2 else sus).append(i["text"])
    return ("text", real) if real else ("suspect", sus) if sus else ("clean", [])


def dirty_spans(ocr_map, skip):
    """Text ranges from sampled OCR: each run of hits spans from the clean sample before it to the
    clean sample after it (conservative: the text may start right after the last clean look)."""
    ts = sorted(ocr_map, key=float)
    hit = [classify(ocr_map[t], skip)[0] == "text" for t in ts]
    out = []
    for i, t in enumerate(ts):
        if not hit[i]:
            continue
        a = float(ts[i - 1]) if i > 0 and not hit[i - 1] else float(t) - OCR_STEP
        b = float(ts[i + 1]) if i + 1 < len(ts) and not hit[i + 1] else float(t) + OCR_STEP
        out.append((a, b))
    return merge(out)


def refine_times(ocr_map, skip, lo, hi):
    """0.25 s probes at each edge of a 1 s text run (only where a probe was not taken yet)."""
    ts = sorted(ocr_map, key=float)
    hit = [classify(ocr_map[t], skip)[0] == "text" for t in ts]
    want = set()
    for i, t in enumerate(ts):
        if not hit[i]:
            continue
        t = float(t)
        if i == 0 or not hit[i - 1]:
            want.update(round(t - d, 2) for d in REFINE)
        if i + 1 == len(ts) or not hit[i + 1]:
            want.update(round(t + d, 2) for d in REFINE)
    have = {round(float(t), 2) for t in ts}
    return sorted(t for t in want if lo <= t <= hi and t not in have)


def ocr_grid(spans):
    """1 s samples covering each candidate span, both ends included."""
    out = set()
    for a, b in spans:
        t = a
        while t < b:
            out.add(round(t, 2))
            t += OCR_STEP
        out.add(round(b, 2))
    return sorted(out)


# ---------------------------------------------------------------- frame stats (pure part)
def frame_flags(times, luma, diff):
    """-> dark spans, cut times, median diff."""
    half = 0.5 / FPS
    dark = merge([(t - half, t + half) for t, y in zip(times, luma) if y < DARK])
    med = sorted(diff)[len(diff) // 2] if diff else 0.0
    thr = max(CUT_MIN, 6 * med)
    cuts = [round(t, 2) for t, d in zip(times, diff) if d > thr]
    return dark, cuts, med


def describe(a, b, times, luma, diff, cuts, ocr_map, skip):
    sel = [i for i, t in enumerate(times) if a <= t <= b]
    ys = [luma[i] for i in sel] or [0.0]
    ds = [diff[i] for i in sel[1:]] or [0.0]
    motion = sum(ds) / len(ds)
    sus = sorted({s for t, items in ocr_map.items() if a - 0.5 <= float(t) <= b + 0.5
                  for s in classify(items, skip)[1] if classify(items, skip)[0] == "suspect"})
    inner = [c for c in cuts if a + 0.1 < c < b - 0.1]
    dur = b - a
    tiles = [round(a + 0.2, 2), round((a + b) / 2, 2), round(b - 0.2, 2)] if dur >= 1.0 else [round((a + b) / 2, 2)]
    return {"start": round(a, 2), "end": round(b, 2), "dur": round(dur, 2),
            "luma_min": round(min(ys), 1), "motion": round(motion, 2), "static": motion < STATIC,
            "cuts": inner, "suspect": sus, "tiles": tiles,
            "score": round(dur * (0.3 if motion < STATIC else 1.0), 2)}


# ---------------------------------------------------------------- media IO
def probe_dur(src):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", src],
                         capture_output=True, text=True, check=True).stdout
    return float(out.strip())


def vad_spans(src):
    import numpy as np
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.float32)
    if len(a) < 1600:
        return []
    ts = get_speech_timestamps(a, VadOptions(threshold=0.5, min_silence_duration_ms=300, speech_pad_ms=100))
    return [(x["start"] / 16000, x["end"] / 16000) for x in ts]


def vtt_spans(path):
    tm = r"(\d+):(\d\d):(\d\d)[.,](\d{3})"

    def sec(m, o):
        return int(m.group(o + 1)) * 3600 + int(m.group(o + 2)) * 60 + int(m.group(o + 3)) + int(m.group(o + 4)) / 1000

    out = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = re.search(tm + r"\s*-->\s*" + tm, line)
            if m:
                out.append((sec(m, 0), sec(m, 4)))
    return out


def frame_stats(src):
    import numpy as np
    w, h = 160, 90
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-an", "-vf", f"fps={FPS},scale={w}:{h},format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    n = len(raw) // (w * h)
    fr = np.frombuffer(raw[: n * w * h], np.uint8).reshape(n, h, w).astype(np.float32)
    times = [round(i / FPS, 3) for i in range(n)]
    luma = [float(f.mean()) for f in fr]
    diff = [0.0] + [float(np.abs(fr[i] - fr[i - 1]).mean()) for i in range(1, n)]
    return times, luma, diff


EOF_GAP = 0.1        # ffmpeg cannot seek a frame at t == duration: probe this much before the end
GRAB_FAILED = "<frame grab failed>"


def grab_time(t, dur):
    """The time actually grabbed: span ends sit on the duration, which has no frame."""
    return max(0.0, min(float(t), dur - EOF_GAP)) if dur else float(t)


def grab(src, t, out, dur=None):
    """One frame -> PNG (the mjpeg encoder refuses the tv-range yuv of a plain libx264 re-encode, which
    killed every grab on 2026-11-18). -> True when the file was written."""
    if os.path.exists(out):
        os.remove(out)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{grab_time(t, dur):.3f}", "-i", src, "-frames:v", "1",
                    "-update", "1", out], capture_output=True)
    return os.path.exists(out) and os.path.getsize(out) > 0


def ocr_frames(src, times, ocr, scratch, dur=None):
    """A failed grab counts as text (dirty): an unreadable frame is never called clean."""
    out = {}
    for t in times:
        f = os.path.join(scratch, f"_win_{t}.png")
        if not grab(src, t, f, dur):
            print(f"WARN: no frame at {t}s — marked dirty", file=sys.stderr)
            out[str(t)] = [{"text": GRAB_FAILED, "score": 1.0}]
            continue
        try:
            found, _ = ocr(f)
        finally:
            if os.path.exists(f):
                os.remove(f)
        out[str(t)] = [{"text": txt.strip(), "score": round(float(sc), 3)} for _, txt, sc in (found or []) if txt.strip()]
    return out


def sheet(src, wins, out, scratch, cols=6, tile_w=300, dur=None):
    from PIL import Image, ImageDraw, ImageFont
    tiles = []
    for w in wins:
        for t in w["tiles"]:
            f = os.path.join(scratch, f"_ws_{t}.png")
            if not grab(src, t, f, dur):
                continue
            im = Image.open(f).convert("RGB")
            os.remove(f)
            im.thumbnail((tile_w, tile_w))
            tiles.append((f"W{w['n']} {t:.1f}", im))
    if not tiles:
        return None
    th = max(im.size[1] for _, im in tiles)
    rows = (len(tiles) + cols - 1) // cols
    canvas = Image.new("RGB", (cols * tile_w, rows * (th + 26)), "black")
    d = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    for i, (label, im) in enumerate(tiles):
        x, y = (i % cols) * tile_w, (i // cols) * (th + 26)
        canvas.paste(im, (x, y + 26))
        d.text((x + 4, y + 3), label, fill="yellow", font=font)
    canvas.thumbnail((1600, 1600))
    canvas.save(out, "JPEG", quality=82, optimize=True)
    return out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("src")
    ap.add_argument("--vtt", help="auto-caption VTT of the same file (yt-dlp --write-auto-subs)")
    ap.add_argument("--rebase", type=float, default=0.0, help="master encoded from -ss S: also print t - S")
    ap.add_argument("--min", type=float, default=1.2, help="shortest window kept (s)")
    ap.add_argument("--max-tiles", type=int, default=36)
    ap.add_argument("--out")
    ap.add_argument("--sheet")
    a = ap.parse_args()

    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "shopee-clip", "scripts"))
    import heavylock
    heavylock.acquire("windows")

    stem = os.path.splitext(a.src)[0]
    out = a.out or stem + "_windows.json"
    sheet_out = a.sheet or stem + "_windows.jpg"
    scratch = os.path.dirname(os.path.abspath(out))
    dur = probe_dur(a.src)

    speech_raw = vad_spans(a.src) + (vtt_spans(a.vtt) if a.vtt else [])
    speech = pad(speech_raw, PAD, 0.0, dur)
    times, luma, diff = frame_stats(a.src)
    dark, cuts, med = frame_flags(times, luma, diff)
    cand = [s for s in subtract([(0.0, dur)], speech + dark) if s[1] - s[0] >= a.min]

    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    ocr_map = ocr_frames(a.src, ocr_grid(cand), ocr, scratch, dur)
    skip = set(overlays(ocr_map))
    more = refine_times(ocr_map, skip, 0.0, dur)
    ocr_map.update(ocr_frames(a.src, more, ocr, scratch, dur))
    text = dirty_spans(ocr_map, skip)

    clean = [s for s in subtract(cand, text) if s[1] - s[0] >= a.min]
    wins = [describe(x, y, times, luma, diff, cuts, ocr_map, skip) for x, y in clean]
    for i, w in enumerate(wins, 1):
        w["n"] = i
        if a.rebase:
            w["master"] = [round(w["start"] - a.rebase, 2), round(w["end"] - a.rebase, 2)]
    usable = round(sum(w["dur"] for w in wins), 2)
    moving = round(sum(w["dur"] for w in wins if not w["static"]), 2)

    picked, budget = [], a.max_tiles
    for w in sorted(wins, key=lambda w: -w["score"]):
        if len(w["tiles"]) <= budget:
            picked.append(w)
            budget -= len(w["tiles"])
    picked.sort(key=lambda w: w["start"])
    sheet_path = sheet(a.src, picked, sheet_out, scratch, dur=dur)

    res = {"src": os.path.abspath(a.src), "dur": round(dur, 2), "vtt": a.vtt, "rebase": a.rebase,
           "speech": speech, "dark": dark, "text": text, "overlays": sorted(skip), "cuts": cuts,
           "motion_median": round(med, 2), "ocr_frames": len(ocr_map), "windows": wins,
           "usable_s": usable, "moving_s": moving, "sheet": sheet_path,
           "sheet_windows": [w["n"] for w in picked]}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)

    print(f"src={a.src} dur={dur:.1f}s speech={len(speech)} spans dark={len(dark)} text={len(text)} "
          f"ocr_frames={len(ocr_map)} overlays={sorted(skip) or '-'}")
    print(" W    start    end   dur  luma  motion  cuts  flags" + ("   master" if a.rebase else ""))
    for w in wins:
        flags = ("STATIC " if w["static"] else "") + (f"suspect={w['suspect']}" if w["suspect"] else "")
        cut = ",".join(f"{c:.1f}" for c in w["cuts"]) or "-"
        m = f"   {w['master'][0]:.2f}-{w['master'][1]:.2f}" if a.rebase else ""
        print(f"W{w['n']:<3} {w['start']:7.2f} {w['end']:7.2f} {w['dur']:5.2f} {w['luma_min']:5.0f} {w['motion']:7.1f}"
              f"  {cut:<10} {flags}{m}")
    print(f"-> {out}" + (f" + sheet {sheet_path} (W{', W'.join(str(n) for n in res['sheet_windows'])})" if sheet_path else ""))
    verdict = "USABLE" if moving >= USABLE_S else "STOP"
    print(f"{verdict}: {usable:.1f} s clean in {len(wins)} windows, {moving:.1f} s moving"
          + ("" if verdict == "USABLE" else f" < {USABLE_S:.0f} s -> try the next official source or ask Fix"))


if __name__ == "__main__":
    main()
