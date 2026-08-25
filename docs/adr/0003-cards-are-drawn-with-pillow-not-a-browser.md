# Card images are drawn with Pillow, not a headless browser or ffmpeg drawtext

Card text is Thai, which needs real text shaping: ffmpeg's `drawtext` does none,
so vowels and tone marks land in the wrong place, and it is not a usable option
however convenient it looks. That leaves rendering to an image first. Headless
chromium would give free syntax highlighting and CSS layout, but adds ~400MB to
the image and a browser process to a NAS that is already swapping (2GB swap
fully consumed, and a whole-host OOM outage in August 2026). Pillow shapes Thai
correctly once Raqm is present, and the card layouts are few enough to
hand-position. If this is ever revisited, note that `drawtext` is not the
escape hatch.

Verified on the NAS, 2026-08-24, `python:3.12-slim` + Pillow 12.3.0: the
manylinux wheel does **not** bundle Raqm — `features.check("raqm")` is `False`
and `ImageFont.Layout.RAQM` silently falls back to basic layout with only a
`UserWarning`. Pillow dlopens the system library at runtime, so
`apt-get install libraqm0` flips it to `True` (Raqm 0.10.5) with no rebuild.
The image therefore needs two apt packages, `libraqm0` and `fonts-noto-core`
(which supplies `NotoSansThai-{Regular,Bold}.ttf`). Rendered proof: with basic
layout the mai-ek over sara-ii in "ที่" is dropped; with Raqm it is placed
correctly.

The font is Waree Bold from `fonts-thai-tlwg`, not Noto Sans Thai. Noto Sans
Thai's cmap contains no Latin letters or digits at all, and Pillow does no font
fallback, so every English word in a Thai sentence — which for this subject
matter is most sentences — renders as tofu boxes. The TLWG faces cover both
scripts in one file.
