"""Real API tests against isolated SQLite; lifespan never starts jobs."""

import json
from pathlib import Path

import pytest
from app import db, lotto, main, service
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "lotto.db")
    db.init()
    payload = json.loads(
        (Path(__file__).parent / "fixtures/latest_2026-10-01.json").read_text()
    )
    db.add_draw(
        {
            "date": "2026-10-01",
            "prizes": lotto.parse_prizes(payload["response"]["data"]),
        }
    )
    monkeypatch.setattr(service, "sync", lambda *_args, **_kwargs: None)
    instance = TestClient(main.app)
    yield instance
    instance.close()


def test_legacy_settings_remain_three_digit_and_two_defaults_are_independent(client):
    db.put(
        "settings",
        {
            "draws": 4,
            "picks": 8,
            "scope": "front_back",
            "permute": True,
            "notify": True,
        },
    )
    old = client.get("/api/settings").json()
    assert old["digits"] == 3 and old["draws"] == 4
    two = client.get("/api/settings?digits=2").json()
    assert two == {
        "digits": 2,
        "draws": 2,
        "picks": 5,
        "scope": "last2",
        "permute": False,
        "notify": False,
    }
    two.update(draws=7, picks=10, permute=True, notify=True)
    assert client.put("/api/settings", json=two).json() == two
    assert client.get("/api/settings").json() == old
    assert client.get("/api/settings?digits=2").json() == two


def test_two_digit_generation_uses_only_last_two_official_prize(client):
    response = client.post("/api/pick", json={"digits": 2, "draws": 1, "picks": 50})
    assert response.status_code == 200
    pick = response.json()
    last2 = set(db.draws()[0]["prizes"]["last2"])
    assert pick["settings"]["digits"] == 2 and pick["settings"]["scope"] == "last2"
    assert pick["excluded"] == sorted(last2) and pick["pool_size"] == 100 - len(last2)
    assert len(pick["numbers"]) == 50
    assert all(len(n) == 2 and n.isascii() and n.isdecimal() for n in pick["numbers"])
    assert not set(pick["numbers"]) & last2
    three = client.post("/api/pick", json={"draws": 1, "picks": 5}).json()
    assert three["settings"]["digits"] == 3 and all(
        len(n) == 3 for n in three["numbers"]
    )


@pytest.mark.parametrize("digits", [1, 4, 2.5, "two"])
def test_mode_queries_reject_invalid_values(client, digits):
    for route in ["/api/settings", "/api/picks", "/api/stats"]:
        assert client.get(route, params={"digits": digits}).status_code == 422


@pytest.mark.parametrize(
    ("digits", "numbers"),
    [
        (2, ["007"]),
        (3, ["07"]),
        (2, ["07", "007"]),
        (2, ["๐๗"]),
        (2, ["\uff11\uff12"]),
        (3, ["007\n"]),
    ],
)
def test_save_rejects_mixed_or_non_ascii_widths(client, digits, numbers):
    assert (
        client.post(
            "/api/picks", json={"numbers": numbers, "settings": {"digits": digits}}
        ).status_code
        == 422
    )
    assert db.picks() == []


def test_history_and_stats_are_separate_and_old_saves_default_to_three(client):
    assert (
        client.post("/api/picks", json={"numbers": ["007"], "settings": {}}).status_code
        == 201
    )
    assert (
        client.post(
            "/api/picks", json={"numbers": ["07", "00"], "settings": {"digits": 2}}
        ).status_code
        == 201
    )
    two, three = (
        client.get("/api/picks?digits=2").json(),
        client.get("/api/picks").json(),
    )
    assert len(two) == len(three) == 1
    assert two[0]["numbers"] == ["00", "07"] and two[0]["settings"]["digits"] == 2
    assert three[0]["numbers"] == ["007"] and three[0]["settings"]["digits"] == 3
    db.set_result(
        two[0]["id"],
        "2026-10-16",
        {
            "hits": [{"number": "07", "kinds": ["last2"]}],
            "exact_hits": 1,
            "expected": 0.02,
        },
    )
    db.set_result(
        three[0]["id"], "2026-10-16", {"hits": [], "exact_hits": 0, "expected": 0.005}
    )
    assert client.get("/api/stats?digits=2").json()["exact_hits"] == 1
    assert client.get("/api/stats").json()["exact_hits"] == 0


def test_three_digit_scope_cannot_target_last2(client):
    assert (
        client.post("/api/pick", json={"digits": 3, "scope": "last2"}).status_code
        == 422
    )
    assert (
        client.put("/api/settings", json={"digits": 3, "scope": "last2"}).status_code
        == 422
    )


def test_two_digit_pick_refreshes_legacy_draw_missing_last2(client, monkeypatch):
    complete = db.draws()[0]
    legacy = {**complete["prizes"], "last2": []}
    with db.conn() as connection:
        connection.execute(
            "UPDATE draws SET prizes = ? WHERE date = ?",
            (json.dumps(legacy), complete["date"]),
        )
    calls = []

    def refresh(want, **_kwargs):
        calls.append(want)
        db.repair_last2(complete)

    monkeypatch.setattr(service, "sync", refresh)
    result = client.post("/api/pick", json={"digits": 2, "draws": 1}).json()
    assert calls == [1]
    assert result["draws_used"] == [complete["date"]]
    assert result["excluded"] == complete["prizes"]["last2"]
