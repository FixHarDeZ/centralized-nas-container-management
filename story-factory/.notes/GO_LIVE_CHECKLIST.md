# story-factory — ลำดับงานก่อนใช้งานจริง (2026-09-15)

สถานะจริงตอนนี้ (ตรวจแล้ว ไม่ใช่เดา):

- `story-factory/.env` **มีแล้ว** (literals ล้วน 19 ค่า) → deploy ไม่พังตอน pre-upload verify
- `scripts/deploy.sh` ใส่ `story-factory` ใน `ALL_STACKS` แล้ว แต่ **ยังไม่ commit**
- `app/mimo.py` / `app/telegram.py` ตรงกับ `shared/` แล้ว (รวม fix token-logging 296e557)
- vault ยังไม่มี `stacks.story_factory.*` เลย, manifest ยัง comment `env:` ทั้งบล็อก
- `secrets/test-vault.sops.yaml` dirty = ciphertext churn (re-encrypt) ต้องดูก่อนเอา key ใหม่ทับ

---

## ขั้นแรก: แก้ชื่อ vault path ให้ตรงกัน (ต้องทำก่อนแตะ vault)

manifest เขียน `stacks.story_factory.google.credentials_b64` (nested)
root `CLAUDE.md` เขียน `stacks.story_factory.google_credentials_b64` (flat)
เลือกอันเดียว — ใช้ **nested** (`...google.credentials_b64`) ให้เข้าชุดกับ `telegram.*`
แล้วแก้ `CLAUDE.md` ตาม. ใส่ค่าใน vault ผิด path = `render_env.py` โยน `missing vault path`
แล้ว `make secrets` พังทั้ง repo ไม่ใช่แค่ stack นี้.

---

## A. งานที่มีแต่คนทำได้ (ผมทำแทนไม่ได้)

### A1. GCP — เปิด Text-to-Speech API
โปรเจกต์เดียวกับ shorts-factory. Console → APIs & Services → Enable
`Cloud Text-to-Speech API`.

### A2. รอบทดสอบเสียง (ทิ้ง ไม่แตะ vault) — ตอบ 4 คำถามในรอบเดียว
สร้าง **API key ธรรมดา** (ไม่ใช่ service account) แล้วยิง REST ตรง:

```
POST https://texttospeech.googleapis.com/v1/text:synthesize?key=<API_KEY>
```

⚠️ `app/tts.py` ใช้ `TextToSpeechClient()` ซึ่งรับแค่ ADC/service-account —
**ป้อน API key เข้า client library ไม่ได้** รอบทดสอบต้องยิง REST เอง

ต้องได้คำตอบ:
1. **เสียงไหน** — th-TH Chirp3-HD หญิง Achernar/Kore/Leda/Zephyr/Sulafat,
   ชาย Charon/Orus/Puck/Algenib/Rasalgethi. บรีฟ = อุ่น นิ่ง เล่าช้า แบบสารคดี
2. **`speaking_rate` ใช้ได้จริงไหมกับ Chirp 3: HD** (เอกสาร Google ขัดกันเอง)
3. **pause/markup tag กับไทย** ทำงานแค่ไหน
4. **รอยต่อ chunk ได้ยินไหม** — ย่อหน้าเดียวยิงครั้งเดียว vs หั่น 3 ครั้ง
   **ต้องเล็มความเงียบแบบ production (`JOIN_SILENCE` 0.30) ก่อนฟัง** ไม่งั้นได้ยิน
   padding ของ Google แล้วไปโทษ prosody. ฟัง **ระดับเสียง/โทนกระโดด** ไม่ใช่ช่องว่าง
   ข้อนี้ข้อเดียวที่พลิก ADR 0012 ได้
   (ข้อ 4 รันด้วยโค้ดในรีโปได้เลย — `chunking.py` + concat ของ `render.py` ไม่ต้องใช้ credential)

