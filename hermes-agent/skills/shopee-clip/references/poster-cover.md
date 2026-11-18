# Poster cover — the posting cover of EVERY clip (Fix 2026-11-17)

Fix: "แนวนี้โอเคเลยเอาแบบนี้ หลังจากนี้ gen ปกแบบนี้ให้ทุกคลิปเลยนะ" (approved mock: message 11667). It replaces the
`make_cover.py` frame + EN pill as the file passed to `clipjob.py deliver --cover`, in every mode (🧑 📦 ✋ 🎬 games and
product films). `deliver` sends it to Fix and to the Secretary chat as before. The in-clip case sticker of a 🎬 clip is a
separate feature and stays.

```
uv run --with pillow python /opt/data/skills/shopee-clip/scripts/make_poster_cover.py <workdir>/cover_spec.json --out <workdir>/cover.jpg
```

Spec keys and limits are in the script docstring. It costs no Flow credit: every picture already exists in the workdir.

## Where each part comes from

| Part | Source | Never |
|---|---|---|
| `hero` | A frame of a RAW shot (`shotK` file in the job, before subs/pills) where the product is large and sharp; 🎬: a clean trailer frame (no caption, no pill, no case sticker) or key art. No product-alone frame (presenter holds it all clip long) → the frame where the product is biggest, or a clean listing photo cropped with `hero_box` | `out.mp4` / the final (burned text), a frame with a Flow defect on the product |
| `title` | Line 1 = what it is (Thai product name, short; a game: its title). Line 2 = the one benefit the clip sells, from the voiceover | A claim the listing and the VO do not make |
| `sub`, `chips`, `badge` | Listing / intake sheet / the approved storyboard, in Thai, 2–4 words each. A game: platform, edition, genre, what you do in it | Price, discount, "ซื้อ 1 แถม 1", coupon, % — the script refuses them; invented specs |
| `circles` (0–3) | Detail crops: another raw frame (the product in use), a listing photo (pack, colour variant), 🎬 the case front (`cover_crop.jpg`) + gameplay frames. Fewer good pictures = fewer circles; the hero grows to fill the space | A crop with a store logo, a promo badge, a price or a QR |
| `theme` | `auto` (hue of the hero). Name one when auto picks a muddy colour or the brand colour is obvious | — |

## Steps

1. Pick the frames: `ffmpeg -ss T -i <raw shot> -frames:v 1 -q:v 2 f.jpg` at 2–3 moments, one grid sheet, ONE vision
   call to choose hero + circles and to read each crop box. Boxes are source pixels of that image; read them off the
   grid, never guess.
2. Write `cover_spec.json`, run the script. Exit 1 names the element that does not fit or the refused word: shorten that
   text and rerun. Nothing is clipped silently.
3. **Vision-check the finished cover** (one call): the product is the real one and whole, no price / discount / store
   logo / QR inside any picture (the script only reads the text you typed), Thai is spelled right, no circle shows a
   face mid-blink or an empty crop. A failed check = fix the spec and rerun; do not deliver it.
   **A read that reports misspellings across several unrelated strings is the misread signature, not N defects:**
   the script draws the spec strings verbatim (PIL can drop tone marks without Raqm, but cannot swap base
   glyphs). Confirm with ONE sheet of zoomed band crops (~1.5–3× per text region) checked against the spec
   strings before touching the spec — editing to chase a thumbnail misread corrupts correct Thai.
4. Pass `cover.jpg` to `clipjob.py deliver --cover`.

## Traps

- **Raqm:** the script stops when Pillow has no Raqm. Run it in the container with `uv run --with pillow`.
- **Listing photos are promo collages** (official-store logo, "ซื้อ 1 แถม 1" circle, size banner). Crop inside the clean
  part of the product or use a raw frame instead.
- **The product Flow drew may differ from the listing** (label art, colour). Hero and circles must not contradict each
  other: when they do, take every picture from the clip, or every picture from the listing.
- A 16:9 trailer frame is cover-fitted: set `hero_focus` so the subject survives, and avoid frames with a large HUD.
- `make_cover.py` stays for the frame scoring (`--t auto`) only when you need help finding a sharp moment.
