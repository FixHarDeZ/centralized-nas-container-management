---
name: shopee-clip
description: Use for EVERY Shopee clip order from Fix (ทำคลิป shopee, ทำคลิปจากลิงก์นี้, a product link or product photos with a clip request, gen ใหม่อีกคลิป). Also a clipjob button tap (✅/🔁 ช็อต, 🤖 ไอยูกด Flow แทน, 🏁 จบงาน). Asks the mode first, then routes to gameplay-clips or runs the Flow modes.
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
- **Source of truth is the repo** (`hermes-agent/skills/`); how a change is kept: `references/house-rules.md`
  → Skill sync. Runtime data: `/opt/data/clips/` (workdirs in `work/<job>`).
- **A missed gate is fixed in code, not in prose.** If you skipped a rule, add the check to `clipjob.py`
  (with a test) instead of adding another paragraph here. 15 KB budget, enforced by a test.
- File names are unique across the 3 clip skills: one not in this skill lives in flow-driver/gameplay-clips.

## Hard rules (every mode)
- No price, currency, discount or % anywhere: voiceover, subs, pills, cover, hashtags.
- CTA words (ลิงก์ / ใต้คลิป / ตะกร้า) only in the last shot or beat.
- Hashtags ≤150 characters, no CJK (`templates/hashtags.md`). Basket link = an https Shopee link. Both go out as ONE message with tap-to-copy buttons (`send_copy_buttons.py`, run by `deliver`); no fenced code blocks, in every mode.
- EN pills ≤2 words. Flow must draw no on-screen text (the block in `references/presenter-post.md`).
- One heavy job at a time (whisper, render, ffmpeg): the NAS has 12 GB, and the gateway is fenced at 4 GB.
- Details + reasons: `references/house-rules.md` (read once per session before the first order).

