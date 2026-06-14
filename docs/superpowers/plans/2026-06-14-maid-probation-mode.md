# maid-tracker Probation Mode + Slip/Document Upload — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers-subagent-driven-development (recommended) or superpowers-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** เพิ่มโหมด probation (จ่ายรายวัน, ลาปิด) ให้แม่บ้านใหม่ + ปุ่มผ่านโปรเข้าโหมดเงินเดือน (transition month แบ่งที่วันผ่านโปร) + แนบสลิปโอนเงินทุก payment + อัปโหลดรูปบัตร/passport หลายรูป.

**Architecture:** เพิ่ม axis `employment_status` (probation｜active) แยกจาก `holiday_mode` เดิม. Monthly calc ทั้งหมด anchor ที่ `monthly_start_date or start_date`. Probation จ่ายรายวันผ่าน table ใหม่ `daily_payments`. File upload (slip + docs) ใช้ FastAPI multipart + serve route หลัง basic-auth, เก็บใน `/data/slips`, `/data/documents`.

**Tech Stack:** FastAPI, SQLite, APScheduler, vanilla JS SPA. `python-multipart` มีใน requirements แล้ว. Test: pytest (เพิ่มใหม่) เฉพาะ calc-layer.

**Spec:** `docs/superpowers/specs/2026-06-14-maid-probation-mode-design.md`

**Key files:**
- `maid-tracker/main.py` — schema/migration, endpoints, models
- `maid-tracker/calc.py` — probation tally + monthly anchor threading
- `maid-tracker/static/app.js` — SPA forms/views
- `maid-tracker/line_notify.py` — webhook reject leave during probation
- `maid-tracker/tests/` — pytest (ใหม่)
- `maid-tracker/requirements.txt` — เพิ่ม pytest

**Defaults locked (review-confirmed):**
- Leave credit เดือน transition = เต็มเดือน.
- `payment_method` แก้ได้ภายหลัง.
- `daily_payments.amount` = snapshot ตอน toggle paid.

---

## Phase 0 — Test infra + migration

### Task 0.1: pytest harness + temp-DB fixture

**Files:**
- Create: `maid-tracker/tests/__init__.py`
- Create: `maid-tracker/tests/conftest.py`
- Modify: `maid-tracker/requirements.txt`

- [ ] **Step 1: เพิ่ม pytest ใน requirements**

เพิ่มบรรทัดท้าย `requirements.txt`:
```
pytest==8.3.4
```

- [ ] **Step 2: conftest fixture ที่ตั้ง DATA_DIR ก่อน import calc**

`tests/conftest.py`:
```python
import os
import sqlite3
import tempfile
import pytest


@pytest.fixture
def db(monkeypatch):
    """Temp SQLite DB with the maid schema; sets DATA_DIR so calc.py picks it up."""
    tmp = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmp)
    db_path = os.path.join(tmp, "maid_tracker.db")
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT, start_date TEXT, monthly_salary REAL,
            max_leave_carry REAL, holiday_mode TEXT DEFAULT 'sunday',
            monthly_leave_days REAL DEFAULT 0,
            employment_status TEXT DEFAULT 'active',
            probation_daily_rate REAL, monthly_start_date TEXT,
            payment_method TEXT DEFAULT 'cash', end_date TEXT
        );
        CREATE TABLE attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER, work_date TEXT, status TEXT,
            note TEXT, half_day INTEGER DEFAULT 0,
            UNIQUE(employee_id, work_date)
        );
        CREATE TABLE daily_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER, work_date TEXT, amount REAL,
            paid_at TEXT, slip_path TEXT,
            UNIQUE(employee_id, work_date)
        );
        """
    )
    conn.commit()
    # calc.py reads DB_PATH from env at import time — import lazily inside tests
    yield conn
    conn.close()


def add_emp(conn, **kw):
    cols = ", ".join(kw.keys())
    qs = ", ".join("?" for _ in kw)
    cur = conn.execute(f"INSERT INTO employees ({cols}) VALUES ({qs})", tuple(kw.values()))
    conn.commit()
    return cur.lastrowid


def add_att(conn, emp_id, work_date, status, half_day=0):
    conn.execute(
        "INSERT INTO attendance (employee_id, work_date, status, half_day) VALUES (?,?,?,?)",
        (emp_id, work_date, status, half_day),
    )
    conn.commit()
```

- [ ] **Step 3: smoke test — fixture สร้าง schema ได้**

`tests/test_smoke.py`:
```python
def test_schema(db):
    cols = [r[1] for r in db.execute("PRAGMA table_info(employees)").fetchall()]
    assert "employment_status" in cols
    assert "probation_daily_rate" in cols
```

- [ ] **Step 4: รัน — ต้อง PASS**

Run: `cd maid-tracker && python -m pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add maid-tracker/tests maid-tracker/requirements.txt
git commit -m "test(maid-tracker): pytest harness + temp-db fixture"
```

> **หมายเหตุ calc.py import:** `calc.py` อ่าน `DB_PATH` จาก env ตอน import. ใน test ให้ `import importlib; import calc; importlib.reload(calc)` หลัง `monkeypatch.setenv` หรือ import calc ภายในฟังก์ชันเทสต์ หลัง fixture ตั้ง env แล้ว. เลือกแบบ import-in-test เพื่อความชัด.

---

### Task 0.2: DB migration — คอลัมน์/ตารางใหม่

**Files:**
- Modify: `maid-tracker/main.py:235-262` (migration block ใน `init_db`)

- [ ] **Step 1: เพิ่ม ALTER + CREATE TABLE ใน `init_db` migration block**

