"""Maid Tracker — LINE Notifier
Sends notifications via LINE Messaging API when:
  - Leave or compensatory attendance is recorded
  - Salary payment is marked as paid

Requires env vars:
  MAID_LINE_CHANNEL_ACCESS_TOKEN
  MAID_LINE_GROUP_ID   LINE group ID (starts with 'C') — everyone in the group receives each message

If either env var is missing, all notify calls are silently skipped.
Uses /v2/bot/message/push with the group ID so a single API call reaches all group members.
"""

import hashlib
import hmac as _hmac
import json
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx
import i18n
from calc import (
    compute_overall_balance,
    compute_probation_resign,
    compute_probation_tally,
    compute_probation_unpaid,
    compute_resign_summary,
)

LINE_API_URL = "https://api.line.me/v2/bot/message/push"
TOKEN = os.environ.get("MAID_LINE_CHANNEL_ACCESS_TOKEN", "")
GROUP_ID = os.environ.get("MAID_LINE_GROUP_ID", "").strip()
CHANNEL_SECRET = os.environ.get("MAID_LINE_CHANNEL_SECRET", "")
PUBLIC_BASE_URL = os.environ.get("MAID_PUBLIC_BASE_URL", "").rstrip("/")
TZ = ZoneInfo(os.environ.get("TZ", "Asia/Bangkok"))

THAI_MONTHS = [
    "",
    "มกราคม",
    "กุมภาพันธ์",
    "มีนาคม",
    "เมษายน",
    "พฤษภาคม",
    "มิถุนายน",
    "กรกฎาคม",
    "สิงหาคม",
    "กันยายน",
    "ตุลาคม",
    "พฤศจิกายน",
    "ธันวาคม",
]


# ─── Slip helpers ────────────────────────────────────────────────────────────


def _slip_token(fname: str) -> str:
    """16-char HMAC-SHA256 token used by the public slip route."""
    key = (CHANNEL_SECRET or "x").encode()
    return _hmac.new(key, fname.encode(), hashlib.sha256).hexdigest()[:16]


def _is_image_slip(fname: str) -> bool:
    ext = (fname or "").rsplit(".", 1)[-1].lower()
    return ext in ("jpg", "jpeg", "png", "webp")


def _slip_public_url(fname: str) -> str | None:
    """Return signed public URL for slip image, or None when config is missing or file is PDF."""
    if not PUBLIC_BASE_URL or not fname or not _is_image_slip(fname):
        return None
    return f"{PUBLIC_BASE_URL}/api/slips/public/{_slip_token(fname)}/{fname}"


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
    bal = b["balance"]
    bal_amt = b["balance_amount"]
    sign = "+" if bal >= 0 else ""
    amt_sign = "+" if bal_amt >= 0 else ""
    kind = "เครดิตสะสม" if bal >= 0 else "ยอดค้าง"

    comp_str = f"+{_fmt_days(b['total_comp'])}" if b["total_comp"] else "0"
    leave_str = f"-{_fmt_days(b['total_leave'])}" if b["total_leave"] else "0"

    return (
        f"📊 ยอดสะสมปัจจุบัน:\n"
        f"  ชดเชย: {comp_str} วัน  |  ลา: {leave_str} วัน\n"
        f"  ⚖️  {kind}: {sign}{_fmt_days(abs(bal))} วัน\n"
        f"  💵 ≈ {amt_sign}฿{_fmt(bal_amt)}"
        f"  (฿{_fmt(b['daily_rate'])}/วัน)"
    )


# ─── Translation append (non-Thai maids) ─────────────────────────────────────

_TR_SEP = "\n\n─────────\n"


def _balance_params(b: dict) -> dict:
    """Pre-formatted balance fields for i18n.translate_block."""
    bal = b["balance"]
    return {
        "comp": _fmt_days(b["total_comp"]) if b["total_comp"] else "0",
        "leave": f"-{_fmt_days(b['total_leave'])}" if b["total_leave"] else "0",
        "kind_pos": bal >= 0,
        "bal_days": _fmt_days(abs(bal)),
        "bal_amt": _fmt(abs(b["balance_amount"])),
        "daily_rate": _fmt(b["daily_rate"]),
    }


