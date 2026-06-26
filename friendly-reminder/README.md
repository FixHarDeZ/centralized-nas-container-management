# friendly-reminder

ระบบติดตามการผ่อนชำระรายเดือน — FastAPI + SQLite + Nginx Basic Auth. บันทึกรายการผ่อน
(ชื่อ, ราคา, จำนวนงวด, เดือนเริ่มต้น) แล้ว auto-generate งวดชำระตลอดอายุสัญญา.

- **Port:** `5066` (nginx → app:8000)
- **Data:** SQLite + สลิป/เอกสาร ใน volume `/data`
- **Reminder:** APScheduler ส่ง LINE วันที่ 1 ของเดือน (`REMINDER_TIME`, default 08:00) +
  แจ้งล่วงหน้า 1 วัน (`DAY_BEFORE_REMINDER_TIME`, default 20:00)
- **Export:** CSV ที่ `/api/report`

## LINE slip auto-pay (webhook)

โพสต์รูปสลิปในกลุ่ม LINE → ระบบแนบสลิปเข้าระบบ + เปลี่ยนสถานะเป็น "จ่ายแล้ว" อัตโนมัติ

- **Webhook URL:** `https://fixhardez.synology.me:15066/webhook/line` (public ผ่าน DSM reverse proxy
  → nginx `location = /webhook/line` ที่ข้าม basic auth; app ตรวจ `X-Line-Signature`)
- **การจับคู่งวด:** นับ "งวดค้าง" = `paid_at IS NULL` และครบกำหนด ≤ เดือนนี้
  - ค้างงวดเดียว → แนบสลิป + mark paid ทันที + แจ้งยืนยันในกลุ่ม
  - ค้างหลายงวด → บอทถามให้พิมพ์ชื่อรายการ แล้วจับคู่สลิปกับ text ที่ตอบมา (pending slot, TTL 10 นาที)
  - ไม่มีงวดค้าง → แจ้ง "ไม่มีงวดค้างชำระ"
- **Security:** signature verify บังคับ (endpoint นี้ flip payment → paid) + กรองเฉพาะ event จาก
  `FRIENDLY_LINE_GROUP_ID`; idempotent ต่อ LINE webhook retry

### Vault keys (`stacks.friendly_reminder.line.*`)

| key | ใช้ทำ |
| :-- | :-- |
| `channel_access_token` | push แจ้งเตือน + ดึงรูปสลิป (`api-data.line.me`) |
| `channel_secret` | ตรวจ `X-Line-Signature` ของ webhook |
| `group_id` | ปลายทาง push + กรอง event |

### LINE Official Account setup (manual)

1. Messaging API → **Use webhook: ON**, Webhook URL = `https://fixhardez.synology.me:15066/webhook/line` → กด **Verify** (คาดหวัง 200)
2. Response settings → **Auto-reply: OFF** (ถ้าเปิด OA จะกินข้อความ webhook ไม่ทำงาน)
3. บอทต้องอยู่ในกลุ่ม `FRIENDLY_LINE_GROUP_ID`
