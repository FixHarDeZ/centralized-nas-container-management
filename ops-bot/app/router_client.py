# ops-bot/app/router_client.py
"""SSH to the ASUS router for the Mesh Node fix. One constant command, never
anything the LLM chose — this is deliberately not app.ssh_client, whose
whitelist feeds the agentic diagnosis and stays read-only.

`restart_net_and_phy` is what the router's own DHCP page Apply button runs
(hidden action_script in /www/Advanced_DHCP_Content.asp). It restarts the
whole LAN, so the session may drop right after the command is sent; that
counts as sent. Success is judged by Kuma's UP, not by this exit code."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import os
from dataclasses import dataclass

import paramiko

from app.config import get_config

logger = logging.getLogger(__name__)

COMMAND = "service restart_net_and_phy"


@dataclass
class RouterResult:
    ok: bool
    output: str


def fingerprint(key: paramiko.PKey) -> str:
    """OpenSSH-style `SHA256:<base64, no padding>`, as `ssh-keygen -l` prints."""
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode().rstrip("=")


class PinnedFingerprint(paramiko.MissingHostKeyPolicy):
    """No known_hosts file in the container: every connect lands here, and
    only a pinned fingerprint gets through. Comma-separated, one per host key
    type: Paramiko negotiates ed25519 where OpenSSH picked ecdsa, so pinning
    only what `ssh-keygen -lF` shows refuses the router."""

    def __init__(self, expected: str):
        self.expected = {fp.strip() for fp in expected.split(",") if fp.strip()}

    def missing_host_key(self, client, hostname, key):
        got = fingerprint(key)
        if got not in self.expected:
            raise paramiko.SSHException(f"router host key mismatch: {got}")


def _run() -> RouterResult:
    cfg = get_config()
    if not os.path.exists(cfg.router_ssh_key_path):
        return RouterResult(False, f"router SSH key not found at {cfg.router_ssh_key_path}")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedFingerprint(cfg.router_ssh_host_key_sha256))
    try:
        client.connect(
            hostname=cfg.router_ssh_host,
            port=cfg.router_ssh_port,
            username=cfg.router_ssh_user,
            key_filename=cfg.router_ssh_key_path,
            look_for_keys=False,
            allow_agent=False,
            timeout=10,
        )
    except Exception as e:
        client.close()
        return RouterResult(False, f"connect failed: {e}")
    try:
        _, stdout, stderr = client.exec_command(COMMAND, timeout=20)
        try:
            out = stdout.read().decode(errors="replace") + stderr.read().decode(errors="replace")
            status = stdout.channel.recv_exit_status()
        except (EOFError, OSError, paramiko.SSHException) as e:
            # The LAN restart can cut the session after the command went out
            return RouterResult(True, f"sent; session dropped ({e.__class__.__name__})")
        return RouterResult(status == 0, out.strip() or f"exit {status}")
    except Exception as e:
        return RouterResult(False, f"exec failed: {e}")
    finally:
        client.close()


async def restart_network() -> RouterResult:
    result = await asyncio.get_running_loop().run_in_executor(None, _run)
    logger.info(f"Router {COMMAND}: ok={result.ok} {result.output[:200]}")
    return result
