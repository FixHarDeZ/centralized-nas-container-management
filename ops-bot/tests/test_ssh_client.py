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


def test_allowed_llm_diagnostic_commands():
    client = SSHClient()
    assert client.is_allowed("docker ps -a") is True
    assert client.is_allowed(
        "docker ps -a --filter 'name=news-feed' --format 'table {{.Names}}'"
    ) is True
    assert client.is_allowed(
        "docker inspect news-feed --format '{{json .State}}'"
    ) is True
    assert client.is_allowed("docker logs --tail 100 news-feed 2>&1") is True
    assert client.is_allowed("df -h / /volume2 2>/dev/null") is True
    assert client.is_allowed("free -m") is True
    assert client.is_allowed("uptime") is True
    assert client.is_allowed("cat /proc/loadavg") is True
    assert client.is_allowed("curl -s http://localhost:5064/") is True


def test_allowed_internal_caller_commands():
    # Commands the app itself issues (watchtower check, /status, /logs) must
    # survive the hardened whitelist — unit tests for those callers mock
    # execute_command and would not catch a whitelist regression.
    client = SSHClient()
    assert client.is_allowed("docker logs watchtower --since 5m 2>&1") is True
    assert client.is_allowed(
        "docker ps -a --format 'table {{.Names}}\\t{{.Status}}\\t{{.Image}}'"
    ) is True
    assert client.is_allowed("docker logs --tail 50 news-feed 2>&1") is True


def test_blocked_shell_escape_commands():
    client = SSHClient()
    assert client.is_allowed("docker ps; rm -rf /volume2/docker/x") is False
    assert client.is_allowed("docker ps && docker restart news-feed") is False
    assert client.is_allowed("docker ps || reboot") is False
    assert client.is_allowed("docker logs x | sh") is False
    assert client.is_allowed("docker ps $(rm -rf /)") is False
    assert client.is_allowed("docker ps `id`") is False
    assert client.is_allowed("docker ps ${IFS}reboot") is False
    assert client.is_allowed("docker ps $'\\x3b reboot'") is False
    assert client.is_allowed("docker ps $HOME") is False
    assert client.is_allowed("df -h > /etc/passwd") is False
    assert client.is_allowed("cat /etc/shadow > /tmp/x") is False
    assert client.is_allowed("docker ps\nrm -rf /") is False
    assert client.is_allowed("docker restart news-feed") is False


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


@pytest.mark.asyncio
async def test_docker_rewritten_to_sudo_full_path(mock_config):
    client = SSHClient()
    chan = MagicMock()
    chan.recv_exit_status.return_value = 0
    stdout = MagicMock()
    stdout.channel = chan
    stdout.read.return_value = b"ok"
    stderr = MagicMock()
    stderr.read.return_value = b""
    ssh = MagicMock()
    ssh.exec_command.return_value = (MagicMock(), stdout, stderr)
    with patch.object(client, "_connect", new=AsyncMock(return_value=ssh)):
        await client.execute_command("docker ps -a")
        sent = ssh.exec_command.call_args[0][0]
        assert sent == "sudo -n /usr/local/bin/docker ps -a"

        await client.execute_command("free -m")
        sent = ssh.exec_command.call_args[0][0]
        assert sent == "free -m"
