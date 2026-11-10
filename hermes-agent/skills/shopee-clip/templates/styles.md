# Clip style presets — the "Option" Fix asked for (2026-10-31)

> **2026-11-05 override:** Flow must render NO on-screen text. Use the "ON-SCREEN TEXT: NONE" block from `references/presenter-post.md` instead of any caption/pill instruction below. EN pills and Thai subs are added in post by `scripts/post_presenter.py`.


Fix: *"แนวคิดของช่องผมยังเป็นแนวเดียวอยู่คือตัวละครพูดอธิบายสินค้า สามารถทำให้มีแนวอื่นด้วยได้ไหมแล้วเรามี Option เลือกในตอนทำคลิป"*

So every clip order now asks TWO things in one clarify call: **กี่วิ?** and **แนวไหน?** (see `SKILL.md` → Duration selection). Each preset below is a drop-in variant of `templates/clip-prompt.md`: same house rules (no price, EN-only on-screen captions, soft CTA last, 9:16, Thai voiceover), different sequence + whether the character chip is attached.

## `presenter` — พรีเซนเตอร์พูดอธิบาย (DEFAULT, ปัจจุบัน)
- Attach the random character chip; 4-beat sequence (hook → โชว์ปก → ชี้จุดเด่น → ชี้ลง CTA).
- **เสียงพากย์ไทย + caption EN สั้นต่อ beat อย่างเดียว** — ห้ามใส่คำอธิบาย/สไตล์บรรยาย "น่ารักๆ" ในพรอมป์ (Fix สั่ง 2026-11-05: *"ปรับใหม่ กรณี gen แบบ presenter ไม่ต้องมีคำอธิบายน่ารักๆในคลิปแล้ว เพราะ Flow ชอบแหกกฏใส่มาให้ แล้วภาษาไทยเพี้ยนตลอด เอาออกไปเลยดีกว่า"*) = ตัด `Audio (Cute and cheerful female voice in Thai)` / `เสียงพากย์ไทยหญิงน่ารักน้ำเสียงสดใส` / `ผู้บรรยาย: พรีเซนเตอร์หญิงน่ารัก ยิ้มเก่ง` ออกหมด เหลือแค่ `Audio (Thai voiceover)` + ประโยคพูดจริง + ป้าย EN สั้นตาม beat (ดู `templates/clip-prompt.md` และ `templates/style-card.md`) — นี่คือ baseline ของทุก prompt ในคลังนี้

## `hands` — มือล้วน ไม่มีหน้าคน (close-up แกะกล่อง)
- **ไม่แนบ character chip** — เฟรมมีแค่มือ + สินค้า + พื้นหลังสตูดิโอเดิม.
- Sequence: มือหยิบกล่องเข้าเฟรม → หมุนให้เห็นสัน/หลัง → นิ้วชี้จุดเด่นบนกล่อง → วางกล่องแล้วชี้ลง CTA.
- เสียงพากย์ไทย + music เดิม; caption EN น้อยกว่าเดิม (2-3 จุด) เพราะจอเต็มด้วยสินค้า.

## `broll` — สินค้าล้วน หมุนช้า (no presenter, no hands)
- **ไม่แนบ character chip**; สินค้าลอย/วางบนแท่นหมุนช้า พื้นหลังพาสเทล.
- Sequence: wide shot → push-in ที่ปก/จุดเด่น → มุมเอียงตัดแสง → จบด้วยสินค้าเต็มเฟรม + CTA caption.
- เสียงพากย์ไทยเล่าต่อเนื่อง 10 วิ; caption EN ต่อ beat. เหมาะคลิปที่ปกสินค้าสวยอยู่แล้ว.
- **ตั้งแต่ 2026-10-31 preset นี้ = จัดเต็มอลังการเป็นค่าเริ่มต้น** (Fix: *"ถ้าคลิปสินค้าแนวโชว์ตัวสินค้า อยากให้ทำแบบโชว์สินค้าแบบจัดเต็ม อลังการ เสียงสีแสงอลังการที่สุด"*) → **แปะบล็อก `SHOWCASE MODE` ด้านล่างเข้าไปในทุก scene prompt**

## SHOWCASE MODE — บล็อก "โชว์สินค้าจัดเต็มอลังการ" (paste เข้า prompt)
ใช้เมื่อ preset = `broll` หรือฟิกสั่งเองว่า "อลังการ / จัดเต็ม / โชว์สินค้า" (ใช้ได้กับ preset อื่นด้วยถ้าเขาสั่ง) — คัดลอกทั้งก้อนไปไว้หลัง beat list:

