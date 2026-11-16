# Preset: presenter + graphics (Fix 2026-11-07)

Fix's order: keep OUR subtitle style for all Thai subs, and add a preset that combines the presenter with graphics.

**Graphics v2 is the DEFAULT for every presenter clip.** Fix chose it over the plain build in an A/B, with one change: *"ภาพนิ่งที่แทรกขอ crop แค่รูปสินค้าวางบนจอให้ไม่บัง presenter"*.
- Every product still (hook card AND inserts) uses `presenter_fx.py` `"mode": "overlay"`: the product is cut out (edge flood-fill bg removal + white sticker border + shadow), slides in and bobs.
- Place it in the empty backdrop beside her. Read that rect off real frames with vision first; for Flow presenters it is usually the right side, centre x≈615–625, y≈380–405, h 225–270.
- **Check the rect at BOTH ends of its window.** She walks across the frame, so a rect that is empty wall when the overlay starts can sit on her by its end: vision-read the drawn rect on a frame at the start AND on the last frame of the window, then cap `dur` at the last clean frame instead of letting the sticker cover her.
- Never use a full-screen card that hides the presenter.
- Keep sparkle/heart stickers ≥20 px away from the cutout's edge, or they read as crammed.
- With a hook overlay, set `"trim": [0, "auto"]` in the post_presenter plan.

## Subtitles (unchanged)
- Itim 48, pastel yellow `&H0066D1FF`, dark brown outline `&H00203050`, Outline 5, Shadow 2.5.
- `BorderStyle=1` (no box), Alignment=2, burned with `ass=...:shaping=complex`.
- Do NOT switch to the reference clip's style.

## Pipeline order (all post-production, 0 credits)

### Coordinates come from `scripts/autogfx.py`, not from reasoning (2026-11-16)
On hatari-s14m1 the post scripts ran for about 2 minutes while the model spent 81 minutes working out face boxes,
the hook card rect, punch centres and sticker spots. `autogfx.py` measures all of them (layout_probe's face
detection and free-wall mask, plus a texture mask so a white product or cream knitwear is not taken for wall):

```
R='uv run --with opencv-python-headless<5 --with numpy python /opt/data/skills/shopee-clip/scripts/autogfx.py'
$R fx sceneN_cut.mp4 --out fx1.json --hook --product ref1.jpg     # scene 1: hook card + punch (step 1 input)
$R fx sceneN_cut.mp4 --out fx2.json                               # later scenes: punch only
$R gfx out.mp4 --report report.json --out gfx.json --fx1 fx1.json # after post_presenter (step 3 input)
```

- About 20 s per call. Each prints the plan it wrote and a `skipped` list. On the real hatari shots its hook card
  and punch came within 10 px of the hand-made ones.
- **A skipped element is left out on purpose** (no face found, she leans into the camera, no free wall because the
  product fills the frame). Do not fill the gap with a guessed coordinate. A clip with one sticker is fine. Only
  `NO sticker placed` needs you: add ONE element by hand with step 0b's probe, because `deliver` refuses an empty plan.
