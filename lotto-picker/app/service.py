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
                inserted = db.add_draw(latest)
                if inserted and not first_boot:
                    fresh = latest
                elif not inserted:
                    db.repair_last2(latest)
            else:
                logger.info("draw %s still in progress, not caching", latest["date"])

        _repair_cached(want, latest, fetch_on, sleep)
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


def _repair_cached(want: int, latest: dict | None, fetch_on, sleep) -> None:
    """Repair recent legacy rows and older targets that block pending two picks."""
    cached = db.draws()
    candidates = {draw["date"]: draw for draw in cached[:want]}
    ascending = list(reversed(cached))
    for saved in db.unchecked_picks():
        if saved["settings"]["digits"] != 2 or not saved["based_on"]:
            continue
        target = next((d for d in ascending if d["date"] > saved["based_on"]), None)
        if target:
            candidates[target["date"]] = target
    for iso, cached_draw in candidates.items():
        if lotto.has_last2(cached_draw["prizes"]):
            continue
        # The latest response was already considered, including live/partial
        # responses. Avoid a second request for the same date in this sync.
        if latest and latest["date"] == iso:
            continue
        try:
            fetched = fetch_on(dt.date.fromisoformat(iso))
        except Exception as exc:
            logger.warning("last2 repair failed at %s: %s", iso, exc)
            continue
        sleep(PROBE_DELAY)
        if fetched and fetched["date"] == iso:
            db.repair_last2(fetched)


def based_on() -> str | None:
    seen = db.get("latest_seen")
    cached = db.draw_dates()
    return max(filter(None, [seen, *cached]), default=None)


def make_pick(draws: int, picks: int, scope: str, permute: bool, digits: int = 3) -> dict:
    if digits == 2:
        scope = "last2"
        used = [draw for draw in db.draws() if lotto.has_last2(draw["prizes"])][:draws]
    else:
        used = db.draws(limit=draws)
    excluded = lotto.excluded(used, scope, permute, digits)
    universe = lotto.ALL_TWO if digits == 2 else lotto.ALL_THREE
    available = sorted(universe - excluded)
    return {
        "numbers": lotto.pick(available, picks),
        "pool_size": len(available),
        "excluded_count": len(excluded),
        "excluded": sorted(excluded),
        "draws_used": [d["date"] for d in used],
        "settings": {
            "draws": draws, "picks": picks, "scope": scope, "permute": permute, "digits": digits,
        },
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
        digits = p["settings"]["digits"]
        if digits == 2 and not lotto.has_last2(target["prizes"]):
            continue
        result = lotto.score(p["numbers"], target["prizes"], digits)
        db.set_result(p["id"], target["date"], result)
        scored.append({**p, "result_draw": target["date"], "result": result})
    return scored


def stats(digits: int = 3) -> dict:
    checked = db.checked_picks(digits)
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
