#!/usr/bin/env python3
"""edge-tts Thai voiceover + libass subtitle generator (WordBoundary-synced).

Usage:
  uv run --with edge-tts python gen_vo_subs.py --text vo_script.txt --probe
    -> writes vo.mp3, prints numbered WordBoundary tokens, writes NO subs.ass
  uv run --with edge-tts python gen_vo_subs.py --text vo_script.txt
    -> writes vo.mp3 AND subs.ass from the PHRASES table below

Fill PHRASES as (start_token_index, end_token_index_exclusive, on-screen text),
counting tokens from the --probe printout IN ORDER. Never string-match Thai
words: edge-tts splits Thai oddly and flat string matching fails silently.
"""
import argparse, asyncio, sys

p = argparse.ArgumentParser()
p.add_argument("--text", required=True)
p.add_argument("--out-mp3", default="vo.mp3")
p.add_argument("--out-ass", default="subs.ass")
p.add_argument("--voice", default="th-TH-PremwadeeNeural")
p.add_argument("--rate", default="+6%")
p.add_argument("--pitch", default="+11Hz")
p.add_argument("--probe", action="store_true")
args = p.parse_args()

# (start_token_idx, end_token_idx_exclusive, on-screen text) — fill from --probe output
PHRASES = [
    (0, 10, "หนึ่งวันของพนักงานใหม่ บนร้านอาหารกลางทะเล"),
    (10, 17, "ทำอาหาร เสิร์ฟลูกค้า จัดโต๊ะ"),
    (17, 25, "ตกแต่งร้านด้วยของกว่าสองร้อยชิ้น"),
    (25, 36, "สนุกกับตัวละครกว่าสี่ร้อยคนจากโลกวันพีซ"),
    (36, 46, "ทั้งทำครัวทั้งเสิร์ฟ ในกราฟิกพิกเซลสุดน่ารัก"),
    (46, 58, "เกมออกแล้วและกำลังจะกลับมาวางขายอีกครั้ง"),
    (58, 62, "ยี่สิบสี่พฤศจิกายน"),
    (62, 72, "ลองเข้ามาดูกันได้เลย ลิงก์ด้านล่าง"),
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

async def main():
    import edge_tts
    TEXT = open(args.text).read().strip()
    tts = edge_tts.Communicate(TEXT, args.voice, rate=args.rate, pitch=args.pitch, boundary="WordBoundary")
    words = []
    with open(args.out_mp3, "wb") as f:
        async for c in tts.stream():
            if c["type"] == "audio":
                f.write(c["data"])
            elif c["type"] == "WordBoundary":
                words.append((c["offset"] / 1e7, c["offset"] / 1e7 + c["duration"] / 1e7, c["text"].strip()))
    print("tokens:", len(words))
    for i, (a, b, t) in enumerate(words):
        print(i, f"{a:.2f}-{b:.2f}", t)
    if args.probe:
        print("(--probe: no subs written; fill PHRASES by token index and re-run)")
        return
    if not PHRASES:
        print("PHRASES is empty — run with --probe first, then fill PHRASES")
        sys.exit(1)

    def ts(t):
        t = max(t, 0.0)
        h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
        return f"{h}:{m:02d}:{s:05.2f}"

    lines = []
    for a, b, text in PHRASES:
        if a >= len(words):
            continue
        b = min(b, len(words))
        st = words[a][0]
        en = words[b - 1][1] + 0.12
        lines.append(f"Dialogue: 0,{ts(st)},{ts(en)},Sub,,0,0,0,,{text}")
    open(args.out_ass, "w").write(STYLE_HDR + "\n".join(lines) + "\n")
    print(args.out_mp3, "+", args.out_ass, "| lines:", len(lines))
    for l in lines:
        print(l)

asyncio.run(main())
