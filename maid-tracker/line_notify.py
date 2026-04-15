"""
Maid Tracker — LINE Notifier
Sends notifications via LINE Messaging API when:
  - Leave or compensatory attendance is recorded
  - Salary payment is marked as paid

Requires env vars:
  LINE_CHANNEL_ACCESS_TOKEN
  LINE_GROUP_ID   LINE group ID (starts with 'C') — everyone in the group receives each message

If either env var is missing, all notify calls are silently skipped.
Uses /v2/bot/message/push with the group ID so a single API call reaches all group members.
"""

import os
import sqlite3
import calendar
import requests
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

LINE_API_URL = "https://api.line.me/v2/bot/message/push"
TOKEN    = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
GROUP_ID = os.environ.get("LINE_GROUP_ID", "").strip()
TZ       = ZoneInfo(os.environ.get("TZ", "Asia/Bangkok"))

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH  = os.path.join(DATA_DIR, "maid_tracker.db")

THAI_MONTHS = [
    "", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def _fmt(amount: float) -> str:
    """Format number with thousand separators, no decimals."""
    return f"{amount:,.0f}"


def _default_status(d: date) -> str:
    return "holiday" if d.weekday() == 6 else "work"


def _working_days_in_month(year: int, month: int) -> int:
    _, n = calendar.monthrange(year, month)
    return sum(1 for day in range(1, n + 1) if date(year, month, day).weekday() != 6)


# ─── Balance computation ──────────────────────────────────────────────────────

def _compute_overall_balance(emp_id: int, start_date: date, monthly_salary: float) -> dict:
    """
    Iterate start_date → today and compute cumulative comp/leave balance.
    Uses its own DB connection (called after the triggering request is committed).
    Daily rate is based on the current month's working days.
    """
    today = date.today()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT work_date, status, half_day FROM attendance WHERE employee_id=?",
        (emp_id,),
    ).fetchall()
    conn.close()

    saved = {
        r["work_date"]: {"status": r["status"], "half_day": bool(r["half_day"])}
        for r in rows
    }

    total_comp = total_leave = 0.0
    d = start_date
    while d <= today:
        rec = saved.get(d.isoformat(), {"status": _default_status(d), "half_day": False})
        inc = 0.5 if rec["half_day"] else 1.0
        if rec["status"] == "compensatory":
            total_comp += inc
        elif rec["status"] == "leave":
            total_leave += inc
        d += timedelta(days=1)

    balance = total_comp - total_leave
    wd = _working_days_in_month(today.year, today.month)
    dr = monthly_salary / wd if wd else 0.0
    balance_amount = round(balance * dr, 2)

    return {
        "total_comp":     total_comp,
        "total_leave":    total_leave,
        "balance":        balance,
        "daily_rate":     round(dr, 2),
        "balance_amount": balance_amount,
    }


def _balance_block(b: dict) -> str:
    """Format the balance summary block for LINE messages."""
    bal       = b["balance"]
    bal_amt   = b["balance_amount"]
    sign      = "+" if bal >= 0 else ""
    amt_sign  = "+" if bal_amt >= 0 else ""
    kind      = "เครดิตสะสม" if bal >= 0 else "ยอดค้าง"

    comp_str  = f"+{_fmt(b['total_comp'])}" if b["total_comp"] else "0"
    leave_str = f"-{_fmt(b['total_leave'])}" if b["total_leave"] else "0"

    return (
        f"📊 ยอดสะสมปัจจุบัน:\n"
        f"  ชดเชย: {comp_str} วัน  |  ลา: {leave_str} วัน\n"
        f"  ⚖️  {kind}: {sign}{_fmt(bal)} วัน\n"
        f"  💵 ≈ {amt_sign}฿{_fmt(bal_amt)}"
        f"  (฿{_fmt(b['daily_rate'])}/วัน)"
    )


# ─── LINE sender ─────────────────────────────────────────────────────────────

