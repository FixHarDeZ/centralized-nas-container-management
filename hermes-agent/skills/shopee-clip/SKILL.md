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
- **Source of truth is the repo**: `centralized-nas-container-management/hermes-agent/skills/`. The three skills
  (shopee-clip, flow-driver, gameplay-clips) are overwritten by every sync, so an in-place edit does not last:
  sync saves it to `/opt/data/clips/skill-drift/` and restores the repo version. To change one for real, edit
  the clone, commit and push, then run `cd /opt/data/centralized-nas-container-management && bash hermes-agent/skills/sync.sh`
  (it runs the tests first and refuses on failure), or ask Fix for `make hermes-skills`.
  Runtime data lives in `/opt/data/clips/` (job workdirs in `/opt/data/clips/work/<job>`).
- **A missed gate is fixed in code, not in prose.** If you skipped a rule, add the check to `clipjob.py`
  (with a test) instead of adding another paragraph here. This file has a 15 KB budget, enforced by a test.
- File names are unique across shopee-clip, flow-driver and gameplay-clips. A file named in `references/` or
  `scripts/` that is not in this skill lives in one of the other two under `/opt/data/skills/`.

## Hard rules (every mode)
- No price, currency, discount or % anywhere: voiceover, subs, pills, cover, hashtags.
- CTA words (ลิงก์ / ใต้คลิป / ตะกร้า) only in the last shot or beat.
- Hashtags ≤150 characters, no CJK (`templates/hashtags.md`). Lead with 2–4 product-benefit hook tags (`#` + Thai phrase, no spaces) before the pool tags; drop pool tags, never hook tags, to fit. Basket link = an https Shopee link, sent with the hashtags in the same delivery message (🛒 ปักตะกร้า).
- EN pills ≤2 words. Flow must draw no on-screen text (the block in `references/presenter-post.md`).
- One heavy job at a time (whisper, render, ffmpeg): the NAS has 12 GB, and the gateway is fenced at 4 GB.
- Details and the reasons behind them: `references/house-rules.md`. Read it once per session before the first order.

## Flow of an order
0. `python3 S/clipjob.py status` lists open jobs. Resume one if this message is about it (a reply
   with a video, a ✅/🔁 tap, "ต่อ"). Do not reconstruct state from memory.
1. **Intake** (before any question that costs time). Run
   `uv run --with pillow python S/intake_images.py <first image> /opt/data/clips/work/<job>`, then do
   one vision pass on the sheet. You need the product name and the basket link. A missing link is
   asked for in the same message as Q1.
2. **Q1 — mode** (`clarify`, one question, buttons):
   `["🎬 footage จากวิดีโอทางการ (เกม/สินค้า, 0 เครดิต)", "🧑 presenter + graphic", "📦 graphic ล้วน (ภาพสินค้า ไม่มีคน)"]`.
   Do not guess from the product type: a game can be 🧑, and a washer can be 🎬.
3. **Q2 — length** (`clarify`, one question): `["10 วิ (แนะนำ)", "20 วิ", "30 วิ", "40 วิ"]`.
   One shot = one Flow generation of 10 s (Omni 1.1 Flash, ≈15 credits; `house-rules.md` → Duration).
   N = length / 10: 10 s→1, 20 s→2, 30 s→3, 40 s→4. A shot can hold several storyboard beats.
4. **🎬 → load skill `gameplay-clips` and follow it.** Its own steps cover footage, VO and delivery. A game
   uses the steps as written. Before any 🎬 final goes to Fix, check its delivery step: a plain MEDIA send in chat
   skips the clip-log row and the copy buttons, so if that is what was done, say so in the reply. Any other product reads its `references/product-footage.md` first
   (official brand video of the exact model only, gated by `source_check.py`). No clipjob for 🎬 (nothing to
   pace or review per shot). Stop reading here for 🎬.
5. **Photo gate (🧑/📦; 🎬 product needs one clean photo for the sticker).** References must be clean product photos: no price, promo text, rating, UI,
   person or hands, and the product in the state the shot needs. Ad graphics and review screenshots
   are storyboard input only. Crop and cutout recipes: `references/product-image-prep.md`.
   With no clean photo, ask Fix for one and stop at zero spend. Never fill the gap with a guessed product.
   Save the references as `<workdir>/ref1.jpg …`.
6. **Storyboard** from `templates/storyboard.md`: N shots of 10 s, the hook in shot 1, CTA in the last shot.
   Shots after the first chain from the previous shot's last frame, with the continuity block repeated.
   Send it and wait for approval. This is a standing gate; "don't ask me" does not waive it
   (`references/run-mode-gates.md`).
   - 🧑: random pick from the roster, never the same face twice in a row, name the pick
     (`references/house-rules.md`). Pass it to `clipjob.py new --character <name>`, so the 📝 pack tells Fix
     which saved Flow character to attach. The Thai voiceover is spoken by the presenter inside Flow.
   - 📦: no person and no hands. Use product hero shots, macro, texture, in-use objects and a lifestyle
     set. The prompt says **no speech** (ambient sound only), because the voice is added in post
     (gameplay TTS). Write the VO script into the storyboard as well.