def _append_tr(msg: str, msg_type: str, language: str, **params) -> str:
    """Append the translated block below the Thai message for non-Thai maids."""
    block = i18n.translate_block(msg_type, language, **params)
    return msg + _TR_SEP + block if block else msg


# ─── LINE sender ─────────────────────────────────────────────────────────────


def send_line(text: str, extra_messages: list | None = None) -> None:
    if not TOKEN or not GROUP_ID:
        return
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {TOKEN}",
    }
    messages = [{"type": "text", "text": text}]
    if extra_messages:
        messages.extend(extra_messages)
    payload = {"to": GROUP_ID, "messages": messages[:5]}
    try:
        resp = httpx.post(LINE_API_URL, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        print(
            f"[LINE] sent to group {GROUP_ID[:8]}…: {text[:80].replace(chr(10), ' ')}",
        )
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
    language: str = "th",
) -> None:
    """Call after saving a leave or compensatory attendance record."""
    if not TOKEN or not GROUP_ID:
        return

    STATUS_LABEL = {
        "leave": "🔴 ลา",
        "compensatory": "🟢 ชดเชย",
    }
    half_label = " (ครึ่งวัน)" if half_day else " (เต็มวัน)"
    status_label = STATUS_LABEL.get(status, status) + half_label

    try:
        b = compute_overall_balance(emp_id, start_date, monthly_salary)
        msg = (
            f"📋 บันทึกการทำงาน — {emp_name}\n"
            f"📅 {work_date}:  {status_label}\n"
            f"\n"
            f"{_balance_block(b)}\n"
            f"\n"
            f"🕒 {_now_str()}"
        )
        msg = _append_tr(
            msg, "attendance", language,
            name=emp_name, date=work_date, status=status, half=half_day,
            **_balance_params(b),
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
    paid_by: str | None = None,
    slip_fname: str | None = None,
    language: str = "th",
) -> None:
    """Call after marking a salary payment period as paid."""
    if not TOKEN or not GROUP_ID:
        return

    month_name = THAI_MONTHS[month]
    period_label = f"รอบที่ {period} ({'วันที่ 15' if period == 1 else 'สิ้นเดือน'})"
    deduction_line = ""
    if deduction_days > 0:
        deduction_line = f"✂️ หักวันลาเกินสะสม {_fmt_days(deduction_days)} วัน: -฿{_fmt(deduction_amount)}\n"
    payer_line = f"  ผู้จ่าย: {paid_by}\n" if paid_by else ""

    image_url = _slip_public_url(slip_fname) if slip_fname else None
    extra = (
        [
            {
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": image_url,
            },
        ]
        if image_url
        else None
    )

    try:
        b = compute_overall_balance(emp_id, start_date, monthly_salary)
        msg = (
            f"💰 จ่ายเงินเดือนแล้ว — {emp_name}\n"
            f"📅 {month_name} {year}  {period_label}\n"
            f"{deduction_line}"
            f"💵 ฿{_fmt(amount)}\n"
            f"{payer_line}"
            f"\n"
            f"{_balance_block(b)}\n"
            f"\n"
            f"🕒 {paid_at}"
        )
        msg = _append_tr(
            msg, "payment", language,
            name=emp_name, month=month, year=year, period=period,
            amount=_fmt(amount), paid_by=paid_by, **_balance_params(b),
        )
        send_line(msg, extra)
    except Exception as e:
        print(f"[LINE] notify_payment error: {e}")