```
SHOWCASE MODE (จัดเต็มอลังการที่สุด — สี เสียง แสง ต้องจัดเต็ม):
- ฉาก: สินค้าลอย/หมุนช้าบนแท่นทรงกลมหรือฐานมีแสงยิงจากด้านล่าง พื้นหลังไล่สีสดจัด (ตัดกับสีสินค้า) มีแส้แสงวิ่งผ่าน + ประกาย sparkles ลอยผ่านเฟรม + เงาสะท้อนบางๆ บนพื้น
- กล้อง: เริ่มกว้างแล้ว push-in เข้าหาสินค้า → orbit รอบสินค้า ~45 องศา → macro close-up ที่จุดเด่นบนตัวสินค้า → จบมุมกึ่งเอียงตัดแสงให้สินค้าเด่นเต็มเฟรม
- แสง: rim light สีตัดกันสองข้าง + lens flare ตอนสินค้าโผล่/หมุนมา facing กล้อง ให้ดูเหม่างานโฆษณาระดับแบรนด์
- เสียง (สำคัญ — Flow สร้างเสียงตาม prompt เท่านั้น ต้องเขียนเป็นคำสั่งเสียง): music อลังการแนว cinematic มี riser ไต่ขึ้นแล้ว impact/stinger ตอนสินค้าโชว์เต็มตา, sound effect whoosh ตอนกล้องเข้า + sparkle chime ทุกครั้งที่แสงวาบ ระดับเสียงจัดเต็มแต่ยังได้ยินเสียงพากย์ไทยชัด
- caption: ใหญ่ เด้ง มี glow/ขอบสีตัดกับพื้นหลัง ไม่เกิน 2 คำต่อ beat เป็นอังกฤษ/คำยืมเท่านั้น (เช่น Mega Bundle / DHA 27mg / 72 Packs / Link below!)
- คงกติกาทุกข้อ: ห้ามราคา/สกุลเงิน/ส่วนลด ทั้งพูดและบนจอ, ห้ามชื่อร้าน/watermark, CTA นุ่มนวลเฉพาะฉากสุดท้าย
```
(frame check เหมือนเดิมทุกเฟรม — อลังการไม่ได้ยกเว้นกติกาอะไรเลย)

