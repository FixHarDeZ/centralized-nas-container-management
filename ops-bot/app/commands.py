from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

import httpx

from app.config import get_config
from app.db import get_db
from app.orchestrator import execute_fix
from app.ssh_client import get_ssh_client
from app.telegram_bot import get_telegram_bot

logger = logging.getLogger(__name__)

_polling_task: Optional[asyncio.Task] = None


async def start_telegram_polling():
    """Start Telegram bot polling for commands and callbacks."""
    cfg = get_config()
    if not cfg.telegram_bot_token:
        logger.warning("No Telegram bot token, skipping polling")
        return

    global _polling_task
    _polling_task = asyncio.create_task(_poll_loop())


async def stop_telegram_polling():
    global _polling_task
    if _polling_task:
        _polling_task.cancel()
        try:
            await _polling_task
        except asyncio.CancelledError:
            pass


async def _poll_loop():
    """Long-poll Telegram for updates."""
    cfg = get_config()
    base_url = f"https://api.telegram.org/bot{cfg.telegram_bot_token}"
    offset = 0

    while True:
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                resp = await client.get(
                    f"{base_url}/getUpdates",
                    params={"offset": offset, "timeout": 30},
                )
                data = resp.json()

                if data.get("ok"):
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        await _handle_update(update)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Telegram poll error: {e}")
            await asyncio.sleep(5)


async def _handle_update(update: dict):
    """Route Telegram update to appropriate handler."""
    if "message" in update:
        msg = update["message"]
        text = msg.get("text", "")
        chat_id = str(msg["chat"]["id"])

        cfg = get_config()
        if chat_id != cfg.telegram_chat_id:
            return  # Ignore messages from unauthorized chats

        if text.startswith("/status"):
            await _handle_status()
        elif text.startswith("/diagnose"):
            parts = text.split(maxsplit=1)
            if len(parts) > 1:
                await _handle_diagnose(parts[1])
        elif text.startswith("/logs"):
            parts = text.split(maxsplit=1)
            if len(parts) > 1:
                await _handle_logs(parts[1])

    elif "callback_query" in update:
        await _handle_callback(update["callback_query"])


async def _handle_status():
    """Handle /status command — show all container statuses."""
    ssh = get_ssh_client()
    result = await ssh.execute_command(
        "docker ps -a --format 'table {{.Names}}\\t{{.Status}}\\t{{.Image}}'"
    )
    tg = get_telegram_bot()
    await tg.send_message(f"📊 **สถานะ Container ทั้งหมด:**\n```\n{result.stdout}\n```")


async def _handle_diagnose(service_name: str):
    """Handle /diagnose command — manual trigger diagnostics."""
    from app.orchestrator import handle_incident

    container_name = service_name.lower().replace(" ", "-")
    await handle_incident(
        service_name=service_name,
        container_name=container_name,
        status="manual",
        alert_message=f"Manual diagnose triggered via /diagnose {service_name}",
    )


async def _handle_logs(service_name: str):
    """Handle /logs command — show recent container logs."""
    parts = service_name.split()
    container = parts[0]
    lines = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 50
    lines = min(lines, 200)

    ssh = get_ssh_client()
    result = await ssh.execute_command(f"docker logs --tail {lines} {container} 2>&1")
    tg = get_telegram_bot()
    await tg.send_message(f"📋 **Logs ({container}, last {lines} lines):**\n```\n{result.stdout[-3000:]}\n```")


async def _handle_callback(callback_query: dict):
    """Handle InlineKeyboard callback (fix/restart/logs buttons)."""
    data = callback_query.get("data", "")
    callback_id = callback_query["id"]

    tg = get_telegram_bot()
    await tg.answer_callback(callback_id, "กำลังดำเนินการ...")

    parts = data.split(":")
    if len(parts) != 2:
        return

    action_type, incident_id_str = parts
    incident_id = int(incident_id_str)

    if action_type in ("fix", "restart"):
        success, output = await execute_fix(incident_id, action_type)
    elif action_type == "logs":
        db = await get_db()
        cursor = await db.execute(
            "SELECT container_name FROM incidents WHERE id = ?",
            (incident_id,),
        )
        row = await cursor.fetchone()
        if row:
            ssh = get_ssh_client()
            result = await ssh.execute_command(f"docker logs --tail 50 {row[0]} 2>&1")
            await tg.send_message(f"📋 **Logs ({row[0]}):**\n```\n{result.stdout[-3000:]}\n```")
