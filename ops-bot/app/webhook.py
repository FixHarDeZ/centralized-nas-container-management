from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from app.orchestrator import handle_incident

logger = logging.getLogger(__name__)

router = APIRouter()


class KumaHeartbeat(BaseModel):
    status: int  # 0=down, 1=up
    time: str
    msg: str = ""


class KumaMonitor(BaseModel):
    name: str
    url: str = ""
    hostname: str = ""
    port: str = ""


class KumaWebhook(BaseModel):
    heartbeat: KumaHeartbeat
    monitor: KumaMonitor


# Map service name to container name (configurable)
SERVICE_CONTAINER_MAP = {
    "Outline Wiki": "outliner-outline-1",
    # Add more mappings as needed
}


def get_container_name(service_name: str) -> str:
    """Resolve service name to Docker container name."""
    if service_name in SERVICE_CONTAINER_MAP:
        return SERVICE_CONTAINER_MAP[service_name]
    # Fallback: use service name as container name (lowercase, hyphenated)
    return service_name.lower().replace(" ", "-")


@router.post("/webhook/uptime-kuma")
async def uptime_kuma_webhook(data: KumaWebhook, background_tasks: BackgroundTasks):
    # Only process DOWN alerts (status=0)
    if data.heartbeat.status != 0:
        return {"status": "ignored", "reason": "service is up"}

    service_name = data.monitor.name
    container_name = get_container_name(service_name)
    alert_message = data.heartbeat.msg

    logger.info(f"Received DOWN alert for {service_name} (container: {container_name})")

    # Run incident handling in background
    background_tasks.add_task(
        handle_incident,
        service_name=service_name,
        container_name=container_name,
        status="down",
        alert_message=alert_message,
    )

    return {"status": "accepted", "service": service_name}
