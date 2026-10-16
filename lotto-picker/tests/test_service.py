import datetime as dt
import json
from pathlib import Path

import pytest
from app import db, lotto, service

FIX = Path(__file__).parent / "fixtures"
PRIZES = lotto.parse_prizes(json.loads((FIX / "latest_2026-10-01.json").read_text())["response"]["data"])

# Real 2026 draw dates around the fixture, including the 17 Jan holiday shift.
DRAW_DAYS = ["2026-01-02", "2026-01-17", "2026-02-01", "2026-02-16", "2026-03-01"]


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "lotto.db")
    db.init()


def fake_glo(days, latest_complete=True):
    calls = []

    def latest():
        prizes = PRIZES if latest_complete else {**PRIZES, "fifth": PRIZES["fifth"][:3]}
        return {"date": days[-1], "prizes": prizes}

    def on(day):
        calls.append(day.isoformat())
        return {"date": day.isoformat(), "prizes": PRIZES} if day.isoformat() in days else None

    return latest, on, calls


def run(want, latest, on, today="2026-03-10"):
    return service.sync(want, latest, on, today=dt.date.fromisoformat(today), sleep=lambda s: None)


def test_first_boot_caches_latest_without_announcing():
    latest, on, _ = fake_glo(DRAW_DAYS)
    assert run(2, latest, on) is None
    assert "2026-03-01" in db.draw_dates()


def test_backfill_finds_shifted_draw_and_announces_only_latest():
    latest, on, calls = fake_glo(DRAW_DAYS[:-1])
    run(1, latest, on)  # first boot: 02-16 cached silently
    latest, on, calls = fake_glo(DRAW_DAYS)
    fresh = run(4, latest, on)
    assert fresh["date"] == "2026-03-01"
    assert sorted(db.draw_dates()) == DRAW_DAYS[1:]
    assert "2026-02-15" in calls  # probed, null, cached as no-draw
    assert "2026-02-15" in db.nodraw_dates()
    assert "2026-01-16" not in calls  # stopped once 4 draws were found
    # every probe was a candidate day
    assert all(dt.date.fromisoformat(c).day in lotto.CANDIDATE_DAYS for c in calls)


def test_second_sync_is_quiet_and_does_not_reprobe():
    latest, on, calls = fake_glo(DRAW_DAYS)
    run(4, latest, on)
    calls.clear()
    assert run(4, latest, on) is None
    assert calls == []


def test_in_progress_draw_is_not_cached_but_marks_seen():
    latest, on, _ = fake_glo(DRAW_DAYS, latest_complete=False)
    assert run(2, latest, on) is None
    assert "2026-03-01" not in db.draw_dates()
    assert db.get("latest_seen") == "2026-03-01"
    assert service.based_on() == "2026-03-01"


def test_pick_is_scored_against_the_next_draw_only():
    latest, on, _ = fake_glo(DRAW_DAYS[:-1])  # latest = 02-16
    run(2, latest, on)
    pid = db.add_pick("manual", ["701", "123"], {}, service.based_on())
    assert service.score_pending() == []  # 02-16 is already public

    latest, on, _ = fake_glo(DRAW_DAYS)  # 03-01 published
    run(2, latest, on)
    scored = service.score_pending()
    assert [s["id"] for s in scored] == [pid]
    assert scored[0]["result_draw"] == "2026-03-01"
    assert service.stats()["exact_hits"] == 1
    assert service.score_pending() == []  # never scored twice


def test_make_pick_excludes_cached_draws():
    latest, on, _ = fake_glo(DRAW_DAYS)
    run(2, latest, on)
    p = service.make_pick(2, 5, "all", False)
    assert len(p["numbers"]) == 5
    assert not set(p["numbers"]) & lotto.draw_numbers(PRIZES)
    assert p["draws_used"] == ["2026-03-01", "2026-02-16"]
