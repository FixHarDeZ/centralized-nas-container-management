"""Friendly Reminder — installment payment tracker with LINE notifications."""
import csv
import io
import os
import sqlite3
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.db import get_conn, init_db
from app.notify import LineCreds, Notifier

_TZ = ZoneInfo(os.environ.get("TZ", "Asia/Bangkok"))
_DATA_DIR = os.environ.get("DATA_DIR", "/data")

_LINE_TOKEN = os.environ.get("FRIENDLY_LINE_CHANNEL_ACCESS_TOKEN", "")
_LINE_GROUP = os.environ.get("FRIENDLY_LINE_GROUP_ID", "").strip()
_REMINDER_TIME = os.environ.get("REMINDER_TIME", "08:00")

_notifier = Notifier(
    line=LineCreds(token=_LINE_TOKEN, to=_LINE_GROUP) if _LINE_TOKEN and _LINE_GROUP else None,
)

_scheduler = BackgroundScheduler(timezone=_TZ.key)

THAI_MONTHS = [
    "", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]


def _fmt(amount: float) -> str:
    return f"{amount:,.2f}"


def _now_str() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _send_monthly_reminder() -> None:
    """Fire on the 1st of each month — notify about all payments due this month."""
    today = date.today()
    year, month = today.year, today.month

    from app.db import DB_PATH
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT p.id, p.installment_id, p.installment_number, p.amount, p.paid_at,
                   i.name, i.num_installments
            FROM payments p
            JOIN installments i ON i.id = p.installment_id
            WHERE p.due_year = ? AND p.due_month = ? AND p.paid_at IS NULL
            ORDER BY i.name, p.installment_number
        """, (year, month)).fetchall()
    finally:
        conn.close()

    if not rows:
        return

    month_name = THAI_MONTHS[month]
    lines = [f"💳 ยอดผ่อนชำระ — {month_name} {year + 543}\n"]
    total = 0.0
    for r in rows:
        lines.append(
            f"  • {r['name']}  งวดที่ {r['installment_number']}/{r['num_installments']}"
            f"  ฿{_fmt(r['amount'])}"
        )
        total += r["amount"]
    lines.append(f"\n💵 รวมทั้งหมด: ฿{_fmt(total)}")
    lines.append(f"🕒 {_now_str()}")

    _notifier.send("\n".join(lines))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    h, m = _REMINDER_TIME.split(":")
    _scheduler.add_job(
        _send_monthly_reminder,
        CronTrigger(day=1, hour=int(h), minute=int(m)),
        id="monthly_reminder",
    )
    _scheduler.start()
    yield
    _scheduler.shutdown(wait=False)


app = FastAPI(title="Friendly Reminder", lifespan=lifespan)


# ─── Pydantic models ──────────────────────────────────────────────────────────

class InstallmentCreate(BaseModel):
    name: str
    total_price: float
    num_installments: int
    start_date: str  # YYYY-MM (first payment month, e.g. "2024-07")
    note: Optional[str] = None


class PaymentNoteUpdate(BaseModel):
    note: Optional[str] = None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _generate_payments(conn, installment_id: int, total_price: float,
                       num_installments: int, start_date: str) -> None:
    """Insert all payment rows for a newly created installment."""
    base_amount = round(total_price / num_installments, 2)
    # Distribute rounding difference into last installment
    last_amount = round(total_price - base_amount * (num_installments - 1), 2)

    year, month = map(int, start_date.split("-"))
    for i in range(1, num_installments + 1):
        amount = base_amount if i < num_installments else last_amount
        conn.execute(
            "INSERT INTO payments (installment_id, installment_number, due_year, due_month, amount) "
            "VALUES (?, ?, ?, ?, ?)",
            (installment_id, i, year, month, amount),
        )
        month += 1
        if month > 12:
            month = 1
            year += 1


def _row_to_dict(row) -> dict:
    return dict(row)


def _installment_with_payments(conn, installment_id: int) -> dict:
    inst = conn.execute(
        "SELECT * FROM installments WHERE id = ?", (installment_id,)
    ).fetchone()
    if not inst:
        raise HTTPException(status_code=404, detail="Installment not found")

    payments = conn.execute(
        "SELECT * FROM payments WHERE installment_id = ? ORDER BY installment_number",
        (installment_id,),
    ).fetchall()

    d = _row_to_dict(inst)
    d["payments"] = [_row_to_dict(p) for p in payments]
    d["paid_count"] = sum(1 for p in d["payments"] if p["paid_at"])
    d["remaining_count"] = d["num_installments"] - d["paid_count"]
    d["total_paid"] = round(sum(p["amount"] for p in d["payments"] if p["paid_at"]), 2)
    d["total_remaining"] = round(d["total_price"] - d["total_paid"], 2)
    return d


# ─── API Routes ───────────────────────────────────────────────────────────────

@app.get("/api/installments")
def list_installments(conn=Depends(get_conn)):
    rows = conn.execute(
        "SELECT * FROM installments ORDER BY start_date, name"
    ).fetchall()
    result = []
    for row in rows:
        d = _row_to_dict(row)
        stats = conn.execute(
            "SELECT COUNT(*) AS total, "
            "SUM(CASE WHEN paid_at IS NOT NULL THEN 1 ELSE 0 END) AS paid, "
            "SUM(CASE WHEN paid_at IS NOT NULL THEN amount ELSE 0 END) AS total_paid "
            "FROM payments WHERE installment_id = ?",
            (row["id"],),
        ).fetchone()
        d["paid_count"] = stats["paid"] or 0
        d["remaining_count"] = (stats["total"] or 0) - d["paid_count"]
        d["total_paid"] = round(stats["total_paid"] or 0.0, 2)
        d["total_remaining"] = round(d["total_price"] - d["total_paid"], 2)
        d["is_complete"] = d["remaining_count"] == 0
        result.append(d)
    return result


@app.post("/api/installments", status_code=201)
def create_installment(body: InstallmentCreate, conn=Depends(get_conn)):
    if body.num_installments < 1:
        raise HTTPException(status_code=400, detail="num_installments must be >= 1")
    if body.total_price <= 0:
        raise HTTPException(status_code=400, detail="total_price must be positive")

    # validate start_date format YYYY-MM
    try:
        year, month = map(int, body.start_date.split("-"))
        if not (1 <= month <= 12):
            raise ValueError
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="start_date must be YYYY-MM format")

    cur = conn.execute(
        "INSERT INTO installments (name, total_price, num_installments, start_date, note) "
        "VALUES (?, ?, ?, ?, ?)",
        (body.name.strip(), body.total_price, body.num_installments, body.start_date, body.note),
    )
    installment_id = cur.lastrowid
    _generate_payments(conn, installment_id, body.total_price, body.num_installments, body.start_date)

    return _installment_with_payments(conn, installment_id)


@app.get("/api/installments/{installment_id}")
def get_installment(installment_id: int, conn=Depends(get_conn)):
    return _installment_with_payments(conn, installment_id)


@app.delete("/api/installments/{installment_id}", status_code=204)
def delete_installment(installment_id: int, conn=Depends(get_conn)):
    row = conn.execute(
        "SELECT id FROM installments WHERE id = ?", (installment_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Installment not found")
    conn.execute("DELETE FROM installments WHERE id = ?", (installment_id,))


@app.post("/api/payments/{payment_id}/pay")
def mark_paid(payment_id: int, body: Optional[PaymentNoteUpdate] = None, conn=Depends(get_conn)):
    row = conn.execute(
        "SELECT p.*, i.name AS inst_name, i.num_installments "
        "FROM payments p JOIN installments i ON i.id = p.installment_id "
        "WHERE p.id = ?",
        (payment_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Payment not found")
    if row["paid_at"]:
        raise HTTPException(status_code=409, detail="Already paid")

    paid_at = _now_str()
    note = body.note if body else None
    conn.execute(
        "UPDATE payments SET paid_at = ?, note = COALESCE(?, note) WHERE id = ?",
        (paid_at, note, payment_id),
    )

    month_name = THAI_MONTHS[row["due_month"]]
    msg = (
        f"✅ จ่ายแล้ว — {row['inst_name']}\n"
        f"📅 งวดที่ {row['installment_number']}/{row['num_installments']}"
        f"  ({month_name} {row['due_year'] + 543})\n"
        f"💵 ฿{_fmt(row['amount'])}\n"
        f"🕒 {paid_at}"
    )
    _notifier.send(msg)

    return {"payment_id": payment_id, "paid_at": paid_at}


@app.post("/api/payments/{payment_id}/unpay")
def mark_unpaid(payment_id: int, conn=Depends(get_conn)):
    row = conn.execute(
        "SELECT id, paid_at FROM payments WHERE id = ?", (payment_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Payment not found")
    if not row["paid_at"]:
        raise HTTPException(status_code=409, detail="Not paid yet")
    conn.execute("UPDATE payments SET paid_at = NULL WHERE id = ?", (payment_id,))
    return {"payment_id": payment_id, "paid_at": None}


@app.get("/api/summary")
def current_month_summary(conn=Depends(get_conn)):
    today = date.today()
    year, month = today.year, today.month
    rows = conn.execute("""
        SELECT p.id, p.installment_id, p.installment_number, p.amount, p.paid_at,
               p.due_year, p.due_month,
               i.name, i.num_installments, i.total_price
        FROM payments p
        JOIN installments i ON i.id = p.installment_id
        WHERE p.due_year = ? AND p.due_month = ?
        ORDER BY p.paid_at IS NULL DESC, i.name
    """, (year, month)).fetchall()

    items = [_row_to_dict(r) for r in rows]
    total = round(sum(r["amount"] for r in items), 2)
    total_paid = round(sum(r["amount"] for r in items if r["paid_at"]), 2)
    return {
        "year": year,
        "month": month,
        "month_name": THAI_MONTHS[month],
        "items": items,
        "total": total,
        "total_paid": total_paid,
        "total_remaining": round(total - total_paid, 2),
    }


@app.get("/api/report")
def download_report(conn=Depends(get_conn)):
    rows = conn.execute("""
        SELECT i.name, i.total_price, i.num_installments, i.start_date,
               p.installment_number, p.due_year, p.due_month, p.amount, p.paid_at, p.note
        FROM payments p
        JOIN installments i ON i.id = p.installment_id
        ORDER BY i.name, p.installment_number
    """).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ชื่อรายการ", "ราคารวม", "จำนวนงวด", "วันที่เริ่ม",
        "งวดที่", "ปีที่ครบกำหนด", "เดือนที่ครบกำหนด",
        "ยอดงวด", "จ่ายเมื่อ", "หมายเหตุ",
    ])
    for r in rows:
        writer.writerow([
            r["name"], r["total_price"], r["num_installments"], r["start_date"],
            r["installment_number"], r["due_year"], r["due_month"],
            r["amount"], r["paid_at"] or "", r["note"] or "",
        ])

    output.seek(0)
    filename = f"friendly-reminder-{date.today().isoformat()}.csv"
    return StreamingResponse(
        iter([output.getvalue().encode("utf-8-sig")]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─── Static frontend ──────────────────────────────────────────────────────────
import pathlib as _pathlib
_STATIC_DIR = _pathlib.Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
