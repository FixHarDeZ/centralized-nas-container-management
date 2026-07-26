"""bearbit.org Hit & Run monitor.

Site rules (myhr.php): every downloaded file must seed 48.0 hours. Timeline per
file is download-done → 24h ผ่อนผัน (pause) → เตือน (warn) → ผิด (hit) at 168h.
18 pending violations locks downloading.

Only the parser lives here — fetching is scraper.fetch_hr_html() (myhr.php is
served as windows-874, which is Python's cp874).
"""

import hashlib
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import config
from bs4 import BeautifulSoup

_TZ = ZoneInfo(config.TZ)

HR_WINDOW_H = 168.0  # total hours from download-done to violation
HR_CAP = 18  # pending violations that lock downloading

# Badge class → meaning. Unknown classes fall through as-is (site may add more).
STATE_LABELS = {
    "hit": "ผิด (H&R)",
    "warn": "เตือน",
    "ok": "กำลัง seed",
    "pause": "ผ่อนผัน",
}

_NUM = re.compile(r"-?[\d.]+")


def _num(text: str) -> float | None:
    m = _NUM.search((text or "").replace(",", ""))
    return float(m.group(0)) if m else None


def parse_hr(html: str) -> list[dict]:
    """Parse myhr.php into row dicts. Columns (verified 2026-07-26):
    0 title (+details.php?id=) · 1 finished · 2 "3.0 ชม. / 48.0 ชม." ·
    3 remaining · 4 "180.4 ชม. ที่แล้ว" · 5 status badge span.bd.<state>
    """
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="t")
    if not table:
        return []

    now = datetime.now(_TZ)
    rows: list[dict] = []
    for tr in table.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 6:
            continue  # header row

        badge = tds[5].find("span", class_="bd")
        classes = badge.get("class", []) if badge else []
        state = next((c for c in classes if c != "bd"), "")

        a = tds[0].find("a", href=True)
        site_id = ""
        if a:
            m = re.search(r"[?&]id=(\d+)", a["href"])
            site_id = m.group(1) if m else ""

        finished_at = tds[1].get_text(" ", strip=True)
        finished_dt = None
        try:
            finished_dt = datetime.strptime(
                finished_at[:16],
                "%Y-%m-%d %H:%M",
            ).replace(tzinfo=_TZ)
        except ValueError:
            pass

        last_seen_txt = tds[4].get_text(strip=True)
        progress = tds[2].get_text(" ", strip=True)
        seeded_h, _, target_h = progress.partition("/")
        remaining_h = _num(tds[3].get_text(strip=True))

        # slack = hours of leeway left after seeding out the remaining requirement.
        # Negative = deadline can no longer be met even if seeding starts now.
        slack_h = None
        deadline = None
        if finished_dt and remaining_h is not None:
            deadline = finished_dt + timedelta(hours=HR_WINDOW_H)
            slack_h = (deadline - now).total_seconds() / 3600 - remaining_h

        rows.append(
            {
                "site_id": site_id,
                "title": (a.get_text(strip=True) if a else tds[0].get_text(strip=True)),
                "finished_at": finished_at,
                "seeded_h": _num(seeded_h),
                "target_h": _num(target_h),
                "remaining_h": remaining_h,
                "last_seen_h": _num(last_seen_txt),
                # "กำลังนับอยู่" = client is announcing right now. Distinct from an
                # unparseable cell, which also yields last_seen_h=None.
                "seeding_now": "กำลังนับ" in last_seen_txt,
                "state": state,
                "state_label": STATE_LABELS.get(state, state),
                "deadline": deadline.strftime("%d/%m %H:%M") if deadline else "",
                "slack_h": slack_h,
            },
        )
    return rows


def summarize(rows: list[dict], slack_threshold_h: float = 24.0) -> dict:
    """Split rows into what needs a push and what is merely informational.

    `ok` = still seeding, never alerted. `pause`/`warn` alert only once slack drops
    under the threshold, otherwise 7 rows sit in `warn` for five days and the push
    becomes noise.
    """
    hits = [r for r in rows if r["state"] == "hit"]
    risky = [
        r
        for r in rows
        if r["state"] in ("warn", "pause")
        and r["slack_h"] is not None
        and r["slack_h"] < slack_threshold_h
    ]
    risky.sort(key=lambda r: r["slack_h"])
    return {
        "rows": rows,
        "hits": hits,
        "risky": risky,
        "hit_count": len(hits),
        "seeding_count": sum(1 for r in rows if r["state"] == "ok"),
        "cap": HR_CAP,
    }


def _fmt_h(v: float | None) -> str:
    return "?" if v is None else f"{v:.1f}"


def format_message(summary: dict) -> str:
    """Plain-text push body shared by LINE and Telegram."""
    risky, hits = summary["risky"], summary["hits"]
    lines = [
        f"⚠️ bearbit H&R — เสี่ยงหลุด {len(risky)} รายการ"
        f" (ผิดแล้ว {summary['hit_count']}/{summary['cap']}, กำลัง seed {summary['seeding_count']})\n",
    ]
    for r in risky[:10]:
        lines.append(
            f"🎬 {r['title'][:70]}\n"
            f"   ⏳ seed {_fmt_h(r['seeded_h'])}/{_fmt_h(r['target_h'])} ชม."
            f" · ขาดอีก {_fmt_h(r['remaining_h'])} ชม.\n"
            f"   ⌛ เหลือเวลา {_fmt_h(r['slack_h'])} ชม. (ครบกำหนด {r['deadline']})\n"
            f"   📡 ระบบเห็นล่าสุด {_fmt_h(r['last_seen_h'])} ชม. ที่แล้ว",
        )
    if len(risky) > 10:
        lines.append(f"...และอีก {len(risky) - 10} รายการ")
    if hits:
        lines.append(
            f"\n🔴 ผิดแล้ว {len(hits)} ไฟล์ — ปลดล็อกด้วย seed bonus ที่ /myhr.php",
        )
    return "\n".join(lines)


