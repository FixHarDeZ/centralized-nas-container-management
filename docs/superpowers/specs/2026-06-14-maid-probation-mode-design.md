# maid-tracker — Probation Mode + Slip/Document Upload (Design)

Date: 2026-06-14
Stack: `maid-tracker/`

## Problem

แม่บ้านมาใหม่ยังไม่ผ่านโปร ต้องจ่ายเป็นรายวัน และยังไม่เปิดฟีเจอร์ลา. กำหนดเรตรายวันได้ตั้งแต่ตอนเพิ่มแม่บ้าน. เมื่อกดผ่านโปรแล้วเข้าโหมดจ่ายรายเดือนทันที และเดือนแรก (transition month) คิดเฉลี่ยรายวันให้เฉพาะวันตั้งแต่ผ่านโปร. เพิ่มระบบแนบสลิปโอนเงิน และอัปโหลดรูปบัตรประชาชน/passport.

## Core concept correction

"เข้าโหมดรายเดือน" = เปลี่ยน **วิธีจ่าย** จากรายวัน → เงินเดือน. เป็น axis ใหม่ (`employment_status`) **แยกจาก** `holiday_mode` (`sunday`｜`monthly`) ที่มีอยู่. หลังผ่านโปร แม่บ้านใช้ `holiday_mode` ที่เลือกตอนสร้าง (default `sunday`) — ไม่ถูกบังคับเป็น `monthly`.

3 axes อิสระ:
- `employment_status`: `probation` (จ่ายรายวัน, ลาปิด) ｜ `active` (จ่ายเงินเดือน, ลาเปิด)
- `holiday_mode`: `sunday` ｜ `monthly` (ใช้เมื่อ active เท่านั้น)
- `payment_method`: `cash` ｜ `transfer` (transfer → แนบสลิปได้)

---

## Unit 1 — Probation pay (รายวัน)

### Schema — `employees` เพิ่มคอลัมน์
| Column | Type | Notes |
|--------|------|-------|
| `employment_status` | TEXT DEFAULT `'active'` | `'probation'｜'active'`. แม่บ้านใหม่ที่สร้างผ่านฟอร์ม probation → `'probation'`. แถวเก่า migrate → `'active'` |
| `probation_daily_rate` | REAL | เรตรายวันช่วงโปร (กรอกตอนสร้าง) |
| `monthly_start_date` | TEXT | = วันผ่านโปร (YYYY-MM-DD). NULL ระหว่างโปร |

**Monthly anchor** = `monthly_start_date or start_date`. แถวเก่า (`monthly_start_date` NULL) fall back เป็น `start_date` → behavior เดิมไม่เปลี่ยน.

### Create form
กรอกตั้งแต่ตอนสร้างทั้งหมด: ข้อมูลทั่วไป + `probation_daily_rate` + config รายเดือนเต็ม (`monthly_salary`, `holiday_mode`, `monthly_leave_days`, `max_leave_carry`) + `payment_method`. ค่ารายเดือน dormant จนผ่านโปร.

มี toggle "เริ่มแบบ probation" — ถ้าเลือก → `employment_status='probation'`, `monthly_start_date=NULL`. ถ้าไม่เลือก → `active` ทันที (= flow เดิม).

### Probation tally
```
tally = Σ (attendance rows status='work' ระหว่าง start_date..min(today, pass_date-1))
        × (1.0 full | 0.5 half) × probation_daily_rate
```
- **ไม่มี default fill** ช่วงโปร — นับเฉพาะวันที่ mark `work` เท่านั้น (Q3).
- Leave/comp/holiday **ปิด** ช่วงโปร: attendance UI ซ่อน option เหล่านี้, LINE webhook reject `leave`/`compensatory` สำหรับแม่บ้าน probation, endpoint `leave-balance`/`summary` leave-section skip.

