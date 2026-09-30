# ops-bot/app/maintenance.py
"""Deploy window: scripts/deploy.sh writes an epoch deadline into a file that
is bind-mounted here, so restarts it causes are not diagnosed as incidents.

Read from the local mount, not over SSH — a deploy is exactly when the NAS is
busiest and SSH has been seen dropping ("SSH session not active").

DOWN alerts inside the window are held, not dropped: a recovery clears them,
and whatever is still down once the window closes gets the normal diagnosis.
A deploy that breaks a service must still be reported, and Kuma only notifies
on state change, so it will not re-send the DOWN by itself.

The marker is two lines: epoch deadline, then comma-separated stack names.
The watcher announces the window opening and closing in Telegram. deploy.sh
rewrites the deadline to a short tail after the last stack is up; that is the
same window, not a new one, so it is not announced again."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Optional

from app.config import get_config

logger = logging.getLogger(__name__)

# service_name -> (container_name, alert_message)
_held: dict[str, tuple[str, str]] = {}
# held DOWNs that came back UP inside the window, for the closing notice
_recovered: list[str] = []
_open_stacks: Optional[list[str]] = None  # None = no window announced
_task: Optional[asyncio.Task] = None


def read() -> Optional[tuple[float, list[str]]]:
    try:
        with open(get_config().maintenance_file) as f:
            lines = f.read().splitlines()
        until = float(lines[0].strip())
    except (OSError, ValueError, IndexError):
        return None
    stacks = [s for s in (lines[1].split(",") if len(lines) > 1 else []) if s.strip()]
    return until, [s.strip() for s in stacks]


def active(now: Optional[float] = None) -> bool:
    marker = read()
    return marker is not None and (now if now is not None else time.time()) < marker[0]


def hold(service_name: str, container_name: str, alert_message: str) -> None:
    _held[service_name] = (container_name, alert_message)
    logger.info(f"Deploy window: holding DOWN for {service_name}")


def release(service_name: str) -> bool:
    """Recovery during the window. True = the DOWN was held, so the recovery
    message is noise too."""
    if _held.pop(service_name, None) is None:
        return False
    _recovered.append(service_name)
    return True


def take_expired() -> list[tuple[str, str, str]]:
    """Held alerts to diagnose now that the window is closed."""
    if not _held or active():
        return []
    out = [(name, c, m) for name, (c, m) in _held.items()]
    _held.clear()
    return out


def _hhmm(epoch: float) -> str:
    return time.strftime("%H:%M", time.localtime(epoch))


def transition() -> Optional[str]:
    """Telegram notice when the window opens or closes, else None. Call before
    take_expired() so the closing notice still sees what is held."""
    global _open_stacks
    marker = read()
    is_open = marker is not None and time.time() < marker[0]
    if is_open and _open_stacks is None:
        _open_stacks = marker[1]
        _recovered.clear()
        names = ", ".join(_open_stacks) or "ไม่ระบุ stack"
        return f"🚀 เริ่ม deploy: {names}\nพัก alert ถึง {_hhmm(marker[0])}"
    if not is_open and _open_stacks is not None:
        names = ", ".join(_open_stacks) or "ไม่ระบุ stack"
        _open_stacks = None
        lines = [f"✅ deploy เสร็จ: {names}"]
        if _recovered:
            lines.append(f"ล่มชั่วคราวแล้วกลับมาเอง: {', '.join(_recovered)}")
        if _held:
            lines.append(f"⚠️ ยังล่มอยู่ กำลังวินิจฉัย: {', '.join(_held)}")
        elif not _recovered:
            lines.append("ไม่มี alert ระหว่าง deploy")
        _recovered.clear()
        return "\n".join(lines)
    return None


async def _watch(handle_incident, notify) -> None:
    while True:
        await asyncio.sleep(30)
        note = transition()
        if note:
            try:
                await notify(note)
            except Exception:
                logger.exception("Deploy window notice failed")
        for name, container, msg in take_expired():
            logger.info(f"Deploy window closed, {name} still down — diagnosing")
            try:
                await handle_incident(
                    service_name=name, container_name=container,
                    status="down", alert_message=msg,
                )
            except Exception:
                logger.exception(f"Held incident for {name} failed")


def start(handle_incident, notify) -> None:
    global _task
    _task = asyncio.create_task(_watch(handle_incident, notify))


async def stop() -> None:
    if _task is not None:
        _task.cancel()
