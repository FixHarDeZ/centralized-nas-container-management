# story-factory — index

**สถานะ: scaffold แล้ว ยังรันไม่ได้** (2026-09-14) — มี compose/Dockerfile/app/tests
ครบ เทสต์ 35 ข้อผ่าน แต่ยังไม่มี secret ตัวไหนใน vault และยังไม่เคย deploy

- `secrets.manifest.yaml` มีแต่ `literals:` — บรรทัด `env:` comment ไว้พร้อม vault path
- **ไม่ได้ใส่ใน `ALL_STACKS` ของ `scripts/deploy.sh`** (pre-upload verify ต้องการ `.env`)
- **ยังไม่จองพอร์ต 5067/15067** — service เดียว ไม่มีพอร์ต ไม่มี dashboard/nginx
  (ยังไม่มีข้อมูลอะไรให้ dashboard โชว์ ดู daily_log)

## คืออะไร

Telegram bot สร้างคลิปเล่าเรื่องไทยแบบยาว 30-40 นาที (Story) ภาพนิ่งจาก Google Flow
+ waveform ขยับตามเสียง อัป YouTube เอง. คำศัพท์ทั้งหมดอยู่ใน root `CONTEXT.md`
หัวข้อ "Long-form vocabulary" (Story / Chapter / Outline / Source note /
Backdrop / Waveform / Competitor scan) — **ไม่ใช้คำร่วมกับ shorts-factory**
Chapter ไม่ใช่ Card, Story ไม่ใช่ Clip.

## ADR ที่ผูกอยู่

- `docs/adr/0010-story-factory-approves-an-outline-not-the-prose.md`
  คนอนุมัติแค่ Outline, ไม่มีใครถูกบังคับให้อ่าน prose, Source note บังคับใน code
- `docs/adr/0011-story-factory-is-documentary-subject-with-bedtime-packaging.md`
  เนื้อหาสารคดี + แพ็กเกจแบบก่อนนอน, ตัดศาสนาออก 10 Story แรกด้วย topic gate
- `docs/adr/0012-story-factory-voices-a-story-in-many-small-calls.md`
  ใช้ `synthesize` ธรรมดา ~20 ครั้ง/Story หั่นที่ขอบประโยค **ไม่ใช้** `synthesizeLongAudio`
  (GCS-only + v1beta1 + ไม่ระบุว่ารองรับ Chirp 3) — reversal condition = รอยต่อได้ยินจริง

ADR เรื่อง waveform overlay **ไม่ต้องเขียน** — วัดแล้วไม่มี trade-off จริง (ดู daily_log 2026-09-14)

## ตัวเลขที่วัดแล้ว (2026-09-14)

render pass เดียว preset veryfast crf 20 `-threads 3` → **0.61× realtime**
Story 40 นาที ≈ **25 นาที wall / ~470 MB / peak RSS ~400 MB**
ping-pong ของ Backdrop ≈ 9 วิ / 730 MB ครั้งเดียว — **คลิป Flow ห้ามเกิน 6-8 วิ**
รายละเอียดและตารางเทียบ preset อยู่ใน `daily_log.md`

## ข้อบังคับที่ตามมาจากตัวเลข

- **ห้ามส่ง mp4 เข้า Telegram** — 5 นาทีก็ 59 MB เกินเพดาน `sendVideo` 50 MB แล้ว
  บอทบอก path บน NAS (`/volume1/stories`) ให้คนไปหยิบเอง
- `mem_limit: 2g` พอ แต่ **`cpus:` ใน compose ไม่มีผลบน DSM ทั้ง repo** (`NanoCpus=0`)
  ใช้ `-threads` ที่คำสั่ง ffmpeg แทน

## ค้างอยู่ (blocking)

**ข้อเท็จจริง TTS ครบแล้ว** (ดู daily_log 2026-09-14 + ADR 0012) — ที่เหลือคือ
**ยิง API ครั้งเดียว ตอบ 4 คำถามพร้อมกัน ไม่ใช่อ่านเอกสารต่อ**:

