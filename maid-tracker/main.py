from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel
from typing import Optional
from contextlib import asynccontextmanager
import csv
import io
import sqlite3
from urllib.parse import quote
import os
import hmac
import hashlib
import base64
import json
import secrets
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
import calendar
import gzip
import glob
import shutil
import line_notify
from keywords import (
    LEAVE_KEYWORDS, COMP_KEYWORDS, HALF_DAY_KEYWORDS, BALANCE_KEYWORDS,
    PAYMENT_KEYWORDS, PAYMENT_PERIOD1_KEYWORDS, PAYMENT_PERIOD2_KEYWORDS, PAYMENT_BOTH_KEYWORDS,
    YESTERDAY_KEYWORDS,
)
from calc import (
    default_status,
    working_days_in_month,
    compute_overall_balance,
    compute_resign_summary,
    compute_leave_deduction,
    compute_monthly_leave_balance,
)
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

_scheduler = BackgroundScheduler(timezone=os.environ.get("TZ", "Asia/Bangkok"))
_TZ = ZoneInfo(os.environ.get("TZ", "Asia/Bangkok"))

_MONTHLY_REPORT_TIME = os.environ.get("MONTHLY_REPORT_TIME", "20:00")
_report_h, _report_m = _MONTHLY_REPORT_TIME.split(":")

_BACKUP_DIR = os.environ.get("MAID_BACKUP_DIR", "/data/backups")
_BACKUP_RETENTION_DAYS = int(os.environ.get("MAID_BACKUP_RETENTION_DAYS", "30"))


def _backup_db() -> Optional[str]:
    """Daily SQLite backup via Online Backup API + gzip. Returns path written.

    Uses sqlite3.Connection.backup() for a consistent snapshot even while writes
    occur. Prunes files older than MAID_BACKUP_RETENTION_DAYS afterwards.
    """
    try:
        os.makedirs(_BACKUP_DIR, exist_ok=True)
        stamp = datetime.now(_TZ).strftime("%Y%m%d-%H%M%S")
        plain_path = os.path.join(_BACKUP_DIR, f"maid-{stamp}.db")
        gz_path = plain_path + ".gz"

        src = sqlite3.connect(DB_PATH)
        try:
            dst = sqlite3.connect(plain_path)
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()

        with open(plain_path, "rb") as fin, gzip.open(gz_path, "wb", compresslevel=6) as fout:
            shutil.copyfileobj(fin, fout)
        os.remove(plain_path)

        cutoff = time.time() - _BACKUP_RETENTION_DAYS * 86400
        for f in glob.glob(os.path.join(_BACKUP_DIR, "maid-*.db.gz")):
            try:
                if os.path.getmtime(f) < cutoff:
                    os.remove(f)
            except OSError:
                pass

        return gz_path
    except Exception as e:
        print(f"[backup] failed: {e}", flush=True)
        return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Fire every minute so each reminder's send_time can be matched exactly
    _scheduler.add_job(_check_reminders, CronTrigger(minute="*"), id="check_reminders")
    # Fire once — at the configured time on the last calendar day of each month
    _scheduler.add_job(
        _send_monthly_report,
        CronTrigger(day="last", hour=int(_report_h), minute=int(_report_m)),
        id="monthly_report",
    )
    # Daily SQLite backup at 03:00 local time
    _scheduler.add_job(_backup_db, CronTrigger(hour=3, minute=0), id="daily_backup")
    _scheduler.start()
    yield
    _scheduler.shutdown(wait=False)

app = FastAPI(title="Maid Tracker", lifespan=lifespan)

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "maid_tracker.db")

_MAID_LINE_CHANNEL_SECRET = os.environ.get("MAID_LINE_CHANNEL_SECRET", "")

# ---------- HTTP Basic Auth ----------
# Set NGINX_BASIC_AUTH_USER + NGINX_BASIC_AUTH_PASS in .env to enable.
# If both are empty, auth is disabled (open access — safe inside LAN/VPN).
_BASIC_USER = os.environ.get("NGINX_BASIC_AUTH_USER", "").strip()
_BASIC_PASS = os.environ.get("NGINX_BASIC_AUTH_PASS", "").strip()

_AUTH_SKIP_PATHS = {"/webhook/line"}
_SESSION_MAX_AGE = 7 * 24 * 3600  # 7 days
_sessions: dict[str, float] = {}   # token → expiry timestamp


def _validate_basic(auth_header: str) -> bool:
    if not auth_header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(auth_header[6:]).decode()
        user, _, pw = decoded.partition(":")
        return (
            hmac.compare_digest(user.encode(), _BASIC_USER.encode())
            and hmac.compare_digest(pw.encode(), _BASIC_PASS.encode())
        )
    except Exception:
        return False


