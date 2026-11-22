# House rules for Shopee clips (all modes)

> Read once per session before the first order. Short rules here; the incidents and measurements behind them
> are in `references/house-rules-history.md`. Orders come only from Telegram; job state lives in `clipjob.py`.
> Script paths: `/opt/data/skills/shopee-clip/scripts/` (Flow helpers: `/opt/data/skills/flow-driver/scripts/`).
> Runtime data: `/opt/data/clips/logs/` (clip-log, delivery-log, perf-log), `/opt/data/clips/flow-state/<project-id>.json`
> (known edit ids, roster, last character), `/opt/data/clips/work/<job>` (job workdirs).

## Credits
- **Model = Omni 1.2 Flash** (Omni 1.1 Flash and Veo 3.1 Fast/Quality leave Flow on 2026-12-05; Veo 3.1 Lite stays,
  4/6/8 s, cost not known here). 720p = 3 credits/s for seconds 1–10 — **now measured on Fix's account** from the
  Settings panel's `Generating will use N credits` (Omni 1.2: 6 s → 18, 7 s → 21, 8 s → 24; Omni 1.1 measured
  cheaper at 1.5/s: 8 s → 12). Still unmeasured here: 6/s for seconds 11–15 and the 360p rates (1/s, 2/s for
  11–15) — third-party write-ups only. So 720p: 6 s = 18, 8 s = 24, 10 s = 30, 15 s = 60. Estimate with
  `clipjob.py cost --seconds 8,6`. Every account has 50/day (≈16 s at 720p); Pro adds 1,000/month.
- **Spend less on 1.2 (twice the 1.1 price):** (1) a shot is as long as its speech needs (~4 Thai syllables/s):
  6–8 s is normal, 10 s only when the line fills it — pass `--seconds`. The clip is the SUM of its shots (post
  adds no seconds: cards and end cards are overlays), so a "20 วิ" order planned as 8 + 8 is a 16 s clip for
  ≈48 instead of ≈60; put the real total on the board and let Fix approve it. (2) Never 11–15 s: two shots are
  cheaper. (3) One regen that repeats the same defect = stop and ask (router step 10); gta6 2026-11-14 paid three
  generations for the same wrong cover. (4) A product Flow cannot hold (new game cover art, rigid rack) is not
  fixed by a reworded prompt: offer 🎬/📦 or a post insert of the real photo. A 360p generation saved at 720p
  is reported as a third of the price but softer, and is untested here: only when Fix says so (`cost --res 360p`).
  A shot under 10 s has not been through post yet (first one: check subs/graphics timing by eye).
- **The board's quota line = Flow's LIVE balance + its reset date** (account menu → `Account details` →
  `N Google Flow credits`, `Resets <date>`; `flow-driver` → `flow-browser-env.md`). The account pools credits
  far above 50/day (282 left on 2026-11-22), so never write "ต้องรอรอบโควต้า" from a 50/day sum; only when the
  live figure is below the plan. Spend per job: clipjob records it (📝 = the published rate per shot length,
  `credits_est` in the row, since 2026-11-22), so no figure is needed in `--notes`.
- Never edit inside Flow (40 credits per edit). Never retry a failed submit with his credits without saying so.
- **Never pre-run `verify-clip.py` before `deliver`** (its copy in Downloads makes `deliver` refuse as a resend);
  if it already ran, delete that copy from both Downloads dirs and re-run `deliver`.
- Credit approval is per product and per question; put the cost inside the question text.
- **Reported spend = the clip-log row's `credits`** (every attempt, regens included); never shots × a rate.

## Running an order
- **After the order, run end to end without per-step confirmation** (Fix: "หลังผมสั่งครั้งแรกทำตั้งแต่ต้นจนจบได้เลยนะ").
  The standing gates still hold: storyboard approval, per-shot review, cost in any spending question
  (`references/run-mode-gates.md`).
- **The job row exists from intake** (`clipjob.py intake`, router step 0, since 2026-11-19): before it a 🧑 job had
  no row until the board was approved, and after a mimo `content_filter` refusal wiped the history (nual-loop-240w
  2026-11-18: every such refusal so far left the next turn with `history=0`) Hermes spent 46 min rebuilding the job
  from `session_search`. `note` each stage; save the board you sent as `<workdir>/board.txt`. A resumed session
  reads `status` (`stage`, `last`) and the workdir, never re-runs intake or re-asks Q1/Q2.
