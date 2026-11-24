# Scene plate (Flow image model) — EXPERIMENT, not in the router yet

Fix 2026-11-24: "ทำไมไม่ generate จาก google flow ที่ gen รูปภาพ (nano banana) … หลาย scene ของในฉากจะได้เหมือนเดิม".
Run it only as the A/B below, with Fix's go, until he approves it for real orders.

## What a plate is — and what it never is
- **A plate = the character + the set, no product.** One 9:16 image from Flow's image model: the roster
  character (her portrait chip) in the room the board describes, hands empty or resting, text-free (style card
  rules). It becomes the START FRAME of shot 1 (and of any shot whose previous last frame is unusable:
  `clipjob.py startframe` skips a hands-only frame), so the room, light and her look hold across shots.
- **Never a product image.** Not a "clean-up", upscale, new angle or white-background redraw of the product:
  the image model redraws screens, buttons, prints and labels (the drift `idcheck`/`chipcheck`/frame-check
  exist to catch), and the buyer gets the real item. The product reaches Flow only as the REAL photo chip; a
  small or busy ref is still fixed by asking Fix for a listing detail photo (`product-image-prep.md`).
- The identity references stay real: `idcheck` / `chipcheck` / `--identity` compare against the real product
  photo and the character portrait, never against the plate.

## Making it (🤖, or a prompt in the 📝 pack)
1. Flow Settings panel → Image (not Video), 9:16. **Read `Generating will use N credits` before the first
   one and write the figure into `house-rules.md` → Credits** (unmeasured as of 2026-11-24; do not assume free).
2. Chips: the character only. Prompt = the board's continuity block (set, light, wardrobe) + "hands empty,
   no product, no text, no logo, no screen content".
3. Gate before use (0–1 vision): `facecheck.py` finds her face; `chipcheck.py --expect <portrait>` on the
   chip; ONE vision read only when the face is unclear. No text in the image (`cover_check.py` price rules on it).
4. Attach as the start frame of shot 1 exactly as `ingest` attaches a last frame (`flow-steps.md`).

## A/B before adoption (needs Fix's go: the video half costs credits)
- Job: re-run **huawei-watchfit5** (2×10 s, ref 437 px, shipped 11-23) shot 1+2 with the same approved prompts,
  plate as shot-1 start frame. ≈60 cr video + the plate's own cost. Nothing is delivered from it.
- Compare A (shipped) vs B on the same frame sheet: her face vs portrait (`idcheck`), room/light match shot 1↔2,
  product drift (`frame-check.md` checklist: case shape, strap, screen), Fix's eye.
- Adopt only if B is no worse on product drift and better on set/identity; then link this file from router
  step 6 and the storyboard credit lines.
