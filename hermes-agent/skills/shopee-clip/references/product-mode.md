# 📦 graphic ล้วน: Flow product b-roll with no person, plus gameplay-style VO and graphics

> ✋ hands mode reuses this file for the voiceover, build and graphics; its own shot rules are in `hands-mode.md`.

Fix 2026-11-10: the voice copies the gameplay recipe ("ลอกแนวเสียงจากคลิปแนว gameplay ได้เลย อันนั้นเทสมาแล้ว").

## Shots (Flow)
- 📦: no person and no hands: hero turntable, macro or texture, the product in use by itself (pouring, opening,
  lighting up), and a lifestyle set dressing.
- Every prompt carries **"no speech, no voiceover, no music — natural ambient sound only"**. The VO is added in
  post, and Flow speech would fight it. Add the no-on-screen-text block from `presenter-post.md`.
- A 📦 prompt has NO `Audio (Thai voiceover):` line, and `ctarule.py` then falls back to scanning the WHOLE file
  for link words — keep every CTA word (ลิงก์ / ใต้คลิป / พิกัด / ตะกร้า / link) out of the entire prompt, not
  just out of a voiceover line, or `pack` refuses the shot before anything is spent.
- Use the reference photo as the Ingredient on every shot, the same as 🧑. The product must not drift
  between shots. Check it in each shot's frame verdict.
- Shots are 3–10 s (one Omni 1.2 Flash generation, `--seconds`; 3 credits/s, so no spare seconds beyond the VO need). Plan ~1–2 s more footage than the VO needs (`fit()` holds the last frame when the
  footage is short, and flags a hold >2 s).

## Voiceover = the gameplay recipe
- **The script comes from the approved board, not from the shots — write the plan and generate the take WHILE
  the shots are still rendering or waiting on Fix's ✅** (it costs Gemini quota, never Flow credits, and needs
  no mp4 in the workdir). Do the ASR phrase-by-phrase check in the same window, so when the last shot lands the
  only work left is `assemble-check` → build. Waiting idle on the review reply and then starting a 10-min VO
  chain is the avoidable half of a long tail.
- Write the plan for `gameplay-clips/scripts/gen_vo_natural.py` exactly as `gameplay-clips/references/natural-vo.md`
  says: engine `gemini`, voice `Leda`, style "cheerful, casual, like telling a friend", spoken Thai with
  particles, numbers as words in `say`, uneven gaps, and edge `rate/pitch` on every phrase for the fallback.
- **Keep each `sub` line ≤ ~35 Thai chars** (Itim 48 in the 620 px sub width: 36 chars render on one row, 43
  wrapped to a 3rd). A third row grows the block upward out of the sub band over the product — split the words
  across the two lines differently; the `say` can stay as long as the pacing needs.
- `vo_end` must land in `DUR−3 … DUR−1.6`. Fit it from stdout as the gameplay skill does (`--from-take`
  costs 0 requests).
- **Size the script to that window BEFORE the first take.** On a 10 s clip the window is 1.4 s wide, and
  Gemini's real rate runs under the char-rate estimate (the first phrase often lands ~7–9 ch/s), so a 5–6
  phrase script overshoots by seconds and `--from-take` cannot buy it back (tempo ≤1.07 +
  `max_inner_pause` save under 1 s). Keep a 10 s script to ~4 phrases ≈ 60–65 Thai chars; when `vo_end`
  overshoots by more than ~1.5 s, cut phrases and take a NEW take — re-timing cannot fix it.
- ASR the take with `gameplay-clips/scripts/asr_th.py` and compare it phrase by phrase with the script before
  building — **then compare the TIMING as well as the words**: each `subs.ass` Dialogue window must overlap the
  ASR span of its own phrase. ps2-hdd-175 (2026-11-24) cut phrase 1 at 1.38 s (spoken to 3.55 s) because the
  boundary estimate counted Whisper's digits ("175") against the `say` line's Thai number words; `vo_split`
  now counts both as spoken (`thainum.py`) and that take re-cuts at 3.50 / 4.97 / 9.39 by itself. A window
  that still misses its span (stdout `ch/s` twice the median is the quick tell): re-cut from word-level
  timestamps (`word_timestamps=True`; segment ends hide the cut), edit BOTH `subs.ass` and
  `subs.timeline.json` (`product_build` reads `vo_end` from the timeline) and pass them as prebuilt files —
  `--from-take` re-derives the same split.