@app.middleware("http")
async def basic_auth_middleware(request: Request, call_next):
    if not _BASIC_USER or request.url.path in _AUTH_SKIP_PATHS:
        return await call_next(request)

    now = time.time()

    # 1. Valid session cookie → pass through immediately
    token = request.cookies.get("maid_session")
    if token:
        expiry = _sessions.get(token)
        if expiry and expiry > now:
            return await call_next(request)
        _sessions.pop(token, None)  # expired — remove

    # 2. Valid Basic Auth → issue session cookie and pass through
    if _validate_basic(request.headers.get("Authorization", "")):
        new_token = secrets.token_hex(32)
        _sessions[new_token] = now + _SESSION_MAX_AGE
        response = await call_next(request)
        response.set_cookie(
            "maid_session", new_token,
            max_age=_SESSION_MAX_AGE,
            httponly=True,
            samesite="lax",
        )
        return response

    return Response(
        status_code=401,
        content="Authentication required",
        headers={"WWW-Authenticate": "Basic realm=\"Maid Tracker\""},
    )


def _parse_target_date(text: str, today: date) -> date:
    """Return the attendance date the message refers to. Default: today."""
    if any(kw in text for kw in YESTERDAY_KEYWORDS):
        return today - timedelta(days=1)
    return today


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
    try:
        c.execute("ALTER TABLE employees ADD COLUMN max_leave_carry REAL")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE salary_payments ADD COLUMN leave_deduction_days REAL DEFAULT 0")
    except Exception:
        pass
    # Holiday mode migration
    try:
        c.execute("ALTER TABLE employees ADD COLUMN holiday_mode TEXT DEFAULT 'sunday'")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE employees ADD COLUMN monthly_leave_days REAL DEFAULT 0")
    except Exception:
        pass
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
    tz = _TZ
    now = datetime.now(tz)
    today_str = now.strftime("%Y-%m-%d")
    current_hm = now.strftime("%H:%M")
    today = now.date()

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

        conn = get_db()
        conn.execute(
            "UPDATE reminders SET last_sent_date=? WHERE id=?",
            (today_str, r["id"]),
        )
        conn.commit()
        conn.close()


_monthly_report_last_sent: str = ""  # guard against double-fire within the same minute


def _send_monthly_report():
    """Triggered by CronTrigger on the last day of each month at MONTHLY_REPORT_TIME."""
    global _monthly_report_last_sent

    tz = _TZ
    month_key = datetime.now(tz).strftime("%Y-%m")
    if _monthly_report_last_sent == month_key:
        return

    conn = get_db()
    rows = conn.execute(
        "SELECT id, name, start_date, monthly_salary FROM employees "
        "WHERE end_date IS NULL OR end_date=''"
    ).fetchall()
    conn.close()

    line_notify.notify_monthly_report([dict(r) for r in rows])
    _monthly_report_last_sent = month_key


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
    max_leave_carry: Optional[float] = None  # max leave-debt days (sunday) / max accumulated days (monthly)
    holiday_mode: str = "sunday"             # 'sunday' | 'monthly'
    monthly_leave_days: float = 0.0          # leave days credited per month (monthly mode only)


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
        "INSERT INTO employees (name,age,nationality,phone,line_id,facebook,start_date,monthly_salary,"
        "max_leave_carry,holiday_mode,monthly_leave_days) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (emp.name, emp.age, emp.nationality, emp.phone, emp.line_id, emp.facebook,
         emp.start_date, emp.monthly_salary, emp.max_leave_carry,
         emp.holiday_mode, emp.monthly_leave_days),
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
        "UPDATE employees SET name=?,age=?,nationality=?,phone=?,line_id=?,facebook=?,start_date=?,monthly_salary=?,"
        "max_leave_carry=?,holiday_mode=?,monthly_leave_days=? WHERE id=?",
        (emp.name, emp.age, emp.nationality, emp.phone, emp.line_id, emp.facebook,
         emp.start_date, emp.monthly_salary, emp.max_leave_carry,
         emp.holiday_mode, emp.monthly_leave_days, emp_id),
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
    end_date   = date.fromisoformat(emp["end_date"])
    conn.close()

    s = compute_resign_summary(
        emp_id, start_date, end_date, emp["monthly_salary"],
        holiday_mode=emp.get("holiday_mode", "sunday"),
        monthly_leave_days=emp.get("monthly_leave_days") or 0.0,
        max_leave_carry=emp.get("max_leave_carry"),
    )

    return {
        "end_date":               emp["end_date"],
        "resign_note":            emp.get("resign_note"),
        "monthly_salary":         emp["monthly_salary"],
        "daily_rate":             s["daily_rate"],
        "working_days_in_month":  working_days_in_month(end_date.year, end_date.month),
        "billable_days":          round(s["base_salary"] / s["daily_rate"]) if s["daily_rate"] else 0,
        "base_salary":            s["base_salary"],
        "total_compensatory_days": s["total_comp"],
        "total_leave_days":       s["total_leave"],
        "cumulative_balance":     s["cumulative_balance"],
        "balance_amount":         s["balance_amount"],
        "final_amount":           s["final_amount"],
    }


