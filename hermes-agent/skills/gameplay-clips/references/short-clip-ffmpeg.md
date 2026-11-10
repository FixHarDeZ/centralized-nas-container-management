# Short footage clip (≤15 s) without build_v5: direct ffmpeg path

Use when the usable footage is one or two clean windows and a full `build_v5.py` plan is overkill
(the 12 s clip on 2026-11-07 used this path). The gates in SKILL.md still apply; this file is the
recipe and the traps. Template: `templates/short_clip_build.py` (copy, edit the constants, run).

## Recipe
1. **Pick the window from measured gaps, then verify it by frames.** Gap seconds come from
   `asr_speech_spans.py` (`--start 0 --dur <full>`). Before cutting, sample the window at 1 fps
   on a tile sheet and check: no on-screen text (subtitle boxes, dialogue panes, title cards,
   HUD prompts that read as text), no logos, no cutscene if gameplay is the promise. Start ≥1 s
   after a scene change, end ≥0.5 s before one.
2. **Check the source audio of that exact window** before designing the mix:
   `ffmpeg -ss T -t D -i src -af volumedetect -vn -f null -`. A window can be completely silent
   (-91 dB) when the trailer's music starts later. Then the clip is VO-only; say so in the delivery.
3. **Generate VO per phrase** with `uv run --with edge-tts python script.py` (not `uv tool run`),
   record each phrase's real duration with ffprobe, place phrase starts at known times, and assert
   `last_end <= DUR - 1.0`. Use the same start times for the subtitle `Dialogue` events.
4. **Mix VO into one track with `adelay` + `amix`**, then `apad=whole_dur=DUR,atrim=0:DUR` so the
   track is exactly DUR long.
5. **Duck the music with sidechain, one graph, one label per use** (see pitfalls below).
6. **Encode once** with the output flags from SKILL.md (`-profile:v high -level 4.0 -pix_fmt yuv420p
   -movflags +faststart`, AAC 48k stereo, `-r 30`).
7. **Verify:** `ffprobe` (duration equal for v and a, 30/1), `volumedetect` on the OUTPUT
   (mean > -40 dB), and frames at each phrase start and at the CTA second, read by vision for stray
   text, price, watermark, or subtitle clipping.

## Pitfalls (each one cost a run)
- **An ffmpeg filter label can be consumed only once.** Using `[vo]` both as the sidechain key and
  as the amix input produced a silent output with no error at `-v error`. Split first:
  `asplit=2[vo][vok]`, then key with `[vok]` and mix `[vo]`.
- **`amix` with `duration=first` silently truncates to the first input's length.** Use
  `duration=longest`, then `apad` + `atrim` to pin the length.
- **`sidechaincompress` output follows the main (music) input's length.** If the music input is
  shorter than the clip, the mix is short by the difference (measured 0.52 s). Pad the music input
  with `apad=whole_dur=DUR,atrim=0:DUR` before it enters the sidechain.
- **A silent source window makes the duck meaningless.** Check step 2 first; do not try to fix
  it by raising gain on the silent track.
- **Subtitle event end times must come from the real phrase durations**, not planned lengths; a
  planned end that outruns the audio shows subtitles over silence.
- **Pills are drawtext and their `enable='between(t,a,b)'` windows must not overlap.** Position them
  at the same y (the pill row) and check each frame interval in the frame sheet.
- **Concat of separately overlaid branches fails on SAR.** Each `bg`+`overlay` branch can come out with a different sample aspect ratio, and `concat` then aborts with `Input link ... parameters do not match` (exit 234, no output file). Put `setsar=1` on EVERY input of the concat, right before it, not only on the first.
- **Multi-window footage = one `-ss T -t D -i trailer.mp4` input per window**, each with its own `split` → blurred bg + 720x405 window overlay at y=280, then `concat=n=N:v=1:a=0`. Derive the audio of each window from the same input and concat them the same way, and pad the total to DUR. Mute or duck any window whose ASR shows speech; a window whose source has speech and no VO over it breaks the audio gate.
- **Find exact text-free boundaries at 0.25 s steps, not 1 s.** Extract one frame per 0.25 s around each candidate edge (`ffmpeg -ss t -frames:v 1`), tile with PIL with the time written on each tile, and ask vision for subtitle/text yes/no per tile. A 1 s sheet misses a subtitle that appears for 0.5 s, and the edge is where a window fails.
- **Gap-count gate scales with clip length.** The VO gate of "≥4 gaps >0.25 s per 20 s" becomes roughly 1 gap per 5 s for a short clip. A 7 s clip with one 0.5 s gap is normal; do not pad silence or stretch phrases to satisfy the 20 s count.
- **Source-embedded UI glyphs** (player icons in a corner of the trailer window) survive the crop.
  Either crop them out of the source before scaling, or name them in the delivery. A small corner
  glyph reads as a player control, not a watermark, but still check it in the final frames.

## Multi-window short clip: lessons from the 2026-11-08 P4R run (10.3 s, 4 cuts)
- **Budget the windows before writing any copy.** Four clean windows (ASR gap ∩ vision no-text) summed to 10.4 s from one trailer. Fix had asked for ~12 s and chose the measured length; say the real number in the delivery.
- **Gemini whole-take VO can run longer than the clip.** 3 phrases came back at vo_end 11.8 s for a 10.4 s clip. Re-time with `--from-take` (0 requests) using top-level `"tempo": 1.07` and smaller `gap_after`; the planned gap is applied after each take phrase, so the last phrase lands where the take puts it. Hold the CTA phrase to ~1 s.
- **Subtitle file = your own ASS, not the one gen_vo_natural writes.** Its Style still carries the v4 MarginV 290 and bold. Write the template Style (MarginV 465, Bold 0) and take event times from the `vo2.log` timeline.
- **Fonts for `ass=`**: copy only Itim-Regular.ttf and FredokaSB-Static.ttf into `fonts_only/` and pass `ass=subs.ass:fontsdir=fonts_only:shaping=complex`.
- **Duck-only gate graph exits 234 unless `[vo]` is consumed**: end the branch with `[vo]anullsink`. Measure: RMS(mix) − RMS(duck-only) over each VO window ≥ 6 dB (P4R: 12.1 dB min).
- **Cover sticker in graphics_layer: `x` is the LEFT edge** (`x + w_est ≤ 640`). A 490×544 crop at h=220 is w≈198, so x=410 keeps it clear of the right rail.
- **make_cover.py needs `uv run --with pillow --with numpy`** (plain `python3` has no numpy). Feed it a footage-only render (no pills, no subs).

## Motion and text checks that do not rely on vision alone
- `ImageChops.difference` mean across 3 frames 0.5 s apart: a moving camera gives roughly 0.5–90;
  near-zero means a static title/logo frame. Vision called static frames "gameplay", so use this
  number to confirm any window labelled gameplay.
- See `references/footage-sourcing.md` §5 for the bottom-strip subtitle check on a montage.
