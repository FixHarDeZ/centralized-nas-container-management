# Daily Log

## 2026-07-13 — จ่ายค้างทั้งหมดทีเดียว + noti ยินดีผ่านโปร + refactor + UI polish

**4 งาน:**

1. **Pay-all ค้างจ่าย:**
   - `POST /api/employees/{id}/daily-payments/pay-all?paid_by=` — จ่ายทุกวันค้างทั้ง window โปร (start→today, cap ก่อน `monthly_start_date`/`end_date`, ข้ามวันขาด+วันที่จ่ายแล้วรวม override amount), amount=rate×frac, LINE สรุปครั้งเดียว (`notify_daily_pay_all` + i18n key `daily_pay_all` ครบ 4 ภาษา). guard 400 ถ้า active แท้ (ไม่เคยมี daily window). UI: ปุ่ม "จ่ายค้างทั้งหมด" (`payAllDaily`) + payer select ใน bar สีเขียว (`.pay-all-bar`) ท้าย section จ่ายรายวัน + badge จำนวนวันค้างบน header.
   - รายเดือน: alert ค้างจ่าย >1 รอบ มีปุ่ม "จ่ายทุกรอบที่ค้าง" (`payAllPeriods` — loop toggle เดิมทีละ period, payer เดียวกัน).
2. **Noti ยินดีผ่านโปร:** `pass_probation` endpoint เรียก `line_notify.notify_pass_probation` — ไทย + บล็อกภาษาแม่บ้าน (`i18n.pass_probation_block`, dict `_PASS_PROBATION` แยกจาก `_MSG` เพราะมี sub-line: รอบจ่าย biweekly/monthly, วันหยุด monthly/sunday, tail "ยังจ่ายรายวันถึงสิ้นเดือน" เมื่อ pass_date < anchor). วันที่ในบล็อกแปลใช้ numeric `DD/MM/YYYY` (ไทยใช้ชื่อเดือน พ.ศ.). my/lo/km machine-generated ยังไม่ผ่าน native review.
3. **Refactor main.py:** `_fetch_emp(conn,id)` fetch-or-404 (แทน ~14 จุด), `_anchor_of(emp)` (แทน 7 จุด), `_compute_period_amount` เป็น single source ของยอดต่อ period (get_payments เลิกคำนวณเอง) + **แก้ bug: toggle/LINE webhook แจ้งยอด period 2 ของ `payment_schedule='monthly'` เป็นครึ่งเดียว** (ไม่รู้จัก schedule มาก่อน — จอแสดงถูกแต่ notify ผิด).
4. **UI polish:** view entrance animation (`#app.view-enter`, respect reduced-motion, เฉพาะ route change — refresh ในหน้าไม่ animate), ambient radial gradient background, navbar glass (`color-mix` + fallback), `.btn-primary` gradient+shadow, `.btn-success` token-based. cache-bust `?v=20260714` ทั้ง css+js.

**Test:** `tests/test_pay_all_and_pass_notify.py` ใหม่ 6 เคส (pay-all จ่ายเฉพาะวันค้าง/idempotent/reject active, notify ถูกเรียกพร้อม anchor, `_compute_period_amount` monthly vs biweekly, i18n blocks) — รวม 54 passed. Smoke จริงผ่าน TestClient: ข้อความ LINE ไทย+พม่า render ถูก.

**ไฟล์:** `main.py`, `line_notify.py`, `i18n.py`, `static/app.js`, `static/style.css`, `static/index.html`, `tests/test_pay_all_and_pass_notify.py`, `README.md`, `.notes/00_INDEX.md`

---

## 2026-07-13 — แก้วันผ่านโปรได้หลังกดผ่านแล้ว

**ฟีเจอร์:** ปุ่ม "แก้วันผ่านโปร" บนหน้า detail โผล่เมื่อ `monthly_start_date` set & !resigned (ทั้ง probation-tail และ active). `editPassProbation()` = reuse endpoints เดิม: `DELETE /pass-probation` (กลับ probation+NULL) → `POST /pass-probation {new pass_date}` (recompute anchor + re-promote ถ้าถึง). **0 backend change** — POST ต้องการ status probation ซึ่ง DELETE คืนให้ก่อนแล้ว.

**Trade-off (ยอมรับ, single-user household):** DELETE→POST ไม่ atomic; ถ้าเดือนแรกรายเดือนถูก mark paid แล้วเลื่อน boundary → salary_payments row เก่า orphan (มองไม่เห็นผ่าน get_payments) — inherent กับการเปลี่ยน boundary, เกิดกับ undo+repass มือเหมือนกัน. เป็น correction action.

**ไฟล์:** `static/app.js` (ปุ่ม detail + `editPassProbation()` + i18n `btnEditPassDate` TH/EN), `static/index.html` (cache-bust `?v=20260713`). prefill prompt = วันนี้ (pass_date เดิมไม่เก็บ; ผลขึ้นกับ "เดือน" เท่านั้น).

**Verify:** node --check OK; TestClient re-pass sequence (Feb-10→anchor Mar-01 → edit Mar-20→anchor Apr-01, del/post 200); 48/48 suite (backend unchanged).


## 2026-07-12 — Per-maid payment schedule + pass-probation month-boundary rework + payer "both"

**3 feature areas บน branch `feat/maid-passprobation-payment-schedule`:**

1. **Per-maid payment schedule** (`payment_schedule`): เพิ่ม column `payment_schedule TEXT DEFAULT 'biweekly'` บน `employees` — `'biweekly'` (default, 2 รอบ: 15 + สิ้นเดือน) หรือ `'monthly'` (1 รอบ สิ้นเดือน = เต็มเงินเดือน, `get_payments` ข้าม period 1). ตั้งค่าได้ตอนสร้าง/แก้ไขข้อมูล (dropdown ในฟอร์ม).
2. **Pass-probation month-boundary rework:** กดผ่านโปรกลางเดือน → **ไม่ active ทันทีแล้ว** — จ่ายรายวันต่อจนสิ้นเดือนที่กด (pass-month), รายเดือนเริ่มวันที่ 1 ของเดือนถัดไปเท่านั้น (`monthly_start_date` = anchor นั้น). ยังคง `employment_status='probation'` จนกว่า `_promote_pending()` จะ flip ให้เมื่อถึง anchor — เรียกตอนกดผ่านโปร (backdate/กดวันที่ 1), ตอน app startup (`lifespan`, heal การพลาด), และ **job ใหม่ `promote_probation` ทุกวัน 00:10**. `first_month_leave_days` ตอนนี้ set = `monthly_leave_days` เสมอ (transition month กลายเป็น full month ของ anchor เดือนถัดไป ไม่ใช่ partial) — **ลบ popup ถามจำนวนวันหยุดเดือนแรกออกแล้ว**. `get_summary` เพิ่ม guard `month_all_daily`: เดือนที่อยู่ก่อน anchor ทั้งเดือนยังคง daily framing แม้ status โดน flip เป็น active ไปแล้ว (กัน pass-month โดนรายงานเป็นเงินเดือนเต็มผิด เวลาดูย้อนหลัง). `get_overall` ยังไม่แก้ — known limitation (all-time dashboard ยัง rough).
3. **Payer "ฟิก + ปุ๊ก":** `PAYERS` const ใน `app.js` เพิ่มตัวเลือกที่ 3 สำหรับกรณีจ่ายร่วมกัน — เก็บเป็น string ตรงๆ ใน `paid_by` เดิม ไม่ต้องแก้ schema.

