---
name: shopee-clip
description: Use for EVERY Shopee clip order from Fix (ทำคลิป shopee, ทำคลิปจากลิงก์นี้, a product link or product photos with a clip request, gen ใหม่อีกคลิป). Asks the mode first, then routes to gameplay-clips or runs the Flow modes.
version: 2.0.0
author: Hermes (IU) + Fix
license: MIT
metadata:
  hermes:
    tags: [video, shopee, google-flow, affiliate, router]
    related_skills: [gameplay-clips, flow-driver]
---
# Shopee clip — router (Telegram only)

Fix orders every clip in Telegram. This skill asks the questions, runs intake, and hands off by mode.
`clipjob.py` holds the job state. Scripts: `/opt/data/skills/shopee-clip/scripts/` (S below).

## Ground rules for this skill
- **Source of truth is the repo**: `centralized-nas-container-management/hermes-agent/skills/`. Every sync
  overwrites the three skills (shopee-clip, flow-driver, gameplay-clips) and refuses while an in-place edit
  is not pulled (`sync.sh --pull`). To keep a change: edit the clone, commit, push, then
  `cd /opt/data/centralized-nas-container-management && bash hermes-agent/skills/sync.sh` (tests run first), or
  ask Fix for `make hermes-skills`. Runtime data: `/opt/data/clips/` (workdirs in `work/<job>`).
- **A missed gate is fixed in code, not in prose.** If you skipped a rule, add the check to `clipjob.py`
  (with a test) instead of adding another paragraph here. This file has a 15 KB budget, enforced by a test.
- File names are unique across shopee-clip, flow-driver and gameplay-clips. A file named in `references/` or
  `scripts/` that is not in this skill lives in one of the other two under `/opt/data/skills/`.

## Hard rules (every mode)
- No price, currency, discount or % anywhere: voiceover, subs, pills, cover, hashtags.
- CTA words (ลิงก์ / ใต้คลิป / ตะกร้า) only in the last shot or beat.
- Hashtags ≤150 characters, no CJK (`templates/hashtags.md`). Basket link = an https Shopee link. Both go out as ONE message with tap-to-copy buttons (`send_copy_buttons.py`, run by `deliver`); no fenced code blocks, in every mode.
- EN pills ≤2 words. Flow must draw no on-screen text (the block in `references/presenter-post.md`).
- One heavy job at a time (whisper, render, ffmpeg): the NAS has 12 GB, and the gateway is fenced at 4 GB.
- Details and the reasons behind them: `references/house-rules.md`. Read it once per session before the first order.

## Flow of an order
0. `python3 S/clipjob.py status` lists open jobs — run it BEFORE inspecting any bare video from Fix
   (a clip with no caption is a shot coming back until `status` says otherwise, not a new order).
   Resume the job that message is about (a reply with a video, a ✅/🔁 tap, "ต่อ"), never from memory.
   Grep `/opt/data/clips/logs/clip-log.jsonl` and `delivery-log.jsonl` for the product name before a new
   job: a duplicate order is confirmed with Fix (which clip, what changes) before any spend. Same game
   but a DIFFERENT platform/edition listing (Switch 2 clip exists, PS5 ordered) is not a duplicate: note
   the prior clip in one line and open the new job — gameplay-clips reuses the old job's source artifacts.
1. **Intake** (before any question that costs time). Run
   `uv run --with pillow python S/intake_images.py <first image> /opt/data/clips/work/<job>`, then do
   one vision pass on the sheet. The gateway already described each image on arrival, so do not read
   them one by one again: a single-image read only for a tile the sheet leaves unclear (at most 2).
   You need the product name and the basket link. A missing link is
   asked for in the same message as Q1. Misattribution across tiles, several models under one link, a sheet-vs-ORDER-TEXT mismatch and a
   late image (re-running `intake_images.py` re-numbers from `img1`): `references/product-image-prep.md`
   → Intake sheet.
2. **Q1 — mode** (`clarify`, one question, buttons):
   `["🎬 footage จากวิดีโอทางการ (เกม/สินค้า, 0 เครดิต)", "🧑 presenter + graphic", "📦 graphic ล้วน (ภาพสินค้า ไม่มีคน)", "✋ มือ+สินค้า ลองใช้ให้ดู (ไม่เห็นหน้า)"]`.
   Do not guess from the product type. For a rigid product (rack, shelf, cabinet, device) add one line to the
   question: Flow redrew its parts/size in 3 of 3 🧑/✋ jobs (2026-11-10/11/14); 🎬/📦 hold the shape better.
3. **Q2 — length, 🧑/📦/✋ only** (`clarify`, one question): `["10 วิ (แนะนำ)", "20 วิ", "30 วิ", "40 วิ"]`.
   **🎬 skips Q2** (Fix 2026-11-12): gameplay-clips picks any whole length 15–50 s from the usable footage
   and the content (its "Length" section). A length Fix names in the order still wins.
   One shot = one Flow generation of 3–10 s, never 11–15 (Omni 1.2 Flash 720p = 3 credits/s; `house-rules.md`
   → Credits). N = ceil(length / 10); size each shot to its speech (`--seconds`); clip = sum of shots.
   A mode/length already named in the order is not asked again.