1. **เสียงไทยตัวไหนฟังดีจริง** — ไม่มีรีวิวที่เชื่อได้ ต้องยิงเองแล้วฟัง
   (th-TH Chirp3-HD: Achernar/Kore/Leda/Zephyr/Sulafat หญิง, Charon/Orus/Puck/Algenib/Rasalgethi ชาย)
   บรีฟ = **อุ่น นิ่ง เล่าช้า แบบสารคดี** ไม่ใช่ "นุ่มง่วง"
2. **`speaking_rate` ใช้กับ Chirp 3: HD ได้จริงไหม** — เอกสาร Google 2 หน้าขัดกันเอง
3. **pause tag (`markup`) ทำงานกับไทยดีแค่ไหน**
4. **รอยต่อ chunk ได้ยินไหม** — ย่อหน้าเดียวยิงครั้งเดียว vs หั่น 3 ครั้ง แล้วฟังตรงรอย
   นี่คือข้อเดียวที่พลิก ADR 0012 ได้ อีก 3 ข้อไม่กระทบสถาปัตยกรรม
   **ต้องเล็มความเงียบแบบ production (`JOIN_SILENCE` 0.30 วิ) ก่อนฟัง** ไม่งั้นจะได้ยิน
   padding ที่ Google แถมมา แล้วไปโทษว่าเป็น prosody reset — คนละอาการ เล็มแก้ได้อันเดียว
   สิ่งที่ต้องฟังคือ **ระดับเสียง/โทนกระโดด** ตรงรอย ไม่ใช่ช่องว่าง
   วัดด้วยว่า Google แถมความเงียบหัว/ท้ายต่อ call เท่าไร

ลำดับที่คนต้องทำก่อน: เปิด Text-to-Speech API ใน GCP project ของ shorts-factory →
รอบทดสอบทิ้งใช้ **API key เฉยๆ พอ** (ไม่ต้อง service account ไม่ต้องแตะ vault,
วางไว้ในไฟล์ที่ gitignored) → **เลือกเสียงได้แล้วค่อย** ใส่ service-account JSON
ลง `secrets/vault.sops.yaml` **ก่อน** แล้วค่อยเพิ่มคีย์ใน `secrets.manifest.yaml`
(สลับลำดับ = `missing vault path` แล้ว `make secrets` พังทั้ง repo)

**Waveform ลากจากเสียงไหน** (narration อย่างเดียว vs mix สุดท้าย) — ไม่ blocking
เพราะ showwaves ฟรี เลือกทีหลังด้วยหูได้

## ต้องมีก่อน deploy ครั้งแรก

1. บอท Telegram **ตัวใหม่** (token เดียวกับ shorts-factory ไม่ได้ — แย่ง getUpdates กัน)
2. service-account JSON **base64 บรรทัดเดียว** เข้า vault (`render_env.py` ไม่ยอม newline)
3. shared folder `stories` สร้างใน **DSM Control Panel → Shared Folder**
   (`synoshare --add` ปฏิเสธ: `share_is_acl_share.c`) — ต้องเป็น shared folder จริง
   ไฟล์ 470 MB หยิบผ่าน File Station/SMB ซึ่งเห็นเฉพาะ shared folder
4. ใส่ `story-factory` ใน `ALL_STACKS` ของ `scripts/deploy.sh`
5. อัปเดตตาราง stack ใน root `CLAUDE.md` + root `README.md` ใน commit เดียวกับโค้ด
   (รวมข้อที่ว่า `cpus:` เป็น no-op ทั้ง repo)

## กับดักที่แก้ไปแล้วตอน review scaffold (2026-09-14)

- **`main.py` อ่าน env ตอน import ไม่ได้** — `os.environ["TELEGRAM_BOT_TOKEN"]`
  ระดับโมดูลแปลว่า import ไม่ได้เลยถ้าไม่มี token (เทสต์แตะไม่ได้ + คอนเทนเนอร์
  ตายด้วย KeyError เป็นอย่างแรก) → เปลี่ยนเป็นฟังก์ชัน `api()` / `chat_id()`