## `gameplay` — ตัดฟุตเตจเกม/ตัวอย่างเกมมาต่อเป็นคลิป (Fix ให้ reference 2026-11-01)
- **ตั้งแต่ 2026-11-01 มีสกิลแยก `gameplay-clips` — สั่งแนวนี้ให้ load สกิลนั้นเป็นตัวหลัก** (scripts + ฟอนต์ + สูตร ffmpeg ครบ ไม่ต้องแกะจากบันทึกรอบก่อน) บล็อกด้านล่างนี้คือสรุปสั้นไว้อ้างอิงเท่านั้น
- **LOOK มาตรฐานของ preset นี้ = สูตร v4 ของคลิป Pikmin 4 (ฟิกสั่ง 2026-11-01: "รอบหน้าถ้าทำแบบฟุตเทจทำคลิปเกมเอาแบบนี้เลย") — ห้ามกลับไปใช้แถบดำว่างเด็ดขาด** ทุกองค์ประกอบที่ต้องครบในคลิปเกมทุกคลิป: (1) **พื้นหลัง key art ของเกม** (ปก/ภาพประกอบจากเว็บค่ายเกม) blur + มืดลงเล็กน้อย เต็มจอแนวตั้ง 720x1280 (2) **หน้าต่าง gameplay 16:9 letterbox กึ่งกลางจอ** ที่ y=320 (3) **ภาพประกอบตัวละครใส** วางเหนือหน้าต่าง (~y140) + แถบตัวละครใสใต้สุดของจอ (4) **caption pill EN สีพาสเทลเปลี่ยนตาม beat** (Fredoka กลม, กล่องสีละ beat, y=52) (5) **ซับไทย sync กับเสียงพากย์** ฟอนต์ Itim กล่องกึ่งโปร่งใต้หน้าต่าง gameplay (6) **เสียงพากย์ไทย TTS + ดนตรี duck อัตโนมัติ** — วิธีประกอบ bg ด้วย PIL, สูตร ffmpeg, กับดัก image input, และเกณฑ์วัดระดับเสียง อยู่ในบล็อกถัดไปทั้งหมด
- **ไม่ต้อง gen ใน Flow เลย = 0 เครดิต** ทั้งคลิปประกอบด้วย ffmpeg ล้วน — เหมาะคลิปแผ่นเกม/กุญแจเกมที่ "ตัวเกม" คือจุดขาย (ดู `game` rules ใน `hooks.md`: hook/เสียงพากย์ต้องพูดถึงแนวเกม+จุดขาย หาด้วย `web_search` 1 ครั้ง)
- **Reference จริงที่ฟิกส่ง (Shopee Video, Muramasa: Revenant Blades PS5, 21.6 วิ 590x1280):** ไม่มีพรีเซ็นเตอร์ ไม่มีสินค้าในเฟรม โครงคือ การ์ดไตเติลชื่อเกม ~2-3 วิ → ฟุตเตจเกมตัดถี่ ช็อตละ ~1.5-3 วิ (เช็คจุดตัดด้วย `select='gt(scene,0.12)'`) → ปิดท้ายด้วยไตเติลชื่อเกมอีกรอบ; **gameplay 16:9 วางกึ่งกลางแนวตั้งบนพื้นดำ (letterbox) ไม่ใช่พื้นหลังเบลอ**; เสียง = เสียงจากตัวอย่างเกมนั้นๆ (ดนตรี/sfx) ไม่มีเสียงพากย์; ปุ่ม/การ์ดสินค้า ราคา เป็น UI ของ Shopee ที่ฟิกปักเอง ไม่ได้อยู่ในพิกเซลของเรา
- **ที่มาฟุตเตจ:** YouTube → `uv tool run yt-dlp -f "bv*[height<=1080]+ba" <url>` (yt-dlp ไม่ได้ติดตั้งถาวร แต่ `uv tool run` ใช้ได้เสมอ, เวอร์ชัน 2026.10.26); Steam store video → `curl` URL `video.epicgames…`/`steamstatic` ตรงๆ; ถ้าฟิกส่งเป็นลิงก์ Shopee Video ให้ของจริงมาไม่ได้ (WAF) → ใช้ trailer ทางการของเกมนั้นแทน แล้วบอกเขา
- **สูตร ffmpeg — ทำ MASTER ก่อนแล้วค่อยตัด (สำคัญ):** trailer ใหญ่มักเป็น AV1 1080p60 ซึ่ง encode ทีละช็อตช้ามาก ให้ encode ทั้งเรื่องครั้งเดียวเป็น output format ก่อน แล้วตัดจาก master: `ffmpeg -i src.mp4 -vf "scale=720:-2,pad=720:1280:0:320:black,fps=30,format=yuv420p" -c:v libx264 -preset veryfast -crf 20 -c:a aac -b:a 128k -ar 48000 -ac 2 master.mp4` (ค่า encode ทุกช็อตที่ตัดจาก master ต้องเหมือนกันเป๊ะ) แล้วตัดช็อต: `ffmpeg -ss <in> -t <len> -i master.mp4 -vf <+drawtext ถ้ามี caption> -c:v libx264 -preset veryfast -crf 19 -c:a aac -b:a 128k -ar 48000 -ac 2 seg_N.mp4` → `ffmpeg -f concat -safe 0 -i list.txt -c copy out.mp4` (concat แบบ copy ปลอดภัยเพราะแต่ละ seg เริ่มที่ keyframe) — hard cut ถี่ ๆ ตามจังหวะ reference ไม่ต้อง xfade; อยากได้เต็มจอแทน letterbox เปลี่ยน pad เป็น `crop=720:1280` ที่ center
- **เลือกช็อตโดย "เผา timestamp ลงเฟรม" ก่อนถาม vision:** ดึง 1 เฟรมทุก ~3 วิ แล้ว `drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf:text='<n>s':x=6:y=6:fontsize=22:fontcolor=yellow:box=1:boxcolor=black@0.7` ทับแต่ละเฟรม แล้ว `tile=4x3` เป็น contact sheet → ถาม vision ครั้งเดียว; คำสั่ง "output one line per panel" ไม่ค่อยถูกฎ แต่พอเผาเวลาลงภาพ คำอ่านผูกกับเวลาได้แม่นพอให้เลือก segment (เช็คจุดตัดหยาบ ๆ ด้วย `select='gt(scene,0.25)',showinfo` คู่กัน)
- **การ์ดไตเติล: ยืมจาก trailer ห้ามวาดใหม่ถ้ามีของจริง** — card สุดท้ายของ trailer (โลโก้ + วันวางจำหน่าย) เอามาเปิดคลิป (~2 วิ) และเอากลับมาปิดท้ายอีกรอบ (~3 วิ) ได้เลย ได้ art ทางการเป๊ะ ๆ ส่วน caption อื่น ๆ ใช้ `drawtext` EN บนแถบดำ (escape `:` เป็น `\:`, escape `'` เป็น `\'`) — ห้ามขึ้นไทยบนจอ (กติกาเดิม)
- **frame check ของ preset นี้:** ข้อความในเกม (ตัวเลขนับ, จับเวลา, subtitle อย่าง "Good pup/") เป็นของเกมเอง = ไม่ใช่ defect; ที่ต้องตรวจคือ caption ที่เราใส่เอง (ต้อง EN ≤2 คำ), ไม่มีราคา/สกุลเงิน/QR/ชื่อร้านในพิกเซลเรา, ไม่มีไทยบนจอ
- **กติกาที่ไม่ขยับ:** ห้ามราคา/สกุลเงิน/ส่วนลด/คูปอง ในพิกเซลของเรา (การ์ดราคาที่ Shopee แสดงเป็นคนละชั้นกัน ไม่นับ), ไม่มีชื่อร้าน/watermark, วันที่pre-orderพูดได้, CTA นุ่มนวลเป็น caption EN (`Link below!`) เฉพาะช็อตสุดท้าย, hashtags+ลิงก์ปักตะกร้าส่งใน delivery ตามเดิม
- **ขั้นตอน:** (1) `web_search` ชื่อเกม+platform/publisher 1 ครั้ง เอาแนวเกม+จุดขาย+วันวางจำหน่าย (2) ได้ฟุตเตจ → ffprobe เช็ค (3) `ffmpeg select='gt(scene,0.12)' showinfo` หาจุดตัด เลือก 4-8 ช็อตเด่น (4) ตัด+pad+concat (5) `scripts/verify-clip.py` (620x1280/h264/aac/duration>1s; ไฟล์ต้องถูก cp เข้า `/opt/data/home/Downloads/` ก่อน เพราะ script สแกนแค่ 2 โฟลเดอร์นั้น) + frame check (ราคา? ไทยบนจอ? โลโก้ร้าน?) (7) log+deliver — **multi-scene review gate ไม่บังคับกับ preset นี้** (ไม่มี scene ไหนถูก gen ใน Flow จึงไม่มี raw scene ให้ส่ง review; ส่งครั้งเดียวพร้อม frame-check verdict ใน delivery เดียว)

