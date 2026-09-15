# story-factory — daily log

## 2026-09-14 — วัด render จริงบน NAS ก่อนเขียน ADR

วัดในคอนเทนเนอร์ throwaway (image `shorts-factory-shorts-factory`, ffmpeg 7.1.5,
`--memory=2g --cpuset-cpus=0-2`) ไม่ได้รันในบอทตัวเป็น ๆ เพื่อไม่ให้ ffmpeg
ชน `mem_limit` ของ shorts-factory แล้วลาก OOM.

**⚠️ `--cpus` ใช้ไม่ได้บน DSM** — `docker run --cpus=3` ตอบ
`NanoCPUs can not be set, as your kernel does not support CPU CFS scheduler`
และ `docker inspect shorts-factory` คืน `NanoCpus=0` ทั้งที่ compose เขียน
`cpus: 3.0` ไว้ = บรรทัดนั้นไม่มีผลจริงมาตลอด. ต้องใช้ `--cpuset-cpus` ถึงจะจำกัดได้จริง.

อินพุตสังเคราะห์: เสียง 60 วิ (sine+tremolo), backdrop 6 วิ (gradients drift ช้า ๆ
ให้ใกล้คลิป Flow ที่นิ่ง ๆ) ต่อ ping-pong เป็น 12 วิ, เอาต์พุต 1920x1080 24fps.

### เส้นทาง ก (pass เดียว) ชนะเส้นทาง ง (วาด strip แยกแล้ว overlay)

| เส้นทาง | wall (เสียง 60 วิ) | peak RSS |
| :--- | :--- | :--- |
| ง: `showwaves` 800x200 → `.mov` qtrle แล้ว overlay | 1.0 + 47.7 = **48.7 วิ** | **1,124 MB** |
| ก: `showwaves` + overlay ใน `-filter_complex` เดียว | **46.5 วิ** | **416 MB** |

เหตุผลที่ทิ้งเส้นทาง ง ไม่ใช่ตัวเลข RSS แต่คือ **`showwaves` ฟรีอยู่แล้ว**:
วาด strip 800x200 ของเสียงทั้ง 60 วิ ใช้ **1.0 วิ / 61 MB** เทียบกับ encode ที่กิน 46 วิ
= ต้นทุนทั้งหมดอยู่ที่ x264 1080p ซึ่งทั้งสองเส้นทางต้องจ่ายเท่ากัน **จึงไม่มีอะไรให้ประหยัดจากการแยก pass**
ส่วน 1,124 MB เป็นผลจากเลือก qtrle (lossless RGBA 800x200x4x1440 เฟรม ≈ 920 MB ตรงกับที่วัดได้)
เปลี่ยนเป็น png/webm alpha ก็ลดได้ — **อย่าใช้ตัวเลข RSS เป็นเหตุผลหลัก** เพราะแก้ได้
แต่ข้อสรุปไม่เปลี่ยน: แยก pass แล้ว**ช้ากว่า**ด้วยซ้ำ. → **ไม่ต้องมี ADR เรื่อง overlay** ทำ pass เดียวจบ.

### preset คือตัวแปรเดียวที่มีผล (pass เดียว, crf 20)

| preset | wall | peak RSS | ขนาด/นาที | คาด 40 นาที |
| :--- | :--- | :--- | :--- | :--- |
| ultrafast | 17.9 วิ | 249 MB | 22.7 MB | ~12 นาที / ~900 MB |
| ultrafast crf 24 | 16.5 วิ | 244 MB | 14.2 MB | ~11 นาที / ~570 MB |
| superfast | 29.9 วิ | 369 MB | 30.7 MB | ~20 นาที / ~1.2 GB |
| veryfast | 46.6 วิ | 409 MB | 11.9 MB | **~31 นาที / ~480 MB** |
| veryfast + `-tune stillimage` | 48.1 วิ | 411 MB | 13.3 MB | ~32 นาที / ~530 MB |

