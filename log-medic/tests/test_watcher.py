import os
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.watcher import RingBuffer, fingerprint, normalize_message


def test_normalize_strips_timestamp():
    line = "2026-07-04T18:03:12.481Z ERROR db timeout"
    assert "2026-07-04" not in normalize_message(line)


def test_normalize_strips_uuid():
    line = "ERROR request 550e8400-e29b-41d4-a716-446655440000 failed"
    assert "550e8400" not in normalize_message(line)


def test_normalize_strips_hex_and_numbers_and_paths():
    line = "ERROR at 0xdeadbeef reading /volume2/docker/foo/bar line 42"
    normalized = normalize_message(line)
    assert "0xdeadbeef" not in normalized
    assert "/volume2/docker/foo/bar" not in normalized
    assert "42" not in normalized


def test_fingerprint_same_for_normalized_equivalent_lines():
    a = fingerprint("torrentwatch", "2026-07-04T18:00:00Z ERROR conn 42 failed")
    b = fingerprint("torrentwatch", "2026-07-04T19:30:00Z ERROR conn 99 failed")
    assert a == b
    assert len(a) == 12


def test_fingerprint_differs_by_container():
    a = fingerprint("torrentwatch", "ERROR boom")
    b = fingerprint("news-feed", "ERROR boom")
    assert a != b


def test_ring_buffer_capture():
    rb = RingBuffer(before=3, after=2)
    for line in ["l1", "l2", "l3", "l4"]:
        rb.push(line)
    excerpt = rb.capture("TRIGGER", ["after1", "after2", "after3"])
    assert excerpt.splitlines() == ["l2", "l3", "l4", "TRIGGER", "after1", "after2"]


@pytest.fixture
def conn(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmpdir)
    import importlib

    import app.db as db_module
    importlib.reload(db_module)
    c = db_module.get_conn(os.path.join(tmpdir, "test.db"))
    db_module.init_db(c)
    return c


def test_process_event_notify_only_skips_gates(conn, monkeypatch):
    import app.watcher as watcher
    notify_mock = MagicMock(return_value=["telegram"])
    monkeypatch.setattr(watcher, "notify", notify_mock)
    row = {"name": "jellyfin", "notify_only": 1, "maturity": "dev", "repo": None, "subdir": None}
    watcher.process_event(conn, row, "fp1", "excerpt", "ERROR boom", datetime.now(UTC))
    notify_mock.assert_called_once()
    import app.db as db
    events = db.get_recent_events(conn)
    assert events[0]["status"] == "notified"


def test_process_event_dev_maturity_logs_only_no_calls(conn, monkeypatch):
    import app.watcher as watcher
    notify_mock = MagicMock()
    analyze_mock = MagicMock()
    monkeypatch.setattr(watcher, "notify", notify_mock)
    monkeypatch.setattr(watcher, "analyzer", MagicMock(analyze=analyze_mock))
    row = {"name": "x", "notify_only": 0, "maturity": "dev", "repo": None, "subdir": None}
    watcher.process_event(conn, row, "fp1", "excerpt", "ERROR boom", datetime.now(UTC))
    notify_mock.assert_not_called()
    analyze_mock.assert_not_called()
    import app.db as db
    events = db.get_recent_events(conn)
    assert events[0]["status"] == "new"


def test_process_event_gated_records_reason(conn, monkeypatch):
    import app.watcher as watcher
    monkeypatch.setattr(watcher.gate, "evaluate", lambda *a, **k: "grace_period")
    notify_mock = MagicMock()
    monkeypatch.setattr(watcher, "notify", notify_mock)
    row = {"name": "x", "notify_only": 0, "maturity": "staging", "repo": "/workspaces/r", "subdir": "sub"}
    watcher.process_event(conn, row, "fp1", "excerpt", "ERROR boom", datetime.now(UTC))
    import app.db as db
    events = db.get_recent_events(conn)
    assert events[0]["status"] == "gated"
    assert events[0]["gate_reason"] == "grace_period"
    notify_mock.assert_not_called()  # grace_period is silent, unlike quota/dirty_repo


def test_process_event_proceeds_to_analyze_and_notifies(conn, monkeypatch):
    import app.watcher as watcher
    monkeypatch.setattr(watcher.gate, "evaluate", lambda *a, **k: None)
    monkeypatch.setattr(watcher.gate, "maybe_trip_breaker", lambda *a, **k: None)
    notify_mock = MagicMock()
    monkeypatch.setattr(watcher, "notify", notify_mock)
    monkeypatch.setattr(watcher.analyzer, "analyze", lambda *a, **k: {"text": "root cause X"})
    monkeypatch.setenv("ENABLE_FIX_RUNNER", "false")
    row = {"name": "x", "notify_only": 0, "maturity": "staging", "repo": "/workspaces/r", "subdir": "sub"}
    watcher.process_event(conn, row, "fp1", "excerpt", "ERROR boom", datetime.now(UTC))
    import app.db as db
    events = db.get_recent_events(conn)
    assert events[0]["status"] == "analyzed"
    assert events[0]["analysis"] == "root cause X"
    assert notify_mock.called


def test_watcher_manager_reload_starts_and_cancels_tasks(conn):
    import asyncio

    import app.watcher as watcher
    import app.db as db

    async def run():
        mgr = watcher.WatcherManager(docker_client=MagicMock())
        db.upsert_monitored_container(conn, "c1", None, None, "dev", 1, 0, None)
        await mgr.reload(conn)
        assert "c1" in mgr._tasks
        db.delete_monitored_container(conn, "c1")
        await mgr.reload(conn)
        assert "c1" not in mgr._tasks
        for t in list(mgr._tasks.values()):
            t.cancel()

    asyncio.run(run())
