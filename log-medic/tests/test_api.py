import os
import tempfile
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmpdir)
    import importlib
    import app.db as db_module
    importlib.reload(db_module)

    import app.main as main_module
    importlib.reload(main_module)
    main_module.app.state.db_path = os.path.join(tmpdir, "test.db")
    main_module.app.state.docker_client = MagicMock(containers=MagicMock(list=MagicMock(return_value=[])))

    with TestClient(main_module.app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_containers_crud_flow(client):
    resp = client.post(
        "/api/containers",
        json={"name": "c1", "repo": None, "subdir": None, "maturity": "dev", "notify_only": False},
    )
    assert resp.status_code == 200

    resp = client.get("/api/containers")
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json() if "name" in c]
    assert "c1" in names

    resp = client.patch("/api/containers/c1", json={"maturity": "staging"})
    assert resp.status_code == 200
    assert resp.json()["maturity"] == "staging"

    resp = client.delete("/api/containers/c1")
    assert resp.status_code == 200


def test_events_list(client):
    resp = client.get("/api/events?limit=10")
    assert resp.status_code == 200
    assert resp.json() == []


def test_watcher_pause_resume(client):
    resp = client.post("/api/watcher/pause")
    assert resp.status_code == 200
    resp = client.post("/api/watcher/resume")
    assert resp.status_code == 200


def test_notify_test_success(client, monkeypatch):
    monkeypatch.setattr("app.api.notify_test.notify", lambda text: [])
    resp = client.post("/api/notify/test")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_notify_test_failure(client, monkeypatch):
    monkeypatch.setattr("app.api.notify_test.notify", lambda text: ["send failed"])
    resp = client.post("/api/notify/test")
    assert resp.status_code == 502
    assert "errors" in resp.json()["detail"]