หลัง block holiday_mode (`main.py:261`) เพิ่ม:
```python
    # Probation mode migration
    for col, definition in [
        ("employment_status", "TEXT DEFAULT 'active'"),
        ("probation_daily_rate", "REAL"),
        ("monthly_start_date", "TEXT"),
        ("payment_method", "TEXT DEFAULT 'cash'"),
    ]:
        try:
            c.execute(f"ALTER TABLE employees ADD COLUMN {col} {definition}")
        except Exception:
            pass
    # Slip path on monthly payments
    try:
        c.execute("ALTER TABLE salary_payments ADD COLUMN slip_path TEXT")
    except Exception:
        pass
    # New tables
    c.executescript("""
        CREATE TABLE IF NOT EXISTS daily_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            work_date TEXT NOT NULL,
            amount REAL NOT NULL,
            paid_at TEXT,
            slip_path TEXT,
            UNIQUE(employee_id, work_date),
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        );
        CREATE TABLE IF NOT EXISTS employee_documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            doc_type TEXT NOT NULL,
            file_path TEXT NOT NULL,
            uploaded_at TEXT NOT NULL,
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        );
    """)
```

- [ ] **Step 2: verify migration idempotent + existing rows = active/cash**

Run: `cd maid-tracker && DATA_DIR=$(mktemp -d) python -c "import main; import sqlite3,os; c=sqlite3.connect(os.path.join(os.environ['DATA_DIR'],'maid_tracker.db')); print([r[1] for r in c.execute('PRAGMA table_info(employees)')]); print([r[0] for r in c.execute('SELECT name FROM sqlite_master WHERE type=\"table\"')])"`
Expected: เห็น `employment_status`/`probation_daily_rate`/`monthly_start_date`/`payment_method` + tables `daily_payments`, `employee_documents`. รันซ้ำไม่ error.

- [ ] **Step 3: Commit**

```bash
git add maid-tracker/main.py
git commit -m "feat(maid-tracker): db migration for probation + slip + documents"
```

---

## Phase 1 — Probation pay calc (TDD core)

> **Boundary rule (one source of truth):** วันหนึ่งเป็น "probation day" ⟺ `monthly_start_date is None` **หรือ** `work_date < monthly_start_date`. ทุก call site (`compute_probation_tally` up_to, `get_daily_payments` cap, `toggle_daily_payment` guard, resign) ต้องใช้กฎเดียวกันนี้. Task 1.0 ทำ helper, Task ที่เหลือเรียกใช้.

### Task 1.0: boundary helper + transition-boundary test

**Files:**
- Modify: `maid-tracker/calc.py` (helper)
- Test: `maid-tracker/tests/test_probation.py`

- [ ] **Step 1: failing test — boundary ที่วันผ่านโปร (pre-pass = probation, on/after = monthly)**

`tests/test_probation.py` (ต้นไฟล์ มี `_calc` helper ตาม Task 1.1):
```python
def test_probation_day_boundary(db, monkeypatch):
    calc = _calc(monkeypatch)
    from datetime import date
    # not passed yet → every day is probation
    assert calc.is_probation_day(date(2026, 6, 25), None) is True
    # passed on 06-20: pre-pass = probation, on/after = monthly
    assert calc.is_probation_day(date(2026, 6, 19), date(2026, 6, 20)) is True
    assert calc.is_probation_day(date(2026, 6, 20), date(2026, 6, 20)) is False
    assert calc.is_probation_day(date(2026, 6, 21), date(2026, 6, 20)) is False
```

- [ ] **Step 2: รัน — FAIL (no is_probation_day)**

Run: `cd maid-tracker && python -m pytest tests/test_probation.py::test_probation_day_boundary -v`
Expected: FAIL `AttributeError ... is_probation_day`

- [ ] **Step 3: implement helper ใน calc.py**

```python
def is_probation_day(d: date, monthly_start_date: date | None) -> bool:
    """A day is a probation (daily-pay) day iff not yet passed, or strictly before pass date."""
    return monthly_start_date is None or d < monthly_start_date


def probation_up_to(monthly_start_date: date | None, today: date) -> date:
    """Upper bound (inclusive) for probation tally: day before pass date, else today."""
    if monthly_start_date is None:
        return today
    return min(today, monthly_start_date - timedelta(days=1))
```

- [ ] **Step 4: รัน — PASS**

Run: `cd maid-tracker && python -m pytest tests/test_probation.py::test_probation_day_boundary -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add maid-tracker/calc.py maid-tracker/tests/test_probation.py
git commit -m "feat(maid-tracker): probation/monthly day boundary helper"
```

> Task 1.1 `compute_probation_tally` caller ใน main.py ใช้ `probation_up_to(monthly_start_date, today)` เป็น `up_to`. `get_daily_payments`/`toggle` ใช้ `is_probation_day` (หรือ `work_date < monthly_start_date` ตรงๆ ตามที่ implement ใน Task 1.5).

### Task 1.1: `compute_probation_tally` ใน calc.py

**Files:**
- Modify: `maid-tracker/calc.py` (เพิ่มฟังก์ชันใหม่)
- Test: `maid-tracker/tests/test_probation.py`

- [ ] **Step 1: failing test — นับเฉพาะวัน mark work, full=1/half=0.5, ตัดที่ pass_date**

`tests/test_probation.py`:
```python
from datetime import date
from tests.conftest import add_emp, add_att


def _calc(monkeypatch):
    import importlib, calc
    importlib.reload(calc)
    return calc


def test_probation_tally_counts_marked_work_only(db, monkeypatch):
    calc = _calc(monkeypatch)
    eid = add_emp(db, name="A", start_date="2026-06-01", monthly_salary=15000,
                  employment_status="probation", probation_daily_rate=400)
    add_att(db, eid, "2026-06-01", "work")           # +400
    add_att(db, eid, "2026-06-02", "work", half_day=1)  # +200
    # 06-03 not marked → 0
    add_att(db, eid, "2026-06-04", "leave")          # ignored in probation
    r = calc.compute_probation_tally(eid, date(2026, 6, 1), 400.0, up_to=date(2026, 6, 30))
    assert r["total_days"] == 1.5
    assert r["amount"] == 600.0


def test_probation_tally_stops_before_pass_date(db, monkeypatch):
    calc = _calc(monkeypatch)
    eid = add_emp(db, name="B", start_date="2026-06-01", monthly_salary=15000,
                  employment_status="probation", probation_daily_rate=400)
    add_att(db, eid, "2026-06-18", "work")
    add_att(db, eid, "2026-06-20", "work")   # on/after pass_date → excluded
    r = calc.compute_probation_tally(eid, date(2026, 6, 1), 400.0, up_to=date(2026, 6, 19))
    assert r["total_days"] == 1.0
    assert r["amount"] == 400.0
```