## Flow of an order
0. `python3 S/clipjob.py status` lists open jobs — run it BEFORE inspecting any bare video from Fix
   (a clip with no caption is a shot coming back until `status` says otherwise, not a new order).
   Resume the job that message is about (a reply with a video, a ✅/🔁 tap, "ต่อ"), never from memory.
   Rows carry `stage` + `last` (newest notes): after a context loss (a model refusal, a reset, a bare "ต่อ")
   continue from `last` and the workdir — never rebuild it from `session_search`.
   Duplicate check before a new job: grep `clip-log.jsonl` for the product name (`delivery-log.jsonl` = slugs only). A duplicate is confirmed with Fix before any spend (it may ride on the
   board's ⚠️ line). Same game, other platform/edition = not a duplicate: one line, new job (gameplay-clips
   reuses the old job's sources).
   Then at once: `clipjob.py intake <job> --product "…" --link <url> [--mode …]`, and
   `clipjob.py note <job> "<done; next>"` after Q1, the photo gate and the board (🎬: `new` here instead).
1. **Intake** (before any question that costs time). Run
   `uv run --with pillow python S/intake_images.py <first image> /opt/data/clips/work/<job>`, then do
   one vision pass on the sheet (`question=` only; `prompt=` is ignored). The gateway already described each
   image: a single-image read only for a tile the sheet leaves unclear (at most 2). You need the product name and
   the basket link (a missing link is asked with Q1). Edge cases: `references/product-image-prep.md` → Intake sheet.
2. **Q1 — mode** (`clarify`, one question, buttons):
   `["🎬 footage จากวิดีโอทางการ (เกม/สินค้า, 0 เครดิต)", "🧑 presenter + graphic", "📦 graphic ล้วน (ภาพสินค้า ไม่มีคน)", "✋ มือ+สินค้า ลองใช้ให้ดู (ไม่เห็นหน้า)"]`.
   Do not guess from the product type. **Vocabulary in the order already names the mode → skip Q1:**
   `gameplay` / `ฟุตเตจ` / `footage` = 🎬, and `+ graphic` is not a mode — graphics are made in post in every
   mode. Rigid product (rack, shelf, device): add one line, Flow redrew its parts in 3 of 3 🧑/✋ jobs.
3. **Q2 — length, 🧑/📦/✋ only** (`clarify`, one question): `["10 วิ (แนะนำ)", "20 วิ", "30 วิ", "40 วิ"]`.
   **🎬 skips Q2**: gameplay-clips picks 15–50 s from the footage. A length Fix names still wins.
   One shot = one Flow generation of 3–10 s, never 11–15 (Omni 1.2 Flash 720p = 3 credits/s; `house-rules.md`
   → Credits). N = ceil(length / 10); size each shot to its speech (`--seconds`); clip = sum of shots.
   A mode/length already named in the order is not asked again.
4. **🎬 → `clipjob.py new <job> --mode gameplay --product "…" --link <url>`, then load skill
   `gameplay-clips` and follow it.** No shots; it holds the state across resets (`note` at each stage)
   and ends with step 12's `deliver` (`--report` optional). Any other product reads its
   `references/product-footage.md` first (official brand video of the exact model only, gated by
   `source_check.py`). A revision of a delivered clip: `clipjob.py reopen <job> --reason …`, then
   `deliver` again (it logs a REVISED row). Stop reading here for 🎬.
5. **Photo gate (🧑/📦/✋; 🎬 product needs one clean photo for the sticker)** — `references/product-image-prep.md`
   (box/case: `scripts/box_crop.py` first; packshots, crops, cutouts). Clean = no price, promo,
   rating, UI, person or hands; a styled room is fine. Ad graphics are storyboard input only.
   **Crop budget: 2 vision checks**, all candidates on ONE sheet; every candidate clean AS IS = no question,
   `note` it and go to the board. Sheet build, the ask, no-clean-photo: `product-image-prep.md` → Photo gate.
   Under ~1000 px = drift risk on the board. References: `<workdir>/ref1.jpg …`.
6. **Storyboard** from `templates/storyboard.md`: N shots (seconds each from the speech, ≤10), the hook in shot 1, CTA in the last shot.
   Shots after the first chain from the previous shot's last frame, with the continuity block repeated.
   Send it and wait for approval. This is a standing gate; "don't ask me" does not waive it
   (`references/run-mode-gates.md`). Send the board as its own message (`S/send_status.py`), then approval + Q3 as TWO questions in ONE `clarify`.
   - 🧑: random pick from the roster, never the same face twice in a row, name the pick
     (`references/house-rules.md`); `new --character <name>` refuses a name with no portrait in
     `/opt/data/clips/characters/`. The Thai voiceover is spoken by the presenter inside Flow.
   - 📦: no person, no hands: hero shots, macro, texture, lifestyle set. The prompt says **no speech** (VO is
     added in post); write the VO script into the storyboard.
   - ✋: every 📦 step from here on (no speech, VO in post), but hands use the product in frame and no
     face ever shows. Read `references/hands-mode.md` first; step 10 needs `clipjob.py scan` before `ready`.
7. **Prompts → files.** Write `<workdir>/shot<K>.txt` for every shot. Build them from
   `templates/clip-prompt.md` + `templates/style-card.md` + a hook from `templates/hooks.md`
   (`S/perf.py pick-hook --category <cat>`), plus the no-on-screen-text block. **Never write the character's
   name (or any น้อง… name) outside the quoted voiceover** — Flow paints it on screen; `pack`/`reserve` refuse it. Then:
   `clipjob.py new <job> --mode presenter|product|hands --product "…" --link <url> --shots N [--seconds 8,6] [--ref <workdir>/ref1.jpg [--ref …]] [--character <name>]` (🧑 only; fills in the intake job). Credits (board, Q3): `clipjob.py cost --seconds 8,6`. workdir = `/opt/data/clips/work/<job>`
8. **Q3 — who drives Flow** (`clarify`, one question, cost in the text):
   `["📝 เตรียม prompt ทีละช็อตให้ (ฟิกกดใน Flow เอง)", "🤖 ให้ไอยูลองทำใน Flow ให้เลย (≈<cost> เครดิต ถ้าติดจะสลับเป็นโหมด prompt ให้เอง)"]`.
   Unanswered / timed out = 📝 (zero spend), for ANY question that would spend credits. An order that says
   ให้ไอยูทำ/กดใน Flow เอง = auto, skip Q3 (cost still on the board). Record: `clipjob.py production <job>
   prompt|auto` right after `new` (refused at `intake`; never `fallback` for this — it locks out `auto`).
   Fix switches to 🤖 after `pack`: tap `🤖 ไอยูกด Flow แทน · <job>` → `clipjob.py decide --text "<text>"`, typed →
   `clipjob.py production <job> auto`; then flow-driver from the shot it names (never after `fallback`).
   Fix changes the shot plan before anything rendered (6+4 s → one 10 s): `clipjob.py reshape <job> --shots N
   [--seconds …]`, rewrite the shot files, pack again — never cancel and reopen.
9. **Shots.**
   - 📝: `clipjob.py pack <job>` sends the reference photos and one tagged prompt per shot. Then wait.
     Each video from Fix: reply to a prompt → `clipjob.py ingest <job> <file> --reply-text "<replied-to text>"`;
     no reply context → ask which shot (buttons), `--shot K` (don't ask when only one shot waits for a file).
     **Fix's file IS his review:** `clipjob.py ready <job> K --raw <file>`, NO vision/idcheck/scan (approved at
     once, no ✅/🔁); a new file replaces an approved shot. Full rules: `references/prompt-pack.md`.
   - 🤖: load skill `flow-driver` and follow it. It calls `reserve`/`submitted`/`submit-failed`/`trouble`.
     Start frame of shot K≥2 = `clipjob.py startframe <job> K` (🧑 skips a last frame without her face;
     `file` null = character chip + refs only). 📝 gets the same pick from `ingest`/`pack`.
     🤖 download fails and Fix sends the mp4: save as `shotK_raw.mp4`, step 10's `ready` (no `ingest`).
     `"FALLBACK": true` printed: close Chrome, one line to Fix (reason, credits, shots left), `pack`, go on as 📝.
     A shot that failed after spending credits gets its own 🔁 button from `submit-failed`; wait for the tap.
10. **Per-shot review (🤖 only — 📝 ended at step 9).** `references/frame-check.md` first. `clipjob.py idcheck
    <job> K --raw <file>` → ONE vision call on its sheet: its `ask_vision` + the frame-check questions (Flow
    text, sub band, scale, planned action). Then `clipjob.py ready <job> K --raw <file> --frame pass|flag:<what>
    --identity match|drift:<part>|count:<2 vs 3 …>|presenter:<face/hair>`. `count:` = a part count differs
    (compartments, buttons, pieces): post cannot fix it, the review puts 🔁 first. ready runs ffprobe + (🧑)
    the repeats/CTA gates and sends ✅/🔁; a failed send → `ready <job> K --resend`. Fix's tap arrives as text →
    `clipjob.py decide --text "<text>"`; if it prints `REFUSED: text is not a review button`, run
    `clipjob.py decide <job> K approve|regen`. Never hand-edit the job JSON. On 🔁 regenerate via flow-driver;
    a regen that repeats the defect = stop: name it, credits spent, zero-credit options, wait for Fix.
    A 🔁 on shot K also asks Fix keep/regen for an already rendered shot K+1 (its start frame is gone); wait
    for that tap too. Shot 2 may render while shot 1 is reviewed only when shot 1 passed every gate.
11. **Post-production (graphics always).** `clipjob.py assemble-check <job>` prints the approved files in order — copy exactly those paths into the workdir (a leftover `shotK_raw.mp4` may be a rejected take).
    - 🧑: `references/presenter-rules.md` + `references/presenter-graphics.md`:
      `autogfx.py fx` → `presenter_fx` → `post_presenter` → `autogfx.py gfx` → `graphics_layer --report … --check`,
      then render. `autogfx` MEASURES every coordinate: never work one out by hand.
    - 📦/✋: `references/product-mode.md`: `product_build.py` (gameplay VO recipe), then
      `graphics_layer --report <workdir>/report.json`.
    - Read `report.json` and every `FLAG:` line. Then make a frame sheet (`references/frame-check.md`) and
      make the cover: `references/poster-cover.md`.
12. **Deliver — one command, nothing else sends the final clip:**
    `clipjob.py deliver <job> --final <final.mp4> --report <report.json> --gfx <gfx.json> --hashtags "<tags>" --cover <cover.jpg> --caption "<short Thai caption>" --hook-id <id> --category <cat> [--notes "…"] [--ack "<flag>=<Fix's call>"]`
    It refuses on an unapproved shot, empty graphics, bad hashtags, a failed verify-clip, a 🎬 end-card title
    cut by the frame edge, or a report flag Fix has not decided (a shot flag he already passed is not one —
    carry it into `--notes`). Each undecided flag: ask with its frame time; as-is = one `--ack "<flag>=<his
    call>"` per flag (`references/prompt-pack.md` → Deliver acks). Never edit `report.json`. A failed send =
    rerun the same command. No extra MEDIA/hashtag text. Last message has 🏁: no cleanup, end the turn (🤖: close
    Chrome first). A 🏁 tap → only `clipjob.py decide --text "<text>"`; no tap = it closes itself in 5 min.
12b. **Close-out with no clip** (Fix orders the skip, `status` shows no shot file): `references/run-mode-gates.md`
   → Close-out. Never stage or imply a clip.
12c. **Re-send of an already-delivered package** (`ขอคลิป hashtag และปักตะกร้า`, `สรุปอีกรอบ`): resolve WHICH
   clip first, read the job's `delivery.sent`, re-run `S/send_copy_buttons.py` — `references/run-mode-gates.md`
   → Re-send.
13. Fix calls it off (`เลิกทำ` / `หยุด` / `พอแล้ว`, or `ไม่ผ่าน` + `ยกเลิก`) → `clipjob.py cancel <job> --reason …`,
    close Chrome, report `spent_shots`. `ไม่ผ่าน` alone is a shot review failure (✅/🔁), never a cancel.

**Vision budget per job**: intake 1 · photo gate ≤2 ·
🤖 shot 1 (+1 full-res confirm of a drift) · 📝 shot 0 · post frame sheet 1 · cover 2 (pick + the
`check_sheet` that `make_poster_cover.py` prints) · 🎬 footage: one sheet per stage. clipjob `note`/`status` print
`vision N/budget`; past it: decide + `note`. Every call counts (locator, chip zoom, screenshot reads):
`references/house-rules.md` → Vision budget.

## Talking to Fix
- One status line when something blocks, sent at that moment, not at the end. Put the credit cost inside
  any question that spends credits. Short "ok/ได้" to your own go/no-go question = yes.
- **A long silent stretch also needs a line** (post, 🤖 browser drive, per-shot frame review): one short
  line at each stage transition — `references/house-rules.md` → Status lines.
- He reads on the phone: buttons over typing, no walls of text, never ask him to check a UI.
- **A real `FLAG` needs his call: ask once with `clarify`, then end the turn and wait** (no re-ask, no `--ack` for him).
- Senders parse no flags: `S/send_status.py` posts its FIRST argument verbatim, so never probe one with `--help`.
