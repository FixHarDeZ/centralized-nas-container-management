# lotto-picker — INDEX

สุ่มเลข 2 ตัว/3 ตัวแยกกัน ไม่ซ้ำ N งวดล่าสุด (ผลจาก GLO) + Telegram + ตรวจผล + สถิติย้อนหลังตั้งแต่ 2558 + ทดสอบย้อนหลัง + สไตล์ + บัญชี + สรุป AI. รายละเอียดเต็ม: `../README.md`

## สถานะ
- **2026-10-19 insights** (branch `feat/lotto-insights`): ประวัติลึก/ความถี่/backtest/สไตล์/บัญชี/ตรวจสลาก/ตัวช่วย 6 หลัก/สรุป mimo — 84+32+64 tests ผ่าน; ดู daily_log สำหรับสถานะ merge/deploy ล่าสุด
- ระบบ 2/3 ตัว **commit `1ca3560` เข้า main + push + deploy แล้ว (2026-10-16)**; NAS app healthy/nginx running, Basic Auth 401/200, exact asset hashes ตรง source, API settings/picks/stats แยกโหมดและสุ่มจริงทั้ง2/3ผ่าน
- แยก settings/history/stats/auto guards ตาม `digits=2|3`; legacy ไม่มี digits = 3. โหมด 2 ตัวเฉพาะ `last2`, pool 00–99, ตรวจตรงตัว /100, ตัดเลขกลับได้แต่ไม่ถือว่าถูก; 3 ตัวคง logic เดิม
- ตรวจรอบนี้: **85 stack tests (60 backend + 25 browser) + 64 repo tests ผ่าน**, JS/ruff/diff ผ่าน, independent backend+UI review approve. Warning เดียวมาจาก Starlette TestClient/AnyIO deprecation ใน test environment
- NAS JSON1 verified; backup ก่อน deploy `/data/backups/lotto-before-dual-20261016-121632.db` integrity ok; หลัง deploy ตรวจแล้ว saved sets/settings เดิมไม่เปลี่ยน, backup ยังอยู่, HTTPS proxy 401/200 + JS hash ผ่าน
- ปิดงาน 2/3 ตัว: native archive/remove worktree และลบ local branch `codex/lotto-two-three-digits` แล้ว; ไม่มี remote feature branch; primary main ตรง origin/main หลัง push บันทึกปิดงาน. `.agents/` เดิมไม่แตะต้อง
- UI redesign 2026-10-16 **commit `6e752db` เข้า main + push + deploy แล้ว**: ครีม/เขียว, bottom navigation 3 ส่วน, stepper/presets, ticket numbers, copy/saved state, ประวัติ/ผลรางวัลใหม่, dark mode + ปุ่ม 44px; API/DB/scheduler/auth เดิม
- ปิดงาน release: NAS app healthy/nginx running, noauth 401/auth 200, API settings/draws/picks/stats 200; SHA-256 index.html/app.js/style.css ตรง source `6e752db`; HTTPS proxy 401/200 และ app.js hash ตรง. ลบ active worktree และ branch `codex/lotto-mobile-ui` แล้ว (native archive เก็บ snapshot กู้คืนได้)
- Deploy guard: archive exclude `.env.deploy` + `secrets/vault.yaml`; ลบ `.env.deploy` เก่าที่เคยอยู่บน NAS แล้ว. ใช้ clean export ของ main + generated env/auth files ไม่ส่ง untracked `.agents/`
- ตรวจ UI รอบนี้: backend 21 + browser 15 = **36 passed**, JS syntax/ruff/diff สะอาด, independent review ผ่าน. Browser ใช้ local fixture server ไม่เรียก GLO/Telegram. คำสั่ง/flow ใน README; design/plan ใน `docs/superpowers/`
- สร้าง + deploy 2026-10-16 (`94c4bf6` + `757b49c`), verified บน NAS (401/200/healthy/Telegram) + external 401; push ทั้งสอง commit แล้วพร้อม release UI
- ค้าง: payload GLO ระหว่างจับสด `/tmp/glo-live/` บน NAS (เก็บ 16/10 14:30-16:30) → ทำ fixture
- Port 5073 (nginx basic auth) → DSM RP 15073 (สร้างแล้ว 16/10) + tile ใน homepage
- รอบจริงรอบแรก: ผลงวด 16/10 (poll 15:00+), auto pick แรก 31/10 20:00