- Add what the product needs on top (a callout on a close-up, a headline): keep the numbers already in the file.
- The gates after it are unchanged: `graphics_layer.py --check`, then ONE vision look at a frame sheet of the
  render (each sticker's start + 0.3 s). The check that the hook card is clear at both ends of its window is
  already inside `fx` (it probes 0–1.4, 0–2.0, 0–2.5, 0–3.0 s and keeps the last window that fits).
- Steps 0b, 1 and 3 below describe the same maths for the cases you place by hand.

### 0a. `scripts/detect_repeats.py scene_raw.mp4 --script prompt_sN.txt --cut sceneN_cut.mp4` (every raw scene, one at a time)
**Skip the run when the job JSON already has `gates.repeats` for that shot — `clipjob.py ready` runs exactly this detector on every 🧑 shot.** Read the verdict instead of paying a second whisper pass over every scene: `note: ""` = clean (use `shotK_raw.mp4`), `note: "ตัดคำซ้ำแล้ว: …"` = the `_cut.mp4` exists and is the file to feed step 1. Only run it yourself when a scene arrived outside `ready` (no gate in the JSON).
Run it as `uv run --with faster-whisper --with numpy python …`. It runs unprompted word-level ASR and looks for ADJACENT doubled phrases that the script does not contain twice.
- exit 3 = repeat found and cut (0 credits). Use `sceneN_cut.mp4` from here on and NAME the cut in the delivery (text + seconds removed).
- exit 0 = clean.
- Proven on ENFANT scene 2: it found `สเต็ปง่ายๆ` ×2, cut 5.792–6.458 (identical to the manual cut), and a re-probe of the cut file came back clean.
- It replaces the manual "unprompted ASR" gate in `presenter-post.md`.

### 0b. `scripts/layout_probe.py scene.mp4 --window S E [--window …] --product <crop.jpg>` (placement without vision rounds)
Run it as `uv run --with "opencv-python-headless<5" --with numpy python …`. **Pin <5: opencv 5 ships no Haar cascades.**

One JSON line per window:
- `face`: Haar union. Use it as the `avoid` rect — but that box is in RAW time: for `graphics_layer`'s `avoid` on the final `out.mp4`, re-probe there (step 3), because punch and xfade move it.
  - A `face` box in a scene that has NO face (hands-only close-up) is Haar firing on skin or a lit panel — keep it as `avoid` anyway: it marks the action area, and centred text landing on the hands reads as covering the subject just as a face hit does.
- `empty_left` / `empty_right`: the backdrop rect free in EVERY sampled frame, inside y 260–640.
- `overlay`: {x, y, h} for the product cutout, sized to its aspect. When `note` says the side is too small → skip or shorten that overlay.

It is CONSERVATIVE: the mottled wall makes it reserve more than vision does, e.g. h 94 where vision allowed ~240. When it says too small but you need the overlay, one vision read of that window may overrule it. Still vision-check one frame of the final render.

- **Sample only times strictly inside the scene**: keep the window END ~0.5 s under the duration (`--window 0 9.5` on a 10 s scene). A sample at or past the duration returns an empty frame and the run dies with `ValueError: cannot reshape array of size 0 into shape (1280,720,3)` — that is a window problem, not a broken video.
- **When it answers `no empty side big enough`, do not go hunting for the rect with vision reads.** Build the free-rect map instead (Lessons → *Free-rect map*); spend vision on checking the render, not on locating empty wall.

### 1. `scripts/presenter_fx.py scene_raw.mp4 fx.json scene_fx.mp4`
Run once per RAW scene, BEFORE post_presenter. It touches video only and copies audio, so duration, ASR and sub timing are unchanged.
- `hook_card` (`"mode": "overlay"`, ~1.4 s): a cut-out product sticker appears beside the presenter from frame 0. Dur: aim ≥3 s (a 1.2 s card reads as a flicker), but the last clean frame of the rect — the both-ends check above — is the hard cap.
- `punch`: snap zoom ≤1.15 on each new selling point. (cx,cy) = the face or the product in hand.
  - **Verify head clearance by measurement, not by a side-by-side read.** Extract the same t from raw and fx, take the topmost dark-hair row in each (luminance < 90 over the head columns), and read ONE y-gridded top crop: a raw-vs-fx comparison reports `hair cut flat by the top edge` even when the crop keeps headroom, and a false clip verdict costs a re-render of the scene.
- `inserts` (`"mode": "overlay"`, 1.2–1.5 s): put one on a word that names the product or its label art.
  - Without `mode` you get the old full-screen card. Use that only to hide a seam or a looped phrase, because it hides the presenter.
- Source images must be CLEAN crops (no price/QR/claims, see `product-image-prep.md`), on a plain light background so the flood-fill cutout works.
- Input is the step-0a output (`sceneN_cut.mp4` when a repeat was cut), so post_presenter aligns to the corrected audio.
- Overlay x/y/h come from step 0b's `overlay` field for that window — but fit them to the cutout's own canvas math BEFORE trusting that `h`: `cutout_png(h)` returns `w = round(src_aspect × h) + 42` by `h + 42` (21 px of outline padding per side), and the overlay then slides up 40 px at `t=start`. So the rect to verify is the UNION of the settled and the slid positions, its centre must satisfy `x0 ≥ empty_left` and `x0 + w ≤ 715` (the overlay never clamps, so a centre near the right edge clips the sticker's border off-frame), and `h ≤ empty_h − 42 − 40` — plus the WIDTH bound `h ≤ empty_w − 42`, which binds first for a square cutout (canvas `w = h + 42`): a 110 px-wide strip of wall caps `h` at 68 no matter how tall the rect is. Check that union on frames at BOTH ends of the window.
- **The probe's own `overlay.h` and `note` are NOT the verdict.** It can print `note: null` ("fits") while suggesting an `h` above the cap that this same rect allows — recompute the cap from `empty_*` with the math above and shrink its suggestion to fit; the canvas math wins.
- **Find the hook card's `dur` by probing successive windows, not by picking a duration.** The empty side shrinks as she moves, so run `--window 0 1.4 --window 0 2.0 --window 0 2.5` and take the LAST window whose rect still passes the cap: that window's end is the hard `dur` cap, and a card sized for the first window clips or covers her by its end.
- Keep every `punch` window OUT of the hook card's window: punch re-frames the base video while the composited sticker stays at fixed coordinates, so an overlap drags her arm under a sticker you already cleared.

### 2. `post_presenter.py`
Run it as before, with each scene's `video` pointing at its `scene_fx.mp4`.
- Read the FLAG lines and `report.json`.

### 3. `scripts/graphics_layer.py out.mp4 gfx.json final.mp4 --report report.json`
Run `--check` first. Exit 2 = a layout violation; fix the plan before rendering.

Elements:
- `headlines`: Thai, ≤2 lines.
  - Styles: `pop|stamp|bounce|wipe` (rotate them across clips).
  - `hl` = the keyword highlighted in pink.
- `stickers`: ASS vector shapes `sparkle|heart|arrow|check|ring|star|burst`.
  - Animations: `pop|twinkle|bounce`.
- `callouts`: ring on a product part + leader line + EN label.
  - The label is ≤2 words, ASCII, nothing money-shaped.
- `badges`: ①②③ feature numbers.
- `endcard` (`x` = card centre, `arrow_y`): the product card drops in on the last beat, with a bouncing arrow.
  - It goes WITH the `Link below!` pill, not instead of it.
  - Skip it when the presenter already holds the product at the CTA: two bottles on screen read as redundant clutter. Use only a bouncing `arrow` sticker beside her pointing hand.
- `cover`: a twinkle sparkle over Flow's lower-right sparkle mark. **Prove the mark exists before placing it:** Flow's overlay is static, so tile the SAME corner crop from 4 frames far apart in one sheet — a real mark sits at identical coordinates in all four while scene content moves. Shifting coordinates across reads, or NONE in all four, mean no mark: drop the `cover` element (`gfx_elements` does not count it, so the plan still passes `deliver`) instead of sparkling a guessed coordinate.
- `avoid`: the presenter face box.
  - **Probe it on `out.mp4` itself, in final-clip time** (`layout_probe out.mp4 --window S E …`, one window per gfx span): step 0b's boxes are RAW-scene coordinates, and `punch` zoom plus the xfade shift every face rect — carrying a raw box over (even + the scene's global start) lands the headline on her cheek. Fall back to a vision read only when the probe finds no face.
  - Flow presenters sit centre-frame, so headlines at the old default y=300 land on the face.
- Auto SFX: pop/twinkle at each element plus a whoosh on the endcard.
  - Mixed at gain 0.35 under a limiter at 0.63 (AAC overshoot otherwise lands the max at exactly −3.0 dB).

### 3b. Cover (every clip, presenter AND gameplay)
1. `uv run --with pillow --with numpy python scripts/make_cover.py --video sceneN_fx.mp4 --t <moment with face + product> --text "<BRAND PRODUCT ≤3 words EN>" --cy 0.45 --color green|pink|… --out cover.jpg`
   - The source must be a PRE-subtitle render.
   - When the clip carries an accepted defect ON the product (a redrawn cover), take `--t` from a moment where the product is out of frame: the post thumbnail is the first thing a viewer sees, so do not feature the flaw there.
   - `--cy` takes a FRACTION of H (0–1), NOT pixels: `--cy 1150` is read as 1150×H, clamped to the safe-zone floor, and prints the identical `block centre y=` line whatever large value you pass — a pixel figure in the old instructions was a silent no-op. Pass `--cy 0.45` (or leave `auto`) and take the printed `block centre y=…` line as the only proof the block moved. Auto picks the least-detail band: it landed on her torso, clear of the face, where the default sat on her chin.
   - **When the box lands on the product's own identity art (a game case's cover), the fix is another `--t`, not a lower `--cy`** — the safe-zone clamp is the floor, so `--cy` cannot push it further down. Render two candidates (`--t` where the product is held up vs where it sits on the table), put them side by side in ONE vision sheet and take the frame where face AND product art are both clear; the losing render costs nothing.
   - The title box can cover the bottle's label (measured on a Pureen cover: the box took the label's middle, and the vision check failed label visibility). Before sending, check the label is readable; if not, keep the box clear of the label area with a shorter title or a lower `--cy` and re-check. Untested alternative: move `--cy` lower, not verified yet.
   - Pick a box colour that contrasts with the wall (pink-on-pink blends in). The `--color` choice set is exactly `blue|green|pink|purple|yellow` — argparse rejects anything else, so an orange-capped product takes `yellow` (the colour it invites, `orange`, is not a choice).
