---
name: gameplay-clips
description: Mode 🎬 of shopee-clip — footage clips cut from official videos (game trailers, and brand product films via references/product-footage.md). Load only after the shopee-clip router picked 🎬. Not an entry point for clip orders.
version: 1.3.0
author: Hermes (IU)
license: MIT
metadata:
  hermes:
    tags: [video, shopee, gameplay, footage, ffmpeg, edge-tts, gemini-tts]
    related_skills: [shopee-clip]
---

# Gameplay / footage clip pipeline (preset `gameplay`, 0 credits, no Flow)
> **Not a game (washer, TV, XR glasses …)? Read `references/product-footage.md` first** — same steps, with deltas for
> research, source gating (`scripts/source_check.py`), burned-in text, the product cutout sticker and `pft-N` hooks.

## Voiceover rule — no countdown or dates (Fix 2026-11-07)
- ห้ามพูดหรือขึ้นจอนับถอยหลัง/จำนวนวันถึงวันวางขาย (เช่น "อีก 118 วัน", ป้าย D-N) และห้ามวันที่ในเสียงพากย์ เพราะคลิปอาจถูกดูหลายเดือนหลังทำ แล้ววันจะผิด — ใช้ hook แบบไม่มีวันที่แทน (`gph-1/3/4/5/6/8/9` ไม่ใช่ `gph-2`/`gph-10`). ไม่ต้องใส่ release_date/release_pill ใน plan.json

## When to use
- Mode 🎬 of `shopee-clip`: the router asked the mode, ran intake and opened the clipjob
  (`clipjob.py new <job> --mode gameplay`). Fix orders ฟุตเทจ / gameplay / ตัดฟุตเตจเกม for any game, or any
  product with an official film. 0 credits: yt-dlp + ffmpeg + TTS + PIL, **no Chrome, no Flow**. No per-shot review
  gate (nothing is generated); one send with the frame-check verdict.
- **No real gameplay footage (no gameplay trailer / narrated throughout / too few clean windows) → use the official
  cinematic cutscene or trailer without asking** (Fix 2026-11-07: «ถ้าหาคลิปเกมเพลแล้วไม่มี หา cinematic cutscene หรือ
  trailer มาทำได้เลย»). The windows must still be speech-free and text/logo-free (a croppable watermark is cropped,
  not a reason to refuse). Say in the delivery that the footage is cinematic/trailer, not gameplay.
- House rules: `/opt/data/skills/shopee-clip/references/house-rules.md` + the router's hard rules (no price/currency/
  discount, EN caption ≤2 words per beat, no shop name/watermark, soft CTA `Link below!` only in the last beat,
  hashtag gate). Delivery = `clipjob.py deliver` (clip + one copy-button message for hashtags and the basket link).
- **Fix attached a reference clip = our audio must sound like it:** measure F0/band/loudness/music-under-VO first,
  then send 2 voice tones in one round (`references/audio-reference-matching.md`, `scripts/measure_audio.py`).
- **Heavy work one at a time** (whisper, build, post): enforced by `heavylock.py` since 2026-11-12. A second heavy
  script waits 120 s, then exits 75 with `BUSY: …` naming the holder: rerun the same command later, do not work
  around it. A run that dies with no output was OOM-killed (4 GB fence): `/opt/data/clips/logs/heavy-log.jsonl` has
  a `start` row with no `end`, and each finished run's `peak_mb`.
- **Footage sourcing can be silent for 15–20 min** (downloads + ASR + vision sheets): send one short status line
  midway (what is done / what is next) and `clipjob.py note <job> "…"`.
- **Vision: one call at a time, small JPEG only.** Run `scripts/vprep.py` (shopee-clip) on every sheet/frame and
  send the `.v.jpg`; never two `vision_analyze` in one tool batch (the second of a pair ran 5–10 min, 2026-11-13). A call that timed out once: do not resend the same image — use OCR/pixels.
- **Before a message that ends the turn with the job still open** (question to Fix, turn-budget wrap-up):
  `clipjob.py wait <job> "<what is needed>"`; on resume `clipjob.py note <job> "resumed"`. The ⏱ line shows the wait.

## Length — 15–50 s, picked from the footage (Fix 2026-11-12)
- No fixed 10/20/30 menu and no Q2 for 🎬. DUR = any whole number of seconds from 15 to 50 that the content
  carries: the usable seconds (speech-free AND text/logo-free, counted in step 2 / footage-sourcing §2a) and the
  story (hook + 4–8 shots of 1.5–3 s + the real end card ~2.5–3 s, and selling points worth a VO line).
