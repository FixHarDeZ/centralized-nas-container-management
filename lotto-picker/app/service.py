"""Glue between GLO, the DB and the pure logic: sync, pick, score, stats.

Fetchers and the clock are parameters so tests drive this without a network.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time

from . import db, glo, lotto

logger = logging.getLogger(__name__)

MAX_DRAWS = 24
# A backfill walk gives up after this many days without finding a draw —
# guards against probing forever if GLO's history endpoint changes shape.
MAX_GAP_DAYS = 45
PROBE_DELAY = 0.3

_lock = threading.Lock()


def sync(want: int, fetch_latest=None, fetch_on=None, today=None, sleep=time.sleep):
    """Pull the latest draw, then backfill until ``want`` complete draws are cached.

    Returns the latest draw only when it was newly inserted — that, and only
    that, is a new result worth announcing. Backfilled history never is.
    """
    fetch_latest = fetch_latest or glo.latest
    fetch_on = fetch_on or glo.on
    today = today or dt.date.today()
    want = max(1, min(want, MAX_DRAWS))
    with _lock:
        fresh = None
        latest = fetch_latest()
        if latest:
            seen = db.get("latest_seen")
            if not seen or latest["date"] > seen:
                # Recorded even while GLO is still drawing: a pick saved now
                # must be scored against the *next* draw, not this one.
                db.put("latest_seen", latest["date"])
            if lotto.is_complete(latest["prizes"]):
                # An empty cache means first boot: the latest draw may be weeks
                # old, so cache it silently instead of announcing it as news.
                first_boot = not db.draw_dates()
                if db.add_draw(latest) and not first_boot:
                    fresh = latest
            else:
                logger.info("draw %s still in progress, not caching", latest["date"])

        have = db.draw_dates()
        if not have:
            return fresh
        nodraw = db.nodraw_dates()
        day = dt.date.fromisoformat(max(have))
        count = gap = 0
        while count < want and gap <= MAX_GAP_DAYS:
            iso = day.isoformat()
            if iso in have:
                count += 1
                gap = 0
            elif day.day in lotto.CANDIDATE_DAYS and iso not in nodraw and day < today:
                try:
                    draw = fetch_on(day)
                except Exception as exc:
                    logger.warning("backfill stopped at %s: %s", iso, exc)
                    break
                sleep(PROBE_DELAY)
                if draw and lotto.is_complete(draw["prizes"]):
                    db.add_draw(draw)
                    have.add(iso)
                    count += 1
                    gap = 0
                else:
                    if draw is None:
                        db.add_nodraw(iso)
                    gap += 1
            else:
                gap += 1
            day -= dt.timedelta(days=1)
        return fresh


def based_on() -> str | None:
    seen = db.get("latest_seen")
    cached = db.draw_dates()
    return max(filter(None, [seen, *cached]), default=None)


def make_pick(draws: int, picks: int, scope: str, permute: bool) -> dict:
    used = db.draws(limit=draws)
    excluded = lotto.excluded(used, scope, permute)
    available = sorted(lotto.ALL_THREE - excluded)
    return {
        "numbers": lotto.pick(available, picks),
        "pool_size": len(available),
        "excluded_count": len(excluded),
        "draws_used": [d["date"] for d in used],
        "settings": {"draws": draws, "picks": picks, "scope": scope, "permute": permute},
    }


def score_pending() -> list[dict]:
    """Score every saved pick whose target draw is now cached."""
    all_draws = sorted(db.draws(), key=lambda d: d["date"])
    scored = []
    for p in db.unchecked_picks():
        if not p["based_on"]:
            continue
        target = next((d for d in all_draws if d["date"] > p["based_on"]), None)
        if target is None:
            continue
        result = lotto.score(p["numbers"], target["prizes"])
        db.set_result(p["id"], target["date"], result)
        scored.append({**p, "result_draw": target["date"], "result": result})
    return scored


def stats() -> dict:
    checked = db.checked_picks()
    numbers = sum(len(p["numbers"]) for p in checked)
    return {
        "picks": len(checked),
        "numbers": numbers,
        "exact_hits": sum(p["result"]["exact_hits"] for p in checked),
        "expected": round(sum(p["result"]["expected"] for p in checked), 2),
        "tod_hits": sum(
            1 for p in checked for h in p["result"]["hits"] if h["kinds"] == ["first3_tod"]
        ),
    }