- [ ] **Step 2: รัน — FAIL (no compute_probation_tally)**

Run: `cd maid-tracker && python -m pytest tests/test_probation.py -v`
Expected: FAIL `AttributeError: module 'calc' has no attribute 'compute_probation_tally'`

- [ ] **Step 3: implement `compute_probation_tally`**

เพิ่มใน `calc.py`:
```python
def compute_probation_tally(
    emp_id: int,
    start_date: date,
    probation_daily_rate: float,
    up_to: date | None = None,
) -> dict:
    """
    Probation pay = sum of attendance rows status='work' (full=1.0, half=0.5)
    in [start_date, up_to] × probation_daily_rate.
    No default fill — only explicitly marked work days count. Leave/comp ignored.
    `up_to` should be min(today, pass_date - 1 day) for transition handling.
    """
    end = up_to or date.today()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT work_date, status, half_day FROM attendance "
        "WHERE employee_id=? AND status='work' AND work_date >= ? AND work_date <= ?",
        (emp_id, start_date.isoformat(), end.isoformat()),
    ).fetchall()
    conn.close()
    total = 0.0
    for r in rows:
        total += 0.5 if r["half_day"] else 1.0
    return {
        "total_days": round(total, 2),
        "amount": round(total * probation_daily_rate, 2),
    }
```

- [ ] **Step 4: รัน — PASS**

Run: `cd maid-tracker && python -m pytest tests/test_probation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add maid-tracker/calc.py maid-tracker/tests/test_probation.py
git commit -m "feat(maid-tracker): compute_probation_tally daily-pay calc"
```

---

### Task 1.2: Monthly anchor threading ใน calc.py

ใช้ `monthly_start_date or start_date` เป็น anchor. ฟังก์ชัน calc รับ `start_date` อยู่แล้ว — caller (main.py) จะส่ง anchor ให้. ฟังก์ชัน calc **ไม่ต้องแก้ signature** แค่ caller ส่งค่าถูก. **แต่** ต้องเพิ่มเทสต์ยืนยันว่า pro-rate/leave ทำงานถูกเมื่อ anchor ≠ start_date (โดยเรียกด้วย anchor).

**Files:**
- Test: `maid-tracker/tests/test_probation.py`

- [ ] **Step 1: test — `compute_resign_summary` ด้วย anchor (monthly_start_date) ให้ base pro-rate ถูก**

เพิ่มใน `tests/test_probation.py`:
```python
def test_resign_uses_anchor_for_first_month_prorate(db, monkeypatch):
    calc = _calc(monkeypatch)
    # passed probation on 06-20; resign 06-30. base = monthly_salary/Mon-Sat × billable(20..30)
    eid = add_emp(db, name="C", start_date="2026-05-01", monthly_salary=15600,
                  employment_status="active", monthly_start_date="2026-06-20")
    anchor = date(2026, 6, 20)
    r = calc.compute_resign_summary(eid, anchor, date(2026, 6, 30), 15600.0, holiday_mode="sunday")
    # June Mon-Sat = 26 working days → dr = 600. billable 20..30 Mon-Sat:
    # 20 Sat,22 Mon,23,24,25,26,27 Sat,29 Mon,30 = 9 days → 5400
    assert r["daily_rate"] == 600.0
    assert r["base_salary"] == 5400.0
```

- [ ] **Step 2: รัน — PASS (calc รับ start_date param อยู่แล้ว, ส่ง anchor ได้)**

Run: `cd maid-tracker && python -m pytest tests/test_probation.py::test_resign_uses_anchor_for_first_month_prorate -v`
Expected: PASS (ยืนยันว่า calc ใช้ param ที่ส่งเป็น anchor ได้ — ไม่ hardcode start_date)

> ถ้า FAIL: ตรวจว่าไม่มีจุดใน calc อ่าน start_date จากที่อื่นนอกจาก param. (มีแล้ว — ทุกฟังก์ชันรับ `start_date` เป็น argument.)

- [ ] **Step 3: Commit**

```bash
git add maid-tracker/tests/test_probation.py
git commit -m "test(maid-tracker): monthly anchor prorate via param"
```

---

### Task 1.3: `get_payments` ใช้ monthly anchor + edge ข้ามเดือน

**Files:**
- Modify: `maid-tracker/main.py:712-765` (`get_payments`)
- Modify: `maid-tracker/main.py` `_compute_period_amount` helper (ค้นหา def แล้วแก้ให้ใช้ anchor เช่นกัน)

- [ ] **Step 1: แก้ `get_payments` ให้ anchor + skip periods ตอน probation**

ใน `get_payments` หลัง `start_date = date.fromisoformat(emp["start_date"])` (line ~712) เพิ่ม:
```python
    # Still in probation → no monthly periods at all (pay is daily via daily-payments)
    if emp.get("employment_status") == "probation":
        conn.close()
        return []
    anchor = date.fromisoformat(emp["monthly_start_date"]) if emp.get("monthly_start_date") else start_date
```
> หมายเหตุ: transition month (ผ่านโปรแล้ว, anchor=pass_date) — anchor logic เดิมจัดการถูก: ถ้า pass_date หลังวันที่ 15 → period 1 skip (`anchor <= mid_day` เป็น False), period 2 = prorated base. ไม่ต้องแก้เพิ่ม.
แล้วแทนที่ทุกจุดที่ตรรกะ "first month / pro-rate / period skip" ใช้ `start_date`:
- line ~741 `if start_date.year == year and start_date.month == month:` → `anchor`
- line ~743 `range(start_date.day, n + 1)` → `range(anchor.day, n + 1)`
- line ~753-756 `first_month_after_15` block: `start_date` → `anchor`
- line ~765 `compute_leave_deduction(..., start_date)` → `anchor`
- line ~772 period-1 skip `start_date <= mid_day` → `anchor <= mid_day`
- line ~788 period-2 `start_date <= last_day` → `anchor <= last_day`

> **อย่าแก้** จุดที่ใช้ `start_date` สำหรับ tenure/employment-days display. เฉพาะตรรกะเงินเดือน/pro-rate/leave.

