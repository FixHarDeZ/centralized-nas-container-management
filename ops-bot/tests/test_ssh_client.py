# ops-bot/tests/test_ssh_client.py
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.ssh_client import SSHClient, SSHResult


@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setenv("SSH_HOST", "192.168.1.1")
    monkeypatch.setenv("SSH_USER", "testuser")
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
    # Read-only commands allowed
    assert client.is_allowed("docker ps -a") is True
    assert client.is_allowed("docker logs --tail 100 mycontainer") is True
    assert client.is_allowed("docker inspect mycontainer") is True
    assert client.is_allowed("docker compose logs --tail 50") is True
    assert client.is_allowed("docker network inspect bridge") is True
    assert client.is_allowed("docker port mycontainer") is True
    assert client.is_allowed("df -h") is True
    assert client.is_allowed("free -m") is True
    assert client.is_allowed("uptime") is True
    assert client.is_allowed("cat /proc/loadavg") is True
    assert client.is_allowed("cat /proc/meminfo") is True
    assert client.is_allowed("curl http://localhost:8080") is True
    assert client.is_allowed("docker logs watchtower --since 5m") is True
    assert client.is_allowed("top -b -n 1") is True
    assert client.is_allowed("hostname") is True


def test_blocked_write_commands():
    client = SSHClient()
    # Write/modify commands blocked
    assert client.is_allowed("docker restart mycontainer") is False
    assert client.is_allowed("docker compose restart") is False
    assert client.is_allowed("docker stop mycontainer") is False
    assert client.is_allowed("docker start mycontainer") is False
    assert client.is_allowed("docker kill mycontainer") is False
    assert client.is_allowed("docker rm mycontainer") is False
    assert client.is_allowed("docker exec mycontainer bash") is False
    assert client.is_allowed("docker pull nginx") is False
    assert client.is_allowed("docker compose up -d") is False
    assert client.is_allowed("docker compose down") is False
    assert client.is_allowed("rm -rf /") is False
    assert client.is_allowed("sudo reboot") is False
    assert client.is_allowed("sed -i 's/3g/5g/' docker-compose.yml") is False
    assert client.is_allowed("echo 'test' > /etc/config") is False
    assert client.is_allowed("apt install nginx") is False


@pytest.mark.asyncio
async def test_execute_blocked_command(mock_config):
    client = SSHClient()
    result = await client.execute_command("rm -rf /")
    assert result.exit_code == -1
    assert "not allowed" in result.stderr.lower()
    assert "read-only" in result.stderr.lower()


@pytest.mark.asyncio
async def test_execute_blocked_restart(mock_config):
    client = SSHClient()
    result = await client.execute_command("docker restart mycontainer")
    assert result.exit_code == -1
    assert "not allowed" in result.stderr.lower()
