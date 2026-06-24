"""Shared salary and attendance calculation helpers.
Used by both main.py (API endpoints) and line_notify.py (LINE messages).
"""

import calendar
import os
import sqlite3
from datetime import date, timedelta

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "maid_tracker.db")


def default_status(d: date, holiday_mode: str = "sunday") -> str:
    """Return the default attendance status for a given day.
    sunday  → Sunday = holiday, Mon-Sat = work  (classic)
    monthly → every day = work  (leave is taken from accrued balance)
    """
    if holiday_mode == "monthly":
        return "work"
    return "holiday" if d.weekday() == 6 else "work"


def working_days_in_month(year: int, month: int) -> int:
    """Salary divisor = ALL calendar days in the month (holidays are paid too).

    Note: name kept for API/JSON-key stability; it now counts every day, not
    just Mon–Sat. Daily rate = monthly_salary / this, and every proration
    counts all days so a full month still pays exactly the monthly salary.
    """
    _, n = calendar.monthrange(year, month)
    return n


def daily_rate(monthly_salary: float, year: int, month: int) -> float:
    wd = working_days_in_month(year, month)
    return monthly_salary / wd if wd else 0.0


# ── Probation / monthly day boundary ──────────────────────────


def is_probation_day(d: date, monthly_start_date: date | None) -> bool:
    """A day is a probation (daily-pay) day iff not yet passed, or strictly before pass date."""
    return monthly_start_date is None or d < monthly_start_date


def probation_up_to(monthly_start_date: date | None, today: date) -> date:
    """Upper bound (inclusive) for probation tally: day before pass date, else today."""
    if monthly_start_date is None:
        return today
    return min(today, monthly_start_date - timedelta(days=1))


def probation_worked_fraction(rec: dict | None) -> float:
    """Worked fraction for one probation day. Default model: every day is present (1.0).
    An attendance row with status='leave' marks an absence:
      full leave  → 0.0 worked, half leave → 0.5 worked.
    (During probation 'leave' is repurposed to mean "ขาด/ไม่มาทำงาน".)
    """
    if rec and rec.get("status") == "leave":
        return 0.5 if rec.get("half_day") else 0.0
    return 1.0


def compute_probation_tally(
    emp_id: int,
    start_date: date,
    probation_daily_rate: float,
    up_to: date | None = None,
) -> dict:
    """Probation = daily pay, every calendar day present by DEFAULT.
    Worked days = each day in [start_date, up_to] counts 1.0, minus days marked
    absent (attendance status='leave': full→0.0, half→0.5).
    Caller must pass `up_to` already clamped to today (do not pay future days).
    """
    end = up_to or date.today()
    if end < start_date:
        return {"total_days": 0.0, "amount": 0.0}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT work_date, status, half_day FROM attendance "
        "WHERE employee_id=? AND work_date >= ? AND work_date <= ?",
        (emp_id, start_date.isoformat(), end.isoformat()),
    ).fetchall()
    conn.close()
    saved = {
        r["work_date"]: {"status": r["status"], "half_day": bool(r["half_day"])}
        for r in rows
    }
    total = 0.0
    d = start_date
    while d <= end:
        total += probation_worked_fraction(saved.get(d.isoformat()))
        d += timedelta(days=1)
    return {
        "total_days": round(total, 2),
        "amount": round(total * probation_daily_rate, 2),
    }


# ── Monthly-mode leave balance ────────────────────────────────


