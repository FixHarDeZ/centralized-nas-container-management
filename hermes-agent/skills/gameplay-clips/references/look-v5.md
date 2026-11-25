# LOOK v5: `scripts/build_v5.py` (cold open, push-in, beat cuts, flash/SFX, loop tail)

Fix approved the LEGO Batman demo. **It is the default builder; v4 `build.sh` is the fallback only.**
(The demo work dir was cleaned up at job end. The example plan below and the docstring schema are the reference.)

## Tall window = the default layout (Fix 2026-11-17, "เอา A")
The 16:9 band left the lower 45 % of the frame as blur. Every new plan sets **`"window_h": 720`** and has no
`window_y` key (it defaults to 190): the footage is a 1:1 window at y 190–910, cropped from the ORIGINAL
trailer, ~1.8× the picture area. Fix approved the Harvest Moon mock (message 11604) rendered this way.
- **The crop keeps the middle 56 % of the width.** Look at each window shot on a frame sheet: subject off-centre
  → `"win_x": ±N` on that seg (px of the 1080p source, limit ±420). HUD / text / two subjects at both edges →
  `"wide": true` on that seg (whole 16:9 picture as a band inside the window). The OCR text check must read the
  1:1 crop, not the full frame: text outside the crop is gone, text inside it is bigger.
- **Pill and subs sit ON the footage** (pill y 210, subs MarginV 465, unchanged numbers). Check a frame per sub
  for a bright or busy patch behind the text.
- **Cover sticker** (`gfx.json`): `"y": 1060` (not 960) and `avoid` footage `[0, 190, 720, 910]`.
- A source with letterbox bars baked in ALL the way through shows them in every window and hero — `wide` and
  window-picking cannot hide them (the bars are part of the picture). Measure row-mean over several frames
  first; if the edge rows are ≈0 on every frame, crop the bars into a new source file BEFORE encoding master
  and point both `master` and `trailer` at it (recipe in gameplay-pitfalls §Footage). A bar that appears only
  in one shot is scene darkness — leave it.
- Not proven yet: `sub_linecheck.py` / `sub_bandprofile.py` on subs that lie over footage (they were tuned on
  the blurred plate) — a FAIL there needs a look at the frame, not a blind re-render.
- `window_h` omitted = the old 16:9 band; use it only when Fix asks for the old look.

## What changed vs v4
- **Cold open.** Seg 0 is a full-screen `hero` shot, a 9:16 centre crop of the ORIGINAL 1080p
  trailer (sharp). There is no title card. The transparent game logo sits small on top for ~1.5 s.
- **Push-in.** Every `window` shot zooms 1.00→1.10 with a sub-pixel affine transform.
  `--selftest-zoom`: max deviation 0.069 px, monotonic, PASS. There is no wobble.
- **Hero shots.** 1–2 per clip is enough. The demo uses 5 of 10, which is busy; keep ≤3.
- **Beat-snapped cuts.** `scripts/beats.py` (spectral flux + autocorrelation tempo) writes
  `work/beats_all.json`. Seg in/out snap to beats inside no-speech gaps (beat_off 3–48 ms measured).
  `snap:false` keeps a seg as planned.
- **Seams.** A 3-frame white flash (0.5/0.3/0.12) plus whoosh/impact SFX.
  `scripts/make_sfx.sh` writes the synthetic SFX to `assets/sfx/`.
- **Countdown pill.** `release_date` gives `D-N` for future dates and `OUT NOW` for past ones.
- **Loop tail.** The last 0.3 s crossfades into frame 0.
- **Safe zones** (`references/safe-zones.md`): window y=280, pill y=210, subs MarginV=465.
  The v4 numbers (pill 52 / subs 290) sit under app UI on every platform.
- **Grade.** `grade` [gamma 1.18, sat 1.15, contrast 1.04]. Trailers are graded dark for TV.

## Run
```
cd <work>; uv run --with numpy --with pillow python <skill>/scripts/build_v5.py plan.json --check   # resolve + validate, no render
uv run --with numpy --with pillow python <skill>/scripts/build_v5.py plan.json                      # render (~1 GB peak RSS)
bash <skill>/scripts/master.sh $PWD/out.mp4 -13.7 -6.0      # ceiling -6.0, NOT the default -4.5 (see pitfalls)
ffmpeg -y -v error -i out.mp4 -c copy -movflags +faststart o.mp4 && mv o.mp4 out.mp4
```
The plan.json schema is in the build_v5.py docstring. A working plan has these parts:
- **segs:** 10 segs on one trailer. Segs 0/1/3/5/7/9 are `hero`, the rest are `window`. Hero count
  should be ≤3 next time.
