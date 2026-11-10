#!/usr/bin/env python3
"""Phrase-by-phrase edge-tts Thai VO builder with EXACT inter-phrase gaps.

VO PACING STANDARD for the `gameplay` preset (Fix 2026-11-04:
"ช่องไฟพูดเว้นนานไปหน่อย เหมือนพูดแล้วหยุด พูดแล้วหยุดตลอดเวลาฟังแล้วแปลกๆ").

Why this replaces gen_vo_subs.py's newline pacing:
  * newline in edge-tts  -> pause fixed ~0.95s EVERY time (too long: "พูดแล้วหยุด")
  * space / period / dash / "..." -> 0.00s (too fast: "รัว")
  * comma -> 0.15-0.32s, semicolon -> 0.15-0.40s (inconsistent, few pass 0.25)
  * SSML <break time="500ms"/> -> edge-tts reads the tags aloud (garbage)
So: synthesise each phrase separately, trim its head/tail silence, join with
a byte-exact silence -> measured gaps 0.37-0.41s with --gap 0.50.

Usage (copy THIS file into the work dir first, then edit PHRASES_TEXT there;
never edit the copy inside the skill):
  uv run --with edge-tts python gen_vo_custom.py --script script_lines.txt \
      --gap 0.50 --rate '-3%' --pitch '+11Hz' --probe
    -> per-phrase timeline + gaps>0.25 count + last_token_end (writes NO files)
  ... same command without --probe
    -> writes vo.mp3 + subs.ass (build.sh consumes both)

Contract:
  * script = one phrase per line (blank lines skipped). 1 line == 1 entry of
    PHRASES_TEXT == 1 subtitle event == 1 inter-phrase gap.
  * PHRASES_TEXT = on-screen Thai subtitle text, index-aligned with the
    non-blank script lines; may contain \n to wrap into 2 lines (converted
to ASS \\N at write time — a raw newline would end the Dialogue line and
silently drop the rest of the text).
  * rate '-3%' / pitch '+11Hz' are the preset defaults (see SKILL.md).
  * Gates it prints for you: >=4 gaps > 0.25s, last_token_end <= DUR-1.5.
  * If shorter gaps make the VO end too early -> ADD phrases (more selling
    points), never raise --gap back toward 1.0.
  * Retries each synthesis up to 5x (edge-tts raises NoAudioReceived
    randomly even with correct parameters).
"""
import argparse, asyncio, io, os, subprocess, wave

p = argparse.ArgumentParser()
p.add_argument("--script", required=True, help="one phrase per line (blank lines skipped)")
p.add_argument("--gap", type=float, default=0.50, help="exact silence between phrases, seconds")
p.add_argument("--lead", type=float, default=0.10, help="silence before first phrase")
p.add_argument("--rate", default="-3%")
p.add_argument("--pitch", default="+11Hz")
p.add_argument("--voice", default="th-TH-PremwadeeNeural")
p.add_argument("--probe", action="store_true")
p.add_argument("--out-mp3", default="vo.mp3")
p.add_argument("--out-ass", default="subs.ass")
args = p.parse_args()

SR = 48000
TH = 600                 # peak amplitude that counts as speech (int16)
TAIL = int(0.06 * SR)    # keep 60ms after last loud sample (consonant decay)

# EDIT PER CLIP: on-screen Thai subtitle text, one entry per non-blank line
# of --script, in order. Empty list => subtitle text falls back to the
# spoken phrase itself (readable but unwrapped).
PHRASES_TEXT = [
    "วลีแรกที่ขึ้นจอ",
    "วลีที่สอง",
]

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


def synth(phrase):
    """-> (mp3_bytes, [(start, end, text), ...]) with retries on service errors."""
    import edge_tts
    last = None
    for _ in range(5):
        try:
            async def run():
                tts = edge_tts.Communicate(phrase, args.voice, rate=args.rate,
                                           pitch=args.pitch, boundary="WordBoundary")
                buf = io.BytesIO()
                toks = []
                async for c in tts.stream():
                    if c["type"] == "audio":
                        buf.write(c["data"])
                    elif c["type"] == "WordBoundary":
                        toks.append((c["offset"] / 1e7,
                                     c["offset"] / 1e7 + c["duration"] / 1e7,
                                     c["text"].strip()))
                return buf.getvalue(), toks
            data, toks = asyncio.run(run())
            if data and toks:
                return data, toks
            last = "empty audio/tokens"
        except Exception as exc:
            last = str(exc)
    raise SystemExit("TTS failed for %r: %s" % (phrase[:30], last))


