#!/usr/bin/env python3
"""windows.py — every usable footage window of one trailer, measured, in one run.

Run (in the container, from the clip workdir):
  uv run --with faster-whisper --with rapidocr-onnxruntime --with numpy --with pillow \
      python <skill>/scripts/windows.py tr_x.mp4 [--vtt subs_x.en.vtt] [--rebase S] [--min 1.2]
  -> tr_x_windows.json + tr_x_windows.jpg (one labelled sheet, already vision-sized) + a table on stdout

Why (lego-hp-switch2-gameplay 2026-11-17, 535 min): Hermes found the windows by hand — ASR, VTT, OCR,
luma, VAD and vision maps read and re-read in its head for 6.5 hours, 100-200k chars of reasoning a
turn. This script does that join once. A window here is a run of the source that is
  * speech-free: silero VAD united with the auto-caption cues when --vtt is given, each padded PAD s.
    No --vtt (yt-dlp auto-subs 429 / none): faster-whisper runs on the source too, and a whisper WORD
    that overlaps or sits within ASR_NEAR s of a VAD span EXTENDS it (switch2-oblivion-rd 2026-11-22: VAD
    ended quiet speech under music ~1 s early). A whisper word far from any VAD span is dropped (music
    hallucinates words, "do do do" on lego-hp). The joined speech is written as <stem>_speech.vtt (master
    time with --rebase) = the build_v5 "vtt" key, so build and table agree. --no-asr skips it;
  * not dark: per-frame luma (4 fps, whole frame) >= DARK; a black dip at a cut never starts a seg;
  * not washed out: every frame at the source rate (64x36 gray) — mean > WASH_MEAN with almost no detail
    = a white flash cut (switch2-oblivion-rd 2026-11-22: 2-5 frame flashes at most of the trailer's cuts,
    one blinked in the hook; 4 fps misses them), padded WASH_PAD;
  * text-free: RapidOCR at 1 s over the candidates only, every text run's edges re-scanned at 0.25 s.
    A string seen on >= half the scanned frames is a persistent overlay (watermark, HUD, rating bug):
    reported, never dirty. One-character hits are listed as `suspect`, never dirty — unless the glyph is BIG
    (box >= BIG_GLYPH of the frame height, confident, not a thin I/L/1): typography, dirty;
  * not a date reveal: the DATE_LEAD s before any date / year hit are dirty. fate-extra-record-ps5 2026-11-27
    shipped giant "2" / "02" / "JA" fragments (the release-date animation before "JAN 28, 2027"): OCR read only a
    few of those frames, as single characters (`suspect`), and both windows there were offered as clean.
Each window also carries its motion (mean frame difference; `static` = a card or a still), the hard
cuts inside it and the best 3 tile times. The sheet shows those tiles labelled `W<n> <t>`, for ONE
vision call: gameplay / cutscene / card / logo per window. Pick segs from the table; don't re-measure.

--song: the soundtrack is a SONG with no narration (lyrics under music, footage-sourcing §0): no VAD, no whisper,
no caption spans — speech is empty and <stem>_speech.vtt is header-only (the build_v5 "vtt"). gta6-codebox-gp2
2026-11-25: the "Now Playing" clips' lyrics counted as speech left 1.5 s of 19 s; Hermes worked the rule out in
a 20-min reasoning turn. With --vtt the script prints a SONG? hint when the captions have [Music] / ♪ cues and
no ">>" speaker mark.
--ocr-step S: OCR sample step (default 1.0). Game footage with button prompts that flash for under a second
(gta6: an L2 prompt at 12.5 s, between the 1 s samples) wants 0.5.
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
WASH_MEAN, WASH_STD = 225.0, 12.0   # 64x36 gray (same numbers as build_v5's seg check)
WASH_PAD = 0.1      # the ramp frames either side of a flash (205-215 luma) are half white too
ASR_NEAR = 1.5      # s: a whisper word this close to a VAD span is the same speech, VAD cut its tail
OCR_STEP = 1.0
REFINE = (0.25, 0.5, 0.75)
MIN_SCORE = 0.6     # RapidOCR confidence for a hit
BIG_GLYPH = 0.12    # x frame height: a one-character hit this tall is typography (fate: '8' 0.32, '21' 0.14)
BIG_SCORE = 0.8     # ... and this confident
THIN = {"I", "L", "1"}   # poles, edges and rails read as these: never "big typography" on their own
DATE_LEAD = 10.0    # s before a date hit: the reveal animation (fate: 175.6-184.6 before "JAN 28, 2027" at 185)
DATE_RE = re.compile(r"\b(19|20)\d\d\b|\b\d{1,2}[./-]\d{1,2}[./-](19|20)?\d\d\b|\b(JAN(UARY)?|FEB(RUARY)?|MAR(CH)?|"
                     r"APR(IL)?|MAY|JUNE?|JULY?|AUG(UST)?|SEPT?(EMBER)?|OCT(OBER)?|NOV(EMBER)?|DEC(EMBER)?)\.?\s*\d{1,2}\b",
                     re.I)
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
        big = float(i.get("h", 0)) >= BIG_GLYPH and float(i.get("score", 1)) >= BIG_SCORE and k not in THIN
        (real if len(k) >= 2 or big else sus).append(i["text"])
    return ("text", real) if real else ("suspect", sus) if sus else ("clean", [])


def date_leads(ocr_map, skip, lead=DATE_LEAD):
    """[(t - lead, t)] before every sampled frame that shows a date / year (overlays excluded)."""
    out = []
    for t, items in ocr_map.items():
        if any(DATE_RE.search(i["text"]) for i in items
               if norm(i["text"]) not in skip and float(i.get("score", 1)) >= MIN_SCORE):
            out.append((float(t) - lead, float(t)))
    return merge(out)


def box_h(box, frame_h):
    """{'h': box height / frame height} for an OCR box (4 points), {} when either is unknown."""
    try:
        ys = [float(p[1]) for p in box]
        return {"h": round((max(ys) - min(ys)) / frame_h, 3)} if frame_h else {}
    except (TypeError, ValueError, IndexError):
        return {}


def frame_height(png):
    try:
        from PIL import Image
        with Image.open(png) as im:
            return im.size[1]
    except Exception:
        return None


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


def ocr_grid(spans, step=None):
    """Samples every `step` s (default OCR_STEP) covering each candidate span, both ends included."""
    step = step or OCR_STEP
    out = set()
    for a, b in spans:
        t = a
        while t < b - 1e-9:
            out.add(round(t, 2))
            t += step
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


def wash_spans(means, stds, rate, pad_s=WASH_PAD):
    """Washed-out (white flash) frames at the source rate -> padded spans."""
    half = 0.5 / rate
    return merge([(max(0.0, i / rate - half - pad_s), i / rate + half + pad_s)
                  for i, (m, sd) in enumerate(zip(means, stds)) if m > WASH_MEAN and sd < WASH_STD])


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


def asr_extend(vad, asr, near=ASR_NEAR):
    """VAD spans extended by the whisper word spans that touch or sit within `near` s of them; a word with no VAD
    span near it is music hallucination and is dropped. Chained words reach further only through the VAD
    span they touch, never word to word."""
    vad = merge(vad)
    keep = [(a, b) for a, b in asr if any(a <= y + near and b >= x - near for x, y in vad)]
    return merge(list(vad) + keep)


def asr_segments(src):
    """faster-whisper (small, int8, English, word timestamps) over the whole source -> [(start, end)] per word."""
    import numpy as np
    from faster_whisper import WhisperModel
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    a = np.frombuffer(raw, np.float32)
    if len(a) < 1600:
        return []
    segs, _ = WhisperModel("small", device="cpu", compute_type="int8").transcribe(
        a, language="en", vad_filter=False, beam_size=1, word_timestamps=True)
    # WORD spans: a segment can run 15 s across music (oblivion 85-102 s) and would swallow every window
    return [(round(wd.start, 2), round(wd.end, 2)) for x in segs for wd in (x.words or []) if wd.end > wd.start]


def write_vtt(spans, path, rebase=0.0):
    def ft(t):
        t = max(0.0, t)
        return f"{int(t // 3600):02d}:{int(t % 3600 // 60):02d}:{t % 60:06.3f}"
    lines = ["WEBVTT", ""]
    for a, b in spans:
        if b - rebase > 0:
            lines += [f"{ft(a - rebase)} --> {ft(b - rebase)}", "speech", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


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


def vtt_is_song(path):
    """Auto-captions of a song: [Music] / ♪ cues and no ">>" speaker change mark anywhere."""
    with open(path, encoding="utf-8", errors="replace") as f:
        txt = f.read()
    return ">>" not in txt and bool(re.search(r"\[\s*music\s*\]|♪", txt, re.I))


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


def wash_stats(src):
    """Per-frame mean / std at the source rate (64x36 gray) + that rate."""
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", src, "-an", "-vf", "scale=64:36,format=gray",
                          "-f", "rawvideo", "-"], capture_output=True, check=True).stdout
    n = len(raw) // (64 * 36)
    if not n:
        return [], [], 30.0
    fr = np.frombuffer(raw[: n * 64 * 36], np.uint8).reshape(n, 36, 64).astype(np.float32)
    rate = n / probe_dur(src)
    return [float(x) for x in fr.mean(axis=(1, 2))], [float(x) for x in fr.std(axis=(1, 2))], rate


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
            fh = frame_height(f)
        finally:
            if os.path.exists(f):
                os.remove(f)
        out[str(t)] = [{"text": txt.strip(), "score": round(float(sc), 3), **box_h(box, fh)}
                       for box, txt, sc in (found or []) if txt.strip()]
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
    ap.add_argument("--no-asr", action="store_true", help="no --vtt: skip the whisper pass (VAD only)")
    ap.add_argument("--song", action="store_true", help="soundtrack is a song, no narration: no speech spans")
    ap.add_argument("--ocr-step", type=float, default=OCR_STEP, help="OCR sample step, s (0.5 for button prompts)")
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

    asr_n, vtt_out = None, None
    vad = [] if a.song else vad_spans(a.src)
    if a.song:
        speech_raw = []
    elif a.vtt:
        speech_raw = vad + vtt_spans(a.vtt)
    elif a.no_asr:
        speech_raw = vad
    else:
        asr = asr_segments(a.src)
        speech_raw = asr_extend(vad, asr)
        asr_n = len(asr)
    speech = pad(speech_raw, PAD, 0.0, dur) if speech_raw else []
    if a.song or not a.vtt:
        vtt_out = write_vtt(speech, stem + "_speech.vtt", a.rebase)
    times, luma, diff = frame_stats(a.src)
    dark, cuts, med = frame_flags(times, luma, diff)
    wash = wash_spans(*wash_stats(a.src))
    cand = [s for s in subtract([(0.0, dur)], speech + dark + wash) if s[1] - s[0] >= a.min]

    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()
    ocr_map = ocr_frames(a.src, ocr_grid(cand, a.ocr_step), ocr, scratch, dur)
    skip = set(overlays(ocr_map))
    more = refine_times(ocr_map, skip, 0.0, dur)
    ocr_map.update(ocr_frames(a.src, more, ocr, scratch, dur))
    text = merge(dirty_spans(ocr_map, skip) + date_leads(ocr_map, skip))

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
           "speech": speech, "speech_vtt": vtt_out, "asr_segments": asr_n, "dark": dark, "wash": wash, "text": text, "overlays": sorted(skip), "cuts": cuts,
           "motion_median": round(med, 2), "ocr_frames": len(ocr_map), "windows": wins,
           "usable_s": usable, "moving_s": moving, "sheet": sheet_path,
           "sheet_windows": [w["n"] for w in picked]}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)

    print(f"src={a.src} dur={dur:.1f}s speech={len(speech)} spans dark={len(dark)} wash={len(wash)} text={len(text)} "
          f"ocr_frames={len(ocr_map)} overlays={sorted(skip) or '-'}")
    print(" W    start    end   dur  luma  motion  cuts  flags" + ("   master" if a.rebase else ""))
    for w in wins:
        flags = ("STATIC " if w["static"] else "") + (f"suspect={w['suspect']}" if w["suspect"] else "")
        cut = ",".join(f"{c:.1f}" for c in w["cuts"]) or "-"
        m = f"   {w['master'][0]:.2f}-{w['master'][1]:.2f}" if a.rebase else ""
        print(f"W{w['n']:<3} {w['start']:7.2f} {w['end']:7.2f} {w['dur']:5.2f} {w['luma_min']:5.0f} {w['motion']:7.1f}"
              f"  {cut:<10} {flags}{m}")
    if vtt_out:
        print(f"speech VTT (VAD{' + whisper' if asr_n is not None else ' only'}) -> {vtt_out} = build_v5 \"vtt\"")
    print(f"-> {out}" + (f" + sheet {sheet_path} (W{', W'.join(str(n) for n in res['sheet_windows'])})" if sheet_path else ""))
    if a.vtt and not a.song and vtt_is_song(a.vtt):
        print(f"SONG? {a.vtt} has [Music]/♪ cues and no >> speaker mark = lyrics, not narration (footage-sourcing §0). "
              f"If no one speaks over the music, re-run with --song (speech-free = the whole song)")
    verdict = "USABLE" if moving >= USABLE_S else "STOP"
    print(f"{verdict}: {usable:.1f} s clean in {len(wins)} windows, {moving:.1f} s moving"
          + ("" if verdict == "USABLE" else f" < {USABLE_S:.0f} s -> try the next official source or ask Fix"))


if __name__ == "__main__":
    main()
