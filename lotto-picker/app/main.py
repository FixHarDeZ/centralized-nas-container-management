"""lotto-picker — separate 2/3-digit picks excluding recent GLO draws.

Jobs (APScheduler, Asia/Bangkok):
- results poll every 15 min 15:00-19:45: cache the new draw, score saved
  picks, announce once (only when the latest draw is newly inserted).
- auto pick at PICK_TIME the day before the next nominal draw (1st/16th):
  one pick per mode/target, with independent persisted restart guards.
- history backfill daily at 04:30 (and once after the startup poll): cache
  every draw since lotto.HISTORY_START for the statistics pages.
- after a new draw is announced, a stats summary (mimo or template) follows as
  a second message per notifying mode.

Users: nginx overwrites ``X-Remote-User`` with the basic-auth name; saved picks,
the ledger and pick settings are per user. The jobs work for ``db.OWNER`` only
(one Telegram chat) — other users' picks are still scored, never announced.
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
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from . import analysis, db, insight, lotto, messages, service

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger("lotto-picker")

_TZ = ZoneInfo(os.environ.get("TZ", "Asia/Bangkok"))
_PICK_TIME = os.environ.get("PICK_TIME", "20:00")
_STATIC = Path(__file__).parent / "static"
_scheduler = BackgroundScheduler(timezone=_TZ.key)
_auto_lock = threading.Lock()


def _today() -> dt.date:
    return dt.datetime.now(_TZ).date()


def current_user(x_remote_user: str | None = Header(None)) -> str:
    """nginx sets this from basic auth on every request (overwriting whatever a
    client sent). The app port is not published, so the only caller without
    it is in-container — the healthcheck, tests — which acts as the owner."""
    user = (x_remote_user or "").strip()
    return user[:64] if user else db.OWNER


User = Depends(current_user)


def _sync() -> dict | None:
    return service.sync(max(db.settings(d)["draws"] for d in (2, 3)), today=_today())


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
    for digits in (3, 2):
        if db.settings(digits)["notify"]:
            mine = [
                s
                for s in scored
                if s["result_draw"] == fresh["date"]
                and s["settings"].get("digits", 3) == digits
                and s["user"] == db.OWNER
            ]
            messages.notifier().send(
                messages.result(fresh, mine, service.stats(digits), digits=digits)
            )
            # Second message, minutes later when mimo answers: never delays the result.
            insight.start(
                digits,
                then=lambda record, d=digits: messages.notifier().send(
                    messages.insight(record, d)
                ),
            )


def backfill_history() -> None:
    try:
        service.backfill_history(today=_today())
    except Exception:
        logger.exception("history backfill failed")


def auto_pick() -> None:
    # A manual invocation can overlap the scheduled job. Keep generation and
    # persisted guard updates together for both profiles in this process.
    with _auto_lock:
        profiles = [db.settings(digits) for digits in (3, 2)]
        profiles = [settings for settings in profiles if settings["notify"]]
        if not profiles:
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
        for settings in profiles:
            digits = settings["digits"]
            guard = "auto_pick_target" if digits == 3 else "auto_pick_target_2"
            if db.get(guard) == target.isoformat():
                continue
            try:
                pick = service.make_pick(
                    settings["draws"],
                    settings["picks"],
                    settings["scope"],
                    settings["permute"],
                    digits=digits,
                    style=settings.get("style", "random"),
                    stat_window=settings.get("stat_window", 0),
                )
                if not pick["numbers"]:
                    logger.warning("auto pick: pool empty with %s", pick["settings"])
                    continue
                db.add_pick("auto", pick["numbers"], pick["settings"], seen)
                db.put(guard, target.isoformat())
                messages.notifier().send(messages.auto_pick(target.isoformat(), pick))
            except Exception:
                logger.exception("auto pick failed for %d digits", digits)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    h, m = _PICK_TIME.split(":")
    _scheduler.add_job(
        poll_results, CronTrigger(hour="15-19", minute="*/15"), id="poll_results"
    )
    _scheduler.add_job(
        auto_pick, CronTrigger(hour=int(h), minute=int(m)), id="auto_pick"
    )
    _scheduler.add_job(
        backfill_history, CronTrigger(hour=4, minute=30), id="backfill_history"
    )
    _scheduler.start()

    # Off the startup path so the healthcheck isn't waiting. The deep history
    # walk must follow the first poll: that poll's first-boot check reads an
    # empty table as "do not announce", which a filled history would defeat.
    def startup():
        poll_results()
        backfill_history()

    threading.Thread(target=startup, daemon=True).start()
    yield
    _scheduler.shutdown(wait=False)


app = FastAPI(title="Lotto Picker", lifespan=lifespan)


class PickParams(BaseModel):
    draws: int = Field(2, ge=1, le=service.MAX_DRAWS)
    picks: int = Field(5, ge=1, le=50)
    scope: Literal["all", "front_back", "last2"] = "all"
    permute: bool = False
    digits: Literal[2, 3] = 3
    style: Literal["random", "hot", "cold", "overdue"] = "random"
    stat_window: int = Field(0, ge=0, le=500)  # 0 = all history

    @model_validator(mode="after")
    def canonical_scope(self):
        if self.digits == 2:
            self.scope = "last2"
        elif self.scope == "last2":
            raise ValueError("last2 scope requires digits=2")
        return self


class Settings(PickParams):
    notify: bool = True


class SavePick(BaseModel):
    numbers: list[str] = Field(min_length=1, max_length=50)
    settings: PickParams


class Ticket(BaseModel):
    number: str = Field(pattern=r"^[0-9]{6}$")
    qty: int = Field(1, ge=1, le=100)


class LedgerEntry(BaseModel):
    draw_date: dt.date
    label: str = Field("", max_length=120)
    tickets: list[Ticket] = Field(default_factory=list, max_length=100)
    cost: float = Field(ge=0, le=1_000_000)
    prize: float | None = Field(None, ge=0, le=100_000_000)

    def row(self) -> dict:
        return {**self.model_dump(), "draw_date": self.draw_date.isoformat(),
                "tickets": [t.model_dump() for t in self.tickets]}


@app.get("/healthz")
def healthz():
    return {"ok": True}


@app.get("/api/me")
def me(user: str = User):
    return {"user": user, "owner": user == db.OWNER}


@app.get("/api/settings")
def get_settings(digits: int = Query(3, ge=2, le=3), user: str = User):
    return db.settings(digits, user)


@app.put("/api/settings")
def put_settings(body: Settings, user: str = User):
    db.put_settings(body.model_dump(), user)
    return db.settings(body.digits, user)


@app.get("/api/draws")
def get_draws(limit: int = Query(24, ge=1, le=500)):
    return [
        {
            "date": d["date"],
            "first": d["prizes"]["first"][0],
            "last3f": d["prizes"]["last3f"],
            "last3b": d["prizes"]["last3b"],
            "last2": d["prizes"].get("last2", []),
            "count": len(lotto.draw_numbers(d["prizes"])),
        }
        for d in db.draws(limit=limit)
    ]


@app.post("/api/pick")
def pick(body: PickParams):
    """Random numbers only — nothing is saved until POST /api/picks."""
    cached = db.draws()
    have = (
        sum(lotto.has_last2(draw["prizes"]) for draw in cached)
        if body.digits == 2
        else len(cached)
    )
    if have < body.draws:
        try:
            service.sync(body.draws, today=_today())
        except Exception as exc:
            logger.warning("on-demand backfill failed: %s", exc)
    return service.make_pick(
        body.draws, body.picks, body.scope, body.permute, digits=body.digits,
        style=body.style, stat_window=body.stat_window,
    )


@app.get("/api/picks")
def list_picks(digits: int = Query(3, ge=2, le=3), user: str = User):
    return db.picks(digits=digits, user=user)


@app.post("/api/picks", status_code=201)
def save_pick(body: SavePick, user: str = User):
    if not all(
        re.fullmatch(rf"[0-9]{{{body.settings.digits}}}", number)
        for number in body.numbers
    ):
        raise HTTPException(422, f"numbers must be {body.settings.digits} ASCII digits")
    # Refresh first: a pick saved after GLO published must not be scored
    # against numbers that were already public.
    try:
        service.sync(body.settings.draws, today=_today())
    except Exception as exc:
        logger.warning("save pick: sync failed, using cache: %s", exc)
    pick_id = db.add_pick(
        "manual",
        sorted(set(body.numbers)),
        body.settings.model_dump(),
        service.based_on(),
        user,
    )
    return {"id": pick_id}


@app.delete("/api/picks/{pick_id}", status_code=204)
def delete_pick(pick_id: int, user: str = User):
    if not db.delete_pick(pick_id, user):
        raise HTTPException(404)


@app.get("/api/stats")
def get_stats(digits: int = Query(3, ge=2, le=3), user: str = User):
    return service.stats(digits, user)


@app.get("/api/history")
def history_status():
    draws = service.history(3)
    return {
        **db.get("history_status", {}),
        "count": len(draws),
        "from": draws[-1]["date"] if draws else None,
        "to": draws[0]["date"] if draws else None,
        "start": lotto.HISTORY_START.isoformat(),
    }


@app.get("/api/frequency")
def get_frequency(
    digits: int = Query(3, ge=2, le=3),
    category: str = Query(None),
    window: int = Query(0, ge=0, le=500),
):
    category = category or analysis.style_category(digits)
    if category not in analysis.CATEGORIES[digits]:
        raise HTTPException(422, f"category must be one of {sorted(analysis.CATEGORIES[digits])}")
    return service.frequency(digits, category, window)


@app.get("/api/backtest")
def get_backtest(
    digits: int = Query(3, ge=2, le=3),
    picks: int = Query(5, ge=1, le=50),
    draws: int = Query(2, ge=1, le=service.MAX_DRAWS),
    scope: Literal["all", "front_back", "last2"] = "all",
    permute: bool = False,
    window: int = Query(0, ge=0, le=500),
):
    if digits == 3 and scope == "last2":
        raise HTTPException(422, "last2 scope requires digits=2")
    return service.backtest(digits, picks, draws, scope, permute, window)


@app.get("/api/insight")
def get_insight(digits: int = Query(3, ge=2, le=3)):
    return insight.current(digits)


@app.post("/api/insight", status_code=202)
def make_insight(digits: int = Query(3, ge=2, le=3)):
    if not service.history(digits):
        raise HTTPException(409, "no history yet")
    insight.start(digits)
    return insight.current(digits)


@app.get("/api/ledger")
def get_ledger(user: str = User):
    return service.ledger(user)


@app.post("/api/ledger", status_code=201)
def add_ledger(body: LedgerEntry, user: str = User):
    return {"id": db.add_ledger(body.row(), user)}


@app.put("/api/ledger/{entry_id}")
def put_ledger(entry_id: int, body: LedgerEntry, user: str = User):
    if not db.update_ledger(entry_id, body.row(), user):
        raise HTTPException(404)
    return {"id": entry_id}


@app.delete("/api/ledger/{entry_id}", status_code=204)
def delete_ledger(entry_id: int, user: str = User):
    if not db.delete_ledger(entry_id, user):
        raise HTTPException(404)


@app.get("/api/check")
def check_ticket(
    number: str = Query(pattern=r"^[0-9]{6}$"),
    date: dt.date | None = None,
):
    result = service.check_ticket(number, date.isoformat() if date else None)
    if result is None:
        raise HTTPException(404, "draw not cached")
    return {**result, "price": lotto.TICKET_PRICE}


@app.post("/api/sync")
def sync_now():
    poll_results()
    return {"draws": len(db.draw_dates()), "latest_seen": db.get("latest_seen")}


@app.get("/")
def index():
    return FileResponse(_STATIC / "index.html")


app.mount("/static", StaticFiles(directory=_STATIC), name="static")
