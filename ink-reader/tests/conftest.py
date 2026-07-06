import tempfile
import os
import shutil
import pytest

import config


@pytest.fixture
def data_dir():
    d = tempfile.mkdtemp(prefix="ink_")
    orig = config.DATA_DIR
    config.DATA_DIR = d
    config.LIBRARY_DIR = os.path.join(d, "library")
    config.COVERS_DIR = os.path.join(d, "covers")
    config.BACKUP_DIR = os.path.join(d, "backups")
    config.DB_PATH = os.path.join(d, "ink.db")
    yield d
    shutil.rmtree(d)
    config.DATA_DIR = orig