`-tune stillimage` **ไม่ช่วย** (ช้าลงนิด ไฟล์ใหญ่ขึ้น) เพราะเฟรมไม่นิ่งจริง —
waveform ขยับทุกเฟรม. เลือก **veryfast crf 20** เป็นค่าตั้งต้น (ไฟล์เล็กสุด ห่างจาก
ultrafast 19 นาที แต่ไม่มีใครนั่งรอ งานเป็น on-demand background อยู่แล้ว) และเปิด
`RENDER_PRESET` ไว้ให้สลับเป็น ultrafast ตอนเครื่องแน่น.

### เชิงเส้นหรือไม่ — วัดที่ 300 วิ

`-threads 3` (ไม่ใช้ cpuset) preset veryfast crf 20, เสียง 300 วิ →
**wall 184.2 วิ / peak RSS 380 MB / 59.1 MB** (ffprobe ยืนยัน duration = 300.000000)
เทียบกับ 60 วิ ที่ 46.6 วิ → ถ้าเป็นเส้นตรงต้องได้ 233 วิ แต่ได้ 184 = **ดีกว่าเส้นตรงเล็กน้อย**
(0.61× realtime ตอนยาว เทียบ 0.78× ตอนสั้น — ต้นทุนคงที่ตอนเปิดเครื่องเจือจางลง)
→ คาด Story 40 นาที = **~25 นาที wall / ~470 MB** ตัวเลขในตารางข้างบนจึงเป็นการประมาณแบบเผื่อไว้แล้ว.
`-threads 3` ทำงานได้ผลโดยไม่ต้อง pin cpuset → **ใช้ `-threads` ที่คำสั่ง ffmpeg ดีกว่า `cpuset_cpus`**
(เล็งเฉพาะโปรเซสที่กินจริง ไม่ไปฝืน scheduler). อ่านตารางข้างบนเป็น **พื้น 3 คอร์** — ปล่อยอิสระจะเร็วกว่านี้.

ping-pong (split→reverse→concat 6 วิ → 12 วิ) = 9.0 วิ / 730 MB **ครั้งเดียวต่อ Story**
ไม่ได้แปรตามความยาว Story. RSS ก้อนนี้สูงสุดในไปป์ไลน์ เพราะ `reverse` บัฟเฟอร์ทั้งคลิปใน RAM
→ **จำกัดความยาวคลิปจาก Flow ไว้ที่ 6 วิ (ตัวเลขที่วัดจริง)** ไม่เกิน 8 วิ.
10 วิ ≈ 240 เฟรม × 3.1 MB ≈ 1.2 GB ก่อนค่าโสหุ้ย = จ่อชน `mem_limit: 2g` แล้ว **ไม่ปลอดภัย**
(คลิป Flow ยาวประมาณ 8 วิ โดยธรรมชาติอยู่แล้ว จึงไม่บีบอะไร).
ถ้าวันหนึ่งอยากได้ยาวกว่านั้น ทางออกคือ `reverse` ลงไฟล์ชั่วคราวก่อน (สตรีม RSS ต่ำ)
แล้วค่อยต่อด้วย `concat` demuxer — เพดานหายไปเลย.

### ผลพลอยได้ที่เป็นข้อบังคับทางสถาปัตยกรรม

- Story 40 นาทีได้ไฟล์ **~470 MB** → **เกินเพดาน `sendVideo` 50 MB ของ Telegram สิบเท่า**
  (ยืนยันด้วยของจริงไม่ใช่การคูณ: เสียงแค่ **5 นาที** ก็ได้ไฟล์ 59.1 MB เกินเพดานแล้ว)
  ส่งคลิปเข้าแชทไม่ได้เด็ดขาด. บอทต้องบอก path บน NAS แล้วให้คนไปหยิบเอง
  (ต่างจาก shorts-factory ที่ส่ง mp4 เข้า Telegram ได้)
- `mem_limit: 2g` พอสำหรับ pass เดียว (พีค 730 MB ที่ ping-pong, 416 MB ตอน encode)
  แต่จะ **ไม่พอ** ถ้าเลือกเส้นทาง ง — อีกเหตุผลที่ทิ้งมันไป
- `cpus:` ใน compose **ไม่มีผลทั้ง repo** ไม่ใช่แค่ stack นี้ — ต้องบันทึกลง root CLAUDE.md
  ตอน `/release` ไม่งั้นคนถัดไปก๊อป `cpus: 3.0` จาก shorts-factory มาใส่ story-factory แล้วเข้าใจผิดว่ากันไว้แล้ว

