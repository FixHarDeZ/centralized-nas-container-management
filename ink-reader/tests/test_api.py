import os

import pytest
from fastapi.testclient import TestClient

import db


@pytest.fixture
def client(data_dir, monkeypatch):
    monkeypatch.setenv("INK_DISABLE_SCHEDULER", "1")
    import main
    with TestClient(main.app) as c:
        yield c


def _seed():
    tid = db.add_title("s1", "Story One", "a,b", 2, 100, "u")
    open(db.cbz_path(tid), "wb").write(b"cbzdata")
    open(db.cover_path(tid), "wb").write(b"jpgdata")
    return tid


def test_titles_list(client):
    _seed()
    r = client.get("/api/titles", params={"status": "new"})
    assert r.status_code == 200
    assert r.json()["titles"][0]["slug"] == "s1"


def test_keep_and_delete(client):
    tid = _seed()
    assert client.post(f"/api/titles/{tid}/keep").json() == {"ok": True}
    assert db.get_title(tid)["status"] == "kept"
    assert client.post(f"/api/titles/{tid}/delete").json() == {"ok": True}
    assert db.get_title(tid)["status"] == "deleted"
    assert not os.path.exists(db.cbz_path(tid))
    assert client.post("/api/titles/999/keep").status_code == 404


def test_file_and_cover(client):
    tid = _seed()
    r = client.get(f"/files/{tid}.cbz")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/vnd.comicbook+zip"
    assert r.content == b"cbzdata"
    assert client.get(f"/covers/{tid}.jpg").content == b"jpgdata"
    assert client.get("/files/999.cbz").status_code == 404


def test_opds_routes(client):
    _seed()
    for path in ("/opds", "/opds/new", "/opds/kept"):
        r = client.get(path)
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/atom+xml")
    assert b"s1" not in client.get("/opds/kept").content


def test_status(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    assert "stats" in r.json()
