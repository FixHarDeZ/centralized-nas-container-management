# maid-tracker — Index (Memory File)

อัปเดตล่าสุด: 2026-05-12

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
  created_at TEXT
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
  leave_deduction_days REAL DEFAULT 0
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
- เดือนแรกที่เริ่มงาน (partial month) → pro-rate เฉพาะวัน Mon–Sat ตั้งแต่ start_date ถึงสิ้นเดือน

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
| GET | `/api/employees/{id}/summary?year=&month=` | สรุปรายเดือน |
| GET | `/api/employees/{id}/overall` | ภาพรวมทั้งหมด |
| GET | `/api/employees/{id}/leave-balance` | ยอดวันหยุดสะสม (monthly mode) |
| GET | `/api/employees/{id}/payments?year=&month=` | ข้อมูลจ่ายเงิน |
| POST | `/api/employees/{id}/payments/{period}/toggle?year=&month=` | บันทึก/ยกเลิกจ่าย |
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
