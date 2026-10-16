# lotto-picker

สุ่มเลขท้าย 3 ตัวที่ไม่ซ้ำกับเลขที่ออกใน N งวดล่าสุด ผลรางวัลมาจาก API ของสำนักงานสลากกินแบ่งรัฐบาล (GLO)
หน้าเว็บใช้บนมือถือได้ ส่งเลขอัตโนมัติกับผลรางวัลเข้า Telegram และตรวจผลเลขที่บันทึกไว้ให้เอง

> ทุกเลขมีโอกาสออก 1 ใน 1000 เท่ากันทุกงวด การตัดเลขที่เคยออกไม่ได้เพิ่มโอกาสถูก
> สถิติในหน้าเว็บจะเทียบจำนวนครั้งที่ถูกกับค่าที่การสุ่มธรรมดาคาดไว้ (`expected`)

| | |
|---|---|
| Port | `5073` (nginx basic auth ทุก path) → DSM RP `https://…:15073` |
| Data | volume `lotto_picker_data:/data` → `lotto.db` |
| Stack | FastAPI + SQLite + APScheduler (`python:3.12-slim`, uid 1000) |

## หน้าเว็บบนมือถือ

- เมนูล่าง 3 ส่วน: **สุ่มเลข / เลขที่บันทึก / ผลรางวัล**; จอใหญ่แสดงเมนูด้านบนและพื้นที่สุ่มสองคอลัมน์
- ปรับจำนวนงวดและจำนวนเลขด้วยปุ่ม +/− หรือค่าลัด; ตัวเลือกประเภทรางวัลและตัดโต๊ดอยู่ใน “ตัวเลือกเพิ่มเติม”
- เลขที่สุ่มแสดงเป็นตั๋วตัวใหญ่ คัดลอกได้ทั้งชุด และต้องกด **บันทึกไว้ตรวจผล** เพื่อเก็บเข้าประวัติ
- “เลขอัตโนมัติและการแจ้งเตือน” เปิด/ปิดทั้งการสร้างเลขอัตโนมัติและการส่งแจ้งเตือน; กด **ใช้ค่าชุดนี้กับเลขอัตโนมัติ** เพื่อบันทึกค่าการสุ่มปัจจุบัน
- ประวัติแยกรอผล / ถูกรางวัล / ตรวจแล้วไม่ถูก พร้อมประเภทรางวัลที่ถูก; ยืนยันก่อนลบชุดเลข
- รองรับธีมมืดตามระบบ ปุ่มสัมผัสอย่างน้อย 44px และการนำทางด้วยคีย์บอร์ด

## ที่มาของผลรางวัล

- `POST https://www.glo.or.th/api/lottery/getLatestLottery` body `{}` คืนงวดล่าสุด
- `POST https://www.glo.or.th/api/lottery/getLotteryResult` body `{"date":"17","month":"01","year":"2026"}` คืนผลของวันนั้น ถ้าวันนั้นไม่มีงวดจะได้ `response: null`
- ไม่ต้องใช้คีย์ ตรวจสอบจาก NAS เมื่อ 2026-10-16
- `lotto.api.rayriffy.com` ที่สคริปต์ทั่วไปใช้ DNS ตายแล้ว

GLO ไม่มี endpoint ลิสต์งวด ระบบจึงเดินถอยหลังจากงวดล่าสุด ยิงเฉพาะวันใน `CANDIDATE_DAYS`
(1,2,3,15,16,17,28–31 เพราะงวดเคยเลื่อนเป็น 17 ม.ค. / 2 พ.ค. / 30 ธ.ค.) วันที่ได้ `null` จะเก็บไว้ในตาราง `nodraw`
และจะไม่ยิงซ้ำ ถ้าเลยไป 45 วันแล้วยังไม่เจองวดก็หยุด เก็บย้อนหลังได้สูงสุด 24 งวด

**ระบบเก็บงวดเฉพาะเมื่อครบทุกรางวัล** (รางวัลที่ 1 = 1, รางวัลที่ 2 = 5, รางวัลที่ 3 = 10, รางวัลที่ 4 = 50, รางวัลที่ 5 = 100, ข้างเคียง = 2, หน้า 3 ตัว = 2, ท้าย 3 ตัว = 2)
GLO ปล่อยผลระหว่างการจับสด ถ้าเก็บงวดที่ยังไม่ครบ ข้อมูลครึ่งงวดจะค้างอยู่ถาวร
ส่วนวันที่ของงวดที่กำลังจับจะจดลง kv `latest_seen` ทันที

## การตัดเลข

- **ทุกรางวัล** (ค่าเริ่มต้น): ใช้ 3 ตัวท้ายของรางวัลที่ 1–5 และรางวัลข้างเคียง รวมกับเลขหน้า 3 ตัวและเลขท้าย 3 ตัว
  ไม่นับเลขท้าย 2 ตัว และไม่นับ `n3` (สลาก N3 เป็นสลากอีกประเภท)
- **เฉพาะหน้า/ท้าย 3 ตัว**: ใช้แค่ 4 เลข
- **ตัดโต๊ด**: ตัดทุกการสลับหลักของเลขที่ออก ทำให้ pool แคบลงเร็วมาก

งวดหนึ่งมีเลข 3 ตัวไม่ซ้ำกันราว 155 เลข ถ้าย้อนหลัง 2 งวดจะเหลือเลขให้สุ่มประมาณ 714 เลข ถ้า 5 งวดจะเหลือประมาณ 429 เลข (วัดจากงวดจริง ส.ค.–ต.ค. 2569)

