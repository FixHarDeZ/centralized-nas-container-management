# ops-bot/app/orchestrator.py
from __future__ import annotations

import json
import logging

from app.db import get_db
from app.diagnostics import run_diagnostics
from app.llm_client import get_llm_client
from app.telegram_bot import get_telegram_bot
from app.watchtower import is_watchtower_update

logger = logging.getLogger(__name__)


async def handle_incident(
    service_name: str,
    container_name: str,
    status: str,
    alert_message: str,
) -> int:
    db = await get_db()

    # Create incident record
    cursor = await db.execute(
        "INSERT INTO incidents (service_name, container_name, status, alert_message) VALUES (?, ?, ?, ?)",
        (service_name, container_name, status, alert_message),
    )
    incident_id = cursor.lastrowid
    await db.commit()

    # Check watchtower grace period
    if await is_watchtower_update(container_name):
        await db.execute(
            "UPDATE incidents SET is_watchtower_update = TRUE WHERE id = ?",
            (incident_id,),
        )
        await db.commit()
        logger.info(f"Incident {incident_id}: watchtower update detected, skipping alert")
        return incident_id

    # Run diagnostics
    logger.info(f"Incident {incident_id}: running diagnostics for {container_name}")
    diagnostic_results = await run_diagnostics(container_name)

    # Save diagnostics to DB
    for step_name, output in diagnostic_results.items():
        await db.execute(
            "INSERT INTO diagnostics (incident_id, step_name, raw_output) VALUES (?, ?, ?)",
            (incident_id, step_name, output),
        )
    await db.commit()

    # LLM analysis
    logger.info(f"Incident {incident_id}: analyzing with LLM")
    llm = get_llm_client()
    analysis = await llm.analyze_diagnostic(service_name, diagnostic_results)

    # Save analysis to DB
    await db.execute(
        "INSERT INTO analyses (incident_id, root_cause, severity, suggested_fix, fix_commands, llm_tokens_used) VALUES (?, ?, ?, ?, ?, ?)",
        (incident_id, analysis.root_cause, analysis.severity, analysis.suggested_fix, json.dumps(analysis.fix_commands), analysis.tokens_used),
    )
    await db.commit()

    # Send Telegram notification
    logger.info(f"Incident {incident_id}: sending Telegram notification")
    tg = get_telegram_bot()
    await tg.send_incident_report(service_name, analysis, diagnostic_results, incident_id)

    return incident_id


async def handle_recovery(service_name: str) -> None:
    """Handle service recovery notification."""
    logger.info(f"Service recovered: {service_name}")
    tg = get_telegram_bot()
    await tg.send_recovery_notification(service_name)