- **Hand THAT take to the build:** `plan.json` with `"vo": "vo_plan.json"` re-rolls a FRESH Gemini take, so
  the ASR'd take is discarded and an unverified one ships. Two ways out, both keeping the verified audio:
  add `"from_take": "<the saved take.wav>"` (the build re-times THAT take from the plan — 0 requests, no
  file juggling), or copy the verified files to distinct names and point the plan at the prebuilt keys
  (`vo_mp3`/`vo_ass` + the `.timeline.json` beside the ass — never at the workdir's own paths: that branch
  copies source→workdir and raises `SameFileError`).
- The CTA phrase goes last. No price, as always.

## Build
```
uv run --with edge-tts --with faster-whisper --with numpy \
  python /opt/data/skills/shopee-clip/scripts/product_build.py plan.json --workdir <workdir>
```
`plan.json`: `{"shots": [<assemble-check files>], "vo": "vo_plan.json", "pills": [...], "xfade": 0.25}`.
- **`tail` sets the shipped length: the clip ends at `vo_end + tail` (capped by the stitched footage), so set it
  to `<ordered seconds> − vo_end`, never a default.** A default 1.6 s under-shoots any order whose VO ends early
  (7.8 + 1.6 = 9.4 s shipped against a 10 วิ order): read `v_dur` off the build stdout and rebuild with a bigger
  `tail` — a rebuild costs ~1 min and 0 credits — while keeping the empty music tail after the VO at ≤3 s (the
  `vo_end ≥ DUR−3` window is the same constraint seen from the VO side).
- A VO already built in the workdir goes in prebuilt (`"vo_mp3"`/`"vo_ass"` + the `.timeline.json` beside
  the ass), but never point them at the workdir's own files: the prebuilt branch copies source→workdir and
  raises `SameFileError` on the same path. Copy to distinct names first (`vo_src.mp3`, `subs_src.ass`,
  `subs_src.timeline.json`) and point the plan at those.
- The bed is Flow's ambient audio at 0.75, ducked under the VO with the gameplay sidechain. Subs use the
  Itim house style from the VO timeline (known text, no ASR timing). Pills are drawn at y=210.
- An edge fallback applies the warm EQ automatically and adds a `notes` line. Tell Fix that voice A was used.
- `report.json` has `flags`, and `deliver` refuses while any flag stands.
- The VO pause gate scales with length (`vo_gates.gap_need`: one gap >0.25 s per 5 s of VO, so 2 on a 10 s
  clip, 4 on 20 s). `VO GATE WARN: N gaps > 0.25s, need M …` is therefore real: widen a `gap_after` to ≥0.30
  via `--from-take` (0 requests) before asking Fix. Never re-cut a verified VO just to silence it.
- `graphics_layer.py out.mp4 gfx.json final.mp4 --report <workdir>/report.json --check` runs the layout
  check only and exits without writing the output — render with the same command minus `--check`.
- **`deliver` refuses an empty graphics plan on any Flow-mode clip** (`graphics plan is empty — graphics are
  mandatory`), and `gfx_elements` counts only `headlines` / `stickers` / `callouts` / `badges` / `endcard` /
  `image_stickers` — the `cover` (watermark) element does NOT count. So "that shot ships without a headline"
  still leaves ≥1 element owed across the clip: when no measured window in ANY shot is clear, put a `sticker`
  in a spot you measured clear yourself rather than shipping an empty plan into `deliver`.
- **`--check` gives plain `stickers` no safety net**: `layout_check` builds its item list from headlines,
  callouts, badges and image_stickers only, so a sticker is never tested against `avoid`, the sub band or the
  pill band — verify its rect by hand from the same measurements before rendering. To decide whether a
  `cover` element is needed at all, crop the four corners of two frames into one sheet and ask whether any
  watermark is burned in.
