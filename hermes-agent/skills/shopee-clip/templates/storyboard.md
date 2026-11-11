# Storyboard template (Fix 2026-11-09, mandatory before any Flow generation)

Why: two 10 s takes of "hold it up / press / set down" read as filler (vacuum-bag clip). Fix wants every shot to SHOW the product working.

## Rules
- Arc: problem -> product doing its job (step by step) -> result. Every shot = ONE visible action where the product performs its function. "Holds it up to camera" alone is not a shot.
- Source the beats from the listing's own how-to / feature / before-after images (gathered by `intake_images.py`). They are storyboard material even when they cannot be attached as references.
- Pace submits ≥5 min apart (Fix 2026-11-09, quality over speed), so a 5-shot board adds ~20 min of wall clock. Say so in the board.
- Shot length: a Flow generation is 10 s for 🧑 presenter boards (N = length / 10, router step 3). The 4-6 s
  mix below applies only to a 📦 graphic board with explicitly shorter shots. Cost: 10 s ≈ 15 cr (measured);
  4 s = 7 cr (measured); 6 s ≈ 10 cr (estimate, mark it as such).
- Mix shot types:
  - `P` presenter to camera (hook, reaction, result) - character chip attached, Flow voiceover.
  - `H` hands close-up doing the action (no face, NO character chip - also avoids the prominent-person refusal).
  - `R` result / before-after (product in place, wide).
- Voiceover line per shot must describe what is on screen in that shot. Count it: ~3.5-4.5 Thai syllables/s, speech >= 70 % of a talking shot. H shots may carry no speech (music + SFX, our sub/pill only).
- Plan the graphics v2 layer per shot: punch-in at the money moment, EN pill (<=2 words), product cutout, before/after card.
- Flag risky actions (zips, valves, fine finger work, text on product) and name a fallback shot.
- CTA: only on the final shot, and only if the clip is light (heavy-content clips skip it).
- No price, no unverified claims (%, seconds, certifications) in any line.

## Running an approved board
- Each shot is its own independent generation (Settings: Video, Ingredients, 9:16, 720p, the shot's seconds, x1). Shots are hard-cut in post, so they need no start-frame chaining. Repeat one continuity block (presenter look, backdrop, lighting) verbatim in every shot prompt.
- Chips per shot type: `H` = product crops only. `P`/`R` = product crops plus the character. Re-attach before each submit, because the box clears its chips on submit.
- A 4 s 720p shot rendered in about 40-120 s. Overlap the work: submit shot N+1, then QC shot N and send it for review. Do not chain past a shot that carries a defect you found yourself.
- Pace the submits. Firing the next one the moment each render lands tripped `unusual activity` by the fifth shot (`references/flow-browser-env.md`), so leave a gap between submits rather than a back-to-back burst.
- **Plan the CTA shot as the expendable one.** It is last in the queue, so it is the shot most likely to hit a rate-limited `Failed` card. If it fails after the one retry, offer two choices. (1) Wait 30 min or more, relaunch Chrome and retry once (credit cost in the text). (2) Ship the shots you have and put the CTA in the caption and basket (0 credits). Fix chose (2). Build option (2) with `NO_AUTO_CTA=1` so post does not add a `Link below!` pill.
- In the post plan, mark every speechless `H` shot `"silent": true` (`references/presenter-post.md`). Otherwise the script tries to align an empty voiceover and crashes.
- An `H` shot that lands on skin (blush on a cheek, cream on a hand) renders a stranger's face part because it has no character chip. "Cheek and jaw only, eyes out of frame" was ignored and the eye and brow showed. When the shot must stay faceless, frame it on the product plus fingertip. When it needs skin, make it a `P`/`R` shot with the character chip, so the face at least matches the presenter.
- For a R/result shot the voiceover lists, write each on-screen touch or prop state into the prompt as its own numbered action (open the compact, touch the cheek, then the eyelid, then the lips). A single sentence that bundles them lets the model skip some of them.
- **Lock the product's structure in every P/R prompt.** Flow fills a "shelf in a wardrobe" scene from its own prior and drifts the attached product (a single black unit came back as a wood wardrobe with two black tiers, one empty). Name the tier count and say "ONE single unit, no other shelving, no extra tiers, no wooden shelves in frame". The product must stay fully visible and un-occluded by clothes or the presenter in the frame check, or the shot is a defect and goes back for re-gen.

## Format sent to Fix (Telegram text, then STOP and wait)
```
🎬 Storyboard: <product> · <N> วิ · presenter <character>
แหล่งไอเดีย: รูป 2 (ก่อน-หลัง), รูป 7 (วิธีใช้ 4 ขั้น)

1. [P 4 วิ] <action> — พากย์: "..." — กราฟิก: pill "..."
2. [H 4 วิ] <action> — (ไม่มีเสียงพูด) — กราฟิก: zoom ...
3. ...

📊 สรุป: <N> ช็อต · รวม <T> วิ
- ช็อต 1: <s> วิ ≈ <c> เครดิต
- ช็อต 2: <s> วิ ≈ <c> เครดิต
- ...
💳 เครดิตรวม ≈ <sum> (ถ้าต้อง gen ช็อตเสี่ยงใหม่ 1 ครั้ง +<c>)
🔁 กด gen ทั้งหมด <N> ครั้ง (≥5 ครั้ง = ต้องเว้นระยะ ใช้เวลานานขึ้น)
⚠️ ช็อตเสี่ยง: <n> (<why>) สำรอง: <alt>
```
**Shot count, seconds per shot, per-shot credits and the total are MANDATORY lines (Fix 2026-11-09).** Credit table, Omni 1.1 Flash 720p x1: 4 s = 7 (measured), 8 s = 12 (measured), 10 s = 15 (measured), 6 s ≈ 10 (estimate - mark it `≈` and say it is an estimate). Before each submit read the Settings panel `Generating will use N credits`; if it differs from the board, tell Fix before generating.
Then ask with `clarify`: `["ผ่าน เริ่ม gen (≈X เครดิต)", "แก้ storyboard", "ยกเลิก"]`. Unanswered = zero spend, no generation.
Put the whole board inside the `clarify` question text and the buttons in `choices`, so the board and the approval arrive as one message. When the source images show two colourways, make the approval buttons carry the colour choice, so the same tap approves the board and resolves the colour.
Router Q3 (who drives Flow, step 8) may ride as the SECOND question in that same call: its default is 📝 (zero spend), so a second entry that gets lost costs nothing and is re-asked at most once.

## Example: vacuum bag 20 s
1. [P 4s] presenter points at an overflowing pile of blankets, tired face - "ผ้าห่มเยอะจนตู้ปิดไม่ลงใช่ไหม?"
2. [H 4s] hands stuff a folded blanket into the clear bag
3. [H 4s] fingers run the zip slider closed (risky: zip detail)
4. [H 4s] hands press the bag, it visibly deflates, air out at the white valve - punch-in + pill `No Pump`
5. [R/P 4s] flat bags stacked neatly in the wardrobe, presenter smiles - before/after card
