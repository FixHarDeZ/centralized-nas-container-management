# 🎬 Product footage: the gameplay pipeline on official brand videos

Fix 2026-11-10: "แบบ gameplay footage … อยากทำกับคลิปสินค้าด้วย เช่นเครื่องซักผ้า ทีวี หรือแว่น Viture Pro 2 XR
ให้ไปหา video trailer มาทำคล้ายๆแบบเดียวกับเกม".

Follow SKILL.md steps -1 … 11 as for a game. **Only the deltas below change.** It costs 0 credits and needs
no Flow. Log rows use `style: "footage"` (`clipjob.py deliver … --style footage`), `category` = the product's (`gadget` / `home` / `beauty` / …),
and `hook_id: "pft-N"`.

## Step 1 — research: specs, not a release date
- Use one `web_search` on the brand's own product page (or the Thai distributor's) for the exact model
  in Fix's listing. Keep the facts you will say: what it does, 2–3 headline features, and a size or
  capacity if it is a selling point.
- **When search returns only aggregators and review sites, get the brand's own page from its sitemap:**
  `curl -sL https://<brand>.com/sitemap_products_1.xml | grep -o '<loc>[^<]*</loc>'` → the product URL →
  `web_extract`. Shopify stores list every product there; that page (not the listing) is the spec source.
- **Every claim in the VO must come from that page.** No "ประหยัดไฟ 50%", "ดีที่สุด" or "อันดับ 1" unless the
  page says it in those words. When the listing and the brand page differ (capacity, variant, colour),
  tell Fix and use the brand page.
- Drop `release_date` / `release_pill` from the plan (step 8 already says to delete the key when there
  is no date). Countdown and date hooks do not exist for products.
- A listing that says PRE-ORDER for a product already on sale goes to Fix as a note, same as for games.
- **A bundle listing whose photos show only part of it** (controller listed with a display stand, console with a
  bundled game) → the missing item simply never appears on screen: say so in the delivery, and never draw or
  source a stand-in for it.

## Step 2 — footage source: official brand video of THIS model
- Search with yt-dlp: `ytsearch8:<brand> <exact model>`, plus `official` / `film` / `introducing` /
  `TVC`. Brand channels, the brand's Thai channel, and the brand's own site (CDN mp4s download
  directly with `curl`) are the only sources.
- **Harvest the brand's PDP videos in the same pass as the channel search:** `curl -sL -A 'Mozilla/5.0' <product-page-url> -o page.html`, then extract every `.mp4` path AND every `videos/...` path that
  carries no extension (poster / `section*` assets) and append `.mp4` to those, range-checking each with
  `curl -r 0-1000 -o /dev/null -w '%{http_code}'` (206 = exists, 404 = skip). One product page yielded 10
  official clips — a 4K hero film plus one short demo loop per feature — and every one went through
  `windows.py`; the SUM of unique clean seconds across them is what the length gate counts. Record the page
  URL and the file paths in the delivery notes as the source.
- **Search the brand's own channel first.** A plain `ytsearch` is dominated by reviewers: on 2026-11-10 the top
  10 for "VITURE Pro 2 XR official" were all third-party. The channel search lists the brand films directly:
  ```
  uv tool run yt-dlp --flat-playlist --no-warnings --playlist-end 15 -j "https://www.youtube.com/@<Brand>/search?query=<model>"
  ```
  For example, `@VITURE … query=pro%202` → "Introducing VITURE Pro 2 …" (50 s, 1080p) and "Sleek on Every Face"
  (32 s, 4K), both 16:9 and both passing the gate.
