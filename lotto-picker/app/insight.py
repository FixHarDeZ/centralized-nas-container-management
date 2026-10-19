"""Plain-language summary of the statistics — by mimo when it can, by template
when it can't.

The model only ever *rewords* facts computed here. It is told not to predict,
and its answer is checked before anyone sees it: every number in the text must
appear in the facts it was given, and tipster phrases are rejected. A failed
check, a missing key or a stalled endpoint all fall back to the template, so a
summary always exists and never contains a number the code did not compute.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import re
import threading

from . import analysis, db, lotto, service

logger = logging.getLogger(__name__)

AI_BUDGET = 300.0
_running: set[int] = set()
_lock = threading.Lock()

# Phrases a tipster uses. Any of them means the model drifted into predicting.
BANNED = (
    "น่าจะออก", "ควรซื้อ", "เลขเด็ด", "แนะนำให้ซื้อ", "มีโอกาสออกสูง", "โอกาสออกมาก",
    "มาแรง", "ต้องออก", "ถึงคิว", "ห้ามพลาด", "งวดหน้าออก",
)
DISCLAIMER = "ทุกเลขมีโอกาสออกเท่ากันทุกงวด สถิติย้อนหลังใช้ทำนายไม่ได้"

SYSTEM = (
    "คุณสรุปสถิติสลากกินแบ่งรัฐบาลเป็นภาษาไทยสั้นๆ จากข้อมูล JSON ที่ให้เท่านั้น\n"
    "กติกา:\n"
    "- ห้ามทำนาย ห้ามแนะนำเลข ห้ามบอกว่าเลขใดมีโอกาสออกมากหรือน้อยกว่าเลขอื่น\n"
    "- ใช้เฉพาะตัวเลขที่มีใน JSON ห้ามคำนวณหรือแต่งตัวเลขใหม่\n"
    "- อธิบายว่าเลขที่ออกบ่อย/ค้างนาน อยู่ในช่วงที่การสุ่มล้วนให้ได้ตามปกติหรือไม่\n"
    "- ถ้ามีผลทดสอบย้อนหลัง ให้บอกว่ากลยุทธ์ไหนต่างจากสุ่มอย่างมีนัยสำคัญหรือไม่\n"
    "- ห้ามเขียนชื่อฟิลด์หรือคำภาษาอังกฤษจาก JSON ให้เขียนเป็นภาษาไทยธรรมดา\n"
    "- ไม่เกิน 6 บรรทัด ขึ้นบรรทัดใหม่ต่อหัวข้อ ข้อความธรรมดา ไม่ใช้ markdown\n"
    f"- บรรทัดสุดท้ายต้องเป็น: {DISCLAIMER}"
)
STYLE_LABEL = {"baseline": "สุ่มทั้งหมด", "random": "สุ่มหลังตัดเลข", "hot": "เลขออกบ่อย",
               "cold": "เลขออกน้อย", "overdue": "เลขค้างนาน"}


def facts(digits: int) -> dict | None:
    """Everything the summary may say, computed here. None without history."""
    hist = service.history(digits)
    if not hist:
        return None
    latest = hist[0]
    p = latest["prizes"]
    freq = service.frequency(digits, analysis.style_category(digits))
    rows = freq["numbers"]
    hot = sorted(rows, key=lambda r: (-r["count"], r["number"]))[:5]
    never = [r["number"] for r in rows if r["count"] == 0]
    seen = [r for r in rows if r["count"]]
    overdue = sorted(seen, key=lambda r: (-r["gap"], r["number"]))[:5]
    if digits == 2:
        drawn = {"เลขท้าย 2 ตัว": p.get("last2", [])}
    else:
        drawn = {"3 ตัวท้ายรางวัลที่ 1": [p["first"][0][-3:]],
                 "เลขหน้า 3 ตัว": p.get("last3f", []), "เลขท้าย 3 ตัว": p.get("last3b", [])}
    previous = (
        analysis.category_numbers(hist[1]["prizes"], digits, analysis.style_category(digits))
        if len(hist) > 1 else []
    )
    latest_numbers = sorted({n for ns in drawn.values() for n in ns})
    settings = db.settings(digits)
    bt = service.backtest(digits, settings["picks"], settings["draws"], settings["scope"],
                          settings["permute"], settings.get("stat_window", 0))
    out = {
        "โหมด": f"{digits} ตัว",
        "งวดล่าสุด": lotto.thai_date(latest["date"]),
        "เลขที่ออกงวดล่าสุด": drawn,
        "ซ้ำกับงวดก่อนหน้า": sorted(set(latest_numbers) & set(previous)),
        "ประวัติ": {"จำนวนงวด": freq["draws"], "ตั้งแต่": lotto.thai_date(freq["from"]),
                    "ถึง": lotto.thai_date(freq["to"])},
        "ออกบ่อยสุด": [{"เลข": r["number"], "ครั้ง": r["count"]} for r in hot],
        "ค้างนานสุด": [{"เลข": r["number"], "ค้าง_งวด": r["gap"]} for r in overdue],
        "ไม่ออกเลยในช่วงนี้": {"จำนวนเลข": len(never), "ตัวอย่าง": never[:5]},
        "ค่าเฉลี่ยต่อเลข_ครั้ง": freq["expected"],
        "ช่วงปกติต่อเลข_ครั้ง": freq["band"],
        "ออกบ่อยสุดที่เห็น_ครั้ง": freq["max_seen"],
        "ออกบ่อยสุดที่สุ่มล้วนมักได้_ครั้ง": freq["max_typical"],
        "เลขนอกช่วงปกติ": freq["outside"],
        "เลขนอกช่วงปกติที่สุ่มล้วนคาด": freq["outside_expected"],
    }
    if bt["plays"]:
        out["ทดสอบย้อนหลัง"] = {
            "งวดที่ทดสอบ": bt["plays"],
            "ผล": [{"กลยุทธ์": STYLE_LABEL[r["strategy"]], "ถูก": r["hits"],
                    "สุ่มคาดว่า": r["expected"], "ต่างจากสุ่มอย่างมีนัยสำคัญ": r["significant"]}
                   for r in bt["strategies"]],
        }
    return out


def template(f: dict) -> str:
    drawn = " / ".join(f"{k} {' '.join(v)}" for k, v in f["เลขที่ออกงวดล่าสุด"].items())
    hot = ", ".join(f"{h['เลข']} ({h['ครั้ง']} ครั้ง)" for h in f["ออกบ่อยสุด"][:3])
    late = ", ".join(f"{o['เลข']} ({o['ค้าง_งวด']} งวด)" for o in f["ค้างนานสุด"][:3])
    lo, hi = f["ช่วงปกติต่อเลข_ครั้ง"]
    typical = f["ออกบ่อยสุดที่สุ่มล้วนมักได้_ครั้ง"]
    never = f["ไม่ออกเลยในช่วงนี้"]
    lines = [
        f"งวด {f['งวดล่าสุด']}: {drawn}",
        f"ประวัติ {f['ประวัติ']['จำนวนงวด']} งวด ออกบ่อยสุด {hot} · ค้างนานสุด {late}",
        f"ปกติแต่ละเลขออก {lo}-{hi} ครั้ง และเลขที่ออกบ่อยสุดมักได้ {typical[0]}-"
        f"{typical[1]} ครั้งจากการสุ่มล้วน (ที่เห็นจริง {f['ออกบ่อยสุดที่เห็น_ครั้ง']})",
    ]
    if never["จำนวนเลข"]:
        lines.append(f"ไม่ออกเลยในช่วงนี้ {never['จำนวนเลข']} เลข เช่น {' '.join(never['ตัวอย่าง'])}")
    if f["ซ้ำกับงวดก่อนหน้า"]:
        lines.append(f"ซ้ำกับงวดก่อน: {' '.join(f['ซ้ำกับงวดก่อนหน้า'])}")
    bt = f.get("ทดสอบย้อนหลัง")
    if bt:
        sig = [r["กลยุทธ์"] for r in bt["ผล"] if r["ต่างจากสุ่มอย่างมีนัยสำคัญ"]]
        lines.append(
            f"ทดสอบย้อนหลัง {bt['งวดที่ทดสอบ']} งวด: "
            + (f"ต่างจากสุ่มชัดเจน: {', '.join(sig)}" if sig else "ไม่มีกลยุทธ์ไหนต่างจากสุ่มอย่างมีนัยสำคัญ")
        )
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"\d+(?:\.\d+)?", re.sub(r"(?<=\d),(?=\d)", "", text)))


def check(text: str, f: dict) -> str | None:
    """Why the model's text is unusable, or None when it may be shown."""
    if any(b in text for b in BANNED):
        return "tipster phrase"
    allowed = _tokens(json.dumps(f, ensure_ascii=False)) | _tokens(DISCLAIMER)
    allowed |= {str(i) for i in range(11)}  # "3 อันดับ", "2 ตัว"
    extra = _tokens(text) - allowed
    if extra:
        return f"numbers not in facts: {sorted(extra)[:5]}"
    if DISCLAIMER not in text:
        return "missing disclaimer"
    return None


