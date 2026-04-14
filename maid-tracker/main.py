from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
import sqlite3
import os
from datetime import date, datetime, timedelta
import calendar

app = FastAPI(title="Maid Tracker")

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "maid_tracker.db")


def get_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS employees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER,
            nationality TEXT DEFAULT 'ไทย',
            phone TEXT,
            line_id TEXT,
            facebook TEXT,
            start_date TEXT NOT NULL,
            monthly_salary REAL NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            work_date TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('work','leave','holiday','compensatory')),
            note TEXT,
            UNIQUE(employee_id, work_date),
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        );
        CREATE TABLE IF NOT EXISTS salary_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            month INTEGER NOT NULL,
            period INTEGER NOT NULL CHECK(period IN (1, 2)),
            paid_at TEXT,
            UNIQUE(employee_id, year, month, period),
            FOREIGN KEY(employee_id) REFERENCES employees(id)
        );
    """)
    # Migrate: add columns if they don't exist yet
    for col, definition in [("end_date", "TEXT"), ("resign_note", "TEXT")]:
        try:
            c.execute(f"ALTER TABLE employees ADD COLUMN {col} {definition}")
        except Exception:
            pass
    conn.commit()
    conn.close()


init_db()


# ---------- Pydantic models ----------

class EmployeeCreate(BaseModel):
    name: str
    age: Optional[int] = None
    nationality: str = "ไทย"
    phone: Optional[str] = None
    line_id: Optional[str] = None
    facebook: Optional[str] = None
    start_date: str
    monthly_salary: float


class AttendanceUpdate(BaseModel):
    work_date: str
    status: str
    note: Optional[str] = None


class ResignRequest(BaseModel):
    end_date: str
    resign_note: Optional[str] = None


# ---------- Helpers ----------

def default_status(d: date) -> str:
    """Sunday = holiday, else work."""
    return "holiday" if d.weekday() == 6 else "work"


def working_days_in_month(year: int, month: int) -> int:
    """Count Mon–Sat days in a month."""
    _, n = calendar.monthrange(year, month)
    return sum(1 for day in range(1, n + 1) if date(year, month, day).weekday() != 6)


def daily_rate(monthly_salary: float, year: int, month: int) -> float:
    wd = working_days_in_month(year, month)
    return monthly_salary / wd if wd else 0


# ---------- Employee endpoints ----------

@app.get("/api/employees")
def list_employees():
    conn = get_db()
    rows = conn.execute("SELECT * FROM employees ORDER BY name").fetchall()
    conn.close()
    today = date.today()
    result = []
    for row in rows:
        emp = dict(row)
        start = date.fromisoformat(emp["start_date"])
        end = date.fromisoformat(emp["end_date"]) if emp.get("end_date") else today
        emp["total_days_employed"] = (end - start).days + 1
        result.append(emp)
    return result


@app.post("/api/employees", status_code=201)
def create_employee(emp: EmployeeCreate):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "INSERT INTO employees (name,age,nationality,phone,line_id,facebook,start_date,monthly_salary) "
        "VALUES (?,?,?,?,?,?,?,?)",
        (emp.name, emp.age, emp.nationality, emp.phone, emp.line_id, emp.facebook,
         emp.start_date, emp.monthly_salary),
    )
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return {"id": new_id}


@app.get("/api/employees/{emp_id}")
def get_employee(emp_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Employee not found")
    emp = dict(row)
    start = date.fromisoformat(emp["start_date"])
    today = date.today()
    end = date.fromisoformat(emp["end_date"]) if emp.get("end_date") else today
    emp["total_days_employed"] = (end - start).days + 1
    return emp


@app.put("/api/employees/{emp_id}")
def update_employee(emp_id: int, emp: EmployeeCreate):
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "UPDATE employees SET name=?,age=?,nationality=?,phone=?,line_id=?,facebook=?,start_date=?,monthly_salary=? WHERE id=?",
        (emp.name, emp.age, emp.nationality, emp.phone, emp.line_id, emp.facebook,
         emp.start_date, emp.monthly_salary, emp_id),
    )
    if c.rowcount == 0:
        conn.close()
        raise HTTPException(404, "Employee not found")
    conn.commit()
    conn.close()
    return {"message": "updated"}


@app.delete("/api/employees/{emp_id}")
def delete_employee(emp_id: int):
    conn = get_db()
    conn.execute("DELETE FROM attendance WHERE employee_id=?", (emp_id,))
    conn.execute("DELETE FROM salary_payments WHERE employee_id=?", (emp_id,))
    conn.execute("DELETE FROM employees WHERE id=?", (emp_id,))
    conn.commit()
    conn.close()
    return {"message": "deleted"}


# ---------- Resign endpoints ----------

@app.post("/api/employees/{emp_id}/resign")
def resign_employee(emp_id: int, req: ResignRequest):
    conn = get_db()
    emp = conn.execute("SELECT id FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        raise HTTPException(404, "Employee not found")
    conn.execute(
        "UPDATE employees SET end_date=?, resign_note=? WHERE id=?",
        (req.end_date, req.resign_note, emp_id),
    )
    conn.commit()
    conn.close()
    return {"message": "resigned"}


@app.delete("/api/employees/{emp_id}/resign")
def cancel_resign(emp_id: int):
    conn = get_db()
    conn.execute(
        "UPDATE employees SET end_date=NULL, resign_note=NULL WHERE id=?",
        (emp_id,),
    )
    conn.commit()
    conn.close()
    return {"message": "cancelled"}


@app.get("/api/employees/{emp_id}/resign-summary")
def get_resign_summary(emp_id: int):
    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        raise HTTPException(404, "Employee not found")
    emp = dict(emp)
    if not emp.get("end_date"):
        conn.close()
        raise HTTPException(400, "ยังไม่ได้แจ้งลาออก")

    start_date = date.fromisoformat(emp["start_date"])
    end_date = date.fromisoformat(emp["end_date"])
    year, month = end_date.year, end_date.month

    all_rows = conn.execute(
        "SELECT work_date, status FROM attendance WHERE employee_id=? AND work_date <= ?",
        (emp_id, emp["end_date"]),
    ).fetchall()
    conn.close()

    saved = {r["work_date"]: r["status"] for r in all_rows}

    # Cumulative balance across ALL time (start → end_date)
    total_comp = total_leave = 0
    d = start_date
    while d <= end_date:
        status = saved.get(d.isoformat(), default_status(d))
        if status == "compensatory":
            total_comp += 1
        elif status == "leave":
            total_leave += 1
        d += timedelta(days=1)
    cumulative_balance = total_comp - total_leave

    # Prorated last-month salary (from 1st-of-month or start_date, whichever is later, to end_date)
    wd_month = working_days_in_month(year, month)
    dr = emp["monthly_salary"] / wd_month if wd_month else 0

    month_start = max(date(year, month, 1), start_date)
    billable = sum(
        1 for i in range((end_date - month_start).days + 1)
        if (month_start + timedelta(days=i)).weekday() != 6
    )
    base_salary = round(dr * billable, 2)

    balance_amount = round(cumulative_balance * dr, 2)
    final_amount = round(base_salary + balance_amount, 2)

    return {
        "end_date": emp["end_date"],
        "resign_note": emp.get("resign_note"),
        "monthly_salary": emp["monthly_salary"],
        "daily_rate": round(dr, 2),
        "working_days_in_month": wd_month,
        "billable_days": billable,
        "base_salary": base_salary,
        "total_compensatory_days": total_comp,
        "total_leave_days": total_leave,
        "cumulative_balance": cumulative_balance,
        "balance_amount": balance_amount,
        "final_amount": final_amount,
    }


# ---------- Attendance endpoints ----------

@app.get("/api/employees/{emp_id}/attendance")
def get_attendance(emp_id: int, year: int, month: int):
    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        raise HTTPException(404, "Employee not found")
    start_date = date.fromisoformat(emp["start_date"])
    today = date.today()

    rows = conn.execute(
        "SELECT work_date, status, note FROM attendance WHERE employee_id=? AND work_date LIKE ?",
        (emp_id, f"{year}-{month:02d}-%"),
    ).fetchall()
    conn.close()

    saved = {r["work_date"]: dict(r) for r in rows}

    _, n = calendar.monthrange(year, month)
    result = []
    for day in range(1, n + 1):
        d = date(year, month, day)
        ds = d.isoformat()
        if d < start_date:
            result.append({"date": ds, "status": "before_start", "note": None, "is_future": False})
            continue
        is_future = d > today
        if ds in saved:
            r = saved[ds]
            result.append({"date": ds, "status": r["status"], "note": r["note"], "is_future": is_future})
        else:
            result.append({"date": ds, "status": default_status(d), "note": None, "is_future": is_future})
    return result


@app.post("/api/employees/{emp_id}/attendance")
def upsert_attendance(emp_id: int, att: AttendanceUpdate):
    if att.status not in ("work", "leave", "holiday", "compensatory"):
        raise HTTPException(400, "Invalid status")
    conn = get_db()
    emp = conn.execute("SELECT id FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        raise HTTPException(404, "Employee not found")
    conn.execute(
        "INSERT INTO attendance (employee_id, work_date, status, note) VALUES (?,?,?,?) "
        "ON CONFLICT(employee_id, work_date) DO UPDATE SET status=excluded.status, note=excluded.note",
        (emp_id, att.work_date, att.status, att.note),
    )
    conn.commit()
    conn.close()
    return {"message": "saved"}


@app.get("/api/employees/{emp_id}/leaves")
def get_leaves(emp_id: int):
    conn = get_db()
    emp = conn.execute("SELECT id FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        raise HTTPException(404, "Employee not found")
    rows = conn.execute(
        "SELECT work_date, note FROM attendance WHERE employee_id=? AND status='leave' ORDER BY work_date DESC",
        (emp_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------- Payment endpoints ----------

@app.get("/api/employees/{emp_id}/payments")
def get_payments(emp_id: int, year: int, month: int):
    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        raise HTTPException(404, "Employee not found")
    emp = dict(emp)

    start_date = date.fromisoformat(emp["start_date"])
    end_date = date.fromisoformat(emp["end_date"]) if emp.get("end_date") else None
    today = date.today()

    _, n = calendar.monthrange(year, month)
    last_day = date(year, month, n)
    mid_day = date(year, month, 15)

    # Paid status for this month
    paid_rows = conn.execute(
        "SELECT period, paid_at FROM salary_payments WHERE employee_id=? AND year=? AND month=?",
        (emp_id, year, month),
    ).fetchall()
    paid_map = {r["period"]: r["paid_at"] for r in paid_rows}

    # Attendance for this month (to calculate actual_pay for period 2)
    att_rows = conn.execute(
        "SELECT work_date, status FROM attendance WHERE employee_id=? AND work_date LIKE ?",
        (emp_id, f"{year}-{month:02d}-%"),
    ).fetchall()
    conn.close()

    saved = {r["work_date"]: r["status"] for r in att_rows}

    wd_month = working_days_in_month(year, month)
    dr = emp["monthly_salary"] / wd_month if wd_month else 0
    half_salary = emp["monthly_salary"] / 2

    # Base salary for this month (prorated if first month)
    if start_date.year == year and start_date.month == month:
        billable = sum(
            1 for day in range(start_date.day, n + 1)
            if date(year, month, day).weekday() != 6
        )
        base_salary = dr * billable
    else:
        base_salary = emp["monthly_salary"]

    # Policy: no monthly deduction — always pay full base salary
    # Period 2 = base_salary - half_salary (always half, no leave/comp adjustment)
    period2_amount = base_salary - half_salary

    result = []

    # Period 1 (15th) — skip if employee started after 15th or resigned before 15th
    if start_date <= mid_day and (end_date is None or end_date >= mid_day):
        result.append({
            "period": 1,
            "due_date": mid_day.isoformat(),
            "amount": round(half_salary, 2),
            "paid": bool(paid_map.get(1)),
            "paid_at": paid_map.get(1),
        })

    # Period 2 (last day or resignation date if resigned this month)
    period2_due = last_day
    if end_date and end_date.year == year and end_date.month == month:
        period2_due = end_date

    if start_date <= last_day and (end_date is None or end_date >= date(year, month, 1)):
        result.append({
            "period": 2,
            "due_date": period2_due.isoformat(),
            "amount": round(period2_amount, 2),
            "paid": bool(paid_map.get(2)),
            "paid_at": paid_map.get(2),
        })

    return result


@app.post("/api/employees/{emp_id}/payments/{period}/toggle")
def toggle_payment(emp_id: int, period: int, year: int, month: int):
    if period not in (1, 2):
        raise HTTPException(400, "Invalid period")
    conn = get_db()
    emp = conn.execute("SELECT id FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        raise HTTPException(404, "Employee not found")

    existing = conn.execute(
        "SELECT paid_at FROM salary_payments WHERE employee_id=? AND year=? AND month=? AND period=?",
        (emp_id, year, month, period),
    ).fetchone()

    if existing and existing["paid_at"]:
        conn.execute(
            "UPDATE salary_payments SET paid_at=NULL WHERE employee_id=? AND year=? AND month=? AND period=?",
            (emp_id, year, month, period),
        )
        paid_at = None
    else:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn.execute(
            "INSERT INTO salary_payments (employee_id, year, month, period, paid_at) VALUES (?,?,?,?,?) "
            "ON CONFLICT(employee_id, year, month, period) DO UPDATE SET paid_at=excluded.paid_at",
            (emp_id, year, month, period, now),
        )
        paid_at = now

    conn.commit()
    conn.close()
    return {"paid": bool(paid_at), "paid_at": paid_at}


# ---------- Summary endpoints ----------

@app.get("/api/employees/{emp_id}/summary")
def get_summary(emp_id: int, year: int, month: int):
    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        raise HTTPException(404, "Employee not found")
    emp = dict(emp)
    start_date = date.fromisoformat(emp["start_date"])
    today = date.today()

    all_rows = conn.execute(
        "SELECT work_date, status FROM attendance WHERE employee_id=? AND work_date <= ?",
        (emp_id, f"{year}-{month:02d}-31"),
    ).fetchall()
    conn.close()

    saved_all = {r["work_date"]: r["status"] for r in all_rows}

    # Carryover: cumulative balance from months before this one
    carryover_balance = 0
    if start_date < date(year, month, 1):
        c_comp = c_leave = 0
        d = start_date
        cutoff = date(year, month, 1)
        while d < cutoff and d <= today:
            status = saved_all.get(d.isoformat(), default_status(d))
            if status == "compensatory":
                c_comp += 1
            elif status == "leave":
                c_leave += 1
            d += timedelta(days=1)
        carryover_balance = c_comp - c_leave

    _, n = calendar.monthrange(year, month)
    saved = {k: v for k, v in saved_all.items() if k.startswith(f"{year}-{month:02d}-")}
    counts = {"work": 0, "leave": 0, "holiday": 0, "compensatory": 0}

    for day in range(1, n + 1):
        d = date(year, month, day)
        if d < start_date or d > today:
            continue
        ds = d.isoformat()
        status = saved.get(ds, default_status(d))
        counts[status] = counts.get(status, 0) + 1

    wd_month = working_days_in_month(year, month)
    dr = emp["monthly_salary"] / wd_month if wd_month else 0

    # Prorated salary for first partial month
    if start_date.year == year and start_date.month == month:
        billable = sum(
            1 for day in range(start_date.day, n + 1)
            if date(year, month, day).weekday() != 6
        )
        base_salary = dr * billable
    else:
        base_salary = emp["monthly_salary"]

    balance = counts["compensatory"] - counts["leave"]
    # Policy: no monthly deduction/credit — leave & comp accumulate and are settled at resignation
    actual_pay = base_salary
    cumulative_balance = carryover_balance + balance

    return {
        "year": year,
        "month": month,
        "employee_name": emp["name"],
        "monthly_salary": emp["monthly_salary"],
        "daily_rate": round(dr, 2),
        "working_days_in_month": wd_month,
        "base_salary": round(base_salary, 2),
        "work_days": counts["work"],
        "leave_days": counts["leave"],
        "holiday_days": counts["holiday"],
        "compensatory_days": counts["compensatory"],
        "balance": balance,
        "carryover_balance": carryover_balance,
        "cumulative_balance": cumulative_balance,
        "money_owed": 0,
        "money_credit": 0,
        "actual_pay": round(actual_pay, 2),
    }


@app.get("/api/employees/{emp_id}/overall")
def get_overall(emp_id: int):
    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        raise HTTPException(404, "Employee not found")
    emp = dict(emp)
    start_date = date.fromisoformat(emp["start_date"])
    today = date.today()
    end = date.fromisoformat(emp["end_date"]) if emp.get("end_date") else today

    rows = conn.execute(
        "SELECT work_date, status FROM attendance WHERE employee_id=?", (emp_id,)
    ).fetchall()
    conn.close()

    saved = {r["work_date"]: r["status"] for r in rows}
    counts = {"work": 0, "leave": 0, "holiday": 0, "compensatory": 0}

    d = start_date
    while d <= end:
        ds = d.isoformat()
        status = saved.get(ds, default_status(d))
        counts[status] = counts.get(status, 0) + 1
        d += timedelta(days=1)

    total_days = (end - start_date).days + 1
    balance = counts["compensatory"] - counts["leave"]

    return {
        "start_date": emp["start_date"],
        "total_days_employed": total_days,
        "total_work_days": counts["work"],
        "total_leave_days": counts["leave"],
        "total_holiday_days": counts["holiday"],
        "total_compensatory_days": counts["compensatory"],
        "overall_balance": balance,
    }


# ---------- Static + SPA fallback ----------

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    return FileResponse("static/index.html")
