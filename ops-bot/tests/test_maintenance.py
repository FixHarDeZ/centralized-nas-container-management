from __future__ import annotations

import time

import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

import app.config
from app import maintenance
from app.main import app as fastapi_app

DOWN = {
    "heartbeat": {"status": 0, "time": "2026-09-30 11:05:00", "msg": "timeout"},
    "monitor": {"name": "AI Desk"},
}
UP = {
    "heartbeat": {"status": 1, "time": "2026-09-30 11:07:00", "msg": "OK"},
    "monitor": {"name": "AI Desk"},
}


@pytest.fixture
def marker(tmp_path, monkeypatch):
    path = tmp_path / "until"
    monkeypatch.setenv("MAINTENANCE_FILE", str(path))
    app.config._config = None
    maintenance._held.clear()
    yield path
    maintenance._held.clear()


def _open_window(path, seconds=600):
    path.write_text(str(int(time.time()) + seconds))


async def _post(body):
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return (await client.post("/webhook/uptime-kuma", json=body)).json()


def test_inactive_without_marker(marker):
    assert maintenance.active() is False


def test_inactive_after_deadline(marker):
    _open_window(marker, -1)
    assert maintenance.active() is False


def test_garbage_marker_is_inactive(marker):
    marker.write_text("soon")
    assert maintenance.active() is False


@pytest.mark.asyncio
async def test_down_in_window_is_held_not_diagnosed(marker):
    _open_window(marker)
    with patch("app.webhook.handle_incident", new_callable=AsyncMock) as handle:
        assert (await _post(DOWN))["status"] == "maintenance"
    handle.assert_not_called()
    assert "AI Desk" in maintenance._held


@pytest.mark.asyncio
async def test_recovery_of_held_down_is_silent(marker):
    _open_window(marker)
    with patch("app.webhook.handle_incident", new_callable=AsyncMock), \
         patch("app.webhook.handle_recovery", new_callable=AsyncMock) as recovery:
        await _post(DOWN)
        assert (await _post(UP))["status"] == "maintenance"
    recovery.assert_not_called()
    assert maintenance.take_expired() == []


@pytest.mark.asyncio
async def test_still_down_after_window_gets_diagnosed(marker):
    _open_window(marker)
    with patch("app.webhook.handle_incident", new_callable=AsyncMock):
        await _post(DOWN)
    assert maintenance.take_expired() == []  # window still open
    _open_window(marker, -1)
    assert maintenance.take_expired() == [("AI Desk", "ai-desk", "timeout")]
    assert maintenance.take_expired() == []


@pytest.mark.asyncio
async def test_held_down_does_not_debounce_later_alert(marker):
    _open_window(marker)
    with patch("app.webhook.handle_incident", new_callable=AsyncMock):
        await _post(DOWN)
    marker.unlink()
    with patch("app.webhook.handle_incident", new_callable=AsyncMock) as handle:
        assert (await _post(DOWN))["status"] == "accepted"
    handle.assert_called_once()
