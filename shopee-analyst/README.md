# shopee-analyst

แนะนำสินค้า Shopee Affiliate ที่น่าทำคลิป ส่งเข้า Telegram ทุกวัน 06:00 / 12:00 / 16:00 (เวลาไทย)
รอบละ 5 ตัว พยายามไม่ซ้ำภายใน 72 ชม.

ที่มา: โค้ดจากแชท claude.ai (เดิมออกแบบให้รันบน GitHub Actions) ย้ายมาเป็น stack บน NAS —
ไม่ต้อง commit history ลง git, snapshot อยู่ใน named volume `/data`

## โครง

| ไฟล์ | หน้าที่ |
|---|---|
| `app/analyst.py` | เรียก Shopee Affiliate Open API (GraphQL), ให้คะแนน, เก็บ snapshot, จัดข้อความ Telegram |
| `app/main.py` | sleep loop ตาม `SLOTS` + CLI `--once` / `--probe` / `--telegram-test` |
| `app/notify.py` | vendored จาก `shared/notify.py` (ห้ามแก้สำเนา — `make sync-shared`) |
| `config.json` | เกณฑ์คัดสินค้า (bake ในอิมเมจ แก้แล้ว deploy) |

ไม่มี HTTP, ไม่มี port. Healthcheck ดู `/data/heartbeat` ที่ loop touch ทุกนาที

## API

- Endpoint ไทย: `https://open-api.affiliate.shopee.co.th/graphql` (ยืนยันแล้วว่าตอบ — ด้วยคีย์ปลอมได้ `error [10035]` "You currently do not have access to the Shopee Affiliate Open API Platform")
- Auth header: `SHA256 Credential=<app_id>, Timestamp=<unix วินาที>, Signature=<sha256(app_id + timestamp + payload + secret)>`
- Query `productOfferV2(keyword, sortType, page, limit)` — `sortType`: 1 relevance, **2 ยอดขายมากสุด**, 3 ราคามาก→น้อย, 4 ราคาน้อย→มาก, 5 ค่าคอมมากสุด
- ชื่อฟิลด์ + enum มาจาก SDK บุคคลที่สาม (`saapi`, `shopee-afflib` — ฝั่งบราซิล) **ยังไม่ยืนยันกับบัญชีไทย** → ใช้ `--probe` ตอนได้คีย์

## คะแนน

`ยอดขายเพิ่มต่อวัน × ค่าคอมต่อชิ้น × (1 + อัตราโต สูงสุด 1)`

`sales` จาก API เป็นยอดสะสม จึงเทียบกับ snapshot ที่ใกล้ 24 ชม. สุด (20–30 ชม.; ไม่มีก็อันเก่าสุดที่เกิน 1 ชม.).
รอบแรกยังไม่มีฐาน → จัดจากยอดสะสม × ค่าคอม พร้อมป้ายเตือน. ควรเก็บ 1–2 สัปดาห์ก่อนเชื่อแนวโน้ม.
Snapshot เขียน**หลัง**ส่ง Telegram สำเร็จเท่านั้น (ส่งพัง = รอบหน้าเทียบกับฐานเดิม).

## `config.json`

| ค่า | ความหมาย |
|---|---|
| `keywords` | คำค้นเฉพาะหมวด เช่น `["ของใช้ในบ้าน"]` ว่าง = ดึงตามยอดขายรวม |
| `sort_type` | ดูตาราง sortType ข้างบน (default 2) |
| `pages_per_search` / `page_size` | จำนวนหน้า × ขนาดหน้า ต่อ keyword |
| `top_n` | จำนวนสินค้าต่อรอบ |
| `min_rating` / `min_commission_rate` / `min_total_sales` | เกณฑ์ขั้นต่ำ (`0.03` = 3%) |
| `repeat_cooldown_hours` | ไม่แนะนำซ้ำภายในกี่ชม. |
| `retention_days` | เก็บ snapshot กี่วัน |

## Secrets

- Telegram: ใช้ bot ของ news-feed (`stacks.news_feed.telegram.*`) send-only
- Shopee: **ยังไม่มีใน vault** — ไม่มีคีย์ = log `skipping run` แล้วไม่ส่งอะไร

เปิดใช้เมื่อได้ App ID / Secret จากเมนู Open API ใน dashboard Shopee Affiliate:

```bash
make edit-vault          # เพิ่ม stacks.shopee_analyst.shopee.app_id / app_secret
# แล้วค่อยเอาคอมเมนต์ SHOPEE_APP_ID / SHOPEE_APP_SECRET ใน secrets.manifest.yaml ออก
# (ใส่ใน manifest ก่อนมีค่าใน vault = make secrets พังทั้ง repo)
make secrets
./scripts/deploy.sh -s shopee-analyst -y
ssh nas "sudo -n /usr/local/bin/docker exec shopee-analyst python -m app.main --probe"
ssh nas "sudo -n /usr/local/bin/docker exec shopee-analyst python -m app.main --once"
```

## คำสั่ง

```bash
docker exec shopee-analyst python -m app.main --telegram-test   # ทดสอบ Telegram
docker exec shopee-analyst python -m app.main --probe           # 1 call limit=1 พิมพ์ฟิลด์
docker exec shopee-analyst python -m app.main --once            # รันรอบเดียวเดี๋ยวนี้
```

## เทสต์

```bash
cd shopee-analyst && uv run --no-project --python 3.12 --with pytest python -m pytest -q tests
```

Fake Shopee server ตรวจ signature จริง, Telegram mock ที่ `notify._urllib_post` — ไม่ยิงข้างนอก

## ข้อจำกัด

- API ไม่บอกจำนวน affiliate ที่โปรโมตสินค้าเดียวกัน — ต้องดูเองจาก TikTok/Reels
- ไม่ scrape เว็บ Shopee (เสี่ยงบล็อก + กระทบบัญชี affiliate)
- ต่อยอด: ผูก Sub ID กับรายงาน conversion (มีตารางใน `shorts-factory` Shop affiliate tracking แล้ว) เพื่อปรับคะแนนจากผลจริง
