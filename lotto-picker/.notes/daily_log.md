# lotto-picker — daily log

## 2026-10-20 — แจ้งเตือนถูกรางวัล (Telegram + ป้ายในเว็บ)
- ผู้ใช้ถามว่ามีแจ้งเตือนถูกรางวัลไหม → เดิมมีแค่ ✅ ในข้อความผลรางวัลปกติ, สลาก 6 หลักในบัญชีไม่แจ้ง, user อื่นไม่ได้อะไร. ผู้ใช้เลือก: (1) ข้อความ 🎉 แยก (2) สลากในบัญชีแจ้งด้วย (3) user อื่น = ป้ายในเว็บ
- ทำ: `service.wins(user)` (งวดล่าสุด: picks ที่ hit + ledger status won), `pending_win_alerts`/`mark_wins_alerted` (kv `win_alerted`), `main.send_win_alerts()` ท้าย `poll_results` ทุกรอบ (แยก `announce()` ออกมา); สลากแจ้งเสมอ, picks ตาม notify ของโหมด แต่ mark ทั้งหมด; owner เพิ่ม/แก้ ledger หลังผลออก = mark เฉพาะสลาก; `messages.win()` (+ ขึ้นเงินภายใน 2 ปี); `GET /api/wins` + ป้าย `#win-banner` ซ่อนได้ต่อ user+งวด (localStorage)
- บั๊กที่จับได้ระหว่างทำ: `let wins/me` ประกาศท้ายไฟล์ แต่ `loadWins()` ถูกเรียกตอน startup → TDZ ReferenceError ถูก catch กลืน ป้ายไม่ขึ้นเลย + promise `/api/wins` ที่สร้างไว้แล้ว reject ไม่มีคนรับ (pageerror ใน browser tests เก่า 25 ตัว) → ย้าย state ขึ้นบนสุด
- เทสต์เก่า `test_poll_notifies_only_enabled_mode...` แก้ตั้งใจ: ตอนนี้ได้ 2 ข้อความ (ผล + 🎉) และ stub `insight.start` (thread แข่งกัน)
- ตรวจ: stack **133 passed** (รวม browser; ใหม่ `tests/test_wins.py` 7 + browser 1), repo 64, ruff สะอาด; screenshot ป้าย 390px light/dark
- Release: commit `e49a6b1` push แล้ว; backup `/data/backups/lotto-before-wins-20261020.db` (12 picks/1 ledger) → deploy 11:32 จาก clean export
- Verify NAS: healthy, noauth 401, hash index/app.js/style.css ตรง, `/api/wins` owner/Pookzii ตอบงวด 16 ต.ค. ว่าง, startup poll รัน `send_win_alerts` ไม่มี error ไม่มีข้อความหลุด (ไม่มีชุดไหนถูกงวด 16 ต.ค.)
- **ยังไม่เห็นข้อความ 🎉 ผ่าน Telegram จริง** — รอบแรกที่เป็นไปได้: งวด 1 พ.ย. (fixhardez มีรายการบัญชี 2 ใบรอผลอยู่แล้ว)

## 2026-10-19 — ปิดงาน
- ทั้งสองงานวันนี้ (insights `ec2c939` + แยก user `557b67a`) merge main, push, deploy, verified บน NAS แล้ว; notes commit `818b611`, `88bbe45`
- ไม่มี branch/worktree ค้าง; scratch DB/screenshot อยู่ใน scratchpad ของ session เท่านั้น
- ค้าง: daily SQLite backup (picks + ledger ดึงใหม่ไม่ได้), GLO live fixture `/tmp/glo-live/`, LINE; รอบจริงแรก: auto pick 31/10 20:00, ผล + สรุปสถิติ 1/11

