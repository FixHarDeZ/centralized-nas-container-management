"""Win alerts (Telegram, owner) and the in-page win banner (every user)."""

import json
from pathlib import Path

import pytest
from app import db, lotto, main, service
from fastapi.testclient import TestClient

FIX = Path(__file__).parent / "fixtures"
PRIZES = lotto.parse_prizes(json.loads((FIX / "latest_2026-10-01.json").read_text())["response"]["data"])
FIRST = PRIZES["first"][0]
BACK3 = PRIZES["last3b"][0]


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "lotto.db")
    db.init()
    sent = []
    monkeypatch.setattr(main.messages, "notifier", lambda: type("N", (), {"send": lambda s, t: sent.append(t)})())
    monkeypatch.setattr(main.insight, "start", lambda *a, **k: None)
    return sent


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "_scheduler", type("S", (), {
        "add_job": lambda *a, **k: None, "start": lambda *a: None, "shutdown": lambda *a, **k: None,
    })())
    monkeypatch.setattr(main.threading, "Thread", lambda *a, **k: type("T", (), {"start": lambda s: None})())
    monkeypatch.setattr(service, "sync", lambda *a, **k: None)
    with TestClient(main.app) as c:
        yield c


def ticket(number, qty=1):
    return {"number": number, "qty": qty}


def test_ledger_win_alerts_once_with_total_even_with_notify_off(env):
    db.put("settings", {**db.settings(), "notify": False})
    db.add_ledger({"draw_date": "2026-10-01", "label": "แผง", "tickets": [ticket(FIRST), ticket("000000")],
                   "cost": 160, "prize": None})
    db.add_draw({"date": "2026-10-01", "prizes": PRIZES})
    main.send_win_alerts()
    assert len(env) == 1
    msg = env[0]
    assert msg.startswith("🎉") and FIRST in msg and "รางวัลที่ 1" in msg and "(แผง)" in msg
    assert "000000" not in msg
    assert f"{lotto.ticket_value(FIRST, PRIZES, {}):,.0f} บาท" in msg
    main.send_win_alerts()
    assert len(env) == 1  # never twice, across polls or restarts (state lives in kv)


LOWER_PRIZES = ("second", "third", "fourth", "fifth", "near1")


@pytest.mark.parametrize("kind", LOWER_PRIZES)
def test_lower_prize_ticket_alerts_with_its_name_and_amount(env, kind):
    number = PRIZES[kind][0]
    db.add_ledger({"draw_date": "2026-10-01", "label": "", "tickets": [ticket(number)], "cost": 80,
                   "prize": None})
    db.add_draw({"date": "2026-10-01", "prizes": PRIZES})
    found = service.wins()
    assert found["tickets"][0]["wins"][0]["kinds"] == [kind]
    assert found["total"] == lotto.PRIZE_AMOUNTS[kind]
    main.send_win_alerts()
    assert len(env) == 1
    assert number in env[0] and main.messages.TICKET_LABEL[kind] in env[0]
    assert f"{lotto.PRIZE_AMOUNTS[kind]:,.0f} บาท" in env[0]


@pytest.mark.parametrize("kind", LOWER_PRIZES)
def test_every_number_of_a_lower_prize_wins_it(kind):
    # the whole list, not just the head: a check that only read [0] would pass above
    for number in PRIZES[kind]:
        assert kind in lotto.ticket_prizes(number, PRIZES), number


@pytest.mark.parametrize("kind", LOWER_PRIZES)
def test_lower_prize_needs_all_six_digits(kind):
    number = PRIZES[kind][0]
    near = next(n for n in (number[:-1] + str((int(number[-1]) + i) % 10) for i in range(1, 10))
                if n not in PRIZES[kind])
    assert kind not in lotto.ticket_prizes(near, PRIZES)


def test_nominal_date_entry_alerts_when_shifted_draw_lands(env):
    db.add_ledger({"draw_date": "2026-01-01", "label": "", "tickets": [ticket("123" + BACK3[-3:], 2)],
                   "cost": 160, "prize": None})
    main.send_win_alerts()
    assert env == []  # no draw yet
    db.add_draw({"date": "2025-12-30", "prizes": PRIZES})
    main.send_win_alerts()
    assert len(env) == 1 and "×2" in env[0] and "เลขท้าย 3 ตัว" in env[0]  # noqa: RUF001


def test_pick_win_follows_mode_notify_and_is_not_replayed(env):
    db.put("settings_2", {**db.settings(2), "notify": False})
    db.add_draw({"date": "2026-09-16", "prizes": PRIZES})
    db.add_pick("manual", [PRIZES["last2"][0]], {"digits": 2}, "2026-09-16")
    db.add_pick("manual", [BACK3], {"digits": 3}, "2026-09-16")
    db.add_draw({"date": "2026-10-01", "prizes": PRIZES})
    service.score_pending()
    main.send_win_alerts()
    assert len(env) == 1
    assert BACK3 in env[0] and "เลข 3 ตัว" in env[0] and "เลข 2 ตัว" not in env[0]
    db.put("settings_2", {**db.settings(2), "notify": True})
    main.send_win_alerts()
    assert len(env) == 1  # the muted 2-digit win was marked, not queued


def test_other_users_never_reach_telegram(env):
    db.add_ledger({"draw_date": "2026-10-01", "label": "", "tickets": [ticket(FIRST)], "cost": 80,
                   "prize": None}, user="Pookzii")
    db.add_draw({"date": "2026-10-01", "prizes": PRIZES})
    main.send_win_alerts()
    assert env == []


def test_entry_recorded_after_result_is_not_pinged(env, client):
    db.add_draw({"date": "2026-10-01", "prizes": PRIZES})
    client.post("/api/ledger", json={"draw_date": "2026-10-01", "cost": 80, "tickets": [ticket(FIRST)]})
    main.send_win_alerts()
    assert env == []
    # someone else's entry does not silence the owner, nor the other way round
    client.post("/api/ledger", json={"draw_date": "2026-10-01", "cost": 80, "tickets": [ticket(BACK3.rjust(6, "0"))]},
                headers={"X-Remote-User": "Pookzii"})
    assert service.wins("Pookzii")["tickets"]


def test_banner_endpoint_per_user_latest_draw_only(client):
    db.add_draw({"date": "2026-09-16", "prizes": PRIZES})
    db.add_ledger({"draw_date": "2026-09-16", "label": "", "tickets": [ticket(FIRST)], "cost": 80, "prize": None},
                  user="Pookzii")
    assert client.get("/api/wins", headers={"X-Remote-User": "Pookzii"}).json()["total"] > 0
    db.add_draw({"date": "2026-10-01", "prizes": {**PRIZES, "first": ["999999"]}})
    db.add_ledger({"draw_date": "2026-10-01", "label": "", "tickets": [ticket(BACK3.rjust(6, "0"))], "cost": 80,
                   "prize": None}, user="Pookzii")
    w = client.get("/api/wins", headers={"X-Remote-User": "Pookzii"}).json()
    assert w["draw"] == "2026-10-01" and len(w["tickets"]) == 1 and w["total"] == 4000
    assert client.get("/api/wins").json()["tickets"] == []  # owner has none
    assert client.get("/api/wins").json()["draw"] == "2026-10-01"


def test_banner_empty_without_draws(client):
    assert client.get("/api/wins").json() == {"draw": None, "picks": [], "tickets": [], "total": 0}
