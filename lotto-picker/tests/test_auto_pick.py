import datetime as dt
import json
from pathlib import Path

import pytest
from app import db, lotto, main, service

FIX = Path(__file__).parent / "fixtures"
PRIZES = lotto.parse_prizes(
    json.loads((FIX / "latest_2026-10-01.json").read_text())["response"]["data"]
)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "lotto.db")
    db.init()
    db.add_draw({"date": "2026-10-01", "prizes": PRIZES})
    db.put("latest_seen", "2026-10-01")
    monkeypatch.setattr(main, "_sync", lambda: None)
    sent = []

    class FakeNotifier:
        def send(self, text):
            sent.append(text)
            return ["telegram"]

    monkeypatch.setattr(main.messages, "notifier", lambda: FakeNotifier())

    def at(day):
        monkeypatch.setattr(main, "_today", lambda: dt.date.fromisoformat(day))

    return sent, at


def test_fires_once_on_the_day_before(env):
    sent, at = env
    at("2026-10-14")
    main.auto_pick()
    assert sent == []  # two days before
    at("2026-10-15")
    main.auto_pick()
    main.auto_pick()  # restart / rerun same evening
    assert len(sent) == 1
    picks = db.picks()
    assert len(picks) == 1 and picks[0]["source"] == "auto"
    assert picks[0]["based_on"] == "2026-10-01"
    assert db.get("auto_pick_target") == "2026-10-16"


def test_skips_when_notify_off(env):
    sent, at = env
    db.put("settings", {**db.settings(), "notify": False})
    at("2026-10-15")
    main.auto_pick()
    assert sent == [] and db.picks() == []


def test_skips_when_pool_empty(env, monkeypatch):
    sent, at = env
    monkeypatch.setattr(lotto, "ALL_THREE", set())
    at("2026-10-15")
    main.auto_pick()
    assert sent == [] and db.picks() == []
    assert db.get("auto_pick_target") is None


def test_based_on_follows_in_progress_draw(env):
    db.put("latest_seen", "2026-10-16")
    assert service.based_on() == "2026-10-16"
