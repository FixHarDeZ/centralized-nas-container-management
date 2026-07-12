# maid-tracker — Index (Memory File)

อัปเดตล่าสุด: 2026-07-12

---

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI (Python 3.12) |
| Database | SQLite — volume `maid_tracker_data` → `/data/maid_tracker.db` |
| Frontend | Vanilla JS + Bootstrap 5.3 (SPA, hash-based routing) |
| Scheduler | APScheduler (BackgroundScheduler) |
| Containerization | Docker — local build (`python:3.12-slim`) |

---

## Ports & URLs

| Layer | Value |
|-------|-------|
| Container (internal) | HTTP `8000` |
| Host port | `5055` |
| Synology Reverse Proxy | `https://<NAS_HOST>:15055` → `http://localhost:5055` |
| LINE Webhook URL | `https://<NAS_HOST>:15055/webhook/line` |

---

## Key Files

| File | Purpose |
|------|---------|
| `main.py` | FastAPI app — routes, middleware, LINE webhook |
| `calc.py` | Calculation helpers (daily rate, balance, monthly-leave-balance) |
| `line_notify.py` | LINE Messaging API push functions (+ `_append_tr` แนบคำแปล, `_reminder_body`) |
| `i18n.py` | Static fragment translations (`translate_block`) สำหรับ notify แม่บ้าน — my/lo/km machine-generated (ยังไม่ผ่าน native review) |
| `reminder_i18n.py` | Static hand-maintained dict (`REMINDERS`) แปล reminder text คงที่ — `lookup(text) -> dict\|None`. เพิ่ม reminder text ใหม่ = เพิ่ม entry เอง ไม่งั้น fallback Thai-only |
| `keywords.py` | LINE keyword lists — แก้ที่นี่เพื่อเพิ่ม/ลด trigger phrase |
| `static/app.js` | SPA frontend — routing, views, i18n (TH/EN) |
| `static/style.css` | Custom styles + calendar grid |
| `docker-compose.yml` | port `5055:8000`, volume, env_file `../.env` |

---

## DB Schema (ล่าสุด — รวม migration columns)

