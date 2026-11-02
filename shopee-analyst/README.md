# shopee-analyst

แนะนำสินค้าที่น่าทำคลิป affiliate ส่งเข้า Telegram ทุกวัน 06:00 / 12:00 / 16:00 (เวลาไทย)
รอบละ 5 ตัว พยายามไม่ซ้ำภายใน 72 ชม. มี 2 แหล่ง รันแยกกัน:

1. **YouTube TH (ใช้งานอยู่)** — `app/clips.py` คลิป Shorts ไทยแนวป้ายยา/รีวิวที่วิวกำลังขึ้น + mimo แยกชื่อสินค้า
2. **Shopee Affiliate Open API (dormant)** — `app/analyst.py` บัญชียังไม่ได้สิทธิ์ (หน้า open_api: AppID `--`)

ที่มา: โค้ดจากแชท claude.ai (เดิมออกแบบให้รันบน GitHub Actions) ย้ายมาเป็น stack บน NAS —
ไม่ต้อง commit history ลง git, snapshot อยู่ใน named volume `/data`

## โครง

| ไฟล์ | หน้าที่ |
|---|---|
| `app/clips.py` | YouTube: ค้นวันละรอบ, วัดวิวทุกรอบ, กรองไทย, จัดอันดับ, mimo แยกชื่อสินค้า (grounded) |
| `app/analyst.py` | Shopee Open API (GraphQL), ให้คะแนน, snapshot, `send_telegram`/`pack` ที่ใช้ร่วม |
| `app/mimo.py` | vendored จาก `shared/mimo.py` |
| `app/main.py` | sleep loop ตาม `SLOTS` + CLI `--once` / `--probe` / `--telegram-test` |
| `app/notify.py` | vendored จาก `shared/notify.py` (ห้ามแก้สำเนา — `make sync-shared`) |
| `config.json` | เกณฑ์คัดสินค้า (bake ในอิมเมจ แก้แล้ว deploy) |

ไม่มี HTTP, ไม่มี port. Healthcheck ดู `/data/heartbeat` ที่ loop touch ทุกนาที

## YouTube (แหล่งหลัก)

- คีย์เวิร์ด `config.json` → `youtube.keywords` (`ป้ายยา`, `ของดีบอกต่อ`, `รีวิว shopee`, `ของใช้ในบ้าน`) คลิปสั้น โพสต์ใน 7 วัน
- **โควตา**: ใช้ OAuth client ของ shorts-factory = แชร์ 10,000 units/วัน กับการอัปคลิปจริง. `search.list` = 100 units
  รันแค่รอบแรกของวัน (Bangkok) × `max_keywords` (4) ที่เหลือ `videos.list` 1 unit/50 คลิป ≈ **402 units/วัน**.
  log บรรทัด `units=` ทุกรอบ. แยกออกได้ทีหลังด้วย API key/GCP project ของตัวเอง
- กรอง: วิว ≥ `min_views`, อักษรไทย ≥ `min_thai_ratio` ของตัวอักษร (regionCode=TH ยังปล่อยคลิปบราซิลมา)
- คะแนน: วิวเพิ่มต่อชม. เทียบ snapshot ก่อนหน้า (ใกล้ 24 ชม. สุด) — รอบแรกใช้วิว/ชม. ตั้งแต่โพสต์
- mimo (`mimo-v2.6-flash`, `mimo_seconds` 180): ชื่อสินค้า + มุมคลิป. **ชื่อต้องอยู่ในข้อความของคลิปนั้นจริง** ไม่งั้นทิ้ง;
  คลิปที่ไม่ใช่สินค้าหลุดไป. mimo ล่ม = ส่งรายการคลิปดิบพร้อมป้ายเตือน
- ข้อความ: ชื่อสินค้า, วิว/ชม., ชื่อคลิป, 💡 มุม, ลิงก์คลิป + `shopee.co.th/search?keyword=` (เปิดในแอปแล้วสร้างลิงก์ affiliate เอง)
- ข้อจำกัด: วิว ≠ ยอดขาย; TikTok (ที่คลิป affiliate ไทยอยู่เยอะสุด) ยังไม่ครอบคลุม

## Shopee Open API (dormant)

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
- YouTube: `stacks.shorts_factory.youtube.*` (OAuth ตัวเดียวกับ shorts-factory)
- mimo: `shared.llm.mimo_api_key`
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
cd shopee-analyst && uv run --no-project --python 3.12 --with pytest --with openai==1.93.0 python -m pytest -q tests
```

Fake Shopee/Google server (ตรวจ signature, นับ `search` call), Telegram mock ที่ `notify._urllib_post`, mimo mock ที่ `clips._ask` — ไม่ยิงข้างนอก.
**ห้าม `ruff format` ทั้งโฟลเดอร์** — จะไปแก้สำเนา vendored `notify.py`/`mimo.py` แล้ว `test_shared_sync` แดง

## ข้อจำกัด

- API ไม่บอกจำนวน affiliate ที่โปรโมตสินค้าเดียวกัน — ต้องดูเองจาก TikTok/Reels
- ไม่ scrape เว็บ Shopee (เสี่ยงบล็อก + กระทบบัญชี affiliate)
- ต่อยอด: ผูก Sub ID กับรายงาน conversion (มีตารางใน `shorts-factory` Shop affiliate tracking แล้ว) เพื่อปรับคะแนนจากผลจริง
