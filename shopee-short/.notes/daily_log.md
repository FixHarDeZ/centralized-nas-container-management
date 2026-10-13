# shopee-short daily log

## 2026-10-12 — รีวิว prompt ของ Hermes + เริ่ม Phase 0

**ทำ**
- รีวิว prompt `shopee-short` ที่ Hermes เขียน → เขียนใหม่เป็นแผนแบบมีด่าน `docs/PLAN.md` (Phase 0 verify → Phase 1 ทดลองมือ → Phase 2 stack)
- เหตุผลหลัก: ลิงก์ใน Shorts กดไม่ได้ (YouTube Help) แผนเดิม "affiliate link ใน description + pin comment" ทำเงินไม่ได้; Shopping tag ต้อง YPP ก่อน; Hermes ติดป้าย "verify แล้ว" ให้ข้อมูลที่ยังเป็นคำบอกเล่า
- ตรวจพอร์ตบน NAS จริง: 5067/15067 ใช้ไม่ได้ (15067 = RP ค้าง) → จอง **5073/15073**
- แก้ด่าน subId: `conversionReport` ว่างจนมี order → เช็คโครงสร้างผ่าน `schema` + เช็คคลิกใน dashboard แทน
- เขียน `scripts/shopee_probe.py` + 6 เทสต์ (TDD) ยิง endpoint `.co.th` ด้วย creds ปลอม → `10020 Invalid Credential` = endpoint ถูก
- branch `feature/shopee-short`

- **ผล Phase 0 ข้อ 1: บัญชีไม่มีสิทธิ์ Open API** — ต้อง "ติดต่อเรา" ขอสิทธิ์ → Phase 1 ใช้ fallback (custom link + feed) probe ยังใช้ได้เมื่อได้สิทธิ์

**ยังไม่ทำ / ค้าง**
- ผู้ใช้: กรอกข้อมูลการชำระเงิน/ภาษี → ติดต่อ Shopee ขอสิทธิ์ Open API; ทดลอง custom link + Sub ID `probe`
- README root drift (5057 my-secretary) ยังไม่แก้
- ⚠️ `:15069` RP → dupe-sweeper (stack ที่ควร LAN only) — รอผู้ใช้ตัดสินว่าลบ RP entry ไหม
- ยังไม่ commit

## 2026-10-13 — /shop ใน shorts-factory (ADR 0015)

- ผู้ใช้เลือกทางไม่ใช้ API: ส่งรูป+ข้อความเข้าบอท ได้คลิปกลับมาโพสต์เอง; ทำ preview layout ให้ดูก่อน → ผู้ใช้โอเค + ขอเสียงผู้หญิง
- สร้างเป็นโหมด `/shop` ใน shorts-factory (รายละเอียด/ผลทดสอบอยู่ใน `shorts-factory/.notes/daily_log.md`)
- PLAN.md + 00_INDEX แก้บรรทัด "ห้ามใช้ shorts-factory" ให้ตรงกับ ADR 0015

**ค้าง**: commit + deploy shorts-factory (รอผู้ใช้อนุญาต), ทดลองโพสต์จริงแล้วจดลง `experiment.md`, ติดต่อ Shopee ขอ Open API
