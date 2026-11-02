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
