# Daily Log

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