## 2026-10-19 (ต่อ) — แยกข้อมูลต่อ user ที่ login nginx
- ผู้ใช้ขอแยกข้อมูลตาม basic auth user. `.htpasswd` มี 3 คน: `lotto` (vault), `fixhardez`, `Pookzii`. ถาม 2 ข้อ: ข้อมูลเดิม → **fixhardez**, เลขอัตโนมัติ/Telegram → **เฉพาะ fixhardez**
- ทำ: nginx `proxy_set_header X-Remote-User $remote_user` (เขียนทับของ client), `main.current_user` (ไม่มี header = owner), คอลัมน์ `username` ใน picks/ledger (migration ใน `db.init()` เติม owner ให้แถวเก่า), kv `settings:<user>` (owner ใช้ key เดิม), `LOTTO_OWNER=fixhardez` literal; คนอื่น notify บังคับ false + UI ซ่อนส่วน automation; ข้อความผลรางวัลรวมเฉพาะเลขของ owner; `/api/me` + chip ชื่อผู้ใช้บน header
- ตรวจ: stack **93 + browser 33 = 125 passed** (ใหม่ `tests/test_users.py` 8 + browser 1), repo 64, ruff/`make check` ผ่าน
- Release: commit `557b67a`; backup `/data/backups/lotto-before-users-20261019.db` (12 picks/0 ledger) → deploy 11:07 จาก clean export (`.htpasswd` local = NAS hash เดียวกัน)
- Verify NAS: migration `fixhardez` 12 แถว; fixhardez picks 12 notify true, Pookzii 0 notify false; nginx as `lotto` → `/api/me` = lotto; **ส่ง `X-Remote-User: fixhardez` ปลอมด้วย creds lotto ได้ข้อมูลของ lotto (`[]`)** = nginx เขียนทับจริง; noauth 401, app.js hash ตรง, healthy

