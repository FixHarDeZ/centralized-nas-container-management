from __future__ import annotations

from unittest.mock import MagicMock, patch

import paramiko
import pytest

import app.config
from app import router_client
from app.router_client import COMMAND, PinnedFingerprint, fingerprint


@pytest.fixture
def router_env(monkeypatch, tmp_path):
    key = tmp_path / "router_ed25519"
    key.write_text("fake")
    monkeypatch.setenv("ROUTER_SSH_HOST", "10.0.0.1")
    monkeypatch.setenv("ROUTER_SSH_USER", "someone")
    monkeypatch.setenv("ROUTER_SSH_KEY_PATH", str(key))
    monkeypatch.setenv("ROUTER_SSH_HOST_KEY_SHA256", "SHA256:expected")
    app.config._config = None
    yield
    app.config._config = None


def _server_key():
    return paramiko.ECDSAKey.generate()


def test_fingerprint_matches_openssh_format():
    key = _server_key()
    fp = fingerprint(key)
    assert fp.startswith("SHA256:") and not fp.endswith("=")


def test_pinned_policy_accepts_matching_key():
    key = _server_key()
    PinnedFingerprint(fingerprint(key)).missing_host_key(MagicMock(), "h", key)


def test_pinned_policy_rejects_other_key():
    with pytest.raises(paramiko.SSHException):
        PinnedFingerprint("SHA256:nope").missing_host_key(MagicMock(), "h", _server_key())


def test_pinned_policy_accepts_any_listed_key():
    key = _server_key()
    PinnedFingerprint(f"SHA256:other, {fingerprint(key)}").missing_host_key(MagicMock(), "h", key)


def test_pinned_policy_rejects_when_unpinned():
    with pytest.raises(paramiko.SSHException):
        PinnedFingerprint("").missing_host_key(MagicMock(), "h", _server_key())


def _fake_client(stdout=b"Done.\n", exit_status=0, connect_error=None):
    client = MagicMock()
    if connect_error:
        client.connect.side_effect = connect_error
    out = MagicMock()
    out.read.return_value = stdout
    out.channel.recv_exit_status.return_value = exit_status
    err = MagicMock()
    err.read.return_value = b""
    client.exec_command.return_value = (MagicMock(), out, err)
    return client


@pytest.mark.asyncio
async def test_restart_runs_only_the_constant_command(router_env):
    client = _fake_client()
    with patch("app.router_client.paramiko.SSHClient", return_value=client):
        result = await router_client.restart_network()
    assert result.ok
    client.exec_command.assert_called_once()
    assert client.exec_command.call_args.args[0] == COMMAND == "service restart_net_and_phy"
    kwargs = client.connect.call_args.kwargs
    assert kwargs["hostname"] == "10.0.0.1" and kwargs["username"] == "someone"
    assert kwargs["look_for_keys"] is False and kwargs["allow_agent"] is False
    assert "password" not in kwargs
    client.close.assert_called_once()


@pytest.mark.asyncio
async def test_connect_failure_is_not_ok(router_env):
    client = _fake_client(connect_error=OSError("no route"))
    with patch("app.router_client.paramiko.SSHClient", return_value=client):
        result = await router_client.restart_network()
    assert not result.ok and "no route" in result.output
    client.exec_command.assert_not_called()


@pytest.mark.asyncio
async def test_session_dropped_after_send_counts_as_sent(router_env):
    client = _fake_client()
    client.exec_command.return_value[1].read.side_effect = EOFError()
    with patch("app.router_client.paramiko.SSHClient", return_value=client):
        result = await router_client.restart_network()
    assert result.ok


@pytest.mark.asyncio
async def test_missing_key_is_not_ok(router_env, monkeypatch):
    monkeypatch.setenv("ROUTER_SSH_KEY_PATH", "/nonexistent/key")
    app.config._config = None
    result = await router_client.restart_network()
    assert not result.ok and "key" in result.output.lower()
