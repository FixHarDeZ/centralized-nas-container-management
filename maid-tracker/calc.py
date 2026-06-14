"""
Shared salary and attendance calculation helpers.
Used by both main.py (API endpoints) and line_notify.py (LINE messages).
"""

import calendar
import sqlite3
import os
from datetime import date, timedelta

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH  = os.path.join(DATA_DIR, "maid_tracker.db")


def default_status(d: date, holiday_mode: str = "sunday") -> str:
    """
    Return the default attendance status for a given day.
    sunday  → Sunday = holiday, Mon-Sat = work  (classic)
    monthly → every day = work  (leave is taken from accrued balance)
    """
    if holiday_mode == "monthly":
        return "work"
    return "holiday" if d.weekday() == 6 else "work"


def working_days_in_month(year: int, month: int) -> int:
    """Count Mon–Sat days in a month."""
    _, n = calendar.monthrange(year, month)
    return sum(1 for day in range(1, n + 1) if date(year, month, day).weekday() != 6)


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


# ── Monthly-mode leave balance ────────────────────────────────

def compute_monthly_leave_balance(
    emp_id: int,
    start_date: date,
    monthly_leave_days: float,
    max_leave_carry: float | None,
    up_to: date | None = None,
) -> dict:
    """
    For 'monthly' holiday mode.

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

    saved = {r["work_date"]: {"status": r["status"], "half_day": bool(r["half_day"])} for r in rows}

    balance      = 0.0
    total_accrued = 0.0
    total_used    = 0.0

    cur_y, cur_m = start_date.year, start_date.month

    while (cur_y, cur_m) <= (end.year, end.month):
        # Credit at start of month — cap prevents over-accrual
        if max_leave_carry is not None and max_leave_carry >= 0:
            headroom = max(0.0, max_leave_carry - balance)
            accrual  = min(monthly_leave_days, headroom)
        else:
            accrual = monthly_leave_days

        balance       += accrual
        total_accrued += accrual

        # Deduct leave days taken this month
        _, n = calendar.monthrange(cur_y, cur_m)
        for day in range(1, n + 1):
            d = date(cur_y, cur_m, day)
            if d < start_date or d > end:
                continue
            rec = saved.get(d.isoformat())
            if rec and rec["status"] == "leave":
                inc        = 0.5 if rec["half_day"] else 1.0
                balance   -= inc
                total_used += inc

        cur_m += 1
        if cur_m > 12:
            cur_m = 1
            cur_y += 1

    can_accrue_more = max_leave_carry is None or balance < max_leave_carry

    return {
        "balance":         round(balance, 2),
        "total_accrued":   round(total_accrued, 2),
        "total_used":      round(total_used, 2),
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
    """
    Iterate start_date → up_to (default: today) and compute cumulative comp/leave balance.
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
        rec = saved.get(d.isoformat(), {"status": default_status(d, holiday_mode), "half_day": False})
        inc = 0.5 if rec["half_day"] else 1.0
        if rec["status"] == "compensatory":
            total_comp += inc
        elif rec["status"] == "leave":
            total_leave += inc
        d += timedelta(days=1)

    balance = total_comp - total_leave
    dr      = daily_rate(monthly_salary, end.year, end.month)
    balance_amount = round(balance * dr, 2)

    return {
        "total_comp":     total_comp,
        "total_leave":    total_leave,
        "balance":        balance,
        "daily_rate":     round(dr, 2),
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
    """
    Compute the leave deduction for period 2 of (year, month).

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
            rec = saved.get(d.isoformat(), {"status": default_status(d, holiday_mode), "half_day": False})
            inc = 0.5 if rec["half_day"] else 1.0
            if rec["status"] == "compensatory":
                effective_balance += inc
            elif rec["status"] == "leave":
                effective_balance -= inc
            d += timedelta(days=1)

        # At the end of each PRIOR month apply the cap —
        # excess was settled via salary deduction, so it doesn't carry forward.
        if (cur_y, cur_m) < (year, month):
            if effective_balance < -max_leave_carry:
                effective_balance = -max_leave_carry

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
        "deduction_days":    round(deduction_days, 2),
        "deduction_amount":  deduction_amount,
        "effective_balance": round(effective_balance, 2),
    }


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


def compute_resign_summary(
    emp_id: int,
    start_date: date,
    end_date: date,
    monthly_salary: float,
    holiday_mode: str = "sunday",
    monthly_leave_days: float = 0.0,
    max_leave_carry: float | None = None,
) -> dict:
    """
    Compute resignation settlement:
      - Prorated last-month salary (from 1st-of-month or start_date to end_date)
      - Cumulative comp/leave balance × daily rate  (sunday mode)
      - Cumulative leave balance × daily rate        (monthly mode)
    """
    year, month = end_date.year, end_date.month
    wd_month    = working_days_in_month(year, month)
    dr          = monthly_salary / wd_month if wd_month else 0.0

    month_start = max(date(year, month, 1), start_date)
    billable    = sum(
        1 for i in range((end_date - month_start).days + 1)
        if (month_start + timedelta(days=i)).weekday() != 6
    )
    base_salary = round(dr * billable, 2)

    if holiday_mode == "monthly":
        lb = compute_monthly_leave_balance(
            emp_id, start_date, monthly_leave_days, max_leave_carry, up_to=end_date
        )
        balance        = lb["balance"]
        total_comp     = 0.0
        total_leave    = lb["total_used"]
        balance_amount = round(balance * dr, 2)
    else:
        b              = compute_overall_balance(emp_id, start_date, monthly_salary, up_to=end_date)
        balance        = b["balance"]
        total_comp     = b["total_comp"]
        total_leave    = b["total_leave"]
        balance_amount = round(balance * dr, 2)

    final_amount = round(base_salary + balance_amount, 2)

    return {
        "total_comp":         total_comp,
        "total_leave":        total_leave,
        "cumulative_balance": balance,
        "daily_rate":         round(dr, 2),
        "base_salary":        base_salary,
        "balance_amount":     balance_amount,
        "final_amount":       final_amount,
    }
