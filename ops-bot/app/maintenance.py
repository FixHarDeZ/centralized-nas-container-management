# ops-bot/app/maintenance.py
"""Deploy window: scripts/deploy.sh writes an epoch deadline into a file that
is bind-mounted here, so restarts it causes are not diagnosed as incidents.

Read from the local mount, not over SSH — a deploy is exactly when the NAS is
busiest and SSH has been seen dropping ("SSH session not active").

DOWN alerts inside the window are held, not dropped: a recovery clears them,
and whatever is still down once the window closes gets the normal diagnosis.
A deploy that breaks a service must still be reported, and Kuma only notifies
on state change, so it will not re-send the DOWN by itself."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from app.config import get_config

logger = logging.getLogger(__name__)

# service_name -> (container_name, alert_message)
_held: dict[str, tuple[str, str]] = {}
_task: Optional[asyncio.Task] = None


def active(now: Optional[float] = None) -> bool:
    try:
        with open(get_config().maintenance_file) as f:
            until = float(f.read().strip())
    except (OSError, ValueError):
        return False
    return (now if now is not None else time.time()) < until


def hold(service_name: str, container_name: str, alert_message: str) -> None:
    _held[service_name] = (container_name, alert_message)
    logger.info(f"Deploy window: holding DOWN for {service_name}")


def release(service_name: str) -> bool:
    """Recovery during the window. True = the DOWN was held, so the recovery
    message is noise too."""
    return _held.pop(service_name, None) is not None


def take_expired() -> list[tuple[str, str, str]]:
    """Held alerts to diagnose now that the window is closed."""
    if not _held or active():
        return []
    out = [(name, c, m) for name, (c, m) in _held.items()]
    _held.clear()
    return out


async def _watch(handle_incident) -> None:
    while True:
        await asyncio.sleep(30)
        for name, container, msg in take_expired():
            logger.info(f"Deploy window closed, {name} still down — diagnosing")
            try:
                await handle_incident(
                    service_name=name, container_name=container,
                    status="down", alert_message=msg,
                )
            except Exception:
                logger.exception(f"Held incident for {name} failed")


def start(handle_incident) -> None:
    global _task
    _task = asyncio.create_task(_watch(handle_incident))


async def stop() -> None:
    if _task is not None:
        _task.cancel()