- [ ] **Step 2: แก้ `_compute_period_amount` helper เช่นเดียวกัน**

ค้นหา: `grep -n "_compute_period_amount" main.py` → เปิด def, ทำ anchor เหมือนกัน (อ่าน `monthly_start_date` จาก emp dict, fallback start_date) ทุกจุด first-month/pro-rate.

- [ ] **Step 3: manual verify — edge โปรข้ามเดือน**

สร้าง emp ผ่าน API: start_date=2026-05-01, monthly_salary=15600, set `employment_status='active'`, `monthly_start_date='2026-06-20'` (ผ่าน DB หรือ pass-probation endpoint ใน Task 1.4).
Run: `curl -s 'http://localhost:5055/api/employees/<id>/payments?year=2026&month=6'` (ผ่าน basic-auth)
Expected: period 2 base pro-rate จาก 06-20 (ไม่ใช่เต็มเดือน). มิ.ย. ไม่จ่าย full month.

> เนื่องจากยังไม่มี API test harness, verify นี้ทำตอน Phase รวม (หลัง Task 1.4) หรือผ่าน manual curl บน dev container.

- [ ] **Step 4: Commit**

```bash
git add maid-tracker/main.py
git commit -m "fix(maid-tracker): monthly payments anchor on monthly_start_date"
```

---

### Task 1.4: Pass-probation endpoint + models + create/update

**Files:**
- Modify: `maid-tracker/main.py` — `EmployeeCreate` model, `create_employee`, `update_employee`, เพิ่ม pass-probation endpoints

- [ ] **Step 1: ขยาย `EmployeeCreate` model (main.py:362-373)**

เพิ่ม field:
```python
    employment_status: str = "active"        # 'probation' | 'active'
    probation_daily_rate: Optional[float] = None
    payment_method: str = "cash"             # 'cash' | 'transfer'
    # monthly_start_date set โดย pass-probation endpoint เท่านั้น (ไม่รับจากฟอร์ม)
```

- [ ] **Step 2: `create_employee` (main.py:416-430) — insert คอลัมน์ใหม่**

ปรับ INSERT ให้รวม `employment_status, probation_daily_rate, payment_method`. ถ้า `employment_status='probation'` → `monthly_start_date=NULL`. ถ้า `'active'` → `monthly_start_date = start_date` (เพื่อให้ anchor = start_date เหมือนเดิม สำหรับคนที่สร้างแบบ active ตรงๆ; หรือปล่อย NULL แล้ว fallback ก็ได้ — เลือก NULL+fallback เพื่อ consistency กับแถวเก่า).
→ เลือก: `monthly_start_date` ปล่อย NULL เสมอตอนสร้าง; ตั้งค่าเฉพาะตอน pass-probation. (active ปกติ fallback เป็น start_date.)

- [ ] **Step 3: `update_employee` (main.py:449-464) — แก้ payment_method ได้, ไม่แตะ employment_status/monthly_start_date**

ปรับ UPDATE ให้รวม `payment_method`, `probation_daily_rate`. **ห้าม** ให้ update เปลี่ยน `employment_status`/`monthly_start_date` (เปลี่ยนผ่าน pass-probation endpoint เท่านั้น).

- [ ] **Step 4: เพิ่ม pass-probation endpoints**

```python
class PassProbationRequest(BaseModel):
    pass_date: str   # YYYY-MM-DD


@app.post("/api/employees/{emp_id}/pass-probation")
def pass_probation(emp_id: int, req: PassProbationRequest):
    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close(); raise HTTPException(404, "Employee not found")
    if emp["employment_status"] != "probation":
        conn.close(); raise HTTPException(400, "Employee is not in probation")
    # validate pass_date: not before start_date
    if req.pass_date < emp["start_date"]:
        conn.close(); raise HTTPException(400, "pass_date before start_date")
    conn.execute(
        "UPDATE employees SET employment_status='active', monthly_start_date=? WHERE id=?",
        (req.pass_date, emp_id),
    )
    conn.commit(); conn.close()
    return {"message": "passed", "monthly_start_date": req.pass_date}


@app.delete("/api/employees/{emp_id}/pass-probation")
def undo_pass_probation(emp_id: int):
    conn = get_db()
    conn.execute(
        "UPDATE employees SET employment_status='probation', monthly_start_date=NULL WHERE id=?",
        (emp_id,),
    )
    conn.commit(); conn.close()
    return {"message": "reverted"}
```

- [ ] **Step 5: manual verify — create probation → pass → active**

```bash
# create
curl -s -XPOST localhost:5055/api/employees -H 'Content-Type: application/json' \
  -d '{"name":"Test","start_date":"2026-06-01","monthly_salary":15600,"employment_status":"probation","probation_daily_rate":400,"payment_method":"transfer"}' -u u:p
# pass
curl -s -XPOST localhost:5055/api/employees/<id>/pass-probation -H 'Content-Type: application/json' -d '{"pass_date":"2026-06-20"}' -u u:p
# check
curl -s localhost:5055/api/employees/<id> -u u:p
```
Expected: หลัง pass → `employment_status=active`, `monthly_start_date=2026-06-20`.

- [ ] **Step 6: Commit**

```bash
git add maid-tracker/main.py
git commit -m "feat(maid-tracker): employee probation fields + pass-probation endpoints"
```

---

### Task 1.5: Daily-payments endpoints (probation payout + toggle)

**Files:**
- Modify: `maid-tracker/main.py` — เพิ่ม endpoints

- [ ] **Step 1: GET daily-payments — list วัน work ที่ mark แล้ว + paid status**

> **⚠️ Bug-fix (advisor):** ต้อง **cap ที่ `monthly_start_date`** — คืนเฉพาะวัน probation (ก่อนผ่านโปร). ไม่งั้น transition month จะคืนวันหลังผ่านโปรที่ monthly salary จ่ายไปแล้ว → double-pay. ใช้ helper `_probation_day_bound` (Task 1.0) เพื่อให้ boundary อยู่ที่เดียว.