- **timing:** `dur` 20.0.
- **release pill:** `release_date` gives `OUT NOW` (0–2.4 s).
- **caps:** one cap per VO phrase, starting at that phrase's start time.
- **cta:** `{"text": "Link below!", "lead": 0.15}`.
- **logo:** `{"png": "logo.png", "start": 0, "end": 1.5, "w": 300, "y": 40}`.
- **tail:** `loop_tail` 0.3, `grade` [1.18, 1.15, 1.04].
- **audio:** `music_gain` 0.75, `vo_gain` 1.25.
- **beats:** `{"json": "work/beats_all.json", "window": 0.25, "cut_guard": 0.25}`.
Minimal plan that passed `--check` (no beats, no release pill, no logo, header-only `vtt` for a no-speech source): omit `beats`, `release_date`/`release_pill` and `logo`; set every seg `snap:false`; `dur` = sum of the segs.
`--check` hard-fails on:
- seg audio outside a no-speech gap
- overlapping pills
- a pill longer than 2 words, non-ASCII, or price-like
- a CTA outside the last seg

## Gates measured (demo, Gemini VO)
- **ffprobe:** 20.000 s, 600 frames, 30/1, High/yuv420p/L4.0, a_dur == v_dur, faststart.
- **Duck-only delta:** 8.47 dB (≥6 ✅). Mastered I = −14.3 LUFS, max −4.0 dB ✅.
- **sub_linecheck:** PASS. Run it against `subs_v5.ass` copied as `subs.ass`, because the builder
  rewrites margins into `subs_v5.ass`. Marks/tails bridging two lines into one band now pass inside
  linecheck itself (`OK (marks bridge 2 lines, bodies Npx apart)`); `bodies <16px apart` = a real collision
  → fix the sub text.
- **Vision sheet (8 frames):** no price/QR/shop, no tofu, no black bars, flash not harsh.
- **Duck-only render for the delta gate:** run `uv run --with numpy python <skill>/scripts/duck_stem_gate.py`
  from the workdir — it implements the whole graph below (reads music_gain/vo_gain from plan.json, VO windows
  from `work/timeline_v5.json`, re-renders both wavs after every build, exit 0 = min delta ≥6 dB); building
  the graph by hand is the fallback. build_v5 exports its stems at `work/music_v5.wav`,
  `work/sfx_v5.wav`, `work/vo_v5.wav` — but RAW, before the gains (changing `music_gain` leaves
  `music_v5.wav` unchanged), so the gate graph must re-apply them exactly as build does:
  `[0]music + [1]sfx amix → volume={music_gain} → pre`; `[2]vo → volume={vo_gain},apad=whole_dur=DUR`
  split into the mix branch and a `pan=mono|c0=0.5*c0+0.5*c1` key; `pre`+`key` through
  `sidechaincompress=threshold=0.04:ratio=4:attack=15:release=500` → `gduck`.
  Render `gduck` ALONE (drop the VO amix, end `[gduck]apad`) = duck-only; render `gduck + voa` =
  the premaster mix. **delta = RMS(premaster) − RMS(duck-only) over the VO windows, must be ≥6 dB.**
  Two graph details that otherwise kill the command: build_v5's audio graph indexes inputs
  `[1]`=music `[2]`=vo `[3]`=sfx, so a standalone run needs a throwaway `-i` at slot 0; and in the
  duck-only render `asplit`'s `[voa]` pad has no consumer, which makes ffmpeg exit with
  `Error binding filtergraph inputs/outputs` until you terminate it with `;[voa]anullsink`.
  `amix` there is `normalize=0`, so the premaster is a plain sum of gduck + voa.
  Operational rules for this gate (each one cost a silent wrong result):
  - Use `ffmpeg -y` on the duck-only output. Without it ffmpeg prompts `Overwrite? [y/N]`, exits, and the old wav is read as if fresh.
  - Regenerate duck-only after every build; the music stem changes whenever the plan changes.
  - **A FAIL is a gain problem before it is a graph problem.** `duck_stem_gate.py` re-applies `music_gain` /
    `vo_gain` from plan.json over the unchanged raw stems, so a gain-only change can be re-measured WITHOUT a
    rebuild (seconds) — the build must still be re-run before shipping, because build_v5 bakes the gains in.
    Levers: lower `music_gain`, raise `vo_gain`. The window that fails is normally the FIRST phrase, since the
    cold open carries the loudest music — or the LAST (CTA) window when the end card's audio is cut from the
    trailer's climax music. Either way size the nudge from THAT window's number, not from the average.
    **Sweep the two knobs instead of sizing one nudge:** the gate re-renders from the raw stems in ~1 s, so loop
    `music_gain`/`vo_gain` pairs in plan.json, re-run the gate, and take the MILDEST pair whose MIN delta clears 6
    with ≥1.5 dB of margin — a first swing of "music halved, VO doubled" passes but buries the music under the
    voice. Do NOT compute the swing from the failing delta: `vo_gain` also drives the sidechain KEY, so raising it
    deepens the duck as well as lifting the voice, and delta moves faster than a static ratio predicts (a 2.2 dB
    window passed at 0.75→0.5 / 1.25→1.75). Measure each pair; rebuild once with the winner.
  - The NAS `python3` has no numpy: run the delta reader with `uv run --with numpy python <file>.py`, and write that reader as a file (a heredoc that references a multi-MB wav trips the lifecycle guard).
  Compare RMS over the VO-phrase windows in `work/timeline_v5.json`.
  Both numbers must be pre-master — master's gain scales them equally so the ratio is unchanged,
  but comparing a POST-master `out` against an un-scaled duck stem under-reads by
  20·log10(music_gain) and reports a false FAIL (music 0.5 → 5.3 dB measured vs 9.7 dB true).
  Fallback: `scripts/duck_gate.py` rebuilds the music from master with `--segs` (omits seam SFX).