- **A long command runs in the foreground with `timeout` ≤ 600.** Above the 600 s cap the terminal starts it as a
  background process and says so (`promoted_from_foreground` … "Do NOT re-run it"); then poll it with
  `process_manage(action="poll", session_id=…)` or read `/opt/data/clips/logs/heavy-log.jsonl` for its `end` row —
  never `pgrep -f <name>` / `ps | grep` (the shell running the check matches itself: honma-gt6-gp 2026-11-18 polled
  a `build_v5` that had died in 2 s for 17 min), never a sleep loop inside `execute_code` (its cell dies at 300 s).
  `build_v5` ≈ 70 s, `windows.py` 0.5–5 min, `post_presenter` 2–15 min.
- **Pass `workdir` (`/opt/data`) to every terminal call**, also from `execute_code`: a stale cwd of a cleaned
  workdir fails before the script runs (`bash: cd: … No such file or directory`, exit 126).
- **Tell Fix early when something blocks.** At most ONE silent retry; a second failure (refusal, Failed card, login wall,
  dead picker) gets a short status at that moment: what failed, what you tried, what is next, whether credits moved.
  Also send one line at each long silent stage (Chrome up, post-production start) — `python3 S/send_status.py "<line>"`
  sends it without ending the run (do not hand-roll the Bot API call each time).
- **Poll through to delivery in the same turn.** Do not end on "still generating" when you could keep watching.
- **First `unusual activity` card → stop driving Flow** (clipjob falls back to the prompt pack; `flow-browser-env.md` →
  Manual mode). No retry, no cookie clearing.
- **Fix cannot inspect the Flow UI.** Verify from the DOM and read-backs and report results as text; never ask him to look.
- **When he says it is slow, give the split.** A measured 10 s run took 47 min end to end with ~12 min of render; the rest
  was image prep, chip cycles, vision reads and an upload timeout. Do image prep while the render runs and batch vision reads.
- **A queue of clips:** start clip N+1's submit before composing clip N's delivery (clipjob paces submits across jobs).
  Compute clip N+1's hook and character only after clip N's log row is written, and frame-check every clip on its own.
- **A new ORDER arriving while another job is mid-run:** capture it at once — `intake` + a note
  `gated until <job> delivered` — then finish the open job first. Intaking immediately is what survives a context
  loss; the gate keeps one heavy job at a time and stops the two jobs' submits/paces from interleaving.
- **Called off (`เลิกทำ` / `หยุด` / `พอแล้ว`):** `clipjob.py cancel`, no clip-log row. There is no cancel control in Flow:
  a queued render may still finish server-side, so say so. Record the abort (edit ids opened, the reason) in the
  flow-state file, close Chrome with CDP `Browser.close` (pkill only when CDP is dead), verify `:9222` is gone, and
  report spend honestly ("unreadable" is not 0).

## Talking to Fix
- **An unanswered, timed-out or cancelled question = the zero-spend option**, re-asked at most once. A reply that carries
  images or prose but no chosen option is input, not an answer: use the material, re-ask once, hold at zero spend.
  A FLAG question follows the same rule (after the one re-ask times out, run `deliver` with
  `--ack "<flag>=zero-spend default (clarify timed out)"`) — the ack value must state it is the timeout default,
  never pretend Fix chose it.
- **A short "ok" / "ได้" to your own go/no-go question is a yes.** Do not re-ask.
- **Reference images with no order are input, not a job.** Ask once (new clip / use in an open job / just keep). Ad-style
  images (headline text, staged lifestyle shots) are storyboard input only; apply that default and say so in one line.
- **Answer repeated image sends once per batch**: one short line per image (usable or not, what is still missing).
- Once an order is clear, never repeat a question across several image messages.
- **Run the CJK/full-width scan over EVERY outbound Thai message too** (clarify questions, status lines), not just
  hashtags and prompts: a stray full-width/CJK pair typed into a Thai sentence goes out verbatim and reads as
  corruption to Fix. The same codepoint check from the hashtag gate is one line before `send_status.py`/`clarify`.
  **Run it on the exact string in the same call that sends it** — scanning a draft and then re-typing the message is
  how a clean scan ends up checking a string other than the one that goes out. On a miss, resend the corrected line
  immediately and name the wrong word; do not leave the corrupted line as the last word.

## Style standard (every clip)
- Female presenter, cute tone, no hard sell; modern Thai teen slang (ปัง, เริ่ด, ของมันต้องมี, ดี๊ดี, คุ้มเว่อร์), not cringe.
  Prompt wording for the presenter: `references/presenter-rules.md` → Presenter prompt style.
- Caption pills are ours (post-production, EN/คำยืม ≤2 words); **Flow renders no on-screen text at all**.
- Short but interesting (Fix: "คลิปไม่ต้องยาวแต่น่าสนใจ"). Structure: short hook → 1–2 selling points → soft CTA.
- Vertical 9:16, Thai voiceover, sound on. No shop name or wordmark on screen, and never ask Fix for one (2026-10-26).
- **Speak a brand name in the voiceover only when its Thai reading is certain**; otherwise name the product type
  (the wordmark is on the product in frame anyway). When two vision reads of the same printed wordmark name
  different brands, the mark is illegible at that resolution — keep it out of VO and pills, and judge product
  identity by shape, colour and counts instead.