def fix_candidates(rows: list[dict], stale_h: float = 24.0, limit: int = 5) -> list[dict]:
    """Rows worth re-adding to Download Station: warned, still savable, and the
    tracker has not seen our client for `stale_h` hours (= the DS task is gone).

    seeding_now rows are announcing right now — re-adding them would duplicate a
    live task. A None last_seen_h with seeding_now=False means the cell did not
    parse, which is not proof of staleness, so it never qualifies either.
    """
    out = [
        r
        for r in rows
        if r["state"] == "warn"
        and not r.get("seeding_now")
        and r["last_seen_h"] is not None
        and r["last_seen_h"] > stale_h
        and (r["remaining_h"] or 0) > 0
        and r["site_id"]
    ]
    out.sort(key=lambda r: (r["slack_h"] is None, r["slack_h"]))
    return out[:limit]


def is_cleared(row: dict) -> bool:
    """True once the file has seeded its full requirement."""
    if row["seeded_h"] is None or row["target_h"] is None:
        return False
    return row["seeded_h"] >= row["target_h"] or (row["remaining_h"] or 0) <= 0


def digest(summary: dict) -> str:
    """Stable fingerprint of the actionable set — used to skip identical daily pushes."""
    key = "|".join(
        sorted(f"{r['site_id']}:{r['state']}" for r in summary["risky"] + summary["hits"])
    )
    return hashlib.sha1(key.encode()).hexdigest()[:16]


if __name__ == "__main__":
    # Synthetic page in the real myhr.php shape, encoded/decoded as cp874 to pin
    # the encoding contract (bearbit sends windows-874; httpx claims utf-8).
    _now = datetime.now(_TZ)

    def _ago(h: float) -> str:
        return (_now - timedelta(hours=h)).strftime("%Y-%m-%d %H:%M")

    # finished-hours-ago chosen so slack is unambiguous: warn is past saving,
    # pause has a whole fresh window left.
    _rows = [
        (_ago(200), "3.0 ชม. / 48.0 ชม.", "45.0 ชม.", "180.4 ชม. ที่แล้ว", "hit"),
        (_ago(160), "23.5 ชม. / 48.0 ชม.", "24.5 ชม.", "0.3 ชม. ที่แล้ว", "warn"),
        (_ago(100), "10.0 ชม. / 48.0 ชม.", "38.0 ชม.", "0.2 ชม. ที่แล้ว", "ok"),
        (_ago(2), "1.0 ชม. / 48.0 ชม.", "47.0 ชม.", "0.1 ชม. ที่แล้ว", "pause"),
        # stale warn = DS task gone, the auto-fix target
        (_ago(160), "23.5 ชม. / 48.0 ชม.", "24.5 ชม.", "30.0 ชม. ที่แล้ว", "warn"),
        # same numbers but the client is announcing — must never be re-added
        (_ago(160), "23.5 ชม. / 48.0 ชม.", "24.5 ชม.", "กำลังนับอยู่", "warn"),
        # fully seeded, waiting to drop off the page
        (_ago(60), "48.0 ชม. / 48.0 ชม.", "0.0 ชม.", "0.1 ชม. ที่แล้ว", "ok"),
    ]
    _rows = [(f"200000{i + 1}", *r) for i, r in enumerate(_rows)]
    _html = '<table class="t"><tr><th>ชื่อ</th><th>เสร็จ</th><th>seed</th><th>ขาด</th><th>เห็นล่าสุด</th><th>สถานะ</th></tr>'
    for _id, _fin, _prog, _rem, _seen, _st in _rows:
        _html += (
            f'<tr><td><a href="details.php?id={_id}">เรื่องทดสอบ {_id}</a></td>'
            f'<td class="muted">{_fin}</td><td>{_prog}</td><td>{_rem}</td>'
            f'<td>{_seen}</td><td><span class="bd {_st}">x</span></td></tr>'
        )
    _html += "</table>"
    _parsed = parse_hr(_html.encode("cp874").decode("cp874"))

    assert len(_parsed) == 7, _parsed
    assert [r["state"] for r in _parsed[:4]] == ["hit", "warn", "ok", "pause"]
    assert _parsed[0]["site_id"] == "2000001"
    assert "เรื่องทดสอบ" in _parsed[0]["title"], _parsed[0]["title"]
    # Column sanity: remaining == target - seeded, catches column reordering
    for r in _parsed:
        assert abs(r["target_h"] - r["seeded_h"] - r["remaining_h"]) < 0.05, r

    _s = summarize(_parsed, slack_threshold_h=24.0)
    assert _s["hit_count"] == 1
    assert _s["seeding_count"] == 2
    # ok is never risky; pause with 47h to seed and a fresh 168h window has slack
    assert {r["site_id"] for r in _s["risky"]} == {"2000002", "2000005", "2000006"}, _s["risky"]

    _c = fix_candidates(_parsed, stale_h=24.0)
    # only the stale warn row: 2000002 was seen 0.3h ago, 2000006 is announcing,
    # 2000001 already violated, 2000004 is still in the grace window
    assert [r["site_id"] for r in _c] == ["2000005"], _c
    assert _parsed[5]["seeding_now"] is True and _parsed[5]["last_seen_h"] is None
    assert _parsed[4]["seeding_now"] is False
    assert is_cleared(_parsed[6]) and not is_cleared(_parsed[1])
    assert digest(_s) == digest(summarize(parse_hr(_html)))
    assert "H&R" in format_message(_s)
    print("hr self-check OK:", {k: _s[k] for k in ("hit_count", "seeding_count")})