```python
@app.get("/api/employees/{emp_id}/daily-payments")
def get_daily_payments(emp_id: int, year: int, month: int):
    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close(); raise HTTPException(404, "Employee not found")
    emp = dict(emp)
    rate = emp.get("probation_daily_rate") or 0
    # cap: probation days only — strictly before monthly_start_date (if passed)
    cap = emp.get("monthly_start_date")  # ISO str or None
    cap_clause = " AND work_date < ?" if cap else ""
    params = [emp_id, f"{year}-{month:02d}-%"] + ([cap] if cap else [])
    att = conn.execute(
        "SELECT work_date, half_day FROM attendance "
        "WHERE employee_id=? AND status='work' AND work_date LIKE ?" + cap_clause + " ORDER BY work_date",
        tuple(params),
    ).fetchall()
    paid = {r["work_date"]: dict(r) for r in conn.execute(
        "SELECT work_date, amount, paid_at, slip_path FROM daily_payments WHERE employee_id=? AND work_date LIKE ?",
        (emp_id, f"{year}-{month:02d}-%"),
    ).fetchall()}
    conn.close()
    out = []
    for a in att:
        frac = 0.5 if a["half_day"] else 1.0
        p = paid.get(a["work_date"])
        out.append({
            "work_date": a["work_date"],
            "fraction": frac,
            "amount": round((p["amount"] if p else rate * frac), 2),
            "paid": bool(p and p["paid_at"]),
            "paid_at": p["paid_at"] if p else None,
            "slip_path": p["slip_path"] if p else None,
        })
    return out
```

- [ ] **Step 2: POST toggle — snapshot amount ตอน mark paid**

```python
@app.post("/api/employees/{emp_id}/daily-payments/{work_date}/toggle")
def toggle_daily_payment(emp_id: int, work_date: str):
    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close(); raise HTTPException(404, "Employee not found")
    emp = dict(emp)
    # Guard: cannot toggle daily-payment on/after monthly_start_date (those days = monthly salary)
    cap = emp.get("monthly_start_date")
    if cap and work_date >= cap:
        conn.close(); raise HTTPException(400, "Date is in monthly-salary period, not probation")
    att = conn.execute(
        "SELECT half_day FROM attendance WHERE employee_id=? AND work_date=? AND status='work'",
        (emp_id, work_date),
    ).fetchone()
    if not att:
        conn.close(); raise HTTPException(400, "No marked work day on that date")
    existing = conn.execute(
        "SELECT id, paid_at FROM daily_payments WHERE employee_id=? AND work_date=?",
        (emp_id, work_date),
    ).fetchone()
    if existing and existing["paid_at"]:
        conn.execute("UPDATE daily_payments SET paid_at=NULL WHERE id=?", (existing["id"],))
        paid_at = None
    else:
        frac = 0.5 if att["half_day"] else 1.0
        amount = round((emp.get("probation_daily_rate") or 0) * frac, 2)
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn.execute(
            "INSERT INTO daily_payments (employee_id, work_date, amount, paid_at) VALUES (?,?,?,?) "
            "ON CONFLICT(employee_id, work_date) DO UPDATE SET amount=excluded.amount, paid_at=excluded.paid_at",
            (emp_id, work_date, amount, now),
        )
        paid_at = now
    conn.commit(); conn.close()
    return {"paid": bool(paid_at), "paid_at": paid_at}
```

- [ ] **Step 3: manual verify**

```bash
curl -s 'localhost:5055/api/employees/<id>/daily-payments?year=2026&month=6' -u u:p
curl -s -XPOST localhost:5055/api/employees/<id>/daily-payments/2026-06-02/toggle -u u:p
```
Expected: toggle → paid=true, amount snapshot ตาม rate × fraction.

- [ ] **Step 4: Commit**

```bash
git add maid-tracker/main.py
git commit -m "feat(maid-tracker): daily-payments endpoints for probation payout"
```

---

### Task 1.6: Resign-during-probation branch

**Files:**
- Modify: `maid-tracker/calc.py` `compute_resign_summary` (เพิ่ม param/branch) หรือ caller ใน main.py
- Modify: `maid-tracker/main.py` resign-summary endpoint
- Test: `maid-tracker/tests/test_probation.py`

- [ ] **Step 1: failing test — resign ระหว่างโปร = เฉพาะ unpaid work days × rate**

> **⚠️ Bug-fix (advisor):** model = จ่ายรายวันไปเรื่อยๆ. วันที่ toggle paid แล้ว (มี `daily_payments.paid_at`) **ห้ามนับซ้ำ** ตอน resign. settlement = เฉพาะวัน work ที่ยังไม่จ่าย.

```python
def test_resign_during_probation_unpaid_only(db, monkeypatch):
    calc = _calc(monkeypatch)
    eid = add_emp(db, name="D", start_date="2026-06-01", monthly_salary=15000,
                  employment_status="probation", probation_daily_rate=400)
    add_att(db, eid, "2026-06-02", "work")
    add_att(db, eid, "2026-06-03", "work")
    add_att(db, eid, "2026-06-04", "work")
    # 06-02 already paid → must NOT be counted again
    db.execute("INSERT INTO daily_payments (employee_id, work_date, amount, paid_at) "
               "VALUES (?,?,?,?)", (eid, "2026-06-02", 400.0, "2026-06-02 18:00"))
    db.commit()
    r = calc.compute_probation_resign(eid, date(2026, 6, 1), date(2026, 6, 4), 400.0)
    assert r["total_days"] == 2.0       # 06-03, 06-04 only
    assert r["final_amount"] == 800.0
```

- [ ] **Step 2: รัน — FAIL**

Run: `cd maid-tracker && python -m pytest tests/test_probation.py::test_resign_during_probation_unpaid_only -v`
Expected: FAIL no `compute_probation_resign`

- [ ] **Step 3: implement `compute_probation_resign` ใน calc.py — เฉพาะ unpaid**