- Per-run artifacts: `templates/style-card.md` block in every prompt; hook by category, least recently used
  (`perf.py pick-hook`, never the same `hook_id` for a category within 5 rows); hashtags from the category pool in
  `templates/hashtags.md` (4 product + 3 vibe + 1 platform).
  The category argument is the `hooks.md` section id (`game|gadget|home|beauty|fashion|food`); an id outside that
  set returns `no candidate hook ids` with no list — read the `##` sections of `hooks.md` to get the id, don't
  invent one from the product noun.
  When the picked hook's subject does not fit the product (a desk line for a wearable), keep the returned
  `hook_id` and swap only the subject noun — the LRU tracks ids, not wording, so a rewritten line with the
  original id keeps the history intact; do not re-pick for a subject mismatch.
  For a placeholder that must name ANOTHER game (`gph-1`'s `<เกมที่คล้าย>`), choose by genre *and* by how certainly
  the name reads in Thai (the brand-name rule above): sharing the genre is enough — the technically closest title is
  the wrong pick if its Thai reading is uncertain, and the id still stays. The same holds for a verb that
  contradicts the product's state: `gph-3` ("ต้องพรีฯ") is wrong once the game is already on sale → swap that
  verb only (ต้องมี / ต้องโดน), keep the id, and name the change in the delivery notes.
- Presenter build = graphics v2 (default since 2026-11-07): `presenter_fx.py` → `post_presenter.py` →
  `graphics_layer.py --report report.json` (`references/presenter-graphics.md`). Product stills are cut-out stickers
  beside the presenter, never full-screen cards that hide her.
- Style reference: Shopee Video `sv.shopee.co.th/share-video/KUNZuOMsCgCKQAICAAAAAA==`.

## Character pick (🧑)
- **Pick the face from `clip-log.jsonl`, never from flow-state's `last_character_used`.** That field is only
  written when the agent drives Flow, so a 📝 prompt-mode run never updates it and it lags behind the newest
  `character` value in clip-log — reading it alone repeats the face Fix already saw in the last clip. Take the
  newest `character` row in clip-log, exclude that name, choose at random from `character_roster` in
  `/opt/data/clips/flow-state/<project-id>.json`, and name the pick on the board.
- **Draw only from female roster names that have a portrait** in `/opt/data/clips/characters/` (male ones,
  e.g. น้องเอิร์ธ, were made for one order: clip-log `notes` say `ตัวละครชาย`). A male pick only when Fix asks.
- **Write the prompt's presenter line from that character's recorded look (flow-state `roster_note`), never her
  NAME and never a generic "young Thai woman"** (champion-trashbag-roll 2026-11-22: the male น้องเอิร์ธ came back a
  woman, and Flow painted the name on the wall). `new` refuses a name with no portrait; `pack`/`reserve` refuse
  a name in the prompt outside the quoted voiceover.

## Storyboard gate (Flow modes)
- No Flow generation before Fix approves the board (`templates/storyboard.md`). Reason: two 10 s "hold / press / set down"
  takes read as filler; every shot must show the product working.
- Shots chain (shot K+1 starts from shot K's last frame) and are submitted ≥5 min apart (Fix: "นานหน่อยแต่คุณภาพดี").
  🧑: a last frame without her face (a hands-only close-up) is never a start frame — `clipjob.py startframe` /
  `ingest` / `pack` take the newest earlier shot whose last frame shows her (facecheck.py, Haar), or none (character
  chip + refs only). uneed-pb-1 2026-11-18: shot 3 started on hands-only shot 2 → a new woman three gens running.
- The frame check asks of every shot: did the planned action happen? did the product keep its shape and size? No = defect.
  The product half is code-gated: `ready` refuses a Flow shot with refs until `clipjob.py idcheck` made the
  refs + 6-frame sheet of THAT file and `--identity match|drift:<what>` records the verdict (aukey-pby92
  2026-11-18: the powerbank morphed between 2 s and 5 s; a 3-frame check with no reference passed it to Fix).

## Skill sync
- Source of truth is the repo: `centralized-nas-container-management/hermes-agent/skills/`. Every sync overwrites
  the three skills (shopee-clip, flow-driver, gameplay-clips) and refuses while an in-place edit is not pulled
  (`sync.sh --pull`). To keep a change: edit the clone, commit, push, then
  `cd /opt/data/centralized-nas-container-management && bash hermes-agent/skills/sync.sh` (tests run first), or
  ask Fix for `make hermes-skills`.

## CTA
- CTA words (ลิงก์ / ใต้คลิป / คำอธิบาย / พิกัด / ตะกร้า) only in the last shot, spoken or on screen. Write the prohibition
  into every non-final shot prompt as its own line; clipjob's CTA gate checks the ASR, and the frame check samples the
  last ~1 s of every non-final shot (the HUAWEI GT 7 run rendered `ลิงก์อยู่ในคำอธิบาย` at 9.65 s anyway).
- Heavy-content clips (many feature lines, dense spec or use-case shots) skip the CTA entirely and leave the link to the
  caption/basket. Decide per clip and state the call in the delivery.

## HARD RULE — never mention price
- **ห้ามพูดถึงราคา/ตัวเลขเงินเด็ดขาด** (no "2,390", no "ราคาดี๊ดี", no Baht figures, spoken OR on screen). Fix:
  "ไม่อยากให้พูดถึงราคาเลย" (2026-09-27). Soft CTA only ("ลิงก์อยู่ใต้คลิปนะ" / "ไปดูรายละเอียดกันได้เลย").
- **Input images too:** never attach a photo that carries its own price/promo text; say which ones you dropped.
- **Shipping is not a price:** "ส่งฟรี" may appear on screen only when Fix's brief supplies it; Baht figures, discount %,
  cashback amounts and crossed-out prices stay out.
- **Dates are not a price:** a pre-order/release date may appear — but 🎬 has its own rule: no countdowns and no dates in
  the voiceover (`gameplay-clips` → Voiceover rule).

## Claims, specs and references (always on)
- **No size, dimension, capacity or load numbers**, spoken or on screen, unless Fix's brief supplies them for this clip.
  Drop them even when a photo prints them, and name what you dropped in the delivery. Conflicting specs across listing,
  ad and label are omitted until Fix picks one.
- **Claims come from the product's own label or a source Fix confirms, never from ad copy.** Efficacy, medical
  ("99.9%", a hospital seal), child-safety, durability, load-bearing and award claims stay out of voiceover, pills and
  subs. Crop claim text out of attached art; when label and ad disagree, follow the label and keep the number out.
- **คำที่ฟิกเขียนเองก็ต้องผ่านเกต label เหมือนกัน:** ถ้า hook/บรรยายของเขาบอก attribute ที่ label สินค้าขัด
  (เช่น "แผ่นล็อตใหม่" ทั้งที่สินค้าเป็นโค้ดในกล่อง) → คงเจตนาไว้ เปลี่ยนแค่คำที่ขัด แล้วบอกสิ่งที่เปลี่ยนใน
  delivery — ห้ามพูดซ้ำคำที่ label ปฏิเสธ และห้ามเปลี่ยนเงียบ ๆ โดยไม่บอก.
- **Shopee listing links usually hit a login wall.** Build the brief from Fix's text and images; never take price, stock
  or spec from an unreadable listing.
- **Ad screenshots are storyboard input, not attachable references.** Vision-check every image for price, QR,
  watermark, claim text and the product's full silhouette; crop only inside clean product area. A reference under
  ~1000 px is a drift risk: say so, and accept it only when Fix does (router step 5,
  `references/product-image-prep.md` → Small-source crops).
- **An image with a real child or other person is not a salvage source.** If the product touches or sits beside a body,
  drop the image and ask for a product-only photo: Flow refuses person-bearing references, and a child's pixels must
  not reach the model.

## Encoding (delivery)
- Every delivered clip is High / yuv420p / L4.0 with faststart; a multi-scene stitch must set
  `-pix_fmt yuv420p -profile:v high -level 4.0` on the output (Facebook Reels rejects `High 4:4:4 Predictive`).
  `verify-clip.py` checks this and `clipjob.py deliver` runs it; a 4:4:4 reading = re-encode, never deliver.

## Status lines (long silent stretches)
- **A long silent stretch also needs a line.** Post, the 🤖 browser drive and the per-shot frame review can run
  15+ min with nothing to ask: send one short line at each stage transition ("Chrome ขึ้นแล้ว → กำลังแปะ chip",
  "ช็อต 2 มาแล้ว → กำลังสแกน/รีวิว"). Silence on his phone reads as the run having died.
- **The line for a stage goes out when the stage STARTS, not when it ends — every mode, 🎬 included.** 0 credits
  still means 20–40 min of sourcing, OCR, gates and post with nothing to ask. Keep ≤ ~5 min between two lines:
  he reads the gap, not the progress, and a silent first stage pulls "ยังทำอยู่เนาะ / ทำไมเงียบไป" out of him while
  the run is in fact healthy.
