"""Presentation of recorded data; no bot actions, credentials or drawing imports."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

BANGKOK = timezone(timedelta(hours=7))

OUTCOMES = {
    "drafting": ("drafting", "ฉบับร่าง", "neutral"),
    "rendered": ("ready", "รออัปโหลด", "info"),
    "assembled": ("ready", "รออัปโหลด", "info"),
    "generate_failed": ("failed", "เขียนไม่สำเร็จ", "danger"),
    "render_failed": ("failed", "เรนเดอร์ไม่สำเร็จ", "danger"),
    "discarded": ("discarded", "ทิ้งสคริปต์", "neutral"),
    "abandoned": ("abandoned", "สิ้นสุดการรอ", "neutral"),
    "no_sources": ("no_sources", "ไม่พบแหล่งอ้างอิง", "warning"),
}
MODES = {
    "idle": ("พร้อมรับหัวข้อใหม่", "neutral"),
    "writing": ("กำลังเขียนสคริปต์", "info"),
    "review": ("รอรีวิวสคริปต์", "warning"),
    "rendering": ("กำลังเรนเดอร์", "info"),
}
ARM_LABELS = {"shock_number": "เปิดด้วยตัวเลข", "question": "เปิดด้วยคำถาม", "explore": "สำรวจหัวข้อใหม่"}


def format_number(value) -> str:
    """Unavailable is not zero. Counts have grouping but no invented decimals."""
    if value is None:
        return "—"
    if isinstance(value, (int, float)):  # noqa: UP038 - local preview supports Python 3.9
        return f"{value:,.0f}"
    return str(value)


def format_percent(value) -> str:
    return "—" if value is None else f"{value:.1f}%"


def format_date(value) -> str:
    """Bot's naive timestamps are Bangkok time; aware ones convert explicitly."""
    if not value:
        return "—"
    text = str(value)
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return text
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone(BANGKOK)
    return stamp.strftime("%d/%m/%Y · %H:%M" if "T" in text or " " in text else "%d/%m/%Y")


def status(record: dict, state: dict | None = None) -> dict:
    """Labels describe this record, not an unrelated draft or a live heartbeat."""
    if record.get("published"):
        key, label, tone = "published", "เผยแพร่แล้ว", "success"
    elif state and record.get("id") and state.get("clip_id") == record["id"] and state.get("mode") in {"review", "writing", "rendering"}:
        mode = state["mode"]
        key = {"writing": "drafting", "review": "review", "rendering": "rendering"}[mode]
        label, tone = MODES[mode]
    else:
        outcome = record.get("outcome") or ""
        key, label, tone = OUTCOMES.get(outcome, (outcome, outcome or "ยังไม่มีผลลัพธ์", "neutral"))
    return {"key": key, "label": label, "tone": tone}


def waiting_jobs(state: dict) -> list[dict]:
    """Only waits actually present in the saved state; no guessed deadlines."""
    jobs = []
    if state.get("mode") == "review":
        jobs.append({"label": "รอรีวิวสคริปต์", "topic": state.get("topic") or "",
                     "clip_id": state.get("clip_id") or "", "detail": "รีวิวและเลือกการทำงานใน Telegram"})
    for key, label, detail in (
        ("parked", "รอวิดีโอจาก Flow", "ตอบกลับข้อความเดิมใน Telegram ด้วยไฟล์วิดีโอ"),
        ("clip_wait", "รอคลิปที่ประกอบจาก Storyboard", "ตอบกลับข้อความ Storyboard เดิมด้วยคลิปที่ประกอบแล้ว"),
        ("auto_pick", "รอเลือกหัวข้ออัตโนมัติ", "เลือกหัวข้อหรือหยุดรอบใน Telegram"),
    ):
        item = state.get(key)
        if not isinstance(item, dict) or not item:
            continue
        deadline = item.get("deadline")
        if deadline:
            detail += f" · กำหนดที่บันทึกไว้ {format_date(deadline)}"
        jobs.append({"label": label, "topic": item.get("topic") or "",
                     "clip_id": item.get("clip_id") or "", "detail": detail})
    return jobs


def sources(record: dict) -> list[dict]:
    """Research links are external data: only ordinary HTTP(S) destinations."""
    research = record.get("research")
    if not isinstance(research, dict):
        return []
    results = research.get("results")
    if not isinstance(results, list):
        return []
    found = []
    for source in results:
        if not isinstance(source, dict) or not isinstance(source.get("url"), str):
            continue
        url = source["url"].strip()
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if parsed.scheme.lower() in {"http", "https"} and parsed.netloc:
            found.append({"title": str(source.get("title") or parsed.netloc), "url": url})
    return found