## 2026-10-19 — สถิติย้อนหลัง / ทดสอบย้อนหลัง / สไตล์ / บัญชี / ตรวจสลาก / สรุป AI
- ผู้ใช้ถามว่าให้ AI วิเคราะห์เลขหวังรางวัลที่ 1 + ให้คะแนนเลขจาก stat ได้ไหม → อธิบายตรงๆ ว่าสถิติทำนายไม่ได้ เสนอ 6 ข้อแบบไม่หลอก ผู้ใช้เลือกทำครบ (1 ประวัติลึก → 2 ความถี่ → 4 backtest → 3 สไตล์ → 5 บัญชี → 6 ตัวช่วย 6 หลัก → AI สรุป)
- GLO probe: รูปแบบรางวัลปัจจุบันเริ่ม **2015-09-01** (ก่อนนั้น last3b 4 ตัว ไม่มี last3f) และทุก payload มี `price` ต่อรางวัล → `HISTORY_START`, `parse_amounts`, kv `prize_amounts`
- `service.backfill_history` (lock แยก, หลัง poll แรก + 04:30) วัดจริงจาก Mac: **265 งวด, 1,508 probes, 12.3 นาที, skipped 0**; รอบสองยิงทุกวันของเดือน <2 งวด — ม.ค. ทุกปีโดนเพราะงวด 30 ธ.ค. (ครั้งเดียว ~250 probes)
- `app/analysis.py`: ความถี่ + ช่วง Binomial/ค่าสูงสุดปกติ, สไตล์ quarter-of-pool ใช้ร่วมกับ backtest (no lookahead, expected แบบ analytic). ผลจริง 2 ตัว: ออกบ่อยสุด 7 ครั้ง vs สุ่มล้วนปกติ 7–9, backtest 241 งวดไม่มีสไตล์ไหนมีนัยสำคัญ (z สูงสุด 1.71)
- Review แก้ 2 จุด: (1) z-score ใช้ variance ผิด (`k·p(1−p)` ของจำนวนจริง) ทำให้ z เล็ก 2.5–8 เท่า → ใช้ null variance ของค่าคาดหวัง มีเทสต์ bias 15% ที่สูตรเก่าได้ z 1.1 สูตรใหม่ 3.8 (2) บัญชีจับวันตามปฏิทิน ไม่ match งวด 30 ธ.ค. → `_resolve_draw` ±5 วัน
- สรุป AI: mimo จริงตอบ 20–75 วิ ผ่าน `check()` ทั้ง 2 โหมด; รอบแรกหลุดชื่อฟิลด์อังกฤษ (`max_typical`) → เปลี่ยนคีย์ facts เป็นไทย + สั่งห้าม
- UI: เมนู 5 ส่วน, heatmap 00–99, อันดับ (ค้างนานไม่รวมเลขที่ไม่เคยออก เพราะอยู่ในออกน้อยแล้ว), กราฟส่วนต่างสะสม, ฟอร์มบัญชี, ตรวจสลาก; แก้ป้าย 6 หลักที่บอกผิดว่า `xxx123` ถูก “3 ตัวท้ายรางวัลที่ 1” (สลากไม่มีรางวัลนี้)
- ตรวจ: stack **84 passed** + browser **32 passed** (เดิม 25 + ใหม่ 7 รัน FastAPI จริงบน DB จำลอง) + repo **64 passed**; ruff สะอาด (ยกเว้น vendored `mimo.py` ที่ shared/ เองก็ติด UP041 อยู่แล้ว); `make check` ผ่าน; screenshot จริงบนข้อมูล 265 งวด light/dark
- **Release**: commit `ec2c939` fast-forward เข้า main + push origin/main, ลบ branch แล้ว. Backup ก่อน deploy `/data/backups/lotto-before-insights-20261019.db` integrity ok (6 draws/12 picks)
- Deploy 10:19 (นอกช่วงจับ 15–20) จาก clean `git archive main` + generated env/htpasswd (ไม่ส่ง `.agents/`): image rebuild มี openai 1.93.0, healthy, nginx up
- Verify NAS: noauth 401, auth 200 (LAN + external `:15073`), SHA-256 index/app.js/style.css ตรง source; picks 3 ตัวยังครบ 12, settings เดิม + style/stat_window default; ไม่มี Telegram ตอน startup; backfill **done 10:32 = 265 งวด 1,489 probes ~13 นาที**; frequency/backtest ตรงกับรันบน Mac; สรุป mimo บน NAS ผ่าน check (13 วิ); หน่วยความจำสูงสุดที่เห็น 104 MiB / 256m
- ค้าง (เดิม): GLO live fixture `/tmp/glo-live/`, LINE, daily SQLite backup (ตอนนี้ ledger เป็นข้อมูลที่ดึงใหม่ไม่ได้แล้ว → backup สำคัญขึ้น); รอบจริงแรกของข้อความสรุปหลังผลออก = งวด 1 พ.ย. 2569

## 2026-10-16 — ปิดงานระบบ 2/3 ตัว
- Source commit `1ca3560` fast-forward เข้า `main` และ push origin/main แล้ว; deploy ด้วย `scripts/deploy.sh -s lotto-picker -y` จาก clean tracked export + generated env/auth files ไม่ส่ง untracked `.agents/` หรือ workstation credentials
- Rebuild/restart เฉพาะ lotto-picker app/nginx, volume SQLite เดิม. Verified app running/healthy, nginx running; noauth401/auth200; SHA-256 HTML/JS/CSS ตรง source `1ca3560`
- Production GET settings/picks/stats สำหรับ digits2และ3 =200; POST /api/pick ทั้ง2/3สุ่มได้5เลข จำนวนหลัก/leadingzero format/exclusions/settingsถูกต้อง, 2ตัวscope last2 และnotify=false. Smoke สุ่มอย่างเดียว ไม่บันทึกเลขทดสอบลงประวัติ
- ตรวจ preservation หลัง deploy: saved sets/settings เดิมไม่เปลี่ยน และจำนวนdrawsไม่ลด; backup `/data/backups/lotto-before-dual-20261016-121632.db` ยังอยู่. Public HTTPS proxy noauth401/auth200 และ JS hash ตรง
- SSH หลุด255ระหว่างตรวจไฟล์ต้องห้ามท้ายสุดหลัง health/API/preservation ผ่าน → retry เฉพาะ check ที่เหลือสำเร็จ; ไม่มี `.env.deploy` หรือ plaintext `secrets/vault.yaml` บน NAS. `refs/deploy/lotto-picker` = source `1ca3560`
- Native worktree archive/remove สำเร็จ (snapshot กู้คืนได้), ลบ local branch `codex/lotto-two-three-digits` แล้ว; ไม่สร้าง remote feature branch. ไม่แตะ worktreeอื่นหรือ `.agents/` เดิม
- อัปเดตและตรวจ memory ทั้ง `daily_log.md` / `00_INDEX.md` พร้อมปิด plan; บันทึกปิดงาน commit/push ตามหลัง source ไม่มี runtime changes. Tests/review: **85 stack +64 repo passed**, independent spec/quality approve
- งานที่ขอครบแล้ว; backlog เดิม GLO live fixture/LINE/daily backup ไม่อยู่ในขอบเขตรอบนี้