### จ่ายรายวัน (per-day payout) — table ใหม่ `daily_payments`
```sql
daily_payments (
  id INTEGER PRIMARY KEY,
  employee_id INTEGER NOT NULL,
  work_date TEXT NOT NULL,          -- YYYY-MM-DD
  amount REAL NOT NULL,             -- snapshot = probation_daily_rate × day_fraction ตอน mark paid
  paid_at TEXT,                     -- NULL = ยังไม่จ่าย
  slip_path TEXT,                   -- NULL ถ้า cash หรือยังไม่แนบ
  UNIQUE(employee_id, work_date)
)
```
- หน้า payments ช่วงโปร: list วัน work ที่ mark แล้ว แต่ละวันมี toggle paid + (ถ้า transfer) ปุ่ม upload slip.
- `amount` snapshot ตอน toggle paid เพื่อกันเรตเปลี่ยนย้อนหลัง.

### Pass probation action
ปุ่ม "ผ่านโปร" บนหน้า employee (แสดงเมื่อ `status='probation'`):
- รับ `pass_date` (default วันนี้, แก้ได้).
- set `monthly_start_date=pass_date`, `employment_status='active'`.
- confirm dialog ก่อนทำ (irreversible-ish; มี endpoint ยกเลิกได้ถ้าจำเป็น — set กลับ NULL/probation).
- หลังผ่าน → leave + monthly เปิดทันที.

### Transition month
แบ่งที่ `pass_date`:
- วัน `< pass_date` ในเดือนนั้น → probation daily (จาก `daily_payments`).
- วัน `>= pass_date` → monthly pro-rate.
- ไม่ double-count: monthly นับ Mon–Sat ตั้งแต่ anchor; probation นับวัน mark ก่อน anchor.

### monthly_start_date threading (จุดเสี่ยง correctness — ต้อง audit ทุก call site)
กฎ: monthly logic anchor ที่ `monthly_start_date or start_date`.
- `main.py get_payments` first-month detect (~741 `start_date.year==year and start_date.month==month`) + `first_month_after_15` (~753) + day range (~742 `range(start_date.day, …)`) → ใช้ anchor.
  - **Edge สำคัญ:** โปรข้ามเดือน (start 05-01, pass 06-20) → `start_date.month` (5) ≠ pass month (6) → first-month branch เดิมไม่ fire → June จ่ายเต็มเดือนผิด. ต้อง fix ให้ detect ที่ anchor month.
- `calc.py` 4 ฟังก์ชันรับ `start_date` → ส่ง anchor แทน: `compute_overall_balance`, `compute_monthly_leave_balance`, `compute_leave_deduction`, `compute_resign_summary`.
- attendance default-fill (`main.py ~592 if d < start_date`) → status-aware: ระหว่างโปร ไม่ default-fill (วัน work ต้อง mark เอง).

### Leave credit เดือน transition — **DEFAULT (review)**
ผ่านโปรกลางเดือน → ได้ leave quota **เต็มเดือน** นั้น (ตรงกับ logic เดิมที่ credit เต็มแม้ start ปลายเดือน). Alternative: pro-rate / ไม่ได้จนเดือนถัดไป — ถ้าไม่เห็นด้วยแก้ที่ review gate.

### Resign ระหว่างโปร
settlement = Σ unpaid probation work days × `probation_daily_rate`. ไม่มี monthly base, ไม่มี comp/leave balance. `compute_resign_summary` แตก branch ตาม `employment_status`.

---

## Unit 2 — Slip upload (transfer payments)

ใช้กับ **ทุก payment** (probation daily + monthly period 1/2).

### Schema
- `daily_payments.slip_path` (Unit 1).
- `salary_payments` เพิ่ม `slip_path TEXT`.

### Behavior
- แม่บ้าน `payment_method='transfer'` → แต่ละ payment มีปุ่ม upload slip.
- `payment_method='cash'` → ไม่มีปุ่ม slip.
- `payment_method` แก้ได้ในหน้า edit (cash↔transfer) — **DEFAULT (review)**.

