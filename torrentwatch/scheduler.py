"""
APScheduler jobs for TorrentWatch.
Scrapes all enabled sources every 30 min from 19:00–00:30 Asia/Bangkok.
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
        # If somehow called from within a running loop, schedule as future
        asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=120)
    except RuntimeError:
        # No running event loop in this thread (normal case for BackgroundScheduler)
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
    settings    = db.get_settings()
    seed_min    = int(settings.get("seed_min", 5))
    leech_min   = int(settings.get("leech_min", 10))
    filter_mode = settings.get("filter_mode", "and")

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
            entries = await scraper.scrape_source(
                source_url, seed_min, leech_min, keywords, filter_mode,
                on_page=lambda pg, n: _update_progress(source_label, pg, total_found + n),
            )
        except Exception as e:
            print(f"[scheduler] scrape error {source_url}: {e}")
            entries = []

        for entry in entries:
            db.upsert_torrent(source_id, entry["site_id"], entry)

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


def _build_scrape_trigger(interval: int, all_day: bool) -> CronTrigger:
    minute = "0,30" if interval == 30 else "0"
    if all_day:
        return CronTrigger(minute=minute, timezone=config.TZ)
    else:
        return CronTrigger(hour="19,20,21,22,23,0,1", minute=minute, timezone=config.TZ)


def reload_scrape_job():
    """Rebuild scrape job from current DB settings — call after settings change."""
    settings = db.get_settings()
    interval  = int(settings.get("scrape_interval", "30"))
    all_day   = settings.get("scrape_all_day", "0") == "1"
    trigger   = _build_scrape_trigger(interval, all_day)
    _scheduler.add_job(_scrape_job, trigger, id="scrape", replace_existing=True)
    label = f"ทุก {interval} นาที {'ทั้งวัน' if all_day else '19:00-01:00'}"
    print(f"[scheduler] scrape job reloaded — {label}")
    # Only update next_run_time if scheduler is already running
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
    _update_next()   # scheduler is now running — safe to read next_run_time
    print("[scheduler] started")


def stop():
    _scheduler.shutdown(wait=False)


def _update_next():
    global _next_scrape
    try:
        job = _scheduler.get_job("scrape")
        if not job:
            return
        nrt = getattr(job, "next_run_time", None)
        if nrt:
            _next_scrape = nrt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass


def status() -> dict:
    _update_next()
    return {
        "last_scrape":    _last_scrape,
        "next_scrape":    _next_scrape,
        "scrape_status":  _scrape_status,
        "scraper_ready":  scraper.is_ready(),
        "scrape_progress": _scrape_progress,
    }


async def trigger_now():
    """Manual scrape trigger from API."""
    await _do_scrape()
