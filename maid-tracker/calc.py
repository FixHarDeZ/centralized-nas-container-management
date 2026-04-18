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


def default_status(d: date) -> str:
    """Sunday = holiday, else work."""
    return "holiday" if d.weekday() == 6 else "work"


def working_days_in_month(year: int, month: int) -> int:
    """Count Mon–Sat days in a month."""
    _, n = calendar.monthrange(year, month)
    return sum(1 for day in range(1, n + 1) if date(year, month, day).weekday() != 6)


def daily_rate(monthly_salary: float, year: int, month: int) -> float:
    wd = working_days_in_month(year, month)
    return monthly_salary / wd if wd else 0.0


def compute_overall_balance(emp_id: int, start_date: date, monthly_salary: float, up_to: date | None = None) -> dict:
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
        rec = saved.get(d.isoformat(), {"status": default_status(d), "half_day": False})
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
    import calendar as _cal

    _, last = _cal.monthrange(year, month)
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
        _, n = _cal.monthrange(cur_y, cur_m)
        m_end = date(cur_y, cur_m, n)
        d = max(date(cur_y, cur_m, 1), start_date)

        while d <= m_end:
            rec = saved.get(d.isoformat(), {"status": default_status(d), "half_day": False})
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


def compute_resign_summary(emp_id: int, start_date: date, end_date: date, monthly_salary: float) -> dict:
    """
    Compute resignation settlement:
      - Prorated last-month salary (from 1st-of-month or start_date to end_date)
      - Cumulative comp/leave balance × daily rate
    """
    year, month = end_date.year, end_date.month

    b           = compute_overall_balance(emp_id, start_date, monthly_salary, up_to=end_date)
    wd_month    = working_days_in_month(year, month)
    dr          = monthly_salary / wd_month if wd_month else 0.0

    month_start = max(date(year, month, 1), start_date)
    billable    = sum(
        1 for i in range((end_date - month_start).days + 1)
        if (month_start + timedelta(days=i)).weekday() != 6
    )
    base_salary    = round(dr * billable, 2)
    balance_amount = round(b["balance"] * dr, 2)
    final_amount   = round(base_salary + balance_amount, 2)

    return {
        "total_comp":         b["total_comp"],
        "total_leave":        b["total_leave"],
        "cumulative_balance": b["balance"],
        "daily_rate":         round(dr, 2),
        "base_salary":        base_salary,
        "balance_amount":     balance_amount,
        "final_amount":       final_amount,
    }
