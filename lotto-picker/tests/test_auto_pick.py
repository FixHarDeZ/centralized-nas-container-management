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


def test_two_digit_auto_is_opt_in_and_independent_of_three(env):
    sent, at = env
    db.put("settings", {**db.settings(), "notify": False})
    db.put("settings_2", {**db.settings(2), "notify": True})
    at("2026-10-15")
    main.auto_pick()
    main.auto_pick()
    assert len(sent) == 1 and "2 ตัว" in sent[0]
    picks = db.picks()
    assert len(picks) == 1 and picks[0]["settings"]["digits"] == 2
    assert all(len(n) == 2 for n in picks[0]["numbers"])
    assert (
        db.get("auto_pick_target_2") == "2026-10-16"
        and db.get("auto_pick_target") is None
    )


def test_legacy_auto_guard_skips_three_but_does_not_block_two(env):
    sent, at = env
    db.put("auto_pick_target", "2026-10-16")
    db.put("settings_2", {**db.settings(2), "notify": True})
    at("2026-10-15")
    main.auto_pick()
    assert len(sent) == 1 and "2 ตัว" in sent[0]
    assert db.picks()[0]["settings"]["digits"] == 2


def test_both_auto_modes_generate_once_with_distinct_guards(env):
    sent, at = env
    db.put("settings_2", {**db.settings(2), "notify": True})
    at("2026-10-15")
    main.auto_pick()
    main.auto_pick()
    assert len(sent) == 2
    assert {p["settings"]["digits"] for p in db.picks()} == {2, 3}
    assert db.get("auto_pick_target") == db.get("auto_pick_target_2") == "2026-10-16"


def test_poll_notifies_only_enabled_mode_with_its_own_picks_and_stats(env, monkeypatch):
    sent, _ = env
    db.put("settings", {**db.settings(), "notify": False})
    db.put("settings_2", {**db.settings(2), "notify": True})
    two = db.add_pick("manual", ["70"], {"digits": 2}, "2026-09-16")
    db.add_pick("manual", ["701"], {"digits": 3}, "2026-09-16")
    monkeypatch.setattr(main, "_sync", lambda: {"date": "2026-10-01", "prizes": PRIZES})
    monkeypatch.setattr(main.insight, "start", lambda *a, **k: None)
    db.add_draw({"date": "2026-10-01", "prizes": PRIZES})
    main.poll_results()
    # the result message, then the separate win alert — both 2-digit only
    assert len(sent) == 2 and "2 ตัว" in sent[0]
    assert "✅70" in sent[0] and "✅701" not in sent[0]
    assert sent[1].startswith("🎉") and "<b>70</b>" in sent[1] and "701" not in sent[1]
    assert db.picks(digits=2)[0]["id"] == two


def test_concurrent_auto_invocations_do_not_duplicate_either_mode(env):
    from concurrent.futures import ThreadPoolExecutor

    sent, at = env
    db.put("settings_2", {**db.settings(2), "notify": True})
    at("2026-10-15")
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: main.auto_pick(), range(2)))
    assert len(sent) == 2 and len(db.picks()) == 2
