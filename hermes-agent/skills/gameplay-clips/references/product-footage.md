# 🎬 Product footage: the gameplay pipeline on official brand videos

Fix 2026-11-10: "แบบ gameplay footage … อยากทำกับคลิปสินค้าด้วย เช่นเครื่องซักผ้า ทีวี หรือแว่น Viture Pro 2 XR
ให้ไปหา video trailer มาทำคล้ายๆแบบเดียวกับเกม".

Follow SKILL.md steps -1 … 11 as for a game. **Only the deltas below change.** It costs 0 credits and needs
no Flow. Log rows use `style: "footage"`, `category` = the product's (`gadget` / `home` / `beauty` / …),
and `hook_id: "pft-N"`.

## Step 1 — research: specs, not a release date
- Use one `web_search` on the brand's own product page (or the Thai distributor's) for the exact model
  in Fix's listing. Keep the facts you will say: what it does, 2–3 headline features, and a size or
  capacity if it is a selling point.
- **Every claim in the VO must come from that page.** No "ประหยัดไฟ 50%", "ดีที่สุด" or "อันดับ 1" unless the
  page says it in those words. When the listing and the brand page differ (capacity, variant, colour),
  tell Fix and use the brand page.
- Drop `release_date` / `release_pill` from the plan (step 8 already says to delete the key when there
  is no date). Countdown and date hooks do not exist for products.
- A listing that says PRE-ORDER for a product already on sale goes to Fix as a note, same as for games.

## Step 2 — footage source: official brand video of THIS model
- Search with yt-dlp: `ytsearch8:<brand> <exact model>`, plus `official` / `film` / `introducing` /
  `TVC`. Brand channels, the brand's Thai channel, and the brand's own site (CDN mp4s download
  directly with `curl`) are the only sources.
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
  When no source has enough gap for the length Fix picked, stop and tell him, and offer 📦 (Flow b-roll)
  or a shorter clip. Do not lay Thai VO over English narration.
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
  Use the same `image_stickers` plan and placement rules as the game cover. The thumbnail uses the
  cutout too.

## Step 7 — VO
- Same voice and recipe (Gemini Leda, edge fallback). Write the script as a friend explaining what it
  does, not ad copy: "ใส่แล้วเหมือนมีจอยักษ์ลอยอยู่ตรงหน้าเลยอะ". Specs are spoken as words.
- Hook from `/opt/data/skills/shopee-clip/templates/hooks.md` → `pft-N`:
  `python3 /opt/data/skills/shopee-clip/scripts/perf.py pick-hook --category <cat> --prefix pft-`.

## Steps 9–10 — gates, log, delivery
Gates unchanged. Log row: `style:"footage"`, `category:<cat>`, `hook_id:"pft-N"`. In `notes`, record the
source URL + channel and the source_check verdict.
