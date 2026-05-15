# Daily Log

## 2026-05-15

### maid-tracker — code cleanup (clean code)

**สิ่งที่ทำ (3 files, ~30 lines reduced):**

**calc.py**
- ลบ `import calendar as _cal` ใน `compute_leave_deduction` — `calendar` import อยู่ top-level แล้ว

**line_notify.py**
- ลบ `_` prefix จาก import aliases (`_compute_overall_balance` → `compute_overall_balance`, `_compute_resign_summary` → `compute_resign_summary`) — `_` prefix บน imported name ไม่มีความหมายใน Python

**main.py**
- เพิ่ม `Response` เข้า top-level imports (เลิกใช้ local import ใน middleware)
- ลบ `daily_rate` จาก calc imports — ไม่เคยถูกเรียกใน main.py
- เพิ่ม `_TZ = ZoneInfo(...)` module-level constant แทน inline construction 3 จุด (`_check_reminders`, `_send_monthly_report`, `line_webhook`)
- ลบ `_AUTH_REALM = b"Basic realm..."` — define แล้วไม่ใช้ (dead code)
- ลบ docstring ของ `basic_auth_middleware` — ซ้ำกับ function name
- ลบ alignment spaces ใน `basic_auth_middleware` (`decoded    =` → `decoded =`)
- ลบ 9 keyword aliases (`_LEAVE_KEYWORDS = LEAVE_KEYWORDS` ฯลฯ) — import แล้ว re-assign ทันทีโดยไม่มีเหตุผล
- แก้ `_YESTERDAY_KEYWORDS` → `YESTERDAY_KEYWORDS` ใน `_parse_target_date`
- ลบ alignment spaces และเปลี่ยน `conn2` → `conn` ใน `_check_reminders`
- แก้ alignment ใน `_send_monthly_report` (`tz        =` → `tz =`)
- ลบ duplicate DB fetch ใน `upsert_attendance` — employee fetch ซ้ำ 2 ครั้ง เอา `emp = dict(emp)` ขึ้น
- Refactor `toggle_payment`: แทนที่ ~20 บรรทัด deduction+amount calculation ด้วย `_compute_period_amount(emp, year, month, period)` ที่มีอยู่แล้ว
- แก้ `_LEAVE/COMP/BALANCE/PAYMENT_KEYWORDS` → public names ใน `line_webhook`
- ลบ `import calendar as _cal` ใน `line_webhook` — `calendar` import อยู่ top-level แล้ว
- ลบ `tz_inner = ZoneInfo(...)` ใน `line_webhook` — ซ้ำกับ `tz` ที่ประกาศไว้แล้วในฟังก์ชันเดียวกัน

**ไม่มีการเปลี่ยน logic หรือ behavior** — cleanup เท่านั้น

---

### line-secretary — code cleanup (clencode)

**สิ่งที่ทำ:**
- `agent.py`: ลบ dead variable `location` ออกจากทุก branch ใน `run()` — ถูก assign 6 ครั้งแต่ไม่เคยอ่าน (`loc_name` คำนวณแยกจาก `proposals[0]` โดยตรง)
- `main.py`: ย้าย `import notion as notion_mod` จากภายในฟังก์ชัน debug 3 จุด ขึ้นไป top-level import
- `notion.py`: ลบ blank line เกินระหว่าง `_prop_value` และ `search`

**ไม่มีการเปลี่ยน logic หรือ behavior** — cleanup เท่านั้น