**ไฟล์ที่แก้ (4 commits):**
- `main.py`: migration `payment_schedule`, `EmployeeCreate` field, create/update employee INSERT/UPDATE, `get_payments` schedule branch; `_promote_pending()` helper + เรียกใน `lifespan`/`pass_probation`/daily job `promote_probation` (00:10); `pass_probation` endpoint เปลี่ยนมาคำนวณ anchor = วันที่ 1 เดือนถัดไป (ไม่ set `employment_status='active'` ตรงๆ อีกต่อไป, ลบ `first_month_leave_days` ออกจาก request body); `get_summary` เพิ่ม `month_all_daily` guard
- `static/app.js`: `PAYERS` array, ฟอร์มพนักงานเพิ่ม `payment_schedule` select + i18n keys (TH/EN), badge สถานะ (เขียว "ผ่านโปรแล้ว — รายเดือนเริ่ม `<date>`" ระหว่าง tail vs เหลือง "ทดลองงาน"), ปุ่ม "ผ่านโปร" ซ่อนเมื่อ anchor ถูก set แล้ว, `passProbation()` ตัด prompt ถามวันหยุดเดือนแรกออก
- `static/index.html`: cache-bust `app.js?v=20260712`
- Tests ใหม่: `tests/test_payment_schedule.py` (schedule branch), `tests/test_pass_probation_boundary.py` (anchor calc, `_promote_pending`, daily-through-month-end, month_all_daily guard)

**Test:** 48 passed (เดิม 36 + ใหม่ 12 จาก `test_payment_schedule.py` + `test_pass_probation_boundary.py`, 3 commits แรก)

**ค้าง/flag:** `get_overall` (all-time dashboard) ยังไม่มี `month_all_daily`-เทียบเท่า guard — ถ้าดู "ภาพรวมทั้งหมด" ของแม่บ้านที่เพิ่งผ่านโปรช่วง pass-month อาจเห็นเลขหยาบผิดเล็กน้อย จงใจไม่แก้รอบนี้ (scope เฉพาะ summary/payslip รายเดือนตาม spec).

## 2026-07-10 — First-month leave days on pass-probation

**Feature:** กดผ่านทดลองงาน → popup ถาม "จำนวนวันหยุดเดือนแรก" → เดือนแรก (transition month) ได้ตามจำนวนที่กรอก, เดือนถัดไปได้ `monthly_leave_days` ปกติ. Default = 0 (ไม่กรอก = ไม่ได้วันหยุดเดือนแรก).

**ไฟล์ที่แก้:**
- `calc.py`: `compute_monthly_leave_balance` + `compute_resign_summary` — เพิ่ม params `monthly_start_date`, `first_month_leave_days`. Transition month (เดือนเดียวกับ monthly_start_date) ใช้ `first_month_leave_days`, เดือนอื่นใช้ `monthly_leave_days` ปกติ
- `main.py`: migration `first_month_leave_days REAL DEFAULT 0`, `PassProbationRequest` เพิ่ม field, `pass_probation` endpoint เก็บลง DB, call sites ทั้ง 4 จุดส่ง params ครบ (leave-balance, get_summary, resign-summary, notify_resign)
- `line_notify.py`: `notify_resign` เพิ่ม params ส่งต่อให้ `compute_resign_summary` ครบ
- `static/app.js`: `passProbation` เพิ่ม prompt ถามจำนวนวันหลัง confirm pass_date, i18n key `firstMonthLeavePrompt` (TH/EN)
- `tests/conftest.py`: เพิ่ม column `first_month_leave_days` ใน test schema
- `tests/test_probation.py`: 3 tests ใหม่ (transition month, next month, zero default)

**Test:** 36 passed (เดิม 33 + ใหม่ 3)

- `i18n._STATUS['km']['compensatory']`: `🟢 ថ្ងៃសងសង` → `🟢 ថ្ងៃសង` (พยางค์ `សង` ซ้ำผิด, high confidence). best-effort review my/lo/km: **lo โอเคหมด**; **my flag 2 จุดยังไม่แก้** (`kind_pos="အကြွေး"` semantics น่าจะกลับ pos/neg; comp label `အပိုဆောင်းရက်` แปลกๆ) — ต้อง native พม่าจริงดู, disclaimer คงไว้.

## 2026-06-30 (2) — Monthly report LINE noti: probation outstanding-only + maid language

**ปัญหา (จากเจ้าของ):**
1. สรุปรายเดือน LINE แสดง "ค้างลา 0.5 วัน ≈ ฿167" สำหรับแม่บ้าน **ทดลองงาน** — แต่ช่วงโปรไม่มีวันลา จึงไม่ควรมียอดค้างลา. คาดหวัง: ช่วงโปรแสดงแค่ "มี/ไม่มียอดค้างจ่าย".
2. noti สรุปรายเดือน **ไม่แนบภาษาแม่บ้าน** (`notify_language`) ทั้งที่ noti อื่นแนบ. คาดหวัง: ถ้าตั้งภาษาไว้ ทุก noti ต้องมีคำแปล.

**แก้:**
- `calc.compute_probation_unpaid(emp_id, start, rate, up_to=None)` — แยก amount-based per-day unpaid (`max(0, day_rate − day_paid)`, tip วันหนึ่งไม่ลดวันอื่น) ออกเป็น helper. **ใช้ร่วม** `get_overall` (dashboard ค้างจ่าย) + `notify_balance_query` + monthly report → ตัวเลขไม่ drift. ลบ logic inline เดิมใน 2 จุดทิ้ง.
- `line_notify._monthly_entry(emp)` (แยกจาก `notify_monthly_report`): probation → ใช้ `compute_probation_unpaid` แสดงแค่ `💵 ค้างจ่าย: ฿X` หรือ `✅ ไม่มียอดค้างจ่าย` (ไม่มี comp/leave). active → balance เดิม แต่ resolve **anchor = `monthly_start_date or start_date`** (เดิมส่ง `start_date` ดิบ → คนผ่านโปรนับ leave จาก start_date ผิด). ต่อท้าย block แปลภาษาต่อแม่บ้าน (`notify_language`) ใต้บล็อกไทยของแต่ละคน.
- `main._send_monthly_report` SELECT เพิ่ม `employment_status, probation_daily_rate, monthly_start_date, notify_language`.
- `i18n.py`: เพิ่ม msg_type `monthly` / `monthly_probation_owed` / `monthly_probation_clear` ครบ 4 ภาษา (en/my/lo/km). `translate_block` เปิดให้ template ใช้ `{comp}{leave}{kind}{bal_days}{bal_amt}` ตรงๆ + guard balance-block path ด้วย `daily_rate in p` (monthly ไม่ส่ง daily_rate). my/lo/km ยัง machine-generated.
- **ปิด gap "ทุก noti"**: เพิ่ม `language` param + `_append_tr` ให้ `notify_cancel_attendance` / `notify_cancel_resign` / `notify_slip_image` (เดิม Thai-only) + plumb `notify_language` จาก caller ใน main.py (cancel-resign + slip-upload SELECT เพิ่ม col). i18n msg_type `cancel_attendance`/`cancel_resign`/`slip_image` × 4 ภาษา. **ครบทุก notify แล้ว.**

