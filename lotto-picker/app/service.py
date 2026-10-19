"""Glue between GLO, the DB and the pure logic: sync, history, pick, score,
stats, ledger.

Fetchers and the clock are parameters so tests drive this without a network.
"""

from __future__ import annotations

import datetime as dt
import logging
import threading
import time

from . import analysis, db, glo, lotto

logger = logging.getLogger(__name__)

MAX_DRAWS = 24
# A backfill walk gives up after this many days without finding a draw —
# guards against probing forever if GLO's history endpoint changes shape.
MAX_GAP_DAYS = 45
PROBE_DELAY = 0.3

_lock = threading.Lock()
# The deep history walk takes ~15 minutes on first run. It has its own lock so
# saving a pick or the results poll (which hold _lock) never wait behind it.
_history_lock = threading.Lock()
_cache: dict = {}


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
            if latest.get("amounts"):
                db.put("prize_amounts", latest["amounts"])
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


def _status(**fields) -> None:
    db.put("history_status", {**db.get("history_status", {}), **fields,
                              "updated": dt.datetime.now().isoformat(timespec="seconds")})


def backfill_history(fetch_on=None, today=None, sleep=time.sleep) -> dict:
    """Cache every draw from ``lotto.HISTORY_START`` to yesterday, resumably.

    Unlike ``sync``'s walk this never gives up on a long gap (draws were
    suspended for months in 2020). Pass one probes every candidate day not yet
    known; pass two probes *every* day of any finished month still short of two
    draws, which finds draws moved off the usual days. Progress lives in the DB:
    ``draws`` and ``nodraw`` grow as it goes, and non-null payloads that are not
    a complete draw go to kv ``history_skipped`` so they are not asked again.
    Must not run before the first results poll, or that poll's first-boot check
    would read a full table and announce an old draw as news.
    """
    fetch_on = fetch_on or glo.on
    today = today or dt.date.today()
    if not _history_lock.acquire(blocking=False):
        return db.get("history_status", {})
    try:
        skipped = set(db.get("history_skipped", []))

        def known() -> set[str]:
            return db.draw_dates() | db.nodraw_dates() | skipped

        def probe(days: list[dt.date], done: int, total: int) -> tuple[int, bool]:
            for day in days:
                try:
                    draw = fetch_on(day)
                except Exception as exc:
                    logger.warning("history backfill stopped at %s: %s", day, exc)
                    _status(state="error", error=str(exc)[:200])
                    return done, False
                sleep(PROBE_DELAY)
                iso = day.isoformat()
                if draw is None:
                    db.add_nodraw(iso)
                elif draw["date"] == iso and lotto.is_complete(draw["prizes"]):
                    db.add_draw(draw)
                else:
                    skipped.add(iso)
                    db.put("history_skipped", sorted(skipped))
                done += 1
                if done % 20 == 0:
                    _status(state="running", probed=done, todo=total, draws=len(history(3)))
            return done, True

        have = known()
        first = [
            day for day in _days(lotto.HISTORY_START, today)
            if day.day in lotto.CANDIDATE_DAYS and day.isoformat() not in have
        ]
        _status(state="running", probed=0, todo=len(first), error=None)
        done, ok = probe(first, 0, len(first))
        if not ok:
            return db.get("history_status", {})

        have = known()
        found = db.draw_dates()
        month_start = today.replace(day=1)
        second = []
        for day in _days(lotto.HISTORY_START, month_start):
            prefix = day.isoformat()[:7]
            if sum(1 for d in found if d.startswith(prefix)) < 2 and day.isoformat() not in have:
                second.append(day)
        done, ok = probe(second, done, done + len(second))
        if ok:
            _status(state="done", probed=done, todo=done, draws=len(history(3)), error=None)
        return db.get("history_status", {})
    finally:
        _history_lock.release()


def _days(start: dt.date, end: dt.date):
    """Every day from ``start`` up to, not including, ``end``."""
    day = start
    while day < end:
        yield day
        day += dt.timedelta(days=1)


def history(digits: int = 3) -> list[dict]:
    """Cached draws usable for statistics, newest first."""
    floor = lotto.HISTORY_START.isoformat()
    return [
        d for d in db.draws()
        if d["date"] >= floor and (digits == 3 or lotto.has_last2(d["prizes"]))
    ]


def _cached(key: tuple, build):
    """Memoise per latest cached draw — results only change when a draw lands."""
    stamp = (max(db.draw_dates(), default=None), len(db.draw_dates()))
    hit = _cache.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    value = build()
    if len(_cache) > 64:
        _cache.clear()
    _cache[key] = (stamp, value)
    return value


def frequency(digits: int, category: str, window: int = 0) -> dict:
    def build():
        draws = history(digits)
        return analysis.frequency(draws[:window] if window else draws, digits, category)
    return _cached(("freq", digits, category, window), build)


def backtest(digits: int, picks: int, exclude_draws: int, scope: str, permute: bool,
             window: int = 0) -> dict:
    return _cached(
        ("backtest", digits, picks, exclude_draws, scope, permute, window),
        lambda: analysis.backtest(history(digits), digits, picks, exclude_draws, scope,
                                  permute, window),
    )