```sql
employees (
  id, name, age, nationality, phone, line_id, facebook,
  birth_date TEXT,          -- YYYY-MM-DD; ถ้ามี → age คำนวณจากวันเกิดตอน read (override col age), ถ้าว่าง → age กรอกมือ
  start_date TEXT,          -- YYYY-MM-DD
  monthly_salary REAL,
  max_leave_carry REAL,     -- NULL = unlimited (sunday mode: max debt; monthly mode: max positive balance)
  holiday_mode TEXT,        -- 'sunday' (default) | 'monthly'
  monthly_leave_days REAL,  -- leave days credited per month (monthly mode only)
  end_date TEXT,            -- NULL = still employed
  resign_note TEXT,
  created_at TEXT,
  -- probation mode (axis แยกจาก holiday_mode):
  employment_status TEXT DEFAULT 'active',  -- 'probation' (จ่ายรายวัน, ลาปิด) | 'active'
  probation_daily_rate REAL,                -- เรตรายวันช่วงโปร
  monthly_start_date TEXT,                  -- = วันที่ 1 ที่ monthly เริ่มจ่ายจริง (1 ของเดือนถัดจาก pass_date, หรือ pass_date เองถ้ากดวันที่ 1). NULL ระหว่างโปร (ยังไม่กดผ่าน). monthly calc anchor = monthly_start_date or start_date
  first_month_leave_days REAL DEFAULT 0,    -- วันหยุดเดือนของ transition month — ตอนนี้ set = monthly_leave_days เสมอตอนกดผ่านโปร (เดือนนั้นเป็น full month แล้วเพราะ daily คุมจนสิ้นเดือน pass). เดือนถัดไปใช้ monthly_leave_days ปกติ
  payment_method TEXT DEFAULT 'cash',       -- 'cash' | 'transfer' (transfer → แนบ slip ได้)
  payment_schedule TEXT DEFAULT 'biweekly', -- 'biweekly' (2 รอบ: 15 + สิ้นเดือน, ปกติ) | 'monthly' (รอบเดียวสิ้นเดือน = เต็มเงินเดือน, ไม่มี period 1)
  notify_language TEXT DEFAULT 'th'          -- 'th'|'my'|'en'|'lo'|'km' — non-Thai → แนบคำแปลใต้ข้อความ LINE
)

attendance (
  id, employee_id, work_date TEXT,
  status TEXT CHECK(IN 'work','leave','holiday','compensatory'),
  note TEXT,
  half_day INTEGER DEFAULT 0   -- 0 = full day (1.0) | 1 = half day (0.5)
)

salary_payments (
  id, employee_id,
  year INT, month INT,
  period INT CHECK(IN 1, 2),
  paid_at TEXT,                -- NULL = not yet paid
  leave_deduction_days REAL DEFAULT 0,
  slip_path TEXT,              -- ไฟล์ slip โอนเงิน (NULL = ไม่มี)
  paid_by TEXT                 -- ผู้จ่ายงวดนี้ (ฟิก/ปุ๊ก) NULL = ยังไม่จ่าย
)

daily_payments (                -- จ่ายรายวันช่วง probation (per work day)
  id, employee_id, work_date TEXT,
  amount REAL,                 -- snapshot = probation_daily_rate × fraction ตอน mark paid
  paid_at TEXT,                -- NULL = ยังไม่จ่าย
  slip_path TEXT,
  paid_by TEXT,                -- ผู้จ่ายวันนี้ (ฟิก/ปุ๊ก)
  UNIQUE(employee_id, work_date)
)

employee_documents (            -- รูปบัตร/passport/เอกสารอื่น (หลายรูป/คน)
  id, employee_id,
  doc_type TEXT,               -- 'id_card' | 'passport' | 'other' (enum — ปลอดภัยใน filename)
  doc_label TEXT,              -- ชื่อเอกสารกรณี 'other' (display-only, ไม่อยู่ใน path)
  file_path TEXT, uploaded_at TEXT
)

reminders (
  id, name, message,
  enabled INTEGER DEFAULT 1,
  schedule_type TEXT,          -- 'month_day_digit' | 'weekday'
  schedule_value TEXT,         -- digit: "0","0,5" | weekday: "0,3" (0=Mon…6=Sun)
  send_time TEXT,              -- "HH:MM"
  last_sent_date TEXT,
  created_at TEXT,
  message_i18n TEXT            -- JSON {my,en,lo,km} cache, มาจาก reminder_i18n.lookup() (sync, static dict — เดิมเป็น MiMo LLM call) ตอน create/update/fire reminder. lookup() ไม่เจอ (ข้อความใหม่ที่ไม่อยู่ใน dict) = NULL = ส่ง Thai-only
)
```

---

## Logic การคำนวณ

### อัตราค่าจ้างรายวัน
```
daily_rate = monthly_salary / working_days_in_month
working_days_in_month = จำนวนวัน "ทั้งเดือน" (รวมวันอาทิตย์/วันหยุด) — calendar.monthrange()[1]
```
**เหตุผล:** วันหยุดเราให้หยุดแต่จ่ายเงินเดือนให้ด้วย → วันหยุดต้องอยู่ใน denominator. ⚠️ ชื่อ fn `working_days_in_month` ยังคงเดิม (API/JSON-key stability) แต่ตอนนี้นับ "ทุกวัน" ไม่ใช่แค่ จ-ส. **Invariant:** full month → จ่ายเต็มเสมอ (dr × วันทั้งเดือน = salary) เพราะ billable ทุกจุดนับทุกวันเช่นกัน (ลบ filter `weekday()!=6` ออก 5 จุด: calc divisor+resign, get_payments, summary, pass-probation transition). หัก excess-leave ใช้ dr ใหม่ (ต่อวันน้อยลง = salary/30 แทน salary/26). ใช้กับ **ทั้งสอง holiday_mode**. วันอาทิตย์ยัง = holiday ในปฏิทิน/attendance เหมือนเดิม (เปลี่ยนแค่ money math ไม่แตะ default_status/Sunday rules).

### เงินเดือนรายเดือน (พื้นฐาน)
- จ่าย **2 รอบ** (default, `payment_schedule='biweekly'`): Period 1 วันที่ 15 = `salary / 2`, Period 2 สิ้นเดือน = `salary / 2`
- เดือนแรกที่เริ่มงาน (partial month) → pro-rate **ทุกวัน** (รวมวันหยุด) ตั้งแต่ **anchor** ถึงสิ้นเดือน

