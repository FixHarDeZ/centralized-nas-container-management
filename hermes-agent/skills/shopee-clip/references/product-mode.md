# 📦 graphic ล้วน: Flow product b-roll with no person, plus gameplay-style VO and graphics

> ✋ hands mode reuses this file for the voiceover, build and graphics; its own shot rules are in `hands-mode.md`.

Fix 2026-11-10: the voice copies the gameplay recipe ("ลอกแนวเสียงจากคลิปแนว gameplay ได้เลย อันนั้นเทสมาแล้ว").

## Shots (Flow)
- 📦: no person and no hands: hero turntable, macro or texture, the product in use by itself (pouring, opening,
  lighting up), and a lifestyle set dressing.
- Every prompt carries **"no speech, no voiceover, no music — natural ambient sound only"**. The VO is added in
  post, and Flow speech would fight it. Add the no-on-screen-text block from `presenter-post.md`.
- Use the reference photo as the Ingredient on every shot, the same as 🧑. The product must not drift
  between shots. Check it in each shot's frame verdict.
- Shots are 10 s (one Omni 1.1 Flash generation). Plan ~1–2 s more footage than the VO needs (`fit()` holds the last frame when the
  footage is short, and flags a hold >2 s).

## Voiceover = the gameplay recipe
- Write the plan for `gameplay-clips/scripts/gen_vo_natural.py` exactly as `gameplay-clips/references/natural-vo.md`
  says: engine `gemini`, voice `Leda`, style "cheerful, casual, like telling a friend", spoken Thai with
  particles, numbers as words in `say`, uneven gaps, and edge `rate/pitch` on every phrase for the fallback.
- `vo_end` must land in `DUR−3 … DUR−1.6`. Fit it from stdout as the gameplay skill does (`--from-take`
  costs 0 requests).
- ASR the take with `gameplay-clips/scripts/asr_th.py` and compare it phrase by phrase with the script before
  building.
- The CTA phrase goes last. No price, as always.

## Build
```
uv run --with edge-tts --with faster-whisper --with numpy \
  python /opt/data/skills/shopee-clip/scripts/product_build.py plan.json --workdir <workdir>
```
`plan.json`: `{"shots": [<assemble-check files>], "vo": "vo_plan.json", "pills": [...], "xfade": 0.25}`.
- A VO already built in the workdir goes in prebuilt (`"vo_mp3"`/`"vo_ass"` + the `.timeline.json` beside
  the ass), but never point them at the workdir's own files: the prebuilt branch copies source→workdir and
  raises `SameFileError` on the same path. Copy to distinct names first (`vo_src.mp3`, `subs_src.ass`,
  `subs_src.timeline.json`) and point the plan at those.
- The bed is Flow's ambient audio at 0.75, ducked under the VO with the gameplay sidechain. Subs use the
  Itim house style from the VO timeline (known text, no ASR timing). Pills are drawn at y=210.
- An edge fallback applies the warm EQ automatically and adds a `notes` line. Tell Fix that voice A was used.
- `report.json` has `flags`, and `deliver` refuses while any flag stands.

## Graphics (mandatory)
- `graphics_layer.py out.mp4 gfx.json final.mp4 --report <workdir>/report.json --check` runs the layout
  check only and exits without writing the output — render with the same command minus `--check`.
- **`layout_probe.py` does not fit here.** It looks for a face and a pastel studio wall. For b-roll, use
  `headlines` / `stickers` / `badges` / `endcard`. Keep the subtitle band (y 700–835) and the pill band
  (y 186–262) clear, as the layout check enforces.
- **The check validates only against the `avoid` boxes you supply — measure them, never estimate them:**
  - Read geometry from FULL-res frames with a drawn grid (100 px lines + coordinate labels + the candidate
    text rect drawn onto the frame). A 50 % contact sheet lies about geometry: its boxes come back in mixed
    coordinate spaces, Thai overlay text misreads, and a spot it calls "clear wall" can be the product
    running straight through the text area.
  - Sample every intended text window at start/mid/end. Framing changes WITHIN a shot (wide → close-up →
    pull back; a late camera move lifts the product rim into a top band that was clear seconds earlier), so
    time-slice each `avoid` rect to the segment its measurement covers — one rect spanning the whole shot
    either blocks all placement or silently stops protecting anything.
  - Pick windows where the measured product top sits below the text rect (and the rect leaves the pill band
    while a pill shows), then let `--check` confirm the arithmetic.
  - After render, re-verify each headline on a grid frame plus a ~3× full-res crop of its y-band checked
    glyph-by-glyph against the plan string (`frame-check.md`); when a sheet read and a crop read disagree,
    the targeted full-res crop wins.
- Proven end-to-end through deliver on the first real hands run (build → 2 headlines placed by the method
  above → cover); a pure 📦 clip with no hands has not run yet.