- **เสียงพากย์ไทยใน preset นี้ = edge-tts (0 เครดิต, ไม่ผ่าน Flow) — Fix สั่งเวอร์ชันมี VO 2026-11-01 ("พากไทย เสียง ญ")** ที่ใช้จริง: `uv run --with edge-tts python <script.py>` (module ไม่ได้ติดตั้งถาวร ต้อง `uv run --with` — ใช้ `uv tool run edge-tts --text "..."` กับข้อความไทยยาวๆ จะพังเงียบด้วย `NoAudioReceived` เพราะ quoting ใน shell) → `edge_tts.Communicate(TEXT, "th-TH-PremwadeeNeural", rate="+0%").save(vo.mp3)` (เสียงหญิงสดใส = ธีมช่อง; ชาย = `th-TH-NiwatNeural`); บท ~55 คำ/20 วิ → ได้ ~15 วิ พอดีคลิป แล้วซ้อนใต้เสียง trailer: `[ga]volume=0.5[pre]; [8:a]aresample=48000,volume=1.25,apad=whole_dur=20.05,asplit=2[voa][vok]; [vok]pan=mono|c0=0.5*c0+0.5*c1[key]; [pre][key]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=700[gduck]; [gduck][voa]amix=inputs=2:duration=longest:normalize=0[aout]` — **ดนตรีต้อง duck ตอนพูด** (v2 ที่แค่ volume=0.30 คงที่ ฟิกฟังไม่รู้เรื่อง: "ดนตรีกับเสียงตีกัน") โดยเกณฑ์วัดด้วย `volumedetect` สองช่วง: ช่วงพากย์ mean ต้องดังกว่าช่วงดนตรีล้วน ≥ 6 dB (วัดจริง −18.7 dB ช่วงพากย์ vs −23.3 dB หัวคลิป / −27.1 dB ท้ายคลิป) และ max ไม่แตะ −3 dB (−5.5 dB = ไม่ clip)
- **กับดัก `amix duration=first`:** ถ้าให้ VO เป็น input แรกหรือใช้ `duration=first` โดยไม่ pad ฝั่ง VO เสียงจะถูกตัดเหลือเท่ากับ VO (วัดจริง: คลิป 20 วิ แต่ audio stream = 15.408 วิ ท้ายคลิปเงียบสนิท) — แก้ด้วย `apad=whole_dur=<ความยาวคลิป>` ที่ฝั่ง VO แล้วใช้ `duration=longest` เสมอ และเช็คด้วย `ffprobe -select_streams a -show_entries stream=duration` ต้องเท่ากับความยาวคลิป
- **ซับไทยบนจอ = เผาด้วย libass + ฟอนต์ไทยจริง (ฟิกสั่งเอง 2026-11-01: "อยากให้มี subtitle โชว์ให้เห็นด้วย")** — กติกา "caption จอ EN เท่านั้น" ใช้กับ Flow ที่ model เขียนสระไทยไม่ได้เท่านั้น ซับที่เราสร้างจาก font จริงไม่มีปัญหา: สร้าง `.ass` (PlayResX 720 / PlayResY 1280, Style `Sub,Loma,40,...,Outline 3,Alignment 2,MarginV 380` → ข้อความลงพอดีในแถบดำใต้หน้าต่าง gameplay ที่จบ y≈725) แล้วเผาด้วย `ass=subs.ass:fontsdir=/usr/share/fonts/opentype/tlwg` (fontconfig มี `Loma`/`Loma-Bold` ที่นั่น; DejaVu ไม่มีสระไทย ห้ามใช้)
- **Timing ซับจาก edge-tts: ต้องสั่ง `boundary="WordBoundary"`** (ค่า default ใน 7.3.1 คือ `SentenceBoundary` → บทไม่มีวรรคตอนจะได้ event เดียว 0 บรรทัด) และ **ห้ามจับคู่ phrase ด้วย string match เพราะตัวแบ่งคำไทยตัดแปลก** (เช่น "สั่งโอッチนด้วย" ออกมาเป็น `สั่ง|โอ|น|ด้วย` → flat string ไม่ตรงกับที่เราเขียน) — ให้ print token ทั้งหมดออกมาก่อน แล้วกำหนด phrase เป็น `(start_idx, end_idx, ข้อความที่จะขึ้นจอ)` นับจากลำดับ token แทน