สคริปต์ที่ใช้วัดอยู่บน NAS ที่ `/volume2/docker/tmp/storybench/` (ลบทิ้งได้)

## 2026-09-14 (รอบสอง) — ข้อเท็จจริง TTS (หาเองหลัง research agent ตายเพราะ rate limit)

ทุกตัวเลขอ่านจากเอกสาร Google เมื่อ 2026-09-14 — **ราคาเป็นตัวที่เน่าเร็วที่สุด** เช็คใหม่ก่อนใช้จริง.

### ตัวตัดสินทางสถาปัตยกรรม: เพดาน 5,000 bytes ต่อ request

`synthesize` มีเพดานเดียวใช้กับทุก tier: **"Total bytes per request: 5,000"**
และ **ขอเพิ่มไม่ได้** ("content limits cannot be increased" ต่างจากโควตาจำนวน request).
ไทยเป็น UTF-8 3 bytes/ตัวอักษร → **1 request ได้ ~1,600 ตัวอักษรไทย** ≈ 400 คำ.
Chapter หนึ่ง ~700 คำ ≈ 2,800 ตัวอักษร ≈ **8,400 bytes = เกินเพดานแน่นอน**
→ **1 Chapter ต้องหั่นเป็น 2-3 request เสมอ ไม่ใช่ข้อยกเว้น**

ทางเลือกอีกทาง `synthesizeLongAudio` **ไม่เอา** เพราะ:
- เขียนลง **GCS bucket อย่างเดียว** (`output_gcs_uri` = `gs://bucket/file.wav`) ไม่มีทางรับ audio กลับมาเป็น bytes
  → ต้องสร้าง bucket + ให้ service account มี Storage Object Creator/Viewer + ดาวน์โหลดกลับ = พึ่งพาเพิ่มทั้งเส้น
- ยัง **`v1beta1` + ป้าย Pre-GA**
- เป็น long-running operation ต้อง poll
- **เอกสารไม่ยืนยันว่ารองรับ Chirp 3: HD** (ตัวอย่างทั้งหน้าใช้ `en-US-Standard-A`)
- อินพุตได้ ~1MB ตัวอักษร แต่เอกสารเขียนกำกวมเอง ("exact limit may vary")

→ **เลือกเส้น `synthesize` ธรรมดา + หั่นก้อน** ไม่แตะ GCS เลย. รอยต่อเพิ่มจาก ~6 (ต่อ Chapter)
เป็น ~20 (ต่อก้อนเสียง) แต่เป็นรอยต่อ**ที่ขอบประโยค** และเรามีบทเรียน `tighten()` / `JOIN_SILENCE`
0.30 วิ จาก shorts-factory ใช้ซ้ำได้ทันที. **หั่นที่ขอบประโยค ห้ามหั่นที่ 5,000 bytes ดิบ ๆ**

### เสียงไทย

Chirp 3: HD รองรับ `th-TH` ยืนยันในตารางภาษา. ชื่อเสียง = `th-TH-Chirp3-HD-<ชื่อ>`
จากชุดกลาง 30 ชื่อเดียวกันทุก locale (Achernar/Kore/Leda/Zephyr/Sulafat ... ฝั่งหญิง,
Charon/Orus/Puck/Algenib/Rasalgethi ... ฝั่งชาย). ชุดเทียบเสียงกับคนเลือกจากลิสต์นี้.

**ที่ทำได้กับ Chirp 3: HD ภาษาไทย**
- **`speaking_rate` ใช้ได้** ช่วง 0.25-2.0 และเอกสารเขียนชัด "Pace control available across all locales"
  → บรีฟ "เล่าช้า แบบสารคดี" ทำได้จริงด้วยพารามิเตอร์ ไม่ต้องพึ่ง SSML
  **⚠️ หน้า `list-voices-and-types` เขียนขัดกันเองว่า Chirp 3 ไม่รองรับ speaking rate/pitch**
  หน้า `chirp3-hd` เขียนว่ารองรับ pace — **ต้องทดลองยิงจริงก่อนเชื่อหน้าใดหน้าหนึ่ง**
