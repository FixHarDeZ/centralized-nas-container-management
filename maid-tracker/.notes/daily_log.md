# Daily Log

---

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
