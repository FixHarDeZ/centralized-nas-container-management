# ops-bot/app/orchestrator.py
from __future__ import annotations

import json
import logging

from app.db import get_db
from app.llm_client import get_llm_client
from app.ssh_client import get_ssh_client
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

    ssh = get_ssh_client()
    tg = get_telegram_bot()
    await tg.send_message(f"🔧 กำลังตรวจสอบ {service_name} แบบ read-only...")

    async def execute(cmd: str) -> str:
        res = await ssh.execute_command(cmd)
        output = res.stdout
        if res.stderr:
            output += f"\n[stderr] {res.stderr}"
        await db.execute(
            "INSERT INTO diagnostics (incident_id, step_name, raw_output) VALUES (?, ?, ?)",
            (incident_id, cmd, f"$ {cmd}\n{output}"),
        )
        await db.commit()
        return output or res.stderr or "(no output)"

    async def narrate(text: str) -> None:
        await tg.send_message(text)

    logger.info(f"Incident {incident_id}: running agentic diagnosis for {container_name}")
    llm = get_llm_client()
    report = await llm.diagnose_agentic(
        service_name, container_name, alert_message, execute=execute, narrate=narrate,
    )

    recommended = next((o for o in report.fix_options if o.recommended), None)
    await db.execute(
        "INSERT INTO analyses (incident_id, root_cause, severity, suggested_fix, fix_commands, report_json, llm_tokens_used) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            incident_id, report.summary, report.severity,
            recommended.detail if recommended else "",
            json.dumps(recommended.commands if recommended else []),
            json.dumps({
                "summary": report.summary, "severity": report.severity,
                "evidence": report.evidence, "machine_status": report.machine_status,
                "fix_options": [
                    {"title": o.title, "recommended": o.recommended, "detail": o.detail, "commands": o.commands}
                    for o in report.fix_options
                ],
                "truncated": report.truncated,
            }, ensure_ascii=False),
            report.tokens_used,
        ),
    )
    await db.commit()

    logger.info(f"Incident {incident_id}: sending Telegram report")
    await tg.send_incident_report(service_name, report, incident_id)
    return incident_id


async def handle_recovery(service_name: str) -> None:
    """Handle service recovery notification."""
    logger.info(f"Service recovered: {service_name}")
    tg = get_telegram_bot()
    await tg.send_recovery_notification(service_name)
