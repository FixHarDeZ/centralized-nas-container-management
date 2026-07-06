import os

import pytest

import config
import db


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "ink.db"))
    monkeypatch.setattr(config, "LIBRARY_DIR", str(tmp_path / "library"))
    monkeypatch.setattr(config, "COVERS_DIR", str(tmp_path / "covers"))
    monkeypatch.setattr(config, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(config, "REQUEST_DELAY_SECONDS", 0)
    os.makedirs(config.LIBRARY_DIR)
    os.makedirs(config.COVERS_DIR)
    db.init_db()
    return tmp_path