def send_line(text: str) -> None:
    if not TOKEN or not GROUP_ID:
        return
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKEN}",
    }
    payload = {"to": GROUP_ID, "messages": [{"type": "text", "text": text}]}
    try:
        resp = requests.post(LINE_API_URL, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"[LINE] sent to group {GROUP_ID[:8]}…: {text[:80].replace(chr(10), ' ')}")
    except Exception as e:
        print(f"[LINE] ERROR: {e}")


# ─── Public notify functions ──────────────────────────────────────────────────

def notify_attendance(
    emp_id: int,
    emp_name: str,
    work_date: str,
    status: str,
    half_day: bool,
    start_date: date,
    monthly_salary: float,
) -> None:
    """Call after saving a leave or compensatory attendance record."""
    if not TOKEN or not GROUP_ID:
        return

    STATUS_LABEL = {
        "leave":        "🔴 ลา",
        "compensatory": "🟢 ชดเชย",
    }
    half_label   = " (ครึ่งวัน)" if half_day else " (เต็มวัน)"
    status_label = STATUS_LABEL.get(status, status) + half_label

    try:
        b   = _compute_overall_balance(emp_id, start_date, monthly_salary)
        msg = (
            f"📋 บันทึกการทำงาน — {emp_name}\n"
            f"📅 {work_date}:  {status_label}\n"
            f"\n"
            f"{_balance_block(b)}\n"
            f"\n"
            f"🕒 {_now_str()}"
        )
        send_line(msg)
    except Exception as e:
        print(f"[LINE] notify_attendance error: {e}")


def notify_payment(
    emp_id: int,
    emp_name: str,
    year: int,
    month: int,
    period: int,
    amount: float,
    paid_at: str,
    start_date: date,
    monthly_salary: float,
) -> None:
    """Call after marking a salary payment period as paid."""
    if not TOKEN or not GROUP_ID:
        return

    month_name   = THAI_MONTHS[month]
    period_label = f"รอบที่ {period} ({'วันที่ 15' if period == 1 else 'สิ้นเดือน'})"

    try:
        b   = _compute_overall_balance(emp_id, start_date, monthly_salary)
        msg = (
            f"💰 จ่ายเงินเดือนแล้ว — {emp_name}\n"
            f"📅 {month_name} {year}  {period_label}\n"
            f"💵 ฿{_fmt(amount)}\n"
            f"\n"
            f"{_balance_block(b)}\n"
            f"\n"
            f"🕒 {paid_at}"
        )
        send_line(msg)
    except Exception as e:
        print(f"[LINE] notify_payment error: {e}")


def notify_cancel_attendance(
    emp_id: int,
    emp_name: str,
    work_date: str,
    prev_status: str,
    prev_half_day: bool,
    start_date: date,
    monthly_salary: float,
) -> None:
    """Call after reverting a leave or compensatory day back to work/holiday."""
    if not TOKEN or not GROUP_ID:
        return

    STATUS_LABEL = {
        "leave":        "🔴 ลา",
        "compensatory": "🟢 ชดเชย",
    }
    half_label   = " (ครึ่งวัน)" if prev_half_day else " (เต็มวัน)"
    status_label = STATUS_LABEL.get(prev_status, prev_status) + half_label

    try:
        b   = _compute_overall_balance(emp_id, start_date, monthly_salary)
        msg = (
            f"↩️ ยกเลิกการบันทึก — {emp_name}\n"
            f"📅 {work_date}:  ยกเลิก{status_label}\n"
            f"\n"
            f"{_balance_block(b)}\n"
            f"\n"
            f"🕒 {_now_str()}"
        )
        send_line(msg)
    except Exception as e:
        print(f"[LINE] notify_cancel_attendance error: {e}")