def compute_monthly_leave_balance(
    emp_id: int,
    start_date: date,
    monthly_leave_days: float,
    max_leave_carry: float | None,
    up_to: date | None = None,
) -> dict:
    """For 'monthly' holiday mode.

    Credits monthly_leave_days at the start of each calendar month.
    The accumulated balance is capped at max_leave_carry (if set).
    Each 'leave' attendance day (full or half) deducts from the balance.

    Returns:
        balance          – current leave balance (negative = debt)
        total_accrued    – sum of all credits given
        total_used       – total leave days taken
        can_accrue_more  – False when balance is already at the cap
        max_leave_carry  – the configured cap (or None)

    """
    end = up_to or date.today()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT work_date, status, half_day FROM attendance "
        "WHERE employee_id=? AND work_date <= ?",
        (emp_id, end.isoformat()),
    ).fetchall()
    conn.close()

    saved = {
        r["work_date"]: {"status": r["status"], "half_day": bool(r["half_day"])}
        for r in rows
    }

    balance = 0.0
    total_accrued = 0.0
    total_used = 0.0

    cur_y, cur_m = start_date.year, start_date.month

    while (cur_y, cur_m) <= (end.year, end.month):
        # Credit at start of month — cap prevents over-accrual
        if max_leave_carry is not None and max_leave_carry >= 0:
            headroom = max(0.0, max_leave_carry - balance)
            accrual = min(monthly_leave_days, headroom)
        else:
            accrual = monthly_leave_days

        balance += accrual
        total_accrued += accrual

        # Deduct leave days taken this month
        _, n = calendar.monthrange(cur_y, cur_m)
        for day in range(1, n + 1):
            d = date(cur_y, cur_m, day)
            if d < start_date or d > end:
                continue
            rec = saved.get(d.isoformat())
            if rec and rec["status"] == "leave":
                inc = 0.5 if rec["half_day"] else 1.0
                balance -= inc
                total_used += inc

        cur_m += 1
        if cur_m > 12:
            cur_m = 1
            cur_y += 1

    can_accrue_more = max_leave_carry is None or balance < max_leave_carry

    return {
        "balance": round(balance, 2),
        "total_accrued": round(total_accrued, 2),
        "total_used": round(total_used, 2),
        "can_accrue_more": can_accrue_more,
        "max_leave_carry": max_leave_carry,
    }


# ── Sunday-mode helpers ───────────────────────────────────────


def compute_overall_balance(
    emp_id: int,
    start_date: date,
    monthly_salary: float,
    up_to: date | None = None,
    holiday_mode: str = "sunday",
) -> dict:
    """Iterate start_date → up_to (default: today) and compute cumulative comp/leave balance.
    Daily rate is based on up_to's month working days.

    Returns:
        total_comp, total_leave, balance, daily_rate, balance_amount

    """
    end = up_to or date.today()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT work_date, status, half_day FROM attendance WHERE employee_id=? AND work_date <= ?",
        (emp_id, end.isoformat()),
    ).fetchall()
    conn.close()

    saved = {
        r["work_date"]: {"status": r["status"], "half_day": bool(r["half_day"])}
        for r in rows
    }

    total_comp = total_leave = 0.0
    d = start_date
    while d <= end:
        rec = saved.get(
            d.isoformat(),
            {"status": default_status(d, holiday_mode), "half_day": False},
        )
        inc = 0.5 if rec["half_day"] else 1.0
        if rec["status"] == "compensatory":
            total_comp += inc
        elif rec["status"] == "leave":
            total_leave += inc
        d += timedelta(days=1)

    balance = total_comp - total_leave
    dr = daily_rate(monthly_salary, end.year, end.month)
    balance_amount = round(balance * dr, 2)

    return {
        "total_comp": total_comp,
        "total_leave": total_leave,
        "balance": balance,
        "daily_rate": round(dr, 2),
        "balance_amount": balance_amount,
    }


def compute_leave_deduction(
    emp_id: int,
    year: int,
    month: int,
    max_leave_carry: float,
    monthly_salary: float,
    start_date: date,
    holiday_mode: str = "sunday",
) -> dict:
    """Compute the leave deduction for period 2 of (year, month).

    Walks month-by-month from start_date through (year, month), tracking the
    effective comp/leave balance.  At the end of every PRIOR month the balance
    is capped at -max_leave_carry (the excess days were settled via a salary
    deduction that month).  The deduction returned is what should be applied to
    the current (year, month) period-2 payment.

    Returns:
        deduction_days:   days to deduct from this month's period 2 (0 if none)
        deduction_amount: deduction_days × daily_rate for this month
        effective_balance: balance after this month's cap is applied

    """
    _, last = calendar.monthrange(year, month)
    end_of_target = date(year, month, last)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT work_date, status, half_day FROM attendance "
        "WHERE employee_id=? AND work_date <= ?",
        (emp_id, end_of_target.isoformat()),
    ).fetchall()
    conn.close()

    saved = {
        r["work_date"]: {"status": r["status"], "half_day": bool(r["half_day"])}
        for r in rows
    }

    effective_balance = 0.0
    cur_y, cur_m = start_date.year, start_date.month

    while (cur_y, cur_m) <= (year, month):
        _, n = calendar.monthrange(cur_y, cur_m)
        m_end = date(cur_y, cur_m, n)
        d = max(date(cur_y, cur_m, 1), start_date)

        while d <= m_end:
            rec = saved.get(
                d.isoformat(),
                {"status": default_status(d, holiday_mode), "half_day": False},
            )
            inc = 0.5 if rec["half_day"] else 1.0
            if rec["status"] == "compensatory":
                effective_balance += inc
            elif rec["status"] == "leave":
                effective_balance -= inc
            d += timedelta(days=1)

        # At the end of each PRIOR month apply the cap —
        # excess was settled via salary deduction, so it doesn't carry forward.
        if (cur_y, cur_m) < (year, month):
            effective_balance = max(effective_balance, -max_leave_carry)

        # Advance to next month
        cur_m += 1
        if cur_m > 12:
            cur_m = 1
            cur_y += 1

    # Deduction for the target month
    deduction_days = 0.0
    if effective_balance < -max_leave_carry:
        deduction_days = abs(effective_balance) - max_leave_carry
        effective_balance = -max_leave_carry  # balance after settlement

    dr = daily_rate(monthly_salary, year, month)
    deduction_amount = round(deduction_days * dr, 2)

    return {
        "deduction_days": round(deduction_days, 2),
        "deduction_amount": deduction_amount,
        "effective_balance": round(effective_balance, 2),
    }