- **pause tag ใช้ได้กับไทย**: `[pause short]` `[pause long]` `[pause]` ใส่ใน field **`markup`** ไม่ใช่ `text`
  ไทยไม่อยู่ในลิสต์ภาษาที่ถูกตัด pause ออก. แต่เอกสารเตือนเองว่าความยาวไม่แน่นอนและโมเดล
  "might occasionally disregard pause tags" → **ห้ามเอา pause tag ไปคำนวณ timestamp ของ Chapter**
  ต้องวัดจากไฟล์เสียงจริงเหมือนที่ตกลงไว้

**ที่ทำไม่ได้**
- **ไม่มี SSML** เลยสำหรับ Chirp 3: HD (และ Studio multispeaker) — Standard/WaveNet/Neural2 มี
- **`custom_pronunciations` ใช้กับ `th-th` ไม่ได้** (ไทยอยู่ในลิสต์ยกเว้นร่วมกับ bn-IN, gu-IN, vi-VN)
  → **แก้คำอ่านผิดได้ทางเดียวคือแทนที่ข้อความ** = พอร์ต `/say` จาก shorts-factory มาตรง ๆ
  (แทนใน `_tts_text()` เท่านั้น ห้ามแทนตอน join) นี่ไม่ใช่ทางเลือก แต่เป็นทางเดียวที่มี

### ราคา — ไม่ใช่ข้อจำกัด

นับ**ตัวอักษร** ไม่ใช่ bytes (รวมช่องว่าง ขึ้นบรรทัดใหม่ และแท็ก SSML ทุกตัวยกเว้น `<mark>`).
Story หนึ่ง ~4,900 คำไทย ≈ **20,000 ตัวอักษร**

| tier | ฟรี/เดือน | หลังฟรี | ต่อ Story | Story/เดือนในโควตาฟรี |
| :--- | :--- | :--- | :--- | :--- |
| Chirp 3: HD | 1M ตัวอักษร | $30/1M | **$0.60** | **~50** |
| WaveNet | 1M (บางหน้าเขียน 4M) | ~$16/1M | $0.32 | ~50 |
| Standard | 4M | ~$4/1M | $0.08 | ~200 |

โควตาฟรีคลุมทุกคลิปที่ตั้งใจทำอยู่แล้ว → **เลือกเสียงด้วยหู ไม่ต้องเลือกด้วยราคา**
โควตา request: Chirp3 = 200/นาที เราใช้ ~20/Story = ไม่มีทางชน.

### สิทธิ์ใช้งาน

ใช้เชิงพาณิชย์และ monetize บน YouTube ได้ทุก tier รวม free tier (free tier เป็นโปรโมชันด้าน
billing ไม่ใช่ license คนละใบ) ต้องเปิด billing account. YouTube ไม่มีกฎห้าม TTS —
ข้อบังคับเรื่องเปิดเผยว่าเป็น AI เล็งไปที่คลิปที่ทำให้เข้าใจผิดว่าเป็นคนจริง ไม่ใช่ narration ของช่องไร้หน้า.
(อ่านจากสรุปบุคคลที่สาม — ถ้าจะขายไฟล์เสียงต่อค่อยไปอ่าน Cloud ToS เอง)

### auth

service account JSON. เก็บทั้งก้อนใน `secrets/vault.sops.yaml` ได้ (sops รับ multiline)
แล้วให้คอนเทนเนอร์เขียนลงไฟล์ตอน start ชี้ `GOOGLE_APPLICATION_CREDENTIALS`.
ใช้ GCP project เดิมของ shorts-factory ตามที่ตกลง — **ต้องเปิด Text-to-Speech API ในโปรเจกต์นั้นก่อน**

### ที่ยังไม่รู้

- **เสียงไทยตัวไหนฟังดีจริง** — ไม่มีรีวิวที่เชื่อได้ ต้องยิงเองแล้วฟัง
- `speaking_rate` กับ Chirp 3: HD ใช้ได้จริงไหม (เอกสารขัดกันเอง)
- pause tag ทำงานกับไทยดีแค่ไหน
ทั้งสามข้อตอบได้ด้วยการยิงจริงครั้งเดียว ไม่ต้องค้นเอกสารต่อ → **ขั้นถัดไปคือยิง API ไม่ใช่อ่านต่อ**

