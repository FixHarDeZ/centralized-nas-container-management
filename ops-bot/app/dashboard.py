from __future__ import annotations

import asyncio
import json
from pathlib import Path
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field
from openai import AsyncOpenAI

from app.config import get_config
from app.db import get_db
from app.model_settings import model_settings, save_model, MODEL_ID

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).parent / 'templates'))
PAGE_SIZE = 25


def decoded(value, expected):
    try:
        result = json.loads(value or 'null')
        return result if isinstance(result, expected) else None
    except (ValueError, TypeError):
        return None


@router.get('/dashboard', response_class=HTMLResponse)
async def dashboard_index(request: Request, q: str = Query('', max_length=100),
                          severity: str = Query('', pattern='^(|critical|warning|info)$'),
                          page: int = Query(1, ge=1, le=1000000)):
    db = await get_db()
    # Latest report only, so repeated analyses never duplicate an incident row.
    joined = (' FROM incidents i LEFT JOIN analyses a ON a.id = '
              '(SELECT MAX(id) FROM analyses WHERE incident_id = i.id) ')
    where, params = [], []
    if q.strip():
        where.append('(instr(lower(i.service_name), lower(?)) > 0 OR instr(lower(COALESCE(i.container_name, \'\')), lower(?)) > 0)')
        params.extend([q.strip(), q.strip()])
    if severity:
        where.append('a.severity = ?')
        params.append(severity)
    predicate = ' WHERE ' + ' AND '.join(where) if where else ''
    total = (await (await db.execute('SELECT COUNT(*)' + joined + predicate, params)).fetchone())[0]
    pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, pages)
    incidents = await (await db.execute(
        'SELECT i.*, a.severity, a.root_cause, a.llm_tokens_used' + joined + predicate +
        ' ORDER BY i.created_at DESC, i.id DESC LIMIT ? OFFSET ?',
        [*params, PAGE_SIZE, (page - 1) * PAGE_SIZE])).fetchall()
    stats = await (await db.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(i.created_at >= datetime('now', 'localtime', '-1 day')), 0) AS recent, "
        "COALESCE(SUM(a.severity = 'critical'), 0) AS critical, "
        "COALESCE(SUM(i.is_watchtower_update = 1), 0) AS suppressed" + joined)).fetchone()
    def page_url(number):
        return '/dashboard?' + urlencode({'q': q, 'severity': severity, 'page': number})
    return templates.TemplateResponse(request=request, name='dashboard.html', context={
        'incidents': incidents, 'stats': stats, 'settings': await model_settings(),
        'q': q, 'severity': severity, 'total': total, 'page': page, 'pages': pages,
        'previous_url': page_url(page - 1), 'next_url': page_url(page + 1), 'active': 'overview',
    })


@router.get('/dashboard/incident/{incident_id}', response_class=HTMLResponse)
async def dashboard_incident(request: Request, incident_id: int):
    db = await get_db()
    incident = await (await db.execute('SELECT * FROM incidents WHERE id = ?', (incident_id,))).fetchone()
    if incident is None:
        raise HTTPException(404, 'Incident not found')
    diagnostics = await (await db.execute('SELECT * FROM diagnostics WHERE incident_id = ? ORDER BY id', (incident_id,))).fetchall()
    analysis = await (await db.execute('SELECT * FROM analyses WHERE incident_id = ? ORDER BY id DESC LIMIT 1', (incident_id,))).fetchone()
    report = decoded(analysis['report_json'], dict) if analysis else None
    actions = await (await db.execute('SELECT * FROM actions WHERE incident_id = ? ORDER BY id DESC', (incident_id,))).fetchall()
    return templates.TemplateResponse(request=request, name='incident_detail.html', context={
        'incident': incident, 'diagnostics': diagnostics, 'analysis': analysis, 'report': report,
        'actions': actions, 'active': 'overview',
        'fix_commands': (decoded(analysis['fix_commands'], list) or []) if analysis else [],
    })


@router.get('/dashboard/settings', response_class=HTMLResponse)
async def settings_page(request: Request):
    return templates.TemplateResponse(request=request, name='settings.html', context={
        'settings': await model_settings(), 'active': 'settings',
    })


class ModelUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model: str | None = Field(..., max_length=128)


def verify_settings_request(request: Request):
    # JSON + a custom header force cross-origin browsers through a CORS preflight
    # (this app has no CORS allowlist). Check Origin as well; proxy may terminate TLS.
    origin = urlsplit(request.headers.get('origin', ''))
    if (request.headers.get('x-ops-settings') != '1' or
            request.headers.get('content-type', '').split(';')[0] != 'application/json' or
            origin.scheme not in ('http', 'https') or origin.netloc != request.url.netloc):
        raise HTTPException(403, 'Settings must be saved from this dashboard')


@router.post('/dashboard/settings')
async def update_settings(request: Request):
    verify_settings_request(request)
    try:
        update = ModelUpdate.model_validate(await request.json())
        return await save_model(update.model)
    except (ValueError, TypeError):
        raise HTTPException(422, 'ระบุ Model ID ที่ถูกต้อง (1–128 ตัวอักษร: A–Z, a–z, 0–9, . _ : / -)')


@router.get('/dashboard/api/models')
async def available_models():
    cfg = get_config()
    if not cfg.mimo_api_key:
        return JSONResponse({'detail': 'ยังไม่ได้ตั้งค่า MiMo API key'}, status_code=503)
    try:
        async with AsyncOpenAI(api_key=cfg.mimo_api_key, base_url=cfg.mimo_base_url, max_retries=0) as client:
            result = await asyncio.wait_for(client.models.list(), timeout=10)
        models = sorted({m.id for m in result.data if isinstance(m.id, str) and MODEL_ID.fullmatch(m.id)})[:200]
        return {'models': models}
    except Exception:
        # Provider errors can contain credentials, endpoint details or request bodies.
        return JSONResponse({'detail': 'ดึงรายชื่อไม่ได้จาก endpoint นี้ ระบุ Model ID เองได้'}, status_code=502)