### Payment Schedule (`payment_schedule`, per-maid)
- **`'biweekly'`** (default): 2 รอบต่อเดือนตามปกติด้านบน (period 1 วันที่ 15 + period 2 สิ้นเดือน)
- **`'monthly'`**: **1 รอบ** สิ้นเดือน = เต็มเงินเดือน (`base_salary`, ไม่หาร 2) — `get_payments` ข้าม period 1 ไปเลย ไม่สร้าง entry. ตั้งค่าได้ตอนสร้าง/แก้ไขข้อมูลแม่บ้าน (dropdown ในฟอร์ม)
- ไม่กระทบ leave/holiday/probation/pass-probation logic — ใช้แค่คำนวณจำนวนรอบ+จำนวนเงินใน `get_payments`

### Probation mode (จ่ายรายวัน — axis `employment_status`)
- **`employment_status='probation'`**: จ่ายรายวัน, **ลา/ชดเชย/holiday ปิด** (attendance default = `unmarked`, POST + LINE webhook reject leave). `get_payments` คืน `[]` (ไม่มีงวดเดือน).
- **Probation tally (default-present model)** = ทุกวันใน [start, up_to] นับ 1.0 อัตโนมัติ (มาทำงานทุกวันรวมอาทิตย์) **ลบ** วันที่ mark ขาด. วันขาด = attendance status=`leave` (repurpose = "ขาด" ช่วงโปร: full→0, half→0.5). `compute_probation_tally`/`probation_worked_fraction` ใน calc.py. caller ต้องส่ง `up_to` ≤ วันนี้ (ไม่จ่ายอนาคต — `get_summary` clamp `min(month_end, today)`).
- **Mark absence (UI):** ปุ่ม "ลงเวลาทำงาน" บนหน้า detail → ปฏิทิน `/attendance`. ช่วงโปร cell toggle **work ↔ ขาด** (ขาดถาม full/half; คลิกกลับ work = DELETE row คืน default). comp/holiday ปิด. `get_attendance` คืน `work` เป็น default ทุกวัน ≤ วันนี้.
- **จ่ายรายวัน** ผ่าน `daily_payments` (toggle paid ต่อวัน, `amount` snapshot). `get_daily_payments` iterate วัน default-present (frac>0) ใน window (cap < `monthly_start_date`). จ่ายวัน default ได้แม้ไม่มี attendance row. จ่ายวันขาดไม่ได้ (400).
- **ยอดค้างจ่าย (amount-based)** = `calc.compute_probation_unpaid()` → Σ `max(0, day_rate − day_paid)` ต่อวัน (overpay/ทิปวันหนึ่งไม่ลดวันอื่น). **single source** ใช้ร่วม `get_overall` (dashboard ค้างจ่าย), `notify_balance_query`, monthly report → ไม่ drift. ต่างจาก `compute_probation_resign` (presence-based unpaid×rate).
- **กดผ่านโปร** (`POST pass-probation` body `pass_date` เท่านั้น — ไม่มี `first_month_leave_days` แล้ว): คำนวณ **anchor** = วันที่ 1 ของเดือนถัดจาก `pass_date` (หรือ `pass_date` เองถ้ากดวันที่ 1 พอดี) → set `monthly_start_date=anchor`, `first_month_leave_days=monthly_leave_days` **แต่ยังไม่เปลี่ยน `employment_status`** — คงเป็น `'probation'` (จ่ายรายวันต่อ) จนกว่า `_promote_pending()` จะ flip ให้เมื่อถึง anchor.
- **Month-boundary rule (2026-07-12 rework):** กดผ่านโปรกลางเดือน → **จ่ายรายวันต่อจนสิ้นเดือนที่กด (pass-month)**, รายเดือนเริ่ม **วันที่ 1 ของเดือนถัดไป**. เหตุผล: จ่ายรายเดือนต้องเริ่มที่วันที่ 1 เสมอ (ไม่มี partial-month monthly). ถ้ากดผ่านโปรวันที่ 1 พอดี → anchor = วันนั้นเลย (ไม่ต้องรอเดือนถัดไป).
- **`_promote_pending()`** (helper ใน `main.py`): `UPDATE employees SET employment_status='active' WHERE employment_status='probation' AND monthly_start_date IS NOT NULL AND monthly_start_date <= today`. เรียก 3 จุด: (1) ท้าย `pass_probation` endpoint (flip ทันทีถ้า anchor = วันนี้/อดีต เช่นกดวันที่ 1 หรือ backdate), (2) `lifespan` ตอน startup (heal การ promote ที่พลาดตอนแอปดับ), (3) **daily job `promote_probation` เวลา 00:10** (ดู Scheduled Jobs) — คุมกรณี anchor เป็นอนาคตตอนกด แล้วมาถึงวันจริงระหว่างแอปรันอยู่.
- **Monthly anchor** = `monthly_start_date or start_date`. ทุก monthly/leave calc (payments, summary, overall, leave-balance, resign) ใช้ anchor → pro-rate/leave accrual เริ่มที่ anchor ไม่ใช่ start_date. แถวเก่า (monthly_start_date NULL) fallback = start_date (behavior เดิม).
- **Transition month** (เดือนที่ผ่านโปร = pass-month): **ทั้งเดือนยังเป็น daily** (`get_daily_payments` cap `work_date < monthly_start_date` = ยังไม่ถึง anchor). รายเดือนรอบแรกจริงคือเดือนของ anchor (เดือนถัดไป) — เดือนนั้นเป็น **full month เสมอ** (ไม่มี partial-month prorate สำหรับ monthly แล้ว เพราะ anchor คือวันที่ 1).
- **Resign ระหว่างโปร** = Σ **unpaid** work days × rate (วันที่ toggle paid แล้วไม่นับซ้ำ). ไม่มี monthly base.
- **Summary/Overall ระหว่างโปร** (`get_summary`/`get_overall` มี probation branch): นับเฉพาะวัน mark work (ไม่ default-fill), **ไม่มี holiday/leave/เงินเดือนรายเดือน**. คืน `employment_status='probation'` + `total_earned`/`total_paid`/`total_unpaid` (work × daily_rate). `export_payslip` ออก CSV รายวันสำหรับ probation. Frontend (detail/summary/list/payments) render daily-pay framing เมื่อ probation. **เหตุผล:** เดิม summary/overall ใช้ `default_status` (sunday) → probation ได้ holiday + เงินเดือนเต็มผิด.
  - **`get_summary` guard `month_all_daily`** (2026-07-12): เดือนที่อยู่ **ก่อน** `monthly_start_date` ทั้งเดือน (`month_end < monthly_start_date`) ยังคง daily framing แม้ `employment_status` โดน `_promote_pending()` flip เป็น `'active'` ไปแล้ว (เช่นดู summary ย้อนหลังของ pass-month หลังผ่านมาหลายเดือน) — กัน pass-month โดนรายงานเป็นเงินเดือนเต็มผิดๆ. `get_overall` **ยังไม่แก้** (all-time dashboard ยัง rough) — known limitation, ไม่ critical เพราะเป็นแค่ยอดรวมภาพกว้าง.