```python
def compute_probation_resign(emp_id, start_date, end_date, probation_daily_rate) -> dict:
    """
    Resign while still in probation: settle only UNPAID marked work days × daily rate
    (days already toggled paid in daily_payments are excluded). No monthly base.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT a.work_date, a.half_day FROM attendance a "
        "LEFT JOIN daily_payments dp "
        "  ON dp.employee_id = a.employee_id AND dp.work_date = a.work_date AND dp.paid_at IS NOT NULL "
        "WHERE a.employee_id=? AND a.status='work' "
        "  AND a.work_date >= ? AND a.work_date <= ? AND dp.id IS NULL",
        (emp_id, start_date.isoformat(), end_date.isoformat()),
    ).fetchall()
    conn.close()
    total = sum(0.5 if r["half_day"] else 1.0 for r in rows)
    return {
        "total_days":     round(total, 2),
        "daily_rate":     round(probation_daily_rate, 2),
        "base_salary":    0.0,
        "balance_amount": 0.0,
        "final_amount":   round(total * probation_daily_rate, 2),
        "probation":      True,
    }
```

- [ ] **Step 4: รัน — PASS**

Run: `cd maid-tracker && python -m pytest tests/test_probation.py::test_resign_during_probation_unpaid_only -v`
Expected: PASS

- [ ] **Step 5: caller ใน main.py resign-summary เลือก branch ตาม `employment_status`**

ใน resign-summary endpoint: ถ้า `emp["employment_status"]=="probation"` → เรียก `compute_probation_resign`, ไม่งั้น flow เดิม (ส่ง anchor = `monthly_start_date or start_date`).

- [ ] **Step 6: Commit**

```bash
git add maid-tracker/calc.py maid-tracker/main.py maid-tracker/tests/test_probation.py
git commit -m "feat(maid-tracker): resign-during-probation settlement"
```

---

### Task 1.7: ปิด leave ระหว่างโปร (webhook + attendance default)

**Files:**
- Modify: `maid-tracker/main.py` attendance default-fill (~592) + attendance POST (~614)
- Modify: `maid-tracker/line_notify.py` (webhook leave handling) หรือ main.py webhook handler

- [ ] **Step 1: attendance default ระหว่างโปร = ไม่ default-fill**

ใน get-attendance (main.py ~575-600): ถ้า `employment_status=='probation'`, days ที่ไม่มี saved row → status `null`/`absent` (ไม่ default `work`). ให้ frontend แสดงว่าต้อง mark เอง.

- [ ] **Step 2: attendance POST ระหว่างโปร reject leave/compensatory/holiday**

ใน POST attendance (~614): ถ้า `employment_status=='probation'` และ `status in ('leave','compensatory','holiday')` → `HTTPException(400, "Leave disabled during probation")`.

- [ ] **Step 3: LINE webhook reject leave ระหว่างโปร**

ใน webhook handler: ก่อนบันทึก leave/comp ตรวจ `employment_status` ของ emp — ถ้า probation → reply ปฏิเสธ "ยังไม่ผ่านโปร เปิดการลายังไม่ได้".

- [ ] **Step 4: manual verify**

```bash
curl -s -XPOST localhost:5055/api/employees/<probation_id>/attendance -H 'Content-Type: application/json' -d '{"work_date":"2026-06-05","status":"leave"}' -u u:p
```
Expected: 400 "Leave disabled during probation".

- [ ] **Step 5: Commit**

```bash
git add maid-tracker/main.py maid-tracker/line_notify.py
git commit -m "feat(maid-tracker): disable leave during probation"
```

---

## Phase 2 — File upload infra (slip + documents)

### Task 2.1: Upload helper + serve route (shared)

**Files:**
- Modify: `maid-tracker/main.py` — helper `_save_upload`, serve routes

- [ ] **Step 1: เพิ่ม dirs + helper**

```python
from fastapi import UploadFile, File, Form
from fastapi.responses import FileResponse

_SLIP_DIR = os.path.join(DATA_DIR, "slips")
_DOC_DIR  = os.path.join(DATA_DIR, "documents")
os.makedirs(_SLIP_DIR, exist_ok=True)
os.makedirs(_DOC_DIR, exist_ok=True)

_ALLOWED_UPLOAD = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
_MAX_UPLOAD = 10 * 1024 * 1024  # 10MB

def _save_upload(file: UploadFile, dest_dir: str, basename: str) -> str:
    if file.content_type not in _ALLOWED_UPLOAD:
        raise HTTPException(400, f"Unsupported type: {file.content_type}")
    data = file.file.read()
    if len(data) > _MAX_UPLOAD:
        raise HTTPException(400, "File too large (max 10MB)")
    ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "application/pdf": ".pdf"}[file.content_type]
    fname = f"{basename}{ext}"
    path = os.path.join(dest_dir, fname)
    with open(path, "wb") as f:
        f.write(data)
    return fname  # store relative filename in DB
```

- [ ] **Step 2: serve routes (หลัง basic-auth เดียวกับ stack)**

```python
@app.get("/api/slips/{fname}")
def serve_slip(fname: str):
    path = os.path.join(_SLIP_DIR, os.path.basename(fname))
    if not os.path.exists(path):
        raise HTTPException(404, "Not found")
    return FileResponse(path)

@app.get("/api/documents/{fname}")
def serve_document(fname: str):
    path = os.path.join(_DOC_DIR, os.path.basename(fname))
    if not os.path.exists(path):
        raise HTTPException(404, "Not found")
    return FileResponse(path)
```
> Basic-auth ครอบที่ nginx layer (ทั้ง stack ยกเว้น `/webhook/line`). `os.path.basename` กัน path traversal.

- [ ] **Step 3: manual verify dirs created**

Run: `docker exec maid-tracker ls -la /data/slips /data/documents` (หรือ local: ตรวจ DATA_DIR)
Expected: dirs มีอยู่.

- [ ] **Step 4: Commit**

```bash
git add maid-tracker/main.py
git commit -m "feat(maid-tracker): file upload helper + serve routes"
```

---

### Task 2.2: Slip upload endpoints (daily + monthly)

**Files:**
- Modify: `maid-tracker/main.py`

- [ ] **Step 1: slip สำหรับ monthly period**