### แก้ความเข้าใจเรื่อง reuse `tighten()` จาก shorts-factory (2026-09-14)

เขียนไว้ก่อนหน้าว่า "ใช้ซ้ำได้ทันที" — **ถูกครึ่งเดียว**. `tighten()` ของ shorts-factory
มี 2 ส่วน และมีแค่ส่วนเดียวที่ย้ายมาได้:

- **ย้ายมาได้**: เล็มความเงียบหัว/ท้ายไฟล์ (`JOIN_SILENCE` 0.30 วิ) — ที่นี่ใช้เล็ม
  padding ที่ Google แถมมาต่อ call (ยังไม่รู้ว่ากี่วิ ต้องวัดตอนยิง API)
- **ย้ายมาไม่ได้**: กลไก align กับ `SentenceBoundary`. มันมีอยู่เพราะ edge-tts คืน
  **ก้อนเดียว** พร้อม offset ที่ยาวเกินจริง เลยต้องวัด start ใหม่จากไฟล์.
  Google `synthesize` คืน **N ไฟล์แยก** — ไม่มี offset ให้ไม่เชื่อตั้งแต่แรก
  timestamp ของ Chapter = ผลรวมสะสมของ duration ไฟล์ที่เล็มแล้ว วัดตรงๆ

และปัญหา "ความเงียบ ~1.0 วิ ทุกรอยต่อ card" **ไม่เกิดที่นี่เลย** — มันเป็น artifact
ของการใส่ `\n` คั่นในคำขอเดียว ไม่ใช่ธรรมชาติของ TTS

### แก้ CONTEXT.md 2 คำที่ผลวัดหักล้าง (2026-09-14)

- **Chapter** เคยเขียนว่า "voiced by its own speech call" — ผิด. 700 คำไทย ≈ 8,400 bytes
  ชน cap 5,000 เสมอ → Chapter = หน่วยของ model call กับ timestamp เท่านั้น
  ขอบของ speech call เล็กกว่า Chapter และ **ไม่มีความหมาย** ไม่โผล่ให้ใครเห็น
- **Waveform** เคยเขียนว่า "rendered on its own and laid over the still เพราะ
  composite ทุกเฟรมแพงกว่า" — ผิด วัดแล้วกลับกัน (ไม่ประหยัดเวลา + RAM 2.7 เท่า)
  แก้เป็นวาดใน render pass เดียวกัน

## 2026-09-14 (ต่อ) — scaffold stack

ไม่มี skill `add-stack` (เช็คแล้วทั้ง `~/.claude/skills` และ `~/.agents/skills`)
— เขียนตามแพตเทิร์น shorts-factory ด้วยมือ

**compose: service เดียว ไม่มีพอร์ต ไม่มี dashboard/nginx** — shorts-factory ค่อยๆ
งอก dashboard ผ่าน ADR 0002→0007→0009 เพราะมี manifest/experiment/retention ให้โชว์
stack นี้ยังไม่มีข้อมูลอะไรเลย ก๊อปมาตอนนี้ = ต้องมี `.htpasswd` จาก vault +
`WRITING_ROUTES` test ไว้เฝ้าข้อมูลที่ยังไม่มี. **พอร์ต 5067/15067 ยังไม่จอง**

**`secrets.manifest.yaml` มีแต่ `literals:`** — `render_env.py` โยน
`missing vault path` แล้ว `make secrets` พังทั้ง repo ถ้า manifest อ้าง path ที่ยังไม่มี
บรรทัด `env:` เลยเขียนไว้แบบ comment พร้อม vault path ที่ตัดสินแล้ว
ยืนยันจากโค้ด: `manifest.get("env") or {}` → ไม่มี `env:` ไม่ error

**เจอของจริง: service-account JSON ใส่ vault ดิบๆ ไม่ได้** — `compose_quote()`
ใน `render_env.py` โยน RenderError ทันทีที่ค่ามี `\n`
("docker-compose .env does not support multiline values — base64-encode or split")
sops เก็บ multiline ได้ก็จริงแต่ renderer ไม่ยอมออก → **ต้อง base64 บรรทัดเดียว**
แก้ ADR 0012 ย่อหน้า auth แล้ว (เดิมเขียนว่า "sops handles the multiline value" = ผิด)

