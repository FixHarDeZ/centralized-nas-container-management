"""lotto-picker — random 3-digit picks that skip numbers from recent GLO draws.

Jobs (APScheduler, Asia/Bangkok):
- results poll every 15 min 15:00-19:45: cache the new draw, score saved
  picks, announce once (only when the latest draw is newly inserted).
- auto pick at PICK_TIME the day before the next nominal draw (1st/16th):
  one pick per target, guarded by kv ``auto_pick_target`` against restarts.
"""

from __future__ import annotations

import datetime as dt
import logging
import os
import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, lotto, messages, service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("lotto-picker")

_TZ = ZoneInfo(os.environ.get("TZ", "Asia/Bangkok"))
_PICK_TIME = os.environ.get("PICK_TIME", "20:00")
_STATIC = Path(__file__).parent / "static"
_scheduler = BackgroundScheduler(timezone=_TZ.key)


def _today() -> dt.date:
    return dt.datetime.now(_TZ).date()


def _sync() -> dict | None:
    return service.sync(db.settings()["draws"], today=_today())


def poll_results() -> None:
    try:
        fresh = _sync()
    except Exception as exc:
        logger.warning("results poll failed: %s", exc)
        return
    scored = service.score_pending()
    if fresh is None:
        return
    logger.info("new draw %s, scored %d pick(s)", fresh["date"], len(scored))
    if db.settings()["notify"]:
        mine = [s for s in scored if s["result_draw"] == fresh["date"]]
        messages.notifier().send(messages.result(fresh, mine, service.stats()))


def auto_pick() -> None:
    s = db.settings()
    if not s["notify"]:
        return
    try:
        _sync()
    except Exception as exc:
        logger.warning("auto pick: sync failed, using cache: %s", exc)
    seen = service.based_on()
    if not seen:
        return
    target = lotto.next_expected_draw(dt.date.fromisoformat(seen))
    if _today() + dt.timedelta(days=1) != target:
        return
    if db.get("auto_pick_target") == target.isoformat():
        return
    pick = service.make_pick(s["draws"], s["picks"], s["scope"], s["permute"])
    if not pick["numbers"]:
        logger.warning("auto pick: pool empty with %s", pick["settings"])
        return
    db.add_pick("auto", pick["numbers"], pick["settings"], seen)
    db.put("auto_pick_target", target.isoformat())
    messages.notifier().send(messages.auto_pick(target.isoformat(), pick))


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    h, m = _PICK_TIME.split(":")
    _scheduler.add_job(poll_results, CronTrigger(hour="15-19", minute="*/15"), id="poll_results")
    _scheduler.add_job(auto_pick, CronTrigger(hour=int(h), minute=int(m)), id="auto_pick")
    _scheduler.start()
    # First run backfills history (a few dozen GLO requests) — keep it off the
    # startup path so the healthcheck isn't waiting on it.
    threading.Thread(target=poll_results, daemon=True).start()
    yield
    _scheduler.shutdown(wait=False)


app = FastAPI(title="Lotto Picker", lifespan=lifespan)


class PickParams(BaseModel):
    draws: int = Field(2, ge=1, le=service.MAX_DRAWS)
    picks: int = Field(5, ge=1, le=50)
    scope: Literal["all", "front_back"] = "all"
    permute: bool = False


class Settings(PickParams):
    notify: bool = True


class SavePick(BaseModel):
    numbers: list[str] = Field(min_length=1, max_length=50)
    settings: PickParams


_THREE = re.compile(r"^\d{3}$")


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/settings")
def get_settings():
    return db.settings()


@app.put("/api/settings")
def put_settings(body: Settings):
    db.put("settings", body.model_dump())
    return db.settings()


@app.get("/api/draws")
def get_draws():
    return [
        {
            "date": d["date"],
            "first": d["prizes"]["first"][0],
            "last3f": d["prizes"]["last3f"],
            "last3b": d["prizes"]["last3b"],
            "last2": d["prizes"].get("last2", []),
            "count": len(lotto.draw_numbers(d["prizes"])),
        }
        for d in db.draws()
    ]


@app.post("/api/pick")
def pick(body: PickParams):
    """Random numbers only — nothing is saved until POST /api/picks."""
    have = len(db.draws(limit=body.draws))
    if have < body.draws:
        try:
            service.sync(body.draws, today=_today())
        except Exception as exc:
            logger.warning("on-demand backfill failed: %s", exc)
    result = service.make_pick(body.draws, body.picks, body.scope, body.permute)
    result["excluded"] = sorted(
        lotto.excluded(db.draws(limit=body.draws), body.scope, body.permute)
    )
    return result


@app.get("/api/picks")
def list_picks():
    return db.picks()


@app.post("/api/picks", status_code=201)
def save_pick(body: SavePick):
    if not all(_THREE.match(n) for n in body.numbers):
        raise HTTPException(422, "numbers must be 3 digits")
    # Refresh first: a pick saved after GLO published must not be scored
    # against numbers that were already public.
    try:
        service.sync(body.settings.draws, today=_today())
    except Exception as exc:
        logger.warning("save pick: sync failed, using cache: %s", exc)
    pick_id = db.add_pick(
        "manual", sorted(set(body.numbers)), body.settings.model_dump(), service.based_on()
    )
    return {"id": pick_id}


@app.delete("/api/picks/{pick_id}", status_code=204)
def delete_pick(pick_id: int):
    if not db.delete_pick(pick_id):
        raise HTTPException(404)


@app.get("/api/stats")
def get_stats():
    return service.stats()


@app.post("/api/sync")
def sync_now():
    poll_results()
    return {"draws": len(db.draw_dates()), "latest_seen": db.get("latest_seen")}


@app.get("/")
def index():
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
