# ops-bot/tests/test_ssh_client.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.ssh_client import SSHClient, SSHResult


@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setenv("SSH_HOST", "192.168.1.1")
    monkeypatch.setenv("SSH_USER", "testuser")
    monkeypatch.setenv("SSH_PASSWORD", "testpass")
    from app.config import _config
    import app.config
    app.config._config = None
    yield
    app.config._config = None


def test_ssh_result():
    r = SSHResult(stdout="ok", stderr="", exit_code=0)
    assert r.stdout == "ok"
    assert r.exit_code == 0


def test_allowed_commands():
    client = SSHClient()
    assert client.is_allowed("docker ps -a") is True
    assert client.is_allowed("docker logs --tail 100 mycontainer") is True
    assert client.is_allowed("df -h") is True
    assert client.is_allowed("rm -rf /") is False
    assert client.is_allowed("sudo reboot") is False
    assert client.is_allowed("curl http://localhost:8080") is True


@pytest.mark.asyncio
async def test_execute_blocked_command(mock_config):
    client = SSHClient()
    result = await client.execute_command("rm -rf /")
    assert result.exit_code == -1
    assert "not allowed" in result.stderr.lower()
