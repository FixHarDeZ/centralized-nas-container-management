import os
import tempfile

import pytest
import yaml


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


@pytest.fixture
def config_file(tmp_path):
    cfg = {
        "containers": {
            "torrentwatch": {
                "repo": "/workspaces/centralized-nas-container-management",
                "subdir": "torrentwatch",
                "maturity": "stable",
            },
            "jellyfin": {"notify_only": True},
        }
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(cfg))
    return str(path)


def test_seeds_when_table_empty(conn, config_file):
    import app.config_seed as config_seed
    import app.db as db
    config_seed.seed_from_config_if_empty(conn, config_file)
    rows = {r["name"]: r for r in db.list_monitored_containers(conn)}
    assert rows["torrentwatch"]["maturity"] == "stable"
    assert rows["jellyfin"]["notify_only"] == 1
    assert rows["jellyfin"]["maturity"] == "dev"  # default when omitted


def test_does_not_reseed_when_table_has_rows(conn, config_file):
    import app.config_seed as config_seed
    import app.db as db
    db.upsert_monitored_container(conn, "manual-add", None, None, "dev", 0, 0, None)
    config_seed.seed_from_config_if_empty(conn, config_file)
    rows = db.list_monitored_containers(conn)
    assert len(rows) == 1
    assert rows[0]["name"] == "manual-add"


def test_handles_empty_container_entry(conn, tmp_path):
    import app.config_seed as config_seed
    import app.db as db
    cfg = {
        "containers": {
            "bare-container": None,  # Empty entry, parsed as None
        }
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(cfg))
    config_seed.seed_from_config_if_empty(conn, str(path))
    rows = {r["name"]: r for r in db.list_monitored_containers(conn)}
    assert "bare-container" in rows
    assert rows["bare-container"]["maturity"] == "dev"
    assert rows["bare-container"]["notify_only"] == 0
