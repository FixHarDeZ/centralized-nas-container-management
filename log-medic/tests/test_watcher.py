import os
import tempfile
import threading
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


def test_process_event_infra_verdict_skips_fix_runner_on_stable(conn, monkeypatch):
    import app.watcher as watcher
    monkeypatch.setattr(watcher.gate, "evaluate", lambda *a, **k: None)
    monkeypatch.setattr(watcher.gate, "maybe_trip_breaker", lambda *a, **k: None)
    notify_mock = MagicMock()
    monkeypatch.setattr(watcher, "notify", notify_mock)
    monkeypatch.setattr(watcher.analyzer, "analyze", lambda *a, **k: {"text": "upstream 503", "excerpt": "E", "verdict": "infra"})
    run_fix_mock = MagicMock()
    monkeypatch.setattr(watcher.analyzer, "run_fix", run_fix_mock)
    monkeypatch.setenv("ENABLE_FIX_RUNNER", "true")
    row = {"name": "x", "notify_only": 0, "maturity": "stable", "repo": "/workspaces/r", "subdir": "sub"}
    watcher.process_event(conn, row, "fp1", "excerpt", "ERROR boom", datetime.now(UTC))
    run_fix_mock.assert_not_called()
    import app.db as db
    events = db.get_recent_events(conn)
    assert events[0]["status"] == "analyzed"
    assert events[0]["verdict"] == "infra"
    assert "🌐 infra" in notify_mock.call_args_list[0].args[0]


def test_process_event_code_verdict_runs_fix_on_stable(conn, monkeypatch):
    import app.watcher as watcher
    monkeypatch.setattr(watcher.gate, "evaluate", lambda *a, **k: None)
    monkeypatch.setattr(watcher.gate, "maybe_trip_breaker", lambda *a, **k: None)
    notify_mock = MagicMock()
    monkeypatch.setattr(watcher, "notify", notify_mock)
    monkeypatch.setattr(watcher.analyzer, "analyze", lambda *a, **k: {"text": "bad regex", "excerpt": "E", "verdict": "code"})
    run_fix_mock = MagicMock(return_value="https://github.com/o/r/pull/7")
    monkeypatch.setattr(watcher.analyzer, "run_fix", run_fix_mock)
    monkeypatch.setenv("ENABLE_FIX_RUNNER", "true")
    row = {"name": "x", "notify_only": 0, "maturity": "stable", "repo": "/workspaces/r", "subdir": "sub"}
    watcher.process_event(conn, row, "fp2", "excerpt", "ERROR boom", datetime.now(UTC))
    run_fix_mock.assert_called_once()
    import app.db as db
    events = db.get_recent_events(conn)
    assert events[0]["status"] == "pr_opened"
    assert events[0]["verdict"] == "code"
    assert events[0]["pr_url"] == "https://github.com/o/r/pull/7"
    assert "🐛 code" in notify_mock.call_args_list[0].args[0]


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


def _make_mock_container(image_id: str, started_at_iso: str):
    container = MagicMock()
    container.image.id = image_id
    container.attrs = {"State": {"StartedAt": started_at_iso}}
    container.logs.return_value = [b"ERROR boom"]
    return container


def test_watch_once_preserves_real_started_at_on_first_attach_and_unchanged_image(conn, monkeypatch):
    import app.watcher as watcher

    process_event_mock = MagicMock()
    monkeypatch.setattr(watcher, "process_event", process_event_mock)

    started_at_iso = "2020-01-01T00:00:00.000000000Z"
    real_started_at = watcher._parse_started_at(started_at_iso)

    docker_client = MagicMock()
    row = {"name": "x", "regex_override": None}
    stop_event = threading.Event()
    last_image_id: dict = {}

    # first attach: name not yet in last_image_id -> real StartedAt kept, not reset
    docker_client.containers.get.return_value = _make_mock_container("sha256:abc", started_at_iso)
    watcher._watch_once(docker_client, row, conn, stop_event, last_image_id, {})
    assert process_event_mock.call_args[0][5] == real_started_at

    # second call, same image id already tracked -> still the real one, no spurious reset
    process_event_mock.reset_mock()
    docker_client.containers.get.return_value = _make_mock_container("sha256:abc", started_at_iso)
    watcher._watch_once(docker_client, row, conn, stop_event, last_image_id, {})
    assert process_event_mock.call_args[0][5] == real_started_at


def test_watch_once_resets_started_at_on_genuine_image_change(conn, monkeypatch):
    import app.watcher as watcher

    process_event_mock = MagicMock()
    monkeypatch.setattr(watcher, "process_event", process_event_mock)

    started_at_iso = "2020-01-01T00:00:00.000000000Z"
    docker_client = MagicMock()
    row = {"name": "x", "regex_override": None}
    stop_event = threading.Event()
    last_image_id = {"x": "sha256:abc"}  # already tracked with a different image id

    docker_client.containers.get.return_value = _make_mock_container("sha256:def", started_at_iso)
    watcher._watch_once(docker_client, row, conn, stop_event, last_image_id, {})
    called_started_at = process_event_mock.call_args[0][5]
    assert abs((datetime.now(UTC) - called_started_at).total_seconds()) < 5


def test_cancel_closes_live_stream_and_clears_registries():
    import app.watcher as watcher

    mgr = watcher.WatcherManager(docker_client=MagicMock())
    name = "x"
    stop_event = threading.Event()
    mgr._tasks[name] = MagicMock()
    mgr._stop_events[name] = stop_event
    stream_mock = MagicMock()
    mgr._streams[name] = stream_mock

    mgr._cancel(name)

    stream_mock.close.assert_called_once()
    assert stop_event.is_set()
    assert name not in mgr._tasks
    assert name not in mgr._stop_events
    assert name not in mgr._streams