4. **🎬 → `clipjob.py new <job> --mode gameplay --product "…" --link <url>`, then load skill
   `gameplay-clips` and follow it.** The job has no shots; it holds the state across session resets
   (`clipjob.py note <job> "<done; next>"` at each stage) and ends with the same `deliver` as step 12
   (`--report` may be omitted). A game uses the steps as written. Any other product reads its
   `references/product-footage.md` first (official brand video of the exact model only, gated by
   `source_check.py`). A revision of a delivered clip: `clipjob.py reopen <job> --reason …`, then
   `deliver` again (it logs a REVISED row). Stop reading here for 🎬.
5. **Photo gate (🧑/📦/✋; 🎬 product needs one clean photo for the sticker).** References must be clean product photos: no price, promo text, rating, UI,
   person or hands, and the product in the state the shot needs. "Clean" means no text/UI/people — NOT
   a plain background: a styled room photo (a rack holding clothes, a shelf with items) is a valid
   reference, attached whole (`references/product-image-prep.md` "Lifestyle photos"); never ask Fix for a
   plain-background photo because of props alone.   Ad graphics and review screenshots
   are storyboard input only. Crop and cutout recipes: `references/product-image-prep.md`.
   **Printed box/case (game, console): take the official store packshot first** (`references/product-image-prep.md`
   → "official brand renders"), not an ad crop.
   **Crop budget: 2 vision checks.** Put every candidate crop on ONE labelled sheet per check; if no
   candidate passes the second check, send Fix the best one with what is wrong and ask (use it / new photo).
   With no clean photo, ask Fix for one and stop at zero spend. Never fill the gap with a guessed product.
   A reference under ~1000 px is high-risk for product identity (Flow redrew a ~700 px one): if Fix accepts it,
   say the drift risk in the storyboard and run the identity frame check before the second shot's submit.
   Save the references as `<workdir>/ref1.jpg …`.
6. **Storyboard** from `templates/storyboard.md`: N shots (seconds each from the speech, ≤10), the hook in shot 1, CTA in the last shot.
   Shots after the first chain from the previous shot's last frame, with the continuity block repeated.
   Send it and wait for approval. This is a standing gate; "don't ask me" does not waive it
   (`references/run-mode-gates.md`). Send the board as its own message (`S/send_status.py`), then approval + Q3 as TWO questions in ONE `clarify`.
   - 🧑: random pick from the roster, never the same face twice in a row, name the pick
     (`references/house-rules.md`). Pass it to `clipjob.py new --character <name>`, so the 📝 pack tells Fix
     which saved Flow character to attach. The Thai voiceover is spoken by the presenter inside Flow.
   - 📦: no person and no hands. Use product hero shots, macro, texture, in-use objects and a lifestyle
     set. The prompt says **no speech** (ambient sound only), because the voice is added in post
     (gameplay TTS). Write the VO script into the storyboard as well.
   - ✋: every 📦 step from here on (no speech, VO in post), but hands use the product in frame and no
     face ever shows. Read `references/hands-mode.md` first; step 10 needs `clipjob.py scan` before `ready`.
7. **Prompts → files.** Write `<workdir>/shot<K>.txt` for every shot. Build them from
   `templates/clip-prompt.md` + `templates/style-card.md` + a hook from `templates/hooks.md`
   (`S/perf.py pick-hook --category <cat>`), plus the no-on-screen-text block. Then:
   `clipjob.py new <job> --mode presenter|product|hands --product "…" --link <url> --shots N [--seconds 8,6] --ref <workdir>/ref1.jpg [--ref …] --character <name>` (🧑 only). Credits (board, Q3): `clipjob.py cost --seconds 8,6`. workdir = `/opt/data/clips/work/<job>`
8. **Q3 — who drives Flow** (`clarify`, one question, cost in the text):
   `["📝 เตรียม prompt ทีละช็อตให้ (ฟิกกดใน Flow เอง)", "🤖 ให้ไอยูลองทำใน Flow ให้เลย (≈<cost> เครดิต ถ้าติดจะสลับเป็นโหมด prompt ให้เอง)"]`.
   An unanswered or timed-out question means 📝 (zero spend) — for ANY question that would spend credits, not just this one. Record the answer: `clipjob.py production <job> prompt|auto`, using `production prompt` rather than `fallback` (a fallback locks that job out of `auto` for good; the hand-off message format is in `flow-driver` → Manual hand-off).
