import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

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


def test_setup_scheduler_registers_all_jobs(db_path):
    import app.scheduler as scheduler
    sched = scheduler.setup_scheduler(db_path)
    job_ids = {job.id for job in sched.get_jobs()}
    assert job_ids == {"daily_quota_reset", "breaker_auto_reset", "daily_digest", "poll_pr_merges"}
    sched.shutdown(wait=False)


def _seed_pr_event(tmp_path, name="torrentwatch"):
    from app import db
    path = str(tmp_path / "t.db")
    conn = db.get_conn(path)
    db.init_db(conn)
    db.upsert_monitored_container(conn, name, "/workspaces/repo", name, "stable", 0, 0, None)
    db.record_event(conn, "fp1", name, status="analyzed")
    db.update_event_status(conn, "fp1", name, status="pr_opened",
                            pr_url="https://github.com/o/r/pull/5")
    return path, conn


@patch("app.scheduler.deployer")
@patch("app.scheduler.subprocess.run")
def test_poll_merged_pr_triggers_deploy(mock_run, mock_deployer, tmp_path):
    from app import scheduler
    path, conn = _seed_pr_event(tmp_path)
    mock_run.return_value = MagicMock(
        returncode=0, stdout=json.dumps({"state": "MERGED", "mergedAt": "2026-07-05T10:00:00Z"})
    )
    scheduler.poll_pr_merges_job(path)
    mock_deployer.deploy.assert_called_once()
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp1'").fetchone()
    # status is 'merged' when deploy is invoked; deploy itself moves it on (mocked here)
    assert row["status"] == "merged"


@patch("app.scheduler.notify")
@patch("app.scheduler.deployer")
@patch("app.scheduler.subprocess.run")
def test_poll_closed_pr_marks_pr_closed_no_deploy(mock_run, mock_deployer, mock_notify, tmp_path):
    from app import scheduler

    def side_effect(args, **kwargs):
        if args[:3] == ["gh", "pr", "view"]:
            return MagicMock(returncode=0, stdout=json.dumps({"state": "CLOSED", "mergedAt": None}))
        return MagicMock(returncode=0, stdout="")

    path, conn = _seed_pr_event(tmp_path)
    mock_run.side_effect = side_effect
    scheduler.poll_pr_merges_job(path)
    mock_deployer.deploy.assert_not_called()
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp1'").fetchone()
    assert row["status"] == "pr_closed"
    assert "without merge" in mock_notify.call_args.args[0]
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert ["git", "push", "origin", "--delete", "fix/fp1"] in calls


@patch("app.scheduler.deployer")
@patch("app.scheduler.subprocess.run")
def test_poll_open_pr_left_alone(mock_run, mock_deployer, tmp_path):
    from app import scheduler
    path, conn = _seed_pr_event(tmp_path)
    mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps({"state": "OPEN", "mergedAt": None}))
    scheduler.poll_pr_merges_job(path)
    mock_deployer.deploy.assert_not_called()
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp1'").fetchone()
    assert row["status"] == "pr_opened"


@patch("app.scheduler.deployer")
@patch("app.scheduler.subprocess.run")
def test_poll_gh_error_skips_event_without_crashing(mock_run, mock_deployer, tmp_path):
    from app import scheduler
    path, conn = _seed_pr_event(tmp_path)
    mock_run.side_effect = RuntimeError("gh exploded")
    scheduler.poll_pr_merges_job(path)  # must not raise
    mock_deployer.deploy.assert_not_called()
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp1'").fetchone()
    assert row["status"] == "pr_opened"  # untouched, retried next cycle


def test_poll_job_registered():
    from unittest.mock import patch as p
    with p("app.scheduler.BackgroundScheduler") as mock_sched_cls:
        from app import scheduler
        scheduler.setup_scheduler(":memory:")
        job_ids = [c.kwargs.get("id") for c in mock_sched_cls.return_value.add_job.call_args_list]
        assert "poll_pr_merges" in job_ids
