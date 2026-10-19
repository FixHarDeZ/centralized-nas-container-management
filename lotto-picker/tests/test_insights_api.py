"""History backfill, style picks, ledger, ticket check and summaries."""

import datetime as dt
import json
from pathlib import Path

import pytest
from app import analysis, db, insight, lotto, main, service
from fastapi.testclient import TestClient

FIX = Path(__file__).parent / "fixtures"
PRIZES = lotto.parse_prizes(json.loads((FIX / "latest_2026-10-01.json").read_text())["response"]["data"])


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "lotto.db")
    monkeypatch.setattr(lotto, "HISTORY_START", dt.date(2026, 1, 1))
    service._cache.clear()
    db.init()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "_scheduler", type("S", (), {
        "add_job": lambda *a, **k: None, "start": lambda *a: None, "shutdown": lambda *a, **k: None,
    })())
    monkeypatch.setattr(main.threading, "Thread", lambda *a, **k: type("T", (), {"start": lambda s: None})())
    with TestClient(main.app) as c:
        yield c


def with_last2(n):
    return {**PRIZES, "last2": [n]}


def fake_on(draw_days, incomplete=()):
    calls = []

    def on(day):
        iso = day.isoformat()
        calls.append(iso)
        if iso in incomplete:
            return {"date": iso, "prizes": {**PRIZES, "fifth": PRIZES["fifth"][:3]}}
        return {"date": iso, "prizes": with_last2(f"{len(calls) % 100:02d}")} if iso in draw_days else None

    return on, calls


# --- history backfill ------------------------------------------------------------


def test_backfill_walks_every_candidate_day_and_is_resumable():
    days = {"2026-01-02", "2026-01-17", "2026-02-01", "2026-02-16", "2026-03-01"}
    on, calls = fake_on(days)
    status = service.backfill_history(on, today=dt.date(2026, 3, 10), sleep=lambda s: None)
    assert status["state"] == "done"
    assert db.draw_dates() == days
    assert all(dt.date.fromisoformat(c).day in lotto.CANDIDATE_DAYS for c in calls[:20])
    calls.clear()
    service.backfill_history(on, today=dt.date(2026, 3, 10), sleep=lambda s: None)
    assert calls == []  # everything known: draws, nodraw, skipped


def test_backfill_finds_moved_draw_by_probing_short_months():
    # 2026-01-20 is not a candidate day: January ends with one draw, so pass two
    # probes every remaining January day and finds it.
    days = {"2026-01-02", "2026-01-20", "2026-02-01", "2026-02-16"}
    on, calls = fake_on(days)
    service.backfill_history(on, today=dt.date(2026, 2, 20), sleep=lambda s: None)
    assert "2026-01-20" in db.draw_dates()
    assert "2026-02-05" not in calls  # February is the current month, untouched


def test_backfill_records_incomplete_payloads_and_stops_on_error():
    on, _calls = fake_on({"2026-01-02"}, incomplete={"2026-01-16"})
    service.backfill_history(on, today=dt.date(2026, 1, 20), sleep=lambda s: None)
    assert "2026-01-16" in db.get("history_skipped")
    assert "2026-01-16" not in db.nodraw_dates()

    def boom(day):
        raise OSError("network down")

    status = service.backfill_history(boom, today=dt.date(2026, 3, 1), sleep=lambda s: None)
    assert status["state"] == "error" and "network down" in status["error"]


# --- style picks -----------------------------------------------------------------


def seed(numbers):
    for i, n in enumerate(numbers):
        db.add_draw({"date": f"2026-{1 + i // 2:02d}-{1 if i % 2 == 0 else 16:02d}",
                     "prizes": with_last2(n)})


def test_hot_style_picks_from_most_frequent_after_exclusion(monkeypatch):
    seed(["11", "11", "11", "22", "22", "33"])  # newest draw = 33
    p = service.make_pick(1, 1, "last2", False, digits=2, style="hot")
    assert p["candidates"] == 99  # quarter cut lands on the tied zeros → all kept
    monkeypatch.setattr(analysis, "STYLE_SHARE", 0)
    p = service.make_pick(1, 1, "last2", False, digits=2, style="hot")
    assert p["numbers"] == ["11"] and p["candidates"] == 1
    assert p["reasons"]["11"] == {"count": 3, "gap": 3}
    assert p["settings"]["style"] == "hot"


def test_overdue_and_window():
    seed(["11", "22", "33", "44"])
    p = service.make_pick(1, 3, "last2", False, digits=2, style="hot", stat_window=2)
    assert p["history_draws"] == 2
    assert p["reasons"]
    p = service.make_pick(1, 1, "last2", False, digits=2, style="overdue")
    assert p["reasons"][p["numbers"][0]]["gap"] == 4  # never seen


def test_pick_api_accepts_style_and_rejects_unknown(client):
    seed(["11", "22"])
    ok = client.post("/api/pick", json={"digits": 2, "draws": 1, "picks": 3, "style": "cold"})
    assert ok.status_code == 200 and ok.json()["settings"]["style"] == "cold"
    assert client.post("/api/pick", json={"digits": 2, "style": "lucky"}).status_code == 422


