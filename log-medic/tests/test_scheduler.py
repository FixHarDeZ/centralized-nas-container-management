import os
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def db_path(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmpdir)
    import importlib
    import app.db as db_module
    importlib.reload(db_module)
    path = os.path.join(tmpdir, "test.db")
    conn = db_module.get_conn(path)
    db_module.init_db(conn)
    conn.close()
    return path


def test_breaker_auto_reset_job_resets_quiet_containers(db_path, monkeypatch):
    import app.db as db
    import app.scheduler as scheduler

    monkeypatch.setenv("STORM_THRESHOLD_PER_HOUR", "1")
    import importlib
    import app.gate
    importlib.reload(app.gate)
    import app.gate as gate

    conn = db.get_conn(db_path)
    db.upsert_monitored_container(conn, "c1", None, None, "stable", 0, 0, None)
    old = datetime.now(UTC) - timedelta(hours=8)
    db.record_event(conn, "fp1", "c1", status="new", now=old.isoformat())
    gate.maybe_trip_breaker(conn, "c1", now=old)
    assert gate.is_breaker_tripped(conn, "c1") is True
    conn.close()

    scheduler.breaker_auto_reset_job(db_path)

    conn = db.get_conn(db_path)
    assert gate.is_breaker_tripped(conn, "c1") is False


def test_daily_digest_job_notifies_only_when_something_tripped(db_path, monkeypatch):
    import app.db as db
    import app.scheduler as scheduler

    monkeypatch.setenv("STORM_THRESHOLD_PER_HOUR", "1")
    import importlib
    import app.gate
    importlib.reload(app.gate)
    import app.gate as gate

    notify_mock = MagicMock()
    monkeypatch.setattr(scheduler, "notify", notify_mock)

    conn = db.get_conn(db_path)
    db.upsert_monitored_container(conn, "c1", None, None, "stable", 0, 0, None)
    now = datetime.now(UTC)
    db.record_event(conn, "fp1", "c1", status="new", now=now.isoformat())
    gate.maybe_trip_breaker(conn, "c1", now=now)
    conn.close()

    scheduler.daily_digest_job(db_path)
    notify_mock.assert_called_once()
    assert "c1" in notify_mock.call_args.args[0]


def test_setup_scheduler_registers_three_jobs(db_path):
    import app.scheduler as scheduler
    sched = scheduler.setup_scheduler(db_path)
    job_ids = {job.id for job in sched.get_jobs()}
    assert job_ids == {"daily_quota_reset", "breaker_auto_reset", "daily_digest"}
