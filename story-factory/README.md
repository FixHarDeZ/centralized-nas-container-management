# story-factory

Telegram bot ที่ทำคลิปเล่าเรื่องไทยยาว 30-40 นาที — สารคดีตำนาน/เรื่องลี้ลับ
เสียงอ่านจาก Google Cloud TTS ภาพนิ่ง 1 ภาพจาก Google Flow + waveform ขยับตามเสียง
อัป YouTube เองด้วยมือ

คำศัพท์ทั้งหมด (Story / Chapter / Outline / Source note / Backdrop / Waveform /
Competitor scan) อยู่ใน root `CONTEXT.md` หัวข้อ "Long-form vocabulary"
**ไม่ใช้คำร่วมกับ shorts-factory** — Chapter ไม่ใช่ Card, Story ไม่ใช่ Clip

## ⚠️ ยังรันไม่ได้

ยังไม่มี secret ตัวไหนอยู่ใน vault เลย `secrets.manifest.yaml` จึงมีแต่ `literals:`
และ stack นี้**ยังไม่ได้ใส่ใน `ALL_STACKS` ของ `scripts/deploy.sh`**

สิ่งที่ต้องมีก่อนรันครั้งแรก:

1. **ยิง TTS API 1 รอบ** เพื่อตอบ 4 คำถามที่ค้างอยู่ (เสียงไทยตัวไหน /
   `speaking_rate` ใช้ได้จริงไหม / pause tag กับไทย / **รอยต่อ chunk ได้ยินไหม**)
   ดู `.notes/00_INDEX.md` — รอบทดสอบใช้ API key เฉยๆ ไม่ต้องแตะ vault
2. **บอท Telegram ตัวใหม่** ห้ามใช้ token เดียวกับ shorts-factory — สองโปรเซส
   long-poll `getUpdates` token เดียวกันจะแย่งข้อความกัน