def _compute_resign_summary(
    emp_id: int,
    start_date: date,
    end_date: date,
    monthly_salary: float,
) -> dict:
    """Compute resign summary: prorated last-month salary + cumulative balance settlement."""
    year, month = end_date.year, end_date.month

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT work_date, status, half_day FROM attendance WHERE employee_id=? AND work_date <= ?",
        (emp_id, end_date.isoformat()),
    ).fetchall()
    conn.close()

    saved = {
        r["work_date"]: {"status": r["status"], "half_day": bool(r["half_day"])}
        for r in rows
    }

    total_comp = total_leave = 0.0
    d = start_date
    while d <= end_date:
        rec = saved.get(d.isoformat(), {"status": _default_status(d), "half_day": False})
        inc = 0.5 if rec["half_day"] else 1.0
        if rec["status"] == "compensatory":
            total_comp += inc
        elif rec["status"] == "leave":
            total_leave += inc
        d += timedelta(days=1)

    cumulative_balance = total_comp - total_leave
    wd_month = _working_days_in_month(year, month)
    dr = monthly_salary / wd_month if wd_month else 0.0

    month_start = max(date(year, month, 1), start_date)
    billable = sum(
        1 for i in range((end_date - month_start).days + 1)
        if (month_start + timedelta(days=i)).weekday() != 6
    )
    base_salary    = round(dr * billable, 2)
    balance_amount = round(cumulative_balance * dr, 2)
    final_amount   = round(base_salary + balance_amount, 2)

    return {
        "total_comp":         total_comp,
        "total_leave":        total_leave,
        "cumulative_balance": cumulative_balance,
        "daily_rate":         round(dr, 2),
        "base_salary":        base_salary,
        "balance_amount":     balance_amount,
        "final_amount":       final_amount,
    }


def notify_resign(
    emp_id: int,
    emp_name: str,
    end_date_str: str,
    resign_note: str | None,
    start_date: date,
    monthly_salary: float,
) -> None:
    """Call after recording a resignation."""
    if not TOKEN or not GROUP_ID:
        return

    try:
        end_date = date.fromisoformat(end_date_str)
        s        = _compute_resign_summary(emp_id, start_date, end_date, monthly_salary)

        balance  = s["cumulative_balance"]
        bal_amt  = s["balance_amount"]
        sign     = "+" if balance >= 0 else ""
        amt_sign = "+" if bal_amt >= 0 else ""
        kind     = "เครดิตชดเชย" if balance >= 0 else "ยอดค้างลา"

        note_line = f"\n📝 เหตุผล: {resign_note}" if resign_note else ""

        msg = (
            f"🚪 บันทึกลาออก — {emp_name}\n"
            f"📅 วันที่ลาออก: {end_date_str}{note_line}\n"
            f"\n"
            f"💼 สรุปการลาออก:\n"
            f"  เงินเดือนเดือนสุดท้าย: ฿{_fmt(s['base_salary'])}\n"
            f"  {kind}: {sign}{_fmt(balance)} วัน  ({amt_sign}฿{_fmt(bal_amt)})\n"
            f"  ───────────────────────\n"
            f"  💵 ยอดที่ต้องจ่าย: ฿{_fmt(s['final_amount'])}\n"
            f"\n"
            f"🕒 {_now_str()}"
        )
        send_line(msg)
    except Exception as e:
        print(f"[LINE] notify_resign error: {e}")


def notify_reminder(name: str, message: str) -> None:
    """Call from the scheduler when a task reminder fires."""
    if not TOKEN or not GROUP_ID:
        return
    try:
        msg = (
            f"🔔 แจ้งเตือนงานวันนี้ — {name}\n"
            f"\n"
            f"{message}\n"
            f"\n"
            f"🕒 {_now_str()}"
        )
        send_line(msg)
    except Exception as e:
        print(f"[LINE] notify_reminder error: {e}")


def notify_cancel_resign(emp_name: str) -> None:
    """Call after cancelling a resignation."""
    if not TOKEN or not GROUP_ID:
        return

    try:
        msg = (
            f"↩️ ยกเลิกลาออก — {emp_name}\n"
            f"✅ ยกเลิกการลาออกเรียบร้อยแล้ว\n"
            f"\n"
            f"🕒 {_now_str()}"
        )
        send_line(msg)
    except Exception as e:
        print(f"[LINE] notify_cancel_resign error: {e}")
