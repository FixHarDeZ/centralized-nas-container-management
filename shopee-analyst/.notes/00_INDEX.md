# shopee-analyst — INDEX

แนะนำสินค้า Shopee Affiliate น่าทำคลิป → Telegram 06:00/12:00/16:00. รายละเอียดเต็ม: `../README.md`

## สถานะ
- **2026-11-02 สร้าง + deploy แล้ว** (no port): container `shopee-analyst` healthy บน NAS, `--telegram-test` ส่งถึงจริง (bot news-feed), loop รอรอบ 06:00
- **❌ บัญชีไม่มีสิทธิ์ Open API** (02/11 หน้า affiliate.shopee.co.th/open_api: AppID/ความลับ = `--`, ปุ่ม 'ใช้' กดไม่ได้, "คุณไม่ได้รับสิทธิ์ในการเข้าถึง Shopee Affiliate Open API Platform" → ต้องขอผ่านลิงก์ 'ติดต่อเรา'). Stack รอเงียบได้ ไม่เปลือง
- **⏳ รอ Shopee App ID/Secret** — vault ยังไม่มี `stacks.shopee_analyst.shopee.*`, manifest คอมเมนต์ไว้; ตอนนี้ทุกรอบ log `skipping run` ไม่ส่งอะไร
- Shopee data path **ยังไม่ verify** กับบัญชีจริง: ยืนยันแค่ endpoint ไทยตอบ (คีย์ปลอม → `error [10035]` no Open API access, ยิงจากใน container บน NAS ได้). Signature/ฟิลด์/sortType ตรงกับ SDK บุคคลที่สาม (`saapi` sortType 2 = ITEM_SOLD_DESC) แต่ยังไม่ผ่านบัญชีไทย
- Bot token ที่วางในแชท claude.ai **ไม่ได้ใช้** (chat_id ตรงกับ news-feed อยู่แล้ว) — ต้อง /revoke ใน BotFather

## โครงไฟล์
- `app/analyst.py`: `shopee_request` (sign), `fetch_products`, `probe`, `rank_products`, `select_fresh`, `build_messages` (≤4000/ข้อความ), `send_telegram` (raise ถ้า notify ไม่คืน `telegram`), `run`
- `app/main.py`: `slots()`/`next_slot()`, `run_once()` (ไม่มีคีย์ = skip เงียบ; error อื่นแจ้ง Telegram), `loop()` heartbeat ทุก 60 วิ
- `app/notify.py` vendored จาก `shared/`
- `/data`: `snapshots/<UTC>.json` `{item_id:{sales}}`, `sent.json` `{item_id: iso}`, `heartbeat`

## งานถัดไป
1. ผู้ใช้เช็คเมนู Open API / ขอสิทธิ์ใน affiliate.shopee.co.th → ได้ App ID + Secret
2. `make edit-vault` → เอาคอมเมนต์ใน manifest ออก → `make secrets` → deploy → `--probe` → แก้ฟิลด์ถ้าไทยต่าง → `--once`
3. เก็บ 1–2 สัปดาห์ก่อนเชื่อแนวโน้ม; ต่อยอดผูก Sub ID/รายงาน conversion