2. Vision-check: face clear, label mostly visible, no price.
   - **Check the printed `main WxH` line too:** when `W > 1080` the title runs off the canvas and the vision
     check reads it as truncated text — shorten the title and re-run before sending.
3. **Cover sending — one sender only.** When the clip goes out through `clipjob.py deliver --cover cover.jpg`, deliver sends the cover ITSELF (its step list runs `send_photo.py`, one ledger row `kind: photo`): do not pre-send it here, or Fix receives the cover twice. The manual `python3 scripts/send_photo.py cover.jpg "<caption>" 8663614341 <label>` → ok + message_id line is for a hand-built delivery (the `send_clip.py` path) only — check_delivery stays clean either way as long as exactly one photo row exists.
- make_cover now uses `FredokaSB-Static.ttf`: the variable Fredoka loads a thin default instance in PIL.

### 4. Check and send
1. Run `verify-clip.py` on final.mp4.
1b. `uv run --with pillow python /opt/data/skills/gameplay-clips/scripts/sub_linecheck.py <workdir>` (symlink `fonts/` into the workdir first): the per-event band count is deterministic, while vision OCR misreads small Thai and will invent a "truncated" subtitle that is not there — never clear a sub defect from a vision read alone. When it reports `bands=1 want=2`, settle it without OCR: crop the sub area at the event's mid-time (`-vf crop=720:340:0:580`) and count lit-row clusters of the subtitle FILL colour only (mask R≈255, G≈214, B≈102 with tolerance, rows with >4 px lit): two base-glyph clusters split by zero-ink rows = two lines = false fail.
2. Make a frame sheet at each element's start + 0.3 s.
3. Vision-check the sheet:
   - every element is present;
   - Thai marks are stacked;
   - nothing covers the face;
   - no price.
