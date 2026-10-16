# lotto-picker — INDEX

สุ่มเลขท้าย 3 ตัวไม่ซ้ำ N งวดล่าสุด (ผลจาก GLO) + Telegram + ตรวจผล. รายละเอียดเต็ม: `../README.md`

## สถานะ
- UI redesign 2026-10-16 เสร็จใน worktree branch `codex/lotto-mobile-ui` (ยังไม่ commit/push/deploy): ครีม/เขียว, bottom navigation 3 ส่วน, stepper/presets, ticket numbers, copy/saved state, ประวัติ/ผลรางวัลใหม่, dark mode + ปุ่ม 44px; API/DB/scheduler/auth เดิม
- ตรวจ UI รอบนี้: backend 21 + browser 15 = **36 passed**, JS syntax/ruff/diff สะอาด, independent review ผ่าน. Browser ใช้ local fixture server ไม่เรียก GLO/Telegram. คำสั่ง/flow ใน README; design/plan ใน `docs/superpowers/`
- สร้าง + deploy 2026-10-16 (`94c4bf6` + commit `feat(homepage): add Lotto Picker tile`), verified บน NAS (401/200/healthy/Telegram) + external 401. **ยังไม่ push**
- ค้าง: payload GLO ระหว่างจับสด `/tmp/glo-live/` บน NAS (เก็บ 16/10 14:30-16:30) → ทำ fixture
- Port 5073 (nginx basic auth) → DSM RP 15073 (สร้างแล้ว 16/10) + tile ใน homepage
- รอบจริงรอบแรก: ผลงวด 16/10 (poll 15:00+), auto pick แรก 31/10 20:00

## โครงไฟล์
- `app/lotto.py` logic ล้วน (parse, is_complete, excluded/pool/pick, score, next_expected_draw, thai_date)
- `app/glo.py` client GLO (urllib, UA ใส่เอง)
- `app/service.py` sync/backfill, make_pick, score_pending, stats — fetcher เป็น parameter ให้เทสต์
- `app/db.py` SQLite `/data/lotto.db`: `draws(date, prizes json)`, `nodraw(date)`, `picks(... based_on, result_draw, result)`, `kv` (settings, latest_seen, auto_pick_target)
- `app/messages.py` ข้อความ + Notifier; `app/notify.py` vendored จาก `shared/` ห้ามแก้ตรง
- `app/static/` dashboard vanilla JS
- `tests/test_ui_browser.py` opt-in `LOTTO_UI_BROWSER=1` ต้องมี Python Playwright + Chrome; tests ปกติไม่ต้องมี browser packages

## ค่าเริ่มต้น settings (kv `settings`)
draws=2, picks=5, scope=all, permute=false, notify=true

## Gotchas
- rayriffy API ตาย (DNS) — ใช้ GLO `getLatestLottery` / `getLotteryResult`
- GLO ปล่อยผลระหว่างจับ → เก็บเฉพาะงวดครบ `EXPECTED_COUNTS` **และทุกค่าเป็นตัวเลขยาวตาม `DIGITS`** (กัน placeholder ระหว่างจับ — ยังไม่เคยเห็น payload ตอนจับสดจริง), จด `latest_seen` ทันที
- `nodraw` เป็น negative cache ถาวร: ถ้า GLO ตอบ null ผิดพลาดในวันที่มีงวดจริง งวดนั้นจะหลุด backfill ตลอด (แก้: ลบแถวใน `nodraw`)
- `auto_pick` เป็น cron เวลาเดียว ไม่มี catch-up: container ดับตอน 20:00 = งวดนั้นไม่มีเลขอัตโนมัติ
- start ครั้งแรก (DB ว่าง) ไม่ประกาศงวดล่าสุด
- `id` ซ้ำใน HTML (`picks` input vs list) เคยทำให้ประวัติไม่ขึ้น → list ใช้ `picks-list`
- UI บันทึกด้วย settings snapshot จากผลสุ่ม ป้องกันกดสุ่มระหว่างบันทึก; notify-only ต้อง GET settings ล่าสุดก่อน PUT เพื่อไม่ทับค่าจากอีกเครื่อง และต้องคืน checkbox เมื่อบันทึกล้มเหลว
- `notify` ปิดทั้งการสร้างเลขอัตโนมัติและส่งแจ้งเตือน; manual sync ตอบ 200 ได้แม้ upstream ล้มเหลว จึงใช้ข้อความว่าแสดงผลล่าสุดที่เก็บไว้
- งวดที่เลื่อนไปวันนอก `CANDIDATE_DAYS` จะหลุด backfill (ยังไม่เคยเจอ)

## ยังไม่ทำ / ไอเดีย
- LINE ยังไม่ผูก (env มีช่องรอ)
- ไม่มี SQLite backup รายวัน (ผลรางวัลดึงใหม่ได้ เสียแค่ประวัติ picks)