### Storage
- ไฟล์ที่ `/data/slips/`. ชื่อ `slip_<empid>_<daily|p1|p2>_<key>.<ext>` (key = date หรือ year-month-period).
- Endpoint upload (multipart) + serve, **หลัง basic-auth เดียวกับ stack**.

---

## Unit 3 — ID/Passport documents

อัปโหลดตอนสร้างแม่บ้าน, **หลายรูปได้**, เพิ่ม/ลบทีหลังในหน้า edit.

### Schema — table ใหม่ `employee_documents`
```sql
employee_documents (
  id INTEGER PRIMARY KEY,
  employee_id INTEGER NOT NULL,
  doc_type TEXT NOT NULL,           -- 'id_card' | 'passport'
  file_path TEXT NOT NULL,
  uploaded_at TEXT NOT NULL
)
```

### Storage
- ไฟล์ที่ `/data/documents/`. Endpoint upload (multipart, หลายไฟล์) + list + delete + serve, **หลัง basic-auth**.

---

## Shared file-upload infra (Unit 2 + 3)
- เพิ่ม dependency `python-multipart` ใน `requirements.txt`.
- Validate content-type (image/* + pdf), จำกัดขนาด.
- Serve ผ่าน FastAPI route (ไม่ mount static ตรงๆ) เพื่อให้ basic-auth/nginx ครอบ.
- **Backup scope:** `_backup_db()` cover **เฉพาะ SQLite**. `/data/slips`, `/data/documents` **out of scope** ของ auto-backup (note ไว้ — off-NAS backup ทำภายหลังถ้าต้องการ).

---

## API additions (ร่าง)
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/employees/{id}/pass-probation` | ผ่านโปร (body: `pass_date`) |
| DELETE | `/api/employees/{id}/pass-probation` | ยกเลิกผ่านโปร (กลับ probation) |
| GET | `/api/employees/{id}/daily-payments?year=&month=` | รายการจ่ายรายวันช่วงโปร |
| POST | `/api/employees/{id}/daily-payments/{work_date}/toggle` | บันทึก/ยกเลิกจ่ายรายวัน |
| POST | `/api/employees/{id}/payments/{period}/slip?year=&month=` | upload slip งวดเดือน |
| POST | `/api/employees/{id}/daily-payments/{work_date}/slip` | upload slip รายวัน |
| GET | `/api/slips/{...}` | serve slip (auth) |
| POST | `/api/employees/{id}/documents` | upload เอกสาร (multi-file, `doc_type`) |
| GET | `/api/employees/{id}/documents` | list เอกสาร |
| DELETE | `/api/employees/{id}/documents/{doc_id}` | ลบเอกสาร |
| GET | `/api/documents/{...}` | serve เอกสาร (auth) |

## SPA changes (ร่าง)
- Create/edit form: probation toggle, `probation_daily_rate`, `payment_method`, document upload section.
- Employee page: ปุ่ม "ผ่านโปร" + badge สถานะ probation; ซ่อน leave UI ระหว่างโปร.
- Payments view: โหมด probation → list รายวัน + toggle + slip; โหมด active → 2 งวดเดิม + slip.
- Attendance calendar: ระหว่างโปร ซ่อน leave/comp/holiday status options.

## Testing
- Probation tally: marked work days only, full/half.
- Pass mid-month → transition split ถูก (probation portion + monthly pro-rate, ไม่ double-count).
- **Edge:** โปรข้ามเดือน (start 05-01, pass 06-20) → June pro-rate ถูก (ไม่จ่ายเต็ม).
- Migration: แถวเก่า → active/cash/anchor=start_date, behavior เดิมไม่เปลี่ยน (regression).
- Resign ระหว่างโปร → unpaid days × rate.
- Slip/document upload: content-type/size validate, serve หลัง auth, multi-file docs.

## Out of scope
- Backup ของ `/data/slips`, `/data/documents`.
- PDF payslip, multi-worker schema.
