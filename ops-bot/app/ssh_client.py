# ops-bot/app/ssh_client.py
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import namedtuple
from functools import partial
from typing import Optional

import paramiko

from app.config import get_config

logger = logging.getLogger(__name__)

SSHResult = namedtuple("SSHResult", ["stdout", "stderr", "exit_code"])

# READ-ONLY commands only — no restart, no fix, no modifications
ALLOWED_PREFIXES = [
    "docker ps",
    "docker logs",
    "docker inspect",
    "docker compose logs",
    "docker network inspect",
    "docker port",
    "df ",
    "free ",
    "uptime",
    "cat /proc/loadavg",
    "cat /proc/meminfo",
    "curl ",
    "docker logs watchtower",
    "top -b",
    "iostat",
    "cat /proc/cpuinfo",
    "hostname",
    "uname",
]


class SSHClient:
    def __init__(self):
        self._client: Optional[paramiko.SSHClient] = None

    def is_allowed(self, command: str) -> bool:
        cmd_stripped = command.strip()
        return any(cmd_stripped.startswith(prefix) for prefix in ALLOWED_PREFIXES)

    async def _connect(self) -> paramiko.SSHClient:
        if self._client is not None:
            return self._client

        cfg = get_config()

        if not os.path.exists(cfg.ssh_key_path):
            raise FileNotFoundError(
                f"SSH key not found at {cfg.ssh_key_path}. "
                f"Mount your SSH key into the container."
            )

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        connect_kwargs = {
            "hostname": cfg.ssh_host,
            "port": cfg.ssh_port,
            "username": cfg.ssh_user,
            "key_filename": cfg.ssh_key_path,
            "timeout": 10,
        }

        await self._run_in_executor(client.connect, **connect_kwargs)
        self._client = client
        logger.info(f"SSH connected to {cfg.ssh_host} as {cfg.ssh_user}")
        return client

    async def execute_command(self, command: str, timeout: int = 30) -> SSHResult:
        if not self.is_allowed(command):
            logger.warning(f"Blocked disallowed command: {command}")
            return SSHResult(
                stdout="",
                stderr=f"Command not allowed (read-only mode): {command}",
                exit_code=-1,
            )

        # Synology: non-login SSH PATH lacks /usr/local/bin and docker.sock is
        # root-only — requires NOPASSWD sudoers entry for /usr/local/bin/docker
        if command.strip().startswith("docker"):
            command = "sudo -n /usr/local/bin/" + command.strip()

        try:
            client = await self._connect()
            # Whole exec runs in the executor — recv_exit_status/read are
            # blocking; on the event loop they freeze the entire app if a
            # remote command hangs (e.g. docker inspect on a wedged container).
            return await self._run_in_executor(
                self._exec_blocking, client, command, timeout
            )
        except Exception as e:
            logger.error(f"SSH command failed: {command} — {e}")
            return SSHResult(stdout="", stderr=str(e), exit_code=-1)

    @staticmethod
    def _exec_blocking(client: paramiko.SSHClient, command: str, timeout: int) -> SSHResult:
        _, stdout, stderr = client.exec_command(command, timeout=timeout)
        # recv_exit_status ignores the channel timeout — enforce a hard
        # deadline by polling so a hung remote command can't block forever
        deadline = time.time() + timeout
        while not stdout.channel.exit_status_ready():
            if time.time() > deadline:
                stdout.channel.close()
                raise TimeoutError(f"SSH command timed out after {timeout}s: {command}")
            time.sleep(0.2)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        return SSHResult(stdout=out, stderr=err, exit_code=exit_code)

    async def close(self):
        if self._client:
            self._client.close()
            self._client = None

    @staticmethod
    async def _run_in_executor(func, *args, **kwargs):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))


_ssh_client: Optional[SSHClient] = None


def get_ssh_client() -> SSHClient:
    global _ssh_client
    if _ssh_client is None:
        _ssh_client = SSHClient()
    return _ssh_client