def to_wav(mp3_bytes, path):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", "pipe:0",
                    "-ar", str(SR), "-ac", "2", "-f", "wav", path],
                   input=mp3_bytes, check=True, timeout=120)


def load(path):
    w = wave.open(path, "rb")
    assert w.getframerate() == SR and w.getnchannels() == 2 and w.getsampwidth() == 2
    frames = w.readframes(w.getnframes())
    w.close()
    return frames


def trim(frames):
    """-> (s0, s1) frame indices bounding the speech (head/tail silence removed)."""
    n = len(frames) // 4
    s0 = None
    s1 = None
    for i in range(n):
        l = int.from_bytes(frames[4*i:4*i+2], "little", signed=True)
        r = int.from_bytes(frames[4*i+2:4*i+4], "little", signed=True)
        if abs(l) > TH or abs(r) > TH:
            if s0 is None:
                s0 = i
            s1 = i
    if s0 is None:
        return 0, n
    return s0, min(n, s1 + TAIL)


def main():
    lines = [l.strip() for l in open(args.script, encoding="utf-8").read().splitlines()]
    phrases = [l for l in lines if l]
    if PHRASES_TEXT and len(phrases) != len(PHRASES_TEXT):
        print("WARNING: %d script lines vs %d PHRASES_TEXT — subtitle events may misalign"
              % (len(phrases), len(PHRASES_TEXT)))

    parts = []
    pos = int(args.lead * SR)
    sil_gap = b"\x00" * (4 * int(args.gap * SR))

    timeline = []
    for idx, ph in enumerate(phrases):
        mp3, toks = synth(ph)
        tmp = f".phrase_{idx}.wav"
        to_wav(mp3, tmp)
        fr = load(tmp)
        s0, s1 = trim(fr)
        seg = fr[s0*4: s1*4]
        pre = b"" if idx == 0 else sil_gap   # silence inserted BEFORE this phrase
        if not args.probe:
            parts.append(pre)
            parts.append(seg)
        shift = (pos + len(pre) // 4) / SR
        timeline.append({
            "idx": idx, "phrase": ph, "start": shift,
            "end": shift + len(seg) / 4 / SR,
            "tokens": [(shift + (a - s0 / SR), shift + (b - s0 / SR), t) for a, b, t in toks],
        })
        pos += len(pre) // 4 + len(seg) // 4
        os.remove(tmp)

    print(f"phrases={len(phrases)} gap={args.gap} total_vo={pos/SR:.2f}s")
    alltoks = []
    for e in timeline:
        g0 = e["tokens"][0][0] if e["tokens"] else e["start"]
        g1 = e["tokens"][-1][1] if e["tokens"] else e["end"]
        print(f"  [{e['idx']}] {e['start']:.2f}-{e['end']:.2f} ({e['end']-e['start']:.2f}s) "
              f"tok {g0:.2f}-{g1:.2f}  {e['phrase'][:40]}")
        alltoks.extend(e["tokens"])
    alltoks.sort()
    gaps = [round(alltoks[i][0] - alltoks[i-1][1], 2) for i in range(1, len(alltoks))]
    big = [g for g in gaps if g > 0.25]
    print(f"last_token_end={alltoks[-1][1]:.2f}s  gaps>0.25={len(big)} {big}")
    if len(big) < 4:
        print("GATE FAIL: need >=4 gaps > 0.25s (add more phrases)")
    if args.probe:
        print("(--probe: no files written)")
        return

    w = wave.open(".vo_full.wav", "wb")
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(b"".join(parts)); w.close()
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", ".vo_full.wav",
                    "-codec:a", "libmp3lame", "-q:a", "2", args.out_mp3],
                   check=True, timeout=300)
    os.remove(".vo_full.wav")

    def ts(t):
        t = max(t, 0.0)
        h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    ev = []
    for i, e in enumerate(timeline):
        txt = PHRASES_TEXT[i] if i < len(PHRASES_TEXT) else e["phrase"]
        txt = txt.replace("\n", "\\N")  # ASS line break — a raw newline would end the Dialogue line
        st = e["tokens"][0][0] if e["tokens"] else e["start"]
        en = e["tokens"][-1][1] + 0.12 if e["tokens"] else e["end"]
        ev.append(f"Dialogue: 0,{ts(st)},{ts(en)},Sub,,0,0,0,,{txt}")
    open(args.out_ass, "w", encoding="utf-8").write(STYLE_HDR + "\n".join(ev) + "\n")
    print(args.out_mp3, "+", args.out_ass, "| events:", len(ev))
    for e in ev:
        print(e)


main()
