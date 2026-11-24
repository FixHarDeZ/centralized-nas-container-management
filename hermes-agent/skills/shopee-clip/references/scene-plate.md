# Scene plate (Flow image model) — TRIAL on the next 🤖 🧑 / ✋ job

Fix 2026-11-24: "ทำไมไม่ generate จาก google flow ที่ gen รูปภาพ (nano banana) … หลาย scene ของในฉากจะได้เหมือนเดิม".
Cost: **0 credits** (Fix read the Image tab's `Generating will use N credits` on 2026-11-24). No separate A/B
re-run: Fix's go is to try it on the NEXT real order ("ลองที่งานหน้า"). One job only; after delivery Fix decides
whether it stays. 📝 and 📦 jobs skip it.

## What a plate is — and what it never is
- **A plate = the set (+ the character in 🧑), no product.** One 9:16 image from Flow's image model: the roster
  character (her portrait chip) in the room the board describes, hands empty or resting; ✋ = the empty
  table / set only, no hands. Text-free (style card rules). It becomes the START FRAME of shot 1, and of any
  shot K≥2 whose `clipjob.py startframe` returns `file` null (instead of the bare character chip), so the
  room, light and her look hold across shots.
- **Never a product image.** Not a "clean-up", upscale, new angle or white-background redraw of the product:
  the image model redraws screens, buttons, prints and labels (the drift `idcheck`/`chipcheck`/frame-check
  exist to catch), and the buyer gets the real item. The product reaches Flow only as the REAL photo chip; a
  small or busy ref is still fixed by asking Fix for a listing detail photo (`product-image-prep.md`).
- The identity references stay real: `idcheck` / `chipcheck` / `--identity` compare against the real product
  photo and the character portrait, never against the plate.

## Making it (before `reserve` of shot 1)
1. Prompt bar `Settings trigger` → **Image** tab, 9:16. The line must read `Generating will use 0 credits`;
   any other figure = stop, skip the plate, one line to Fix with the figure.
2. Chips: 🧑 the character chip only; ✋ none. Prompt = the board's continuity block (set, light, wardrobe) +
   "hands empty, no product, no text, no logo, no screen content, 9:16".
3. Download it like a shot (`flow-browser-env.md` → Download) to `<workdir>/plate.jpg`.
4. Gate (0–1 vision): 🧑 `facecheck.py` finds her face; ONE vision read of the plate only when the face is
   unclear or to confirm no text / logo / screen content / product. Fails = skip the plate (normal shot 1),
   no second plate.
5. **Settings trigger → back to the Video tab** and check the credit line equals `clipjob.py cost` for shot 1
   before `reserve`. Submitting from the Image tab makes a picture, not the shot.
6. Shot 1 chips = the plate (from the project's media in the picker) + the product ref; 🧑 drops the
   character chip (her face is in the plate, as with a chained start frame). `chipcheck.py --expect
   <workdir>/plate.jpg` on the plate chip.

## Report it
- Clip-log `--notes`: `plate: used|skipped (<why>)`.
- Delivery message, one line: plate used or skipped, and what to compare (her face shot 1↔2, room/light,
  product drift). Fix's verdict decides adoption; then link this file from router step 9 and drop "TRIAL".