def notify_daily_payment(
    emp_name: str,
    work_date: str,
    amount: float,
    paid_at: str,
    paid_by: str | None = None,
    slip_fname: str | None = None,
    language: str = "th",
) -> None:
    """Call after marking a probation daily payment as paid."""
    if not TOKEN or not GROUP_ID:
        return

    payer_line = f"\n  ผู้จ่าย: {paid_by}" if paid_by else ""
    image_url = _slip_public_url(slip_fname) if slip_fname else None
    extra = (
        [
            {
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": image_url,
            },
        ]
        if image_url
        else None
    )

    try:
        msg = (
            f"💰 จ่ายรายวันแล้ว — {emp_name}\n"
            f"📅 วันที่ {work_date}\n"
            f"💵 ฿{_fmt(amount)}{payer_line}\n"
            f"\n"
            f"🕒 {paid_at}"
        )
        msg = _append_tr(
            msg, "daily_payment", language,
            name=emp_name, date=work_date, amount=_fmt(amount), paid_by=paid_by,
        )
        send_line(msg, extra)
    except Exception as e:
        print(f"[LINE] notify_daily_payment error: {e}")


def notify_slip_image(
    emp_name: str, slip_fname: str, label: str, language: str = "th"
) -> None:
    """Send slip image to LINE after upload when payment is already paid."""
    image_url = _slip_public_url(slip_fname)
    if not image_url:
        return  # PDF or missing MAID_PUBLIC_BASE_URL — skip silently
    if not TOKEN or not GROUP_ID:
        return
    try:
        msg = f"📎 สลิปโอนเงิน — {emp_name}\n{label}\n🕒 {_now_str()}"
        msg = _append_tr(msg, "slip_image", language, name=emp_name)
        extra = [
            {
                "type": "image",
                "originalContentUrl": image_url,
                "previewImageUrl": image_url,
            },
        ]
        send_line(msg, extra)
    except Exception as e:
        print(f"[LINE] notify_slip_image error: {e}")


def notify_cancel_attendance(
    emp_id: int,
    emp_name: str,
    work_date: str,
    prev_status: str,
    prev_half_day: bool,
    start_date: date,
    monthly_salary: float,
    language: str = "th",
) -> None:
    """Call after reverting a leave or compensatory day back to work/holiday."""
    if not TOKEN or not GROUP_ID:
        return

    STATUS_LABEL = {
        "leave": "🔴 ลา",
        "compensatory": "🟢 ชดเชย",
    }
    half_label = " (ครึ่งวัน)" if prev_half_day else " (เต็มวัน)"
    status_label = STATUS_LABEL.get(prev_status, prev_status) + half_label

    try:
        b = compute_overall_balance(emp_id, start_date, monthly_salary)
        msg = (
            f"↩️ ยกเลิกการบันทึก — {emp_name}\n"
            f"📅 {work_date}:  ยกเลิก{status_label}\n"
            f"\n"
            f"{_balance_block(b)}\n"
            f"\n"
            f"🕒 {_now_str()}"
        )
        msg = _append_tr(
            msg, "cancel_attendance", language,
            name=emp_name, date=work_date, status=prev_status, half=prev_half_day,
            **_balance_params(b),
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
    employment_status: str | None = None,
    probation_daily_rate: float = 0.0,
    language: str = "th",
) -> None:
    """Call after recording a resignation."""
    if not TOKEN or not GROUP_ID:
        return

    try:
        end_date = date.fromisoformat(end_date_str)
        note_line = f"\n📝 เหตุผล: {resign_note}" if resign_note else ""

        if employment_status == "probation":
            s = compute_probation_resign(
                emp_id,
                start_date,
                end_date,
                probation_daily_rate,
            )
            msg = (
                f"🚪 บันทึกลาออก — {emp_name}\n"
                f"📅 วันที่ลาออก: {end_date_str}{note_line}\n"
                f"\n"
                f"💼 สรุปการลาออก (ทดลองงาน):\n"
                f"  วันที่ยังไม่จ่าย: {_fmt(s['total_days'])} วัน × ฿{_fmt(s['daily_rate'])}\n"
                f"  ───────────────────────\n"
                f"  💵 ยอดที่ต้องจ่าย: ฿{_fmt(s['final_amount'])}\n"
                f"\n"
                f"🕒 {_now_str()}"
            )
            msg = _append_tr(
                msg, "resign", language,
                name=emp_name, end_date=end_date_str, final=_fmt(s["final_amount"]),
            )
            send_line(msg)
            return

        s = compute_resign_summary(emp_id, start_date, end_date, monthly_salary)

        balance = s["cumulative_balance"]
        bal_amt = s["balance_amount"]
        sign = "+" if balance >= 0 else ""
        amt_sign = "+" if bal_amt >= 0 else ""
        kind = "เครดิตชดเชย" if balance >= 0 else "ยอดค้างลา"

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
        msg = _append_tr(
            msg, "resign", language,
            name=emp_name, end_date=end_date_str, final=_fmt(s["final_amount"]),
        )
        send_line(msg)
    except Exception as e:
        print(f"[LINE] notify_resign error: {e}")