3. **service account JSON เข้า vault แบบ base64 บรรทัดเดียว** —
   `render_env.py` ปฏิเสธค่าที่มี newline ("docker-compose .env does not support
   multiline values") แล้ว `make secrets` จะพังทั้ง repo ไม่ใช่แค่ stack นี้
   ต้องเปิด Text-to-Speech API ใน GCP project ของ shorts-factory ก่อน
4. **shared folder ชื่อ `stories`** สร้างใน DSM Control Panel → Shared Folder
   (`synoshare --add` ทาง CLI ปฏิเสธ: `share_is_acl_share.c`) — ต้องเป็น shared
   folder จริงเพราะไฟล์ ~470 MB ต้องหยิบผ่าน File Station/SMB จากเครื่อง

ลำดับใส่ vault สำคัญ: **ใส่ค่าลง `secrets/vault.sops.yaml` ก่อน แล้วค่อย
uncomment บรรทัดใน `secrets.manifest.yaml`** สลับกันเมื่อไหร่ `make secrets` พังทั้ง repo

## Flow

```
/story <หัวข้อ>
  → ด่านหัวข้อศาสนา (app/topics.py, ADR 0011) — ! นำหน้าข้ามได้
  → mimo วาง Outline 7 บท
  → 🛑 คนกดอนุมัติ — จุดเดียวที่บอทหยุดรอคน (ADR 0010)
  → เขียนทีละบท บทละ ~700 คำ ส่งบทก่อนหน้าไปเป็น context
      ↳ ทุกบทผ่าน Source note validator (app/sources.py) ไม่ผ่าน = เขียนใหม่เอง ไม่ถามคน
        (รวมข้อ "ประโยคเดียวยาวเกิน 5,000 ไบต์" — ตรวจตรงนี้เพราะยังเขียนใหม่ได้
         ถ้าไปตรวจตอน TTS คือเสียทั้ง Story)
      ↳ เขียนเสร็จบันทึกลง workdir/story.json ทันที (checkpoint)
  → TTS บทที่ N วิ่งซ้อนกับการเขียนบท N+1 หั่นที่ขอบประโยค ~20 request ต่อ Story (ADR 0012)
      ↳ เสียงเสร็จบันทึกลง story.json อีกครั้ง, raw chunk ก่อน trim เก็บไว้ที่ workdir/raw/
  → ffmpeg pass เดียว: Backdrop วน + showwaves + x264
  → ส่ง .txt ตัวบทเต็มเข้า Telegram + บอก path ของ mp4 บน NAS
```

**พัง/`/cancel`/คอนเทนเนอร์ตายกลางทาง = ไม่เสียของ** — `app/story.py` เก็บทุกบทที่เขียนแล้ว
และทุกบทที่จ่ายเสียงแล้วไว้ใน `/data/work/<timestamp>/story.json`. ตอน start บอทเจอ
งานค้างจะถามว่าทำต่อไหม หรือพิมพ์ `/resume` เอง — บทที่มีแล้วไม่ถาม mimo ซ้ำ เสียงที่มีแล้ว
ไม่ยิง TTS ซ้ำ. workdir ที่เสร็จแล้วเก็บไว้ `KEEP_WORKDIRS` (3) ชุดล่าสุดสำหรับฟังรอยต่อ
(~250 MB/ชุด) ที่ค้าง/ทิ้งด้วยมือไม่ลบให้

**ไม่ส่ง mp4 เข้า Telegram** — 5 นาทีก็ 59 MB แล้ว เกินเพดาน `sendVideo` 50 MB
บอทบอก path ให้ไปหยิบเอง

## ตัวเลขที่วัดจริงบน NAS (2026-09-14)

| ค่า | ผล |
| :--- | :--- |
| render veryfast crf20 `-threads 3` | **0.61× realtime** |
| Story 40 นาที | ~25 นาที wall / ~470 MB / peak RSS ~400 MB |
| ping-pong Backdrop 6 วิ | 9.0 วิ / 730 MB ครั้งเดียวต่อ Story |
| TTS | ~20 request / Story ≈ $0.60 (ฟรี 1M chars/เดือน ≈ 50 Story) |

ตาราง preset เต็มอยู่ใน `.notes/daily_log.md`

## Gotchas

- **`cpus:` ใน compose ไม่มีผลบน DSM ทั้ง repo** — kernel ไม่มี CFS bandwidth
  control, daemon ปฏิเสธตรงๆ (`NanoCPUs can not be set`) และ `docker inspect`
  คืน `NanoCpus=0` แม้ compose จะเขียนไว้ ต้องคุมที่ `-threads` ของ ffmpeg
- **Backdrop ยาวเกิน 8 วิไม่ได้** — `reverse` อมทุกเฟรมไว้ใน RAM (~3.1 MB/เฟรม)
  10 วิ ≈ 1.2 GB เบียด `mem_limit: 2g`
- **`-tune stillimage` ใช้ไม่ได้** waveform ขยับทุกเฟรม = ทุกเฟรมเป็นเฟรมใหม่
- **ภาพนิ่งใช้ `-stream_loop -1` ไม่ได้** — อ่านได้เฟรมเดียว ออกมาเป็นคลิป 1 เฟรม
  `render._input_flags()` เลยแยกทาง: `.png/.jpg/.jpeg/.webp` ใช้ `-loop 1 -framerate 24`
  คลิปใช้ `-stream_loop -1` (ถ้าไม่แยก จะไปตายที่ ffprobe ตอนท้าย หลังจ่าย TTS ครบแล้ว)
- **`-shortest` + `-stream_loop -1` ตัดคลิปสั้นเงียบๆ ได้** `render.build()`
  เลย ffprobe เทียบความยาวกับเสียงทุกครั้ง ไม่เชื่อว่าสำเร็จเพราะ exit 0
- **Chirp 3: HD ไม่รับ SSML และตัด `custom_pronunciations` สำหรับ `th-th`** —
  แก้คำอ่านผิดได้ทางเดียวคือแทนที่ข้อความ (`say.json`) และต้องแทนที่ใน
  `tts._speakable()` **ที่เดียว**
- **pause tag ห้ามใช้คำนวณ timestamp** — non-deterministic; timestamp มาจาก
  ffprobe ของไฟล์จริงเสมอ
- **ffmpeg ทุกตัววิ่งผ่าน `render.run()` = `asyncio.create_subprocess_exec`** ไม่ใช่
  `subprocess.run`/`to_thread` — สองอย่างนั้นหยุดกลางคันไม่ได้ `/cancel` ระหว่าง render
  จะเป็นคำโกหก 25 นาที และ blocking call ทำให้ poll loop แข็ง `getUpdates` ไม่ถูกเรียก.
  Google TTS client เป็น sync เลยครอบ `to_thread` (ยกเลิกได้ที่ขอบ chunk).
  Story แต่ละเรื่องมี workdir ของตัวเอง (`/data/work/<timestamp>`)
- **Telegram sendMessage เกิน 4096 ตัวอักษร = ไม่ส่งเลย** ไม่ตัดให้ `say()` หั่นเอง
  และ keyboard ติดไปกับท่อนสุดท้ายเท่านั้น

## ADR

- `docs/adr/0010` — คนอนุมัติแค่ Outline ไม่มีใครถูกบังคับให้อ่าน prose,
  Source note บังคับใน code
- `docs/adr/0011` — เนื้อหาสารคดี + แพ็กเกจก่อนนอน, ตัดศาสนา 10 Story แรก
- `docs/adr/0012` — `synthesize` ธรรมดาหลายครั้ง ไม่ใช้ `synthesizeLongAudio`

## Test

```bash
cd story-factory && python -m pytest tests/ -q
```

ครอบเฉพาะตรรกะบริสุทธิ์ที่ ADR ล็อกไว้แล้ว: การหั่นที่ขอบประโยค, timestamp
สะสมจากความยาวที่วัดจริง, Source note validator, ด่านหัวข้อศาสนา, input flag
ของ Backdrop (ภาพนิ่ง vs คลิป), checkpoint/resume/prune ของ `story.py`, และว่า cancel
ฆ่า child process จริง — 35 ข้อ ไม่มีข้อไหนยิง API หรือเข้ารหัสวิดีโอจริง