4. Send.

## Layout rules (enforced by `graphics_layer.py --check`)
Text-bearing elements are the headline, callout labels and badges.
- They stay inside x80–592 / y192–832.
- They may not collide with each other in time + rect.
- With `--report`:
  - they stay out of the pill band y186–262 while a pill shows;
  - they stay out of the sub band y700–835 while a sub shows.
- They stay off `avoid` zones.
- **Compute a headline's rect before running `--check`.** `text_rect()` takes `y` as the box TOP and returns `h = lines*size*1.3 + 12`, width = longest line + 12, centred at x360 — so a face-avoid hit is nearly always the second line or those 12 px of padding, not a bad placement: drop to one line, shrink `size`, or lift `y` until `bottom < face_top`. A headline may sit inside the pill band (y186–262) **only while no pill shows at that time**, so timing it to end before the first pill is the cheapest way to buy the space above her head.
- A callout's leader LINE may not cross the sub band while a sub shows. Product parts below y≈700 (label art at the bottle base) cannot take a callout, so point at the pump or cap instead.

Practical slots:
- Headline at y≈200–260, but only while NO pill shows. Otherwise put it beside the head at size 46–50.
- **When pills + subs saturate the timeline (one 10 s scene, 4 pills, subs edge-to-edge), y≈200–260 and
  "beside the head" are both unusable** — the headline is centred at x360, so there is no side column — and
  the only slot left is face_bottom → sub_top: take `face` from step 0b and the first sub start from
  `report.json`, set `y = face_bottom + ~20` with `bottom < sub_top` (face bottom 525 + subs from 700 →
  y 545, size 42, 2 lines ≈ 121 px). It lands on the product she holds, which is allowed: only `avoid`
  (the face) is hard.
  Legal, but DROP the headline instead when what she holds IS the identity art (a game case's cover): centred
  text over it hides the exact thing the shot exists to show. Ship callout + stickers + pills + subs, and say in
  the delivery that no headline slot survived.
- **`--check` prints a text element's ACTUAL rect — read it and shift, don't re-guess.** A callout label is
  CENTRED on (lx, ly) with width ≈ its own text (~240 px for a 2-word label), so a 2-word label needs
  lx ≥ ~201 to stay inside x80 and ly ≥ face_bottom + ~10 to clear `avoid`; the printed rect is the answer,
  not a second vision ask.
- **A scene's single sub-free gap hosts ONE text element.** A headline in the `face_bottom → sub_top` strip and a callout label in the same strip collide in time + rect. Put the callout on the product close-up (the ring is that moment's job) and give the headline to another scene or drop it — two text elements cannot share the gap.
- Callout labels go beside the product.
- Badges go in the left column, x≈120.

