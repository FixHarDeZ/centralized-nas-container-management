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
| `circles` (0–3 detail slots) | **First choice: a listing / official detail photo that literally shows the label** (a strap close-up, the dial, the feature screen on the wrist) — they are 800–3800 px and sharp. A raw frame only for the product in use, and only when the detail is big in it. 🎬: the case front as `"shape": "card"` (whole case, never a circle) + a gameplay frame. Fewer good pictures = fewer slots; the hero grows | A crop of a 720p Flow frame smaller than the circle (the script refuses it: upscaled = mush), a crop where the labelled thing is not the main subject, a store logo / promo badge / price / QR |
| `theme` | `auto` (hue of the hero). Name one when auto picks a muddy colour or the brand colour is obvious | — |

## Detail slots — the rules that failed (Fix 2026-11-18)

Three covers shipped with slots that said nothing: D2 "สายถัก" / "มุมข้าง" were 170–200 px crops of 720p frames blown
up to a 244 px circle (mush), GT6 "แผนที่สนามกอล์ฟ" showed a wrist at an angle with no map, the Lego case art went in
a circle and lost its top and bottom. The workdirs already held the right pictures (`huawei-watch-d-2-blue-straps.jpg`,
`off6_golf.jpg`, `off5_dial.png`). The script now refuses the first and third kind; the second only the check catches.

- **A slot proves its label at thumbnail size.** The label names ONE thing and that thing fills the slot: box tight
  around it (the golf map: the watch face, not the forearm). Can't find a picture that shows it → drop the slot, or
  turn the claim into a chip.
- **`circle`** = square-ish close-up (box w/h 0.8–1.25) with at least as many pixels as the circle shows (1 slot 340,
  2 slots 320, 3 slots 244 px). Exit 1 `too small` → a bigger box or a listing photo; exit 1 `square-ish` → a square box
  or `card`.
- **`card`** = the whole picture at its own aspect: a game case, a pack, a box, a wide side profile. Nothing is cut.
- White / black padding is trimmed off every picture by the script (listing photos, `cover_crop.jpg`).
- **Label words come from the listing or the VO**, 2–4 words; a label longer than the slot fails instead of shrinking.
- "Hero and circles must not contradict": that means the same variant (colour, dial, case). An official photo of the
  same variant next to a Flow hero is fine — it is the sharp picture, not a contradiction.

## Steps

**Vision budget: 2 calls per cover** (pick + check), +1 re-check after a fix (2026-11-19..22: 47 cover calls /
~99 min for 11 covers — per-slot pre-checks and repeated cover reads).

1. Pick the frames: `ffmpeg -ss T -i <raw shot> -frames:v 1 -q:v 2 f.jpg` at 2–3 moments, one grid sheet, ONE vision
   call to choose hero + circles and to read each crop box. Boxes are source pixels of that image; correct any box
   against the pixel probe in `frame-check.md` → Locating a crop before cutting (a grid read can land on
   background). No per-slot pre-check call: step 3's sheet checks every slot at once.
2. Write `cover_spec.json`, run the script. Exit 1 names the element that does not fit or the refused word: shorten that
   text and rerun. Nothing is clipped silently.
3. **ONE vision call on the `check_sheet` the script prints, with its `ask_vision`** (picture 1 = the cover,
   2.. = each detail slot exactly as pasted, no captions). Pass = (a) product whole and real, (b) no price /
   discount / store logo / QR inside any picture (the script only reads the text you typed), (c) no missing
   tone marks / empty boxes / tofu, and every slot answer names its `slot_labels` thing (same order) without
   being told the label. A vague slot answer ("a wrist", "a dark room", "unclear") = wrong picture or loose box:
   fix that slot, rebuild, ONE re-check; still failing = drop the slot. Thai spelling is NOT read back:
   vision garbles Thai on every read and the script draws the spec strings verbatim (PIL cannot swap glyphs),
   so a read that "finds" misspellings in several strings is the misread signature — never edit spec Thai to
   match it. Latin lines can be OCR-checked (crop the band, RapidOCR, compare to the spec).
4. Pass `cover.jpg` to `clipjob.py deliver --cover`.

## Traps

- **Raqm:** the script stops when Pillow has no Raqm. Run it in the container with `uv run --with pillow`.
- **The banned-word regex matches Thai SUBSTRINGS:** `ลด` inside `เวิลด์` trips `REFUSED … contains price/discount
  wording` on a title like `โอเพนเวิลด์สุดอิสระ`. Reword the spec (e.g. `เปิดเมืองอิสระเต็มที่`) — never edit the
  script's `BANNED` list to let a word through. Franchise and product names count too: `เซลด้า` contains `ลด`, so
  write those in Latin (`ลาย Zelda ลิมิเต็ด`).
- **Zoomed band crops use scale expressions, not percentages:** `scale=150%` fails with `Error initializing
  filters` (the graph never builds, so it reads as a broken filter chain) — write `scale=iw*3/2:ih*3/2`
  (2× = `iw*2:ih*2`).
- **A circle exit-1 `too small` is fixed by a BIGGER box on the same photo, not a new photo** — the box vision
  reads off the grid is often a tight bbox of the part; pad it outward toward the whole product view until the
  crop is ≥ the circle's pixel floor (2 slots = 320 px), then re-run. Two enlarge rounds is normal.
- **On a white (or black) background photo the circle box must hug the PRODUCT's own bbox, not the square you
  eyeballed around it** — the script trims that uniform padding BEFORE measuring w/h, so a visually square box
  on white comes back non-square after the trim and exits 1 `square-ish` (340×340 → 250×326 on a packshot).
  Derive the box from the non-white pixel bbox (step 1 → `frame-check.md` → Locating a crop), so the trim has
  nothing to remove and the aspect you measured is the aspect the script measures.
- **Listing photos are promo collages** (official-store logo, "ซื้อ 1 แถม 1" circle, size banner). Crop inside the clean
  part of the product or use a raw frame instead.
- **The product Flow drew may differ from the listing** (label art, colour). Hero and slots must show the same variant:
  when Flow's variant differs, take every picture from the clip, or every picture from the listing.
- A 16:9 trailer frame is cover-fitted: set `hero_focus` so the subject survives, and avoid frames with a large HUD.
- **A raw frame whose product fills the frame gets cropped by the card to the product's middle** and then fails the
  step-3 "whole product" check. When every raw frame is a close-up, take the hero from the clean official packshot
  (the table allows a clean listing photo) and centre it with `hero_focus`.
- `make_cover.py` stays for the frame scoring (`--t auto`) only when you need help finding a sharp moment.
- **`box` lives in the coordinate space of the file named in the same `image`** — a box read off the full frame
  exits `box … is outside the <W>x<H> image` once `image` already points at the pre-cropped file. Pass EITHER the
  full frame plus its `box`, OR the pre-cropped file with no `box` (used whole); mixing the two halves from
  different coordinate spaces costs a whole rebuild round.