**Test:** 33 pass + `test_monthly_report.py` (compute_probation_unpaid overpay-no-cross-reduction; i18n monthly blocks owed/clear/active + Thai=None) + `test_i18n` ขยาย coverage ครบ 10 msg_type × 4 ภาษา.
**ค้าง / flag:**
- **monthly-mode maid** (holiday_mode='monthly') ในสรุปรายเดือนยังใช้ `compute_overall_balance` (sunday semantics) — balance ที่ถูกต้องต้องใช้ `compute_monthly_leave_balance` (accrued−used). **pre-existing**, ไม่แก้ในรอบนี้เพราะ half-fix (แค่ส่ง holiday_mode) ได้ตัวเลขผิดแบบใหม่. ถ้ามีแม่บ้าน monthly mode จริงต้องแก้แยก.
- ยังไม่ smoke-test ข้อความประกอบจริงบน NAS (line_notify bind helper ตอน import → unit-test assembled message ลำบาก). ต้อง `/deploy` + trigger รายงานดู LINE จริง.
- native review my/lo/km.

## 2026-06-30 — Docker healthcheck + CI test coverage
- **Healthcheck** เพิ่มใน `docker-compose.yml` (service `maid-tracker`): stdlib urllib ยิง `GET http://localhost:8000/` (catch-all route → `static/index.html`) `interval 30s / timeout 10s / retries 3 / start_period 30s`. Hung uvicorn → Docker auto-restart (เดิมไม่มี healthcheck เลย). Deploy + verified `(healthy)` บน NAS.
- **CI:** project เพิ่ม `.github/workflows/tests.yml` — รัน `pytest tests/` ของ stack นี้ (31 tests) ทุก PR ที่แตะ `*.py`/`requirements.txt`. เดิม CI รันแค่ root `tests/` + `shared/tests/` → stack tests ไม่เคยรันอัตโนมัติ.

---

## 2026-06-25 (2) — Reminder translation: MiMo LLM → static dict (`reminder_i18n.py`)

**เหตุผล:** input space reminder ทั้งหมดมีแค่ ~2-10 ข้อความคงที่ (owner ยืนยัน แทบไม่เปลี่ยน). เรียก MiMo ทุกครั้งที่ save reminder คือ over-engineering — มี failure mode (token truncation, ดู entry ก่อนหน้า), latency, ต้องดูแล secrets/dependency โดยไม่จำเป็น.

**เปลี่ยน:**
- เพิ่ม `reminder_i18n.py`: dict `REMINDERS: dict[str, dict[str, str]]` แมป Thai reminder text → `{my, en, lo, km}`. Seeded จาก MiMo output ที่ผลิตจริงใน production cache อยู่แล้ว (ยัง machine-generated, ยังไม่ผ่าน native review เหมือน `i18n.py`). ฟังก์ชัน `lookup(text) -> dict | None`.
- ลบไฟล์: `reminder_translate.py` (MiMo caller), `http_client.py` (vendored httpx+retry client ที่ใช้เฉพาะ `reminder_translate`)
- `main.py` เปลี่ยนทุก call site (4 จุด) จาก `reminder_translate.translate_reminder(...)` (async, MiMo call) → `reminder_i18n.lookup(r["message"])` (sync, dict lookup)
- `secrets.manifest.yaml`: ลบ `MIMO_*` keys ทั้งหมด (ไม่ใช้ MiMo แล้ว)

**Fallback behavior:** ข้อความ reminder ใหม่ที่ไม่อยู่ใน dict → `lookup()` คืน `None` → ส่ง Thai-only เหมือนเดิม (ไม่มี auto-translate แล้ว). ต้องเพิ่ม entry ใน `REMINDERS` dict เองเมื่อมี reminder text ใหม่ที่ต้องการแปล.

**ไฟล์:** เพิ่ม `reminder_i18n.py`; ลบ `reminder_translate.py`, `http_client.py`; แก้ `main.py`, `secrets.manifest.yaml`.

---

## 2026-06-25 — Fix reminder Burmese แปลหายบ่อย (MiMo token truncation)

**อาการ:** LINE reminder แม่บ้าน (notify_language=`my`) ส่วนใหญ่มีแต่ไทย บางครั้งมีพม่า.
**Root cause (วัด live บน NAS):** `reminder_translate.translate_reminder` ใช้ MiMo `xiaomi/mimo-v2.5` (reasoning model). `reasoning_tokens≈1427` ต่อ call → `max_tokens=1500` เหลือ ~70 token ให้ output → JSON output ถูกตัดกลางคัน → `json.loads` error `Unterminated string` → return `None` → ส่ง Thai-only. ไม่ persist + set `last_sent_date` → ไม่ retry วันนั้น.
**Fix:** `reminder_translate.py` `max_tokens` 1500 → **4000**. ทดสอบ live: `finish_reason=stop`, JSON ครบ 4 ภาษา (my/en/lo/km).
**Backfill:** seeded reminders 2 ตัวใน live DB มี `message_i18n=NULL` → run translate+UPDATE ตรง (ไม่ส่ง LINE) ให้ cache พม่าไว้แล้ว.
**Deploy:** `./scripts/deploy.sh -s maid-tracker -y` (rebuild image, COPY . . bake fix). ยืนยัน container `/app/reminder_translate.py` = 4000.
**ไฟล์:** `reminder_translate.py`.
**ค้าง:** ยัง depend MiMo ตอน fire สำหรับ reminder ใหม่ที่ผู้ใช้เพิ่ม — ถ้า MiMo ล่ม fire-time = Thai-only วันนั้น (ไม่ retry). พิจารณา manual translation field ถ้าเจ็บอีก.

---

## 2026-06-25 — fix: reminders on-the-fly translation for existing reminders

**Bug:** Existing reminders created before i18n feature have empty `message_i18n`. LINE notifications showed Thai only, even when employees have `notify_language = "my"`.

**Fix:** Both `_check_reminders` (scheduler) and `test_reminder` (test button) now translate on-the-fly when `message_i18n` is empty — calls `reminder_translate.translate_reminder()` via MiMo, caches result in DB for subsequent fires.

**Files:** `main.py`

**Test:** 33/33 passed. Deployed.

## 2026-06-25 — fix: probation per-day unpaid + accumulated + total_earned

**Bugs (3 related):**
1. `total_unpaid = earned - paid` (cumulative) — yesterday's tip (200 vs 167) reduced today's unpaid (334 → 301). Should be per-day: each day's overpayment is a tip, doesn't reduce other days.
2. LINE balance query "ยอดสะสม" showed `compute_probation_tally` amount (501) instead of `total_paid + total_unpaid` (534).
3. Dashboard `total_earned` showed tally amount (501) instead of actual cost including tips (534).

