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
import line_notify
from datetime import datetime
from zoneinfo import ZoneInfo
import config

_TZ = ZoneInfo(config.TZ)
_scheduler = BackgroundScheduler(timezone=config.TZ)

_last_scrape: str = ""
_next_scrape: str = ""
_scrape_status: str = "idle"


def _run_async(coro):
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=120)
        else:
            loop.run_until_complete(coro)
    except Exception as e:
        print(f"[scheduler] async run error: {e}")


async def _do_scrape():
    global _last_scrape, _scrape_status

    _scrape_status = "running"
    now = datetime.now(_TZ)
    _last_scrape = now.strftime("%Y-%m-%d %H:%M")
    today = now.strftime("%Y-%m-%d")

    settings = db.get_settings()
    seed_min  = int(settings.get("seed_min", 10))
    leech_min = int(settings.get("leech_min", 10))
    line_enabled    = settings.get("line_notify_enabled", "1") == "1"
    line_kw_only    = settings.get("line_notify_keyword_only", "0") == "1"
    line_summary    = settings.get("line_notify_summary", "1") == "1"

    sources = db.get_enabled_sources()
    round_results = []

    for source in sources:
        source_id  = source["id"]
        source_url = source["url"]
        keywords   = db.get_keywords_for_source(source_id)

        try:
            entries = await scraper.scrape_source(source_url, seed_min, leech_min, keywords)
        except Exception as e:
            print(f"[scheduler] scrape error {source_url}: {e}")
            entries = []

        new_keyword_matches = []
        total_new = 0

        for entry in entries:
            is_new, _ = db.upsert_torrent(source_id, entry["site_id"], entry)
            if is_new:
                total_new += 1
                if entry.get("keyword_match"):
                    new_keyword_matches.append(entry)

        round_results.append({
            "source_url":    source_url,
            "total_count":   len(entries),
            "keyword_count": len(new_keyword_matches),
        })

        if line_enabled and new_keyword_matches:
            await line_notify.notify_keyword_matches(source_url, new_keyword_matches)

    if line_enabled and line_summary and not line_kw_only:
        await line_notify.notify_round_summary(round_results)

    _scrape_status = "idle"
    print(f"[scheduler] scrape done — {sum(r['total_count'] for r in round_results)} entries across {len(sources)} sources")


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
        "last_scrape":  _last_scrape,
        "next_scrape":  _next_scrape,
        "scrape_status": _scrape_status,
        "scraper_ready": scraper.is_ready(),
    }


async def trigger_now():
    """Manual scrape trigger from API."""
    await _do_scrape()
