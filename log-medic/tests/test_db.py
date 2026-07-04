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