**`/volume1/stories` ยังไม่มี และสร้างทาง CLI ไม่ได้**
`synoshare --add stories ... /volume1` → `Error: share create failed.[0x0D00
share_is_acl_share.c:49]` (sudo ต้องใส่รหัส — NOPASSWD มีแค่ `/usr/local/bin/docker`)
**ไม่ mkdir ทิ้งไว้** เพราะ DSM UI จะสร้าง shared folder ชื่อซ้ำไม่ได้ทีหลัง
→ คนต้องสร้างเองใน Control Panel → Shared Folder ครั้งเดียว
(ต้องเป็น shared folder จริง ไม่ใช่ dir เปล่า เพราะไฟล์ 470 MB ต้องหยิบผ่าน
File Station/SMB และทั้งสองเห็นเฉพาะ shared folder). volume1 เหลือ 5.5T

**ไม่แตะ `ALL_STACKS` ใน `scripts/deploy.sh`** — pre-upload verify บังคับว่าทุก stack
ใน list ต้องมี `.env` stack นี้ยังไม่มี ใส่ตอนนี้ = deploy พังทั้งเครื่อง

### โค้ดที่เขียน

pure logic ที่ ADR ล็อกไว้แล้ว + เทสต์ **25 ข้อ ผ่านหมด**:

- `app/chunking.py` หั่นที่ขอบประโยค pack แบบ greedy (call น้อย = prosody reset น้อย)
  ตัวคั่นหลักของไทยคือ **ช่องว่าง** ไม่ใช่จุด. run ที่ยาวเกิน cap แล้วไม่มีที่ตัด
  → ติดธง `forced` แล้ว `voice_chapter()` โยน error **ไม่ยอมตัดเงียบๆ กลางคำไทย**
- `app/timeline.py` timestamp = ผลรวมสะสมของ duration ที่ ffprobe วัดจากไฟล์จริง
- `app/sources.py` กติกาที่เครื่องตรวจได้จริงไม่ใช่ "จริงหรือเปล่า" แต่คือ
  "พูดเหมือนเป็นเรื่องที่ยืนยันแล้วหรือเปล่า" → passage ไม่มี source ต้องมีคำว่า
  เล่ากันว่า/ว่ากันว่า/... **และห้ามมีตัวเลข/ปี เลย** (เคสที่วัดจริงใน shorts-factory
  คือแต่งตัวเลข — hedge ไม่ได้ทำให้ปีที่แต่งขึ้นไม่อันตราย). คืน problem ทุกข้อ
  ไม่ใช่ข้อแรก เพราะ prompt เขียนใหม่ได้ผลกว่าเมื่อบอกครบ
- `app/topics.py` ด่านศาสนา **raise ไม่ return bool** — bool ที่ลืมเช็ค = คลิปขึ้นช่อง
- `app/render.py` `build_command()` แยกจาก `build()` เพื่อให้เทสต์อ่านคำสั่งได้
  โดยไม่ต้องเผา CPU 25 นาที; `build()` ffprobe เทียบความยาวทุกครั้ง
- `app/tts.py` `_trim()` = ครึ่งที่ย้ายมาได้ของ `tighten()`; `_speakable()` เป็น
  **ที่เดียว** ที่ substitute
- `app/script.py` deadline แชร์ข้ามทุก retry, `asyncio.wait_for` ครอบทุก LLM call
  (httpx timeout เป็น per-read), ไม่ใช้ `max_tokens`
- `app/main.py` poll loop, ตัวกันเดียวคือ chat id, `/` ที่ไม่รู้จักไม่ตกเป็นหัวข้อ
- `conftest.py` เปล่าๆ ที่ราก stack เพื่อให้ `from app import ...` ทำงานตอนรัน
  pytest จาก repo root (shorts-factory ไม่มี ต้องรันจากในโฟลเดอร์ถึงจะผ่าน)

## 2026-09-14 (ต่อ) — review scaffold รอบแรก

