# Audio reference matching (gameplay preset)

Use when Fix attaches a reference clip: he wants our clip's sound to land near it on voice timbre, loudness and music bed. Measure both clips with the same tool, rank EQ candidates numerically, then send 2 tones in ONE round for him to pick.

## Measure both with the same tool

`uv run --with numpy python <skill_dir>/scripts/measure_audio.py <ref.mp4> <our_out.mp4>`

Prints per file: duration, integrated loudness / true peak / LRA, F0 mean/std/p10/p90, 5-band profile, pause fraction. Decode both to 16 kHz mono. F0 = autocorrelation keeping only conf > 0.40 and 120-400 Hz (music harmonics otherwise poison the median). Bands = each band's level relative to the 80-8000 Hz total, over the loudest 60% of frames.

## REF baseline (measured on Fix's 10 s presenter sample)

| metric | REF | our clip before tuning |
|---|---|---|
| loudness | -14.1 LUFS, LRA 1.1, TP 0.0 (it clips — do NOT copy the clipping) | -16.4 to -17.1 LUFS, TP -4.5 |
| F0 mean / std / p10-p90 | 289 / 49 / 235-364 Hz | 221 / 42 / 176-276 Hz |
| band 80-300 Hz | +7.6 | +17.8 (10 dB of mud) |
| band 300 Hz-1k | +14.2 | +14.6 (ok) |
| band 1-3 kHz | +4.1 | -1.0 (5 dB missing presence) |
| band 3-6k / 6-8k | -14.5 / -27.2 | -13.5 / -26.2 (ok) |
| speech minus music-only | 12.5 dB | 12.7 dB (already matched) |

Score = sum of abs(band - REF band) to rank EQ candidates numerically (raw 17.7, validated chain 4.0-8.0). Lower = closer. A lower-F0 voice never scores 0, so rank in code, never by eye.

## Validated fixes

1. VO chain (replaces the old 180 Hz boost, which measured WORSE than raw):
   `highpass=f=120,equalizer=f=220:g=-7:w=1.2,equalizer=f=2400:g=5:w=1.2,equalizer=f=4500:g=-4:w=1.3,equalizer=f=7500:g=2.5:w=1.0,acompressor=threshold=0.2:ratio=2:attack=12:release=200:makeup=1`
   then measure mean, `volume` back to the pre-chain mean, `alimiter=limit=0.9:level=0` LAST.
2. Pitch: REF F0 289 Hz -> candidates `+30Hz` (F0 238) and `+50Hz` (F0 265), sent as tone A/B in one round. **Fix PICKED tone A `+30Hz` on 2026-11-03 ("ชอบโทน A มากกว่า ใช้ A เป็นหลักเลย") -> with a REF clip, `+30Hz` is now the default, not `+50Hz`.** Lesson: the candidate closest to REF's F0 did NOT win — 265 Hz matched 289 Hz better, but 238 Hz sounded more natural to him, so pitch matching has a ceiling; never push F0 all the way to REF. Without a REF the standard stays `+11Hz`. Pitch does not move token timing, so the same PHRASES/subs work for every tone. Tone-name collision: the no-REF set is `+6Hz`=A/`+11Hz`=B, the REF set is `+30Hz`=A/`+50Hz`=B — always write the Hz value, never just "tone A".
3. Music bed: REF keeps music ~12.5 dB under speech; the old duck put ours ~26 dB under (music vanished = dry clip). Build with `[ga]volume=0.75` + `sidechaincompress=threshold=0.04:ratio=4:attack=15:release=500` -> measured 14-18 dB, clears the >=6 dB gate with margin. Trailer music level varies per clip, so re-measure the delta every time.
4. Loudness: run `scripts/master.sh` after build. Pre-limit target -13.7 -> ~-14.1 final; ceiling -4.5 -> max ~-4.0 to -4.4, which keeps the whole-clip max gate below -3 while matching REF's -14.1 LUFS.

## Pitfalls

- `alimiter` auto-level is ON by default: it boosts back and destroys gain staging. Always pass `level=0`.
- The limiter eats ~0.4 dB of integrated loudness: set the pre-limit target above the final target, and never run master twice (each run re-encodes audio = generation loss).
- Rank EQ candidates by band score in code; never copy another clip's chain numbers — every trailer's spectrum differs.
