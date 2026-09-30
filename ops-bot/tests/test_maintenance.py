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
    maintenance._recovered.clear()
    maintenance._open_stacks = None
    yield path
    maintenance._held.clear()
    maintenance._recovered.clear()
    maintenance._open_stacks = None


def _open_window(path, seconds=600, stacks="ai-deck,homepage"):
    path.write_text(f"{int(time.time()) + seconds}\n{stacks}\n")


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


def test_single_line_marker_still_works(marker):
    marker.write_text(str(int(time.time()) + 600))
    assert maintenance.active() is True
    assert "ไม่ระบุ stack" in maintenance.transition()


def test_announces_open_once_with_stack_names(marker):
    _open_window(marker)
    note = maintenance.transition()
    assert note.startswith("🚀") and "ai-deck, homepage" in note
    _open_window(marker, 300)  # deploy.sh narrows to the tail
    assert maintenance.transition() is None


def test_no_notice_without_window(marker):
    assert maintenance.transition() is None


@pytest.mark.asyncio
async def test_close_notice_lists_recovered_and_still_down(marker):
    _open_window(marker)
    maintenance.transition()
    with patch("app.webhook.handle_incident", new_callable=AsyncMock), \
         patch("app.webhook.handle_recovery", new_callable=AsyncMock):
        await _post(DOWN)
        await _post(UP)
        await _post({**DOWN, "monitor": {"name": "Homepage"}})
    _open_window(marker, -1)
    note = maintenance.transition()
    assert note.startswith("✅") and "ai-deck, homepage" in note
    assert "กลับมาเอง: AI Desk" in note
    assert "กำลังวินิจฉัย: Homepage" in note
    assert maintenance.take_expired() == [("Homepage", "homepage", "timeout")]
    assert maintenance.transition() is None


def test_quiet_close_says_no_alerts(marker):
    _open_window(marker)
    maintenance.transition()
    _open_window(marker, -1)
    assert "ไม่มี alert" in maintenance.transition()