## โครงไฟล์
- `app/analysis.py` pure: `CATEGORIES` (ไม่นับ near1), `frequency`/`chance_profile` (Binomial band, max/min ปกติ), `style_candidates` (quarter ของ pool, ties ตรงรอยตัดเก็บหมด), `backtest` (no lookahead, expected analytic, null variance `(k/|C|)²·|T|·q(1−q)`, z 2.58)
- `app/insight.py` facts (คีย์ไทย) → mimo → `check()` (ตัวเลขต้องอยู่ใน facts, `BANNED`, ต้องมี `DISCLAIMER`) → fallback `template()`; thread ต่อโหมด; kv `insight_2/3`
- `app/mimo.py` vendored จาก `shared/` (ห้ามแก้สำเนา); `requirements` เพิ่ม `openai==1.93.0`
- service ใหม่: `backfill_history`, `history`, `frequency`/`backtest` (`_cached` ต่องวดล่าสุด), `make_pick(style, stat_window)` คืน `reasons`/`candidates`, `ledger()` + `_resolve_draw` ±5 วัน, `check_ticket`
- DB ใหม่: ตาราง `ledger(draw_date,label,tickets json,cost,prize)`; kv `history_status`, `history_skipped`, `prize_amounts`, `insight_2/3`
- `tests/test_analysis.py`, `test_insights_api.py`, `test_ui_insights_browser.py` (opt-in, FastAPI จริง + DB จำลอง 60 งวด)
- `app/lotto.py` logic ล้วน (parse, is_complete, excluded/pool/pick, score, next_expected_draw, thai_date)
- `app/glo.py` client GLO (urllib, UA ใส่เอง)
- `app/service.py` sync/backfill, make_pick, score_pending, stats — fetcher เป็น parameter ให้เทสต์
- `app/db.py` SQLite `/data/lotto.db`: `draws(date, prizes json)`, `nodraw(date)`, `picks(... based_on, result_draw, result)`, `kv` (settings, latest_seen, auto_pick_target)
- `app/messages.py` ข้อความ + Notifier; `app/notify.py` vendored จาก `shared/` ห้ามแก้ตรง
- `app/static/` dashboard vanilla JS, mode profiles แยก drafts/results/saved state, mutation locks และ async read guards
- `tests/test_modes_api.py`, `test_digit_storage.py`, `test_messages.py`: แยกโหมด/legacy/SQL limit/API/ข้อความ/last2 repair
- `tests/test_ui_browser.py` opt-in `LOTTO_UI_BROWSER=1` ต้องมี Python Playwright + Chrome; tests ปกติไม่ต้องมี browser packages

## ค่าเริ่มต้น settings
- ทั้งสองโหมดเพิ่ม `style=random`, `stat_window=0` (0 = ประวัติทั้งหมด); pick เก่าที่ไม่มี style = random
- 3 ตัว: kv `settings`, digits=3, draws=2, picks=5, scope=all, permute=false, notify=true (ค่าเดิมไม่เปลี่ยน)
- 2 ตัว: kv `settings_2`, digits=2, draws=2, picks=5, scope=last2, permute=false, notify=false (เปิดเองใน UI)
- GET settings/picks/stats รับ `?digits=2|3` default3; PUT/POST mode อยู่ใน body/settings. Auto guards: `auto_pick_target` / `auto_pick_target_2`

## Gotchas
- **history backfill ห้ามรันก่อน poll แรก** (first-boot check ดูตารางว่าง); walk 45 วันของ sync ใช้กับประวัติลึกไม่ได้ (งดออก 2563)
- ก่อน 2015-09-01 GLO ส่ง last3b 4 ตัว ไม่มี last3f → ไม่เก็บ ห้ามปน
- สลาก 6 หลักไม่มีรางวัล “3 ตัวท้ายรางวัลที่ 1” — `targets` 3 ตัวใช้กับการตรวจเลขที่สุ่มเท่านั้น ห้ามเอาไปบอกว่าสลากถูก
- Playwright element screenshot ของ element สูงๆ วาด skip-link/เมนูล่างทับกลางภาพ = artifact (ตำแหน่งจริง -80px)
- สรุป AI: ถ้าใส่คีย์อังกฤษใน facts โมเดลจะลอกชื่อฟิลด์ลงข้อความ
- ใหม่: complete draw ต้องมี last2 ครบ1เลขด้วย โดยไม่ใส่ใน EXPECTED_COUNTS ที่ใช้สร้าง scope3. งวด legacy ที่ขาด last2 ซ่อมเฉพาะ field นี้จากผลครบ/วันที่ตรง ไม่เปลี่ยน3prizes/ผลตรวจหรือประกาศงวดเก่า; pending2 รอข้อมูลถ้า target ยังไม่มีlast2
- DB schema เดิม; settings JSON เก็บ digits และ SQL filter ก่อน LIMIT. ห้ามย้าย legacy ไป2ตัวหรือรวมสถิติข้ามโหมด
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