- **stamp `mode` ก่อน `create_task` เสมอ** — เดิม stamp ข้างในงาน สองข้อความ/สองแตะ
  ที่มาก่อนงานแรกถูก schedule จะผ่านด่าน idle ทั้งคู่ แล้วสอง Story ใช้ workdir
  เดียวกัน (บทเรียนเดียวกับ `trends_running` ของ shorts-factory) — ตามด้วย
  `make_outline` ต้องคืน mode เป็น idle ในทุกทางออก ไม่งั้นบอทค้างถาวร
- **ภาพนิ่งเป็น Backdrop เคยพังแน่นอน** — `-stream_loop -1` กับ `.png` ได้เฟรมเดียว
  ffprobe ตอนท้ายถึงจับได้ = เสียทั้ง Story หลังจ่าย TTS ครบแล้ว
  → `render._input_flags()` แยก `-loop 1 -framerate 24`
- **run ที่ยาวเกิน 5,000 ไบต์โดยไม่มีขอบประโยค** ย้ายไปตรวจใน `sources.check(..., limit)`
  ซึ่งอยู่ในลูปเขียนใหม่ ไม่ใช่ปล่อยให้ `tts.voice_chapter` โยนทิ้งทั้ง Story
  (`voice_chapter` ยังโยนอยู่ในฐานะ backstop)
- **`/cancel` ระหว่าง render เป็นคำโกหก** — `asyncio.to_thread(render.build)` ยกเลิกไม่ได้
  ffmpeg วิ่งต่อจนครบ ~25 นาที แต่บอทกลับเป็น idle → คนสั่ง Story ใหม่ได้ทันที
  แล้วสองงานเขียน `narration.wav` ทับกัน + x264 สองตัวใน `mem_limit: 2g`
  (เครื่องเคย OOM ทั้งตัว 19/08) → ตอน `mode == "working"` ปฏิเสธตรงๆ ว่ายกเลิกไม่ได้
- **pop `pending` ที่ `handle()` ไม่ใช่ใน task** — แตะปุ่ม ✅ ครั้งที่สองเจอ `pending`
  ว่างแล้วเงียบไปเอง ไม่ต้องมีสาขา `if not pending` ที่เผลอ set mode เป็น idle
  ทับงานที่กำลังวิ่งอยู่ — `make_story(client, state, pending)` รับมาเป็น argument
- **workdir ต่อ Story** `/data/work/<timestamp>` ไม่ใช้ `work/` ร่วมกัน — path ตายตัว
  แปลว่าอนาคตถ้ามีสองงานซ้อนเมื่อไหร่ ไฟล์ทับกันเงียบๆ

## review รอบสาม (2026-09-14) — redesign ตามที่เสนอ

- **`render.run()`** = asyncio subprocess ทุก ffmpeg → `/cancel` ฆ่า ffmpeg ได้จริง
  (เทสต์ `test_cancelling_the_task_kills_the_child_process`) และ poll loop ไม่แข็ง
  เดิม `tts.voice_chapter` + `render.ping_pong` เป็น sync ใน coroutine = บอทหูหนวกตลอด TTS
- **`app/story.py` checkpoint** — `Job` ใน `/data/work/<ts>/story.json` บันทึกทุกบทตอนเขียนเสร็จ
  และตอนเสียงเสร็จ, `voiced()` เชื่อไฟล์ไม่เชื่อตัวเลข, `unfinished()` เสนอ resume ตอน start,
  `/resume` + ปุ่ม ▶/🗑, `prune()` เก็บ `KEEP_WORKDIRS` ชุดที่เสร็จ ไม่แตะที่ค้าง/abandoned
- raw chunk ก่อน trim อยู่ `workdir/raw/NN/` ไม่ลบ — หลักฐานเดียวสำหรับ reversal ของ ADR 0012
- TTS บท N ซ้อนกับเขียนบท N+1 (`asyncio.create_task(_voice)`), `finally` cancel voice ที่ค้าง
  ไม่งั้น task เก่าเขียนทับ workdir ที่ `/resume` เพิ่งเปิด
- `stories_published` → `stories_rendered` (นับตอน render เสร็จ ไม่ใช่ตอนอัป)
- งานเดียวถือใน `main._current` — `busy()` แทนการอ่าน mode อย่างเดียว