## งานตามเวลา (Asia/Bangkok)

| งาน | เวลา | ทำอะไร |
|---|---|---|
| `poll_results` | 15:00–19:45 ทุก 15 นาที และตอน startup | sync ผลรางวัล ตรวจเลขที่บันทึกไว้ แล้วส่ง Telegram **เฉพาะเมื่อมีงวดล่าสุดถูกเพิ่มเข้ามาใหม่** (งวดที่ backfill และงวดแรกตอนเปิดเครื่องครั้งแรกจะไม่ส่ง) |
| `auto_pick` | `PICK_TIME` (20:00) | ถ้าพรุ่งนี้เป็นวันออกรางวัลตามปฏิทิน (วันที่ 1/16) จะสุ่มตามค่าที่บันทึกไว้ แล้วบันทึกเป็นเลข `auto` และส่ง Telegram มี kv `auto_pick_target` กันส่งซ้ำ |

ปุ่ม "แจ้งเตือน" ในหน้าเว็บ (`notify`) เปิด/ปิดได้ทั้งสองงาน

## การตรวจผล

เลขที่บันทึกไว้จะผูก `based_on` กับงวดล่าสุดที่ระบบเห็นตอนบันทึก (ก่อนบันทึกจะ sync ทุกครั้ง)
แล้วตรวจกับงวดแรกที่ใหม่กว่างวดนั้น เลขที่บันทึกหลังผลออกแล้วจึงไม่ถูกตรวจกับผลที่รู้อยู่แล้ว

ประเภทที่ถูก:
- 3 ตัวท้ายรางวัลที่ 1
- เลขหน้า 3 ตัว
- เลขท้าย 3 ตัว
- โต๊ด 3 ตัวท้ายรางวัลที่ 1 (นับแยก ไม่รวมใน `exact_hits`)

## API

| Method | Path | |
|---|---|---|
| GET | `/api/settings` · PUT | `{draws, picks, scope: all\|front_back, permute, notify}` |
| POST | `/api/pick` | สุ่มอย่างเดียว ไม่บันทึก คืน `numbers, pool_size, excluded, draws_used` |
| GET/POST | `/api/picks` | ประวัติ / บันทึกเลขไว้ตรวจผล |
| DELETE | `/api/picks/{id}` | |
| GET | `/api/draws` · `/api/stats` | |
| POST | `/api/sync` | ดึงผลรางวัลทันที |
| GET | `/healthz` | healthcheck (ยิงตรงที่แอป ไม่ผ่าน nginx) |

## Secrets / env

`secrets.manifest.yaml`:
- `LOTTO_TELEGRAM_BOT_TOKEN` / `LOTTO_TELEGRAM_CHAT_ID` → ใช้ bot ของ news-feed (`stacks.news_feed.telegram.*`) ส่งอย่างเดียว ไม่ได้อ่าน update จึงไม่ชนกับ news-feed
- literals `DATA_DIR=/data`, `PICK_TIME=20:00`
- ไม่บังคับ: `LINE_CHANNEL_ACCESS_TOKEN` + `LINE_TO` (ถ้าว่างจะไม่ส่ง LINE) และ `PUBLIC_URL` (ใส่ลิงก์ท้ายข้อความ)

Basic auth ของ dashboard อยู่ที่ `stacks.lotto_picker.dashboard.basic_auth_user/basic_auth_password` → `nginx/.htpasswd` (gitignored):

```bash
export SOPS_AGE_KEY_FILE=~/.config/sops/age/keys.txt
U=$(sops -d --extract '["stacks"]["lotto_picker"]["dashboard"]["basic_auth_user"]' secrets/vault.sops.yaml)
P=$(sops -d --extract '["stacks"]["lotto_picker"]["dashboard"]["basic_auth_password"]' secrets/vault.sops.yaml)
printf '%s:%s\n' "$U" "$(openssl passwd -apr1 "$P")" > lotto-picker/nginx/.htpasswd
chmod 644 lotto-picker/nginx/.htpasswd
```

## Tests

```bash
cd lotto-picker && ../.venv/bin/python -m pytest tests -q
```

ใช้ payload จริงของ GLO ใน `tests/fixtures/` (งวด 1 ต.ค. 2569 และ 17 ม.ค. 2569 ที่เลื่อนวัน) และใช้ fetcher ปลอมจึงไม่ต้องต่อเน็ต

Browser acceptance tests เป็น opt-in ใช้ `pytest` + Python `playwright` และ Chrome ที่ติดตั้งในเครื่อง:

```bash
cd lotto-picker
LOTTO_UI_BROWSER=1 ../.venv/bin/python -m pytest tests/test_ui_browser.py -q
```

ทดสอบผ่าน local fixture server โดยไม่เปิด FastAPI scheduler ไม่เรียก GLO และไม่ส่ง Telegram
ครอบคลุมเมนูมือถือ สุ่ม/บันทึก/คัดลอก การตั้งค่า การลบและยกเลิก โหลดใหม่หลัง error เลขหมด และ layout 320/390/768/1440px
ตั้ง `LOTTO_UI_SCREENSHOTS=/tmp/lotto-ui` เพิ่มเมื่อต้องการภาพ light/dark ของแต่ละขนาด
