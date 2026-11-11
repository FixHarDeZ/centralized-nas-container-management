# House rules for Shopee clips (all modes)

> Read once per session before the first order. Short rules here; the incidents and measurements behind them
> are in `references/house-rules-history.md`. Orders come only from Telegram; job state lives in `clipjob.py`.
> Script paths: `/opt/data/skills/shopee-clip/scripts/` (Flow helpers: `/opt/data/skills/flow-driver/scripts/`).
> Runtime data: `/opt/data/clips/logs/` (clip-log, delivery-log, perf-log), `/opt/data/clips/flow-state/<project-id>.json`
> (known edit ids, roster, last character), `/opt/data/clips/work/<job>` (job workdirs).

## Credits
- ~1.5 credits per second at 720p (measured 4 s = 7, 8 s = 12, 10 s = 15). PRO = 50/day ≈ 33 s of finished clip.
  Read the live `Generating will use N credits` line when it is visible; quote only numbers actually read. The narrow
  layout shows no balance: say "remaining unknown" rather than estimating.
- 40 s (≈60) exceeds the daily quota on its own: read the live cost and tell Fix before submitting.
- Never edit inside Flow (40 credits per edit). Never retry a failed submit with his credits without saying so.
- Credit approval is per product and per question; put the cost inside the question text.

## Running an order
- **After the order, run end to end without per-step confirmation** (Fix: "หลังผมสั่งครั้งแรกทำตั้งแต่ต้นจนจบได้เลยนะ").
  The standing gates still hold: storyboard approval, per-shot review, cost in any spending question
  (`references/run-mode-gates.md`).
- **Tell Fix early when something blocks.** At most ONE silent retry; a second failure (refusal, Failed card, login wall,
  dead picker) gets a short status at that moment: what failed, what you tried, what is next, whether credits moved.
  Also send one line at each long silent stage (Chrome up, post-production start).
- **Poll through to delivery in the same turn.** Do not end on "still generating" when you could keep watching.
- **First `unusual activity` card → stop driving Flow** (clipjob falls back to the prompt pack; `flow-browser-env.md` →
  Manual mode). No retry, no cookie clearing.
- **Fix cannot inspect the Flow UI.** Verify from the DOM and read-backs and report results as text; never ask him to look.
- **When he says it is slow, give the split.** A measured 10 s run took 47 min end to end with ~12 min of render; the rest
  was image prep, chip cycles, vision reads and an upload timeout. Do image prep while the render runs and batch vision reads.
- **A queue of clips:** start clip N+1's submit before composing clip N's delivery (clipjob paces submits across jobs).
  Compute clip N+1's hook and character only after clip N's log row is written, and frame-check every clip on its own.
- **Called off (`เลิกทำ` / `หยุด` / `พอแล้ว`):** `clipjob.py cancel`, no clip-log row. There is no cancel control in Flow:
  a queued render may still finish server-side, so say so. Record the abort (edit ids opened, the reason) in the
  flow-state file, close Chrome with CDP `Browser.close` (pkill only when CDP is dead), verify `:9222` is gone, and
  report spend honestly ("unreadable" is not 0).

## Talking to Fix
- **An unanswered, timed-out or cancelled question = the zero-spend option**, re-asked at most once. A reply that carries
  images or prose but no chosen option is input, not an answer: use the material, re-ask once, hold at zero spend.
- **A short "ok" / "ได้" to your own go/no-go question is a yes.** Do not re-ask.
- **Reference images with no order are input, not a job.** Ask once (new clip / use in an open job / just keep). Ad-style
  images (headline text, staged lifestyle shots) are storyboard input only; apply that default and say so in one line.
- **Answer repeated image sends once per batch**: one short line per image (usable or not, what is still missing).
- Once an order is clear, never repeat a question across several image messages.

## Style standard (every clip)
- Female presenter, cute tone, no hard sell; modern Thai teen slang (ปัง, เริ่ด, ของมันต้องมี, ดี๊ดี, คุ้มเว่อร์), not cringe.
  Prompt wording for the presenter: `references/presenter-rules.md` → Presenter prompt style.
- Caption pills are ours (post-production, EN/คำยืม ≤2 words); **Flow renders no on-screen text at all**.
- Short but interesting (Fix: "คลิปไม่ต้องยาวแต่น่าสนใจ"). Structure: short hook → 1–2 selling points → soft CTA.
- Vertical 9:16, Thai voiceover, sound on. No shop name or wordmark on screen, and never ask Fix for one (2026-10-26).
- Per-run artifacts: `templates/style-card.md` block in every prompt; hook by category, least recently used
  (`perf.py pick-hook`, never the same `hook_id` for a category within 5 rows); hashtags from the category pool in
  `templates/hashtags.md` (4 product + 3 vibe + 1 platform).
- Presenter build = graphics v2 (default since 2026-11-07): `presenter_fx.py` → `post_presenter.py` →
  `graphics_layer.py --report report.json` (`references/presenter-graphics.md`). Product stills are cut-out stickers
  beside the presenter, never full-screen cards that hide her.
- Style reference: Shopee Video `sv.shopee.co.th/share-video/KUNZuOMsCgCKQAICAAAAAA==`.

## Storyboard gate (Flow modes)
- No Flow generation before Fix approves the board (`templates/storyboard.md`). Reason: two 10 s "hold / press / set down"
  takes read as filler; every shot must show the product working.
- Shots chain (shot K+1 starts from shot K's last frame) and are submitted ≥5 min apart (Fix: "นานหน่อยแต่คุณภาพดี").
- The frame check asks of every shot: did the planned action happen? did the product keep its shape and size? No = defect.

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
