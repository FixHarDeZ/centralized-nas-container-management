"""Per-user data: picks, ledger and settings follow the nginx basic-auth user."""

import json
import sqlite3
from pathlib import Path

import pytest
from app import db, lotto, main, messages, service
from fastapi.testclient import TestClient

FIX = Path(__file__).parent / "fixtures"
PRIZES = lotto.parse_prizes(json.loads((FIX / "latest_2026-10-01.json").read_text())["response"]["data"])
ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DATA_DIR", tmp_path)
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "lotto.db")
    db.init()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "_scheduler", type("S", (), {
        "add_job": lambda *a, **k: None, "start": lambda *a: None, "shutdown": lambda *a, **k: None,
    })())
    monkeypatch.setattr(main.threading, "Thread", lambda *a, **k: type("T", (), {"start": lambda s: None})())
    monkeypatch.setattr(service, "sync", lambda *a, **k: None)
    with TestClient(main.app) as c:
        yield c


def as_user(name):
    return {"X-Remote-User": name}


def save(client, user, numbers=("123",)):
    body = {"numbers": list(numbers), "settings": {"digits": 3, "draws": 2, "picks": 5}}
    return client.post("/api/picks", json=body, headers=as_user(user)).json()["id"]


def test_picks_are_private_per_user(client):
    mine = save(client, "fixhardez", ["111"])
    theirs = save(client, "Pookzii", ["222"])
    assert [p["numbers"] for p in client.get("/api/picks", headers=as_user("fixhardez")).json()] == [["111"]]
    assert [p["numbers"] for p in client.get("/api/picks", headers=as_user("Pookzii")).json()] == [["222"]]
    # cannot delete someone else's pick
    assert client.delete(f"/api/picks/{mine}", headers=as_user("Pookzii")).status_code == 404
    assert client.delete(f"/api/picks/{theirs}", headers=as_user("Pookzii")).status_code == 204
    assert len(client.get("/api/picks", headers=as_user("fixhardez")).json()) == 1


def test_no_header_acts_as_owner(client):
    save(client, db.OWNER, ["333"])
    assert client.get("/api/me").json() == {"user": db.OWNER, "owner": True}
    assert len(client.get("/api/picks").json()) == 1
    assert client.get("/api/me", headers=as_user("Pookzii")).json() == {"user": "Pookzii", "owner": False}


def test_ledger_is_private_per_user(client):
    entry = {"draw_date": "2026-10-01", "cost": 80}
    a = client.post("/api/ledger", json=entry, headers=as_user("fixhardez")).json()["id"]
    client.post("/api/ledger", json={**entry, "cost": 160}, headers=as_user("Pookzii"))
    assert client.get("/api/ledger", headers=as_user("fixhardez")).json()["summary"]["entries"] == 1
    pk = client.get("/api/ledger", headers=as_user("Pookzii")).json()
    assert pk["summary"]["entries"] == 1 and pk["entries"][0]["cost"] == 160
    assert client.put(f"/api/ledger/{a}", json=entry, headers=as_user("Pookzii")).status_code == 404
    assert client.delete(f"/api/ledger/{a}", headers=as_user("Pookzii")).status_code == 404


def test_settings_per_user_and_notify_owner_only(client):
    body = {"digits": 3, "draws": 7, "picks": 9, "notify": True}
    other = client.put("/api/settings", json=body, headers=as_user("Pookzii")).json()
    assert other["draws"] == 7 and other["notify"] is False
    owner = client.get("/api/settings", headers=as_user("fixhardez")).json()
    assert owner["draws"] == 2 and owner["notify"] is True
    assert db.get("settings:Pookzii")["draws"] == 7
    assert db.get("settings") is None  # owner's legacy key untouched


def test_stats_per_user(client):
    db.add_draw({"date": "2026-09-16", "prizes": PRIZES})
    db.add_pick("manual", [PRIZES["last3b"][0]], {"digits": 3}, "2026-09-16", user="Pookzii")
    db.add_draw({"date": "2026-10-01", "prizes": PRIZES})
    service.score_pending()
    assert client.get("/api/stats", headers=as_user("Pookzii")).json()["exact_hits"] == 1
    assert client.get("/api/stats", headers=as_user("fixhardez")).json()["picks"] == 0


def test_result_message_only_carries_owner_picks(monkeypatch):
    sent = []
    monkeypatch.setattr(messages, "notifier", lambda: type("N", (), {"send": lambda s, t: sent.append(t)})())
    monkeypatch.setattr(main.insight, "start", lambda *a, **k: None)
    db.add_draw({"date": "2026-09-16", "prizes": PRIZES})
    db.add_pick("manual", ["999"], {"digits": 3}, "2026-09-16", user="Pookzii")
    db.add_pick("manual", ["888"], {"digits": 3}, "2026-09-16", user=db.OWNER)
    fresh = {"date": "2026-10-01", "prizes": PRIZES}
    db.add_draw(fresh)
    monkeypatch.setattr(main, "_sync", lambda: fresh)
    main.poll_results()
    text = "\n".join(sent)
    assert "888" in text and "999" not in text


def test_legacy_rows_migrate_to_owner(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE picks (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL, numbers TEXT NOT NULL, settings TEXT NOT NULL,
            based_on TEXT, result_draw TEXT, result TEXT);
        INSERT INTO picks (source, numbers, settings) VALUES ('manual', '["123"]', '{}');
    """)
    old.commit()
    old.close()
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init()
    db.init()  # idempotent
    assert [p["numbers"] for p in db.picks(user=db.OWNER)] == [["123"]]
    assert db.picks(user="Pookzii") == []


def test_nginx_overwrites_remote_user_header():
    conf = (ROOT / "nginx" / "nginx.conf").read_text()
    assert "proxy_set_header    X-Remote-User     $remote_user;" in conf