- **First-month leave days** (`first_month_leave_days`): ไม่มี popup ถามแล้ว — กดผ่านโปร set ให้อัตโนมัติ = `monthly_leave_days` เสมอ (transition month ตอนนี้คือ full month ของ anchor เดือนถัดไป ไม่ใช่ partial เดือนที่กด จึงไม่ต้องถามจำนวนวันหยุดเป็นพิเศษ). `compute_monthly_leave_balance` ยัง branch ตาม field นี้เหมือนเดิม (เดือนของ anchor ใช้ `first_month_leave_days`, เดือนอื่นใช้ `monthly_leave_days`) แต่ค่าตอนนี้เท่ากันเสมอสำหรับ maid ที่ผ่านโปรผ่าน flow ใหม่.

### Slip / Documents (file upload)
- `payment_method='transfer'` → แนบ slip ได้ทุก payment (daily + monthly period). เก็บ `/data/slips/`.
- เอกสาร id_card/passport/**other** หลายรูป/คน. `doc_type` เป็น enum (ปลอดภัยใน filename), `other` ใส่ชื่อผ่าน `doc_label` (display-only, escHtml ตอน render). เก็บ `/data/documents/`. Serve ผ่าน FastAPI route (หลัง nginx basic-auth). Validate type (jpg/png/webp/pdf) + ≤10MB. **ไม่อยู่ใน DB backup**.
- **⚠️ 413 Request Entity Too Large** ตอน upload รูปใหญ่ = nginx `client_max_body_size` (default 1MB). ตั้ง `25m` ใน `nginx/nginx.conf` (> app cap 10MB เพื่อให้ app ตอบ error สวยแทน nginx 413). หาก 413 ยังขึ้นหลัง deploy = DSM reverse proxy cap ของมันเอง.

### Payer (ผู้จ่าย)
- `paid_by` บน `salary_payments` + `daily_payments`. เลือกจาก dropdown ตอนกด "บันทึกจ่ายแล้ว" → ส่ง query `paid_by=`. Unmark → clear เป็น NULL. รายชื่อ payer = const `PAYERS = ["ฟิก", "ปุ๊ก", "ฟิก + ปุ๊ก"]` ใน app.js (แก้ที่เดียว) — เพิ่ม `"ฟิก + ปุ๊ก"` (2026-07-12) สำหรับกรณีจ่ายร่วมกัน, เก็บเป็น string ตรงๆ column เดิมไม่ต้องแก้ schema. แสดงเป็น badge "จ่ายโดย X" บนงวด/วันที่จ่ายแล้ว.

### Reminder Translation (static dict, ไม่ใช่ LLM แล้ว)
- **เปลี่ยนจาก MiMo LLM → static dict** (2026-06-25): reminder text เป็น free-text แต่ในทางปฏิบัติมีแค่ ~2-10 ข้อความคงที่ที่ owner ใช้จริง (แทบไม่เปลี่ยน) — เรียก LLM ทุกครั้งคือ over-engineering ที่มี failure mode (token truncation เคยทำให้พม่าหาย), latency, ต้องดูแล secrets โดยไม่จำเป็น.
- `reminder_i18n.py` เก็บ `REMINDERS: dict[str, dict[str, str]]` แมป Thai text ตรงตัว → `{my, en, lo, km}`. `lookup(text) -> dict | None` — sync, ไม่มี I/O.
- เรียกใช้ 4 จุดใน `main.py` (create_reminder, update_reminder, `_check_reminders` ตอน fire, test_reminder): ได้ผล lookup แล้ว cache เป็น JSON ใน `reminders.message_i18n` เหมือนเดิม.
- **เพิ่ม reminder text ใหม่ที่ต้องการแปล:** ต้องเพิ่ม entry ใน `REMINDERS` dict เอง (key = Thai text ตรงตัวเป๊ะ). ข้อความใหม่ที่ไม่ตรง key ใดๆ → `lookup()` คืน `None` → ส่ง Thai-only เงียบๆ (ไม่ error, ไม่ retry, ไม่มี auto-translate อีกแล้ว).
- ไฟล์ที่ลบไปแล้ว: `reminder_translate.py` (MiMo caller), `http_client.py` (vendored httpx+retry ใช้เฉพาะไฟล์นั้น). `MIMO_API_KEY`/`MIMO_BASE_URL`/`MIMO_MODEL` ลบออกจาก `secrets.manifest.yaml` แล้ว.

### โหมดวันหยุด 2 แบบ

#### `holiday_mode = 'sunday'` (default)
| สถานะ | Default ของ |
|-------|-------------|
| `work` | วันจันทร์–เสาร์ |
| `holiday` | วันอาทิตย์ |
| `compensatory` | ทำงานวันอาทิตย์ (+1 วัน) |
| `leave` | ลาวันทำงาน (−1 วัน) |

- **Balance** = `total_comp − total_leave`
- Balance สะสมตลอด → ชำระยอดรวมวันลาออก
- `max_leave_carry` = max debt: ถ้า balance < −max_leave_carry → หักจาก Period 2 ของเดือนนั้น

#### `holiday_mode = 'monthly'`
| สถานะ | Default ของ |
|-------|-------------|
| `work` | ทุกวัน (รวมอาทิตย์) |
| `leave` | วันที่แม่บ้านใช้โควต้าหยุด |

- ต้นเดือนได้รับ `monthly_leave_days` วัน (เข้า balance)
- `max_leave_carry` = ceiling ของ balance บวก: ถ้า balance ≥ max → ไม่สะสมเพิ่ม
- **Balance** = `accrued_total − used_total` (ลบ = debt)
- Debt ชำระวันลาออก (ไม่มี Period 2 deduction ในโหมดนี้)
- LINE webhook: compensatory → reject, leave ใช้ได้ทุกวัน

### Max Leave Carry Cap (sunday mode)
```
ถ้า effective_balance < −max_leave_carry:
    deduction_days = |effective_balance| − max_leave_carry
    หักจาก Period 2 × daily_rate
    carry-forward = −max_leave_carry
```

### Resignation Settlement
```
final = base_salary_last_month + (cumulative_balance × daily_rate)
```
- `cumulative_balance > 0` → ได้เงินเพิ่ม (มีชดเชยเกินลา)
- `cumulative_balance < 0` → หักเงิน (ลาเกินชดเชย)

---

## Environment Variables (ใน root `.env`)

| Variable | Required | Notes |
|----------|----------|-------|
| `TZ` | — | ตั้งใน compose (`Asia/Bangkok`) |
| `DATA_DIR` | — | default `/data` |
| `MAID_LINE_CHANNEL_ACCESS_TOKEN` | ❌ optional | ถ้าว่าง → ปิด LINE ทั้งหมด |
| `MAID_LINE_GROUP_ID` | ❌ optional | Group ID ขึ้นต้นด้วย `C` |
| `MAID_LINE_CHANNEL_SECRET` | ❌ optional | สำหรับ verify webhook signature |
| `NGINX_BASIC_AUTH_USER/PASS` | ❌ optional | เปิด HTTP Basic Auth (ยกเว้น `/webhook/line`) |
| `MONTHLY_REPORT_TIME` | ❌ optional | เวลาส่งรายงานเดือน (default `20:00`) |
| `MAID_PUBLIC_BASE_URL` | ❌ optional | URL สาธารณะของ maid-tracker (เช่น `https://<NAS_HOST>:15055`) — ใช้สำหรับ signed slip URL ส่ง LINE image (vault key: `stacks.maid_tracker.public_base_url`) |

**ถอดแล้ว (2026-06-25):** `MIMO_API_KEY`/`MIMO_BASE_URL`/`MIMO_MODEL` — reminder translation ย้ายจาก MiMo LLM call ไปเป็น static dict (`reminder_i18n.py`), ไม่ต้องใช้ secret/API ใดๆ แล้ว. ดูหัวข้อ "Reminder Translation" ด้านล่าง.

---

## API Endpoints หลัก

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/employees` | รายชื่อทั้งหมด |
| POST | `/api/employees` | สร้างใหม่ |
| GET/PUT | `/api/employees/{id}` | ดู/แก้ไข |
| DELETE | `/api/employees/{id}` | ลบ |
| GET | `/api/employees/{id}/attendance?year=&month=` | ดูสถานะรายวัน |
| POST | `/api/employees/{id}/attendance` | บันทึก/แก้ไขวัน |
| DELETE | `/api/employees/{id}/attendance/{work_date}` | ลบวัน (un-mark probation work day) |
| GET | `/api/employees/{id}/summary?year=&month=` | สรุปรายเดือน |
| GET | `/api/employees/{id}/overall` | ภาพรวมทั้งหมด |
| GET | `/api/employees/{id}/leave-balance` | ยอดวันหยุดสะสม (monthly mode) |
| GET | `/api/employees/{id}/payments?year=&month=` | ข้อมูลจ่ายเงิน |
| POST | `/api/employees/{id}/payments/{period}/toggle?year=&month=&paid_by=` | บันทึก/ยกเลิกจ่าย (`paid_by`=ผู้จ่าย ฟิก/ปุ๊ก, clear ตอน unmark) |
| POST | `/api/employees/{id}/pass-probation` | ผ่านโปร (body `pass_date` เท่านั้น) → set `monthly_start_date` = วันที่ 1 ของเดือนถัดไป (หรือ pass_date ถ้าเป็นวันที่ 1) + `first_month_leave_days=monthly_leave_days`; ยังคง `employment_status='probation'` จนกว่า anchor มาถึง (ดู `_promote_pending`) |
| DELETE | `/api/employees/{id}/pass-probation` | ยกเลิกผ่านโปร (กลับ probation) |
| GET | `/api/employees/{id}/daily-payments?year=&month=` | รายการจ่ายรายวันช่วงโปร (cap < monthly_start_date) |
| POST | `/api/employees/{id}/daily-payments/{work_date}/toggle?paid_by=&amount=` | บันทึก/ยกเลิกจ่ายรายวัน (`paid_by`=ผู้จ่าย, `amount`=override จำนวนเงิน optional `>0`, ไม่ส่ง=คำนวณ `rate×frac`) |
| POST | `/api/employees/{id}/daily-payments/{work_date}/amount?amount=` | แก้จำนวนเงินของวันที่จ่ายแล้ว (in-place, ยังคง paid) |
| POST | `/api/employees/{id}/daily-payments/{work_date}/slip` | upload slip รายวัน (multipart) |
| POST | `/api/employees/{id}/payments/{period}/slip?year=&month=` | upload slip งวดเดือน (multipart) |
| GET | `/api/slips/{fname}` | serve slip |
| POST/GET | `/api/employees/{id}/documents` | upload (multi-file `doc_type` enum id_card\|passport\|other + `doc_label` ถ้า other + `files`) / list เอกสาร |
| DELETE | `/api/employees/{id}/documents/{doc_id}` | ลบเอกสาร |
| GET | `/api/documents/{fname}` | serve เอกสาร |
| POST | `/api/employees/{id}/resign` | บันทึกลาออก |
| DELETE | `/api/employees/{id}/resign` | ยกเลิกลาออก |
| GET | `/api/employees/{id}/resign-summary` | สรุปการลาออก |
| GET | `/api/employees/{id}/export/attendance` | Export CSV |
| GET/POST | `/api/reminders` | จัดการ reminders |
| POST | `/webhook/line` | LINE webhook (public, skip auth) |

---

## SPA Routes (Hash-based)

| Hash | View |
|------|------|
| `#/` | รายชื่อแม่บ้าน |
| `#/employee/new` | เพิ่มใหม่ |
| `#/employee/:id` | ข้อมูล + ภาพรวม |
| `#/employee/:id/edit` | แก้ไข |
| `#/employee/:id/leaves?y=&m=` | ปฏิทิน + รายการลา |
| `#/employee/:id/summary?y=&m=` | สรุปรายเดือน |
| `#/employee/:id/payments?y=&m=` | จ่ายเงินเดือน |
| `#/employee/:id/attendance?y=&m=` | ปฏิทิน standalone |
| `#/reminders` | แจ้งเตือนงานประจำ |

---

## Scheduled Jobs (APScheduler)

| Job | Trigger | Action |
|-----|---------|--------|
| `check_reminders` | ทุก 1 นาที | ตรวจ reminders ที่ enabled และส่ง LINE |
| `monthly_report` | วันสุดท้ายของเดือน เวลา `MONTHLY_REPORT_TIME` | ส่งสรุปรายเดือนทาง LINE. แต่ละคนแนบ block แปลภาษา (`notify_language`) ใต้บล็อกไทย. **Probation** → แสดงแค่ `ค้างจ่าย ฿X` / `ไม่มียอดค้างจ่าย` (ไม่มี comp/leave). **Active** → balance เดิม resolve anchor=`monthly_start_date or start_date`. `line_notify._monthly_entry()` |
| `promote_probation` | ทุกวัน เวลา `00:10` | เรียก `_promote_pending()` — flip `employment_status` จาก `probation`→`active` ให้แม่บ้านที่ `monthly_start_date` (anchor) มาถึงแล้ว. เสริมการเรียกตอน pass-probation endpoint + app startup (`lifespan`) — คุมกรณี anchor เป็นอนาคตตอนกดแล้วมาถึงวันจริงระหว่างแอปรันค้างอยู่ |
