# ✋ hands: hands + product, try-it-and-explain, no face

Fix 2026-11-13: the faceless demo other affiliate channels run (only hands and the product on screen, the
product is tried while a voice explains). `clipjob.py new --mode hands`; clip-log `style` = `hands`.

**It is the 📦 pipeline with hands in frame.** Follow `product-mode.md` for the voiceover, the build
(`product_build.py`) and the graphics. Only the differences are listed here.

## Shots (Flow)
- Framing: wrists down only. POV (the user's own eye line) or top-down over a table. One pair of hands,
  the same skin tone, sleeves and nails in every shot (write them into the continuity block).
- **The camera is too close for a body to fit.** Every beat with a hand is a close-up or top-down within
  arm's length: the frame holds the hand, the part of the product it touches and nothing wider. Write the
  camera into each beat ("extreme close-up, camera 30 cm from the tray", "top-down, only the table top in
  frame") and add "both hands enter from the BOTTOM edge of the frame, nothing enters from the left or right
  edge". Asking only for "no face" in a wide shot failed: the first ✋ job (aimi-rack, 2026-11-13) got a
  woman's face in profile at the left edge for under 1 s, both forearms and a shoulder.
- **A product too big for a close-up (floor rack, shelf, cabinet) is shown whole only in beats with NO
  person at all** (an empty establishing or result shot). Hands appear only in the close-up beats. Never
  write "the rack kept whole in frame" on a beat that also has hands.
- **No face, no head, no body, no mirror or screen reflection of a person**, in any frame. No character
  chip is attached (`--character` is not used).
- Every prompt carries the 📦 audio line (**no speech, no voiceover, no music, natural ambient sound
  only**) and the no-on-screen-text block from `presenter-post.md`. The voice is added in post, so there is
  no lip-sync and no Flow speech to check.
- The reference photo is the Ingredient on every shot. Shots after the first chain from the previous
  shot's last frame, as in 🧑/📦, and their prompt repeats the continuity block: the SAME room, wall, floor
  and light, and the same load state of the product (what stands on which tier). A beat that needs another
  state (empty rack for a drainage demo) is written as an action inside the shot (the hand lifts the items
  off), never as a new scene. In aimi-rack shot 2 came back as another room with the rack empty.
- Props carry no label: "plain unbranded bottles, no text on any prop". Flow printed the product's brand
  name on a skincare tube.

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
**`clipjob.py scan <job> K --raw <file>` first; `ready` refuses a ✋ shot without it.** It writes
`shotK_scan1.jpg …` (one frame every 0.5 s, 10 tiles per sheet, tile n of sheet m = second
`((m−1)·10 + n − 1)/2`). Read EVERY sheet, one `vision_analyze` per sheet, with the question the command
prints, and look at the tile edges: three sampled frames missed a face that was on screen for under a second.
Any one of these is `--frame flag:<what>`:
- an arm shown above the forearm, a shoulder, hair or clothing of a body;
- text or a brand name drawn on a prop;
- the room or the product's load state differs from the previous shot;
- a face, head, hair, shoulder, torso or a second person leaks in, even for one tile (a bare foot or knee
  at the floor edge is a NOTE, not a flag: report it with its time);
- wrong finger count, fused or extra fingers, a hand passing through the product;
- product scale against the hand differs from the reference or from the previous shot;
- product shape, colour, logo or parts differ from the reference photo;
- the planned action did not happen (the hand only hovers), or the product is switched to another state
  with no action (state teleport).

## Graphics
- `layout_probe.py` does not fit (no face, no studio wall): vision-read 2–3 frames per shot, as in 📦 —
  but take placement geometry the way `product-mode.md` → Graphics says (grid-frames, never sheet estimates).
- The `avoid` box covers the product's WHOLE motion path in that shot, plus the hands: a union of
  per-window measurements, time-sliced where the framing changes (a close-up puts a support pole through
  the centre of the frame; a late camera rise lifts the rim into the top band) — not one frame's box.
- Fewer elements than 📦: the frame is already busy. One headline per shot, pills on the selling points.
  Where no measured window keeps the text off product and hands, that shot ships without a headline —
  "text never covers the product" outranks the headline count.

## Status — first real ✋ run (`aimi-rack-20261113`, 2 shots, 30 credits, delivered)
- **Actions that held a rigid rack's shape:** pushing a floor rack into a corner, setting a bottle onto a
  tier, an index finger pressing a caster lock (close-up), pouring water onto the top tray, hands on the
  top rim gliding it, the final point-down. Tier count, colour and scale stayed exact against the
  reference. The redraw warning still goes in the storyboard message.
- **The weak beat is the static one.** A frame where the hands only rest reads as filler: keep every beat
  an ACTION and let the previous action's result carry the in-between frames.
- A product that stands on the floor takes a body anchor as its size cue ("top tray at mid-thigh"), not
  "fits in the palm".
- The VO/build/graphics chain of 📦 worked with flags 0.
- **Faults the 3-frame check passed** (the run's own notes said "no face in any sampled frame"; a later
  0.4 s sampling of the raw shots showed otherwise): a woman's face in profile at the left edge of shot 1
  (~3.6–4.4 s), arms to the shoulder from both sides, shot 2 in another room with the rack empty, the brand
  name printed on a skincare tube. The scan gate, the close-framing rule and the continuity rule above
  answer these and are not yet proven on a real order.
