#!/usr/bin/env python3
"""Natural-sounding Thai VO + subs.ass, per-phrase prosody (edge-tts OR Gemini TTS).

Why: gen_vo_custom.py uses ONE rate/pitch and ONE gap for every phrase -> flat,
metronomic, "AI" delivery. Here every phrase carries its own mood/rate/pitch
and its own gap_after, and the Gemini engine takes a natural-language
direction ("excited teen girl reviewing a game") per phrase.

Usage:
  uv run --with edge-tts python gen_vo_natural.py plan.json [--probe] [--out-mp3 vo.mp3] [--out-ass subs.ass]
  (Gemini needs GEMINI_API_KEY in env or /opt/data/.env; stdlib urllib only)

plan.json:
{
  "engine": "gemini" | "edge",
  "voice":  "Laomedeia"            # gemini prebuilt voice | edge voice (th-TH-PremwadeeNeural)
  "model":  "gemini-2.5-flash-preview-tts", # gemini only (see synth_gemini for why not 3.8)
  "style":  "cheerful, casual Thai teen girl telling a friend about a game",  # gemini, ENGLISH, all phrases
  "lead": 0.10,                    # silence before first phrase
  "phrases": [
    {"say": "spoken text (numbers as words)", "sub": "on-screen text, \\n = 2nd line",
     "mood": "excited",               # gemini: appended to style (English)
     "rate": "+4%", "pitch": "+14Hz",  # edge only (defaults -3% / +11Hz)
     "gap_after": 0.30}               # silence after this phrase (default 0.35)
  ]
}
Outputs vo.mp3 (48k stereo), subs.ass (Itim style identical to v4), and prints the
timeline + gates: gaps>0.25 count (need >=4 per 20 s), last end, per-phrase
chars/sec (a phrase far faster than its neighbours = engine skipped words).
Every phrase is RMS-levelled to the same loudness so per-call takes match.
"""
import time, argparse, asyncio, base64, io, json, math, os, struct, subprocess, sys, urllib.request, wave

ap = argparse.ArgumentParser()
ap.add_argument("plan")
ap.add_argument("--probe", action="store_true", help="synthesize + print timeline, write no outputs")
ap.add_argument("--out-mp3", default="vo.mp3")
ap.add_argument("--out-ass", default="subs.ass")
ap.add_argument("--keep-takes", action="store_true", help="keep .take_N.wav per phrase")
ap.add_argument("--from-take", help="gemini: reuse a saved whole-script take (wav/mp3) instead of calling the API")
ap.add_argument("--take-out", default="gemini_take.wav", help="gemini: where the raw whole-script take is saved")
args = ap.parse_args()
P = json.load(open(args.plan, encoding="utf-8"))
ENGINE = P.get("engine", "edge")
SR = 48000
TH = 600
TAIL = int(0.06 * SR)
TARGET_RMS = 3200.0  # int16 RMS of voiced part, all phrases levelled to this