def _ask_ai(f: dict) -> str:
    from . import mimo  # openai import stays off the startup path

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(f, ensure_ascii=False)},
    ]
    return asyncio.run(
        mimo.complete(mimo.client(), messages, within=min(AI_BUDGET, mimo.budget()))
    ).strip()


def generate(digits: int, ask=None) -> dict:
    """Build and store the summary for the latest draw. ``ask`` is the model
    call (a parameter so tests never reach the network)."""
    f = facts(digits)
    if f is None:
        return {}
    text, source, error = template(f), "template", None
    if ask or os.environ.get("MIMO_API_KEY"):
        try:
            answer = (ask or _ask_ai)(f)
            error = check(answer, f)
            if error is None:
                text, source = answer, "ai"
        except Exception as exc:  # Stalled, Truncated, network — template stands
            error = f"{type(exc).__name__}: {exc}"[:200]
        if error:
            logger.warning("insight %d digits fell back to template: %s", digits, error)
    record = {
        "draw": service.history(digits)[0]["date"],
        "text": text,
        "source": source,
        "error": error,
        "at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    db.put(f"insight_{digits}", record)
    return record


def current(digits: int) -> dict:
    record = db.get(f"insight_{digits}") or {}
    latest = service.history(digits)
    return {
        **record,
        "running": digits in _running,
        "stale": bool(latest) and record.get("draw") != latest[0]["date"],
    }


def start(digits: int, then=None) -> bool:
    """Generate in a thread — the model can take minutes. False if one is
    already running for this mode."""
    with _lock:
        if digits in _running:
            return False
        _running.add(digits)

    def run():
        try:
            record = generate(digits)
            if then and record:
                then(record)
        except Exception:
            logger.exception("insight %d digits failed", digits)
        finally:
            with _lock:
                _running.discard(digits)

    threading.Thread(target=run, daemon=True).start()
    return True
