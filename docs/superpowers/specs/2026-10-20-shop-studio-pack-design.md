# Shop Studio pack: the Studio pack flow for Product Clips

Status: accepted (2026-10-20), phased. **Phase 1**: core + Telegram `/shop`, deployed and run end to end once. **Phase 2**: Creator Studio web, planned separately after reading `shop_store`'s invariants (3-6 scenes in `save_plan`, `accept_scene`, the ≤60 s check, fenced writes). See ADR 0018.

## Goal

Make Product Clips (Shopee affiliate) the way the owner now makes Shorts with
🎞 Storyboard Studio packs: one pack, the scenes generated and arranged in
Flow's Storyboard Studio, one export back, cut and rendered by the bot.

## Owner decisions (2026-10-20)

- **Both entry points**: the Telegram `/shop` Brief and the Creator Studio
  web `/shop` job.
- **Flow only**: every shot is a Flow shot. No Pexels, no product-photo Ken
  Burns segments.
- **The character always speaks**: 🗣 is forced on and needs a character.
- **The product comes in as an Ingredient**: the product photos are attached in
  Flow and the character holds or uses the product in the scene.
- **No end card**: there is no price or discount card. The closing line (the
  CTA) is the last shot, spoken by the character.

## Shape

One shared core, two thin front ends.

### Core: `app/shop_studio.py` (no Telegram, no store)

- `shots(pitch)`: one shot per beat, plus a closing shot that speaks
  `end_narration`. Every shot has `narration`, `spoken` and `lines`, and a
  `photo` (the beat's photo; the closing shot reuses the first beat's).
- `measure(shots, workdir)`: speak all shots in one edge-tts take with
  `shop.VOICE`, the same call the renderer makes. This gives each shot's span.
- `fit(shots, spans)`: shots whose take is past `studio.SPEAK_FIT` go through
  `script.condense()` and are re-measured, two rounds at most. Shop rules
  stay in force through a rules hook on `condense()`, because the Shorts
  defaults contradict them:
  - Shop `spoken` keeps Arabic digits, with no ร้อย/พัน/หมื่น/แสน.
  - Every number, single digits included, must be in the Brief
    (`shop.unsourced` + `_check_voice`).
  - `lines` are rebuilt from the new narration with `shop.fit_lines()`. A beat
    that still needs more than two lines goes back as a problem.
- `plan(shots, brief, character)`: one storyboard call (`storyboard.plan`) with
  a shop rule. The rule covers:
  - One scene per shot, with `@Tag` holding, using or showing the product.
  - The product as shown in the attached reference photo: its shape, colours
    and labels are never changed, invented or added to.
  - No real people or brands beyond the product itself.
  - A short English product name for the Products line.
- The product gets its own `@Product` tag. The human makes an Asset Profile of
  it from the photos, as with the character. Ingredients-to-Video takes at most
  3 images: character, product and frame. The first live pack confirms whether
  two profiles work in one scene.
- 🤖 auto characters are told to be a woman, because the Pitch is written as
  one.
- Dialogue is the shot's `spoken` (Thai script, digits, "บาท"), not
  `narration`.
- `markdown(board, tag, product)`: the short Storyboard Studio shape, plus a
  Products line:

  ```
  Story Title: …
  Characters:
  @Tag is a … / @Tag speaks in …
  Products:
  The product shown in the attached product photos: <english name>. Keep its shape, colours and labels exactly as in the photos.
  Scene N:
  @Tag holds the product … (one sentence)
  Dialogue: "…"
  ```

- `animate(scene, photo)`: the per-shot prompt is `Speaks in Thai: "…"
  Natural lip movement. <move>. No subtitles, no on-screen text, no background
  music.` The page tells the human which photos to attach: the character and
  product photo N.
- Shot length: `studio.speak_seconds(span)` gives 8 or 10 s. Credits are
  12 or 15 per shot.
- `render(shots, segments, voices, workdir)`: `shop_render`'s
  `video_segment` + `text_layer` path, the same one `build_snapshot` uses.
  - Badge on top, subtitle at y 1440 (~75 %, clear of the mouth).
  - Each shot's own trimmed voice, with no TTS. The voice step (keep head, trim
    tail, two-pass loudnorm) is factored out of `studio.speaking_take()`.
  - Each segment is as long as its trimmed voice. BGM is ducked under it, and
    there is no end card.
  - The output is mp4 + `shop.caption_text()`.

### Telegram `/shop`

- The Pitch review gets 🎞 next to 🎬. Pressing it:
  - closes the Brief's review;
  - frees the bot (`mode` back to idle — a pack waits hours for Flow);
  - parks the pack in `clip_wait` with `kind: "shop"`.
- It is the same single slot as Shorts packs: one pack at a time, with the
  same swap button.
- The pack files live in `/data/studio/<shop_id>/`, along with copies of the
  product photos (`refs/pNN.jpg`), because the dashboard only mounts `/data`.
- `studio.CLIP_ID` accepts shop ids (`p` + 12 digits).
- The dashboard `/storyboard/<id>` page is reused with a shop variant:
  - product photos to download;
  - per shot, which photo to attach;
  - no Pexels and no 🎬/🖼 toggles.
- The pack keyboard has 👤 character choices, ↩️ (back to Pitch review, needs
  the bot idle) and 🗑. There are no card toggles and no 🗣 toggle (both are
  forced).
- The export comes back through the same inbox and reply paths, is cut with
  `keep_voice` for every shot, then rendered by the core. The output goes to
  `/output/shop/<id>/` with `shop.json` (`render.mode: "studio"`). The video and
  caption are sent as they are today.
- Uneven exports: the same refuse-and-offer-cut-evenly rule.

### Creator Studio web `/shop`

- A job gets `mode: "studio"`, chosen at creation (default `scenes`, the
  current per-scene flow, unchanged).
- On a studio job, the worker's `generate_plan`:
  - writes the Pitch;
  - runs core `fit` and `plan`;
  - stores the pack (markdown, per-shot prompts and seconds, the expected
    length) in the plan as `studio`.
- The job page shows the pack and has one export upload. The upload is a new
  asset kind, `export`. The `probe_asset` path validates it, then a new
  `cut_export` command cuts it into per-scene media plus voices, with the
  same length check and an explicit cut-evenly retry.
- Render: `build_snapshot` branches on `mode: "studio"` to the core render.
  There is no end card and no TTS. Revision fencing is unchanged.

## Not in scope

- Experiments, Manifest and the dashboard clip list stay unchanged for shop
  (ADR 0015).
- Automating Flow.

## Risks

- Veo redraws the product: packaging text and logos drift. The page warns about
  this, and the owner regenerates the shot. Nothing checks it automatically.
- The library has no gender field, and the Pitch is written as a woman
  ("ค่ะ"). Both library characters today are women. A male character would
  need the Pitch prompt to follow the character, which is out of scope until
  one exists.