# ---------- Attendance endpoints ----------

@app.get("/api/employees/{emp_id}/attendance")
def get_attendance(emp_id: int, year: int, month: int):
    conn = get_db()
    row = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, "Employee not found")
    emp          = dict(row)
    start_date   = date.fromisoformat(emp["start_date"])
    holiday_mode = emp.get("holiday_mode") or "sunday"
    today        = date.today()

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
            result.append({"date": ds, "status": default_status(d, holiday_mode), "note": None, "half_day": False, "is_future": is_future})
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
    holiday_mode = (emp["holiday_mode"] or "sunday")
    # Monthly mode: reject compensatory / holiday — those concepts don't apply
    if holiday_mode == "monthly" and att.status in ("compensatory", "holiday"):
        conn.close()
        raise HTTPException(400, "Compensatory/holiday status not applicable in monthly-leave mode")

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


@app.get("/api/employees/{emp_id}/leave-balance")
def get_leave_balance(emp_id: int):
    """Monthly-mode: return current accumulated leave balance."""
    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        raise HTTPException(404, "Employee not found")
    emp = dict(emp)
    conn.close()
    if (emp.get("holiday_mode") or "sunday") != "monthly":
        raise HTTPException(400, "leave-balance only applies to monthly holiday mode")
    start_date = date.fromisoformat(emp["start_date"])
    lb = compute_monthly_leave_balance(
        emp_id, start_date,
        emp.get("monthly_leave_days") or 0.0,
        emp.get("max_leave_carry"),
    )
    return lb


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
    # Still in probation → no monthly periods at all (pay is daily via daily-payments)
    if emp.get("employment_status") == "probation":
        conn.close()
        return []
    anchor = date.fromisoformat(emp["monthly_start_date"]) if emp.get("monthly_start_date") else start_date
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
    if anchor.year == year and anchor.month == month:
        billable = sum(
            1 for day in range(anchor.day, n + 1)
            if date(year, month, day).weekday() != 6
        )
        base_salary = dr * billable
    else:
        base_salary = emp["monthly_salary"]

    # Policy: no monthly deduction — always pay full base salary.
    # If the employee started after the 15th their first month, period 1 is skipped,
    # so period 2 should pay the entire prorated base salary (not base - half).
    first_month_after_15 = (
        anchor.year == year
        and anchor.month == month
        and anchor > mid_day
    )
    period2_amount = base_salary if first_month_after_15 else base_salary - half_salary

    # Leave deduction for period 2 (applied when max_leave_carry is configured)
    max_carry = emp.get("max_leave_carry")
    p2_deduction_days   = 0.0
    p2_deduction_amount = 0.0
    if max_carry is not None and max_carry >= 0:
        ded = compute_leave_deduction(emp_id, year, month, max_carry, emp["monthly_salary"], anchor)
        p2_deduction_days   = ded["deduction_days"]
        p2_deduction_amount = ded["deduction_amount"]

    result = []

    # Period 1 (15th) — skip if employee started after 15th or resigned before 15th
    if anchor <= mid_day and (end_date is None or end_date >= mid_day):
        result.append({
            "period": 1,
            "due_date": mid_day.isoformat(),
            "amount": round(half_salary, 2),
            "leave_deduction_days": 0.0,
            "deduction_amount": 0.0,
            "paid": bool(paid_map.get(1)),
            "paid_at": paid_map.get(1),
        })

    # Period 2 (last day or resignation date if resigned this month)
    period2_due = last_day
    if end_date and end_date.year == year and end_date.month == month:
        period2_due = end_date

    if anchor <= last_day and (end_date is None or end_date >= date(year, month, 1)):
        result.append({
            "period": 2,
            "due_date": period2_due.isoformat(),
            "amount": round(period2_amount - p2_deduction_amount, 2),
            "leave_deduction_days": round(p2_deduction_days, 2),
            "deduction_amount": round(p2_deduction_amount, 2),
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

    amount, toggle_deduction_days, toggle_deduction_amount = _compute_period_amount(emp, year, month, period)

    if existing and existing["paid_at"]:
        conn.execute(
            "UPDATE salary_payments SET paid_at=NULL, leave_deduction_days=0 "
            "WHERE employee_id=? AND year=? AND month=? AND period=?",
            (emp_id, year, month, period),
        )
        paid_at = None
    else:
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        conn.execute(
            "INSERT INTO salary_payments (employee_id, year, month, period, paid_at, leave_deduction_days) "
            "VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(employee_id, year, month, period) DO UPDATE SET "
            "paid_at=excluded.paid_at, leave_deduction_days=excluded.leave_deduction_days",
            (emp_id, year, month, period, now, round(toggle_deduction_days, 2)),
        )
        paid_at = now

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
            deduction_days=toggle_deduction_days,
            deduction_amount=toggle_deduction_amount,
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
    start_date   = date.fromisoformat(emp["start_date"])
    holiday_mode = emp.get("holiday_mode") or "sunday"
    today        = date.today()

    all_rows = conn.execute(
        "SELECT work_date, status, half_day FROM attendance WHERE employee_id=? AND work_date <= ?",
        (emp_id, f"{year}-{month:02d}-31"),
    ).fetchall()
    conn.close()

    saved_all = {r["work_date"]: {"status": r["status"], "half_day": bool(r["half_day"])} for r in all_rows}

    _, n = calendar.monthrange(year, month)
    saved = {k: v for k, v in saved_all.items() if k.startswith(f"{year}-{month:02d}-")}
    counts = {"work": 0.0, "leave": 0.0, "holiday": 0.0, "compensatory": 0.0}

    for day in range(1, n + 1):
        d = date(year, month, day)
        if d < start_date or d > today:
            continue
        ds = d.isoformat()
        rec = saved.get(ds, {"status": default_status(d, holiday_mode), "half_day": False})
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

    max_carry = emp.get("max_leave_carry")

    # ── Monthly mode ──────────────────────────────────────────
    if holiday_mode == "monthly":
        monthly_leave_days = emp.get("monthly_leave_days") or 0.0
        # Balance up through end of this month (or today, whichever earlier)
        up_to_date = min(date(year, month, n), today)
        lb = compute_monthly_leave_balance(
            emp_id, start_date, monthly_leave_days, max_leave_carry=max_carry, up_to=up_to_date
        )
        # Balance at start of this month (for carryover display)
        prev_end = date(year, month, 1) - timedelta(days=1)
        if prev_end >= start_date:
            lb_prev = compute_monthly_leave_balance(
                emp_id, start_date, monthly_leave_days, max_leave_carry=max_carry, up_to=prev_end
            )
            carryover_balance = lb_prev["balance"]
        else:
            carryover_balance = 0.0

        accrued_this_month = lb["total_accrued"] - (lb_prev["total_accrued"] if prev_end >= start_date else 0.0)
        leave_balance = lb["balance"]
        deduction_days = abs(leave_balance) if leave_balance < 0 else 0.0
        deduction_amount = round(deduction_days * dr, 2)
        actual_pay = base_salary - deduction_amount

        return {
            "year": year, "month": month,
            "employee_name": emp["name"],
            "holiday_mode": "monthly",
            "monthly_leave_days": monthly_leave_days,
            "monthly_salary": emp["monthly_salary"],
            "max_leave_carry": max_carry,
            "daily_rate": round(dr, 2),
            "working_days_in_month": wd_month,
            "base_salary": round(base_salary, 2),
            "work_days": counts["work"],
            "leave_days": counts["leave"],
            "holiday_days": 0,
            "compensatory_days": 0,
            "accrued_this_month": round(accrued_this_month, 2),
            "carryover_balance": round(carryover_balance, 2),
            "leave_balance": round(leave_balance, 2),
            "can_accrue_more": lb["can_accrue_more"],
            "balance": round(leave_balance, 2),
            "cumulative_balance": round(leave_balance, 2),
            "leave_deduction_days": round(deduction_days, 2),
            "deduction_amount": round(deduction_amount, 2),
            "money_owed": round(deduction_amount, 2),
            "money_credit": 0,
            "actual_pay": round(actual_pay, 2),
        }

    # ── Sunday mode ───────────────────────────────────────────
    # Carryover: cumulative balance from months before this one
    carryover_balance = 0.0
    if start_date < date(year, month, 1):
        c_comp = c_leave = 0.0
        d = start_date
        cutoff = date(year, month, 1)
        while d < cutoff and d <= today:
            rec = saved_all.get(d.isoformat(), {"status": default_status(d, "sunday"), "half_day": False})
            inc = 0.5 if rec["half_day"] else 1
            if rec["status"] == "compensatory":
                c_comp += inc
            elif rec["status"] == "leave":
                c_leave += inc
            d += timedelta(days=1)
        carryover_balance = c_comp - c_leave

    balance = counts["compensatory"] - counts["leave"]
    cumulative_balance = carryover_balance + balance

    deduction_days   = 0.0
    deduction_amount = 0.0
    if max_carry is not None and max_carry >= 0:
        ded = compute_leave_deduction(emp_id, year, month, max_carry, emp["monthly_salary"], start_date)
        deduction_days   = ded["deduction_days"]
        deduction_amount = ded["deduction_amount"]

    actual_pay = base_salary - deduction_amount

    return {
        "year": year, "month": month,
        "employee_name": emp["name"],
        "holiday_mode": "sunday",
        "monthly_salary": emp["monthly_salary"],
        "max_leave_carry": max_carry,
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
        "leave_deduction_days": round(deduction_days, 2),
        "deduction_amount": round(deduction_amount, 2),
        "money_owed": round(deduction_amount, 2),
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

    holiday_mode = emp.get("holiday_mode") or "sunday"
    saved = {r["work_date"]: {"status": r["status"], "half_day": bool(r["half_day"])} for r in rows}
    counts = {"work": 0.0, "leave": 0.0, "holiday": 0.0, "compensatory": 0.0}

    d = start_date
    while d <= end:
        ds = d.isoformat()
        rec = saved.get(ds, {"status": default_status(d, holiday_mode), "half_day": False})
        inc = 0.5 if rec["half_day"] else 1
        counts[rec["status"]] = counts.get(rec["status"], 0) + inc
        d += timedelta(days=1)

    total_days = (end - start_date).days + 1

    # Daily rate preview using current month's working days
    wd_month = working_days_in_month(today.year, today.month)
    dr = emp["monthly_salary"] / wd_month if wd_month else 0

    if holiday_mode == "monthly":
        lb = compute_monthly_leave_balance(
            emp_id, start_date,
            emp.get("monthly_leave_days") or 0.0,
            emp.get("max_leave_carry"),
            up_to=end,
        )
        return {
            "start_date": emp["start_date"],
            "holiday_mode": "monthly",
            "monthly_leave_days": emp.get("monthly_leave_days") or 0.0,
            "total_days_employed": total_days,
            "total_work_days": counts["work"],
            "total_leave_days": lb["total_used"],
            "total_holiday_days": 0,
            "total_compensatory_days": 0,
            "overall_balance": lb["balance"],
            "leave_balance": lb["balance"],
            "total_accrued": lb["total_accrued"],
            "can_accrue_more": lb["can_accrue_more"],
            "daily_rate": round(dr, 2),
            "balance_amount": round(lb["balance"] * dr, 2),
        }

    balance = counts["compensatory"] - counts["leave"]
    balance_amount = round(balance * dr, 2)

    return {
        "start_date": emp["start_date"],
        "holiday_mode": "sunday",
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

def _compute_period_amount(emp: dict, year: int, month: int, period: int) -> tuple[float, float, float]:
    """
    Return (net_amount, deduction_days, deduction_amount) for the given period.
    Respects first-month proration and max_leave_carry deduction for period 2.
    """
    wd_month    = working_days_in_month(year, month)
    dr          = emp["monthly_salary"] / wd_month if wd_month else 0
    half_salary = emp["monthly_salary"] / 2
    start_date  = date.fromisoformat(emp["start_date"])
    anchor      = date.fromisoformat(emp["monthly_start_date"]) if emp.get("monthly_start_date") else start_date
    _, n        = calendar.monthrange(year, month)

    if anchor.year == year and anchor.month == month:
        billable    = sum(1 for day in range(anchor.day, n + 1) if date(year, month, day).weekday() != 6)
        base_salary = dr * billable
    else:
        base_salary = emp["monthly_salary"]

    mid_day             = date(year, month, 15)
    first_month_after15 = anchor.year == year and anchor.month == month and anchor > mid_day

    if period == 1:
        return round(half_salary, 2), 0.0, 0.0

    gross = base_salary if first_month_after15 else base_salary - half_salary
    deduction_days, deduction_amount = 0.0, 0.0
    max_carry = emp.get("max_leave_carry")
    if max_carry is not None and max_carry >= 0:
        ded = compute_leave_deduction(emp["id"], year, month, max_carry, emp["monthly_salary"], anchor)
        deduction_days   = ded["deduction_days"]
        deduction_amount = ded["deduction_amount"]
    return round(gross - deduction_amount, 2), deduction_days, deduction_amount


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

    Required env: MAID_LINE_CHANNEL_SECRET (for signature verification)
    Optional:     leave blank to skip verification (dev/testing only)
    """
    body = await request.body()

    # Verify LINE signature (HMAC-SHA256)
    if _MAID_LINE_CHANNEL_SECRET:
        signature = request.headers.get("X-Line-Signature", "")
        computed = base64.b64encode(
            hmac.new(_MAID_LINE_CHANNEL_SECRET.encode(), body, hashlib.sha256).digest()
        ).decode()
        if not hmac.compare_digest(computed, signature):
            raise HTTPException(400, "Invalid LINE signature")

    try:
        data = json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    tz = _TZ
    today = datetime.now(tz).date()
    today_str = today.isoformat()

    for event in data.get("events", []):
        if event.get("type") != "message":
            continue
        msg = event.get("message", {})
        if msg.get("type") != "text":
            continue

        text = msg.get("text", "").strip()

        is_leave   = any(kw in text for kw in LEAVE_KEYWORDS)
        is_comp    = any(kw in text for kw in COMP_KEYWORDS)
        is_balance = any(kw in text for kw in BALANCE_KEYWORDS)
        is_payment = any(kw in text for kw in PAYMENT_KEYWORDS)

        if not is_leave and not is_comp and not is_balance and not is_payment:
            continue

        # Balance query — resolve employee and reply with current balance
        if is_balance and not is_leave and not is_comp and not is_payment:
            emp = _resolve_employee(text)
            if emp is None:
                continue
            line_notify.notify_balance_query(
                emp_id=emp["id"],
                emp_name=emp["name"],
                start_date=date.fromisoformat(emp["start_date"]),
                monthly_salary=emp["monthly_salary"],
            )
            continue

        # Salary payment recording
        if is_payment and not is_leave and not is_comp:
            emp = _resolve_employee(text)
            if emp is None:
                continue

            # Determine which period(s) to mark as paid
            has_p1  = any(kw in text for kw in PAYMENT_PERIOD1_KEYWORDS)
            has_p2  = any(kw in text for kw in PAYMENT_PERIOD2_KEYWORDS)
            has_both = any(kw in text for kw in PAYMENT_BOTH_KEYWORDS)

            last_day_of_month = calendar.monthrange(today.year, today.month)[1]

            if has_both:
                target_periods = [1, 2]
            elif has_p1 and not has_p2:
                target_periods = [1]
            elif has_p2 and not has_p1:
                target_periods = [2]
            else:
                # Auto-detect from date — confident zones only; ask otherwise
                # Days 13–18: around 15th  →  Period 1
                # Days 24–last: near end of month  →  Period 2
                # Other days: genuinely unclear
                if 13 <= today.day <= 18:
                    target_periods = [1]
                elif today.day >= last_day_of_month - 6:
                    target_periods = [2]
                else:
                    line_notify.send_line(
                        f"❓ วันที่ {today.day} ระบบไม่แน่ใจว่าจ่ายรอบไหนนะคะ\n"
                        f"กรุณาระบุเพิ่มเติมด้วยนะคะ เช่น:\n"
                        f'• "จ่ายแล้ว กลางเดือน" → รอบ 1 (วันที่ 15)\n'
                        f'• "จ่ายแล้ว ปลายเดือน" → รอบ 2 (สิ้นเดือน)\n'
                        f'• "จ่ายแล้ว ทั้งเดือน" → ทั้งสองรอบ'
                    )
                    continue

            # Acknowledge before writing
            period_th = {1: "กลางเดือน (รอบ 1)", 2: "ปลายเดือน (รอบ 2)"}
            if len(target_periods) == 2:
                period_label = "ทั้งสองรอบ"
            else:
                period_label = period_th[target_periods[0]]
            line_notify.send_line(
                f"💰 กำลังบันทึกจ่ายเงินเดือน{period_label} ให้ {emp['name']} นะคะ..."
            )

            conn = get_db()
            start_date_emp = date.fromisoformat(emp["start_date"])
            paid_at = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S")

            for period in target_periods:
                existing = conn.execute(
                    "SELECT paid_at FROM salary_payments "
                    "WHERE employee_id=? AND year=? AND month=? AND period=?",
                    (emp["id"], today.year, today.month, period),
                ).fetchone()

                if existing and existing["paid_at"]:
                    conn.close()
                    line_notify.send_line(
                        f"ℹ️ {emp['name']} รอบ {period} เดือนนี้บันทึกว่าจ่ายแล้วก่อนหน้านี้นะคะ "
                        f"(จ่ายเมื่อ {existing['paid_at']})"
                    )
                    continue

                if existing:
                    conn.execute(
                        "UPDATE salary_payments SET paid_at=? "
                        "WHERE employee_id=? AND year=? AND month=? AND period=?",
                        (paid_at, emp["id"], today.year, today.month, period),
                    )
                else:
                    conn.execute(
                        "INSERT INTO salary_payments (employee_id, year, month, period, paid_at) "
                        "VALUES (?,?,?,?,?)",
                        (emp["id"], today.year, today.month, period, paid_at),
                    )
                conn.commit()

                amount, ded_days, ded_amount = _compute_period_amount(emp, today.year, today.month, period)
                # Save deduction info alongside the payment record
                conn.execute(
                    "UPDATE salary_payments SET leave_deduction_days=? "
                    "WHERE employee_id=? AND year=? AND month=? AND period=?",
                    (round(ded_days, 2), emp["id"], today.year, today.month, period),
                )
                conn.commit()
                line_notify.notify_payment(
                    emp_id=emp["id"],
                    emp_name=emp["name"],
                    year=today.year,
                    month=today.month,
                    period=period,
                    amount=amount,
                    paid_at=paid_at,
                    start_date=start_date_emp,
                    monthly_salary=emp["monthly_salary"],
                    deduction_days=ded_days,
                    deduction_amount=ded_amount,
                )

            conn.close()
            continue

        # Leave takes precedence if both somehow match
        status     = "leave" if is_leave else "compensatory"
        is_half_day = any(kw in text for kw in HALF_DAY_KEYWORDS)

        emp = _resolve_employee(text)
        if emp is None:
            continue

        target_date = _parse_target_date(text, today)
        target_date_str = target_date.isoformat()
        is_yesterday = target_date < today
        date_label = f"วันที่ {target_date_str}" if is_yesterday else "วันนี้"

        emp_holiday_mode = emp.get("holiday_mode") or "sunday"

        if emp_holiday_mode == "monthly":
            # Monthly mode: compensatory concept does not exist
            if status == "compensatory":
                line_notify.send_line(
                    f"ℹ️ {emp['name']} ใช้รูปแบบ 'เดือนละ {emp.get('monthly_leave_days', 0)} วัน' นะคะ\n"
                    f"ไม่มีวันชดเชยในโหมดนี้ค่ะ"
                )
                continue
            # Leave on any day is fine in monthly mode — fall through to record it
        else:
            # Leave on Sunday is redundant — it's already a holiday
            if status == "leave" and target_date.weekday() == 6:
                line_notify.send_line(
                    f"📅 {date_label}วันอาทิตย์ เป็นวันหยุดอยู่แล้วนะคะ {emp['name']} 😊\n"
                    f"ไม่ต้องลงวันลาค่ะ วันหยุดอยู่แล้ว"
                )
                continue

            # Compensatory only applies on Sunday (the designated day off)
            if status == "compensatory" and target_date.weekday() != 6:
                line_notify.send_line(
                    f"📅 {date_label}เป็นวันทำงานปกตินะคะ {emp['name']} 😊\n"
                    f"การบันทึกชดเชยใช้ได้เฉพาะวันอาทิตย์ที่มาทำงานเท่านั้นค่ะ"
                )
                continue

        # Check for duplicate record on target date with the same status
        conn = get_db()
        prev = conn.execute(
            "SELECT status, half_day FROM attendance WHERE employee_id=? AND work_date=?",
            (emp["id"], target_date_str),
        ).fetchone()

        if prev and prev["status"] == status:
            conn.close()
            STATUS_LABEL = {"leave": "ลา", "compensatory": "ชดเชย"}
            half_label = " (ครึ่งวัน)" if bool(prev["half_day"]) else " (เต็มวัน)"
            line_notify.send_line(
                f"✅ บันทึกแล้วนะคะ — {emp['name']}\n"
                f"📅 {target_date_str}: {STATUS_LABEL[status]}{half_label} (บันทึกไว้แล้วก่อนหน้านี้)"
            )
            continue

        # Acknowledge intent before writing — lets the group know action is in progress
        STATUS_ACK  = {"leave": "ลา", "compensatory": "ชดเชย"}
        half_ack    = "ครึ่งวัน" if is_half_day else "เต็มวัน"
        date_ack    = f" (วันที่ {target_date_str})" if is_yesterday else ""
        line_notify.send_line(
            f"📝 รับทราบค่ะ — {emp['name']}\n"
            f"🔄 กำลังบันทึก{STATUS_ACK[status]}{half_ack}{date_ack}ในระบบให้นะคะ..."
        )

        NOTE = {"leave": "แจ้งลาผ่าน LINE", "compensatory": "แจ้งชดเชยผ่าน LINE"}
        conn.execute(
            "INSERT INTO attendance (employee_id, work_date, status, note, half_day) VALUES (?,?,?,?,?) "
            "ON CONFLICT(employee_id, work_date) DO UPDATE SET status=excluded.status, note=excluded.note, half_day=excluded.half_day",
            (emp["id"], target_date_str, status, NOTE[status], int(is_half_day)),
        )
        conn.commit()
        conn.close()

        start_date = date.fromisoformat(emp["start_date"])
        line_notify.notify_attendance(
            emp_id=emp["id"],
            emp_name=emp["name"],
            work_date=target_date_str,
            status=status,
            half_day=is_half_day,
            start_date=start_date,
            monthly_salary=emp["monthly_salary"],
        )

    return {"status": "ok"}


# ---------- Export ----------

@app.get("/api/employees/{emp_id}/export/attendance")
def export_attendance(emp_id: int):
    conn = get_db()
    emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        conn.close()
        raise HTTPException(404, "Employee not found")
    emp = dict(emp)
    start_date   = date.fromisoformat(emp["start_date"])
    holiday_mode = emp.get("holiday_mode") or "sunday"
    end_date     = date.fromisoformat(emp["end_date"]) if emp.get("end_date") else date.today()

    att_rows = conn.execute(
        "SELECT work_date, status, half_day, note FROM attendance WHERE employee_id=? ORDER BY work_date",
        (emp_id,),
    ).fetchall()
    conn.close()

    saved = {r["work_date"]: dict(r) for r in att_rows}

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "status", "half_day", "note"])

    d = start_date
    while d <= end_date:
        ds = d.isoformat()
        rec = saved.get(ds)
        if rec:
            status = rec["status"]
            half_day = "true" if rec["half_day"] else "false"
            note = rec["note"] or ""
        else:
            status = default_status(d, holiday_mode)
            half_day = "false"
            note = ""
        writer.writerow([ds, status, half_day, note])
        d += timedelta(days=1)

    output.seek(0)
    filename = f"attendance_{emp['name']}_{date.today().isoformat()}.csv"
    encoded = quote(filename, safe="")
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename=\"attendance.csv\"; filename*=UTF-8''{encoded}"},
    )


@app.get("/api/employees/{emp_id}/payslip/{year}/{month}")
def export_payslip(emp_id: int, year: int, month: int):
    """Return a Thai-language payslip CSV for the given employee/month.

    Reuses get_summary() so the figures match the dashboard exactly.
    """
    s = get_summary(emp_id, year, month)

    thai_months = [
        "", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
        "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
    ]

    output = io.StringIO()
    w = csv.writer(output)
    w.writerow(["ใบรับเงินเดือน (Payslip)"])
    w.writerow([])
    w.writerow(["ลูกจ้าง", s["employee_name"]])
    w.writerow(["เดือน", f"{thai_months[month]} {year + 543}"])
    w.writerow(["โหมดวันหยุด", s["holiday_mode"]])
    w.writerow([])
    w.writerow(["รายการ", "จำนวน"])
    w.writerow(["เงินเดือนต่อเดือน (บาท)", f'{s["monthly_salary"]:.2f}'])
    w.writerow(["จำนวนวันทำงานในเดือน", s["working_days_in_month"]])
    w.writerow(["อัตราต่อวัน (บาท)", f'{s["daily_rate"]:.2f}'])
    w.writerow(["เงินเดือนพื้นฐาน (บาท)", f'{s["base_salary"]:.2f}'])
    w.writerow([])
    w.writerow(["วันทำงานจริง", s["work_days"]])
    w.writerow(["วันลา", s["leave_days"]])
    if s["holiday_mode"] == "sunday":
        w.writerow(["วันหยุดประจำสัปดาห์", s["holiday_days"]])
        w.writerow(["วันชดเชย (ทำงานวันหยุด)", s["compensatory_days"]])
    w.writerow([])
    w.writerow(["ยอดวันลาคงเหลือเดือนนี้", s.get("balance", 0)])
    w.writerow(["ยอดสะสมยกมา", s.get("carryover_balance", 0)])
    w.writerow(["ยอดสะสมรวม", s.get("cumulative_balance", 0)])
    w.writerow([])
    w.writerow(["หักลา (จำนวนวัน)", s["leave_deduction_days"]])
    w.writerow(["หักลา (บาท)", f'{s["deduction_amount"]:.2f}'])
    w.writerow([])
    w.writerow(["เงินสุทธิที่ได้รับ (บาท)", f'{s["actual_pay"]:.2f}'])

    filename = f"payslip_{s['employee_name']}_{year}-{month:02d}.csv"
    encoded = quote(filename, safe="")
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv; charset=utf-8-sig",
        headers={"Content-Disposition": f"attachment; filename=\"payslip.csv\"; filename*=UTF-8''{encoded}"},
    )


@app.post("/api/admin/backup")
def trigger_backup():
    """Manual on-demand backup trigger. Returns the path of the new gz file."""
    path = _backup_db()
    if not path:
        raise HTTPException(500, "Backup failed; check container logs")
    return {"path": path, "size_bytes": os.path.getsize(path)}


@app.get("/api/admin/backups")
def list_backups():
    """List available backup files with size + mtime."""
    if not os.path.isdir(_BACKUP_DIR):
        return {"backups": []}
    items = []
    for f in sorted(glob.glob(os.path.join(_BACKUP_DIR, "maid-*.db.gz"))):
        try:
            items.append({
                "filename": os.path.basename(f),
                "size_bytes": os.path.getsize(f),
                "mtime": datetime.fromtimestamp(os.path.getmtime(f), _TZ).isoformat(),
            })
        except OSError:
            pass
    return {"backups": items, "retention_days": _BACKUP_RETENTION_DAYS}


# ---------- Static + SPA fallback ----------

app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/{full_path:path}")
def serve_spa(full_path: str):
    return FileResponse("static/index.html")