9. **Shots.**
   - 📝: `clipjob.py pack <job>` sends the reference photos and one tagged prompt per shot. Then wait.
     Each video from Fix: if the message replies to a prompt, run
     `clipjob.py ingest <job> <file> --reply-text "<replied-to text>"`. If it has no reply context, ask
     which shot it is (buttons ช็อต 1…N), then run `--shot K`. Do not ask when the job state answers it: exactly one
     shot is submitted with no file yet. Full rules: `references/prompt-pack.md`.
   - 🤖: load skill `flow-driver` and follow it. It calls `reserve`/`submitted`/`submit-failed`/`trouble`.
     🤖, Flow download fails and Fix sends the mp4: copy it to the workdir as `shotK_raw.mp4` and run
     step 10's `ready` on it. 🤖 has no `ingest` step.
     When a command prints `"FALLBACK": true`: stop driving Flow and close Chrome (CDP `Browser.close`), tell Fix
     in one line (reason, credits spent, shots left), run `clipjob.py pack <job>` and continue as 📝.
     A shot that failed after spending credits gets its own 🔁 button from `submit-failed`; wait for the tap.
10. **Per-shot review.** After each file arrives (downloaded or ingested), vision-check 3 frames — one inside the first 2 s, since a caption can live only in the hook window — for Flow text,
    product drift (shape AND real-world scale against the presenter), and whether the planned action happened. Then run
    `clipjob.py ready <job> K --raw <file> --frame pass|flag:<what you saw>`. That runs ffprobe and, for 🧑,
    the repeats and CTA gates, then sends the shot with the ✅/🔁 keyboard. If that send fails the checks are
    kept: `clipjob.py ready <job> K --resend` (no re-check). Fix's tap arrives as text →
    `clipjob.py decide --text "<text>"`; if it prints `REFUSED: text is not a review button`, run
    `clipjob.py decide <job> K approve|regen`. Never hand-edit the job JSON. On 🔁: in 📝 run `pack <job> --shot K`; in 🤖 regenerate via flow-driver. A regen that repeats the defect = stop: name it, the credits spent, the zero-credit options (post fix / manual), wait for Fix.
    A 🔁 on shot K also asks Fix keep/regen for an already rendered shot K+1 (its start frame is gone); wait
    for that tap too. Shot 2 may render while shot 1 is reviewed only when shot 1 passed every gate.
11. **Post-production (graphics always).** `clipjob.py assemble-check <job>` prints the approved files in order — copy exactly those paths into the workdir (a leftover `shotK_raw.mp4` may be a rejected take).
    - 🧑: `references/presenter-rules.md` + `references/presenter-graphics.md`:
      `autogfx.py fx` → `presenter_fx` → `post_presenter` → `autogfx.py gfx` → `graphics_layer --report … --check`,
      then render. `autogfx` MEASURES every coordinate: never work one out by hand.
    - 📦/✋: `references/product-mode.md`: `product_build.py` (gameplay VO recipe), then
      `graphics_layer --report <workdir>/report.json`.
    - Read `report.json` and every `FLAG:` line. Then make a frame sheet (`references/frame-check.md`) and
      run `make_cover.py` (pre-sub source, EN ≤3 words).
12. **Deliver — one command, nothing else sends the final clip:**
    `clipjob.py deliver <job> --final <final.mp4> --report <report.json> --gfx <gfx.json> --hashtags "<tags>" --cover <cover.jpg> --caption "<short Thai caption>" --hook-id <id> --category <cat> [--notes "…"] [--ack "<flag>=<Fix's call>"]`
    It refuses when a shot is unapproved, graphics are empty, hashtags fail, verify-clip fails, or the report
    has a flag Fix has not decided on: tell him each flag with its frame time, he picks "ส่งแบบนี้" or regen;
    as-is = `--ack "<flag text>=<his call>"` (logged). Never edit `report.json` to clear a flag. A failed send =
    rerun the same command (finished steps are skipped). Send no extra MEDIA or hashtag text (it would
    duplicate them). Its last message has the 🏁 จบงาน button: do NO cleanup, end the turn (🤖: close Chrome
    first). A 🏁 tap → only `clipjob.py decide --text "<text>"`; no tap = it closes itself in 5 min.
12b. **Close-out with no clip** (Fix orders the skip, `status` shows no shot file): `references/run-mode-gates.md`
   → Close-out. Never stage or imply a clip.
12c. **Re-send of an already-delivered package** (`ขอคลิป hashtag และปักตะกร้า`, `สรุปอีกรอบ`): resolve WHICH
   clip first, read the job's `delivery.sent`, re-run `S/send_copy_buttons.py` — `references/run-mode-gates.md`
   → Re-send.
13. Fix calls it off (`เลิกทำ` / `หยุด` / `พอแล้ว`) → `clipjob.py cancel <job> --reason …`, close Chrome, report
    the credits actually spent (`spent_shots`). No clip-log row.

## Talking to Fix
- One status line when something blocks, sent at that moment, not at the end. Put the credit cost inside
  any question that spends credits. Short "ok/ได้" to your own go/no-go question = yes.
- **A long silent stretch also needs a line** (post, 🤖 browser drive, per-shot frame review): one short
  line at each stage transition — `references/house-rules.md` → Status lines.
- He reads on the phone: buttons over typing, no walls of text, never ask him to check a UI.
- **A real `FLAG` needs his call: ask once with `clarify`, then end the turn and wait** (no re-ask, no `--ack` for him).
- Senders parse no flags: `S/send_status.py` posts its FIRST argument verbatim, so never probe one with `--help`.