def compute_probation_resign(
    emp_id,
    start_date,
    end_date,
    probation_daily_rate,
) -> dict:
    """Resign while still in probation: settle only UNPAID worked days × daily rate.
    Default model: every day present unless marked absent ('leave'); days already
    paid (daily_payments.paid_at) are excluded. No monthly base.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    att = {
        r["work_date"]: {"status": r["status"], "half_day": bool(r["half_day"])}
        for r in conn.execute(
            "SELECT work_date, status, half_day FROM attendance "
            "WHERE employee_id=? AND work_date >= ? AND work_date <= ?",
            (emp_id, start_date.isoformat(), end_date.isoformat()),
        ).fetchall()
    }
    paid = {
        r["work_date"]
        for r in conn.execute(
            "SELECT work_date FROM daily_payments WHERE employee_id=? AND paid_at IS NOT NULL",
            (emp_id,),
        ).fetchall()
    }
    conn.close()
    total = 0.0
    d = start_date
    while d <= end_date:
        ds = d.isoformat()
        if ds not in paid:
            total += probation_worked_fraction(att.get(ds))
        d += timedelta(days=1)
    return {
        "total_days": round(total, 2),
        "daily_rate": round(probation_daily_rate, 2),
        "base_salary": 0.0,
        "balance_amount": 0.0,
        "final_amount": round(total * probation_daily_rate, 2),
        "probation": True,
    }


def compute_resign_summary(
    emp_id: int,
    start_date: date,
    end_date: date,
    monthly_salary: float,
    holiday_mode: str = "sunday",
    monthly_leave_days: float = 0.0,
    max_leave_carry: float | None = None,
) -> dict:
    """Compute resignation settlement:
    - Prorated last-month salary (from 1st-of-month or start_date to end_date)
    - Cumulative comp/leave balance × daily rate  (sunday mode)
    - Cumulative leave balance × daily rate        (monthly mode)
    """
    year, month = end_date.year, end_date.month
    wd_month = working_days_in_month(year, month)
    dr = monthly_salary / wd_month if wd_month else 0.0

    month_start = max(date(year, month, 1), start_date)
    # All days in range are paid (holidays included) → count every day.
    billable = (end_date - month_start).days + 1
    base_salary = round(dr * billable, 2)

    if holiday_mode == "monthly":
        lb = compute_monthly_leave_balance(
            emp_id,
            start_date,
            monthly_leave_days,
            max_leave_carry,
            up_to=end_date,
        )
        balance = lb["balance"]
        total_comp = 0.0
        total_leave = lb["total_used"]
        balance_amount = round(balance * dr, 2)
    else:
        b = compute_overall_balance(emp_id, start_date, monthly_salary, up_to=end_date)
        balance = b["balance"]
        total_comp = b["total_comp"]
        total_leave = b["total_leave"]
        balance_amount = round(balance * dr, 2)

    final_amount = round(base_salary + balance_amount, 2)

    return {
        "total_comp": total_comp,
        "total_leave": total_leave,
        "cumulative_balance": balance,
        "daily_rate": round(dr, 2),
        "base_salary": base_salary,
        "balance_amount": balance_amount,
        "final_amount": final_amount,
    }
