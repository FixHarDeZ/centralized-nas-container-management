import os
import tempfile

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


def test_upsert_and_list_containers(conn):
    import app.db as db
    db.upsert_monitored_container(conn, "torrentwatch", "/workspaces/repo", "torrentwatch", "stable", 0, 0, None)
    rows = db.list_monitored_containers(conn)
    assert len(rows) == 1
    assert rows[0]["name"] == "torrentwatch"
    assert rows[0]["maturity"] == "stable"


def test_upsert_is_idempotent_update(conn):
    import app.db as db
    db.upsert_monitored_container(conn, "x", None, None, "dev", 1, 0, None)
    db.upsert_monitored_container(conn, "x", None, None, "staging", 1, 1, None)
    row = db.get_monitored_container(conn, "x")
    assert row["maturity"] == "staging"
    assert row["paused"] == 1


def test_delete_container(conn):
    import app.db as db
    db.upsert_monitored_container(conn, "x", None, None, "dev", 0, 0, None)
    db.delete_monitored_container(conn, "x")
    assert db.get_monitored_container(conn, "x") is None


def test_record_event_persists_status_on_recurrence(conn):
    import app.db as db
    fp = "test-fingerprint-123"
    container = "test-container"

    # First occurrence with status "pending" and gate_reason "new"
    db.record_event(conn, fp, container, "pending", "new")

    # Second occurrence with status "reviewed" and gate_reason "manual_check"
    db.record_event(conn, fp, container, "reviewed", "manual_check")

    # Verify the row reflects the second call's values
    row = conn.execute(
        "SELECT * FROM events WHERE fingerprint=? AND container=?",
        (fp, container),
    ).fetchone()
    assert row is not None
    assert row["status"] == "reviewed"
    assert row["gate_reason"] == "manual_check"
    assert row["count"] == 2  # Bumped on recurrence


def test_verdict_column_and_migration_is_idempotent(tmp_path):
    import app.db as db
    conn = db.get_conn(str(tmp_path / "t.db"))
    db.init_db(conn)
    db.init_db(conn)  # second init not raise (duplicate column guard)
    db.record_event(conn, "fp1", "c1", status="analyzed")
    db.update_event_status(conn, "fp1", "c1", status="analyzed", verdict="code")
    row = conn.execute("SELECT verdict FROM events WHERE fingerprint='fp1'").fetchone()
    assert row["verdict"] == "code"


def test_verdict_column_added_to_existing_db(tmp_path):
    """DB created v1 schema (no verdict column) on init_db."""
    import sqlite3
    import app.db as db
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE events (fingerprint TEXT NOT NULL, container TEXT NOT NULL,"
        " first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,"
        " count INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL,"
        " gate_reason TEXT, analysis TEXT, pr_url TEXT,"
        " PRIMARY KEY (fingerprint, container))"
    )
    old.commit()
    old.close()
    # Now open with current app code and init_db
    conn = db.get_conn(path)
    db.init_db(conn)
    # Should not raise; verdict column should exist
    db.record_event(conn, "fp2", "c2", status="analyzed")
    db.update_event_status(conn, "fp2", "c2", status="analyzed", verdict="code")
    row = conn.execute("SELECT verdict FROM events WHERE fingerprint='fp2'").fetchone()
    assert row["verdict"] == "code"


def test_record_event_preserves_pr_opened_on_recurrence(tmp_path):
    import app.db as db
    conn = db.get_conn(str(tmp_path / "t.db"))
    db.init_db(conn)
    db.record_event(conn, "fp1", "c1", status="new")
    db.update_event_status(conn, "fp1", "c1", status="pr_opened", pr_url="https://x/pull/1")
    # error recurs while PR is open -> process_event would call record_event with a gate status
    db.record_event(conn, "fp1", "c1", status="gated", gate_reason="cooldown")
    row = conn.execute("SELECT status, count, pr_url FROM events WHERE fingerprint='fp1'").fetchone()
    assert row["status"] == "pr_opened"   # NOT clobbered to gated
    assert row["count"] == 2              # occurrence still counted (2 record_event calls)
    assert row["pr_url"] == "https://x/pull/1"


def test_record_event_does_not_protect_deployed(tmp_path):
    import app.db as db
    conn = db.get_conn(str(tmp_path / "t.db"))
    db.init_db(conn)
    db.record_event(conn, "fp2", "c1", status="new")
    db.update_event_status(conn, "fp2", "c1", status="deployed")
    db.record_event(conn, "fp2", "c1", status="gated", gate_reason="cooldown")
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp2'").fetchone()
    assert row["status"] == "gated"   # post-deploy recurrence re-enters pipeline


def test_get_events_by_status(conn):
    import app.db as db
    db.record_event(conn, "fp1", "c1", status="analyzed")
    db.record_event(conn, "fp2", "c2", status="pending")
    db.record_event(conn, "fp3", "c1", status="analyzed")
    rows = db.get_events_by_status(conn, "analyzed")
    assert len(rows) == 2
    assert all(row["status"] == "analyzed" for row in rows)
    rows = db.get_events_by_status(conn, "pending")
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"
