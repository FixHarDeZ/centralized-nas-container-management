"""Shared pytest fixtures for repo-level script tests."""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"


@pytest.fixture
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture
def scripts_dir() -> Path:
    return SCRIPTS_DIR


@pytest.fixture
def tmp_vault(tmp_path: Path) -> Path:
    """A plaintext YAML mimicking a decrypted vault, for unit tests."""
    return tmp_path / "vault.yaml"


@pytest.fixture
def tmp_manifest(tmp_path: Path) -> Path:
    return tmp_path / "secrets.manifest.yaml"
