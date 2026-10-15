"""Shop HTML shell; records stay in the Shop API/store, not bot state."""
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def register_views(app, store):
    templates = Jinja2Templates(directory=Path(__file__).parent / 'templates')

    @app.get('/shop', response_class=HTMLResponse)
    def listing(request: Request):
        return templates.TemplateResponse(request=request, name='shop_list.html',
                                          context={'jobs': store.list_jobs(), 'gate': None})

    @app.get('/shop/{job_id}', response_class=HTMLResponse)
    def workspace(request: Request, job_id: str):
        job = {**store.get_job(job_id), 'assets': store.list_assets(job_id),
               'renders': store.list_renders(job_id)}
        return templates.TemplateResponse(request=request, name='shop_job.html',
                                          context={'job': job, 'gate': None})
