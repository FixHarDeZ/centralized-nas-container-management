# Preset: presenter + graphics (Fix 2026-11-07)

Fix's order: keep OUR subtitle style for all Thai subs, and add a preset that combines the presenter with graphics.

**Graphics v2 is the DEFAULT for every presenter clip.** Fix chose it over the plain build in an A/B, with one change: *"ภาพนิ่งที่แทรกขอ crop แค่รูปสินค้าวางบนจอให้ไม่บัง presenter"*.
- Every product still (hook card AND inserts) uses `presenter_fx.py` `"mode": "overlay"`: the product is cut out (edge flood-fill bg removal + white sticker border + shadow), slides in and bobs.
- Place it in the empty backdrop beside her. Read that rect off real frames with vision first; for Flow presenters it is usually the right side, centre x≈615–625, y≈380–405, h 225–270.
- Never use a full-screen card that hides the presenter.
- Keep sparkle/heart stickers ≥20 px away from the cutout's edge, or they read as crammed.
- With a hook overlay, set `"trim": [0, "auto"]` in the post_presenter plan.

## Subtitles (unchanged)
- Itim 48, pastel yellow `&H0066D1FF`, dark brown outline `&H00203050`, Outline 5, Shadow 2.5.
- `BorderStyle=1` (no box), Alignment=2, burned with `ass=...:shaping=complex`.
- Do NOT switch to the reference clip's style.

## Pipeline order (all post-production, 0 credits)

### 0a. `scripts/detect_repeats.py scene_raw.mp4 --script prompt_sN.txt --cut sceneN_cut.mp4` (every raw scene, one at a time)
Run it as `uv run --with faster-whisper --with numpy python …`. It runs unprompted word-level ASR and looks for ADJACENT doubled phrases that the script does not contain twice.
- exit 3 = repeat found and cut (0 credits). Use `sceneN_cut.mp4` from here on and NAME the cut in the delivery (text + seconds removed).
- exit 0 = clean.
- Proven on ENFANT scene 2: it found `สเต็ปง่ายๆ` ×2, cut 5.792–6.458 (identical to the manual cut), and a re-probe of the cut file came back clean.
- It replaces the manual "unprompted ASR" gate in `presenter-post.md`.

### 0b. `scripts/layout_probe.py scene.mp4 --window S E [--window …] --product <crop.jpg>` (placement without vision rounds)
Run it as `uv run --with "opencv-python-headless<5" --with numpy python …`. **Pin <5: opencv 5 ships no Haar cascades.**

One JSON line per window:
- `face`: Haar union. Use it as the `avoid` rect.
- `empty_left` / `empty_right`: the backdrop rect free in EVERY sampled frame, inside y 260–640.
- `overlay`: {x, y, h} for the product cutout, sized to its aspect. When `note` says the side is too small → skip or shorten that overlay.

It is CONSERVATIVE: the mottled wall makes it reserve more than vision does, e.g. h 94 where vision allowed ~240. When it says too small but you need the overlay, one vision read of that window may overrule it. Still vision-check one frame of the final render.

### 1. `scripts/presenter_fx.py scene_raw.mp4 fx.json scene_fx.mp4`
Run once per RAW scene, BEFORE post_presenter. It touches video only and copies audio, so duration, ASR and sub timing are unchanged.
- `hook_card` (`"mode": "overlay"`, ~1.4 s): a cut-out product sticker appears beside the presenter from frame 0.
- `punch`: snap zoom ≤1.15 on each new selling point. (cx,cy) = the face or the product in hand.
- `inserts` (`"mode": "overlay"`, 1.2–1.5 s): put one on a word that names the product or its label art.
  - Without `mode` you get the old full-screen card. Use that only to hide a seam or a looped phrase, because it hides the presenter.
- Source images must be CLEAN crops (no price/QR/claims, see `product-image-prep.md`), on a plain light background so the flood-fill cutout works.
- Input is the step-0a output (`sceneN_cut.mp4` when a repeat was cut), so post_presenter aligns to the corrected audio.
- Overlay x/y/h come from step 0b's `overlay` field for that window.

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
- `cover`: a twinkle sparkle over Flow's lower-right sparkle mark.
- `avoid`: the presenter face box.
  - **Take it from step 0b's `face` per window** (add the scene's global start). Fall back to a vision read only when the probe finds no face.
  - Flow presenters sit centre-frame, so headlines at the old default y=300 land on the face.
- Auto SFX: pop/twinkle at each element plus a whoosh on the endcard.
  - Mixed at gain 0.35 under a limiter at 0.63 (AAC overshoot otherwise lands the max at exactly −3.0 dB).

### 3b. Cover (every clip, presenter AND gameplay)
1. `uv run --with pillow --with numpy python scripts/make_cover.py --video sceneN_fx.mp4 --t <moment with face + product> --text "<BRAND PRODUCT ≤3 words EN>" --cy 1150 --color green|pink|… --out cover.jpg`
   - The source must be a PRE-subtitle render.
   - `--cy 1150` puts the title on her torso, clear of the face. Auto put it on the chin.
   - The title box can cover the bottle's label (measured on a Pureen cover: the box took the label's middle, and the vision check failed label visibility). Before sending, check the label is readable; if not, keep the box clear of the label area with a shorter title or a lower `--cy` and re-check. Untested alternative: move `--cy` lower, not verified yet.
   - Pick a box colour that contrasts with the wall (pink-on-pink blends in).
2. Vision-check: face clear, label mostly visible, no price.
3. `python3 scripts/send_photo.py cover.jpg "<caption>" 8663614341 <label>` → ok + message_id. Ledger rows are `kind: photo`; check_delivery stays clean.
- make_cover now uses `FredokaSB-Static.ttf`: the variable Fredoka loads a thin default instance in PIL.

### 4. Check and send
1. Run `verify-clip.py` on final.mp4.
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
- A callout's leader LINE may not cross the sub band while a sub shows. Product parts below y≈700 (label art at the bottle base) cannot take a callout, so point at the pump or cap instead.

Practical slots:
- Headline at y≈200–260, but only while NO pill shows. Otherwise put it beside the head at size 46–50.
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
  - A callout TARGET (pump, cap, label part) still needs a gridded frame sheet: cyan lines every 100 px on the real frame at the element's time, then ask vision for the part's point.
- **The `--report` timeline moves when a scene's trim changes** (e.g. hook overlay → `trim: 0`). Re-read `report.json` pills/subs and shift every gfx time after each post_presenter re-run, before `--check`.
- **Close-up product shots (no face) are the slot for the headline and callout.** On presenter shots the face takes the centre column, and the pill and sub bands take the top and bottom.
