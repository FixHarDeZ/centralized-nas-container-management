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


def test_make_two_digit_pick_uses_last2_pool_and_mode_snapshot():
    db.add_draw({"date": "2026-10-01", "prizes": PRIZES})
    p = service.make_pick(2, 100, "all", False, digits=2)
    assert len(p["numbers"]) == 99
    assert PRIZES["last2"][0] not in p["numbers"]
    assert p["pool_size"] == 99 and p["excluded_count"] == 1
    assert p["excluded"] == ["70"]
    assert p["settings"] == {
        "draws": 2, "picks": 100, "scope": "last2", "permute": False, "digits": 2,
        "style": "random", "stat_window": 0,
    }


def test_mixed_pending_picks_use_their_own_modes_and_stats_stay_separate():
    three = db.add_pick("manual", ["701", "107"], {}, "2026-10-01")
    two = db.add_pick("manual", ["70", "07"], {"digits": 2}, "2026-10-01")
    db.add_draw({"date": "2026-10-16", "prizes": PRIZES})
    results = {p["id"]: p for p in service.score_pending()}
    assert results[three]["result"]["exact_hits"] == 1
    assert results[two]["result"]["hits"] == [{"number": "70", "kinds": ["last2"]}]
    assert service.stats(2) == {
        "picks": 1, "numbers": 2, "exact_hits": 1, "expected": 0.02, "tod_hits": 0,
    }
    assert service.stats()["tod_hits"] == 1
    assert service.stats()["numbers"] == 2


def test_two_digit_pick_waits_for_earliest_target_with_missing_last2():
    two = db.add_pick("manual", ["70"], {"digits": 2}, "2026-10-01")
    three = db.add_pick("manual", ["701"], {}, "2026-10-01")
    old_prizes = {k: v for k, v in PRIZES.items() if k != "last2"}
    db.add_draw({"date": "2026-10-16", "prizes": old_prizes})
    db.add_draw({"date": "2026-11-01", "prizes": PRIZES})
    assert [p["id"] for p in service.score_pending()] == [three]
    assert db.picks(digits=2)[0]["result_draw"] is None
    assert db.unchecked_picks()[0]["id"] == two


def test_sync_repairs_latest_missing_last2_without_announcing_or_rewriting_results():
    old_prizes = {k: v for k, v in PRIZES.items() if k != "last2"}
    db.add_draw({"date": "2026-10-16", "prizes": old_prizes})
    saved = db.add_pick("manual", ["701"], {}, "2026-10-01")
    historical_result = {"hits": [], "exact_hits": 0, "expected": 0.005}
    db.set_result(saved, "2026-10-16", historical_result)

    def latest():
        return {"date": "2026-10-16", "prizes": PRIZES}

    assert run(1, latest, lambda _: None, today="2026-10-17") is None
    assert db.draws()[0]["prizes"]["last2"] == ["70"]
    assert db.picks()[0]["result"] == historical_result


def test_sync_repairs_missing_last2_in_requested_history_without_announcing():
    old_prizes = {k: v for k, v in PRIZES.items() if k != "last2"}
    db.add_draw({"date": "2026-10-01", "prizes": old_prizes})
    db.add_draw({"date": "2026-10-16", "prizes": PRIZES})
    calls = []

    def on(day):
        calls.append(day.isoformat())
        return ({"date": day.isoformat(), "prizes": PRIZES}
                if day.isoformat() == "2026-10-01" else None)

    def latest():
        return {"date": "2026-10-16", "prizes": PRIZES}

    assert run(2, latest, on, today="2026-10-17") is None
    assert calls.count("2026-10-01") == 1
    assert db.draws()[1]["prizes"]["last2"] == ["70"]


def test_sync_never_repairs_cached_draw_from_partial_result():
    old_prizes = {k: v for k, v in PRIZES.items() if k != "last2"}
    db.add_draw({"date": "2026-10-16", "prizes": old_prizes})
    partial = {**PRIZES, "fifth": []}

    def latest():
        return {"date": "2026-10-16", "prizes": partial}

    assert run(1, latest, lambda _: {"date": "2026-10-16", "prizes": partial},
               today="2026-10-17") is None
    assert db.draws()[0]["prizes"] == old_prizes



def test_make_two_digit_pick_skips_cached_draws_without_last2():
    old_prizes = {k: v for k, v in PRIZES.items() if k != "last2"}
    db.add_draw({"date": "2026-10-01", "prizes": PRIZES})
    db.add_draw({"date": "2026-10-16", "prizes": old_prizes})
    p = service.make_pick(1, 5, "last2", False, digits=2)
    assert p["draws_used"] == ["2026-10-01"]
    assert p["excluded"] == ["70"]


def test_sync_repairs_older_pending_target_then_scores_that_draw():
    old_prizes = {k: v for k, v in PRIZES.items() if k != "last2"}
    db.add_draw({"date": "2026-10-16", "prizes": old_prizes})
    db.add_draw({"date": "2026-11-01", "prizes": PRIZES})
    saved = db.add_pick("manual", ["70"], {"digits": 2}, "2026-10-01")
    calls = []

    def on(day):
        calls.append(day.isoformat())
        return {"date": day.isoformat(), "prizes": PRIZES}

    def latest():
        return {"date": "2026-11-01", "prizes": PRIZES}

    assert run(1, latest, on, today="2026-11-02") is None
    assert calls == ["2026-10-16"]
    scored = service.score_pending()
    assert len(scored) == 1 and scored[0]["id"] == saved
    assert scored[0]["result_draw"] == "2026-10-16"
    assert scored[0]["result"]["exact_hits"] == 1
    assert service.score_pending() == []


def test_sync_repair_ignores_wrong_date_and_preserves_retryable_cached_row():
    old_prizes = {k: v for k, v in PRIZES.items() if k != "last2"}
    db.add_draw({"date": "2026-10-16", "prizes": old_prizes})
    db.add_draw({"date": "2026-11-01", "prizes": PRIZES})

    def latest():
        return {"date": "2026-11-01", "prizes": PRIZES}

    def on(day):
        return ({"date": "2026-10-01", "prizes": PRIZES}
                if day.isoformat() == "2026-10-16" else None)

    assert run(2, latest, on, today="2026-11-02") is None
    assert db.draws()[1]["prizes"] == old_prizes
    assert "2026-10-16" not in db.nodraw_dates()
    assert db.draw_dates() == {"2026-10-16", "2026-11-01"}


def test_repair_only_adds_last2_and_does_not_replace_known_prizes_or_valid_last2():
    cached_prizes = {**PRIZES, "first": ["123456"]}
    cached_prizes.pop("last2")
    db.add_draw({"date": "2026-10-16", "prizes": cached_prizes})
    assert db.repair_last2({"date": "2026-10-16", "prizes": PRIZES})
    assert db.draws()[0]["prizes"]["first"] == ["123456"]
    assert db.draws()[0]["prizes"]["last2"] == ["70"]
    assert not db.repair_last2({"date": "2026-10-16", "prizes": {**PRIZES, "last2": ["07"]}})
    assert db.draws()[0]["prizes"]["last2"] == ["70"]
    assert not db.repair_last2({"date": "2026-10-01", "prizes": PRIZES})
    assert db.draw_dates() == {"2026-10-16"}
