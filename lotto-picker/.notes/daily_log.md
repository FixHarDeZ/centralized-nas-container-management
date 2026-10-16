# lotto-picker — daily log

## 2026-10-16 — สร้าง stack
- ที่มา: สคริปต์จาก Gemini ใช้ `lotto.api.rayriffy.com` → DNS ตาย (เช็คทั้ง Mac และ NAS) เปลี่ยนไปใช้ GLO `getLatestLottery`/`getLotteryResult` (ไม่มีคีย์, วันไม่มีงวด = `response: null`, ยืนยัน 17 ม.ค./2 พ.ค. 2569 เป็นวันเลื่อน)
- ผู้ใช้เลือก: stack ใหม่, เว็บ + แจ้งเตือน, N=2 K=5, ทำครบ 4 ส่วนเสริม (ส่งเลขล่วงหน้า/ตรวจผล/ตัดโต๊ด/เลือกรางวัล), เปิดจากข้างนอก
- ทำ: FastAPI+SQLite+APScheduler, nginx basic auth 5073, vault `stacks.lotto_picker.dashboard.*` (ใหม่) + Telegram ยืม `stacks.news_feed.telegram.*`
- บั๊กที่เจอระหว่างทำ: (1) default arg `fetch_latest=glo.latest` ผูกตอน define → mock ไม่ติด แก้เป็น resolve ตอนเรียก (2) `id="picks"` ซ้ำ input/list (3) start ครั้งแรกจะประกาศงวดเก่า → first boot เก็บเงียบ
- ตรวจแล้ว: เทสต์ stack 16 ผ่าน, repo tests 63 ผ่าน, doc drift ไม่มี, `make check` ผ่าน; บนเครื่องจริง backfill 5 งวดจาก GLO pool 429; deploy NAS: noauth 401 / auth 200 / healthy / Telegram test ส่งได้
- เพิ่มหลังรีวิว: `is_complete` เช็คตัวเลข+ความยาว (`DIGITS`) ไม่ใช่แค่จำนวน, เทสต์ `auto_pick` 4 เคส → stack tests 21 ผ่าน, ruff สะอาด
- สถานะ: commit `feat(lotto-picker): new stack` (amend รวมรอบรีวิว) deploy + verified บน NAS, **ยังไม่ push**
- ค้าง: ผู้ใช้ต้องสร้าง DSM Reverse Proxy `https://<domain>:15073` → `http://localhost:5073` เอง (+ เช็ค router forward 15073); ยังไม่เห็นรอบ `poll_results`/`auto_pick` จริง (16/10 เป็นวันออกรางวัล: auto pick รอบนี้ไม่มีเพราะ deploy หลัง 20:00 ของ 15/10, ผลงวด 16/10 จะ poll+ประกาศ 15:00+ วันนี้ = รอบจริงรอบแรก)

## 2026-10-16 (ต่อ)
- ผู้ใช้สร้าง DSM RP 15073 เสร็จแล้ว
- เพิ่ม tile ใน homepage (deploy แล้ว)
- ปิดงาน: commits `94c4bf6` (stack) + `feat(homepage): add Lotto Picker tile` (commit ถัดไป) — deploy ทั้งคู่แล้ว, **ยังไม่ push**. External `:15073` ตอบ 401 (RP ต่อถึง nginx)
- ค้างรอบหน้า: (1) ดูผลงวด 16/10 ใน Telegram เย็นนี้ = รอบจริงรอบแรก (2) NAS เก็บ payload GLO ระหว่างจับสดที่ `/tmp/glo-live/latest_HHMM.json` (14:30-16:30 ทุก 10 นาที) → ถ้าเห็นทรงข้อมูลตอนกำลังจับ เอามาทำ fixture + เทสต์ `is_complete` (3) auto pick แรก 31/10 20:00
