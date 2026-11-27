# Storyboard template (Fix 2026-11-09, mandatory before any Flow generation)

Why: two 10 s takes of "hold it up / press / set down" read as filler (vacuum-bag clip). Fix wants every shot to SHOW the product working.

## Rules
- Arc: problem -> product doing its job (step by step) -> result. Every shot = ONE visible action where the product performs its function. "Holds it up to camera" alone is not a shot.
- Source the beats from the listing's own how-to / feature / before-after images (gathered by `intake_images.py`). They are storyboard material even when they cannot be attached as references.
- Pace submits ≥5 min apart (Fix 2026-11-09, quality over speed), so a 5-shot board adds ~20 min of wall clock. Say so in the board.
- Shot length: one Flow generation is 3–10 s (Omni 1.2 Flash, 3 credits/s at 720p). Give each shot the seconds
  its speech or action needs (6–8 s normal; ~4 Thai syllables/s) and pass them as `clipjob.py new --seconds 8,6`.
  Never 11–15 s (double rate). The clip length is the sum of the shots (post adds none): show that total on the
  board. Example, a "20 วิ" 🧑 order: 8 + 8 = 16 s ≈48 credits, or 10 + 10 = 20 s ≈60; Fix picks with the
  approval tap, and the board marks which option fits what is left in the account (read the live balance first,
  `house-rules.md` → Credits) — 10 + 10 = 60 does not, and a regen on
  top of 48 usually does not either (`house-rules.md` → Credits).
- **Keep every per-shot second count inside what the Flow duration control can actually express** (buttons `4s/6s/8s/10s`, or a 1-s slider when the panel renders one — `flow-driver` → `flow-production-notes.md`). A board promising 7 s per shot while the control offers only even seconds forces a mid-run re-split; when that happens the APPROVAL still binds the totals, so re-split to offered values keeping the same clip total and same total credits (7+6+7 → 8+6+6), and say so in one status line instead of re-asking.
- Mix shot types:
  - `P` presenter to camera (hook, reaction, result) - character chip attached, Flow voiceover.
  - `H` hands close-up doing the action (no face, NO character chip - also avoids the prominent-person refusal).
  - `R` result / before-after (product in place, wide).
- **The order text's own selling points go on the FIRST board** — the counts, specs and compatibility Fix pasted with the link ("175เกมส์", "(PC/PS2)", "2.5 นิ้ว"): each one is in a พากย์ line or a shot, or the board says why not; price / promo words never. ps2-hdd-175 11-24: the first board left out 175 games and plugged the drive into a PS2 instead of a PC, and both came back as revision rounds.
- Voiceover line per shot must describe what is on screen in that shot. Count it: ~3.5-4.5 Thai syllables/s, speech >= 70 % of a talking shot. H shots may carry no speech (music + SFX, our sub/pill only).
- **Count each shot's พากย์ against the LENGTH gate before the board goes out**: `ก-๙` + Latin/digits inside the
  quotes, ≤11.5 per second on the final shot and ≤12/s elsewhere (`clipjob.py new` prints it as `vo_rate`; `pack`
  refuses past it). The gate fires only after Fix has approved, so a line over it can then be fixed only by
  editing the script he signed off on — measure first, send second.
- **The พากย์ lines printed on the board ARE the approved script** — the scene's `Audio` line (🧑) and the post TTS plan (📦) take them verbatim, with length-fit edits only: expanding the content contradicts the approved board and burns a TTS take just to learn it overshoots the shot.
- Plan the graphics v2 layer per shot: punch-in at the money moment, EN pill (<=2 words), product cutout, before/after card. **Count the pill's whitespace tokens while writing the board**: `&` is its own token, so `Tie & Go` = 3 and `post_presenter.py` refuses it — that gate fires only after the approved board is already running, so word pills ≤2 tokens from the start. **📦/✋ have no punch-in** — `graphics_layer.py` has no zoom effect — so for those modes the board plans a sticker (arrow/sparkle, `anim: pop`) at the money moment instead; never promise in an approved board what post cannot render.
- Flag risky actions (zips, valves, fine finger work, text on product) and name a fallback shot.
- Rigid product (rack, shelf, cabinet, device) in 🧑/✋ and Fix named the mode in the order (router Q1 skipped): put the Q1 warning on the board's ⚠️ line — Flow redrew its parts/size in 3 of 3 such jobs (2026-11-10/11/14); the risk does not disappear with the question.
- **The order asks to SHOW two variants in one 10 วิ ("โชว์ทั้งแบบ A และ B ใน 10 วิ"): one shot, not two.** Two
  gens double the submit risk and need a second on-screen price read; instead WEAR one variant and HOLD the other
  up (on a hanger / folded), attach BOTH refs as ingredients (chipcheck verifies each), and lock both in the
  prompt's structure block — exact piece counts for each, "never merge them, never add a third garment" — so one
  idcheck verifies both. Split 2×5 s only if Fix insists both be worn, and read that duration's credit line from
  Settings before putting the number on a board.