**Fix:**
- `main.py` `/summary` + `/overall`: per-day unpaid calculation — iterate each day, `max(0, day_rate - day_paid)`, sum. `total_earned = total_paid + total_unpaid`.
- `line_notify.py` `notify_balance_query`: accumulated = `total_paid + total_unpaid` (per-day), not `tally['amount']`.
- `i18n.py` `translate_block`: added `days` and `daily_rate` params to `.format()` call (were missing, caused KeyError).

**Files:** `main.py`, `line_notify.py`, `i18n.py`

**Test:** 33/33 passed. Deployed + verified API returns `total_earned: 534, total_paid: 200, total_unpaid: 334`.

## 2026-06-24 — fix: probation balance — no negative unpaid + i18n for balance query

**Bugs:**
1. `total_unpaid = earned - paid` went negative when overpaid (e.g., 167 earned - 200 paid = -33). Dashboard showed "ค้างจ่าย -33" which is confusing — overpayment should be treated as tip, not tracked.
2. `notify_balance_query` had no i18n — always Thai, even for non-Thai employees.

**Fix:**
- `main.py`: `total_unpaid = max(0, earned - paid)` in both `/summary` and `/overall` endpoints.
- `line_notify.py`: `notify_balance_query` now accepts `language` param, uses `_append_tr` for translated blocks.
- `i18n.py`: added `balance_query` key for all languages (en/my/lo/km).

**Files:** `main.py`, `line_notify.py`, `i18n.py`

**Test:** 33/33 passed. Deployed.

## 2026-06-24 — fix: balance query shows wrong data for probation employees

**Bug:** `notify_balance_query` always called `compute_overall_balance` (monthly mode) — showing comp/leave days which don't apply to probation employees. Probation employees are paid daily, no leave/comp balance.

**Fix:** `notify_balance_query` now branches on `employment_status`:
- `"probation"` → `compute_probation_tally` → shows days worked + cumulative amount
- `"monthly"` → `compute_overall_balance` → shows comp/leave balance (existing behavior)

**Files:** `line_notify.py` (import `compute_probation_tally`, branch in `notify_balance_query`), `main.py` (pass `employment_status` + `probation_daily_rate` from employee record)

**Test:** 33/33 passed. Deployed.

## 2026-06-25 — fix: probation per-day unpaid + accumulated + total_earned

**Bugs (3 related):**
1. `total_unpaid = earned - paid` (cumulative) — yesterday's tip (200 vs 167) reduced today's unpaid (334 → 301). Should be per-day: each day's overpayment is a tip, doesn't reduce other days.
2. LINE balance query "ยอดสะสม" showed `compute_probation_tally` amount (501) instead of `total_paid + total_unpaid` (534).
3. Dashboard `total_earned` showed tally amount (501) instead of actual cost including tips (534).

**Fix:**
- `main.py` `/summary` + `/overall`: per-day unpaid calculation — iterate each day, `max(0, day_rate - day_paid)`, sum. `total_earned = total_paid + total_unpaid`.
- `line_notify.py` `notify_balance_query`: accumulated = `total_paid + total_unpaid` (per-day), not `tally['amount']`.
- `i18n.py` `translate_block`: added `days` and `daily_rate` params to `.format()` call (were missing, caused KeyError).

**Files:** `main.py`, `line_notify.py`, `i18n.py`

**Test:** 33/33 passed. Deployed + verified API returns `total_earned: 534, total_paid: 200, total_unpaid: 334`.

## 2026-06-24 — fix: nginx blocked LINE webhook (401 → keyword commands dead)

**Bug:** All LINE keyword commands (แสดงยอด, ยอดสะสม, วันนี้ลา, จ่ายแล้ว, etc.) silently failed — no response in group chat.

**Root cause:** `nginx.conf` applied `auth_basic` to all `location /` paths. The `/webhook/line` endpoint had no dedicated location block, so nginx returned 401 before the request reached FastAPI. The `_AUTH_SKIP_PATHS` in main.py only skips app-level middleware — nginx blocks first.

**Fix:** Added explicit `location /webhook/line` block in `nginx.conf` without `auth_basic`, matching the existing `/api/slips/public/` pattern.

**Files:** `nginx/nginx.conf`

**Test:** `curl -X POST https://<NAS_HOST>:15055/webhook/line -d '{}'` → 400 (was 401). Deployed + verified.

**Note:** With 2 active employees, keyword queries require a name in the message (e.g., "ส้มแสดงยอด"). Without a name, the system sends a clarification prompt.

## 2026-06-24 — fix: daily-pay amount edit + JS cache-bust

**Bug:** User could not edit the amount of an already-paid probation daily payment. Two root causes:
1. Stale cached `app.js` — `index.html` loaded `/static/app.js` with no cache-bust query param.
2. No endpoint to edit amount on an already-paid day (toggle only flips paid state).

**Fix:**
- `main.py`: added `POST /api/employees/{emp_id}/daily-payments/{work_date}/amount?amount=` — updates amount in-place on an already-paid day; 400 if not paid or amount<=0.
- `static/app.js`: added "แก้จำนวนเงิน" button on paid daily cards + `editDailyAmount()` fn (prompt → POST → refresh).
- `static/index.html`: added `?v=20260624` cache-bust on `app.js` script tag.

**Files:** `main.py`, `static/app.js`, `static/index.html`

**Test:** 33/33 passed (py_compile OK, node --check OK). `python-multipart` re-installed in venv (was missing).

## 2026-06-24 — Candidate 5: migrate backup to shared sqlite_backup module

Inline `_backup_db()` (Online Backup API + gzip + retention) ย้ายไป `shared/sqlite_backup.py`
ผ่าน `from sqlite_backup import backup_db`. ลบ `gzip`, `shutil` imports ที่ไม่ใช้แล้ว.
Manual trigger API (`POST /api/admin/backup`) ยังใช้ wrapper `_backup_db()` เหมือนเดิม.

## 2026-06-20 — fix: LINE resign notice used monthly calc for probation employees

**Bug:** `notify_resign` (line_notify.py) always called `compute_resign_summary` (monthly leave-balance math) regardless of `employment_status`. Probation employees who'd been paid daily for every day worked still got a fabricated "ยอดค้างลา" line and nonzero ยอดที่ต้องจ่าย on resignation.

**Fix:** `notify_resign` now branches on `employment_status == "probation"` → calls `compute_probation_resign` (unpaid days × daily rate, no monthly base/leave balance), matching the logic already used by the `GET /resign-summary` preview endpoint. `resign_employee` (main.py) now passes `employment_status` + `probation_daily_rate` through.

**ไฟล์:** `line_notify.py`, `main.py`

**Test:** no pytest runtime available in this sandbox (httpx not importable under system python3.13); verified manually by stubbing httpx + sqlite fixture — fully-paid probation resign now sends ฿0 with no leave-balance line.

## 2026-06-17 — cleanup: httpx + dedup slip-upload tail (ponytail audit)

Ponytail audit ทั้ง repo → ส่วนใหญ่ lean. เจอ 2 micro-cut ใน maid-tracker:

