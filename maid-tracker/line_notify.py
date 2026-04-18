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
import requests
from datetime import date, datetime
from zoneinfo import ZoneInfo
from calc import compute_overall_balance as _compute_overall_balance, compute_resign_summary as _compute_resign_summary

LINE_API_URL = "https://api.line.me/v2/bot/message/push"
TOKEN    = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")
GROUP_ID = os.environ.get("LINE_GROUP_ID", "").strip()
TZ       = ZoneInfo(os.environ.get("TZ", "Asia/Bangkok"))

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


def _fmt_days(days: float) -> str:
    """Format day count — preserves .5 for half-day entries, drops .0 for whole days."""
    return f"{days:,.1f}" if days % 1 else f"{days:,.0f}"


def _balance_block(b: dict) -> str:
    """Format the balance summary block for LINE messages."""
    bal       = b["balance"]
    bal_amt   = b["balance_amount"]
    sign      = "+" if bal >= 0 else ""
    amt_sign  = "+" if bal_amt >= 0 else ""
    kind      = "เครดิตสะสม" if bal >= 0 else "ยอดค้าง"

    comp_str  = f"+{_fmt_days(b['total_comp'])}" if b["total_comp"] else "0"
    leave_str = f"-{_fmt_days(b['total_leave'])}" if b["total_leave"] else "0"

    return (
        f"📊 ยอดสะสมปัจจุบัน:\n"
        f"  ชดเชย: {comp_str} วัน  |  ลา: {leave_str} วัน\n"
        f"  ⚖️  {kind}: {sign}{_fmt_days(abs(bal))} วัน\n"
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
    deduction_days: float = 0.0,
    deduction_amount: float = 0.0,
) -> None:
    """Call after marking a salary payment period as paid."""
    if not TOKEN or not GROUP_ID:
        return

    month_name   = THAI_MONTHS[month]
    period_label = f"รอบที่ {period} ({'วันที่ 15' if period == 1 else 'สิ้นเดือน'})"

    deduction_line = ""
    if deduction_days > 0:
        deduction_line = (
            f"✂️ หักวันลาเกินสะสม {_fmt_days(deduction_days)} วัน: -฿{_fmt(deduction_amount)}\n"
        )

    try:
        b   = _compute_overall_balance(emp_id, start_date, monthly_salary)
        msg = (
            f"💰 จ่ายเงินเดือนแล้ว — {emp_name}\n"
            f"📅 {month_name} {year}  {period_label}\n"
            f"{deduction_line}"
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


def notify_balance_query(
    emp_id: int,
    emp_name: str,
    start_date: date,
    monthly_salary: float,
) -> None:
    """Call when a group member asks for the current balance via LINE chat."""
    if not TOKEN or not GROUP_ID:
        return
    try:
        b   = _compute_overall_balance(emp_id, start_date, monthly_salary)
        msg = (
            f"📊 ยอดสะสม — {emp_name}\n"
            f"\n"
            f"{_balance_block(b)}\n"
            f"\n"
            f"🕒 {_now_str()}"
        )
        send_line(msg)
    except Exception as e:
        print(f"[LINE] notify_balance_query error: {e}")


def notify_monthly_report(employees: list[dict]) -> None:
    """
    Send end-of-month summary for all active employees.
    Called by the scheduler on the last day of each month at 20:00.
    `employees` is a list of dicts with keys: id, name, start_date, monthly_salary.
    """
    if not TOKEN or not GROUP_ID:
        return
    if not employees:
        return

    today  = date.today()
    month_name = THAI_MONTHS[today.month]
    year_be    = today.year + 543

    lines = [f"📅 สรุปประจำเดือน {month_name} {year_be}\n"]

    for emp in employees:
        try:
            start = date.fromisoformat(emp["start_date"])
            b     = _compute_overall_balance(emp["id"], start, emp["monthly_salary"])
            bal   = b["balance"]
            sign  = "+" if bal >= 0 else ""
            kind  = "เครดิต" if bal >= 0 else "ค้างลา"
            lines.append(
                f"👤 {emp['name']}\n"
                f"  ชดเชย +{_fmt_days(b['total_comp'])} วัน  |  ลา -{_fmt_days(b['total_leave'])} วัน\n"
                f"  ⚖️ {kind}: {sign}{_fmt_days(abs(bal))} วัน  ≈ {sign}฿{_fmt(abs(b['balance_amount']))}"
            )
        except Exception as e:
            print(f"[LINE] monthly report error for emp {emp.get('id')}: {e}")

    msg = "\n\n".join(lines) + f"\n\n🕒 {_now_str()}"
    try:
        send_line(msg)
    except Exception as e:
        print(f"[LINE] notify_monthly_report error: {e}")


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
