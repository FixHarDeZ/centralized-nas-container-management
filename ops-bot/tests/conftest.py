"""Shared test fixtures: isolate from local .env and clean up globals."""
from __future__ import annotations

import asyncio

import pytest

import app.config
import app.db


@pytest.fixture(autouse=True)
def _isolate_settings(monkeypatch):
    """Tests must not read the operator's rendered .env (real secrets/ports)."""
    monkeypatch.setitem(app.config.Settings.model_config, "env_file", None)
    app.config._config = None
    yield
    app.config._config = None


@pytest.fixture(autouse=True)
def _close_db():
    """Close global aiosqlite connection — its worker thread is non-daemon
    and keeps the pytest process alive after tests finish."""
    yield
    if app.db._db is not None:
        asyncio.run(app.db.close_db())
