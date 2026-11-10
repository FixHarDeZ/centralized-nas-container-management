# 9:16 safe zones (Reels / TikTok / Shorts / Shopee Video) → 720x1280 bands

Researched 2026-11-05. Everything here is the **organic/ads overlay** zone: where the app's own UI
(tabs, username, caption, right-hand like/comment/share rail, product card, progress bar) sits on top of the video.

## Sources
| Platform | Source | Status |
|---|---|---|
| FB/IG Reels | Meta Business Help "About text overlays and the safe zone for ads in Stories and Reels" — https://www.facebook.com/business/help/980593475366490 | Official. The page *text* now only says "keep top, bottom and sides free"; the 14% / 35% / 6% numbers are in its diagram / Ads Guide and repeated by every checker (e.g. https://adchecklab.com/articles/instagram-reels-safe-zone-template, https://www.solidlabs.com/social-safe-zones). Same page: **Reels ads with disclaimers → keep bottom 40% free.** |
| TikTok | TikTok Ads Help "In-feed ad specs → Safe Zone" (downloadable template zips, size depends on caption length + anchor) — https://ads.tiktok.com/help/article/tiktok-auction-in-feed-ads | Official templates; pixel numbers measured from them by https://shotcraft.video/reference/platform-safe-zones/ (240 top / 660 bottom / 120 left / 300 right, right reserve only in the rail band y 840–1260 of 1920). No public pixel map in the text. |
| YouTube Shorts | Google universal vertical-video template (from https://support.google.com/google-ads/answer/13547298 / 9128498), measured by https://adkit.so/tools/safe-zones/youtube and shotcraft | Official template: safe rect x48–888, y288–1248 of 1080x1920 (15% top, 35% bottom). |
| Shopee Video | Shopee Seller Education Hub "Creating high quality videos" — https://seller.shopee.sg/edu/article/24431/create-high-quality-shopee-video | **No official safe-zone / pixel guidance exists that I could find.** Shopee only says: ≥720p, full-screen 9:16 with no black bars, 10–60 s, add text to summarise features, no other-platform logos/watermarks, no "link in bio"/"tap the orange cart" phrases. Its player has the same TikTok-style layout (top tabs, right rail incl. basket, bottom-left creator/caption + product card) — **treat it as TikTok (unverified assumption, not measured).** |

## Pixel bands (720x1280 = 1080x1920 × 2/3)
| Platform | Top danger | Bottom danger | Left | Right |
|---|---|---|---|---|
| Meta Reels (14/35/6%) | y 0–179 | y 832–1280 | 0–43 | 677–720 |
| Meta Reels w/ disclaimer (40%) | — | y 768–1280 | | |
| TikTok in-feed | y 0–160 | y 840–1280 | 0–80 | 640–720 above rail; **520–720 for y 560–840** (rail) |
| TikTok ad + anchor + 4-line caption ("paranoid") | | y ≈677–1280 | | |
| YouTube Shorts | y 0–192 | y 832–1280 | 0–32 | 592–720 |
| Shopee Video | (assume TikTok) | (assume TikTok) | | |
| **Union (all of the above, normal case)** | **y 0–192** | **y 832–1280** | **0–80** | **592–720; 520–720 in y 560–840** |

Clear box for everything: **x 80–592 (≈80–520 in y 560–840), y 192–832** → 640 px tall. Note it is not centred: right rail is wider than left margin.

## Our gameplay layout v4 — measured on lego-batman-gp/out.mp4 (pixel bbox + vision on `scratch/safezone_check.png`)
- Caption pill `y=52`: box measured **y 38–94** → entirely under the top UI on every platform (tabs/"Following | For you", search, Reels camera icon). ❌
- Thai subs `MarginV=290`: box measured **y 882–1005** (2 lines) / 928–1005 (1 line) → entirely in the bottom band (username + caption + product card + progress bar). ❌
- Game window y 320–725: vertically safe ✅; its right ~200 px from y 560 down sits under TikTok/Shopee rail icons — acceptable (footage, not text).
- Character illustration ~y140 above window: decorative, being under top UI is fine; but it must not collide with a moved pill (see below).

## Recommendation (keeps pill + subs clear on Reels, TikTok, Shorts, Shopee-as-TikTok)
| Element | Now | Recommended | Result (measured in mock) |
|---|---|---|---|
| Caption pill drawtext `y` | 52 | **210** (box ≈ y 196–252; box = y−14 … y+42 at 40pt/boxborderw 14) | clear of YT 192 ✅ |
| Game window overlay y (`overlay=0:Y`) | 320 | **280** (window 280–685; crop from master stays `crop=720:405:0:320`) | gives room for 2-line subs below |
| Subs `MarginV` | 290 | **465** (box bottom y≈830; 2-line top ≈707) | inside 832 ✅ |
| Subs `MarginL / MarginR` | 50 / 50 | **60 / 140** (text area x 60–580) | clears YT rail (592) and the actual TikTok icon column (~x 640+); still touches TikTok's *conservative* 520 rail reserve by ~40 px — tradeoff vs. 3-line wraps |
| Illustration (`make_bg.py --ill-y/--ill-w`) | y≈140, bottom ≤318 | **y + h ≤ 190** (e.g. `--ill-y 20`, w so h ≤ 170) or left/right of the pill | must not hit the pill box 196–252; under top UI is OK (decoration) |

Tradeoffs / pitfalls:
- With window at 280 the 2-line sub box (707–830) sits just below the window bottom (685) — good. If the window stays at 320, MarginV 465 2-line subs overlap the bottom ~18 px of the game window (still readable, acceptable fallback).
- **Thai has no spaces → libass can't wrap long phrases**: one phrase rendered x 1–638 on one line even with the narrower margins. Insert `\N` in PHRASES_TEXT for any phrase wider than ~480 px (≈ 19 Thai chars at Itim 48, current style), check with `sub_linecheck.py`.
- Reels *ads* with disclaimers want the bottom 40% (y ≥768) clear and TikTok ads with anchor + long caption push to y≈677 — impossible to satisfy together with a 2-line sub under a 405 px window. We post organic, so the normal-case union above is the target.
- Pill is centred (x=(w-text_w)/2); a 2-word pill at 40pt is ~250 px wide → x ≈ 235–485, inside the clear box.
- **Presenter clips** (full-frame talking presenter, captions locked to upper half), 720x1280: caption box **top ≥ y 200, bottom ≤ y 600**, text area **x 80–580** (keep x ≤ 520 if a caption block reaches below y 560, rail band). In libass terms: `Alignment=8` (top-centre) `MarginV=210`, `MarginL=80`, `MarginR=140`; hook pill/title `y=210` same as gameplay. Keep the presenter's face roughly y 250–800 so the bottom 832–1280 band (username/caption/product card) only covers torso/hands, and don't put product name/CTA text below y 832.
- Frame-check helper: `scratch/sz/draw.py` pattern (PIL translucent red bands on a real frame) — bands: top 0–192, bottom 832–1280, sides 43, rail x≥520 for y 560–840.