- Lock DUR after the footage count and before the VO script; write it in the plan, `clipjob.py note <job>
  "DUR <n> s: <usable> s clean, <why>"` and in the status line. Do not wait for Fix to confirm it.
- Thin content → the shorter clip, never padding: no repeated shot, held frame, stretched footage or filler VO
  to reach a longer number. Rich content → go longer, up to 50 s (Shopee allows 10–60 s).
- A length Fix names in the order wins over this rule (the older "below DUR → clarify" rules apply to it).
- Usable seconds < 15 → clarify with the real number and options (shorter clip at the usable length / another
  source / footage Fix sends) and stop, as in `references/gameplay-pitfalls.md`.
- Scale with DUR: VO char budget (deadline − lead − Σgaps) × 10–16 ch/s, the gap gate (≥4 gaps >0.25 s per 20 s),
  and the shot count. A clip of 15 s or less may use the short-clip path below.

## Cover sticker + thumbnail — DEFAULT on every clip (Fix 2026-11-07 / 11-08)
- After build_v5 + master + remux, add the game case cover (product: the product crop) as a cut-out sticker with
  `/opt/data/skills/shopee-clip/scripts/graphics_layer.py out.mp4 gfx.json final.mp4` — below the Thai subs, clear of
  the footage window and the right rail (`x + w ≤ 640`), one `image_stickers` entry per span BETWEEN hero segs, then
  re-run verify-clip. Confirm it with a pixel diff, not vision (in-span mean can run ~15–45 vs ≈0–2 outside,
  depending on contrast). **graphics_layer re-encodes the audio through its own limiter, so re-run
  `volumedetect` on `final.mp4` before deliver** — the peak gate on `out.mp4` does not cover it and
  verify-clip does not check peaks.
- The sticker shows the WHOLE case front (aspect gate ~1.6 h:w for a Switch case; bbox from a labelled 50-px grid).
- Thumbnail = `make_cover.py` + the same crop composited bottom-right; card size has two limits (width ≤ ~620 and not over the title) and a title wider than ~1000 px is cut: `references/cover-sticker.md`.
- Recipe, measurements and traps: **`references/cover-sticker.md` (read before placing the sticker).**

## Short clip (≤15 s, one or two clean windows) — direct ffmpeg, not build_v5
- Use `references/short-clip-ffmpeg.md` + `templates/short_clip_build.py` when build_v5's plan is overkill. Same gates (ffprobe, output flags, volumedetect on the OUTPUT, frame check, send_clip).
- Mixing traps that silently produce bad audio: a filter label used twice (split it with `asplit`); `amix duration=first` truncates; sidechain output follows the music input length (pad it); a silent source window leaves the clip VO-only.

## LOOK standard — v5 = DEFAULT (Fix อนุมัติ demo แล้ว)
- **ทุกคลิปประกอบด้วย `scripts/build_v5.py` (plan.json; schema ใน docstring)**: cold open เต็มจอด้วยช็อตแรงที่สุด (ห้ามเปิดด้วยการ์ดไตเติล; โลโก้เกม PNG ใสเล็ก ๆ ทับ ~1.5 วิ), push-in 1.00→1.10 ทุก window shot (`--selftest-zoom` ต้อง PASS), hero เต็มจอ (crop 9:16 จาก trailer 1080p ต้นฉบับ) ≤3 ช็อต, ตัดลงบีต (`scripts/beats.py`), แฟลชขาว 3 เฟรม + whoosh/impact ที่ seam (`scripts/make_sfx.sh` → `assets/sfx/`), ป้าย `OUT NOW` เท่านั้น (ห้าม `D-N` — กฎ no countdown ด้านบน), loop tail 0.3 วิ crossfade เข้าเฟรมแรก, grade [1.18,1.15,1.04]
- **Layout ตาม `references/safe-zones.md`: pill y=210, หน้าต่างเกม y=280, subs MarginV 465** (ค่า v4 pill y=52 / MarginV 290 อยู่ใต้ UI แอปทุกแพลตฟอร์ม)
- bg.png = key art cover-fit + blur (step 6); caption pill Fredoka-SemiBold 40pt พาสเทล `0xFF8FB1/0xFFD166/0x8AC926/0x7A5CFF@0.92`, `boxborderw=14`, `borderw=3:bordercolor=0x5A2A4A`; ซับไทย libass **Itim 48 เหลืองพาสเทล `&H0066D1FF` ขอบน้ำตาลเข้ม `&H00203050` Outline 5 Shadow 2.5, `BorderStyle=1` (ไม่มีกล่อง), Alignment=2** (ฟิกเลือกแทนกล่องดำ เพราะกล่องไม่น่ารักและบังสินค้า — ห้ามกลับไปใช้ BorderStyle=3; จะเปลี่ยน look ใช้สูตร A/B ใน `/opt/data/skills/shopee-clip/references/presenter-post.md` → Changing the subtitle look) + filter ต้องเป็น `ass=…:shaping=complex` เสมอ; เสียง trailer volume 0.75 + duck `sidechaincompress threshold=0.04:ratio=4:release=500` + VO
- วิธีรัน/gates/pitfalls: **`references/look-v5.md` (อ่านก่อนทุกคลิป)**. `scripts/build.sh` (v4: หน้าต่าง 16:9 นิ่งบน bg) = fallback เท่านั้น