def _reminder_body(name, message, message_i18n, active_langs):
    """Thai reminder + one cached translated block per active non-Thai language."""
    body = f"🔔 แจ้งเตือนงานวันนี้ — {name}\n\n{message}"
    if message_i18n and active_langs:
        try:
            cache = json.loads(message_i18n)
        except Exception:
            cache = {}
        for lang in active_langs:
            tr = cache.get(lang)
            if tr:
                body += f"{_TR_SEP}{tr}"
    return body + f"\n\n🕒 {_now_str()}"


def notify_reminder(name, message, message_i18n=None, active_langs=None):
    """Call from the scheduler when a task reminder fires."""
    if not TOKEN or not GROUP_ID:
        return
    try:
        send_line(_reminder_body(name, message, message_i18n, active_langs or []))
    except Exception as e:
        print(f"[LINE] notify_reminder error: {e}")


def notify_balance_query(
    emp_id: int,
    emp_name: str,
    start_date: date,
    monthly_salary: float,
    employment_status: str = "monthly",
    probation_daily_rate: float = 0.0,
    language: str = "th",
) -> None:
    """Call when a group member asks for the current balance via LINE chat."""
    if not TOKEN or not GROUP_ID:
        return
    try:
        if employment_status == "probation":
            t = compute_probation_tally(emp_id, start_date, probation_daily_rate)
            u = compute_probation_unpaid(emp_id, start_date, probation_daily_rate)
            accumulated = round(u["total_paid"] + u["total_unpaid"], 2)
            msg = (
                f"📊 ยอดสะสม — {emp_name}\n\n"
                f"📅 วันที่ทำงาน: {t['total_days']} วัน\n"
                f"💵 ยอดจ่ายสะสม: ฿{_fmt(accumulated)}\n"
                f"(฿{_fmt(probation_daily_rate)}/วัน)\n\n"
                f"🕒 {_now_str()}"
            )
            msg = _append_tr(
                msg, "balance_query", language,
                name=emp_name, days=t["total_days"],
                amount=_fmt(accumulated), daily_rate=_fmt(probation_daily_rate),
            )
        else:
            b = compute_overall_balance(emp_id, start_date, monthly_salary)
            msg = f"📊 ยอดสะสม — {emp_name}\n\n{_balance_block(b)}\n\n🕒 {_now_str()}"
            msg = _append_tr(
                msg, "balance", language,
                name=emp_name,
                comp=f"+{_fmt_days(b['total_comp'])}" if b["total_comp"] else "0",
                leave=f"-{_fmt_days(b['total_leave'])}" if b["total_leave"] else "0",
                kind_pos=b["balance"] >= 0,
                bal_days=_fmt_days(abs(b["balance"])),
                bal_amt=_fmt(abs(b["balance_amount"])),
                daily_rate=_fmt(b["daily_rate"]),
            )
        send_line(msg)
    except Exception as e:
        print(f"[LINE] notify_balance_query error: {e}")


