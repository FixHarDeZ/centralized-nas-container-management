"""Wallpaper Scout — FastAPI app: topic CRUD + dashboard."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import app.db as db
import app.scheduler as scheduler

_STATIC_DIR = Path(__file__).parent / "static"
_sched = BackgroundScheduler()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    db.init_db()
    scheduler.start_all(_sched)
    _sched.start()
    yield
    _sched.shutdown(wait=False)


app = FastAPI(lifespan=_lifespan)


class TopicCreate(BaseModel):
    query: str
    purposes: list[str]
    frequency_per_day: int = 1
    max_new_per_cycle: int = 5


class TopicUpdate(BaseModel):
    query: str | None = None
    purposes: list[str] | None = None
    frequency_per_day: int | None = None
    max_new_per_cycle: int | None = None
    enabled: bool | None = None


def _with_today_count(topic: dict) -> dict:
    today = date.today().isoformat()
    topic["downloaded_today"] = db.daily_download_counts(today).get(topic["query"], 0)
    return topic


@app.get("/api/status")
def status():
    return {"status": "ok"}


@app.get("/api/topics")
def list_topics():
    return [_with_today_count(t) for t in db.list_topics()]


@app.post("/api/topics", status_code=201)
def create_topic(payload: TopicCreate):
    topic_id = db.create_topic(payload.query, payload.purposes, payload.frequency_per_day, payload.max_new_per_cycle)
    topic = db.get_topic(topic_id)
    scheduler.schedule_topic(_sched, topic)
    return _with_today_count(topic)


@app.patch("/api/topics/{topic_id}")
def update_topic(topic_id: int, payload: TopicUpdate):
    topic = db.get_topic(topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="topic not found")

    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    if "enabled" in fields:
        fields["enabled"] = int(fields["enabled"])
    db.update_topic(topic_id, **fields)

    updated = db.get_topic(topic_id)
    if updated["enabled"]:
        scheduler.schedule_topic(_sched, updated)
    else:
        scheduler.unschedule_topic(_sched, topic_id)
    return _with_today_count(updated)


@app.post("/api/topics/{topic_id}/run", status_code=202)
def run_topic_now(topic_id: int):
    if db.get_topic(topic_id) is None:
        raise HTTPException(status_code=404, detail="topic not found")
    _sched.add_job(scheduler.run_topic_cycle, args=[topic_id])
    return {"status": "queued"}


@app.delete("/api/topics/{topic_id}", status_code=204)
def delete_topic(topic_id: int):
    scheduler.unschedule_topic(_sched, topic_id)
    db.delete_topic(topic_id)
    return Response(status_code=204)


app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