- **requests → httpx**: เหลือใช้แค่ `requests.post` ที่เดียวใน `line_notify.send_line`. swap เป็น `httpx.post` (signature เหมือนกัน). ตัด dep `requests==2.32.3` ออก ใส่ `httpx==0.28.1` แทน → ตรงกับ stack อื่นทั้ง repo, dep น้อยลง 1.
- **dedup slip-upload tail**: `upload_period_slip` + `upload_daily_slip` มี tail ซ้ำ (fetch paid_at, fetch emp name, commit/close, notify_slip_image ถ้า already_paid). แยกเป็น `_finish_slip_upload(conn, emp_id, fname, already_paid, label)`. `main.py` −19 บรรทัด net.

**ไฟล์:** `line_notify.py`, `main.py`, `requirements.txt`

**Test:** 16 passed. **Commit:** `116da32` (no Claude trailer). **Deploy:** `./scripts/deploy.sh -s maid-tracker -y` → image rebuilt (httpx-0.28.1 ติดตั้ง, requests หาย), container restarted OK.

---

## 2026-06-16 — LINE slip image push (daily + monthly payment)

### ฟีเจอร์ที่เพิ่ม
- **จ่ายรายวัน (probation):** `toggle_daily_payment` ตอน mark paid → ส่ง LINE text พร้อมสลิปรูปถ้ามี (ไม่เคยมีมาก่อน)
- **จ่ายรายเดือน:** `toggle_payment` ส่ง LINE แบบเดิม + เพิ่ม `paid_by` ในข้อความ + สลิปรูปถ้ามีตอน mark paid
- **slip upload ทั้ง daily + monthly:** ถ้า payment ถูก mark paid แล้ว → upload สลิปทีหลัง → ส่ง LINE image ทันที (trigger จาก upload endpoint)
- **PDF slip:** skip image ส่ง LINE โดยอัตโนมัติ (LINE ไม่รองรับ PDF)

### Security
- **HMAC-signed public slip URL:** `/api/slips/public/{token}/{fname}` — token = HMAC-SHA256(CHANNEL_SECRET, fname)[:16]
- nginx public location `/api/slips/public/` bypass basic-auth → app validate token เอง
- ป้องกัน enumerate: ไม่ใช้ obscurity แต่ใช้ HMAC token จาก CHANNEL_SECRET ที่ LINE รู้

### Config ที่ต้องทำก่อน deploy
1. `make edit-vault` → เพิ่ม key `stacks.maid_tracker.public_base_url` = `https://<NAS_HOST>:15055`
2. `make secrets` → สร้าง `.env` ใหม่
3. `./scripts/deploy.sh`

### ไฟล์ที่แก้
- `main.py`: public slip route, toggle_payment/daily + upload endpoints
- `line_notify.py`: HMAC helpers, notify_daily_payment, notify_slip_image, send_line extra_messages
- `nginx/nginx.conf`: public location block
- `secrets.manifest.yaml`: MAID_PUBLIC_BASE_URL vault key

---

## 2026-06-14 (เพิ่มเติม) — Probation: default-present model + summary fix

### 2 ฟีดแบ็คจาก user (เทสต์ live)
1. **วันหยุดต้องไม่ได้รับช่วงโปร:** `get_summary`/`get_overall` เดิมใช้ `default_status` (sunday) → probation ได้ holiday + เงินเดือนเต็มผิด. แก้: probation branch (นับเฉพาะ daily, ไม่มี holiday/monthly), `export_payslip` ออก CSV รายวัน, frontend detail/summary/list/payments render daily framing.
2. **เปลี่ยน model เป็น default-present:** user ขอให้ทุกวัน default = work (มาทุกวันรวมอาทิตย์), mark เฉพาะวัน **ขาด**. 
   - `compute_probation_tally` rewrite: ทุกวันใน window = 1.0, ลบวันขาด (`probation_worked_fraction`: leave full→0, half→0.5)
   - วันขาด = attendance `leave` (repurpose ช่วงโปร). `upsert_attendance` ยอม leave, reject comp/holiday. skip LINE notify ช่วงโปร
   - `get_attendance` default = work ทุกวัน ≤ วันนี้. cycleDay UI: work↔ขาด (full/half), คลิกกลับ = DELETE row
   - `get_daily_payments`: iterate วัน default-present. `toggle_daily_payment` จ่ายวัน default ได้ (ไม่ต้องมี row), จ่ายวันขาดไม่ได้
   - `compute_probation_resign`: unpaid worked days (default-present − ขาด − paid)

### Verify
- pytest 9 passed (tally default-present, resign, summary/overall/payslip views)
- E2E: default 31 วัน → mark ขาด → 30, จ่ายวัน default ได้, จ่ายวันขาด 400, summary work_days=30 earned=15000 holiday=0

## 2026-06-14 — Probation mode + slip/document upload

### งานที่ทำ (brainstorm → spec → plan → subagent-driven impl)
Spec: `docs/superpowers/specs/2026-06-14-maid-probation-mode-design.md`
Plan: `docs/superpowers/plans/2026-06-14-maid-probation-mode.md`

**Probation mode** (axis `employment_status` แยกจาก holiday_mode):
- แม่บ้านใหม่เริ่มแบบ probation → จ่ายรายวัน (`probation_daily_rate` กรอกตอนสร้าง), ลา/ชดเชย/holiday ปิด
- จ่ายรายวันต่อวันผ่าน table `daily_payments` (toggle paid, amount snapshot)
- กดผ่านโปร (`pass-probation` endpoint) → set `monthly_start_date`, active ทันที, เปิด leave + monthly
- **Monthly anchor** = `monthly_start_date or start_date` thread เข้าทุก calc: `get_payments`, `_compute_period_amount`, `get_summary`, `get_overall`, `get_leave_balance`, `get_resign_summary` (calc.py functions รับ start_date param อยู่แล้ว → caller ส่ง anchor)
- **Transition month**: daily (< pass_date, cap ใน `get_daily_payments`) + monthly pro-rate (≥ pass_date). ไม่ double-pay/orphan. Edge โปรข้ามเดือน fix (first-month detect ที่ anchor.month)
- Resign ระหว่างโปร = unpaid days only (LEFT JOIN daily_payments paid_at)

**Slip / Documents**:
- `payment_method` (cash/transfer) ต่อแม่บ้าน. transfer → upload slip ทุก payment (daily + period), เก็บ `/data/slips`
- เอกสาร id_card/passport หลายรูป/คน, เก็บ `/data/documents`. Serve ผ่าน FastAPI route (หลัง nginx basic-auth), validate jpg/png/webp/pdf ≤10MB
- `delete_employee` ลบ daily_payments/employee_documents + ไฟล์ slip/doc ด้วย
- **ไม่อยู่ใน DB backup** (`_backup_db` = SQLite เท่านั้น) — off-NAS backup ทำภายหลังถ้าต้องการ

**Schema migration** (idempotent ALTER/CREATE IF NOT EXISTS): employees +4 cols, salary_payments +slip_path, ตารางใหม่ daily_payments/employee_documents. แถวเก่า → active/cash/NULL anchor (behavior เดิมไม่เปลี่ยน)

