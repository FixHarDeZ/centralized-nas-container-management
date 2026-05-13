# Daily Log

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
