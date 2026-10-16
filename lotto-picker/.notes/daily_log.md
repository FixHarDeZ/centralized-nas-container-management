# lotto-picker — daily log

## 2026-10-16 — ปิดงาน release UI
- ตามคำสั่งผู้ใช้: commit `6e752db` รวม source/UI/docs/tests/deploy guard, fast-forward เข้า `main` และ push origin/main สำเร็จ (รวม commits stack/homepage เดิมที่ค้าง push)
- ตรวจซ้ำก่อนปล่อย: stack **36 passed (25.43s)**, repo **64 passed (0.87s)**; JS syntax, bash syntax, ruff และ diff ผ่าน
- Deploy ผ่าน `scripts/deploy.sh -s lotto-picker -y` จาก clean tracked export ของ main + generated per-stack env/nginx auth files; ไม่ส่ง `.agents/` ที่ untracked. Rebuild/restart เฉพาะ lotto-picker (app+nginx), volume SQLite เดิม
- Verify หลัง deploy: app running/healthy, nginx running; noauth 401; auth HTML/JS/CSS 200 พร้อม SHA-256 ตรง source `6e752db` ทุกไฟล์; read-only API settings/draws/picks/stats 200; HTTPS proxy noauth 401/auth 200 และ app.js hash ตรง
- Security cleanup: archive ไม่ส่ง workstation `.env.deploy` และ plaintext `secrets/vault.yaml` อีก; พบ `.env.deploy` เก่าบน NAS และลบแล้ว, plaintext vault ไม่พบ. ไม่แสดงค่า credentials ใน log
- Native archive/remove worktree สำเร็จ (มี snapshot กู้คืนได้); ลบ local branch `codex/lotto-mobile-ui` แล้ว. ไม่มี remote feature branch ที่สร้างในงานนี้. Primary checkout อยู่ `main`; `.agents/` เดิมไม่แตะต้อง
- อัปเดตและตรวจ `daily_log.md` + `00_INDEX.md` พร้อม plan release status; source `6e752db` deploy แล้ว, บันทึกปิดงาน commit/push ตามหลัง (ไม่มี runtime changes)
- งาน UI ไม่มีค้าง; GLO live fixture/รอบ auto pick/LINE/backup เป็น backlog เดิม

## 2026-10-16 — Redesign UI สำหรับมือถือ
- ผู้ใช้อนุมัติแนวแอปมือถือ ครีม/เขียวเข้ม เมนูล่าง 3 ส่วน (“สุ่มเลข / เลขที่บันทึก / ผลรางวัล”) และให้ทำต่อ
- แก้ `app/static/index.html`, `style.css`, `app.js`: stepper/presets, ตัวเลือกพับเก็บ, ticket numbers ใหญ่, copy, saved status, ประวัติพร้อมประเภทรางวัล, draw cards, ปุ่มอย่างน้อย 44px, safe area, dark mode, focus และ reduced motion; API/DB/งานตามเวลา/auth เดิม
- เพิ่ม request guards กันสุ่ม/บันทึกชนกัน, บันทึก generation settings snapshot, empty/error/retry, rollback notify เมื่อบันทึกไม่ได้, ยืนยันก่อนลบ; สลับเมนูกลับด้านบนหน้าเสมอ
- Independent review พบ notify-only ใช้ค่าเก่าอาจทับ settings จากอีกเครื่อง → แก้เป็น GET ล่าสุดก่อน PUT โดยไม่เปลี่ยนค่าที่ยังไม่ได้บันทึกในฟอร์ม; regression test เห็น fail ก่อนแก้และ pass หลังแก้. Re-review: spec/quality ผ่าน ไม่มีประเด็นค้าง
- ตรวจ: backend 21 + browser 15 = **36 passed (16.64s)**; `node --check`, ruff และ `git diff --check` ผ่าน. Browser ครอบคลุมสุ่ม/บันทึก/คัดลอก/ลบ/ตั้งค่า/โหลดใหม่หลัง error/เลขหมด/หลายเครื่อง/การสลับเมนู/จอ 320,390,768,1440px; ตรวจภาพ light/dark และมือถือ/desktop
- Test environment เดิมขาด apscheduler จึงใช้ venv ชั่วคราว `/tmp/lotto-picker-ui-venv` ลง requirements ของ stack + pytest/ruff/playwright; ไม่แก้ production dependencies. UI ใช้ fixture server ไม่มี scheduler/GLO/Telegram
- อัปเดต README + design/plan ใน `docs/superpowers/` และ memory ทั้งสองไฟล์
- ก่อน release: พบ `scripts/deploy.sh` ไม่ exclude `.env.deploy` ตามกฎ repo → เพิ่ม exclusion ทั้งไฟล์นี้และ plaintext `secrets/vault.yaml`; regression test ใช้ synthetic tar เห็น fail ก่อนแก้/ผ่านหลังแก้. Repo tests **64 passed**, bash syntax/ruff/diff ผ่าน
- สถานะ: แก้ใน native worktree branch `codex/lotto-mobile-ui`, **ยังไม่ commit/push/deploy**. NAS ยังคง UI เดิมที่ deploy ก่อนรอบนี้; งาน GLO live fixture / รอบ auto pick / LINE / backup ค้างตามรายการเดิม

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