## Steps
-1. **Multi-image intake** (the router's step 1 already ran it for a routed order; run it here only when it did not): `uv run --with pillow python /opt/data/skills/shopee-clip/scripts/intake_images.py <order_image> <workdir>` → one `vision_analyze` on `intake_sheet.jpg` covering every image Fix sent together (cover art, edition, listing title, platform badges) BEFORE footage search or plan. Later image messages for the same game = part of the order, never a new clarify.
0. Work dir `/opt/data/clips/work/<job>/` (the clipjob workdir; `cache/scratch` is pruned after ~24 h and a revision needs the files) — `cp <skill_dir>/fonts/*.ttf .` (Itim-Regular, Fredoka-SemiBold, FredokaSB-Static, Mali-Bold) ห้ามใช้ DejaVu/Liberation กับไทย (ไม่มีสระ → กล่องว่าง). **Fredoka-SemiBold.ttf เป็น variable font: drawtext (`fontfile=`) ใช้ได้ แต่ libass/ASS เลือกจาก fontsdir ไม่ได้ แล้ว fallback เป็น DejaVu เงียบ ๆ** → ใน ASS style ทุกตัวใช้ `Fontname=FredokaSB, Bold=0` (ไฟล์ static `FredokaSB-Static.ttf`) และยืนยันด้วย `ffmpeg -v verbose … -vf ass=… -f null - 2>&1 | grep fontselect`
1. **Hook + ข้อมูลเกม**: hook เลือกด้วย `python3 /opt/data/skills/shopee-clip/scripts/perf.py pick-hook --category game --prefix gph-` (ids `gph-1..10` ใน `/opt/data/skills/shopee-clip/templates/hooks.md`; ไม่ใส่ `--prefix` ได้ `game-N` ผิดชุด; ไม่มีข้อมูล perf = LRU; LRU อาจคืน `gph-10`/`gph-2` ซึ่งเป็นวันที่ → ส่ง `--candidates gph-1,gph-3,gph-4,gph-5,gph-6,gph-7,gph-8,gph-9` ทุกครั้งที่คลิปไม่มีวันที่). `web_search "<เกม> <platform> release date"` 1 ครั้ง → แนวเกม + จุดขาย + วันวางขาย. **ลิสติ้งที่ฟิกส่งมาอาจล้าสมัย**: ถ้าข่าวทางการใหม่กว่าเลื่อนวัน → ห้ามวันเก่าบนจอ/เสียง ใช้ PRE-ORDER หรือไม่แสดงวัน และบอกฟิกใน delivery ให้แก้ลิสติ้ง (ลิสติ้งที่ค้างวันเดิมทำให้คนซื้อเข้าใจผิด). **วันที่สองแหล่งขัดกัน** (หน้าร้าน ≠ search): ใช้ระดับเดือนเท่านั้นทั้งเสียงและจอ — ห้ามเลขวันหลุด แล้วบอกทั้งสองวันพร้อมเหตุผลใน delivery; ตรงกันถึงระดับวัน → ใช้ระดับวันได้ (hook 📅 ใช้ได้เฉพาะกรณีนี้; `pick-hook` ที่ได้ hook นับถอยหลัง/📅 ทั้งที่วันยังไม่ยืนยันจากผู้จัดจำหน่าย → ข้ามไปเลือก hook ที่ไม่มีวันที่ แล้ว log `hook_id: "custom-<slug>-N"` ตามที่คลิปก่อนหน้าทำ)
2. ฟุตเตจ: `uv tool run yt-dlp -f "bv*[height<=1080]+ba" --merge-output-format mp4 -o trailer.mp4 <YouTube official trailer>`; **ถ้าขึ้น `Sign in to confirm your age` ใช้ `--extractor-args 'youtube:player_client=tv_embedded'`** (ไม่ต้องคุกกี้); เลือกฟุตเตจด้วย contact sheet + ASR ตาม `references/footage-sourcing.md` (**จัดอันดับแหล่งด้วยผลรวมช่วงว่างที่วัดจาก ASR ก่อน ไม่ใช่ความยาว — สั้นพูดเยอะ/ยาวเงียบ เป็นแค่ค่าเฉลี่ย: preview 17 นาทีที่มีคนบรรยายตลอดใช้ได้จริง ~11 วิ แต่คลิป 2.5 นาทีเสียงขะยะมีช่วงว่าง ~28 วิ; cinematic ≠ gameplay**); Steam/Epic CDN mp4 `curl` ตรงๆ ได้; ลิงก์ Shopee Video → WAF กัน → ใช้ trailer ทางการแทนแล้วบอกฟิก. **ทันทีที่ได้ trailer ดึงซับอัตโนมัติมาทำตารางเสียง**: `uv tool run yt-dlp --write-auto-subs --sub-lang en --skip-download -o subs <url>` (ได้ `subs.en.vtt`; ห้ามใช้เทมเพลต `%(ext)s` — eval ของ shell ชนวงเล็บ) แล้ว parse เป็นรายการช่วง "มีคนบรรยาย":
   - Parsing the auto-subs into a speech table, ASR confirmation and the seg rules: **`references/footage-sourcing.md` §0** (read before choosing segs).
3. **Encode MASTER ก่อนตัดเสมอ** (trailer มักเป็น AV1 1080p60): `ffmpeg -i trailer.mp4 -vf "scale=720:-2,pad=720:1280:0:320:black,fps=30,format=yuv420p" -c:v libx264 -preset veryfast -crf 20 -c:a aac -b:a 128k -ar 48000 -ac 2 master.mp4` (เก็บ trailer.mp4 ไว้ — hero shot ของ v5 crop จากต้นฉบับ). **Corner overlays are removed in THIS encode, not in the hero:** if the contact sheet shows a publisher/hardware FPS, DLSS or RTX panel in a corner, crop it out before scale (e.g. `crop=1560:878:0:100` on a 1920×1080 source whose overlay starts at x≈1605 top-right and x≈1674 bottom-right; 16:9 kept). The hero's centre 608-px crop is usually clear of corner overlays — verify on a frame, don't assume.
4. เลือกช็อต (ก่อนวาง hero/window ให้ผ่าน **dark-dip scan** ใน `references/footage-sourcing.md` §5c — source หลายตัวมีการ cut/fade เป็นดำกลางเรื่อง; hero ที่เริ่มตรงจุดนั้นจะขึ้นเฟรมดำเป็นวินาทีแรก): scene detect `select='gt(scene,0.25)'` (จุดตัดแข็ง) + รันซ้ำที่ `0.06` (dissolve) เป็นจุดหยาบ → สุ่มเฟรมด้วย `-ss` ห่าง ~0.5 วิ ในช่วงที่สงสัย. **ยืนยัน in/out ด้วยเฟรมจริงแบบแบทช์**: `ffmpeg -ss T -i master.mp4 -frames:v 1 -update 1 f_T.png` แล้วป้ายด้วย PIL จาก list เวลาในโค้ด (ห้ามพึ่งป้ายจาก fps filter/ให้ vision อ่านป้าย) ต่อเป็นแผ่นเดียวถาม vision ครั้งเดียว. โครง: **ช็อตแรงสุดเปิด (hero)** → 4–8 ช็อต 1.5–3 วิ → **การ์ดท้าย trailer จริง (โลโก้ + วันวางขาย) ~2.5–3 วิ — ยืมของจริง ห้ามวาดใหม่**. crop แถบซับของฟุตเตจ (`crop=720:110:0:615`) ตรวจด้วย — trailer เผาซับค้างหลังเสียงพูด 1–3 วิ เลื่อน in/out ให้พ้นได้ก็เลื่อน; เลี่ยงเฟรมที่มีตัวเลขหน้าตาเหมือนราคา. **ก่อนล็อก seg ให้ OCR ทั้งเรื่องที่ 1 fps หนึ่งรอบ** (วิธีใน `references/footage-sourcing.md` §5d) เพื่อผังข้อความที่เผาลงเฟรมแบบมีเวลา — vision บน contact sheet คืนเป็นคำอธิบาย ตอบคำเดิมซ้ำทุกเฟรม และพลาด caption ตัวเล็ก ~18 px ได้ จึงใช้ตัดสินเรื่อง "ช่วงนี้มีตัวหนังสือไหม" ไม่ได้
5. ตัด seg (เมื่อใช้ v4 fallback) / plan segs (v5): **วัด `volumedetect` ทุก seg ก่อน build** — ช่วงว่างอาจเงียบสนิท (−42 dB) → map เสียงจาก gap อื่น (`-map 0:v -map 1:a`, v5: `audio_src/audio_in`). **src ต้องเป็นช่วง gap เท่านั้น เลือกตัวดังสุดในกลุ่ม gap — ห้ามเลือกค่าดังสุดของทั้งเรื่อง** (ความดังใน trailer เล่าเรื่องคือเสียงบรรยายอังกฤษ). หลัง map ต้อง ≥ −40 dB. การ์ดท้ายมักเงียบสนิท → map แบบเดียวกัน
6. bg.png: `uv run --with pillow python <skill_dir>/scripts/make_bg.py --art art.jpg --ill ill.png --strip strip.png --out bg.png` — art จากเว็บค่ายเกม (nintendo.com → `assets.nintendo.com` ปก/ภาพใส; ไม่มีหน้า product → key art จากหน้าเกมของผู้จัดจำหน่าย); **vision-verify ทุกภาพก่อนใช้**; `--ill` = ตัวละครใสหรือโลโก้ PNG ใส (ตรวจ alpha); คำนวณ `h = w × (h₀/w₀)` ให้ภาพไม่ชนป้าย/หน้าต่าง (layout v5: `y + h ≤ 190`); ไม่มี key art (ค่ายไม่มีภาพนิ่งให้) → ดึงเฟรม 1080p จาก trailer ด้วย `ffmpeg -ss T -i trailer.mp4 -frames:v 1 art.png` แล้วใช้เป็น `--art` (make_bg cover-fit + blur อยู่แล้ว)
7. **VO DEFAULT = เสียง B: `scripts/gen_vo_natural.py` engine `gemini`** (Gemini TTS เสียง Leda, whole-script 1 request/คลิป; ฟิกเลือกแล้ว) — อ่าน **`references/natural-vo.md`** ก่อนใช้ทุกครั้ง:
   - Script style, quota fallback, `vo_end` window, Thai ASR check, deadline and takes: **`references/natural-vo.md` → Run rules** (read every run).
8. ประกอบ (key ของ plan ที่พลาดบ่อย): **ไม่มี `release_date` → ลบทั้ง key `release_pill` (ไม่งั้น KeyError)**; ข้อความ 3 คำขึ้นไปหรือยาว ใส่ `sub_text` แบ่งบรรทัดด้วย `\N` เอง (ไทยไม่มีช่องว่างให้ libass ตัด; sub_linecheck `bands=N+1 want=N` (เช่น bands=3 want=2 จาก event 2 บรรทัด) = บรรทัดยาวเกิน — ทั้งไทยไม่มีช่องว่างให้ libass ตัด และบรรทัดละตินยาวเกิน ~22 อักขระ (Itim 48 ในกรอบใช้การ 520px) libass ตัดเอง → แก้ที่ข้อความซับให้สั้น/แบ่งบรรทัด ห้ามแตะบท VO); index ของ `sub_text`/`caps` นับ 0-based; ถ้า `master` เป็นช่วงที่ encode จาก `-ss` ให้ rebase seg/`speech.vtt` ให้เป็นเวลาในไฟล์นั้น (ดู footage-sourcing §4); ไม่มี beats ที่ตรงช่วง → `snap:false` ทุก seg. **`build_v5.py plan.json --check`** (หยุดถ้าผิดกติกา: seg นอก gap, pill ทับกัน, pill >2 คำ/non-ASCII/คล้ายราคา, CTA นอกเซกท้าย) → render. `--check` ไม่ตรวจ **เสียง** CTA ของ VO: วลี CTA ต้องเริ่มในเซกท้าย (ดู `references/natural-vo.md` → CTA phrase must start inside the last seg) ก่อน render. **ตัวเลขใน pill EN = โดนข้อ "คล้ายราคา" ทันที** (`4K TV` ถูกปฏิเสธ) → เขียนเป็นคำล้วน (`TV MODE`); ตัวเลขในซับไทยใช้ได้ตามเดิม. CAPS/pills วางตาม timeline ของ VO (`subs.timeline.json`) ห้ามสอง pill ทับกัน; วันที่เต็ม `25 FEB 2027` = 3 คำ → pill ใช้ `25 FEB`
9. **master ก่อน gates (ครั้งเดียว)**: `bash <skill_dir>/scripts/master.sh $PWD/out.mp4 -13.7 -6.0` (v5 มี impact SFX → ceiling −4.5 ทะลุ max −2.8; **the ceiling is a target, not a guarantee: the measured peak has come out 3–4 dB above it (−6.0 → −1.9). Judge by the peak master.sh prints; if ≥ −3, rerun master.sh (same values once, then 1 dB lower) and remux, no rebuild**) → **remux faststart เสมอ** `ffmpeg -y -v error -i out.mp4 -c copy -movflags +faststart o.mp4 && mv o.mp4 out.mp4` (master.sh คืนไฟล์ที่ไม่มี faststart → verify ล้ม `no moov atom`). Gates (บังคับทุกข้อ):
   - `ffprobe`: duration ≈ เป้า, `r_frame_rate` 30/1, `nb_frames` ≈ วินาที×30, **audio dur == video dur**, High/yuv420p/L4.0
   - เสียง: **duck-only delta ≥6 dB** (render กราฟเดียวกันแต่ VO เป็นแค่ sidechain key → เพลงล้วนที่ duck แล้ว; เทียบ mean ช่วง VO ของ premaster mix กับ duck-only) + whole max < −3 dB. decode เป็น wav ก่อนตัดช่วงวัด (seek mp4 ตรงๆ หน้าต่างเลื่อน). **build_v5 export stems ที่ `work/music_v5.wav`, `work/sfx_v5.wav`, `work/vo_v5.wav` แต่เป็น raw ก่อน gain** (เปลี่ยน `music_gain` แล้วค่าใน `music_v5.wav` ไม่เปลี่ยน) → กราฟ gate ต้องใส่ `volume={music_gain}` หลัง amix ดนตรี+sfx และ `volume={vo_gain}` ที่ VO key เอง ตามสูตรใน `references/look-v5.md` → Duck-only render. **วัดโดยไม่คูณ gain = ต่ำกว่าจริง 20·log10(music_gain) → FAIL ปลอม** (music 0.5 วัดได้ 5.3 dB ทั้งที่จริง 9.7) แล้วจะไปลดดนตรีเกินจำเป็น; ตัวเลือกอื่น `scripts/duck_gate.py` (rebuild จาก master ตาม `--segs` แต่ไม่รวม SFX ที่ seam). อย่าอ้างว่า gate นี้ผ่านจนกว่าจะวัดจริงในคลิปนั้น
   - ซับ: `uv run --with pillow python <skill_dir>/scripts/sub_linecheck.py <dir>` (v5: คัดลอก `subs_v5.ass` เป็น `subs.ass` ในโฟลเดอร์ทดสอบ เพราะ builder เขียน margin ใหม่ลงไฟล์นั้น; ไฟล์ต้องอยู่ใน `<dir>` ตรง ๆ หาไม่เจอสคริปต์ยัง exit 0). FAIL `bands=1 want=2` → `scripts/sub_bandprofile.py <dir>` ชี้ขาดว่าเป็น false positive (fill สองบรรทัดห่าง ≥16 px = marks/หางเชื่อมแถบ → ผ่าน + จดเหตุผลใน notes) หรือบรรทัดชนจริง (<16 px → แก้ข้อความซับ)
   - `python3 /opt/data/skills/shopee-clip/scripts/verify-clip.py` (cp เข้า `/opt/data/home/Downloads/` ก่อน)
   - frame check: แผ่นเดียว (cold open / seam / hero / CTA / loop tail) ถาม vision ให้ flag ราคา/฿/%/QR/ชื่อร้าน, pill EN ≤2 คำ, ไทยบนจอเฉพาะซับเรา — **closed questions only (is a sub showing / are vowels and tone marks complete / any empty box); vision garbles Thai sub text even when the sub is right, never compare its transcription with the script**; ความถูกต้องของข้อความเช็คจาก subs.ass + sub_linecheck, แถบดำว่าง, แฟลชแรงเกิน; วันที่ในการ์ดท้ายที่ยืมมายืนยันด้วย crop zoom เสมอ. **ป้าย pill เช็คด้วยแผ่น crop แถบป้าย** (`crop=600:90:60:180` scale 2x ทีละเวลา แล้วเขียน expected text ลงใน label) — vision ตอบตรงกว่าถามจากภาพเต็มเฟรม. **ห้ามใช้แผ่นหลายเฟรมยืนยัน *เวลา* ของซับ**: vision จะตอบข้อความซับเดิมซ้ำทุกเฟรมทั้งที่ซับคนละใบ ให้เช็คเวลาซับจาก plan/timeline แทน OCR
10. **Deliver — one command:** copy the final into `/opt/data/home/Downloads/<job>.mp4`, then
    `python3 /opt/data/skills/shopee-clip/scripts/clipjob.py deliver <job> --final /opt/data/home/Downloads/<job>.mp4 --hashtags "<tags>" --cover <thumb.jpg> --caption "<short Thai caption>" --hook-id gph-N --category game [--notes "…"]` (a non-game product: add `--style footage`, its own category and a `pft-N` hook — `references/product-footage.md`)
    (`--report` is optional for gameplay: deliver checks audio == video duration itself). It runs verify-clip, appends
    the clip-log row (`style: gameplay`, `credits: 0`), sends the clip, the copy-button message (hashtags + basket
    link) and the cover, then check_delivery. A failed send = rerun the same command. Send no MEDIA line and no
    hashtag text in the reply. Cleanup afterwards: delete only scratch (frame sheets, OCR/scan files, intermediates)
    and the Downloads copy; **keep `trailer/master/plan/vo/bg/cutout` in the workdir** for step 11.
11. **Revision pass (ฟิกทักแก้จุดเดียว)** — `clipjob.py reopen <job> --reason "<what Fix asked>"`, then reuse the
    passed seg/bg/trailer/master: fix the part he named → new `vo.mp3` + `subs.ass` (`--from-take` if only timing)
    → **regenerate every pill from the new timeline** → build → master → remux → the full gate set → the same
    `deliver` command with the new final (it logs a new row starting `REVISED: <reason>`; never rewrite the first row).

## Stacked orders — คลิปหลายอัน
- ฟิกสั่งคลิปต่อกัน 2+ อัน: งานเบา (search, โหลด trailer, เขียนบท, plan) ทำคู่ขนานได้ แต่ **งานหนัก (whisper/ASR, build_v5 render, gates) รันทีละคลิปเท่านั้น** — RAM NAS ไม่พอให้ลูกหลายตัว render พร้อมกัน (OOM ฆ่า gateway). ถ้าใช้ `delegate_task` ให้ส่งทีละ 1 ลูกที่ทำงานหนัก หรือสั่งลูกให้ทำแค่ส่วนเบาแล้วแม่ render เองตามลำดับ
- brief ของลูกต้องยืนด้วยตัวเอง: copy กติกาที่จำเป็นทั้งหมด (ห้ามราคา, caption EN ≤2 คำ, ส่งผ่าน `clipjob.py deliver` เท่านั้น, hashtag gate, verify + send) เข้า context ตรงๆ ห้ามสั่งให้ไป load `shopee-clip` ทั้งไฟล์
- จัด `hook_id` คนละอันให้ลูก; append `clip-log.jsonl` ครั้งละ 1 บรรทัด ห้าม rewrite
- อย่าเดารหัสสินค้า/URL asset ใส่ brief — ให้ลูก resolve เอง
- รายงานลูก = self-report → เช็คเอง: sha256 ตรง `delivery-log.jsonl` + `ok:true`/`message_id`, ffprobe, hashtag gate เป็นโค้ด, `check_delivery.py` exit 0. ลูกเงียบหาย (ไม่มี completion) = ตรวจไฟล์บนดิสก์แล้วทำส่วนที่ขาดต่อเอง


## Pitfalls
**`references/gameplay-pitfalls.md`** — every item cost a real run, grouped by step (footage + speech gaps, audio,
subs, build, vision, terminal, delivery). Read the group for the step you are about to run.