```python
@app.post("/api/employees/{emp_id}/payments/{period}/slip")
def upload_period_slip(emp_id: int, period: int, year: int, month: int, file: UploadFile = File(...)):
    if period not in (1, 2):
        raise HTTPException(400, "Invalid period")
    fname = _save_upload(file, _SLIP_DIR, f"slip_{emp_id}_{year}{month:02d}_p{period}")
    conn = get_db()
    conn.execute(
        "INSERT INTO salary_payments (employee_id, year, month, period, slip_path) VALUES (?,?,?,?,?) "
        "ON CONFLICT(employee_id, year, month, period) DO UPDATE SET slip_path=excluded.slip_path",
        (emp_id, year, month, period, fname),
    )
    conn.commit(); conn.close()
    return {"slip_path": fname}
```

- [ ] **Step 2: slip สำหรับ daily payment**

```python
@app.post("/api/employees/{emp_id}/daily-payments/{work_date}/slip")
def upload_daily_slip(emp_id: int, work_date: str, file: UploadFile = File(...)):
    fname = _save_upload(file, _SLIP_DIR, f"slip_{emp_id}_daily_{work_date}")
    conn = get_db()
    cur = conn.execute(
        "UPDATE daily_payments SET slip_path=? WHERE employee_id=? AND work_date=?",
        (fname, emp_id, work_date),
    )
    if cur.rowcount == 0:
        conn.execute(
            "INSERT INTO daily_payments (employee_id, work_date, amount, slip_path) VALUES (?,?,0,?)",
            (emp_id, work_date, fname),
        )
    conn.commit(); conn.close()
    return {"slip_path": fname}
```

- [ ] **Step 3: รวม slip_path ใน get_payments output**

ใน `get_payments` (Task 1.3) เพิ่ม `slip_path` จาก paid_map ลงผลแต่ละ period (อ่านจาก salary_payments).

- [ ] **Step 4: manual verify**

```bash
curl -s -XPOST 'localhost:5055/api/employees/<id>/payments/1/slip?year=2026&month=6' -F file=@slip.jpg -u u:p
curl -s 'localhost:5055/api/slips/slip_<id>_202606_p1.jpg' -u u:p -o /tmp/out.jpg && file /tmp/out.jpg
```
Expected: upload คืน slip_path, serve คืนรูป.

- [ ] **Step 5: Commit**

```bash
git add maid-tracker/main.py
git commit -m "feat(maid-tracker): slip upload for daily + monthly payments"
```

---

### Task 2.3: Document upload endpoints (multi-file)

**Files:**
- Modify: `maid-tracker/main.py`

- [ ] **Step 1: upload (หลายไฟล์), list, delete**

```python
@app.post("/api/employees/{emp_id}/documents")
def upload_documents(emp_id: int, doc_type: str = Form(...), files: list[UploadFile] = File(...)):
    if doc_type not in ("id_card", "passport"):
        raise HTTPException(400, "Invalid doc_type")
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    saved = []
    for i, file in enumerate(files):
        fname = _save_upload(file, _DOC_DIR, f"doc_{emp_id}_{doc_type}_{int(datetime.now().timestamp())}_{i}")
        conn.execute(
            "INSERT INTO employee_documents (employee_id, doc_type, file_path, uploaded_at) VALUES (?,?,?,?)",
            (emp_id, doc_type, fname, now),
        )
        saved.append(fname)
    conn.commit(); conn.close()
    return {"saved": saved}

@app.get("/api/employees/{emp_id}/documents")
def list_documents(emp_id: int):
    conn = get_db()
    rows = conn.execute(
        "SELECT id, doc_type, file_path, uploaded_at FROM employee_documents WHERE employee_id=? ORDER BY uploaded_at",
        (emp_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.delete("/api/employees/{emp_id}/documents/{doc_id}")
def delete_document(emp_id: int, doc_id: int):
    conn = get_db()
    row = conn.execute("SELECT file_path FROM employee_documents WHERE id=? AND employee_id=?", (doc_id, emp_id)).fetchone()
    if row:
        fpath = os.path.join(_DOC_DIR, os.path.basename(row["file_path"]))
        if os.path.exists(fpath):
            os.remove(fpath)
        conn.execute("DELETE FROM employee_documents WHERE id=?", (doc_id,))
        conn.commit()
    conn.close()
    return {"message": "deleted"}
```

- [ ] **Step 2: delete_employee ลบ documents + daily_payments + files ด้วย**

แก้ `delete_employee` (main.py:467-475): เพิ่ม `DELETE FROM employee_documents`, `DELETE FROM daily_payments`, ลบไฟล์ใน slips/documents ของ emp นั้น.

- [ ] **Step 3: manual verify multi-file**

```bash
curl -s -XPOST localhost:5055/api/employees/<id>/documents -F doc_type=id_card -F files=@a.jpg -F files=@b.jpg -u u:p
curl -s localhost:5055/api/employees/<id>/documents -u u:p
```
Expected: 2 ไฟล์บันทึก, list คืน 2 rows.

- [ ] **Step 4: Commit**

```bash
git add maid-tracker/main.py
git commit -m "feat(maid-tracker): employee document upload (id/passport, multi-file)"
```

---

## Phase 3 — SPA frontend

> ไม่มี JS test harness — แต่ละ task = implement + manual verify ใน browser.

### Task 3.1: Create/edit form — probation + payment_method + documents

**Files:**
- Modify: `maid-tracker/static/app.js`

- [ ] **Step 1: form fields**

เพิ่มในฟอร์มสร้าง/แก้แม่บ้าน: checkbox "เริ่มแบบ probation (จ่ายรายวัน)" → toggle field `probation_daily_rate`. Dropdown `payment_method` (เงินสด/โอน). Section อัปโหลดเอกสาร (id_card/passport, เลือกหลายไฟล์). ส่ง field ใหม่ใน POST/PUT.

- [ ] **Step 2: i18n keys (TH/EN)** เพิ่ม label ใหม่ทั้งสองภาษา (ตามรูปแบบ i18n เดิมใน app.js).

- [ ] **Step 3: manual verify** — สร้างแม่บ้าน probation ผ่าน UI, ตรวจค่าใน DB.

- [ ] **Step 4: Commit**
```bash
git add maid-tracker/static/app.js
git commit -m "feat(maid-tracker): create/edit form probation + payment_method + docs"
```