**Frontend** (`static/app.js`): form probation toggle + payment_method + docs upload; detail badge + ปุ่มผ่านโปร + ซ่อน leave; payments view render per-month (daily section + monthly section, transition มีทั้งคู่)

**ไฟล์ที่เปลี่ยน:** `main.py`, `calc.py`, `static/app.js`, `requirements.txt` (+pytest), `tests/` (ใหม่: conftest + test_probation + test_smoke)

### Verify
- pytest: 6 passed (calc layer: boundary, tally, anchor prorate, resign-unpaid)
- E2E (TestClient): probation→payments[], leave reject, daily cap < pass_date, transition period2=5400 prorated, toggle on/after pass reject — ทุก assertion ผ่าน
- Phase 1 spec-compliance review (subagent): no double-pay/orphan, anchor ครบ, idempotent migration — ผ่าน

### Pre-deploy
- ไม่ต้องเพิ่ม dep runtime (`python-multipart` มีอยู่แล้ว). pytest = dev เท่านั้น
- ต้องมั่นใจ `/data/slips`, `/data/documents` เขียนได้ (สร้าง auto ตอน import)

### Next (defer)
- Off-NAS backup ของ slips/documents
- delete_document ตอนนี้ silent ถ้าไม่เจอ (cosmetic)

## 2026-06-06 — Phase 1+2 enhance: backup + payslip

### งานที่ทำ

**Phase 1 — Daily SQLite backup**
- เพิ่ม `_backup_db()` ใน `main.py` ใช้ `sqlite3.Connection.backup()` (Online Backup API) + gzip
- เขียนไฟล์ `/data/backups/maid-{YYYYMMDD-HHMMSS}.db.gz`
- Prune backup เก่ากว่า `MAID_BACKUP_RETENTION_DAYS` (default 30 วัน)
- Schedule daily 03:00 ผ่าน APScheduler CronTrigger
- Env vars ใหม่: `MAID_BACKUP_DIR` (default `/data/backups`), `MAID_BACKUP_RETENTION_DAYS` (default 30)
- Manual trigger endpoint: `POST /api/admin/backup`
- List endpoint: `GET /api/admin/backups`

**Phase 2 — Payslip CSV**
- เพิ่ม endpoint `GET /api/employees/{emp_id}/payslip/{year}/{month}`
- Reuse `get_summary()` data — ตัวเลขตรงกับ dashboard
- Output UTF-8 BOM CSV ภาษาไทย + ปี พ.ศ. (year + 543)
- Filename pattern: `payslip_<name>_<YYYY>-<MM>.csv`

**ไฟล์ที่เปลี่ยน:**
- `maid-tracker/main.py`:
  - import เพิ่ม `gzip`, `glob`, `shutil`
  - เพิ่ม `_BACKUP_DIR`, `_BACKUP_RETENTION_DAYS`, `_backup_db()`
  - เพิ่ม `daily_backup` job ใน `lifespan`
  - เพิ่ม endpoints: `export_payslip`, `trigger_backup`, `list_backups`

**Pre-deploy checklist:**
- ไม่ต้องเพิ่ม dependency (built-in `sqlite3.backup` + `gzip`)
- DB volume `maid_tracker_data` เดิม — backups เก็บใน `/data/backups` subdir ของ volume เดียวกัน
- ถ้าต้องการ off-NAS backup: mount volume แล้ว rsync `backups/` ไปที่อื่นอีกที (ภายหลัง)

**Post-deploy verify:**
1. `docker exec maid-tracker ls -la /data/backups/` (อาจว่างถ้ายังไม่ถึง 03:00)
2. Manual trigger: `curl -X POST http://<NAS>:5055/api/admin/backup -u <user>:<pass>`
3. Test payslip download: เปิด `https://<NAS>:15055/api/employees/1/payslip/2026/6` ใน browser

**Next (Phase 3 — defer):**
- Multi-worker schema (breaking — แยก PR + brainstorm ก่อน)
- LINE Rich Menu
- PDF version of payslip (เพิ่ม `reportlab` dep)

---

## 2026-05-24 — ย้ายกลับ basic auth (ลบ Authelia)

### งานที่ทำ

**เหตุผล:** ลบ Authelia auth stack ออก → maid-nginx กลับมาใช้ basic auth เหมือนเดิม

**ไฟล์ที่เปลี่ยน:**

`maid-tracker/nginx/nginx.conf`:
- ลบ `location /authelia` (forward-auth endpoint) ออก
- ลบ `auth_request /authelia` และ `error_page 401 =302` ออก
- เพิ่ม `auth_basic "Restricted"` + `auth_basic_user_file /etc/nginx/.htpasswd`
- mount path เปลี่ยนจาก `templates/default.conf.template` → `conf.d/default.conf`

`maid-tracker/docker-compose.yml`:
- ลบ `auth_net` external network ออก
- ลบ `AUTHELIA_HOST` + `NAS_HOST` env vars ออกจาก maid-nginx service
- เพิ่ม volume mount: `./nginx/.htpasswd:/etc/nginx/.htpasswd:ro`

`maid-tracker/nginx/.htpasswd` (ใหม่, ไม่ commit):
- APR1 hash สำหรับ user `fixhardez`

`maid-tracker/.env.example` + `.env`:
- ลบ `NAS_HOST` + `AUTHELIA_HOST` block + `NGINX_BASIC_AUTH_*` ออก

**Deploy:** `scripts/deploy.sh -s maid-tracker -y` — image rebuilt + maid-tracker-nginx created ✅

---

## 2026-05-18 (2)

### ปรับ Frontend ให้ Modern

**ไฟล์ที่เปลี่ยน:**
- `static/style.css` — redesign ทั้งหมด: CSS variables/tokens, navbar gradient (dark slate), calendar status colors ใหม่, card shadows, avatar, action buttons, stat cards
- `static/index.html` — เพิ่ม Google Font Sarabun, meta theme-color, ปรับ navbar HTML
- `static/app.js` — อัปเดต employee list cards (avatar สี่เหลี่ยมมน, chevron), profile header (rounded avatar), quick action buttons (action-btn class), stat cards, breadcrumb style

**Design decisions:**
- Primary: `#4f46e5` (indigo) แทน Bootstrap blue
- Navbar: gradient `#0f172a → #1e1b4b → #312e81`
- Calendar colors: ใช้ Tailwind-inspired palette (ecfdf5, fff1f2, eff6ff)
- Avatar: border-radius 14px แทน circle

---

## 2026-05-18

### แก้บัค Basic Auth loop เมื่อกดปฏิทินการทำงาน

**ปัญหา:** browser บางตัวไม่ส่ง cached Basic Auth credentials กับ `fetch()` requests (แม้ same-origin) ทำให้ API return 401 + `WWW-Authenticate` → browser โชว์ dialog → loop

**วิธีแก้ (main.py):**
- เพิ่ม session cookie mechanism ใน `basic_auth_middleware`
- หลังจาก Basic Auth สำเร็จครั้งแรก → ออก `maid_session` cookie (httponly, samesite=lax, อายุ 7 วัน)
- request ถัดไปใช้ cookie แทน — browser ส่ง cookie อัตโนมัติ ไม่ต้องพึ่ง Basic Auth credential cache
- เพิ่ม `_validate_basic()` helper + `_sessions` dict (in-memory, expire auto)
- เพิ่ม import `secrets`, `time`