- CTA: only on the final shot, and only if the clip is light (heavy-content clips skip it).
- No price, no unverified claims (%, seconds, certifications) in any line.

## Running an approved board
- Each shot is its own independent generation (Settings: Video, Ingredients, 9:16, 720p, the shot's seconds, x1). Shot 2 onward starts from the previous shot's last frame (router step 6; `clipjob.py pack` sends that frame and `reserve` enforces the order). Repeat one continuity block (presenter look, backdrop, lighting) verbatim in every shot prompt.
- Chips per shot type: `H` = product crops only. `P`/`R` = product crops plus the character. Re-attach before each submit, because the box clears its chips on submit.
- A 4 s 720p shot rendered in about 40-120 s. Overlap the work: submit shot N+1, then QC shot N and send it for review. Do not chain past a shot that carries a defect you found yourself.
- Pace the submits. Firing the next one the moment each render lands tripped `unusual activity` by the fifth shot (`references/flow-browser-env.md`), so leave a gap between submits rather than a back-to-back burst.
- **Plan the CTA shot as the expendable one.** It is last in the queue, so it is the shot most likely to hit a rate-limited `Failed` card. If it fails after the one retry, offer two choices. (1) Wait 30 min or more, relaunch Chrome and retry once (credit cost in the text). (2) Ship the shots you have and put the CTA in the caption and basket (0 credits). Fix chose (2). Build option (2) with `NO_AUTO_CTA=1` so post does not add a `Link below!` pill.
- In the post plan, mark every speechless `H` shot `"silent": true` (`references/presenter-post.md`). Otherwise the script tries to align an empty voiceover and crashes.
- An `H` shot that lands on skin (blush on a cheek, cream on a hand) renders a stranger's face part because it has no character chip. "Cheek and jaw only, eyes out of frame" was ignored and the eye and brow showed. When the shot must stay faceless, frame it on the product plus fingertip. When it needs skin, make it a `P`/`R` shot with the character chip, so the face at least matches the presenter.
- For a R/result shot the voiceover lists, write each on-screen touch or prop state into the prompt as its own numbered action (open the compact, touch the cheek, then the eyelid, then the lips). A single sentence that bundles them lets the model skip some of them.
- **Product-identity checklist (one line per board, under the shots):** the parts a viewer could count or
  measure: tiers/drawers/doors/wheels, colour, proportions against a person (height ≈ waist / chest / head).
  Every shot prompt carries those counts as exact numbers, and every per-shot frame verdict answers each item;
  one miss = `--frame flag:<item>`. Rigid products drifted on both 🧑 jobs that had none (2026-11-10/11).
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
💳 เครดิตรวม ≈ <sum> (ถ้าต้อง gen ช็อตเสี่ยงใหม่ 1 ครั้ง +<c>) · เครดิตที่เหลือจากบัญชี Flow: <N · รีเซ็ต <date>> · <พอ / ไม่พอต้องรอรอบรีเซ็ต>
🔁 กด gen ทั้งหมด <N> ครั้ง (≥5 ครั้ง = ต้องเว้นระยะ ใช้เวลานานขึ้น)
⚠️ ช็อตเสี่ยง: <n> (<why>) สำรอง: <alt>
🔎 เช็คสินค้า: <ชั้น/ลิ้นชัก/ล้อ N> · <สี> · <สูงประมาณ เอว/อก/หัว>
```
**กราฟิก: promise only what `autogfx` places from a flag** (`presenter-graphics.md` top): `pill "<EN ≤2 words>"`, `zoom <beat> (หน้า/สินค้า)`, `สติกเกอร์สินค้า` (cut-out, ช็อตสุดท้ายถ้าไม่ระบุ), `headline "<คำ>"`. Each may be left out when it does not fit the real frames; the board says "ถ้ามีที่วาง" once, not per item.
**Shot count, seconds per shot, per-shot credits and the total are MANDATORY lines (Fix 2026-11-09).** Credits, Omni 1.2 Flash 720p x1 = 3 per second (4 s = 12, 6 s = 18, 8 s = 24, 10 s = 30; `clipjob.py cost --seconds 8,6`); published rates, not measured here yet, so mark every figure `≈`. Size each shot to its speech (6–8 s normal), never above 10 s, and cover the remaining clip seconds in post (0 credits). Before each submit read the Settings panel `Generating will use N credits`; if it differs from the board, tell Fix before generating.
Then ask with `clarify`: `["ผ่าน เริ่ม gen (≈X เครดิต)", "แก้ storyboard", "ยกเลิก"]`. Unanswered = zero spend, no generation.
The board itself goes out FIRST as its own message (`S/send_status.py`, posts its first argument verbatim); the `clarify` carries only the buttons (router step 6) — a board stuffed into a question text is a wall of text on the phone. When the source images show two colourways, make the approval buttons carry the colour choice, so the same tap approves the board and resolves the colour. **The button cap is 4 and two asks can compete for it:** the quota length fork needs both split buttons because it decides the credits, so with three or more colourways there is no button left for colour — name the default colourway in the board body (what the ad's hero shows) with the route to change it (`บอกใน แก้ storyboard`) and keep the fork on the buttons. **Same shape for a quota length fork:** when the ordered length and what the account has left disagree (a 20 วิ board = 60 credits against a balance that cannot cover it), put BOTH splits in the buttons — `["ผ่าน 10+10 = 20 วิ (≈60 เครดิต)", "ผ่าน 8+8 = 16 วิ (≈48 เครดิต)", "แก้ storyboard", "ยกเลิก"]`, 4 buttons max — one tap then approves AND picks the split, while the board still states which option fits today's quota and that a regen may wait for the reset. **Size the fork's VO to the LONGER split and mark the shot lines `8–10 วิ`:** write each shot's พากย์ at ~30 syllables (≈7–7.5 s of speech) so the SAME approved script fills a 10 s shot at ≥70 % and still fits an 8 s one — a line sized only for 8 s underfills the 10 s tap, and Flow pads a short script by repeating the last phrase (`references/presenter-post.md` → Looped voiceover). If he taps the longer split and the line still runs short, ONE neutral length-fit clause may be added before `pack` (no new claims) and is noted in the job — that is a length-fit edit, not a script change.
**On a `แก้ storyboard` tap:** ONE open `clarify` with NO buttons — "พิมพ์มาเลยว่าแก้อะไร (บทพากย์ส่งบรรทัดมาได้เลย · โครง/ความยาว · ผู้บรรยาย · กราฟิก)" — never a menu first: ps2-hdd-175 11-24 asked a 4-button menu and then a free-text question on each of three rounds, two hops where one does. Revise, re-send the board as its own message, then ask approval again — one revision round, then a non-answer = zero spend. **A voiceover/hook change is HIS text: ask Fix to send his line instead of drafting alternatives** (he writes his own script; offer drafts only if he asks for options), and check his line against the syllable budget for the chosen length before the board goes out again. **A DIRECTION is not a line:** when he writes `hook ประมาณว่า <แนว>` instead of a full sentence, draft exactly ONE line that keeps his key wording, check it against the syllable budget, and put it on the next board — his approval tap on that board is his sign-off on the wording; do not bounce a direction back asking him to write the sentence himself.
Router Q3 (who drives Flow, step 8) may ride as the SECOND question in that same call: its default is 📝 (zero spend), so a second entry that gets lost costs nothing and is re-asked at most once.
**When that call times out, the ONE re-ask MERGES approval + Q3 into a single question with ≤4 buttons** (`ผ่าน + ให้ไอยูกด 🤖`, `ผ่าน + ฟิกกดเอง 📝`, `แก้ storyboard`, `ยกเลิก`): one tap then settles both, and two separate questions surviving a second timeout is how a run ends at zero spend with a board that was never approved.

## Example: vacuum bag 20 s
1. [P 4s] presenter points at an overflowing pile of blankets, tired face - "ผ้าห่มเยอะจนตู้ปิดไม่ลงใช่ไหม?"
2. [H 4s] hands stuff a folded blanket into the clear bag
3. [H 4s] fingers run the zip slider closed (risky: zip detail)
4. [H 4s] hands press the bag, it visibly deflates, air out at the white valve - punch-in + pill `No Pump`
5. [R/P 4s] flat bags stacked neatly in the wardrobe, presenter smiles - before/after card

## Character pick (🧑)
- **Pick the face from `clip-log.jsonl`, never from flow-state's `last_character_used`.** That field is only
  written when the agent drives Flow, so a 📝 prompt-mode run never updates it and it lags behind the newest
  `character` value in clip-log — reading it alone repeats the face Fix already saw in the last clip. Take the
  newest `character` row in clip-log, exclude that name, choose at random from `character_roster` in
  `/opt/data/clips/flow-state/<project-id>.json`, and name the pick on the board.
- **Draw only from female roster names that have a portrait** in `/opt/data/clips/characters/` (male ones,
  e.g. น้องเอิร์ธ, were made for one order: clip-log `notes` say `ตัวละครชาย`). A male pick only when Fix asks.
- **Write the prompt's presenter line from that character's recorded look, never her NAME and never a generic
  "young Thai woman"** (`references/house-rules-history.md`). Looks of all twelve: `flow-driver` `references/flow-steps.md`
  step 2; flow-state `roster_note` = only the last three added. `new` refuses a name with no portrait; `pack`/`reserve` refuse
  a name in the prompt outside the quoted voiceover.
