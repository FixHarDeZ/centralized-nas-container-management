# shopee-analyst — daily log

## 2026-11-02 — สร้าง stack จากโค้ดแชท claude.ai
- ที่มา: zip `shopee-affiliate-analyst` (GitHub Actions + stdlib script). ย้ายเป็น stack NAS: ตัด git-commit history, snapshot ลง volume `/data`, scheduler เป็น sleep loop ใน container (`SLOTS` 06:00,12:00,16:00 Bangkok), Telegram ผ่าน `shared/notify.py`
- เพิ่ม: ไม่มี Shopee key = skip เงียบ (ของเดิมจะแจ้ง error ทุกรอบ), `--probe`, `--once`, heartbeat healthcheck, write_json atomic
- Telegram: ใช้ `stacks.news_feed.telegram.*` (เช็คแล้ว chat_id ตรงกับที่ผู้ใช้วางมา — เทียบเป็น bool ไม่พิมพ์ค่า). token ที่วางในแชทไม่ได้ใช้ → แนะนำ revoke
- ทดสอบ Shopee ไทยจริง: `open-api.affiliate.shopee.co.th/graphql` ตอบ `error [10035]` กับคีย์ปลอม (ทั้งจาก Mac และจาก container บน NAS) = URL ถูก, ยังพิสูจน์ signature/schema ไม่ได้จนกว่าจะมีคีย์จริง. ชื่อฟิลด์/sortType เช็คกับ source ของ `saapi` 0.2 (PyPI)
- Tests: 14 passed (py3.12, fake Shopee server ตรวจ signature). Repo: doc drift สะอาด, `make check` ผ่าน
- Deploy: `deploy.sh -s shopee-analyst -y` → healthy, `--telegram-test` ส่งถึง, `--once` = skip (exit 0)
- ค้าง: Shopee App ID/Secret (ผู้ใช้), verify ฟิลด์ไทยด้วย `--probe`
- ต่อมา: ผู้ใช้เปิดหน้า open_api แล้วเจอว่าบัญชีไม่ได้รับสิทธิ์ (AppID `--`) → แนะนำขอสิทธิ์ผ่าน 'ติดต่อเรา'; ระหว่างนี้ไม่ scrape

## 2026-11-02 (ต่อ) — แหล่ง YouTube TH แทน Open API
- ทดลองแหล่งฟรี: Google Trends TH RSS = ข่าว/กีฬาล้วน (เมสซี่, ราคาน้ำมัน) ไม่มีสินค้า, Google autocomplete = noise → ตัดทิ้ง. YouTube search `ป้ายยา`/`ของดีบอกต่อ`/`รีวิว shopee` ได้คลิปสินค้าไทยจริงพร้อมวิว → เลือกตัวนี้
- `/shop/revenue` บน NAS ยังไม่มี report import เลย (conversions/imports = 0) → ส่วน "ยอดขายของเราเอง" รอ CSV จากผู้ใช้
- เขียน `app/clips.py` + `tests/test_clips.py` (24 tests รวม). ค้นวันละรอบ (โควตาแชร์ shorts-factory), mimo grounded
- เจอ `mimo-v2.5-pro` → 400 `Unsupported model` (catalog เหลือ v2.6-flash/pro) → stack นี้ใช้ `mimo-v2.6-flash`; lotto-picker ยังฟิก v2.5 ไม่ได้แก้รอบนี้
- พลาด: `ruff format .` ในโฟลเดอร์ stack ไปแก้ vendored `mimo.py` — คืนด้วย cp จาก shared/ ก่อน commit
- commit `a9a3467` push แล้ว; deploy → healthy; `--once` บน NAS: tracked 97 / ranked 76 / sent 5, mimo 50 วิ, units 402, ส่ง Telegram สำเร็จ. deploy record = `0df3343` (tree มี ai-deck pin bump ของ session อื่นค้าง ไม่ได้แตะ)
- ค้าง: ผู้ใช้ยืนยันเห็นข้อความใน chat bot news-feed, CSV รายงาน conversion, bot แยกสำหรับวางลิงก์จากมือถือ, แก้ MIMO_MODEL ของ lotto-picker