ยังไม่ commit อะไร. ไล่โค้ดที่เพิ่ง scaffold แล้วเจอ 4 จุดที่พังแน่ถ้าปล่อยไป
รายละเอียดอยู่ใน `00_INDEX.md` หัวข้อ "กับดักที่แก้ไปแล้ว" — สรุป: env ระดับโมดูล
ใน `main.py`, stamp `mode` หลัง spawn, `-stream_loop -1` กับภาพนิ่ง,
และ run ยาวเกินแคปที่ไปตายนอกลูปเขียนใหม่.

เพิ่ม `tests/test_render.py` (2 ข้อ อ่าน `build_command()` เฉยๆ ไม่เข้ารหัสจริง)
+ 2 ข้อใน `test_sources.py` และลบบรรทัด `assert not hasattr(topics.check,
"returns_bool")` ทิ้ง — assertion นั้นเป็นจริงกับฟังก์ชันทุกตัวในโลก ไม่ได้ตรวจอะไร
ของจริงคือ `pytest.raises` บรรทัดถัดไป. รวม **29 ข้อผ่าน**

ยืนยันด้วยว่า `import app.main` สำเร็จโดยไม่มี env สักตัว

## 2026-09-14 (ต่อ 2) — review scaffold รอบสอง

advisor จับอีก 2 ข้อ ที่เทสต์รอบแรกไปไม่ถึง — ทั้งคู่เป็นผลข้างเคียงของการ stamp
`mode` ที่เพิ่งเพิ่มเข้าไปรอบแรกเอง:

1. **`/cancel` ตอน `mode == "working"`** เดิมตอบ "ยกเลิกแล้ว" แล้ว set idle แต่
   `asyncio.to_thread(render.build, ...)` ยกเลิกไม่ได้ ffmpeg วิ่งต่อจนครบ ~25 นาที
   บอทว่างแล้ว → `/story` → ✅ → `make_story` ตัวที่สอง เขียน `00.wav`…`narration.wav`
   ทับตัวแรกที่ ffmpeg ยังอ่านอยู่ + x264 สองตัวพร้อมกันใน `mem_limit: 2g`
   **แก้ 2 ทาง**: ปฏิเสธตรงๆ ระหว่าง working (ทางเดียวที่ซื่อสัตย์ เพราะหยุดไม่ได้จริง)
   และแยก workdir เป็น `/data/work/<timestamp>` ต่อ Story ไม่ให้ path ชนกันได้อีก
2. **สาขา `if not pending: state["mode"] = "idle"`** ที่เพิ่มรอบแรก — ทางเดียวที่จะเข้าถึง
   คือแตะ ✅ ซ้ำแล้ว spawn `make_story` ตัวที่สอง ซึ่งจะไปเคลียร์ธง busy ของ**ตัวที่ชนะ**
   `pop` ไป แก้ด้วยการ pop `pending` ที่ `handle()` แล้วส่งเป็น argument — แตะครั้งที่สอง
   เจอ `state.get("pending")` ว่าง ไม่ทำอะไรเลย สาขานั้นหายไปทั้งอัน

แก้ `/help` ให้ตรงกับพฤติกรรมจริง (`/cancel` ใช้ได้เฉพาะตอนรออนุมัติ)
เทสต์ 29 ข้อยังผ่าน, `import app.main` โดยไม่มี env ยังผ่าน

## 2026-09-14 (ต่อ 3) — review ทั้งสอง stack แล้ว redesign story-factory

ผู้ใช้ให้ทำตามลำดับที่เสนอ (ดู 00_INDEX "review รอบสาม"). ทำ story #1-#4 ในรอบเดียว
เพราะทั้งหมดแก้ `make_story` ตัวเดียวกัน:
- `render.run/ffmpeg/concat` async, `ping_pong/build` async, `tts.voice_chapter` async
  (Google ใน `to_thread`, trim ผ่าน `render.ffmpeg`), รับ `scratch` ไม่ใช้ TemporaryDirectory
- `app/story.py` ใหม่ + `tests/test_story.py` 4 ข้อ, `test_render.py` +2 (cancel kills child, stderr in error)
- `main.py` เขียนใหม่: `begin()/busy()/_current`, `/resume`, ปุ่ม resume ตอน start,
  `/cancel` ยกเลิกได้ทั้ง Outline และ Story