- **When the brand has no official channel at all, take the brand store's own marketplace listing videos** —
  they are the brand's own asset, so they do not trip the third-party-reviewer ban. A video-detail page carries
  the file in its meta tags: `curl -sL -A 'Mozilla/5.0' '<marketplace video-detail URL>' | grep -o 'og:video:url[^,]*'`
  → the CDN mp4 downloads with plain `curl -o` (the CDN is not behind the listing page's WAF). Read
  `og:video:duration` from the same page first, and still vision-check 2–3 frames against Fix's photos.
- **Prefer 16:9 `watch?v=` films.** `/shorts/` uploads are vertical. The v5 layout puts the source in a 16:9
  window, so a vertical short ends up tiny with bars. When only shorts exist, cut segments from them and build
  with `/opt/data/skills/shopee-clip/scripts/product_build.py` (full-frame 9:16 + the same VO recipe) instead
  of build_v5.
- **Check titles and supers for prices.** One VITURE short is titled "…now available for $…". A price in the
  title often means a price card in the film.
- **Gate every candidate before downloading:**
  ```
  python3 <skill_dir>/scripts/source_check.py --search "ytsearch8:VITURE Pro 2 XR official" --model "Pro 2 XR" --brand VITURE
  python3 <skill_dir>/scripts/source_check.py <url> --model "<model code>" --brand <brand>
  ```
  - `ok:false` because of `missing_tokens` means the video shows a different or unnamed model. Do not use it.
  - `official:false` means a third-party upload (reviewer, reseller). Do not use it. It is someone
    else's work, and their voice is on it.
  - Title and description can be generic ("XR glasses"), so a pass is necessary but not sufficient. Also
    vision-check 2–3 frames against Fix's listing photos: shape, logo, ports, colour.
- **Product films are often narrated all the way through.** Rank the sources by the total ASR gap
  (footage-sourcing.md), exactly as for trailers. Music-only brand films and "design" films work best.
  When no source has enough gap for the length Fix named (or 15 s when he named none; SKILL.md "Length"), stop and tell him, and offer 📦 (Flow b-roll)
  or a shorter clip. Do not lay Thai VO over English narration.
- **Measure the text-free runs before committing to a length (brand films are caption-heavy).** Run a 1 fps
  contact sheet over the whole source and count the longest continuous run with no on-screen text and no
  people. A 50 s 16:9 brand film had only a ~6 s clean run; a 60 s vertical short had a 9 s one. If the longest
  clean run is shorter than the length Fix named (or 15 s), stop and offer Fix a shorter clip or another source (shorts are
  often the cleaner option). Do not paper over it with brand captions.
- **Locate the product itself before counting those clean seconds.** Text-free seconds of *other* hardware do
  not make a product clip: map where the exact model appears (the OCR map plus one framesheet pass) and require
  at least one moving, supers-free window of it for the hero. Brand films routinely park an accessory in a static
  end-card block with its name and a date burned in across the whole shot — if that block is the product's only
  appearance, no crop saves it (the label sits between the product and the frame edge) → stop and offer Fix:
  footage with the product carried as a sticker cut from his photos / footage he supplies / a different mode
  (📦 or 🧑). Checking three official sources is normal here; fetching a fourth on your own is not.
- **Brand films run 8–18 s, so `windows.py` prints its per-source `STOP: … < 15 s` on nearly every source —
  normal for a product, not a dead end.** Run it on every official source and sum the clean windows; ask Fix
  only when the SUM of the *unique* clean seconds is under 15. Markets re-cut the same film into near-identical
  edits, so ask the one sheet of candidate tiles whether they are duplicates and count a single copy.
- **A non-empty `overlays` list in `<stem>_windows.json` means burned text the 1 s OCR cadence did not turn into
  a `text` run** (a small corner title passes unseen while the window reads clean). Confirm every candidate
  window with `ocr_scan.py SRC START END out.json 0.5` before cutting — only frames with no hit are clean.
  **`overlays` is a hint, not the gate — it changes between two runs of the same file (empty one run,
  `['HUAWEI']` the next),** so run the 0.5-step scan anyway. Brand films also carry a tiny legal line in a
  bottom corner ("content is for reference only") that the 1 s cadence almost never records: take its bbox
  from the 0.5-step hits (boxes are in source pixels), crop that band out of the source (`crop=W:H:X:0` with H
  just above the bbox) and re-run `windows.py` on the cropped file — dodging the line by trimming the window
  costs more seconds than these 8–43 s films have left.
- **A persistent corner title is cropped out of the source, not refused**: take its box from the OCR hits (a
  centred hit on the end card pins the boxes' pixel scale), `ffmpeg -vf crop=W:H:X:Y` the band plus ~12 px, then
  re-run `windows.py` on the cropped file so the clean table is measured, not hand-edited. Intermittent legal
  micro-captions inside a window are dodged by moving the seg in/out off their timestamps (re-check at the
  planned in points, per footage-sourcing §5d).
- **Shorts are vertical: use `product_build.py` directly.** They are 9:16 already, so skip the 16:9 window
  path. A short can yield a clean run with zero speech while ASR reports one segment; that is a music-only
  film, not a failed ASR.
- Shopee listing videos sit behind a WAF. Same as games: tell Fix and use the brand video.

## Step 4 — shots: watch for burned-in text
- Brand films carry supers: prices, "% OFF", promo dates, Chinese or Japanese copy, and spec numbers
  that may not match the Thai model. Run the frame check on every seg (price, %, CJK, any number that
  is not in the brand-page facts). Crop or move the in/out to avoid them.
- The end card (logo + model name) can be borrowed as the CTA card like a game's, but only when it
  shows **no price and no promo**.
- Hero shot = the product doing its job (glasses on a face with the virtual screen, washer drum
  turning, TV picture), not a lifestyle shot with no product in it.

## Step 6 — background and sticker
- `bg.png` `--art`: the brand's product key visual, or a 1080p frame from the source (step 6 fallback).
- The case-cover sticker becomes a **product cutout** from Fix's listing photo or the brand page,
  background removed (`/opt/data/skills/shopee-clip/references/product-image-prep.md` covers the cutout).
  Use the same `image_stickers` plan and placement rules as the game cover. The thumbnail is the poster cover
  (`/opt/data/skills/shopee-clip/references/poster-cover.md`); the cutout can be one of its circles.
- **Brand-DAM renders are usually RGBA cutouts already** — check `im.mode == "RGBA"` and
  `getchannel("A").getextrema() == (0, 255)` with transparent corners; when that passes, skip the flood fill.
  No single render shows the whole product (case-only and buds-only colourway renders are the normal split),
  so composite same-colourway renders into ONE sticker: buds above case on a transparent canvas, `getbbox()`
  crop, 2x LANCZOS. Placement math (`w_est = h x w0/h0`) uses the composite's aspect, never a source's.
- **A clean product photo on a plain white studio background needs no ad salvage — cut it out in one PIL pass:**
  `ImageDraw.floodfill(work, seed, MARK, thresh=32)` from all four corners with a marker colour, build the
  alpha from where the marker landed, then `alpha.getbbox()` to crop. Flood fill from the corners rather than
  a global "near-white" threshold, or white areas INSIDE the product (labels, highlights, screen bezel) turn
  transparent too. Vision-check the result for clipped parts and a white halo before it goes into `gfx.json`.
  - **Crop the marketing text away BEFORE the flood fill**: corner fill only removes background connected to
    the corners, so a headline/spec block sitting on the same white field survives as floating islands in the
    alpha. Locate the product first (largest dark component on a 4×-downscaled mask), crop to it plus a few px,
    then fill.
  - **Eat the JPEG halo and keep the sticker sharp**: `alpha = alpha.filter(ImageFilter.MinFilter(3))` before
    `getbbox()` drops the 1-px light fringe left at the edge, and upscaling the cut-out 2× (LANCZOS) stops it
    going soft at display size.

## Step 7 — VO
- Same voice and recipe (Gemini Leda, edge fallback). Write the script as a friend explaining what it
  does, not ad copy: "ใส่แล้วเหมือนมีจอยักษ์ลอยอยู่ตรงหน้าเลยอะ". Specs are spoken as words.
- Hook from `/opt/data/skills/shopee-clip/templates/hooks.md` → `pft-N`:
  `python3 /opt/data/skills/shopee-clip/scripts/perf.py pick-hook --category <cat> --prefix pft-`.

## Step 8 — build: `product_build.py` when the footage spans several files
Mixing orientations (a 16:9 brand film plus vertical listing videos) does not fit `build_v5`'s single
master/trailer pair — pre-cut each seg to its own file and drive `product_build.py` instead.
- **Cut every seg to 9:16 before the build** so its `scale=…:increase,crop=720:1280` is a no-op: a portrait
  source scales straight to 720×1280; a 16:9 source becomes a 720×405 band at `y=280` over its own blurred
  stretch (`split` → `boxblur=24:2,eq=brightness=-0.12` → `overlay=(W-w)/2:280`) — the whole picture survives
  and the pill band (186–262) and subtitle band (700–835) stay clear.
- **The music bed must be ONE track cut into consecutive slices**: give shot *k* the audio of a single
  music-only source at a running offset (the shot durations summed), so `acrossfade` blends the same musical
  moment with itself and the seams are silent. Slicing each source's own audio jumps the track at every cut.
    - **Probe the bed before cutting shots**: it must be ≥ Σ shot durations, or the LAST shot's audio truncates
      silently and the clip's tail goes dead — check `ffprobe -show_entries format=duration <bed>` against the
      sum, then read each cut shot's `a=` duration (a short `a=` = the bed ran out).
    - **Build a crossfade loop from two explicit `-i` inputs of the same file** (`[0:a]atrim…` + `[1:a]atrim…` +
      `acrossfade`); the `asplit`-on-one-input form emits only the head, which surfaces as that same short shot
      audio instead of as an error.
- **Lay the VO around the last shot before writing it** — `product_build` sets `total = vo_end + tail`, the CTA
  may only start inside the last shot, and `hold = total − footage` must stay ≤ 2 s (it flags otherwise). With
  `L = footage − d_last` (the last shot's start) the constraints are `cta_start ≥ L`,
  `d_last ≥ cta_dur + tail − 2`, and the pre-CTA phrases must fill `0 → L`: size the script to that window
  first, tune gaps second.
- **Prebuilt VO files live in a subfolder of the workdir** (`"vo_mp3": "vo_src/vo.mp3"`): keys naming files
  already sitting in the workdir make `product_build` copy a file onto itself and abort with `SameFileError`
  before any render.
- **Widen a tight footage window by lowering `tail` (1.6 → ~1.2), not by re-generating the VO**: `total =
  vo_end + tail`, so a shorter tail lowers the `hold ≤ 2 s` floor while the CTA-must-start-inside-the-last-shot
  ceiling stays put.

## Steps 9–10 — gates, log, delivery
Gates unchanged. Log row (written by `deliver --style footage`): `style:"footage"`, `category:<cat>`, `hook_id:"pft-N"`. In `notes`, record the
source URL + channel and the source_check verdict.
