# ops-bot/app/ssh_client.py
from __future__ import annotations

import asyncio
import logging
import os
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

        try:
            client = await self._connect()
            _, stdout, stderr = await self._run_in_executor(
                client.exec_command, command, timeout=timeout
            )
            exit_code = stdout.channel.recv_exit_status()
            out = stdout.read().decode("utf-8", errors="replace")
            err = stderr.read().decode("utf-8", errors="replace")
            return SSHResult(stdout=out, stderr=err, exit_code=exit_code)
        except Exception as e:
            logger.error(f"SSH command failed: {command} — {e}")
            return SSHResult(stdout="", stderr=str(e), exit_code=-1)

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