## Fonts
- **Fredoka-SemiBold.ttf is a VARIABLE font, and libass cannot select it from fontsdir.** fontselect falls back to DejaVuSans, so labels come out in a plain system font.
- Use `gameplay-clips/fonts/FredokaSB-Static.ttf` instead: a static wght=600 instance, family `FredokaSB`, made with fontTools `varLib.instancer`.
  - In any ASS style, set `Fontname=FredokaSB, Bold=0`.
  - drawtext pills (`fontfile=`) are unaffected.
- To verify a font, run `ffmpeg -v verbose ... -vf ass=... -f null - 2>&1 | grep fontselect`. It must name the intended font, not DejaVu/Liberation.

## Hard rules that still apply
- No price, currency or discount, spoken or on screen.
- Efficacy or kill-rate claims (e.g. "กินแล้วตายทั้งรัง", "ออกฤทธิ์แบบโดมิโน") stay out of the voiceover, graphics and subs unless Fix supplies a source that backs them.
- Shopee-safe layout, no shop name or watermark, EN pills/labels ≤2 words, CTA only on the final shot.

## Still not built
- Explainer scenes (mechanism diagrams, cross-sections) as separate Flow scenes. Each one costs credits and needs the review gate.

## Lessons
- **post_presenter.py drops a short Thai phrase when it sits between two short gaps** (FLAG: `script phrase ... SKIPPED`, and its subtitle line is missing from `subs.ass`). Spaces in the `script` string are phrase breaks, so a 2–3-word phrase flanked by short pauses becomes its own event and gets rejected. Fix: remove the space inside that phrase in the plan's `script` (merging it with its neighbour), re-run post_presenter, then grep `subs.ass` to confirm the phrase now has its own event. Read every FLAG line before sending.
- **A Flow thumbnail is a poor check.** Scene 1's first frame showed no bottle while later frames did. Download the 720p file and check frames before judging a scene.
- **Chaining two scenes:**
  - Upload the last frame as an ingredient, attach it, and say "start exactly on the attached image" in scene 2.
  - The chip shows no filename, so verify it from the thumbnail.
