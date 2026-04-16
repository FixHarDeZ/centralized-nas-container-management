from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from contextlib import asynccontextmanager
import sqlite3
import os
import hmac
import hashlib
import base64
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar
import line_notify
from apscheduler.schedulers.background import BackgroundScheduler

_scheduler = BackgroundScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    _scheduler.add_job(_check_reminders, "interval", seconds=60, id="check_reminders")
    _scheduler.start()
    yield
    _scheduler.shutdown(wait=False)

app = FastAPI(title="Maid Tracker", lifespan=lifespan)

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "maid_tracker.db")

_LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET", "")

# Keywords that trigger automatic attendance recording from LINE chat
_LEAVE_KEYWORDS = [
    "ขอลา", "ลาวันนี้", "วันนี้ขอลา", "วันนี้ลา", "ลาวันนี้นะ",
    "ขอหยุด", "หยุดวันนี้", "วันนี้หยุด", "วันนี้ขอหยุด",
    "ลาครึ่งวัน", "ลาครึ่ง",
]
_COMP_KEYWORDS  = [
    "ทำชดเชย", "ชดเชยวันนี้", "วันนี้ชดเชย", "วันนี้ทำชดเชย",
    "ทำงานวันหยุด", "ทำงานวันอาทิตย์", "มาทำงานวันนี้",
    "ชดเชยครึ่งวัน", "ชดเชยครึ่ง",
]
_HALF_DAY_KEYWORDS = ["ครึ่งวัน", "ครึ่งวันเช้า", "ครึ่งวันบ่าย"]


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
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            message TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            schedule_type TEXT NOT NULL,
            schedule_value TEXT NOT NULL,
            send_time TEXT NOT NULL DEFAULT '07:00',
            last_sent_date TEXT,
            created_at TEXT NOT NULL
        );
    """)
    # Migrate: add columns if they don't exist yet
    for col, definition in [("end_date", "TEXT"), ("resign_note", "TEXT")]:
        try:
            c.execute(f"ALTER TABLE employees ADD COLUMN {col} {definition}")
        except Exception:
            pass
    try:
        c.execute("ALTER TABLE attendance ADD COLUMN half_day INTEGER DEFAULT 0")
    except Exception:
        pass
    conn.commit()
    conn.close()


init_db()


def _seed_default_reminders():
    """Insert default reminders on first run (only if the table is empty)."""
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM reminders").fetchone()[0]
    if count == 0:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            "INSERT INTO reminders (name, message, enabled, schedule_type, schedule_value, send_time, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            ("เปลี่ยนผ้าปูที่นอน", "🛏️ วันนี้เปลี่ยนผ้าปูที่นอนด้วยนะคะ",
             1, "month_day_digit", "0", "07:00", now_str),
        )
        conn.execute(
            "INSERT INTO reminders (name, message, enabled, schedule_type, schedule_value, send_time, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            ("ล้างห้องน้ำ", "🚿 วันนี้ล้างห้องน้ำด้วยนะคะ",
             1, "weekday", "0,3", "07:00", now_str),
        )
        conn.commit()
    conn.close()


_seed_default_reminders()


def _should_fire_today(r: dict, today: date) -> bool:
    stype = r["schedule_type"]
    sval  = r["schedule_value"]
    if stype == "month_day_digit":
        digits = [d.strip() for d in sval.split(",") if d.strip()]
        return any(str(today.day).endswith(d) for d in digits)
    if stype == "weekday":
        days = [int(d.strip()) for d in sval.split(",") if d.strip()]
        return today.weekday() in days
    return False


def _check_reminders():
    """Runs every 60 s. Fires LINE reminder if time + schedule match and not already sent today."""
    tz          = ZoneInfo(os.environ.get("TZ", "Asia/Bangkok"))
    now         = datetime.now(tz)
    today_str   = now.strftime("%Y-%m-%d")
    current_hm  = now.strftime("%H:%M")
    today       = now.date()

    conn = get_db()
    rows = conn.execute("SELECT * FROM reminders WHERE enabled=1").fetchall()
    conn.close()

    for row in rows:
        r = dict(row)
        if r["send_time"] != current_hm:
            continue
        if r.get("last_sent_date") == today_str:
            continue
        if not _should_fire_today(r, today):
            continue

        line_notify.notify_reminder(r["name"], r["message"])

        conn2 = get_db()
        conn2.execute(
            "UPDATE reminders SET last_sent_date=? WHERE id=?",
            (today_str, r["id"]),
        )
        conn2.commit()
        conn2.close()


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
    half_day: bool = False


class ResignRequest(BaseModel):
    end_date: str
    resign_note: Optional[str] = None


class ReminderCreate(BaseModel):
    name: str
    message: str
    enabled: bool = True
    schedule_type: str   # 'month_day_digit' | 'weekday'
    schedule_value: str  # digits: "0" or "0,5" | weekdays: "0,3" (0=Mon…6=Sun)
    send_time: str = "07:00"


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
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        raise HTTPException(404, "Employee not found")
    emp = dict(emp)
    conn.execute(
        "UPDATE employees SET end_date=?, resign_note=? WHERE id=?",
        (req.end_date, req.resign_note, emp_id),
    )
    conn.commit()
    conn.close()

    line_notify.notify_resign(
        emp_id=emp_id,
        emp_name=emp["name"],
        end_date_str=req.end_date,
        resign_note=req.resign_note,
        start_date=date.fromisoformat(emp["start_date"]),
        monthly_salary=emp["monthly_salary"],
    )

    return {"message": "resigned"}


@app.delete("/api/employees/{emp_id}/resign")
def cancel_resign(emp_id: int):
    conn = get_db()
    # Fetch employee name before clearing resign data
    emp = conn.execute("SELECT name FROM employees WHERE id=?", (emp_id,)).fetchone()
    emp_name = emp["name"] if emp else None
    conn.execute(
        "UPDATE employees SET end_date=NULL, resign_note=NULL WHERE id=?",
        (emp_id,),
    )
    conn.commit()
    conn.close()

    if emp_name:
        line_notify.notify_cancel_resign(emp_name=emp_name)

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
        "SELECT work_date, status, half_day FROM attendance WHERE employee_id=? AND work_date <= ?",
        (emp_id, emp["end_date"]),
    ).fetchall()
    conn.close()

    saved = {r["work_date"]: {"status": r["status"], "half_day": bool(r["half_day"])} for r in all_rows}

    # Cumulative balance across ALL time (start → end_date)
    total_comp = total_leave = 0.0
    d = start_date
    while d <= end_date:
        rec = saved.get(d.isoformat(), {"status": default_status(d), "half_day": False})
        inc = 0.5 if rec["half_day"] else 1
        if rec["status"] == "compensatory":
            total_comp += inc
        elif rec["status"] == "leave":
            total_leave += inc
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
        "SELECT work_date, status, note, half_day FROM attendance WHERE employee_id=? AND work_date LIKE ?",
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
            result.append({"date": ds, "status": "before_start", "note": None, "half_day": False, "is_future": False})
            continue
        is_future = d > today
        if ds in saved:
            r = saved[ds]
            result.append({"date": ds, "status": r["status"], "note": r["note"], "half_day": bool(r["half_day"]), "is_future": is_future})
        else:
            result.append({"date": ds, "status": default_status(d), "note": None, "half_day": False, "is_future": is_future})
    return result


@app.post("/api/employees/{emp_id}/attendance")
def upsert_attendance(emp_id: int, att: AttendanceUpdate):
    if att.status not in ("work", "leave", "holiday", "compensatory"):
        raise HTTPException(400, "Invalid status")
    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        raise HTTPException(404, "Employee not found")
    emp = dict(emp)

    # Capture previous record before overwriting (needed for cancel detection)
    prev = conn.execute(
        "SELECT status, half_day FROM attendance WHERE employee_id=? AND work_date=?",
        (emp_id, att.work_date),
    ).fetchone()
    prev_status   = prev["status"]   if prev else None
    prev_half_day = bool(prev["half_day"]) if prev else False

    conn.execute(
        "INSERT INTO attendance (employee_id, work_date, status, note, half_day) VALUES (?,?,?,?,?) "
        "ON CONFLICT(employee_id, work_date) DO UPDATE SET status=excluded.status, note=excluded.note, half_day=excluded.half_day",
        (emp_id, att.work_date, att.status, att.note, int(att.half_day)),
    )
    conn.commit()
    conn.close()

    start_date     = date.fromisoformat(emp["start_date"])
    monthly_salary = emp["monthly_salary"]

    if att.status in ("leave", "compensatory"):
        # New leave/comp recorded
        line_notify.notify_attendance(
            emp_id=emp_id,
            emp_name=emp["name"],
            work_date=att.work_date,
            status=att.status,
            half_day=att.half_day,
            start_date=start_date,
            monthly_salary=monthly_salary,
        )
    elif att.status in ("work", "holiday") and prev_status in ("leave", "compensatory"):
        # Cancelled a previously recorded leave or compensatory day
        line_notify.notify_cancel_attendance(
            emp_id=emp_id,
            emp_name=emp["name"],
            work_date=att.work_date,
            prev_status=prev_status,
            prev_half_day=prev_half_day,
            start_date=start_date,
            monthly_salary=monthly_salary,
        )

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
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        raise HTTPException(404, "Employee not found")
    emp = dict(emp)

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

    # Fetch paid amount from payments list to include in notification
    wd_month = working_days_in_month(year, month)
    dr = emp["monthly_salary"] / wd_month if wd_month else 0
    half_salary = emp["monthly_salary"] / 2
    start_date = date.fromisoformat(emp["start_date"])
    _, n = calendar.monthrange(year, month)
    if start_date.year == year and start_date.month == month:
        billable = sum(
            1 for day in range(start_date.day, n + 1)
            if date(year, month, day).weekday() != 6
        )
        base_salary = dr * billable
    else:
        base_salary = emp["monthly_salary"]
    amount = half_salary if period == 1 else round(base_salary - half_salary, 2)

    conn.commit()
    conn.close()

    if paid_at:
        line_notify.notify_payment(
            emp_id=emp_id,
            emp_name=emp["name"],
            year=year,
            month=month,
            period=period,
            amount=round(amount, 2),
            paid_at=paid_at,
            start_date=start_date,
            monthly_salary=emp["monthly_salary"],
        )

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
        "SELECT work_date, status, half_day FROM attendance WHERE employee_id=? AND work_date <= ?",
        (emp_id, f"{year}-{month:02d}-31"),
    ).fetchall()
    conn.close()

    saved_all = {r["work_date"]: {"status": r["status"], "half_day": bool(r["half_day"])} for r in all_rows}

    # Carryover: cumulative balance from months before this one
    carryover_balance = 0.0
    if start_date < date(year, month, 1):
        c_comp = c_leave = 0.0
        d = start_date
        cutoff = date(year, month, 1)
        while d < cutoff and d <= today:
            rec = saved_all.get(d.isoformat(), {"status": default_status(d), "half_day": False})
            inc = 0.5 if rec["half_day"] else 1
            if rec["status"] == "compensatory":
                c_comp += inc
            elif rec["status"] == "leave":
                c_leave += inc
            d += timedelta(days=1)
        carryover_balance = c_comp - c_leave

    _, n = calendar.monthrange(year, month)
    saved = {k: v for k, v in saved_all.items() if k.startswith(f"{year}-{month:02d}-")}
    counts = {"work": 0.0, "leave": 0.0, "holiday": 0.0, "compensatory": 0.0}

    for day in range(1, n + 1):
        d = date(year, month, day)
        if d < start_date or d > today:
            continue
        ds = d.isoformat()
        rec = saved.get(ds, {"status": default_status(d), "half_day": False})
        inc = 0.5 if rec["half_day"] else 1
        counts[rec["status"]] = counts.get(rec["status"], 0) + inc

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
        "SELECT work_date, status, half_day FROM attendance WHERE employee_id=?", (emp_id,)
    ).fetchall()
    conn.close()

    saved = {r["work_date"]: {"status": r["status"], "half_day": bool(r["half_day"])} for r in rows}
    counts = {"work": 0.0, "leave": 0.0, "holiday": 0.0, "compensatory": 0.0}

    d = start_date
    while d <= end:
        ds = d.isoformat()
        rec = saved.get(ds, {"status": default_status(d), "half_day": False})
        inc = 0.5 if rec["half_day"] else 1
        counts[rec["status"]] = counts.get(rec["status"], 0) + inc
        d += timedelta(days=1)

    total_days = (end - start_date).days + 1
    balance = counts["compensatory"] - counts["leave"]

    # Daily rate preview using current month's working days
    wd_month = working_days_in_month(today.year, today.month)
    dr = emp["monthly_salary"] / wd_month if wd_month else 0
    balance_amount = round(balance * dr, 2)

    return {
        "start_date": emp["start_date"],
        "total_days_employed": total_days,
        "total_work_days": counts["work"],
        "total_leave_days": counts["leave"],
        "total_holiday_days": counts["holiday"],
        "total_compensatory_days": counts["compensatory"],
        "overall_balance": balance,
        "daily_rate": round(dr, 2),
        "balance_amount": balance_amount,
    }


# ---------- Reminder endpoints ----------

@app.get("/api/reminders")
def list_reminders():
    conn = get_db()
    rows = conn.execute("SELECT * FROM reminders ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/api/reminders", status_code=201)
def create_reminder(rem: ReminderCreate):
    if rem.schedule_type not in ("month_day_digit", "weekday"):
        raise HTTPException(400, "Invalid schedule_type")
    conn = get_db()
    c = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c.execute(
        "INSERT INTO reminders (name, message, enabled, schedule_type, schedule_value, send_time, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (rem.name, rem.message, int(rem.enabled),
         rem.schedule_type, rem.schedule_value, rem.send_time, now_str),
    )
    new_id = c.lastrowid
    conn.commit()
    conn.close()
    return {"id": new_id}


@app.put("/api/reminders/{rem_id}")
def update_reminder(rem_id: int, rem: ReminderCreate):
    if rem.schedule_type not in ("month_day_digit", "weekday"):
        raise HTTPException(400, "Invalid schedule_type")
    conn = get_db()
    c = conn.cursor()
    c.execute(
        "UPDATE reminders SET name=?, message=?, enabled=?, "
        "schedule_type=?, schedule_value=?, send_time=? WHERE id=?",
        (rem.name, rem.message, int(rem.enabled),
         rem.schedule_type, rem.schedule_value, rem.send_time, rem_id),
    )
    if c.rowcount == 0:
        conn.close()
        raise HTTPException(404, "Reminder not found")
    conn.commit()
    conn.close()
    return {"message": "updated"}


@app.post("/api/reminders/{rem_id}/toggle")
def toggle_reminder(rem_id: int):
    conn = get_db()
    row = conn.execute("SELECT enabled FROM reminders WHERE id=?", (rem_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Reminder not found")
    new_enabled = 1 - row["enabled"]
    conn.execute("UPDATE reminders SET enabled=? WHERE id=?", (new_enabled, rem_id))
    conn.commit()
    conn.close()
    return {"enabled": bool(new_enabled)}


@app.delete("/api/reminders/{rem_id}")
def delete_reminder(rem_id: int):
    conn = get_db()
    conn.execute("DELETE FROM reminders WHERE id=?", (rem_id,))
    conn.commit()
    conn.close()
    return {"message": "deleted"}


@app.post("/api/reminders/{rem_id}/test")
def test_reminder(rem_id: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM reminders WHERE id=?", (rem_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, "Reminder not found")
    r = dict(row)
    line_notify.notify_reminder(r["name"], r["message"])
    return {"message": "sent"}


# ---------- LINE Webhook ----------

def _resolve_employee(text: str) -> dict | None:
    """
    Find the active employee to record attendance for.
    - 1 active employee  → return that employee automatically
    - Multiple           → try to find a name mention in text; if ambiguous send a clarification message
    Returns None and handles the LINE message internally when it cannot resolve.
    """
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM employees WHERE end_date IS NULL OR end_date=''",
    ).fetchall()
    conn.close()

    active = [dict(r) for r in rows]

    if not active:
        line_notify.send_line("⚠️ ไม่พบข้อมูลพนักงานที่ active ในระบบ")
        return None

    if len(active) == 1:
        return active[0]

    # Multiple active employees — try to match by name mentioned in the message
    matched = [e for e in active if e["name"] in text]
    if len(matched) == 1:
        return matched[0]

    names = ", ".join(e["name"] for e in active)
    line_notify.send_line(
        f"⚠️ มีพนักงาน {len(active)} คน ({names})\n"
        f"กรุณาระบุชื่อในข้อความด้วยนะคะ เช่น '[ชื่อ]ขอลาวันนี้'"
    )
    return None


@app.post("/webhook/line")
async def line_webhook(request: Request):
    """
    Receives LINE Messaging API webhook events.
    Anyone in the LINE group can trigger attendance recording:
      - Leave:        "วันนี้ขอลานะคะ", "ขอหยุดวันนี้", ...
      - Compensatory: "วันนี้ทำชดเชย", "ทำงานวันอาทิตย์", ...
    Add "ครึ่งวัน" in the message for a half-day entry.

    Required env: LINE_CHANNEL_SECRET (for signature verification)
    Optional:     leave blank to skip verification (dev/testing only)
    """
    body = await request.body()

    # Verify LINE signature (HMAC-SHA256)
    if _LINE_CHANNEL_SECRET:
        signature = request.headers.get("X-Line-Signature", "")
        computed = base64.b64encode(
            hmac.new(_LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
        ).decode()
        if not hmac.compare_digest(computed, signature):
            raise HTTPException(400, "Invalid LINE signature")

    try:
        data = json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    tz = ZoneInfo(os.environ.get("TZ", "Asia/Bangkok"))
    today = datetime.now(tz).date()
    today_str = today.isoformat()

    for event in data.get("events", []):
        if event.get("type") != "message":
            continue
        msg = event.get("message", {})
        if msg.get("type") != "text":
            continue

        text = msg.get("text", "").strip()

        is_leave = any(kw in text for kw in _LEAVE_KEYWORDS)
        is_comp  = any(kw in text for kw in _COMP_KEYWORDS)

        if not is_leave and not is_comp:
            continue

        # Leave takes precedence if both somehow match
        status     = "leave" if is_leave else "compensatory"
        is_half_day = any(kw in text for kw in _HALF_DAY_KEYWORDS)

        emp = _resolve_employee(text)
        if emp is None:
            continue

        # Leave on Sunday is redundant — it's already a holiday
        if status == "leave" and today.weekday() == 6:
            line_notify.send_line(
                f"📅 วันนี้วันอาทิตย์ เป็นวันหยุดอยู่แล้วนะคะ {emp['name']} 😊"
            )
            continue

        # Check for duplicate record today with the same status
        conn = get_db()
        prev = conn.execute(
            "SELECT status, half_day FROM attendance WHERE employee_id=? AND work_date=?",
            (emp["id"], today_str),
        ).fetchone()

        if prev and prev["status"] == status:
            conn.close()
            STATUS_LABEL = {"leave": "ลา", "compensatory": "ชดเชย"}
            half_label = " (ครึ่งวัน)" if bool(prev["half_day"]) else " (เต็มวัน)"
            line_notify.send_line(
                f"✅ บันทึกแล้วนะคะ — {emp['name']}\n"
                f"📅 {today_str}: {STATUS_LABEL[status]}{half_label} (บันทึกไว้แล้วก่อนหน้านี้)"
            )
            continue

        NOTE = {"leave": "แจ้งลาผ่าน LINE", "compensatory": "แจ้งชดเชยผ่าน LINE"}
        conn.execute(
            "INSERT INTO attendance (employee_id, work_date, status, note, half_day) VALUES (?,?,?,?,?) "
            "ON CONFLICT(employee_id, work_date) DO UPDATE SET status=excluded.status, note=excluded.note, half_day=excluded.half_day",
            (emp["id"], today_str, status, NOTE[status], int(is_half_day)),
        )
        conn.commit()
        conn.close()

        start_date = date.fromisoformat(emp["start_date"])
        line_notify.notify_attendance(
            emp_id=emp["id"],
            emp_name=emp["name"],
            work_date=today_str,
            status=status,
            half_day=is_half_day,
            start_date=start_date,
            monthly_salary=emp["monthly_salary"],
        )

    return {"status": "ok"}


# ---------- Static + SPA fallback ----------

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    return FileResponse("static/index.html")