## 2026-10-16 — ระบบสุ่ม 2 ตัว / 3 ตัวแยกกัน
- ผู้ใช้สั่งเพิ่มระบบสุ่มแยก 2/3 ตัว พร้อม commit main/push/deploy/ลบ worktree+branch และปิดงานอัตโนมัติ
- เพิ่ม mode selector มือถือ, draft/result/saved state แยก, ประวัติ/สถิติ/notification settings แยก; ป้องกัน mutation ข้ามโหมดและ async GET เก่าทับโหมดใหม่
- Backend เพิ่ม `digits=2|3` default3, key settings_2 (notify=false เริ่มต้น) แยกจาก settings เดิม; SQL mode filter ก่อน LIMIT; ไม่เปลี่ยน schema/ลบข้อมูลเดิม, legacy ไม่มีdigitsถือเป็น3
- 2 ตัวใช้ official last2 เท่านั้น, 00–99/leading zeros, optional reverse exclusion, scoring last2 ตรงตัวเท่านั้น และ expected /100; 3 ตัว /1000 และ scope/scoring เดิม
- API validation ใช้ ASCII จำนวนหลักตรงโหมด; auto pick/ผลรางวัลแยก mode+stats, guards auto_pick_target เดิม / auto_pick_target_2 ใหม่, process lock กัน auto ซ้ำพร้อมกัน
- Complete draw ต้องมี last2 ครบ; cache legacy ขาด last2 ซ่อมเฉพาะ field นี้ด้วย payload ครบ/วันที่ตรง ไม่แตะ 3 prizes/results ไม่ประกาศงวดเก่า และไม่ตรวจ2เป็นแพ้ระหว่างรอข้อมูล
- TDD: เห็น fail ก่อนทำทั้ง pure/db/service, API/auto/messages และ browser modes; ตรวจรวม **85 passed (36.32s; backend60 + browser25)**, repo **64 passed (1.10s)**, JS syntax/Ruff/diff ผ่าน. มี Starlette TestClient/AnyIO deprecation warning จาก dependency ของ test environment1รายการ
- Independent backend/API และ UI/spec/quality review approve ไม่มี actionable findings. ไม่ยิง GLO/Telegram จาก tests
- NAS JSON1 verified; สำรอง SQLite ด้วย backup API และ integrity_check=ok ที่ `/data/backups/lotto-before-dual-20261016-121632.db`; baseline 0 picks/5 draws/settings เดิม เพื่อ verify หลัง deploy
- อัปเดต README stack + root README/CLAUDE summary + design/plan + memory ทั้งสองไฟล์
- สถานะก่อน release: branch `codex/lotto-two-three-digits`, ยังไม่ commit/push/deploy รุ่นนี้; จะทำต่อครบตามคำสั่ง (backlog GLO live fixture/LINE/daily backup เดิมไม่เปลี่ยน)

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
