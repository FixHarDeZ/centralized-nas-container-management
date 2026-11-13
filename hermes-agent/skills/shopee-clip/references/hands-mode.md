# ✋ hands: hands + product, try-it-and-explain, no face

Fix 2026-11-13: the faceless demo other affiliate channels run (only hands and the product on screen, the
product is tried while a voice explains). `clipjob.py new --mode hands`; clip-log `style` = `hands`.

**It is the 📦 pipeline with hands in frame.** Follow `product-mode.md` for the voiceover, the build
(`product_build.py`) and the graphics. Only the differences are listed here.

## Shots (Flow)
- Framing: wrists down only. POV (the user's own eye line) or top-down over a table. One pair of hands,
  the same skin tone, sleeves and nails in every shot (write them into the continuity block).
- **No face, no head, no body, no mirror or screen reflection of a person**, in any frame. No character
  chip is attached (`--character` is not used).
- Every prompt carries the 📦 audio line (**no speech, no voiceover, no music, natural ambient sound
  only**) and the no-on-screen-text block from `presenter-post.md`. The voice is added in post, so there is
  no lip-sync and no Flow speech to check.
- The reference photo is the Ingredient on every shot. Shots after the first chain from the previous
  shot's last frame, as in 🧑/📦.

## Storyboard = a demo, not an unboxing
- Beats show the product being USED: pick it up, switch it on, press/pour/wipe/attach, show the result.
  Shot 1 opens on the action already happening (the hook), the last beat puts the product down and the
  hand points down for the CTA.
- **One simple action per beat, slow, with the product kept whole in frame.** Flow redraws a rigid product
  when it is rotated, opened or partly covered. Prefer the hand touching or pointing beside the product
  over gripping across it; never cover the logo or the part the beat is about.
- Write the size cue into the prompt (the product against the hand: "fits in one palm", "taller than the
  hand"). Scale drift is the common fault of this style.
- A rigid product (rack, shelf, device) has the same redraw risk as 🧑 (2 of 2 jobs, 2026-11-10/11): say it in
  the storyboard message so Fix can still switch to 📦 or 🎬 at zero spend.

## Frame check, per shot (in addition to `frame-check.md`)
Any one of these is `--frame flag:<what>`:
- a face, head or a second person leaks in;
- wrong finger count, fused or extra fingers, a hand passing through the product;
- product scale against the hand differs from the reference or from the previous shot;
- product shape, colour, logo or parts differ from the reference photo;
- the planned action did not happen (the hand only hovers), or the product is switched to another state
  with no action (state teleport).

## Graphics
- `layout_probe.py` does not fit (no face, no studio wall): vision-read 2–3 frames per shot, as in 📦.
- The `avoid` box covers the product's WHOLE motion path in that shot, plus the hands, not one frame's box.
- Fewer elements than 📦: the frame is already busy. One headline per shot, pills on the selling points.

## Status
Not yet proven on a real clip (added 2026-11-13), and 📦 below it has not run a real clip either. After the
first ✋ order, write here what Flow did with the hands and which action types held the product shape.