def based_on() -> str | None:
    seen = db.get("latest_seen")
    cached = db.draw_dates()
    return max(filter(None, [seen, *cached]), default=None)


def make_pick(
    draws: int, picks: int, scope: str, permute: bool, digits: int = 3,
    style: str = "random", stat_window: int = 0,
) -> dict:
    """Exclude recent draws, then pick at random from the style's candidates.

    Every style has the same odds; a style only decides *which* equally likely
    numbers you draw from. ``reasons`` is history shown next to each number,
    never a probability.
    """
    if digits == 2:
        scope = "last2"
    hist = history(digits)
    used = hist[:draws] if digits == 2 else db.draws(limit=draws)
    excluded = lotto.excluded(used, scope, permute, digits)
    universe = lotto.ALL_TWO if digits == 2 else lotto.ALL_THREE
    available = sorted(universe - excluded)
    window = hist[:stat_window] if stat_window else hist
    counts, gaps, _ = analysis.counts_and_gaps(window, digits, analysis.style_category(digits))
    candidates = analysis.style_candidates(available, counts, gaps, style, picks)
    numbers = lotto.pick(candidates, picks)
    return {
        "numbers": numbers,
        "pool_size": len(available),
        "candidates": len(candidates),
        "excluded_count": len(excluded),
        "excluded": sorted(excluded),
        "draws_used": [d["date"] for d in used],
        "history_draws": len(window),
        "reasons": analysis.reasons(numbers, counts, gaps, len(window)),
        "settings": {
            "draws": draws, "picks": picks, "scope": scope, "permute": permute, "digits": digits,
            "style": style, "stat_window": stat_window,
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


# --- ledger --------------------------------------------------------------------


def prize_amounts() -> dict[str, int]:
    return {**lotto.PRIZE_AMOUNTS, **db.get("prize_amounts", {})}


def ledger() -> dict:
    """Entries with their prize resolved, plus the running totals.

    A manual ``prize`` wins; otherwise tickets are checked against the cached
    draw for that date. No cached draw yet = pending, counted in cost only.
    """
    amounts = prize_amounts()
    by_date = {d["date"]: d["prizes"] for d in db.draws()}
    entries = []
    for e in db.ledger():
        drawn = _resolve_draw(e["draw_date"], by_date)
        prizes = by_date.get(drawn)
        wins = []
        if prizes is not None:
            for t in e["tickets"]:
                kinds = lotto.ticket_prizes(t["number"], prizes)
                if kinds:
                    wins.append({"number": t["number"], "qty": t["qty"], "kinds": kinds,
                                 "amount": lotto.ticket_value(t["number"], prizes, amounts) * t["qty"]})
        if e["prize"] is not None:
            won, status = e["prize"], "manual"
        elif prizes is None:
            won, status = None, "pending"
        else:
            won = sum(w["amount"] for w in wins)
            status = "won" if won else "lost"
        entries.append({**e, "result_draw": drawn, "wins": wins, "won": won, "status": status})
    settled = [e for e in entries if e["status"] != "pending"]
    cost = sum(e["cost"] for e in settled)
    won = sum(e["won"] for e in settled)
    return {
        "entries": entries,
        "summary": {
            "entries": len(entries),
            "pending": len(entries) - len(settled),
            "cost": cost,
            "pending_cost": sum(e["cost"] for e in entries if e["status"] == "pending"),
            "won": won,
            "net": won - cost,
            "return": round(won / cost, 4) if cost else None,
            "expected_return": round(lotto.expected_return(amounts), 4),
            "ticket_price": lotto.TICKET_PRICE,
        },
    }


LEDGER_SHIFT_DAYS = 5


def _resolve_draw(date: str, cached: dict) -> str | None:
    """The cached draw an entry belongs to. Entries made before a draw carry its
    *nominal* date (1st/16th) but GLO moves draws — 30 Dec instead of 1 Jan
    every year, 17 Jan, 2 May — so the nearest cached draw within a few days
    counts as that draw. Draws are ~15 days apart, so this cannot grab the
    neighbouring one."""
    if date in cached:
        return date
    day = dt.date.fromisoformat(date)
    near = [
        (abs((dt.date.fromisoformat(d) - day).days), d) for d in cached
        if abs((dt.date.fromisoformat(d) - day).days) <= LEDGER_SHIFT_DAYS
    ]
    return min(near)[1] if near else None


def check_ticket(number: str, date: str | None = None) -> dict | None:
    """What one 6-digit ticket won in a cached draw (latest when no date)."""
    draws = db.draws()
    draw = next((d for d in draws if d["date"] == date), None) if date else (draws[0] if draws else None)
    if draw is None:
        return None
    amounts = prize_amounts()
    kinds = lotto.ticket_prizes(number, draw["prizes"])
    return {
        "number": number,
        "date": draw["date"],
        "kinds": kinds,
        "amounts": {k: amounts[k] for k in kinds},
        "total": sum(amounts[k] for k in kinds),
    }