- **แถบดำว่างๆ ให้เติมด้วย key art ของเกม (ฟิกสั่ง 2026-11-01: "พื้นดำๆ ว่างๆ เอารูปจากเว็บไซต์มาตัดแปะให้สวยขึ้น")** — วิธีที่ใช้แล้วสวย: ดึงภาพจากเว็บค่ายเกม (nintendo.com หน้า product → `grep -oE 'https://assets\.nintendo\.com/...'` จะได้ทั้งปก 2000x2000, ภาพประกอบ RGBA ใส และพื้นหลัง) → **ประกอบ background 720x1280 ด้วย PIL ใน `execute_code`** (cover-fit + `GaussianBlur(radius=24)` + `Brightness 0.92` + `Color 1.08` + `Image.blend` scrim ดำ 18% ให้ตัวหนังสือเด่น) แล้วแปะ illustration ใส (alpha) บน bg: รูปตัวละครใส่เหนือหน้าต่าง gameplay (~y140) แถบตัวละครใสใต้สุด (y = H − สูงแถบ) → บันทึกเป็น `bg.png` ไฟล์เดียว แล้ว ffmpeg ต่อเป็นเลเยอร์เดียว: `[game]overlay=0:320:shortest=1` บน `[9:v]scale=720:1280,format=yuv420p`
- **กับดัก image input ใน filter_complex: ภาพนิ่งที่ไม่ได้ `-loop 1` ทำให้ทั้งคลิปเหลือ 1 เฟรม** (ผลลัพธ์อ่าน `nb_frames=1`, `duration=0.04s` ทั้งที่ ffprobe ฝั่ง format บอก 20 วิ — และ `ffmpeg -ss 2 -i out.mp4` จะคาย `Output file is empty, nothing was encoded`) — ให้ใส่ `-loop 1` ทุก input ภาพนิ่ง และ **เช็ค `ffprobe -select_streams v -show_entries stream=nb_frames` เสมอหลัง build** (ต้อง ≈ วินาที × fps) และระวัง index ของ input: นับ 0..N-1 ตามลำดับที่สั่งจริง ไม่ใช่ตามที่จำได้ (สลับ index ของ vo/bg = `matches no streams`)
- **ฟอนต์ "น่ารัก" ตามที่ฟิกขอ (2026-11-01)** — ดาวน์โหลด Google Fonts ลง scratch แล้วชี้ `fontsdir` ไปที่โฟลเดอร์นั้น: `https://github.com/google/fonts/raw/main/ofl/itim/Itim-Regular.ttf` (ไทย กลมน่ารัก ใช้กับซับ), `.../ofl/mali/Mali-Bold.ttf`, `.../ofl/fredoka/Fredoka%5Bwdth%2Cwght%5D.ttf` (EN กลม ใช้กับ caption pill) — **ห้ามใช้ DejaVu/Liberation กับภาษาไทย** (ไม่มีสระ ขึ้นกล่องว่าง), ส่วน `Loma` (มีในเครื่องที่ `/usr/share/fonts/opentype/tlwg`) ใช้ได้แต่ดูไม่น่ารัก
- **caption pill สีพาสเทลเปลี่ยนสีตาม beat** (Fredoka 40pt, `box=1:boxcolor=0xFF8FB1@0.92 / 0xFFD166@0.92 / 0x8AC926@0.92 / 0x7A5CFF@0.92`, `boxborderw=14`, `borderw=3:bordercolor=0x5A2A4A`, `y=52`, `enable='between(t,...)'` นับจาก cumulative duration ของ segment) และ **ซับไทย = Itim 48 เหลืองพาสเทลขอบน้ำตาล ไม่มีกล่อง (`BorderStyle=1`, Outline 5, Shadow 2.5; ฟิกเลือก 2026-11-06) render ด้วย `ass=…:shaping=complex`** — ตำแหน่ง/margin ตาม `gameplay-clips/references/safe-zones.md` (MarginV 465)

