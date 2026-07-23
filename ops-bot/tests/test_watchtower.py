# ops-bot/tests/test_watchtower.py
import pytest
from unittest.mock import AsyncMock, patch

from app.watchtower import is_watchtower_update


@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setenv("WATCHTOWER_GRACE_MINUTES", "5")
    from app.config import _config
    import app.config
    app.config._config = None
    yield
    app.config._config = None


@pytest.mark.asyncio
async def test_returns_true_when_recent_update(mock_config):
    mock_ssh = AsyncMock()
    mock_ssh.execute_command = AsyncMock(
        return_value=type("R", (), {
            "stdout": "2026-07-23 07:35:00 Found new outliner-outline-1 image\n",
            "stderr": "",
            "exit_code": 0,
        })()
    )

    with patch("app.watchtower.get_ssh_client", return_value=mock_ssh):
        result = await is_watchtower_update("outliner-outline-1")

    assert result is True


@pytest.mark.asyncio
async def test_returns_false_when_no_update(mock_config):
    mock_ssh = AsyncMock()
    mock_ssh.execute_command = AsyncMock(
        return_value=type("R", (), {
            "stdout": "",
            "stderr": "",
            "exit_code": 0,
        })()
    )

    with patch("app.watchtower.get_ssh_client", return_value=mock_ssh):
        result = await is_watchtower_update("outliner-outline-1")

    assert result is False
