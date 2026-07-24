from __future__ import annotations

import hashlib
import hmac
import logging
import time
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from pydantic import BaseModel

from app.config import get_config
from app.orchestrator import handle_incident, handle_recovery
from app.telegram_bot import get_telegram_bot

logger = logging.getLogger(__name__)

router = APIRouter()


class KumaHeartbeat(BaseModel):
    status: int  # 0=down, 1=up
    time: str
    msg: str = ""


class KumaMonitor(BaseModel):
    name: str
    url: str = ""
    hostname: Optional[str] = ""
    port: Optional[str] = ""


class KumaWebhook(BaseModel):
    heartbeat: Optional[KumaHeartbeat] = None
    monitor: Optional[KumaMonitor] = None


# Map service name to container name (configurable)
SERVICE_CONTAINER_MAP = {
    "Outline Wiki": "outliner-outline-1",
    "News Feed": "news-feed",
    "Homepage": "homepage",
    "Ink Reader": "ink-reader",
    "Maid Tracker": "maid-tracker",
    "My Secretary": "my-secretary",
    "Portainer": "portainer",
    "Torrent Watch": "torrentwatch",
    "Watchtower": "watchtower",
    "Hermes Gateway": "hermes-agent",
    "Ops Bot": "ops-bot",
}

# Debounce: track last alert time per monitor
_last_alert: dict[str, float] = {}


def get_container_name(service_name: str) -> str:
    """Resolve service name to Docker container name."""
    if service_name in SERVICE_CONTAINER_MAP:
        return SERVICE_CONTAINER_MAP[service_name]
    # Fallback: use service name as container name (lowercase, hyphenated)
    return service_name.lower().replace(" ", "-")


def _verify_secret(secret: Optional[str]) -> None:
    """Verify webhook secret using constant-time comparison."""
    cfg = get_config()
    if not cfg.kuma_webhook_secret:
        return  # No secret configured, allow all

    if secret is None:
        raise HTTPException(status_code=401, detail="Missing webhook secret")

    # Constant-time comparison to prevent timing attacks
    expected = cfg.kuma_webhook_secret.encode()
    provided = secret.encode()
    if not hmac.compare_digest(expected, provided):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")


def _is_debounced(monitor_name: str) -> bool:
    """Check if this monitor is within debounce window."""
    cfg = get_config()
    now = time.time()
    last = _last_alert.get(monitor_name, 0)
    elapsed = now - last
    if elapsed < cfg.debounce_minutes * 60:
        logger.info(f"Debounced alert for {monitor_name} ({elapsed:.0f}s ago, window={cfg.debounce_minutes}m)")
        return True
    return False


def _record_alert(monitor_name: str) -> None:
    """Record alert time for debounce tracking."""
    _last_alert[monitor_name] = time.time()


@router.post("/webhook/uptime-kuma")
async def uptime_kuma_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    secret: Optional[str] = Query(None, alias="secret"),
):
    # Verify webhook secret first
    _verify_secret(secret)

    # Parse raw body for debugging
    raw_body = await request.body()
    try:
        import json
        body = json.loads(raw_body)
        logger.info(f"Raw webhook body: {json.dumps(body, default=str)[:500]}")
    except Exception:
        logger.warning(f"Non-JSON body: {raw_body[:200]}")
        return {"status": "error", "message": "Invalid JSON"}

    # Parse into model
    try:
        data = KumaWebhook.model_validate(body)
    except Exception as e:
        logger.error(f"Validation error: {e}")
        logger.error(f"Body was: {json.dumps(body, default=str)[:1000]}")
        return {"status": "error", "message": str(e)}

    # Unknown payload shape (no Kuma keys at all)
    if "heartbeat" not in body and "monitor" not in body:
        logger.warning(f"Unrecognized webhook payload: {json.dumps(body, default=str)[:200]}")
        return {"status": "error", "message": "Not an Uptime Kuma payload"}

    # Handle test notification from Uptime Kuma (null heartbeat/monitor)
    if data.heartbeat is None or data.monitor is None:
        logger.info("Received test notification from Uptime Kuma")
        return {"status": "test_ok", "message": "Webhook endpoint is reachable"}

    service_name = data.monitor.name
    status = data.heartbeat.status

    # Handle recovery (status=1, UP)
    if status == 1:
        logger.info(f"Recovery detected for {service_name}")
        background_tasks.add_task(handle_recovery, service_name=service_name)
        # Clear debounce on recovery
        _last_alert.pop(service_name, None)
        return {"status": "recovery_noted", "service": service_name}

    # Handle DOWN (status=0)
    if status != 0:
        return {"status": "ignored", "reason": f"unknown status: {status}"}

    # Debounce check
    if _is_debounced(service_name):
        return {"status": "debounced", "service": service_name}

    container_name = get_container_name(service_name)
    alert_message = data.heartbeat.msg

    logger.info(f"Received DOWN alert for {service_name} (container: {container_name})")

    # Record alert for debounce
    _record_alert(service_name)

    # Run incident handling in background
    background_tasks.add_task(
        handle_incident,
        service_name=service_name,
        container_name=container_name,
        status="down",
        alert_message=alert_message,
    )

    return {"status": "accepted", "service": service_name}