## `skit` — สั้นๆ มีสถานการณ์ (ปัญหา → สินค้าแก้)
- แนบ character chip; 2 beat ใน 10 วิ: (1) 3 วิ ฉากเหนื่อย/ยุ่งกับปัญหา, (2) เอามือแตะสินค้าแล้วเปลี่ยนเป็นยิ้ม + ชี้ลง CTA.
- บทพูดไทยสั้นกว่าเดิม (ประโยคเดียว), caption EN 2 จุด.

## Rules that do NOT move between presets
- ห้ามราคา/สกุลเงิน/% ส่วนลด/คูปอง/ชื่อร้าน/watermark — เหมือนเดิมทุกแนว.
- caption จอ = อังกฤษ/คำยืม เท่านั้น, ≤2 คำต่อ beat; เสียงพากย์ไทยคงเดิม.
- CTA นุ่มนวลท้ายคลิปเท่านั้น (`Link below!` / ลิงก์อยู่ใต้คลิปในเสียง).
- cover-fidelity block ใส่ทุกแนวที่เห็นหน้ากล่อง; stray-prop line ใส่ทุกแนว.
- Style card (`templates/style-card.md`) คงเดิมทุกแนว — มันคือชั้น "คลิปดูเป็นช่องเดียวกัน" แนวที่เปลี่ยนคือ sequence + ใคร/อะไรอยู่ในเฟรมเท่านั้น.

## เลือกยังไงตอนสั่ง — เป็นปุ่มให้กด (clarify tool)
- ทั้ง "กี่วิ" และ "แนวไหน" ถูกส่งเป็น **`clarify` call เดียว มี 2 questions × choices → ฟิกกดปุ่มเลือก ไม่ต้องพิมพ์**; ตัวเลือกแรกของคำถามแนวคือ `presenter … (แนะนำ)`
- กดข้าม / ไม่ตอบ / timeout → ใช้ `presenter` (default ตามที่ฟิกสั่ง 2026-10-31) ห้ามถามซ้ำรอบสอง
- ฟิกตอบแนวใน clarify → ใช้ preset นั้นทันที ไม่ต้องถามยืนยันซ้ำ
- สั่งสั้นมาก / ระบุแนวเองในข้อความ → ใช้ที่เขียนไว้ ไม่ต้องถามข้อที่มีคำตอบแล้ว
- บันทึก `style` ลง `logs/clip-log.jsonl` (`"style": "hands"`) และ `state/<project-id>.json` → `last_clip.style` เพื่อให้รันถัดไปรู้ว่าใช้อะไรไปแล้ว
