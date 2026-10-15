"""Shop HTML shell; records stay in the Shop API/store, not bot state."""
from pathlib import Path

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates


def register_views(app, store):
    templates = Jinja2Templates(directory=Path(__file__).parent / 'templates')
    affiliate = app.state.affiliate

    @app.get('/shop', response_class=HTMLResponse)
    def listing(request: Request):
        posted = affiliate.posted_counts()
        jobs = [{**job, 'posts': posted.get(job['id'], 0)} for job in store.list_jobs()]
        return templates.TemplateResponse(request=request, name='shop_list.html',
                                          context={'jobs': jobs, 'gate': None})

    # Registered before /shop/{job_id}, which would otherwise look up a job named "revenue".
    @app.get('/shop/revenue', response_class=HTMLResponse)
    def revenue(request: Request):
        return templates.TemplateResponse(request=request, name='shop_revenue.html',
                                          context={'summary': affiliate.summary(), 'gate': None})

    @app.get('/shop/{job_id}', response_class=HTMLResponse)
    def workspace(request: Request, job_id: str):
        job = {**store.get_job(job_id), 'assets': store.list_assets(job_id),
               'renders': store.list_renders(job_id)}
        return templates.TemplateResponse(request=request, name='shop_job.html',
                                          context={'job': job, 'gate': None})
