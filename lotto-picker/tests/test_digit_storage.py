import json

import pytest
from app import db


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "lotto.db")
    db.init()


def test_settings_profiles_preserve_legacy_three_defaults_and_start_two_off():
    db.put("settings", {"draws": 7, "notify": True})
    assert db.settings()["digits"] == 3
    assert db.settings()["draws"] == 7
    assert db.settings()["scope"] == "all"
    assert db.settings(2) == {
        "draws": 2, "picks": 5, "scope": "last2", "permute": False,
        "notify": False, "digits": 2, "style": "random", "stat_window": 0,
    }
    db.put("settings_2", {"draws": 4, "notify": True, "permute": True})
    assert db.settings(2)["draws"] == 4
    assert db.settings(2)["notify"] is True
    assert db.settings()["draws"] == 7
    assert db.get("settings") == {"draws": 7, "notify": True}


def test_history_filters_mode_before_limit_and_decodes_legacy_without_rewrite():
    legacy = db.add_pick("manual", ["007"], {}, "2026-10-01")
    modern3 = db.add_pick("manual", ["123"], {"digits": 3}, "2026-10-01")
    for i in range(60):
        db.add_pick("manual", [f"{i:02}"], {"digits": 2}, "2026-10-01")
    rows = db.picks(limit=2, digits=3)
    assert [p["id"] for p in rows] == [modern3, legacy]
    assert all(p["settings"]["digits"] == 3 for p in rows)
    assert len(db.picks(digits=2)) == 50
    assert len(db.unchecked_picks()) == 62
    with db.conn() as c:
        raw = c.execute("SELECT settings FROM picks WHERE id = ?", (legacy,)).fetchone()[0]
    assert json.loads(raw) == {}


def test_checked_picks_filter_mode_and_keep_legacy_results():
    old = db.add_pick("manual", ["007"], {}, "2026-10-01")
    two = db.add_pick("manual", ["07"], {"digits": 2}, "2026-10-01")
    result = {"hits": [], "exact_hits": 0, "expected": 0.005}
    for pid in (old, two):
        db.set_result(pid, "2026-10-16", result)
    assert [p["id"] for p in db.checked_picks(3)] == [old]
    assert [p["id"] for p in db.checked_picks(2)] == [two]
    assert len(db.checked_picks()) == 2
    assert db.checked_picks(3)[0]["result"] == result