เทสต์ 35 ผ่าน, import ไม่ต้องมี env ผ่าน. ยังไม่ commit — รอ /release พร้อม root docs
ต่อไป: shared/mimo.py + shared/telegram.py แล้วรื้อ hedge ใน shorts

**2026-09-15** — `shared/telegram.py` mutes `httpx` logger at import: INFO log line carries the bot token in the URL. Inherited via vendored copy.

## 2026-09-15 — ตรวจสถานะก่อนเริ่มใช้งานจริง

ไม่แตะโค้ด สำรวจอย่างเดียว แล้วเขียน `.notes/GO_LIVE_CHECKLIST.md`

ข้อเท็จจริงที่ตรวจแล้ว (ต่างจากที่ `00_INDEX.md` เขียนไว้ 2026-09-14):
- `story-factory/.env` **ถูก render แล้ว** (literals 19 ค่า) → pre-upload verify ของ deploy.sh
  ผ่าน แม้ manifest ยังไม่มี `env:` — deploy ทั้ง repo ไม่ได้พังอย่างที่กลัว
- `scripts/deploy.sh` เติม `story-factory` ใน `ALL_STACKS` แล้ว แต่ยัง uncommitted
- `app/mimo.py`/`app/telegram.py` ตรงกับ `shared/` (รวม fix token-logging 296e557) ไม่ drift

กับดักที่เพิ่งเจอ เพิ่มเข้า checklist:
- **ชื่อ vault path ขัดกัน** — manifest = `stacks.story_factory.google.credentials_b64`
  (nested) แต่ root `CLAUDE.md` = `stacks.story_factory.google_credentials_b64` (flat)
  เลือกผิดทาง = `missing vault path` แล้ว `make secrets` พังทั้ง repo. ตัดสินใช้ nested
- **รอบทดสอบเสียงใช้โค้ดใน stack ไม่ได้** — `tts._synthesize()` ใช้ `TextToSpeechClient()`
  ซึ่งรับแค่ ADC/service account ป้อน API key ไม่ได้ → รอบทดสอบต้องยิง REST
  `v1/text:synthesize?key=` เอง (ข้อ 4 รอยต่อ chunk ยังใช้ `chunking.py` + concat ในรีโปได้ ไม่ต้อง credential)
- **Backdrop เป็น prereq ที่ลิสต์ "ต้องมีก่อน deploy" ลืมเขียน** — `main.py:234` อ่าน
  `/volume1/stories/backdrop.mp4` แล้ว `backdrop.png` ชื่อตายตัว ไม่มีไฟล์ = ปฏิเสธหลังอนุมัติ Outline
- **`write_credentials()` เงียบเมื่อ blob ว่าง** → บอทบูตผ่าน เขียนครบ 7 บท แล้วตายตอน TTS
  ต้อง smoke test ด้วย `docker exec` ก่อนพิมพ์ `/story` รอบแรก
- `secrets/test-vault.sops.yaml` dirty อยู่ (ciphertext churn) ต้องเคลียร์ก่อนใส่คีย์ใหม่

**พักงานไว้ (2026-09-15)** — คนตัดสินใจว่ายังไม่อยากมีค่าใช้จ่ายเพิ่ม. Cloud TTS
คิดเงินจาก billing account ของ GCP project แยกจาก subscription Gemini Pro
(consumer sub ไม่ให้เครดิต GCP) และโควตาฟรีแยกตามชนิดเสียง ไม่ pool.
ยิงหน้า pricing แล้วเนื้อหาถูกตัด → **ตัวเลข $0.60/Story + ฟรี 1M chars/เดือน
ยังไม่ได้ verify กับหน้า pricing จริง** ต้องเช็คแถว Chirp 3: HD เอง (บางชั้นคิดต่อไบต์
ไม่ใช่ต่อ character = ไทย 3 ไบต์/ตัว แพงขึ้น 3 เท่า).
งานฝั่งโค้ดไม่มีอะไรค้าง — blocker เดียวคือการตัดสินใจเรื่องค่าใช้จ่าย.
ทางเลือกถ้าไม่ผูกบัตร = edge-tts (ฟรี) แต่เท่ากับพลิก ADR 0012.
