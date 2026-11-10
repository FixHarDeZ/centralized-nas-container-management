# Audio recipe v2 — derived from Fix's reference clip (2026-11-03)

REF sample Fix attached: I=-14.1 LUFS, LRA 1.1, TP 0.0, F0 ~289 Hz, music under VO ~12.5 dB,
silent 0.026, bands 80-300 +7.6 / 1k-3k +4.1. Fix's complaint about old clips: "เสียงดูแข็ง / ไม่เป็นธรรมชาติ".

## VO chain (order matters)

```
highpass=f=120,equalizer=f=220:g=-7:w=1.2,equalizer=f=2400:g=5:w=1.2,
equalizer=f=4500:g=-4:w=1.3,equalizer=f=7500:g=2.5:w=1.0,
acompressor=threshold=0.2:ratio=2:attack=12:release=200:makeup=1
```
then level-match mean to -18.0 dB, limiter LAST.

- Old chain boosted 180 Hz → over-weighted bass = the "stiff" sound. Cutting 220 Hz and
  boosting presence 2.4 kHz is what makes it natural (band score vs REF: 17.7 → 4.9-8.0).
- `alimiter` without `level=0` auto-boosts ~0.6 dB and the level misses target — add `level=0`
  or re-measure and trim afterwards.

## VO pacing / breathing room (Fix สั่ง 2026-11-04: "เอาเสียงแบบนี้จดเป็นสกิลไว้เลย")

Fix's complaint about the pre-fix clips: *"เสียงคลิป gameplay รัวเกินไม่มีช่องไฟเว้นวรรคเลย"* —
one unbroken wall of Thai with no breath between sentences. The accepted sound (007 First Light,
20 s) is: short sentences, a real pause after each one, slightly slower than the old rate.

| knob | value | why |
|---|---|---|
| `--rate` | **`-3%`** (was `+6%`) | old rate made the wall feel rushed |
| `--pitch` | `+11Hz` unchanged (`+30Hz`/`+50Hz` when a REF clip exists) | tone is a separate axis from pacing |
| script layout | **one sentence per line** in `vo_script.txt` | edge-tts pauses **~0.9 s** at a newline (measured 0.88–0.97 s from `--probe` token gaps); blank lines give the same length, not longer |
| gaps per 20 s clip | **≥4–5 gaps, each >0.25 s** | measured, not eyeballed — read them off the probe output |
| end margin | last token `end` **≤ DUR − 1.5 s** | VO must finish ~1.5–2 s before the clip ends; never let the last word touch the edge |

Verified run: 6 lines / 5 gaps 0.88–0.97 s, VO 0.10–18.31 s inside a 20.07 s clip — when the
script runs long, **cut words, never compress the pauses**.

## Music under VO

```
volume=0.75 + sidechaincompress=threshold=0.04:ratio=4:attack=15:release=500
```
→ delta VO:music ≈ 18 dB (REF 12.5). Old settings (volume=0.5, threshold=0.02:ratio=8:release=700)
gave 26 dB — music vanished, clip felt dead.

## Master

`master.sh` defaults T=-13.7 C=-4.5 → final I≈-14.4 LUFS, TP≈-4.4 (REF -14.1/0.0, ceiling -3).

## Pitch tones (A/B in one round, never guess one at a time)

edge-tts pitch +30 Hz ≈ F0 238, +50 Hz ≈ 265 (REF 289). Pitch does NOT change token timing,
so PHRASES/subs.ass are reusable across tones. `NoAudioReceived` = service bug → retry loop only.

## Subtitle gap check: TV black is YAVG=16, not 0

A "gap after last subtitle" reading of YAVG=16 = pure black = PASS. Threshold for lit text must be
>16 (use ~17+); a `sub_gap_ok: false` with YAVG≈16 is a false alarm, not a burned-in leftover.

## Trailer footage → segs

Use `yt-dlp --write-auto-subs` on the trailer as a speech map: cut segs ONLY from quiet windows
so Thai VO never sits over English trailer speech. 8 segs ≈ 20.2 s total, boundaries confirmed
by vision contact sheets (a scene change mid-seam is invisible in frames — always check).

## File-name gotcha

The VO generator writes `voA_final.mp3` / `voB_final.mp3` (NO underscore), while build scripts
tend to reference `vo_A_final.mp3`. Assert existence before `shutil.copy` — a missing file killed
a build silently once.