**ไฟล์ที่เปลี่ยน:** `maid-tracker/main.py` (middleware section เท่านั้น, ไม่มี frontend change)

---

## 2026-05-12

### สร้าง maid-tracker stack ใหม่

**สร้างจากศูนย์** — Docker stack FastAPI + SQLite + Bootstrap 5 SPA สำหรับบันทึกการทำงานแม่บ้าน

**ไฟล์ที่สร้าง:**
- `maid-tracker/docker-compose.yml` — port 5055
- `maid-tracker/Dockerfile` — python:3.12-slim
- `maid-tracker/requirements.txt`
- `maid-tracker/main.py` — FastAPI backend
- `maid-tracker/static/index.html`, `app.js`, `style.css` — SPA frontend

**ฟีเจอร์หลัก:**
- โปรไฟล์แม่บ้าน (ชื่อ, อายุ, สัญชาติ, เบอร์, LINE, Facebook, วันเริ่มงาน, เงินเดือน)
- ปฏิทินบันทึกการทำงานรายเดือน (default: จ-ส = ทำงาน, อา = หยุด)
- สถานะ: ทำงาน / ลา / หยุด / ชดเชย (รองรับ half-day)
- สรุปรายเดือน + คำนวณเงินเดือน (prorate เดือนแรก)
- สะสม balance (ชดเชย−ลา) ชำระวันลาออก

---

### เพิ่ม feature รูปแบบวันหยุด 2 โหมด

**โหมดใหม่: เดือนละ X วัน**

**DB migration (auto):**
- `employees.holiday_mode` — `'sunday'` | `'monthly'`
- `employees.monthly_leave_days` — วันหยุดที่ได้ต่อเดือน

**Logic (calc.py):**
- `default_status(d, holiday_mode)` — monthly mode ทุกวันคือ work
- `compute_monthly_leave_balance()` — คำนวณยอดสะสมวันหยุด ครบ cap ไม่สะสมเพิ่ม

**Backend (main.py):**
- EmployeeCreate + CRUD รองรับ holiday_mode + monthly_leave_days
- `GET /api/employees/{id}/leave-balance` — endpoint ใหม่
- get_summary / get_overall / export_attendance รองรับทั้ง 2 โหมด
- LINE webhook: monthly mode block compensatory + allow leave ทุกวัน

**Frontend (app.js):**
- ฟอร์ม: radio เลือกโหมด + ช่องกรอก monthly_leave_days + max cap
- ปฏิทิน monthly: work ↔ leave เท่านั้น, legend สั้นลง
- Leave balance bar เหนือปฏิทิน (monthly mode)
- สรุปเดือน: stat card + financial table ปรับตามโหมด
- Employee detail: stat card แสดง leave_balance แทน comp_days

**อัปเดต:** README.md + CLAUDE.md ทั้งสองไฟล์

---

## 2026-05-19

### Fix: default theme เป็น light

**ไฟล์ที่แก้:** `static/index.html` บรรทัด 21

**เปลี่ยนจาก:**
```js
var theme = saved || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
```
**เป็น:**
```js
var theme = saved || "light";
```

**ผล:** ผู้ใช้ใหม่ (ไม่มี localStorage) จะเห็น light theme เสมอ ไม่ตาม OS preference อีกต่อไป ส่วนผู้ที่เคย toggle ยังจำค่าเดิมได้ปกติ

---

## 2026-06-14 (รอบ 2)

### Feature: ผู้จ่าย (payer dropdown) + เอกสารอื่นๆ + fix 413 upload

**สาเหตุ:** user รายงาน add passport ใบที่ 2 error `413 Request Entity Too Large` (nginx/1.31.1) + ขอเพิ่ม (1) เอกสารอื่นนอกจากบัตร/passport (2) dropdown เลือกผู้จ่ายแต่ละงวด (ฟิก/ปุ๊ก)

**1. Fix 413:** `nginx/nginx.conf` เพิ่ม `client_max_body_size 25m;` — default nginx = 1MB, รูป passport จากมือถือ 3-8MB เลยโดน reject ก่อนถึง app. ตั้ง 25m > app cap 10MB → app ตอบ error สวยแทน

**2. เอกสารอื่นๆ (`other`):** `doc_type` คงเป็น enum `id_card|passport|other` (กัน path-traversal เพราะ doc_type อยู่ใน filename ตอน `_save_upload`). เพิ่มคอลัมน์ `doc_label TEXT` (display-only) สำหรับชื่อเอกสารกรณี other. Frontend: option "เอกสารอื่นๆ" + text input โผล่เมื่อเลือก other; typeLabel map (escHtml(doc_label))

**3. ผู้จ่าย (`paid_by`):** เพิ่มคอลัมน์ `paid_by TEXT` บน `salary_payments` + `daily_payments`. `toggle_payment`/`toggle_daily_payment` รับ query `paid_by`, เก็บตอน mark / clear (NULL) ตอน unmark. `get_payments`/`get_daily_payments` คืน `paid_by`. Frontend: `payerSelect()` dropdown (const `PAYERS=["ฟิก","ปุ๊ก"]`) ข้างปุ่มจ่าย + `payerBadge()` "จ่ายโดย X" เมื่อจ่ายแล้ว

**Bug ที่เจอ+แก้ระหว่างทาง:**
- migration ALTER `daily_payments.paid_by` + `employee_documents.doc_label` อยู่**ก่อน** executescript ที่ CREATE ตารางนั้น → fresh DB ALTER fail เงียบ (caught) → คอลัมน์หาย. ย้าย ALTER ไป**หลัง** CREATE
- pre-existing `NameError: start_date` ใน `toggle_payment` (notify_payment อ้าง `start_date` ที่ไม่เคย define) — เผยตอน test mark-paid. แก้: `start_date = date.fromisoformat(emp["start_date"])`

**ไฟล์:** `main.py` (migration, upload_documents, toggle_payment, toggle_daily_payment, get_payments, get_daily_payments), `static/app.js` (PAYERS const, doc form, typeLabel, payerSelect/payerBadge, toggle funcs, i18n TH+EN), `nginx/nginx.conf`, `tests/test_payments_docs.py` (3 tests ใหม่)

**Test:** 12 passed (เดิม 9 + ใหม่ 3: paid_by roundtrip, other doc+label, invalid doc_type rejected)

---

## 2026-06-14 (รอบ 3)

### Policy: อัตรารายวัน หารด้วยจำนวนวันทั้งเดือน (รวมวันหยุด)

**คำขอ user:** "วันหยุดเราให้หยุด แต่เราก็จ่ายเงินเดือนให้" → daily rate ต้องหารด้วยจำนวนวันรวมวันหยุด ไม่ใช่แค่วันทำงาน จ-ส

**เปลี่ยน:** `working_days_in_month` เดิม = นับ จ-ส (ไม่นับอาทิตย์) → นับ **ทุกวันในเดือน** (`calendar.monthrange()[1]`). ชื่อ fn คงเดิม (JSON-key stability) แต่ความหมายเปลี่ยน