### A3. Telegram bot ตัวใหม่
BotFather → `/newbot` → เก็บ token. **ห้ามใช้ token ของ shorts-factory**
(สองโปรเซส long-poll `getUpdates` token เดียว = แย่งข้อความกัน)
ทักบอทหนึ่งข้อความ แล้วอ่าน chat_id:
`curl -s "https://api.telegram.org/bot<TOKEN>/getUpdates"` → `.result[].message.chat.id`

### A4. Service account JSON → base64 บรรทัดเดียว
GCP → IAM → Service Accounts → สร้าง + role `Cloud Text-to-Speech User` → ดาวน์โหลด JSON
```
base64 -i sa.json | tr -d '\n' | pbcopy
```
(`render_env.py` ไม่ยอม newline ใน `.env`)

### A5. DSM shared folder `stories`
Control Panel → Shared Folder → สร้าง `stories` (บน volume1)
`synoshare --add` ปฏิเสธ (`share_is_acl_share.c`) — ต้องกดใน UI
ไฟล์ ~470 MB/Story หยิบผ่าน File Station/SMB ได้เฉพาะ shared folder จริง

### A6. Backdrop — **prereq ที่ notes ลืมเขียน**
`main.py:234` อ่าน `/volume1/stories/backdrop.mp4` ก่อน แล้ว `backdrop.png`
ไม่มีไฟล์ = บอทปฏิเสธ "ไม่มี Backdrop" หลังอนุมัติ Outline
- คลิป Flow **ห้ามเกิน 8 วิ** (`BACKDROP_MAX_SECONDS`) — ping-pong reverse อมทุกเฟรม ~3.1 MB
- ชื่อไฟล์ตายตัว 1 ไฟล์ ใช้ร่วมทุก Story จนกว่าจะเปลี่ยนโค้ด

---

## B. งานฝั่งผม (สั่งได้เลยหลัง A เสร็จ) — ลำดับห้ามสลับ

1. `make edit-vault` → ใส่ `stacks.story_factory.telegram.bot_token`,
   `.telegram.chat_id`, `stacks.story_factory.google.credentials_b64`
   (ดู `secrets/test-vault.sops.yaml` ที่ dirty อยู่ก่อน ว่าต้อง sync ด้วยไหม)
2. เปิด comment `env:` ใน `story-factory/secrets.manifest.yaml`
   (`MIMO_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `GOOGLE_CREDENTIALS_B64`)
   + แก้ `TTS_VOICE` เป็นเสียงที่เลือกจาก A2 (+ `TTS_SPEAKING_RATE` ถ้าใช้ได้จริง)
3. `make secrets` → ยืนยัน `story-factory/.env` มี 4 คีย์ใหม่
4. `cd story-factory && python -m pytest tests/ -q` (35 ข้อ) + root `pytest tests/test_shared_sync.py`
5. อัปเดตเอกสารใน commit เดียวกับโค้ด (`/release` rule): root `CLAUDE.md` ตาราง stack
   (ลบ "ยังไม่ deploy"), root `README.md`, `.notes/00_INDEX.md`, `.notes/daily_log.md`
6. `./scripts/deploy.sh -y` (ไม่มี `-y` = ไม่มี TTY แล้ว upload ถูกข้ามเงียบๆ)
7. **smoke test ก่อนพิมพ์ `/story`** — `write_credentials()` เงียบเมื่อ blob ว่าง
   บอทจะบูตผ่าน เขียนบทจนหมด แล้วค่อยตายตอน TTS (เสียเวลา 10+ นาที + ค่า mimo):
   ```
   docker exec story-factory python -c "from app import tts; tts.write_credentials(); \
     from google.cloud import texttospeech; texttospeech.TextToSpeechClient(); print('TTS OK')"
   ```
8. `/story <หัวข้อ>` รอบแรก → อนุมัติ Outline → ~25 นาที render → ไฟล์โผล่ที่ `/volume1/stories`