def test_frequency_backtest_and_history_endpoints(client):
    seed(["11", "11", "22", "33", "44", "55"])
    f = client.get("/api/frequency?digits=2").json()
    assert f["draws"] == 6 and next(r for r in f["numbers"] if r["number"] == "11")["count"] == 2
    assert client.get("/api/frequency?digits=3&category=nope").status_code == 422
    assert client.get("/api/frequency?digits=3&category=all").json()["category"] == "all"
    bt = client.get("/api/backtest?digits=2&picks=5&draws=1&scope=last2").json()
    assert bt["plays"] == 0  # fewer than 24 draws of history
    h = client.get("/api/history").json()
    assert h["count"] == 6 and h["start"] == "2026-01-01"
    assert len(client.get("/api/draws?limit=2").json()) == 2


# --- ledger + ticket check --------------------------------------------------------


def test_ledger_auto_prize_manual_override_and_pending(client):
    db.add_draw({"date": "2026-10-01", "prizes": PRIZES})
    first = PRIZES["first"][0]
    a = client.post("/api/ledger", json={"draw_date": "2026-10-01", "label": "แผง",
                                          "tickets": [{"number": first, "qty": 1},
                                                      {"number": "000001", "qty": 2}],
                                          "cost": 240}).json()["id"]
    client.post("/api/ledger", json={"draw_date": "2026-10-01", "cost": 100, "prize": 50})
    client.post("/api/ledger", json={"draw_date": "2026-10-16", "cost": 80})
    view = client.get("/api/ledger").json()
    entry = next(e for e in view["entries"] if e["id"] == a)
    assert entry["status"] == "won" and entry["won"] >= 6_000_000
    s = view["summary"]
    assert s["pending"] == 1 and s["pending_cost"] == 80 and s["cost"] == 340
    assert s["expected_return"] == 0.6
    assert client.post("/api/ledger", json={"draw_date": "2026-10-01", "cost": 80,
                                            "tickets": [{"number": "12345"}]}).status_code == 422
    assert client.put(f"/api/ledger/{a}", json={"draw_date": "2026-10-01", "cost": 1}).status_code == 200
    assert client.delete(f"/api/ledger/{a}").status_code == 204
    assert client.delete(f"/api/ledger/{a}").status_code == 404


def test_ledger_nominal_date_matches_shifted_draw(client):
    # saved after 16 Dec as "next draw 1 Jan"; GLO held it on 30 Dec
    db.add_draw({"date": "2025-12-30", "prizes": PRIZES})
    client.post("/api/ledger", json={"draw_date": "2026-01-01", "cost": 80,
                                     "tickets": [{"number": PRIZES["first"][0]}]})
    entry = client.get("/api/ledger").json()["entries"][0]
    assert entry["result_draw"] == "2025-12-30" and entry["status"] == "won"
    client.post("/api/ledger", json={"draw_date": "2026-01-16", "cost": 80})
    pending = next(e for e in client.get("/api/ledger").json()["entries"] if e["draw_date"] == "2026-01-16")
    assert pending["status"] == "pending"


def test_ticket_check(client):
    assert client.get("/api/check?number=123456").status_code == 404
    db.add_draw({"date": "2026-10-01", "prizes": PRIZES})
    r = client.get(f"/api/check?number=000{PRIZES['last3b'][0]}").json()
    assert "last3b" in r["kinds"] and r["total"] >= 4000
    assert client.get("/api/check?number=12ab56").status_code == 422


def test_sync_stores_prize_amounts_from_latest():
    service.sync(1, lambda: {"date": "2026-10-01", "prizes": PRIZES, "amounts": {"last2": 2500}},
                 lambda d: None, today=dt.date(2026, 10, 2), sleep=lambda s: None)
    assert service.prize_amounts()["last2"] == 2500


# --- insight ------------------------------------------------------------------------


def test_insight_uses_ai_text_only_when_it_passes_checks(monkeypatch):
    seed(["11", "11", "22", "33"])
    good = lambda f: f"ล่าสุด {f['เลขที่ออกงวดล่าสุด']['เลขท้าย 2 ตัว'][0]}\n{insight.DISCLAIMER}"  # noqa: E731
    assert insight.generate(2, ask=good)["source"] == "ai"
    invented = lambda f: f"เลข 77 ออก 99 ครั้ง\n{insight.DISCLAIMER}"  # noqa: E731
    r = insight.generate(2, ask=invented)
    assert r["source"] == "template" and "numbers not in facts" in r["error"]
    tipster = lambda f: f"เลขเด็ด 11\n{insight.DISCLAIMER}"  # noqa: E731
    assert insight.generate(2, ask=tipster)["error"] == "tipster phrase"

    def stalled(f):
        raise TimeoutError("silent")

    r = insight.generate(2, ask=stalled)
    assert r["source"] == "template" and insight.DISCLAIMER in r["text"]
    assert insight.current(2)["stale"] is False


def test_insight_template_without_key(monkeypatch):
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    seed(["11", "22"])
    r = insight.generate(3)
    assert r["source"] == "template" and r["error"] is None
    assert "งวด" in r["text"]