### Task 3.2: Employee page — badge + ปุ่มผ่านโปร + ซ่อน leave

**Files:**
- Modify: `maid-tracker/static/app.js`

- [ ] **Step 1:** แสดง badge "Probation" เมื่อ status=probation. ปุ่ม "ผ่านโปร" → modal เลือก pass_date (default วันนี้) → confirm → `POST pass-probation` → reload. ซ่อน UI ลา/ปฏิทิน leave options ระหว่างโปร.
- [ ] **Step 2: manual verify** — กดผ่านโปร, badge หาย, leave เปิด.
- [ ] **Step 3: Commit**
```bash
git add maid-tracker/static/app.js
git commit -m "feat(maid-tracker): probation badge + pass-probation UI"
```

### Task 3.3: Payments view — probation daily list + slip buttons

**Files:**
- Modify: `maid-tracker/static/app.js`

- [ ] **Step 1:** **render ตามเดือนเทียบ anchor ไม่ใช่ตาม status ปัจจุบัน** (advisor bug-fix — transition month ต้องเห็นทั้ง daily ก่อนผ่านโปร + monthly หลังผ่านโปร):
  - เรียกทั้ง `GET daily-payments?year=&month=` และ `GET payments?year=&month=` ทุกเดือน.
  - ถ้า `daily-payments` คืน rows → render section "จ่ายรายวัน (ช่วงโปร)" แต่ละแถว toggle paid + (ถ้า transfer) ปุ่ม slip + thumbnail.
  - ถ้า `payments` คืน periods → render section "เงินเดือน" 2 งวด + (ถ้า transfer) ปุ่ม slip ต่อ period.
  - **Transition month** จะมี **ทั้งสอง section** (daily 06-01..06-19 + monthly 06-20..30) — ถูกต้อง, ไม่ double เพราะ backend cap แล้ว.
  - เดือนเต็มโปร → มีแค่ daily. เดือนเต็มเงินเดือน → มีแค่ periods. แสดงยอดรวมรายวันที่ section หัว.
- [ ] **Step 2: manual verify** — toggle จ่ายรายวัน, upload slip, เห็น thumbnail.
- [ ] **Step 3: Commit**
```bash
git add maid-tracker/static/app.js
git commit -m "feat(maid-tracker): payments view probation daily + slip upload"
```

---

## Phase 4 — Docs + verification

### Task 4.1: Update stack docs

**Files:**
- Modify: `maid-tracker/.notes/00_INDEX.md` (schema, endpoints, logic)
- Modify: `maid-tracker/.notes/daily_log.md` (สรุปงาน)
- Modify: `maid-tracker/README.md` (ฟีเจอร์ใหม่)
- Modify: root `CLAUDE.md` (maid-tracker row: probation + slip + docs)

- [ ] **Step 1:** อัปเดตทั้ง 4 ไฟล์ตามที่ implement จริง (schema columns/tables ใหม่, endpoints, probation logic, slip/doc storage paths).
- [ ] **Step 2: Commit**
```bash
git add maid-tracker/.notes maid-tracker/README.md CLAUDE.md
git commit -m "docs(maid-tracker): probation mode + slip/document upload"
```

### Task 4.2: Full regression verify

- [ ] **Step 1:** รัน `cd maid-tracker && python -m pytest tests/ -v` → ทุก test PASS.
- [ ] **Step 2:** Manual E2E บน dev/local container:
  - แม่บ้าน active เดิม: payments 2 งวดเหมือนเดิม (regression — anchor fallback ทำงาน).
  - แม่บ้าน probation: mark work → daily list → toggle paid → upload slip.
  - Pass mid-month → transition: probation portion + monthly pro-rate ไม่ double-count.
  - Edge ข้ามเดือน (start 05-01, pass 06-20): June pro-rate ถูก.
  - Resign ระหว่างโปร: unpaid days × rate.
  - Documents: upload หลายไฟล์ + delete.
- [ ] **Step 3:** ถ้าผ่านครบ → พร้อม deploy (`./scripts/deploy.sh`) + `/maid-release`.

---

## Self-review (plan author)

**Spec coverage:**
- Probation daily pay → Task 1.1, 1.5 ✓
- mode รายเดือน หลังผ่านโปร (axis แยก) → Task 1.4 ✓
- Transition split + anchor + edge ข้ามเดือน → Task 1.2, 1.3 ✓
- Leave ปิดระหว่างโปร → Task 1.7 ✓
- Resign ระหว่างโปร → Task 1.6 ✓
- Slip ทุก payment (transfer) → Task 2.1, 2.2 ✓
- payment_method เลือกตอนสร้าง/แก้ได้ → Task 1.4, 3.1 ✓
- Documents หลายรูป → Task 2.3, 3.1 ✓
- Migration แถวเก่า → Task 0.2 ✓
- Docs → Task 4.1 ✓

**Placeholder scan:** ไม่มี TBD/TODO ใน implementation steps. Frontend tasks (Phase 3) ใช้ implement+manual-verify เพราะไม่มี JS test harness — ระบุ verify criteria ชัด.

**Advisor bug-fixes (รอบ 2) — patched:**
1. Transition double-pay/orphan → `get_daily_payments` cap ที่ `monthly_start_date` (Task 1.5) + `toggle` guard + SPA render per-month-relative-to-anchor (Task 3.3) + `get_payments` skip periods ตอน probation (Task 1.3).
2. Resign re-pay paid days → `compute_probation_resign` นับเฉพาะ unpaid (LEFT JOIN daily_payments), test มีวัน paid (Task 1.6).
3. Boundary 3 ที่ → centralize `is_probation_day`/`probation_up_to` (Task 1.0) + transition-boundary test.
4. `pass_date` validation (ไม่ก่อน start_date) — Task 1.4.

**Type consistency:** `monthly_start_date` TEXT (ISO) ทุกที่; anchor = `date.fromisoformat(...)` fallback `start_date`. `daily_payments.amount` REAL snapshot. calc ฟังก์ชันรับ `start_date: date` (ส่ง anchor) — signature เดิมไม่เปลี่ยน.
