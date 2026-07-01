"""Friendly Reminder — installment payment tracker with LINE notifications."""
import base64
import calendar
import csv
import hashlib
import hmac
import io
import json
import logging
import mimetypes
import os
import shutil
import sqlite3
import time
import urllib.request
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.db import DB_PATH, SLIPS_DIR, get_conn, init_db
from app.notify import LineCreds, Notifier
from app.slip_match import PendingStore, decide

_TZ = ZoneInfo(os.environ.get("TZ", "Asia/Bangkok"))

_LINE_TOKEN = os.environ.get("FRIENDLY_LINE_CHANNEL_ACCESS_TOKEN", "")
_LINE_GROUP = os.environ.get("FRIENDLY_LINE_GROUP_ID", "").strip()
_REMINDER_TIME = os.environ.get("REMINDER_TIME", "08:00")
_DAY_BEFORE_TIME = os.environ.get("DAY_BEFORE_REMINDER_TIME", "20:00")
_LINE_SECRET = os.environ.get("FRIENDLY_LINE_CHANNEL_SECRET", "")

_notifier = Notifier(
    line=LineCreds(token=_LINE_TOKEN, to=_LINE_GROUP) if _LINE_TOKEN and _LINE_GROUP else None,
)

_scheduler = BackgroundScheduler(timezone=_TZ.key)

# In-memory pending-slip slot for the LINE webhook (see app/slip_match.py).
_pending = PendingStore()
_LINE_CONTENT_URL = "https://api-data.line.me/v2/bot/message/{mid}/content"
_CT_EXT = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
_logger = logging.getLogger(__name__)

THAI_MONTHS = [
    "", "มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน",
    "กรกฎาคม", "สิงหาคม", "กันยายน", "ตุลาคม", "พฤศจิกายน", "ธันวาคม",
]

_ALLOWED_SLIP_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


def _fmt(amount: float) -> str:
    return f"{amount:,.2f}"


def _effective_due(year: int, month: int, due_day: int) -> date:
    """Due date for a payment, clamping due_day to the month's last day
    (e.g. due_day=31 → 28/29 in Feb)."""
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(due_day, last))


def _now_str() -> str:
    return datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _open_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ─── LINE webhook helpers ──────────────────────────────────────────────────────

def _verify_line_signature(body: bytes, signature: str) -> bool:
    if not _LINE_SECRET:
        return False
    computed = base64.b64encode(
        hmac.new(_LINE_SECRET.encode(), body, hashlib.sha256).digest()
    ).decode()
    return hmac.compare_digest(computed, signature)