- **Never guess coordinates.** Guessed coordinates put headlines on faces and rings on empty space.
  - Faces and empty sides come from `layout_probe.py`.
  - A callout TARGET (pump, cap, label part) still needs a point on the real frame at the element's time — but **budget exactly ONE coordinate ask** (gridded frame, cyan lines every 100 px, labels carrying parent-frame coords). To cover several points inside that one ask (a callout target AND a CTA-hand sticker), `vstack` the frames into a single image with the grid and y-labels drawn per panel — each panel's labels restart from its own top — and name the panels A/B in the question: multiple points, one round. Vision replying with prose instead of numbers happens often enough that a second rephrasing burns the run: when the answer carries no `(x,y)`, drop the geometry-dependent element (callout ring, endcard) and keep headlines + stickers + pills + subs. **And REJECT any coordinate that falls outside the 720×1280 frame** — a box edge past x720 or a point at x850 means the read invented geometry, which is the prose failure in numeric clothing: drop the element rather than trusting a number that cannot exist. That is still a complete graphics pass; a ring on a guessed point is a defect Fix sends back.
  - **Consult `report.json`'s sub timeline BEFORE spending the ask:** a callout target below the sub band (y > 835) can only show its leader line in a sub-free gap, so when the beat it labels sits inside a long sub the element never renders — drop it from the plan first, or the one ask is spent on a dead element.
- **Free-rect map — the fallback when `layout_probe` reports `no empty side big enough`.** Sample 6–7 frames across the scene (`ffmpeg -ss <t> -i <scene> -frames:v 1 -f rawvideo -pix_fmt rgb24 -`, 720×1280), take each frame's wall as the median of the outermost 8 px of the left and right edge columns over rows 100–1200, mark a 20×20 cell busy when the median per-pixel `|px − wall|` summed over RGB exceeds ~26, and print the grid as ASCII with x labelled every 100 px (`.` <20 free, `:` <45, `*` <90, `#` busy). The largest `.`/`:` block that lies outside y186–262 and y700–835 is your overlay/insert rect — then vision-check one frame of the render as usual. The recipe is implemented as `scripts/freerect.py` — `uv run --with numpy python <skill>/scripts/freerect.py <scene.mp4> <t1,t2,…>` prints this grid directly (`.` free, `#` busy; numpy is not in the `execute_code` kernel). Freerect also shows wall the probe structurally cannot see: `layout_probe` scans side columns only inside y260–640, so free space above her head (rows 0–200) appears only here — check the hair at the frame edge before using a top strip.
- **The `--report` timeline moves when a scene's trim changes** (e.g. hook overlay → `trim: 0`). Re-read `report.json` pills/subs and shift every gfx time after each post_presenter re-run, before `--check`.
- **Close-up product shots (no face) are the slot for the headline and callout.** On presenter shots the face takes the centre column, and the pill and sub bands take the top and bottom.
