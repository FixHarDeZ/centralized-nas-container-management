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
4. Gate (0–1 vision): 🧑 `facecheck.py <plate.jpg>` — the image path is its ONLY argument; a second one (a
   `--portrait` flag, `--help`) makes it return `{"error": "unreadable image"}` and exit 2. On a full-body
   plate Haar normally answers `{"face": false, "hits": []}` because her face is a few dozen px, so budget the
   ONE vision read as the normal path, not the exception: in that single call confirm the face is hers AND that
   there is no text / logo / screen content / product. Fails = skip the plate (normal shot 1), no second plate.
5. **Return to the project root FIRST, then Settings trigger → Video tab.** Generating the plate opens its own
   `/edit/<id>`, and that page's Settings trigger is the IMAGE editor's own panel (crop / model, no Image/Video
   tabs) — clicking a tab there is a no-op. `goto_url` the project root (the box comes back empty with 0 chips:
   retype the shot prompt and re-attach after the switch), then switch tabs and check the credit line equals
   `clipjob.py cost` for shot 1 before `reserve`. Submitting from the Image tab makes a picture, not the shot.
6. Shot 1 chips = the plate (from the project's media in the picker) + the product ref; 🧑 drops the
   character chip (her face is in the plate, as with a chained start frame). `chipcheck.py --expect
   <workdir>/plate.jpg` on the plate chip.

- **A policy refusal with the plate attached:** drop the plate, run shot 1 the normal way, log `plate: refused`. The plate is never what a refusal is debugged on (`flow-driver/references/pitfalls.md` → Policy refusal order covers the shot itself).

## The gate (2026-11-25)
cal-d-protein-1mo was the trial order and the plate was skipped without a word. `clipjob.py reserve` now refuses
shot 1 of a 🤖 🧑/✋ job until a verdict is recorded: `clipjob.py plate <job> used` (needs `<workdir>/plate.jpg`)
or `clipjob.py plate <job> skipped|refused --why "<Image tab read N credits / face gate failed / refusal>"`.
The gate stops once one delivered job used a plate (Fix's verdict decides the rest); the clip-log row carries
`plate`. `CLIPJOB_PLATE_TRIAL=0` switches it off.
- **Ordering:** `clipjob.py plate` and `clipjob.py production` both REFUSE while the job is still at `intake`
  (`run clipjob.py new … after Fix approves the board`) — record them right after `new`, in that sequence:
  `new` → `production` → `plate` → `note`.
- **When the session's vision budget is already spent, skip the plate instead of gating it half-blind:** the
  gate's ONE read (face + no text/logo/product) cannot be substituted cheaply, so run
  `plate <job> skipped --why "vision budget spent — plate gate needs its read"` and shoot shot 1 the normal way
  (character chip + refs). A skipped plate costs nothing and is reported like any other skip.
- **A single-shot clip has nothing for the plate to protect** — holding set, light and face is the whole point,
  and it only pays across shots; a 🧑 plate also puts the character's face into an ATTACHED start frame, the same
  person-bearing image class that has already refused a submission. Put the trial decision in the approval
  clarify as its own 0-credit question instead of deciding alone, then record `plate <job> skipped --why
  "<his choice> — 1 shot, no cross-shot continuity to protect"` (or `used` when he picks ลอง). The verdict still
  goes in after `new` → `production`, before `reserve`.

## Report it
- Clip-log `--notes`: `plate: used|skipped|refused (<why>)`.
- Delivery message, one line: plate used or skipped, and what to compare (her face shot 1↔2, room/light,
  product drift). Fix's verdict decides adoption; then link this file from router step 9 and drop "TRIAL".
