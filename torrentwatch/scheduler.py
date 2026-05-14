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
import re
from pathlib import Path
import db
import line_notify
import scraper
from datetime import datetime
from zoneinfo import ZoneInfo
import config

_TZ = ZoneInfo(config.TZ)
_scheduler = BackgroundScheduler(timezone=config.TZ)

_last_scrape:     str  = ""
_next_scrape:     str  = ""
_scrape_status:   str  = "idle"
_scrape_progress: dict = {}   # {"source": label, "page": N, "found": N}


def _nas_filename(title: str) -> str:
    safe = re.sub(r'[^\x00-\x7F]', '_', title).strip("_ ")[:80]
    return (safe or "torrent") + ".torrent"


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
    global _last_scrape, _scrape_status, _scrape_progress

    _scrape_status = "running"
    now = datetime.now(_TZ)
    _last_scrape = now.strftime("%Y-%m-%d %H:%M")
    today = now.strftime("%Y-%m-%d")

    settings      = db.get_settings()
    seed_min      = int(settings.get("seed_min", 5))
    leech_min     = int(settings.get("leech_min", 10))
    completed_min = int(settings.get("completed_min", 20))
    filter_mode   = settings.get("filter_mode", "and")
    scrape_sticky_val = settings.get("scrape_sticky", "0")
    skip_sticky  = scrape_sticky_val != "1"
    line_notify_enabled = settings.get("line_notify_keyword_enabled", "0") == "1"
    auto_dl      = settings.get("auto_download_nas", "0") == "1"
    nas_dir      = Path(config.NAS_DOWNLOADS_DIR)
    print(f"[scheduler] scrape_sticky={scrape_sticky_val!r} → skip_sticky={skip_sticky}")

    sources     = db.get_enabled_sources()
    total_found = 0

    try:
        # Re-login each cycle to recover from stale connections after long idle periods
        if not await scraper.relogin():
            print("[scheduler] relogin failed — scrape aborted")
            return

        for i, source in enumerate(sources):
            source_id    = source["id"]
            source_url   = source["url"]
            keywords     = db.get_keywords_for_source(source_id)
            from urllib.parse import urlparse
            source_display = (source.get("label") or "").strip() or urlparse(source_url).path.split("/")[-1] or source_url
            source_total = len(sources)
            source_idx   = i + 1

            _scrape_progress = {"source": source_display, "source_idx": source_idx, "source_total": source_total, "page": 0, "found": 0}

            try:
                entries, seen_sticky_ids = await scraper.scrape_source(
                    source_url, seed_min, leech_min, keywords, filter_mode,
                    on_page=lambda pg, n, _lbl=source_display, _idx=source_idx, _tot=source_total: _update_progress(_lbl, _idx, _tot, pg, total_found + n),
                    skip_sticky=skip_sticky,
                    completed_min=completed_min,
                )
            except Exception as e:
                print(f"[scheduler] scrape error {source_url}: {e}")
                entries, seen_sticky_ids = [], set()

            new_keyword_matches: list[dict] = []
            for entry in entries:
                try:
                    is_new, torrent_id = db.upsert_torrent(source_id, entry["site_id"], entry)
                    if is_new and entry.get("keyword_match"):
                        new_keyword_matches.append({**entry, "id": torrent_id})
                except Exception as e:
                    print(f"[scheduler] upsert error {source_url} site_id={entry.get('site_id')}: {e}")

            try:
                if not skip_sticky:
                    print(f"[scheduler] calling sync_stickies — seen_sticky_ids={seen_sticky_ids}")
                    db.sync_stickies(source_id, seen_sticky_ids, today)
            except Exception as e:
                print(f"[scheduler] sync_stickies error {source_url}: {e}")

            total_found += len(entries)

            # Push LINE notification for newly-found keyword-matched torrents only
            try:
                if line_notify_enabled and new_keyword_matches:
                    await line_notify.notify_keyword_matches(source_url, new_keyword_matches)
            except Exception as e:
                print(f"[scheduler] LINE notify error {source_url}: {e}")

            # Auto-download new keyword matches directly to NAS watch folder
            if auto_dl and new_keyword_matches:
                if nas_dir.exists():
                    for match in new_keyword_matches:
                        try:
                            data = await scraper.fetch_torrent_bytes(
                                match["torrent_url"], match.get("detail_url", "")
                            )
                            if data:
                                dest = nas_dir / _nas_filename(match["title"])
                                dest.write_bytes(data)
                                db.mark_downloaded_nas(match["id"])
                                print(f"[scheduler] auto-dl: {match['title'][:50]}")
                        except Exception as e:
                            print(f"[scheduler] auto-dl error {match['title'][:30]}: {e}")
                else:
                    print("[scheduler] auto-dl: /downloads not mounted, skipping")

    finally:
        _scrape_status   = "idle"
        _scrape_progress = {}
        print(f"[scheduler] scrape done — {total_found} entries across {len(sources)} sources")


def _update_progress(source_label: str, source_idx: int, source_total: int, page: int, found: int):
    global _scrape_progress
    _scrape_progress = {"source": source_label, "source_idx": source_idx, "source_total": source_total, "page": page, "found": found}


def _scrape_job():
    _run_async(_do_scrape())


def _cleanup_job():
    settings = db.get_settings()
    days = int(settings.get("retention_days", 7))
    deleted = db.cleanup_old_records(days=days)
    print(f"[scheduler] weekly cleanup — deleted {deleted} old records (>{days} days)")


def reload_scrape_job():
    """Set up the fixed-schedule scrape jobs. Call after settings change if needed."""
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
    # End-of-day sweep: catch last-minute uploads before midnight rollover
    _scheduler.add_job(
        _scrape_job,
        CronTrigger(hour=23, minute=58, timezone=config.TZ),
        id="scrape_eod",
        replace_existing=True,
    )
    print("[scheduler] scrape jobs set — night (19:00-01:00 / 30min), day (06:00-19:00 / 60min), end-of-day (23:58)")
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
        for job_id in ("scrape_night", "scrape_day", "scrape_eod"):
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
        "line_configured": bool(config.LINE_ACCESS_TOKEN and config.LINE_USER_ID),
    }


async def trigger_now():
    """Manual scrape trigger from API."""
    await _do_scrape()
