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
- The bed is Flow's ambient audio at 0.75, ducked under the VO with the gameplay sidechain. Subs use the
  Itim house style from the VO timeline (known text, no ASR timing). Pills are drawn at y=210.
- An edge fallback applies the warm EQ automatically and adds a `notes` line. Tell Fix that voice A was used.
- `report.json` has `flags`, and `deliver` refuses while any flag stands.

## Graphics (mandatory)
- Run `graphics_layer.py out.mp4 gfx.json final.mp4 --report <workdir>/report.json --check`, then render.
- **`layout_probe.py` does not fit here.** It looks for a face and a pastel studio wall. For b-roll, vision-read
  2–3 frames per shot, put the product's box into `avoid` (so text never covers it), and use `headlines` /
  `stickers` / `badges` / `endcard`. Keep the subtitle band (y 700–835) and the pill band (y 186–262) clear,
  as the layout check enforces.
- Not yet proven on a real 📦 clip (2026-11-10). After the first real run, write down what worked here.
