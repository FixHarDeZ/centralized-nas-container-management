"""
APScheduler jobs for TorrentWatch.

Fixed auto-scrape schedule (Asia/Bangkok):
  19:00–01:00  every 30 minutes  (minute 0,30; hour 19-23,0)
  01:00–06:00  paused
  06:00–19:00  every 60 minutes  (minute 0; hour 6-18)

Weekly cleanup runs Sunday 03:00.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import asyncio
import db
import scraper
from datetime import datetime
from zoneinfo import ZoneInfo
import config

_TZ = ZoneInfo(config.TZ)
_scheduler = BackgroundScheduler(timezone=config.TZ)

_last_scrape:   str = ""
_next_scrape:   str = ""
_scrape_status: str = "idle"
_scrape_progress: dict = {}   # {"source": url, "page": N, "found": N}


def _run_async(coro):
    try:
        # BackgroundScheduler runs in a thread without an event loop — use asyncio.run()
        loop = asyncio.get_running_loop()
        asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=120)
    except RuntimeError:
        asyncio.run(coro)
    except Exception as e:
        print(f"[scheduler] async run error: {e}")


async def _do_scrape():
    global _last_scrape, _scrape_status

    _scrape_status = "running"
    now = datetime.now(_TZ)
    _last_scrape = now.strftime("%Y-%m-%d %H:%M")
    today = now.strftime("%Y-%m-%d")

    global _scrape_progress
    settings     = db.get_settings()
    seed_min     = int(settings.get("seed_min", 5))
    leech_min    = int(settings.get("leech_min", 10))
    filter_mode  = settings.get("filter_mode", "and")
    skip_sticky  = settings.get("scrape_sticky", "0") != "1"

    sources     = db.get_enabled_sources()
    total_found = 0

    for source in sources:
        source_id  = source["id"]
        source_url = source["url"]
        keywords   = db.get_keywords_for_source(source_id)
        from urllib.parse import urlparse
        source_label = urlparse(source_url).path.split("/")[-1] or source_url

        _scrape_progress = {"source": source_label, "page": 0, "found": 0}

        try:
            entries, seen_sticky_ids = await scraper.scrape_source(
                source_url, seed_min, leech_min, keywords, filter_mode,
                on_page=lambda pg, n: _update_progress(source_label, pg, total_found + n),
                skip_sticky=skip_sticky,
            )
        except Exception as e:
            print(f"[scheduler] scrape error {source_url}: {e}")
            entries, seen_sticky_ids = [], set()

        for entry in entries:
            db.upsert_torrent(source_id, entry["site_id"], entry)

        # Sync sticky state: refresh date for still-pinned entries, clear flag for removed ones
        if not skip_sticky:
            db.sync_stickies(source_id, seen_sticky_ids, today)

        total_found += len(entries)

    _scrape_status   = "idle"
    _scrape_progress = {}
    print(f"[scheduler] scrape done — {total_found} entries across {len(sources)} sources")


def _update_progress(source_label: str, page: int, found: int):
    global _scrape_progress
    _scrape_progress = {"source": source_label, "page": page, "found": found}


def _scrape_job():
    _run_async(_do_scrape())


def _cleanup_job():
    deleted = db.cleanup_old_records(days=7)
    print(f"[scheduler] weekly cleanup — deleted {deleted} old records")


def reload_scrape_job():
    """Set up the two fixed-schedule scrape jobs. Call after settings change if needed."""
    # Night window: 19:00–00:30  (every 30 min)
    _scheduler.add_job(
        _scrape_job,
        CronTrigger(hour="19,20,21,22,23,0", minute="0,30", timezone=config.TZ),
        id="scrape_night",
        replace_existing=True,
    )
    # Day window: 06:00–18:00  (every 60 min)
    _scheduler.add_job(
        _scrape_job,
        CronTrigger(hour="6,7,8,9,10,11,12,13,14,15,16,17,18", minute="0", timezone=config.TZ),
        id="scrape_day",
        replace_existing=True,
    )
    print("[scheduler] scrape jobs set — night (19:00-01:00 / 30min), day (06:00-19:00 / 60min)")
    if _scheduler.running:
        _update_next()


def start():
    reload_scrape_job()
    _scheduler.add_job(
        _cleanup_job,
        CronTrigger(day_of_week="sun", hour=3, timezone=config.TZ),
        id="cleanup",
        replace_existing=True,
    )
    _scheduler.start()
    _update_next()
    print("[scheduler] started")


def stop():
    _scheduler.shutdown(wait=False)


def _update_next():
    global _next_scrape
    try:
        earliest = None
        for job_id in ("scrape_night", "scrape_day"):
            job = _scheduler.get_job(job_id)
            if not job:
                continue
            nrt = getattr(job, "next_run_time", None)
            if nrt and (earliest is None or nrt < earliest):
                earliest = nrt
        if earliest:
            _next_scrape = earliest.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass


def status() -> dict:
    _update_next()
    return {
        "last_scrape":     _last_scrape,
        "next_scrape":     _next_scrape,
        "scrape_status":   _scrape_status,
        "scraper_ready":   scraper.is_ready(),
        "scrape_progress": _scrape_progress,
    }


async def trigger_now():
    """Manual scrape trigger from API."""
    await _do_scrape()