STYLE_HDR = """[Script Info]
ScriptType: v4.00+
PlayResX: 720
PlayResY: 1280
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,Itim,48,&H0066D1FF,&H0066D1FF,&H00203050,&H60203050,1,0,0,0,100,100,0,0,1,5,2.5,2,50,50,290,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def gemini_key():
    k = os.environ.get("GEMINI_API_KEY")
    if not k and os.path.exists("/opt/data/.env"):
        for line in open("/opt/data/.env"):
            if line.startswith("GEMINI_API_KEY="):
                k = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not k:
        sys.exit("GEMINI_API_KEY missing")
    return k


class QuotaExhausted(Exception):
    pass


GEMINI_CHAIN = ["gemini-3.8-flash-tts", "gemini-3.1-flash-tts-preview",
                "gemini-3.8-flash-lite-tts", "gemini-2.5-flash-preview-tts"]
if os.environ.get("VO_GEMINI_CHAIN"):  # override, e.g. to test the fallback with exhausted models
    GEMINI_CHAIN = os.environ["VO_GEMINI_CHAIN"].split(",")


def synth_gemini(ph, model=None):
    """-> raw input bytes for ffmpeg + input format args."""
    model = model or P.get("model", "gemini-3.8-flash-tts")
    # Prompt form is model-specific (measured 2026-11-05, ASR-checked):
    #  * gemini-2.5-flash-preview-tts: "Read aloud in a <how> tone:\n<text>" -> obeys
    #    the direction, speaks only <text>. DEFAULT.
    #  * gemini-3.8-flash-tts: any prose direction (Thai OR English, "Say ...:" or
    #    "Read aloud ...:") is READ ALOUD (16-19 s takes for a 2 s line); "[excited] <text>"
    #    tags work but it improvises extra words ("โอ้โห ...") -> subs no longer match.
    how = ", ".join(x for x in (P.get("style", ""), ph.get("mood", "")) if x)
    if ph.get("_text"):
        text = ph["_text"]
    elif not how:
        text = ph["say"]
    elif "2.5" in model:
        text = f"Read aloud in a {how} tone:\n{ph['say']}"
    else:
        text = f"[{ph.get('mood') or P.get('style')}] {ph['say']}"
    body = {"contents": [{"parts": [{"text": text}]}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                                 "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig":
                                                                  {"voiceName": P.get("voice", "Laomedeia")}}}}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    last = None
    payload = body  # keep the JSON payload: the except-branch below rebinds `body` to bytes,
    # and json.dumps(bytes) on the next retry raised "Object of type bytes is not JSON serializable"
    for _ in range(7):
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                         headers={"Content-Type": "application/json",
                                                  "x-goog-api-key": gemini_key()})
            r = json.load(urllib.request.urlopen(req, timeout=120))
            c0 = r["candidates"][0]
            if "content" not in c0:  # intermittent: candidate with finishReason only, no audio
                raise RuntimeError(f"no audio (finishReason={c0.get('finishReason')})")
            part = c0["content"]["parts"][0]["inlineData"]
            mime = part.get("mimeType", "")
            rate = 24000
            if "rate=" in mime:
                rate = int(mime.split("rate=")[1].split(";")[0])
            return base64.b64decode(part["data"]), ["-f", "s16le", "-ar", str(rate), "-ac", "1"]
        except Exception as e:  # 429/500/empty candidate -> retry
            body = getattr(e, "read", lambda: b"")() or str(e).encode()
            last = body[:300]
            if b"PerDay" in body or b"per day" in body.lower():
                raise QuotaExhausted(model)  # daily free quota: retrying is pointless, next model
            time.sleep(35 if "429" in str(e) else 5)  # per-minute limit / transient
    sys.exit(f"gemini TTS failed for {ph['say'][:30]!r}: {last}")


def gemini_whole():
    """ONE request for the whole script (free tier = 10 requests/DAY/model -> per-phrase calls burn
    the quota in 1-2 clips). Returns 48k stereo s16 frames of the raw take."""
    if args.from_take:
        return to_frames(open(args.from_take, "rb").read(), [])
    lines = "\n".join(ph["say"] for ph in P["phrases"])
    style = P.get("style", "")
    chain = GEMINI_CHAIN if os.environ.get("VO_GEMINI_CHAIN") or not P.get("model") \
        else [P["model"]] + [m for m in GEMINI_CHAIN if m != P["model"]]
    raw = None
    for model in chain:
        text = (f"Read aloud in a {style} tone:\n{lines}" if "2.5" in model
                else (f"[{style}] {lines}" if style else lines))
        try:
            raw, fmt = synth_gemini({"say": lines, "_text": text}, model)
            print("gemini model:", model)
            break
        except QuotaExhausted:
            print(f"quota exhausted today: {model} -> next")
    if raw is None:
        return None  # every model out of daily quota -> caller falls back to edge (plan A)
    fr = to_frames(raw, fmt)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", "pipe:0",
                    args.take_out], input=fr, check=True)
    print("raw take saved:", args.take_out, f"{len(fr)/4/SR:.2f}s (reuse with --from-take)")
    return fr


def align_bounds(fr):
    """Phrase boundaries in the whole take: ASR word timestamps (faster-whisper small) mapped by
    cumulative script-character proportion, then snapped to the quietest 20 ms inside +-0.35 s."""
    import numpy as np
    from faster_whisper import WhisperModel
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "shopee-clip", "scripts"))
    import heavylock
    heavylock.acquire("gen_vo_natural")
    st = np.frombuffer(fr, np.int16).reshape(-1, 2).mean(1)
    mono16 = st[::3].astype(np.float32) / 32768.0           # 48k -> 16k
    words = []
    segs, _ = WhisperModel("small", device="cpu", compute_type="int8").transcribe(
        mono16, language="th", word_timestamps=True)
    for sg in segs:
        for w in sg.words:
            words.append((w.start, w.end, len(w.word.strip()) or 1))
    tot_asr = sum(w[2] for w in words)
    say = [len(ph["say"].replace(" ", "")) for ph in P["phrases"]]
    tot = sum(say)
    env = np.convolve(np.abs(st), np.ones(960) / 960, "same")  # 20 ms envelope
    bounds, acc = [], 0
    for n in say[:-1]:
        acc += n
        target = acc / tot * tot_asr
        c, t = 0, words[-1][1]
        for a, b, k in words:
            c += k
            if c >= target:
                t = b; break
        i0, i1 = int(max(0, t - 0.35) * SR), int(min(len(st) / SR, t + 0.35) * SR)
        bounds.append((i0 + int(np.argmin(env[i0:i1]))) / SR)
    return bounds


def synth_edge(ph):
    import edge_tts
    last = None
    for _ in range(5):
        try:
            async def run():
                c = edge_tts.Communicate(ph["say"], P.get("voice", "th-TH-PremwadeeNeural"),
                                         rate=ph.get("rate", "-3%"), pitch=ph.get("pitch", "+11Hz"))
                b = io.BytesIO()
                async for ch in c.stream():
                    if ch["type"] == "audio":
                        b.write(ch["data"])
                return b.getvalue()
            d = asyncio.run(run())
            if d:
                return d, []
        except Exception as e:
            last = str(e)
    sys.exit(f"edge TTS failed for {ph['say'][:30]!r}: {last}")


def to_frames(raw, fmt):
    out = subprocess.run(["ffmpeg", "-v", "error", *(fmt or []), "-i", "pipe:0", "-ar", str(SR), "-ac", "2",
                          "-f", "s16le", "pipe:1"], input=raw, capture_output=True, check=True).stdout
    return out


def trim_level(fr):
    n = len(fr) // 4
    s = struct.unpack("<%dh" % (2 * n), fr[:4 * n])
    s0 = s1 = None
    for i in range(n):
        if abs(s[2 * i]) > TH or abs(s[2 * i + 1]) > TH:
            if s0 is None:
                s0 = i
            s1 = i
    if s0 is None:
        return fr
    s1 = min(n, s1 + TAIL)
    seg = s[2 * s0:2 * s1]
    voiced = [x for x in seg if abs(x) > TH] or seg
    rms = math.sqrt(sum(x * x for x in voiced) / len(voiced))
    g = TARGET_RMS / rms if rms else 1.0
    peak = max(abs(x) for x in seg) * g
    if peak > 30000:
        g *= 30000 / peak
    return struct.pack("<%dh" % len(seg), *[int(max(-32768, min(32767, x * g))) for x in seg])


def squeeze_pauses(fr, max_pause):
    """Shorten silences INSIDE a phrase longer than max_pause s down to max_pause (Gemini takes
    breathe a lot; this fits a deadline without speeding the voice up = no 'rushed' sound)."""
    n = len(fr) // 4
    s = struct.unpack("<%dh" % (2 * n), fr[:4 * n])
    win = int(0.01 * SR)
    quiet = [max(abs(x) for x in s[2 * i * win:2 * (i + 1) * win] or [0]) < TH for i in range(n // win)]
    keep = int(max_pause / 0.01)
    out, run = [], 0
    for i, q in enumerate(quiet):
        run = run + 1 if q else 0
        if run <= keep:
            out.append(fr[4 * i * win:4 * (i + 1) * win])
    out.append(fr[4 * (n // win) * win:])
    return b"".join(out)


def main():
    pos = int(P.get("lead", 0.10) * SR)
    parts = [b"\x00" * 4 * pos]
    tl = []
    global ENGINE
    whole = None
    if ENGINE == "gemini" and P.get("mode", "whole") == "whole":
        whole = gemini_whole()
        if whole is None:
            print("FALLBACK: all Gemini models out of quota -> edge-tts plan A (per-phrase rate/pitch + warm EQ)")
            ENGINE = "edge"
            P["voice"] = P.get("edge_voice", "th-TH-PremwadeeNeural")
    if whole is not None:
        cuts = [0] + [int(b * SR) for b in align_bounds(whole)] + [len(whole) // 4]
        pieces = [whole[4 * a:4 * b] for a, b in zip(cuts, cuts[1:])]
        print("align bounds:", [round(c / SR, 2) for c in cuts[1:-1]])
    # tempo / pause squeeze are Gemini fitting knobs; edge (incl. fallback) is already brisk
    tempo = float(P.get("tempo", 1.0)) if ENGINE == "gemini" else 1.0
    for i, ph in enumerate(P["phrases"]):
        if whole is not None:
            fr = pieces[i]
        else:
            if ENGINE == "gemini" and i:
                time.sleep(P.get("sleep", 7))
            raw, fmt = (synth_gemini if ENGINE == "gemini" else synth_edge)(ph)
            fr = to_frames(raw, fmt)
        if tempo != 1.0:  # atempo keeps pitch; use to fit a deadline instead of cutting pauses to 0
            fr = subprocess.run(["ffmpeg", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", "pipe:0",
                                 "-af", f"atempo={tempo}", "-f", "s16le", "pipe:1"], input=fr,
                                capture_output=True, check=True).stdout
        seg = trim_level(fr)
        if P.get("max_inner_pause") and ENGINE == "gemini":
            seg = squeeze_pauses(seg, float(P["max_inner_pause"]))
        if args.keep_takes:
            w = wave.open(f".take_{i}.wav", "wb"); w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
            w.writeframes(seg); w.close()
        st = pos / SR
        parts.append(seg)
        pos += len(seg) // 4
        tl.append({"i": i, "start": st, "end": pos / SR, "say": ph["say"], "sub": ph.get("sub", ph["say"])})
        if i < len(P["phrases"]) - 1:
            g = int(ph.get("gap_after", 0.35) * SR)
            parts.append(b"\x00" * 4 * g)
            pos += g
    gaps = [round(tl[i]["start"] - tl[i - 1]["end"], 2) for i in range(1, len(tl))]
    print(f"engine={ENGINE} voice={P.get('voice')} phrases={len(tl)} vo_end={tl[-1]['end']:.2f}s")
    for e in tl:
        d = e["end"] - e["start"]
        cps = len(e["say"].replace(" ", "")) / d if d else 0
        print(f"  [{e['i']}] {e['start']:.2f}-{e['end']:.2f} ({d:.2f}s, {cps:.1f} ch/s)  {e['say'][:44]}")
    big = [g for g in gaps if g > 0.25]
    print(f"gaps={gaps}  gaps>0.25={len(big)}")
    if len(big) < 4:
        print("GATE WARN: <4 gaps > 0.25s")
    cps_all = [len(e["say"].replace(" ", "")) / (e["end"] - e["start"]) for e in tl]
    med = sorted(cps_all)[len(cps_all) // 2]
    for e, c in zip(tl, cps_all):
        if c > med * 1.45 or c < med * 0.55:
            print(f"GATE WARN: phrase {e['i']} {c:.1f} ch/s vs median {med:.1f} -> engine may have skipped/added words; listen/ASR it")
    if args.probe:
        print("(--probe: no files written)"); return
    pcm = b"".join(parts)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", "pipe:0",
                    "-codec:a", "libmp3lame", "-q:a", "2", args.out_mp3], input=pcm, check=True)

    def ts(t):
        t = max(t, 0.0)
        return f"{int(t // 3600)}:{int(t % 3600 // 60):02d}:{t % 60:05.2f}"
    ev = [f"Dialogue: 0,{ts(e['start'])},{ts(e['end'] + 0.12)},Sub,,0,0,0,,{e['sub'].replace(chr(10), chr(92) + 'N')}"
          for e in tl]
    open(args.out_ass, "w", encoding="utf-8").write(STYLE_HDR + "\n".join(ev) + "\n")
    json.dump(tl, open(os.path.splitext(args.out_ass)[0] + ".timeline.json", "w"), ensure_ascii=False, indent=1)
    open(os.path.splitext(args.out_mp3)[0] + ".engine", "w").write(ENGINE + "\n")
    print(args.out_mp3, "+", args.out_ass, "| events:", len(ev), "| engine used:", ENGINE,
          "(edge -> apply warm EQ chain)" if ENGINE == "edge" else "")


main()
