# maid-tracker — Index (Memory File)

อัปเดตล่าสุด: 2026-06-14

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
| `line_notify.py` | LINE Messaging API push functions |
| `keywords.py` | LINE keyword lists — แก้ที่นี่เพื่อเพิ่ม/ลด trigger phrase |
| `static/app.js` | SPA frontend — routing, views, i18n (TH/EN) |
| `static/style.css` | Custom styles + calendar grid |
| `docker-compose.yml` | port `5055:8000`, volume, env_file `../.env` |

---

## DB Schema (ล่าสุด — รวม migration columns)

```sql
employees (
  id, name, age, nationality, phone, line_id, facebook,
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
  monthly_start_date TEXT,                  -- = วันผ่านโปร; NULL ระหว่างโปร. monthly calc anchor = monthly_start_date or start_date
  payment_method TEXT DEFAULT 'cash'        -- 'cash' | 'transfer' (transfer → แนบ slip ได้)
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
  slip_path TEXT               -- ไฟล์ slip โอนเงิน (NULL = ไม่มี)
)

daily_payments (                -- จ่ายรายวันช่วง probation (per work day)
  id, employee_id, work_date TEXT,
  amount REAL,                 -- snapshot = probation_daily_rate × fraction ตอน mark paid
  paid_at TEXT,                -- NULL = ยังไม่จ่าย
  slip_path TEXT,
  UNIQUE(employee_id, work_date)
)

employee_documents (            -- รูปบัตรประชาชน/passport (หลายรูป/คน)
  id, employee_id,
  doc_type TEXT,               -- 'id_card' | 'passport'
  file_path TEXT, uploaded_at TEXT
)

reminders (
  id, name, message,
  enabled INTEGER DEFAULT 1,
  schedule_type TEXT,          -- 'month_day_digit' | 'weekday'
  schedule_value TEXT,         -- digit: "0","0,5" | weekday: "0,3" (0=Mon…6=Sun)
  send_time TEXT,              -- "HH:MM"
  last_sent_date TEXT,
  created_at TEXT
)
```

---

## Logic การคำนวณ

### อัตราค่าจ้างรายวัน
```
daily_rate = monthly_salary / working_days_in_month
working_days_in_month = วันจันทร์–เสาร์ทั้งหมดในเดือน (ไม่นับอาทิตย์)
```

### เงินเดือนรายเดือน (พื้นฐาน)
- จ่าย **2 รอบ**: Period 1 วันที่ 15 = `salary / 2`, Period 2 สิ้นเดือน = `salary / 2`
- เดือนแรกที่เริ่มงาน (partial month) → pro-rate เฉพาะวัน Mon–Sat ตั้งแต่ **anchor** ถึงสิ้นเดือน

### Probation mode (จ่ายรายวัน — axis `employment_status`)
- **`employment_status='probation'`**: จ่ายรายวัน, **ลา/ชดเชย/holiday ปิด** (attendance default = `unmarked`, POST + LINE webhook reject leave). `get_payments` คืน `[]` (ไม่มีงวดเดือน).
- **Probation tally** = attendance rows status=`work` (full=1/half=0.5) ที่ mark เอง × `probation_daily_rate`. ไม่มี default-fill. จ่ายรายวันผ่าน `daily_payments` (toggle paid ต่อวัน, `amount` snapshot).
- **Mark work day (UI):** ปุ่ม "ลงเวลาทำงาน" บนหน้า detail → ปฏิทิน `/attendance`. ช่วงโปร cell toggle **work ↔ unmarked** เท่านั้น (คลิกซ้ำ = ลบ via DELETE attendance). leave/comp/holiday ปิด. `get_attendance` คืน `unmarked` สำหรับวันที่ยังไม่ mark.
- **กดผ่านโปร** (`POST pass-probation` body `pass_date`): set `monthly_start_date=pass_date`, `employment_status='active'` → เปิด leave + monthly ทันที.
- **Monthly anchor** = `monthly_start_date or start_date`. ทุก monthly/leave calc (payments, summary, overall, leave-balance, resign) ใช้ anchor → pro-rate/leave accrual เริ่มที่วันผ่านโปร ไม่ใช่ start_date. แถวเก่า (monthly_start_date NULL) fallback = start_date (behavior เดิม).
- **Transition month** (เดือนที่ผ่านโปร): วัน `< pass_date` = daily (`get_daily_payments` cap `work_date < monthly_start_date`), วัน `>= pass_date` = monthly pro-rate. ไม่ double-pay/orphan. ถ้า pass_date หลังวันที่ 15 → period 1 skip, period 2 = full prorated base.
- **Resign ระหว่างโปร** = Σ **unpaid** work days × rate (วันที่ toggle paid แล้วไม่นับซ้ำ). ไม่มี monthly base.

### Slip / Documents (file upload)
- `payment_method='transfer'` → แนบ slip ได้ทุก payment (daily + monthly period). เก็บ `/data/slips/`.
- เอกสาร id_card/passport หลายรูป/คน. เก็บ `/data/documents/`. Serve ผ่าน FastAPI route (หลัง nginx basic-auth). Validate type (jpg/png/webp/pdf) + ≤10MB. **ไม่อยู่ใน DB backup** (`_backup_db` = SQLite เท่านั้น).

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
| POST | `/api/employees/{id}/payments/{period}/toggle?year=&month=` | บันทึก/ยกเลิกจ่าย |
| POST | `/api/employees/{id}/pass-probation` | ผ่านโปร (body `pass_date`) → active + set monthly_start_date |
| DELETE | `/api/employees/{id}/pass-probation` | ยกเลิกผ่านโปร (กลับ probation) |
| GET | `/api/employees/{id}/daily-payments?year=&month=` | รายการจ่ายรายวันช่วงโปร (cap < monthly_start_date) |
| POST | `/api/employees/{id}/daily-payments/{work_date}/toggle` | บันทึก/ยกเลิกจ่ายรายวัน |
| POST | `/api/employees/{id}/daily-payments/{work_date}/slip` | upload slip รายวัน (multipart) |
| POST | `/api/employees/{id}/payments/{period}/slip?year=&month=` | upload slip งวดเดือน (multipart) |
| GET | `/api/slips/{fname}` | serve slip |
| POST/GET | `/api/employees/{id}/documents` | upload (multi-file `doc_type`+`files`) / list เอกสาร |
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
| `monthly_report` | วันสุดท้ายของเดือน เวลา `MONTHLY_REPORT_TIME` | ส่งสรุปรายเดือนทาง LINE |