def _fetch_line_content(message_id: str) -> tuple[bytes, str]:
    """Download a LINE message's binary content. The content URL is short-lived,
    so this must run when the image event arrives."""
    req = urllib.request.Request(
        _LINE_CONTENT_URL.format(mid=message_id),
        headers={"Authorization": f"Bearer {_LINE_TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        ct = resp.headers.get("Content-Type", "").split(";")[0].strip()
        return resp.read(), _CT_EXT.get(ct, ".jpg")


def _outstanding_payments(conn) -> list[dict]:
    """Payments that are due (this month or earlier) and still unpaid."""
    today = date.today()
    rows = conn.execute(
        "SELECT p.id, p.installment_number, p.amount, i.name, i.num_installments "
        "FROM payments p JOIN installments i ON i.id = p.installment_id "
        "WHERE p.paid_at IS NULL AND (p.due_year < ? OR (p.due_year = ? AND p.due_month <= ?)) "
        "ORDER BY p.due_year, p.due_month",
        (today.year, today.year, today.month),
    ).fetchall()
    return [dict(r) for r in rows]


def _apply_attach_pay(conn, payment_id: int, slip_filename: str) -> None:
    """Idempotent: keep the original paid_at if already paid; always attach slip."""
    conn.execute(
        "UPDATE payments SET paid_at = COALESCE(paid_at, ?), slip_filename = ? WHERE id = ?",
        (_now_str(), slip_filename, payment_id),
    )
    conn.commit()


def _unpaid_with_due(conn) -> list[dict]:
    """All unpaid payments with their effective due date resolved."""
    rows = conn.execute("""
        SELECT p.installment_number, p.amount, p.due_year, p.due_month,
               i.name, i.num_installments, i.due_day
        FROM payments p
        JOIN installments i ON i.id = p.installment_id
        WHERE p.paid_at IS NULL
    """).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["due"] = _effective_due(r["due_year"], r["due_month"], r["due_day"])
        out.append(d)
    out.sort(key=lambda d: (d["due"], d["name"], d["installment_number"]))
    return out


def _send_due_reminder() -> None:
    """Run daily — notify about every unpaid payment that is due today or overdue.
    Repeats each day until the payment is marked paid."""
    today = date.today()
    conn = _open_db()
    try:
        due = [d for d in _unpaid_with_due(conn) if d["due"] <= today]
    finally:
        conn.close()

    if not due:
        return

    lines = ["💳 ครบกำหนดชำระ / เกินกำหนด\n"]
    total = 0.0
    for d in due:
        overdue = (today - d["due"]).days
        tag = "⚡ ครบกำหนดวันนี้" if overdue == 0 else f"🔴 เกินกำหนด {overdue} วัน"
        lines.append(
            f"  • {d['name']}  งวดที่ {d['installment_number']}/{d['num_installments']}"
            f"  ฿{_fmt(d['amount'])}\n"
            f"     กำหนด {d['due'].day} {THAI_MONTHS[d['due'].month]} {d['due'].year + 543} · {tag}"
        )
        total += d["amount"]
    lines.append(f"\n💵 รวมทั้งหมด: ฿{_fmt(total)}")
    lines.append(f"🕒 {_now_str()}")
    _notifier.send("\n".join(lines))


def _send_day_before_reminder() -> None:
    """Run daily — notify if any unpaid payment is due tomorrow."""
    tomorrow = date.today() + timedelta(days=1)
    conn = _open_db()
    try:
        due = [d for d in _unpaid_with_due(conn) if d["due"] == tomorrow]
    finally:
        conn.close()

    if not due:
        return

    lines = ["⏰ แจ้งเตือนล่วงหน้า 1 วัน\nพรุ่งนี้ครบกำหนดชำระ\n"]
    total = 0.0
    for d in due:
        lines.append(
            f"  • {d['name']}  งวดที่ {d['installment_number']}/{d['num_installments']}"
            f"  ฿{_fmt(d['amount'])}"
        )
        total += d["amount"]
    lines.append(f"\n💵 รวม: ฿{_fmt(total)}")
    lines.append(f"🕒 {_now_str()}")
    _notifier.send("\n".join(lines))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    h1, m1 = _REMINDER_TIME.split(":")
    _scheduler.add_job(
        _send_due_reminder,
        CronTrigger(hour=int(h1), minute=int(m1)),
        id="due_reminder",
    )
    h2, m2 = _DAY_BEFORE_TIME.split(":")
    _scheduler.add_job(
        _send_day_before_reminder,
        CronTrigger(hour=int(h2), minute=int(m2)),
        id="day_before_reminder",
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
    start_date: str  # YYYY-MM
    due_day: int = 1  # day of month payment is due (1-31, clamped to month length)
    note: Optional[str] = None


class InstallmentUpdate(BaseModel):
    due_day: int


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _generate_payments(conn, installment_id: int, total_price: float,
                       num_installments: int, start_date: str) -> None:
    base_amount = round(total_price / num_installments, 2)
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
    if not (1 <= body.due_day <= 31):
        raise HTTPException(status_code=400, detail="due_day must be between 1 and 31")
    try:
        year, month = map(int, body.start_date.split("-"))
        if not (1 <= month <= 12):
            raise ValueError
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="start_date must be YYYY-MM format")

    cur = conn.execute(
        "INSERT INTO installments (name, total_price, num_installments, start_date, due_day, note) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (body.name.strip(), body.total_price, body.num_installments,
         body.start_date, body.due_day, body.note),
    )
    installment_id = cur.lastrowid
    _generate_payments(conn, installment_id, body.total_price, body.num_installments, body.start_date)
    conn.commit()  # commit before reading back

    return _installment_with_payments(conn, installment_id)


@app.get("/api/installments/{installment_id}")
def get_installment(installment_id: int, conn=Depends(get_conn)):
    return _installment_with_payments(conn, installment_id)


@app.patch("/api/installments/{installment_id}")
def update_installment(installment_id: int, body: InstallmentUpdate, conn=Depends(get_conn)):
    if not (1 <= body.due_day <= 31):
        raise HTTPException(status_code=400, detail="due_day must be between 1 and 31")
    row = conn.execute(
        "SELECT id FROM installments WHERE id = ?", (installment_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Installment not found")
    conn.execute(
        "UPDATE installments SET due_day = ? WHERE id = ?", (body.due_day, installment_id)
    )
    conn.commit()
    return _installment_with_payments(conn, installment_id)


@app.delete("/api/installments/{installment_id}", status_code=204)
def delete_installment(installment_id: int, conn=Depends(get_conn)):
    row = conn.execute(
        "SELECT id FROM installments WHERE id = ?", (installment_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Installment not found")
    # Delete slip files for all payments of this installment
    slips = conn.execute(
        "SELECT slip_filename FROM payments WHERE installment_id = ? AND slip_filename IS NOT NULL",
        (installment_id,),
    ).fetchall()
    conn.execute("DELETE FROM installments WHERE id = ?", (installment_id,))
    conn.commit()
    for s in slips:
        try:
            (SLIPS_DIR / s["slip_filename"]).unlink(missing_ok=True)
        except Exception:
            pass


@app.post("/api/payments/{payment_id}/pay")
def mark_paid(payment_id: int, conn=Depends(get_conn)):
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
    conn.execute("UPDATE payments SET paid_at = ? WHERE id = ?", (paid_at, payment_id))
    conn.commit()  # commit immediately so next read sees updated data

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
    conn.commit()  # commit immediately
    return {"payment_id": payment_id, "paid_at": None}


@app.post("/api/payments/{payment_id}/slip")
async def upload_slip(payment_id: int, file: UploadFile = File(...), conn=Depends(get_conn)):
    row = conn.execute(
        "SELECT id, slip_filename FROM payments WHERE id = ?", (payment_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Payment not found")

    ext = ""
    if file.filename:
        ext = os.path.splitext(file.filename)[1].lower()
    if ext not in _ALLOWED_SLIP_EXTS:
        raise HTTPException(status_code=400, detail=f"Allowed types: {', '.join(_ALLOWED_SLIP_EXTS)}")

    # Delete old slip file if exists
    if row["slip_filename"]:
        try:
            (SLIPS_DIR / row["slip_filename"]).unlink(missing_ok=True)
        except Exception:
            pass

    filename = f"payment_{payment_id}_{uuid.uuid4().hex[:8]}{ext}"
    dest = SLIPS_DIR / filename
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    conn.execute("UPDATE payments SET slip_filename = ? WHERE id = ?", (filename, payment_id))
    conn.commit()
    return {"payment_id": payment_id, "slip_filename": filename}


@app.delete("/api/payments/{payment_id}/slip", status_code=204)
def delete_slip(payment_id: int, conn=Depends(get_conn)):
    row = conn.execute(
        "SELECT slip_filename FROM payments WHERE id = ?", (payment_id,)
    ).fetchone()
    if not row or not row["slip_filename"]:
        raise HTTPException(status_code=404, detail="No slip found")
    try:
        (SLIPS_DIR / row["slip_filename"]).unlink(missing_ok=True)
    except Exception:
        pass
    conn.execute("UPDATE payments SET slip_filename = NULL WHERE id = ?", (payment_id,))
    conn.commit()


@app.get("/api/slips/{filename}")
def serve_slip(filename: str):
    # Sanitize: only allow safe filenames (no path traversal)
    if "/" in filename or "\\" in filename or ".." in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = SLIPS_DIR / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="Slip not found")
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)


@app.get("/api/summary")
def current_month_summary(conn=Depends(get_conn)):
    today = date.today()
    year, month = today.year, today.month
    rows = conn.execute("""
        SELECT p.id, p.installment_id, p.installment_number, p.amount, p.paid_at,
               p.due_year, p.due_month, p.slip_filename,
               i.name, i.num_installments, i.total_price, i.due_day
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
        SELECT i.name, i.total_price, i.num_installments, i.start_date, i.due_day,
               p.installment_number, p.due_year, p.due_month, p.amount, p.paid_at, p.note
        FROM payments p
        JOIN installments i ON i.id = p.installment_id
        ORDER BY i.name, p.installment_number
    """).fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ชื่อรายการ", "ราคารวม", "จำนวนงวด", "วันที่เริ่ม", "วันครบกำหนด",
        "งวดที่", "ปีที่ครบกำหนด", "เดือนที่ครบกำหนด",
        "ยอดงวด", "จ่ายเมื่อ", "หมายเหตุ",
    ])
    for r in rows:
        writer.writerow([
            r["name"], r["total_price"], r["num_installments"], r["start_date"], r["due_day"],
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


# ─── LINE webhook ──────────────────────────────────────────────────────────────

@app.post("/webhook/line")
async def line_webhook(request: Request):
    """Public endpoint (nginx skips basic auth here). A slip image posted in the
    group attaches to the single outstanding payment and marks it paid; if several
    are outstanding, the bot asks which by name and matches the next text reply."""
    if not _LINE_SECRET:
        raise HTTPException(503, "Webhook not configured")
    body = await request.body()
    if not _verify_line_signature(body, request.headers.get("X-Line-Signature", "")):
        raise HTTPException(400, "Invalid LINE signature")
    try:
        data = json.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    for event in data.get("events", []):
        try:
            if event.get("type") != "message":
                continue
            if (event.get("source") or {}).get("groupId") != _LINE_GROUP:
                continue
            msg = event.get("message", {})
            conn = _open_db()
            try:
                outstanding = _outstanding_payments(conn)
                saved_basename = None
                text = None
                if msg.get("type") == "image":
                    content, ext = _fetch_line_content(msg["id"])
                    saved_basename = f"line_{msg['id']}_{uuid.uuid4().hex[:8]}{ext}"
                    (SLIPS_DIR / saved_basename).write_bytes(content)
                elif msg.get("type") == "text":
                    text = (msg.get("text") or "").strip()
                else:
                    continue

                d = decide(outstanding, saved_basename, text, _LINE_GROUP, _pending, time.time())
                if d.action == "attach_pay" and d.payment_id is not None:
                    _apply_attach_pay(conn, d.payment_id, d.slip_path)
                if d.reply_text:
                    _notifier.send(d.reply_text)
            finally:
                conn.close()
        except Exception:  # one bad event must not 500 the batch (LINE retries forever)
            _logger.exception("webhook event failed")
    return {"ok": True}


# ─── Static frontend ──────────────────────────────────────────────────────────
import pathlib as _pathlib
_STATIC_DIR = _pathlib.Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