- **Loop check:** mean abs diff of the last frame vs frame 0 should be small (~8–12), much lower
  than t−0.5 s vs frame 0 (~65–70).

## Pitfalls
- **Master v5 with ceiling `-6.0`; the ceiling is a TARGET, not a guarantee.** With the default −4.5
  the impact SFX transients push the decoded peak to −2.8 dB, which fails the "max < −3" gate.
  **`master.sh` measures and prints the peak of its own finished AAC file (the faststart remux is
  `-c copy` and does not change audio), but that peak can still land 3–4 dB ABOVE the ceiling passed
  (−6.0 → −2.76 in one run, −6.0 → −1.9 in another) — the printed max IS the number to gate on.**
  If it is ≥ −3: re-run `master.sh` once with the SAME ceiling first (the second pass re-measures
  `I_before` and has passed where the first failed), then step the ceiling down 1 dB at a time.
  Ceiling is a master-only knob: master + remux, no rebuild, no credits. Then re-measure on
  `final.mp4` after `graphics_layer` — it re-encodes the audio through its own limiter.
- **VO deadline = `dur − 1.5`.** The Gemini VO is longer (18.36 s), so dur 20.0 is needed.
  The last seg absorbs the remainder.
- **Run heavy jobs ONE AT A TIME on this NAS.**
  - Free RAM is only ~4.5 GB and swap is already full.
  - Three parallel subagents (whisper medium + Python frame pipelines + ffmpeg) OOM-killed the
    Hermes gateway on 2026-11-05.
  - The build itself peaks at ~1.1 GB; gates peak at ~0.3 GB.
- **Hero seg audio mapping.** A `trailer` hero seg takes its audio from `audio_src: master` at `audio_in` (master time). Leaving `audio_in` out makes it default to the absolute trailer time, which is past the end of a short master and silently mis-gates the audio check.
- **Each window seg is one push-in shot.** Split a long no-speech gap into two or three window segs (5–6 s each) rather than one 11 s window; a single long push-in reads as a slow static shot.
- **`dur` must equal the sum of the seg durations** (the last seg absorbs any remainder). Five segs of 1.6 + 5.7 + 5.8 + 1.4 + 5.5 = 20.0 passed `--check` with no beat snapping (`snap:false` on all).
- **Output bitrate is high** (13.5 MB / 20 s). That is fine for Shopee and Telegram (<50 MB).
  If size matters, raise the crf in build_v5.py.
