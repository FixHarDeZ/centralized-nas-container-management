"""APScheduler jobs: per-topic scrape cycle + daily Telegram summary.

Sort strategy per topic: the first cycle after a topic is created runs
`toplist` (grab a good initial batch of existing wallpapers). Every
subsequent cycle runs `date_added` — `toplist` is a near-static ranking,
so a recurring scraper hitting it repeatedly would find zero new results
within days, making the topic's frequency setting pointless.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.base import JobLookupError

import app.db as db
import app.llm as llm
import app.wallhaven as wallhaven
from app.notify import Notifier, TgCreds

logger = logging.getLogger(__name__)

_TZ = ZoneInfo(os.environ.get("TZ", "Asia/Bangkok"))
_PHOTOS_ROOT = Path(os.environ.get("PHOTOS_ROOT", "/photos_root"))

notifier = Notifier(
    telegram=TgCreds(
        token=os.environ.get("WALLPAPER_SCOUT_TELEGRAM_BOT_TOKEN", ""),
        chat=os.environ.get("WALLPAPER_SCOUT_TELEGRAM_CHAT_ID", ""),
    )
    if os.environ.get("WALLPAPER_SCOUT_TELEGRAM_BOT_TOKEN") and os.environ.get("WALLPAPER_SCOUT_TELEGRAM_CHAT_ID")
    else None,
)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "topic"


def run_topic_cycle(topic_id: int) -> None:
    topic = db.get_topic(topic_id)
    if topic is None or not topic["enabled"]:
        return

    if topic["search_terms"]:
        search_terms = topic["search_terms"]
    else:
        search_terms = llm.expand_query(topic["query"])
        db.set_search_terms(topic_id, search_terms)

    sorting = "toplist" if not topic["backfilled"] else "date_added"
    slug = slugify(topic["query"])

    for purpose in topic["purposes"]:
        _run_purpose(topic_id, purpose, search_terms, sorting, topic["max_new_per_cycle"], slug)

    if not topic["backfilled"]:
        db.mark_backfilled(topic_id)


def _run_purpose(
    topic_id: int,
    purpose: str,
    search_terms: list[str],
    sorting: str,
    max_new: int,
    slug: str,
) -> None:
    results = wallhaven.search(search_terms, purpose, sorting)
    new_count = 0
    for item in results:
        if new_count >= max_new:
            break
        wallhaven_id = item["id"]
        if db.download_exists(topic_id, purpose, wallhaven_id):
            continue
        try:
            image_bytes = wallhaven.download_image(item["path"])
        except Exception as exc:
            logger.warning("download failed topic=%s purpose=%s id=%s: %s", topic_id, purpose, wallhaven_id, exc)
            continue
        ext = item["path"].rsplit(".", 1)[-1]
        dest_dir = _PHOTOS_ROOT / purpose / slug
        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{wallhaven_id}.{ext}"
        (dest_dir / filename).write_bytes(image_bytes)
        db.record_download(topic_id, purpose, wallhaven_id, filename)
        new_count += 1


def send_daily_summary() -> None:
    today = date.today().isoformat()
    counts = db.daily_download_counts(today)
    total = sum(counts.values())
    if total == 0:
        return
    breakdown = ", ".join(f"{query} ({n})" for query, n in counts.items())
    text = f"วันนี้ดาวน์โหลดรูปใหม่ {total} รูป: {breakdown}"
    notifier.send(text)


def schedule_topic(sched, topic: dict) -> None:
    job_id = f"topic-{topic['id']}"
    seconds = max(1, int(86400 / topic["frequency_per_day"]))
    sched.add_job(
        run_topic_cycle,
        trigger=IntervalTrigger(seconds=seconds),
        args=[topic["id"]],
        id=job_id,
        replace_existing=True,
        # IntervalTrigger's default first fire is now+interval — without this,
        # a freshly created topic (or one re-enabled) would show zero images
        # for up to a full interval, defeating the toplist backfill-on-create design.
        next_run_time=datetime.now(_TZ),
    )


def unschedule_topic(sched, topic_id: int) -> None:
    try:
        sched.remove_job(f"topic-{topic_id}")
    except JobLookupError:
        pass


def start_all(sched) -> None:
    for topic in db.list_topics():
        if topic["enabled"]:
            schedule_topic(sched, topic)

    hour, minute = os.environ.get("DAILY_SUMMARY_TIME", "09:00").split(":")
    sched.add_job(
        send_daily_summary,
        trigger=CronTrigger(hour=int(hour), minute=int(minute), timezone=_TZ),
        id="daily-summary",
        replace_existing=True,
    )
