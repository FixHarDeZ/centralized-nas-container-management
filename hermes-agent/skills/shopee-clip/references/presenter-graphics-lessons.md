# Presenter clip lessons (Pureen run, 2026-11-08)

## Graphics v2 is mandatory on presenter clips
- Shipping a presenter clip with only post_presenter (subs + pills) is NOT the default build. Fix called it out: "Graphic ไม่ crop รูปสินค้ามาแปะ... และ effect น่ารักๆ".
- Required chain after raw scenes pass review:
  1. `scripts/layout_probe.py` on the raw scenes (windows around each product mention) for overlay x/y/h.
     Its `note: no empty side big enough` is conservative; overlay at x≈655, y≈330, h≈120-130 still fit beside the face in practice. Confirm with one vision read on a frame with a cyan grid.
  2. `scripts/presenter_fx.py scene_raw.mp4 fxN.json sceneN_fx.mp4` with `hook_card` / `inserts` in `mode: overlay` (product cutout from a CLEAN bottle photo, not the ad crop), plus `punch`.
     Use dur 3.0 or longer for the hook; 1.2 s was too brief and nobody saw it.
  3. `post_presenter.py` on the fx scenes. Set `trim: [0, "auto"]` at TOP LEVEL (a per-scene `trim` key is ignored). Keep `script` text merged without spaces where a Thai phrase is split; spaces are subtitle breaks.
  4. `scripts/graphics_layer.py out.mp4 gfx.json final.mp4 --report report.json --check` then render. The script lives in `scripts/`, not the skill root.
  5. Frame sheet check, then verify-clip.py, then send.
- presenter_fx runs take ~2-4 min per scene. Under the 600 s terminal cap run it as a tracked background job and poll with `sleep`, do not re-run it.

## Product cutout source
- Use a clean product photo (white bg) for cutouts. Do NOT use an ad crop that still carries "Probiotic" banners or claim text.
- Ad images can contain a real child/toddler. Do not attach them to Flow: a humanoid in the reference risks the prominent-person refusal, and the child is not the product.

## Submit behaviour and polling
- After Start generation, the prompt box clears but no generation card may appear for several minutes. Do NOT resubmit immediately: wait 5+ min, reload, then check the grid for a new `Generated video thumbnail` tile and open it. That is how the scene-1 render was found.
- Narrow layout (~800 px): the picker only lists some saved characters and scrolling changes the list. Pick a character from what is actually listed, excluding the last-used one.
- The rendered presenter may not match the character named in the prompt (prompt said น้องเนย, render looked like น้องมิ้นท์). Verify by vision on the first frame before review, and say so in the review message.

## Subtitles
- A Thai phrase can be dropped as SKIPPED ("ไม่แสบตา"). Merging it into the adjacent phrase without a space fixed it.

## Cover
- make_cover with `--cy 1150` may still put the title box over the label. Vision-check the cover and move the title lower or accept and say so.

## Delivery order (final)
1. verify-clip.py on the final file
2. append a clip-log row (sha256, edit ids)
3. send_clip.py for the video
4. send_copy_buttons.py for hashtags and basket link
5. send_photo.py for the cover
6. kill Chrome (`pkill -f '[c]hrome-flow'`), then check with curl; pkill may return SIGTERM even when it works
