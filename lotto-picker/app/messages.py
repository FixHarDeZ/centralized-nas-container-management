"""Notification text + the stack's Notifier. Formatting stays here, not in the
vendored notify.py."""

from __future__ import annotations

import os

from . import lotto
from .notify import LineCreds, Notifier, TgCreds

SCOPE_LABEL = {
    "all": "ทุกรางวัล",
    "front_back": "เฉพาะเลขหน้า/ท้าย 3 ตัว",
    "last2": "เลขท้าย 2 ตัว",
}
STYLE_LABEL = {
    "random": "สุ่มล้วน",
    "hot": "ตามกระแส (เลขออกบ่อย)",
    "cold": "สวนกระแส (เลขออกน้อย)",
    "overdue": "เลขค้างนาน",
}
KIND_LABEL = {
    "last2": "เลขท้าย 2 ตัว",
    "first3": "3 ตัวท้ายรางวัลที่ 1",
    "first3_tod": "โต๊ด 3 ตัวท้ายรางวัลที่ 1",
    "last3f": "เลขหน้า 3 ตัว",
    "last3b": "เลขท้าย 3 ตัว",
}


TICKET_LABEL = {
    "first": "รางวัลที่ 1",
    "second": "รางวัลที่ 2",
    "third": "รางวัลที่ 3",
    "fourth": "รางวัลที่ 4",
    "fifth": "รางวัลที่ 5",
    "near1": "ข้างเคียงรางวัลที่ 1",
    "last3f": "เลขหน้า 3 ตัว",
    "last3b": "เลขท้าย 3 ตัว",
    "last2": "เลขท้าย 2 ตัว",
}


def notifier() -> Notifier:
    return Notifier(
        line=LineCreds(
            os.getenv("LINE_CHANNEL_ACCESS_TOKEN", ""), os.getenv("LINE_TO", "")
        ),
        telegram=TgCreds(
            os.getenv("LOTTO_TELEGRAM_BOT_TOKEN", ""),
            os.getenv("LOTTO_TELEGRAM_CHAT_ID", ""),
            parse_mode="HTML",
        ),
    )


def _rule(settings: dict) -> str:
    rule = f"ไม่ซ้ำ {settings['draws']} งวดล่าสุด ({SCOPE_LABEL[settings['scope']]})"
    if settings.get("permute"):
        rule += " ตัดเลขกลับด้วย" if settings.get("digits", 3) == 2 else " ตัดโต๊ดด้วย"
    style = settings.get("style", "random")
    if style != "random":
        rule += f"\nสไตล์: {STYLE_LABEL[style]} (โอกาสถูกเท่าสุ่มล้วน)"
    return rule


def _link() -> str:
    url = os.getenv("PUBLIC_URL", "").strip()
    return f"\n\n🔗 {url}" if url else ""


def auto_pick(target: str, pick: dict) -> str:
    return (
        f"🎲 <b>เลขสุ่ม {pick['settings'].get('digits', 3)} ตัว · งวด {lotto.thai_date(target)}</b>\n"
        f"<b>{'  '.join(pick['numbers'])}</b>\n\n"
        f"{_rule(pick['settings'])}\n"
        f"เหลือให้สุ่ม {pick['pool_size']} เลข"
        f"{_link()}"
    )


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def insight(record: dict, digits: int) -> str:
    source = "สรุปโดย AI จากตัวเลขที่ระบบคำนวณ" if record["source"] == "ai" else "สรุปอัตโนมัติ"
    return (
        f"📊 <b>สถิติ {digits} ตัว · งวด {lotto.thai_date(record['draw'])}</b>\n"
        f"{_escape(record['text'])}\n\n<i>{source}</i>{_link()}"
    )


def result(draw: dict, scored: list[dict], stats: dict, digits: int = 3) -> str:
    p = draw["prizes"]
    lines = [f"🎯 <b>ผลสลาก {digits} ตัว · {lotto.thai_date(draw['date'])}</b>"]
    if digits == 3:
        lines.extend(
            [
                f"รางวัลที่ 1: {p['first'][0]} (3 ตัวท้าย <b>{p['first'][0][-3:]}</b>)",
                f"เลขหน้า 3 ตัว: <b>{'  '.join(p['last3f'])}</b>",
                f"เลขท้าย 3 ตัว: <b>{'  '.join(p['last3b'])}</b>",
            ]
        )
    lines.append(f"เลขท้าย 2 ตัว: <b>{'  '.join(p.get('last2', []))}</b>")
    for s in scored:
        hits = {h["number"]: h["kinds"] for h in s["result"]["hits"]}
        marked = [
            f"✅{n}"
            if n in hits and hits[n] != ["first3_tod"]
            else f"🔁{n}"
            if n in hits
            else n
            for n in s["numbers"]
        ]
        lines.append("")
        lines.append(
            f"เลข {digits} ตัวที่สุ่มไว้ ({'อัตโนมัติ' if s['source'] == 'auto' else 'บันทึกเอง'}): {'  '.join(marked)}"
        )
        for n, kinds in hits.items():
            lines.append(f"  {n} → {', '.join(KIND_LABEL[k] for k in kinds)}")
    if stats["picks"]:
        lines.append("")
        lines.append(
            f"สถิติสะสม {digits} ตัว: ถูก {stats['exact_hits']} จาก {stats['numbers']} เลข"
            f" (สุ่มธรรมดาคาดว่า {stats['expected']:.2f})"
        )
    return "\n".join(lines) + _link()


def win(found: dict) -> str:
    """Its own message, so a win never hides inside the routine result text."""
    lines = [f"🎉 <b>ถูกรางวัล · งวด {lotto.thai_date(found['draw'])}</b>"]
    for t in found["tickets"]:
        lines.append("")
        label = f" ({_escape(t['label'])})" if t["label"] else ""
        lines.append(f"🎟 สลากในบัญชี{label}")
        for w in t["wins"]:
            qty = f" ×{w['qty']}" if w["qty"] > 1 else ""  # noqa: RUF001 (shown to people)
            kinds = " + ".join(TICKET_LABEL[k] for k in w["kinds"])
            lines.append(f"<b>{w['number']}</b>{qty} → {kinds} · {w['amount']:,.0f} บาท")
    if found["tickets"]:
        lines.append(f"\n💰 รวม <b>{found['total']:,.0f} บาท</b> · ขึ้นเงินภายใน 2 ปีนับจากวันออกรางวัล")
    for p in found["picks"]:
        lines.append("")
        lines.append(
            f"🎲 เลข {p['digits']} ตัวที่บันทึกไว้ ({'อัตโนมัติ' if p['source'] == 'auto' else 'บันทึกเอง'})"
        )
        for h in p["hits"]:
            lines.append(f"<b>{h['number']}</b> → {', '.join(KIND_LABEL[k] for k in h['kinds'])}")
    return "\n".join(lines) + _link()
