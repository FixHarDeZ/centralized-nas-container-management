from __future__ import annotations

import json
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.db import get_db

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard_index(request: Request):
    db = await get_db()

    cursor = await db.execute(
        "SELECT id, service_name, container_name, status, is_watchtower_update, created_at "
        "FROM incidents ORDER BY created_at DESC LIMIT 50"
    )
    incidents = await cursor.fetchall()

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "incidents": incidents,
    })


@router.get("/dashboard/incident/{incident_id}", response_class=HTMLResponse)
async def dashboard_incident(request: Request, incident_id: int):
    db = await get_db()

    cursor = await db.execute("SELECT * FROM incidents WHERE id = ?", (incident_id,))
    incident = await cursor.fetchone()

    cursor = await db.execute(
        "SELECT step_name, raw_output, created_at FROM diagnostics WHERE incident_id = ?",
        (incident_id,),
    )
    diagnostics = await cursor.fetchall()

    cursor = await db.execute(
        "SELECT root_cause, severity, suggested_fix, fix_commands, llm_tokens_used, created_at, report_json "
        "FROM analyses WHERE incident_id = ?",
        (incident_id,),
    )
    analysis = await cursor.fetchone()

    report = None
    if analysis and analysis[6]:
        report = json.loads(analysis[6])

    cursor = await db.execute(
        "SELECT action_type, commands_executed, result_output, success, executed_at FROM actions WHERE incident_id = ?",
        (incident_id,),
    )
    actions = await cursor.fetchall()

    return templates.TemplateResponse("incident_detail.html", {
        "request": request,
        "incident": incident,
        "diagnostics": diagnostics,
        "analysis": analysis,
        "report": report,
        "actions": actions,
        "fix_commands": json.loads(analysis[3]) if analysis and analysis[3] else [],
    })