7. **Prompts → files.** Write `<workdir>/shot<K>.txt` for every shot. Build them from
   `templates/clip-prompt.md` + `templates/style-card.md` + a hook from `templates/hooks.md`
   (`S/perf.py pick-hook --category <cat>`), plus the no-on-screen-text block. Then:
   `clipjob.py new <job> --mode presenter|product --product "…" --link <url> --shots N --ref <workdir>/ref1.jpg [--ref …] --character <name>` (required for 🧑; omit for 📦). workdir = `/opt/data/clips/work/<job>`
8. **Q3 — who drives Flow** (`clarify`, one question, cost in the text):
   `["📝 เตรียม prompt ทีละช็อตให้ (ฟิกกดใน Flow เอง)", "🤖 ให้ไอยูลองทำใน Flow ให้เลย (≈<N×15> เครดิต ถ้าติดจะสลับเป็นโหมด prompt ให้เอง)"]`.
   An unanswered or timed-out question means 📝 (zero spend). Record the answer: `clipjob.py production <job> prompt|auto`.
9. **Shots.**
   - 📝: `clipjob.py pack <job>` sends the reference photos and one tagged prompt per shot. Then wait.
     Each video from Fix: if the message replies to a prompt, run
     `clipjob.py ingest <job> <file> --reply-text "<replied-to text>"`. If it has no reply context, ask
     which shot it is (buttons ช็อต 1…N). Never guess, then run `--shot K`. Full rules: `references/prompt-pack.md`.
   - 🤖: load skill `flow-driver` and follow it. It calls `reserve`/`submitted`/`submit-failed`/`trouble`.
     When a command prints `"FALLBACK": true`:
     1. Stop driving Flow and close Chrome (CDP `Browser.close`).
     2. Tell Fix in one line: the reason, credits spent, shots left.
     3. Run `clipjob.py pack <job>` and continue as 📝.
10. **Per-shot review.** After each file arrives (downloaded or ingested), vision-check 3 frames: Flow text,
    product drift, and whether the planned action happened. Then run
    `clipjob.py ready <job> K --raw <file> --frame pass|flag:<what you saw>`. That runs ffprobe and, for 🧑,
    the repeats and CTA gates, then sends the shot with the ✅/🔁 keyboard. Fix's tap arrives as text →
    `clipjob.py decide --text "<text>"`. On 🔁: in 📝 run `pack <job> --shot K`; in 🤖 regenerate via flow-driver.
    Send shot 1 for review while shot 2 renders.
11. **Post-production (graphics always).** `clipjob.py assemble-check <job>` prints the approved files in order.
    - 🧑: `references/presenter-rules.md` + `references/presenter-graphics.md`:
      `layout_probe` → `presenter_fx` → `post_presenter` → `graphics_layer --report … --check`, then render.
    - 📦: `references/product-mode.md`: `product_build.py` (gameplay VO recipe), then
      `graphics_layer --report <workdir>/report.json`.
    - Read `report.json` and every `FLAG:` line. Then make a frame sheet (`references/frame-check.md`) and
      run `make_cover.py` (pre-sub source, EN ≤3 words).
12. **Deliver — one command, nothing else sends the final clip:**
    `clipjob.py deliver <job> --final <final.mp4> --report <report.json> --gfx <gfx.json> --hashtags "<tags>" --cover <cover.jpg> --caption "<short Thai caption>" --hook-id <id> --category <cat> [--notes "…"] [--ack "<flag>=<Fix's call>"]`
    It refuses when a shot is unapproved, graphics are empty, hashtags fail, verify-clip fails, or the report
    has a flag Fix has not decided on. For each flag, tell Fix what it is (with the frame time) and let him choose
    between "ส่งแบบนี้" and regenerating. If he chooses as-is, pass `--ack "<flag text>=<his call>"`; it goes into
    the clip-log. Never edit `report.json` to clear a flag. If a send fails mid-way, rerun the same command:
    finished steps are skipped and the clip is logged once. On success it has run verify-clip, the
    clip-log row, the clip, copy buttons, cover and check_delivery. Then do the cleanup
    (`/opt/data/skills/flow-driver/references/flow-steps.md` step 13).
13. Fix calls it off (`เลิกทำ` / `หยุด` / `พอแล้ว`) → `clipjob.py cancel <job> --reason …`, close Chrome, report
    the credits actually spent (`spent_shots`). No clip-log row.

## Talking to Fix
- One status line when something blocks, sent at that moment, not at the end. Put the credit cost inside
  any question that spends credits. Short "ok/ได้" to your own go/no-go question = yes.
- He reads on the phone: buttons over typing, no walls of text, never ask him to check a UI.