**Invariant ที่รักษา:** full month จ่ายเต็มเสมอ (dr × วันทั้งเดือน = salary). ต้องแก้ทั้ง divisor + billable counts พร้อมกัน ไม่งั้นพัง:
- calc.py:29 divisor → `return n`
- calc.py billable (resign) → ลบ filter `weekday()!=6`
- main.py get_payments billable → `n - anchor.day + 1`
- main.py get_summary billable → เหมือนกัน
- main.py pass-probation transition billable → เหมือนกัน
(5 จุด — grep `weekday` แยก salary-divisor ออกจาก Sunday-holiday/attendance logic ก่อนแก้ ห้ามแตะ `default_status`, Sunday-leave-redundant, compensatory-only-Sunday)

**ผลข้างเคียง (แจ้ง user):** (1) หัก excess-leave ต่อวันน้อยลง (salary/30 แทน salary/26) — auto-track เพราะ `compute_leave_deduction` ใช้ `daily_rate()`. (2) ใช้กับ **ทั้งสอง holiday_mode** (monthly mode เดิมก็หาร จ-ส ทั้งที่ทำงานทุกวัน → uniform = แก้ให้ถูกด้วย)

**Frontend:** preview `/26` → `/30` + label "เฉลี่ย 30 วัน/เดือน รวมวันหยุด" (TH+EN). CSV "จำนวนวันทำงานในเดือน" → "จำนวนวันในเดือน (รวมวันหยุด)"

**ไฟล์:** `calc.py`, `main.py`, `static/app.js`, `README.md`, root `CLAUDE.md`, `tests/test_daily_divisor.py` (4 tests ใหม่ lock invariant), `tests/test_probation.py` (อัปเดต assertion 600→520, 5400→5720)

**Test:** 16 passed (เดิม 12 + ใหม่ 4)

---

## 2026-06-15 — เพิ่ม basic-auth user ที่ nginx

เพิ่ม user `Pookzii` (apr1 hash) ใน `nginx/.htpasswd` ข้าง `fixhardez` เดิม. Hash gen ผ่าน `openssl passwd -apr1`.

**ไฟล์:** `nginx/.htpasswd`

**Deploy:** ต้อง `./scripts/deploy.sh` + restart maid-nginx (htpasswd mount read-only) ถึงมีผลบน NAS. `nginx -s reload` ไม่พอเพราะไฟล์ mount ใหม่ตอน container start — restart container.

---

## 2026-06-18 — วันเกิดแม่บ้าน → คำนวณอายุอัตโนมัติ

เพิ่มฟิลด์ `birth_date` (col `employees`, migration TEXT). ถ้ากรอกวันเกิด → คำนวณอายุให้อัตโนมัติ; ถ้าไม่กรอก → ใส่อายุเองได้เหมือนเดิม.

**Design (single source of truth):** age คำนวณตอน **read** ไม่ใช่ตอน write. `_age_from_birth(bd)` (main.py) → `list_employees` + `get_employee` override `emp["age"]` เมื่อมี `birth_date`. ทุกจุดที่ display `emp.age` ทำงานต่อโดยไม่ต้องแก้ (app.js:586 list card, app.js:977 detail).

**Frontend:** เพิ่ม `<input type=date name=birth_date>` ในฟอร์ม. JS `syncAge()` — มีวันเกิด → คำนวณอายุ + `disabled` ช่อง age (disabled input ไม่ถูกส่งใน FormData → age post เป็น null → server derive จาก birth_date). ว่าง → ช่อง age แก้ได้. label i18n `fieldBirthDate` (TH "วันเกิด" / EN "Date of Birth").

**Edge:** `_age_from_birth` กัน parse fail/None/วันเกิดอนาคต → คืน None. ใช้ tuple-compare `(month,day)` leap-safe.

**ไฟล์:** `main.py`, `static/app.js`, `.notes/00_INDEX.md`

**Test:** age logic verified (birthday passed/not-yet/garbage/future/None). main.py + app.js parse OK.

---

## 2026-06-24 — แจ้งเตือนหลายภาษา + override จ่ายรายวัน + แปล reminder ด้วย MiMo

**3 ฟีเจอร์ (branch `feat/maid-multilingual-notify`):**

1. **Multilingual notify (Feature A):** เพิ่ม `employees.notify_language` (`th`|`my`|`en`|`lo`|`km`, default `th`) + dropdown "ภาษาแจ้งเตือน" ในฟอร์ม. notify 4 ตัวที่แม่บ้านสนใจ (`notify_attendance`/`notify_payment`/`notify_daily_payment`/`notify_resign`) ต่อท้าย block แปลภาษาใต้ข้อความไทย (separator `─────────`, ข้อความเดียว ไม่กิน `messages[:5]`). Static fragment dict ใน `i18n.py` (`translate_block`), label คงที่แปลครั้งเดียว reuse, ตัวเลข/ชื่อ/วันที่ (numeric `MM/YYYY`) คงเดิม.
   - ⚠️ **my/lo/km เป็น machine-generated ยังไม่ผ่าน native review** (คอมเมนต์กำกับทุก block). en self-verified. ควรให้เจ้าของภาษาตรวจก่อนใช้จริง.
   - resign block ใช้ยอดจ่ายสุทธิ (`final`) อย่างเดียว (resign summary ไม่มี comp/leave breakdown แบบ balance block).
2. **Daily-pay override (Feature B):** `toggle_daily_payment` รับ `amount` (optional). mark paid: ส่ง `amount>0` → เก็บตามนั้น (จ่ายเกินได้ ไม่ cap), ไม่ส่ง → คำนวณเดิม `rate×frac`. UI prompt ช่องเงิน pre-fill ค่าคำนวณ. ไม่ต้อง migration (col `amount` มีอยู่). `total_paid` สะท้อนอัตโนมัติ.
3. **Reminder translation (Feature C):** reminder เป็น free-text → แปลตอน save ด้วย **MiMo** (`xiaomi/mimo-v2.5`, OpenAI-compatible, ลอกจาก news-feed `_summarize_mimo`). เก็บ JSON ใน `reminders.message_i18n`. `notify_reminder` ตอนส่ง query ภาษาของแม่บ้าน active (non-Thai) แล้วต่อท้าย block ที่ cache ไว้. แปลล้มเหลว/empty/bad JSON → Thai-only (non-blocking).
   - ⚠️ MiMo v2.5 = reasoning model: `max_tokens=1500` (น้อยไป → `content` ว่าง). treat empty = fail.
   - vault: token promote → `shared.llm.mimo_api_key` (news-feed repoint ด้วย). `scripts/` ยังใช้ `shared.mimo.anthropic_api_key` (เดิม, out of scope).

**ไฟล์ใหม่:** `i18n.py`, `reminder_translate.py`, `http_client.py` (vendored จาก `shared/`, เพิ่มใน Makefile `HTTP_COPIES` + guard test).
**Test:** 33 pass (i18n key-coverage, notify append, daily override, reminder translate stubs, reminder body filtering).
**ค้าง:** native review my/lo/km; ทดสอบ MiMo จริงบน NAS (workstation sandbox อาจ block).
