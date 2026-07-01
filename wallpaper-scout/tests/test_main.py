import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, mocker):
    monkeypatch.setenv("DATA_DIR", tempfile.mkdtemp())
    monkeypatch.setenv("PHOTOS_ROOT", tempfile.mkdtemp())
    mocker.patch("app.scheduler.llm.expand_query", return_value=["stub"])
    import importlib
    import app.db as db_module
    import app.scheduler as scheduler_module
    import app.main as main_module
    importlib.reload(db_module)
    importlib.reload(scheduler_module)
    importlib.reload(main_module)
    with TestClient(main_module.app) as c:
        yield c


def test_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_list_topic(client):
    resp = client.post(
        "/api/topics",
        json={"query": "IU", "purposes": ["mobile", "pc"], "frequency_per_day": 2, "max_new_per_cycle": 5},
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["query"] == "IU"
    assert created["purposes"] == ["mobile", "pc"]

    listed = client.get("/api/topics").json()
    assert len(listed) == 1
    assert listed[0]["query"] == "IU"
    assert listed[0]["downloaded_today"] == 0


def test_patch_topic(client):
    created = client.post(
        "/api/topics",
        json={"query": "IU", "purposes": ["mobile"], "frequency_per_day": 1, "max_new_per_cycle": 5},
    ).json()

    resp = client.patch(f"/api/topics/{created['id']}", json={"enabled": False, "frequency_per_day": 4})
    assert resp.status_code == 200
    assert resp.json()["enabled"] == 0
    assert resp.json()["frequency_per_day"] == 4


def test_patch_topic_purposes(client):
    created = client.post(
        "/api/topics",
        json={"query": "IU", "purposes": ["mobile"], "frequency_per_day": 1, "max_new_per_cycle": 5},
    ).json()

    resp = client.patch(f"/api/topics/{created['id']}", json={"purposes": ["laptop"]})
    assert resp.status_code == 200
    assert resp.json()["purposes"] == ["laptop"]


def test_delete_topic(client):
    created = client.post(
        "/api/topics",
        json={"query": "IU", "purposes": ["mobile"], "frequency_per_day": 1, "max_new_per_cycle": 5},
    ).json()

    resp = client.delete(f"/api/topics/{created['id']}")
    assert resp.status_code == 204
    assert client.get("/api/topics").json() == []


def test_create_topic_schedules_job(client, mocker):
    mock_schedule = mocker.patch("app.main.scheduler.schedule_topic")
    client.post(
        "/api/topics",
        json={"query": "IU", "purposes": ["mobile"], "frequency_per_day": 1, "max_new_per_cycle": 5},
    )
    mock_schedule.assert_called_once()


def test_patch_topic_disable_unschedules_job(client, mocker):
    created = client.post(
        "/api/topics",
        json={"query": "IU", "purposes": ["mobile"], "frequency_per_day": 1, "max_new_per_cycle": 5},
    ).json()

    mock_unschedule = mocker.patch("app.main.scheduler.unschedule_topic")
    client.patch(f"/api/topics/{created['id']}", json={"enabled": False})
    mock_unschedule.assert_called_once_with(mocker.ANY, created["id"])


def test_delete_topic_unschedules_job(client, mocker):
    created = client.post(
        "/api/topics",
        json={"query": "IU", "purposes": ["mobile"], "frequency_per_day": 1, "max_new_per_cycle": 5},
    ).json()

    mock_unschedule = mocker.patch("app.main.scheduler.unschedule_topic")
    client.delete(f"/api/topics/{created['id']}")
    mock_unschedule.assert_called_once_with(mocker.ANY, created["id"])


def test_patch_nonexistent_topic_404(client):
    resp = client.patch("/api/topics/99999", json={"enabled": False})
    assert resp.status_code == 404


def test_delete_nonexistent_topic_204(client):
    # pinning current behavior: no existence check on DELETE, so this is a
    # silent no-op 204 rather than a 404 (see main.py delete_topic)
    resp = client.delete("/api/topics/99999")
    assert resp.status_code == 204


def test_get_dashboard_static_index(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


def test_run_topic_now_returns_downloaded_count(client, mocker):
    created = client.post(
        "/api/topics",
        json={"query": "IU", "purposes": ["mobile"], "frequency_per_day": 1, "max_new_per_cycle": 5},
    ).json()

    mock_run = mocker.patch("app.main.scheduler.run_topic_cycle", return_value=3)
    resp = client.post(f"/api/topics/{created['id']}/run")
    assert resp.status_code == 200
    assert resp.json() == {"downloaded": 3}
    mock_run.assert_called_once_with(created["id"])


def test_run_topic_now_reports_failure(client, mocker):
    created = client.post(
        "/api/topics",
        json={"query": "IU", "purposes": ["mobile"], "frequency_per_day": 1, "max_new_per_cycle": 5},
    ).json()

    mocker.patch("app.main.scheduler.run_topic_cycle", side_effect=RuntimeError("wallhaven down"))
    resp = client.post(f"/api/topics/{created['id']}/run")
    assert resp.status_code == 502
    assert "wallhaven down" in resp.json()["detail"]


def test_run_nonexistent_topic_404(client):
    resp = client.post("/api/topics/99999/run")
    assert resp.status_code == 404