- **`layout_probe.py` does not fit here.** It looks for a face and a pastel studio wall. For b-roll, use
  `headlines` / `stickers` / `badges` / `endcard`. Keep the subtitle band (y 700–835) and the pill band
  (y 186–262) clear, as the layout check enforces.
- **The check validates only against the `avoid` boxes you supply — measure them, never estimate them:**
  - Read geometry from FULL-res frames with a drawn grid (100 px lines + coordinate labels + the candidate
    text rect drawn onto the frame). A 50 % contact sheet lies about geometry: its boxes come back in mixed
    coordinate spaces, Thai overlay text misreads, and a spot it calls "clear wall" can be the product
    running straight through the text area.
  - When the product has a detectable hue, skip the grid+vision round and use the pixel probe in
    `frame-check.md` → Locating a crop: a strict mask with a per-row count floor returns the product's top
    per frame in one PIL pass, and that number is exactly what the `avoid` top needs (a grid read's y came
    back wrong even with coordinate labels). **Print the per-row profile before trusting `rows[0]`:** a warm
    mask over a warm-lit set also matches the wall and the shadows, so the first hit is background — the
    product top is the first row of the SUSTAINED block, and the clear text band is the run of zero-count
    rows above it (that run is where a headline actually fits).
  - Pre-measure a headline BEFORE writing gfx.json: `ImageFont.truetype(Itim, size).getlength(text) + 12`
    must fit the safe box (x80–592 = 512 px) — a full product name at size 58 overflows and `--check` fails
    on the first run; drop the size (40–46) or split into two lines first.
  - Sample every intended text window at start/mid/end. Framing changes WITHIN a shot (wide → close-up →
    pull back; a late camera move lifts the product rim into a top band that was clear seconds earlier), so
    time-slice each `avoid` rect to the segment its measurement covers — one rect spanning the whole shot
    either blocks all placement or silently stops protecting anything.
  - Pick windows where the measured product top sits below the text rect (and the rect leaves the pill band
    while a pill shows), then let `--check` confirm the arithmetic.
  - **A product that fills the frame leaves ONE legal text band, so a headline and a pill cannot share that beat.**
    A close-up measuring its top at ~235–275 px leaves only y192–262 clear (the pill band — and only while no pill
    shows; the sub band 700–835 is blocked while subs show, the safe box ends at y832). Stagger the windows instead:
    headline in a window where no pill is showing, the pill after it — and keep the pill's window where the measured
    product top is >262, or the pill visibly sits on the product. Planning both over the same shot only gets settled
    by `--check` failing, which costs a rebuild rather than a re-plan.
  - After render, re-verify each headline on a grid frame plus a ~3× full-res crop of its y-band checked
    glyph-by-glyph against the plan string (`frame-check.md`); when a sheet read and a crop read disagree,
    the targeted full-res crop wins.
  - The same rule covers text printed ON the product: a coarse sheet read that quotes a capacity number or
    a serial has inferred it, not read it — settle it with a ~3× crop of the label before treating it as a
    no-capacity violation, since text the eye cannot read must not become a claim, and text printed on the
    product is excluded by the style card anyway.
- The board's "punch-in at the money moment" has NO implementation in this chain (graphics_layer has no
  zoom effect): substitute a sticker (arrow/sparkle, `anim: pop`) aimed at the money moment and name the
  substitution in the delivery.
- When the product fills the frame and no window satisfies "product top sits below the text rect", pick the
  headline band by drawing two candidate rects on a full-res frame for ONE vision read (e.g. top over
  decorative parts vs bottom over functional parts) and take the verdict's choice; then set the `avoid` top
  from graphics_layer's own rect math — `y + size×1.3 + 12` — because `--check` measures the headline
  with that padding and fails on the few px an eyeballed rect misses.
- Proven end-to-end through deliver on the first real hands run (build → 2 headlines placed by the method
  above → cover) and on a pure 📦 clip with no hands (VO → build → sticker + headline → poster cover →
  deliver).
