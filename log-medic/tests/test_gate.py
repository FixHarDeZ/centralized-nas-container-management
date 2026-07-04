import os
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta

import pytest


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


def test_in_grace_period(monkeypatch):
    import app.gate as gate
    now = datetime.now(UTC)
    assert gate.in_grace_period(now - timedelta(minutes=5), now=now) is True
    assert gate.in_grace_period(now - timedelta(minutes=30), now=now) is False


def test_circuit_breaker_trips_after_threshold(conn, monkeypatch):
    monkeypatch.setenv("STORM_THRESHOLD_PER_HOUR", "3")
    import importlib
    import app.gate as gate
    import app.db as db
    importlib.reload(gate)
    now = datetime.now(UTC)
    for i in range(4):
        db.record_event(conn, f"fp{i}", "c1", status="new", now=now.isoformat())
    gate.maybe_trip_breaker(conn, "c1", now=now)
    assert gate.is_breaker_tripped(conn, "c1") is True


def test_circuit_breaker_resets_after_quiet_window(conn, monkeypatch):
    monkeypatch.setenv("STORM_THRESHOLD_PER_HOUR", "1")
    import importlib
    import app.gate as gate
    import app.db as db
    importlib.reload(gate)
    old = datetime.now(UTC) - timedelta(hours=7)
    db.record_event(conn, "fp1", "c1", status="new", now=old.isoformat())
    db.record_event(conn, "fp2", "c1", status="new", now=old.isoformat())
    gate.maybe_trip_breaker(conn, "c1", now=old)
    assert gate.is_breaker_tripped(conn, "c1") is True
    reset = gate.maybe_reset_breaker(conn, "c1", now=datetime.now(UTC))
    assert reset is True
    assert gate.is_breaker_tripped(conn, "c1") is False


def test_cooldown(conn, monkeypatch):
    monkeypatch.setenv("COOLDOWN_HOURS", "6")
    import importlib
    import app.gate as gate
    import app.db as db
    importlib.reload(gate)
    now = datetime.now(UTC)
    db.record_event(conn, "fp1", "c1", status="new", now=(now - timedelta(hours=1)).isoformat())
    assert gate.in_cooldown(conn, "fp1", "c1", now=now) is True
    db.record_event(conn, "fp2", "c1", status="new", now=(now - timedelta(hours=7)).isoformat())
    assert gate.in_cooldown(conn, "fp2", "c1", now=now) is False


def test_cooldown_anchored_to_last_seen_not_first_seen(conn, monkeypatch):
    monkeypatch.setenv("COOLDOWN_HOURS", "6")
    import importlib
    import app.gate as gate
    import app.db as db
    importlib.reload(gate)
    now = datetime.now(UTC)
    db.record_event(conn, "fp1", "c1", status="new", now=(now - timedelta(hours=7)).isoformat())
    db.record_event(conn, "fp1", "c1", status="new", now=(now - timedelta(hours=1)).isoformat())
    assert gate.in_cooldown(conn, "fp1", "c1", now=now) is True


def test_quota_exceeded(conn, monkeypatch):
    monkeypatch.setenv("DAILY_QUOTA", "2")
    import importlib
    import app.gate as gate
    import app.db as db
    importlib.reload(gate)
    assert gate.quota_exceeded(conn) is False
    db.increment_quota(conn)
    db.increment_quota(conn)
    assert gate.quota_exceeded(conn) is True


def test_dirty_repo_uncommitted_changes(tmp_path):
    import app.gate as gate
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-m", "main"], cwd=repo, check=True)
    (repo / "f.txt").write_text("dirty")
    assert gate.check_dirty_repo(str(repo), "fp1") is True


def test_dirty_repo_clean_is_false(tmp_path, monkeypatch):
    monkeypatch.setenv("REPO_IDLE_HOURS", "0")
    import importlib
    import app.gate as gate
    importlib.reload(gate)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-m", "main"], cwd=repo, check=True)
    assert gate.check_dirty_repo(str(repo), "fp1") is False
