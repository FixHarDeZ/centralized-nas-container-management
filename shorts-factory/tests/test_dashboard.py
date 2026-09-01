"""The dashboard reads and only reads.

`DATA_DIR` is read at import time by app.manifest/app.history/app.render, so the
environment is set before the import happens — hence the fixture ordering and
the reloads below.
"""
import importlib
import json
import os
from statistics import median

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    """A /data that looks like a live one: two Manifests, state, say."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    clips = tmp_path / "clips"
    clips.mkdir()

    (clips / "20260801-120000-000.json").write_text(json.dumps({
        "id": "20260801-120000-000",
        "created_at": "2026-08-01T12:00:00",
        "topic": "ทำไม container กิน RAM",
        "variant": "shock_number",
        "explore": False,
        "outcome": "rendered",
        "published": True,
        "video_id": "vid1",
        "scripts": [{"at": "2026-08-01T12:02:00", "script": {
            "title": "RAM หายไปไหน", "category": "devops",
            "cards": [{"narration": "การ์ดหนึ่ง", "spoken": "การ์ดหนึ่ง"}],
        }}],
        "snapshots": [{"date": "2026-08-08", "age_days": 7, "views": 182, "percent": 41.2}],
        "render": {"duration": 47.3, "cards": [{"start": 0.0}]},
    }, ensure_ascii=False), encoding="utf-8")

    (clips / "20260802-120000-000.json").write_text(json.dumps({
        "id": "20260802-120000-000",
        "created_at": "2026-08-02T12:00:00",
        "topic": "หัวข้อที่ถูกทิ้ง",
        "variant": "question",
        "outcome": "discarded",
        "scripts": [],
    }, ensure_ascii=False), encoding="utf-8")

    (tmp_path / "state.json").write_text(json.dumps(
        {"mode": "idle", "offset": 42, "last_snapshot": "2026-08-08"}), encoding="utf-8")
    (tmp_path / "say.json").write_text(json.dumps(
        {"ทีเอไอ": "ไทย"}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "history.json").write_text(json.dumps([
        {"video_id": "vid1", "title": "RAM หายไปไหน", "topic": "ทำไม container กิน RAM",
         "uploaded_at": "2026-08-01T13:00:00"}]), encoding="utf-8")
    return tmp_path


@pytest.fixture()
def client(data_dir):
    """A client whose modules were imported *after* DATA_DIR was set."""
    from app import history, manifest
    for module in (manifest, history):
        importlib.reload(module)
    from app import dashboard
    importlib.reload(dashboard)
    return TestClient(dashboard.app)


def test_healthz(client):
    reply = client.get("/healthz")
    assert reply.status_code == 200
    assert reply.json() == {"ok": True}


def test_no_route_can_write(client):
    """Read-only is a property of the code, not only of the :ro mount."""
    from app import dashboard
    for route in dashboard.app.routes:
        allowed = getattr(route, "methods", set()) or set()
        assert allowed <= {"GET", "HEAD"}, f"{route.path} allows {allowed}"


def test_clips_page_lists_newest_first(client):
    reply = client.get("/")
    assert reply.status_code == 200
    body = reply.text
    assert "หัวข้อที่ถูกทิ้ง" in body
    assert "ทำไม container กิน RAM" in body
    assert body.index("หัวข้อที่ถูกทิ้ง") < body.index("ทำไม container กิน RAM")


def test_clips_page_shows_day7_numbers(client):
    body = client.get("/").text
    assert "182" in body      # views from the day-7 snapshot
    assert "41.2" in body     # its retention percent


def test_clips_page_survives_a_broken_manifest(client, data_dir):
    (data_dir / "clips" / "broken.json").write_text("{ not json", encoding="utf-8")
    assert client.get("/").status_code == 200


def test_clip_page_shows_every_draft_and_the_snapshots(client):
    body = client.get("/clip/20260801-120000-000").text
    assert "RAM หายไปไหน" in body       # the draft's title
    assert "การ์ดหนึ่ง" in body          # the card narration
    assert "182" in body                # the snapshot row
    assert "vid1" in body               # the YouTube link


def test_clip_page_of_a_drafting_manifest_is_not_an_error(client):
    assert client.get("/clip/20260802-120000-000").status_code == 200


def test_unknown_clip_is_a_404_page_not_a_traceback(client):
    reply = client.get("/clip/nope")
    assert reply.status_code == 404
    assert "ไม่พบ" in reply.text


def test_experiment_page_shows_both_arms_and_a_verdict(client):
    from app import experiment
    body = client.get("/experiment").text
    for name in experiment.VARIANTS:
        assert name in body
    assert "สรุปไม่ได้" in body     # two clips is far below the threshold


def test_now_page_reads_state_and_say(client):
    body = client.get("/now").text
    assert "idle" in body
    assert "ไทย" in body            # the say.json substitution


def test_now_page_without_state_file(client, data_dir):
    (data_dir / "state.json").unlink()
    reply = client.get("/now")
    assert reply.status_code == 200