def _monthly_entry(emp: dict) -> str:
    """Per-employee block for the monthly report (Thai + maid-language translation).

    Probation: leave does not exist — show only whether there is an outstanding
    daily-pay balance, matching the dashboard ค้างจ่าย. Active: cumulative
    comp/leave balance as before.
    """
    name = emp["name"]
    lang = emp.get("notify_language") or "th"
    start = date.fromisoformat(emp["start_date"])

    if emp.get("employment_status") == "probation":
        rate = emp.get("probation_daily_rate") or 0.0
        unpaid = compute_probation_unpaid(emp["id"], start, rate)["total_unpaid"]
        if unpaid > 0:
            thai = f"👤 {name} (ทดลองงาน)\n  💵 ค้างจ่าย: ฿{_fmt(unpaid)}"
            block = i18n.translate_block(
                "monthly_probation_owed", lang, name=name, amount=_fmt(unpaid)
            )
        else:
            thai = f"👤 {name} (ทดลองงาน)\n  ✅ ไม่มียอดค้างจ่าย"
            block = i18n.translate_block("monthly_probation_clear", lang, name=name)
        return thai + (_TR_SEP + block if block else "")

    # Active: anchor leave accrual at pass-probation date when present.
    anchor = (
        date.fromisoformat(emp["monthly_start_date"])
        if emp.get("monthly_start_date")
        else start
    )
    b = compute_overall_balance(emp["id"], anchor, emp["monthly_salary"])
    bal = b["balance"]
    sign = "+" if bal >= 0 else ""
    kind = "เครดิต" if bal >= 0 else "ค้างลา"
    thai = (
        f"👤 {name}\n"
        f"  ชดเชย +{_fmt_days(b['total_comp'])} วัน  |  ลา -{_fmt_days(b['total_leave'])} วัน\n"
        f"  ⚖️ {kind}: {sign}{_fmt_days(abs(bal))} วัน  ≈ {sign}฿{_fmt(abs(b['balance_amount']))}"
    )
    block = i18n.translate_block(
        "monthly", lang, name=name,
        comp=f"+{_fmt_days(b['total_comp'])}" if b["total_comp"] else "0",
        leave=f"-{_fmt_days(b['total_leave'])}" if b["total_leave"] else "0",
        kind_pos=bal >= 0, bal_days=_fmt_days(abs(bal)),
        bal_amt=_fmt(abs(b["balance_amount"])),
    )
    return thai + (_TR_SEP + block if block else "")


def notify_monthly_report(employees: list[dict]) -> None:
    """Send end-of-month summary for all active employees.
    Called by the scheduler on the last day of each month at 20:00.
    `employees` is a list of dicts with keys: id, name, start_date, monthly_salary,
    employment_status, probation_daily_rate, monthly_start_date, notify_language.
    """
    if not TOKEN or not GROUP_ID:
        return
    if not employees:
        return

    today = date.today()
    month_name = THAI_MONTHS[today.month]
    year_be = today.year + 543

    lines = [f"📅 สรุปประจำเดือน {month_name} {year_be}\n"]

    for emp in employees:
        try:
            lines.append(_monthly_entry(emp))
        except Exception as e:
            print(f"[LINE] monthly report error for emp {emp.get('id')}: {e}")

    msg = "\n\n".join(lines) + f"\n\n🕒 {_now_str()}"
    try:
        send_line(msg)
    except Exception as e:
        print(f"[LINE] notify_monthly_report error: {e}")


def notify_cancel_resign(emp_name: str, language: str = "th") -> None:
    """Call after cancelling a resignation."""
    if not TOKEN or not GROUP_ID:
        return

    try:
        msg = (
            f"↩️ ยกเลิกลาออก — {emp_name}\n✅ ยกเลิกการลาออกเรียบร้อยแล้ว\n\n🕒 {_now_str()}"
        )
        msg = _append_tr(msg, "cancel_resign", language, name=emp_name)
        send_line(msg)
    except Exception as e:
        print(f"[LINE] notify_cancel_resign error: {e}")
