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
import app.booru as booru
import app.reddit as reddit
from app.notify import Notifier, TgCreds
import app.photos_albums as photos_albums

logger = logging.getLogger(__name__)

# Image sources by name (topic.sources selects which run). Each exposes the
# same interface: search(terms, purpose, sorting) -> [{"id", "path"}] and
# download_image(url) -> bytes.
_SOURCES = {"wallhaven": wallhaven, "booru": booru, "reddit": reddit}

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


def run_topic_cycle(topic_id: int) -> int:
    topic = db.get_topic(topic_id)
    if topic is None or not topic["enabled"]:
        return 0

    if topic["search_terms"]:
        search_terms = topic["search_terms"]
    else:
        search_terms = llm.expand_query(topic["query"])
        db.set_search_terms(topic_id, search_terms)

    sorting = "toplist" if not topic["backfilled"] else "date_added"
    slug = slugify(topic["query"])

    downloaded = 0
    for purpose in topic["purposes"]:
        if purpose not in wallhaven.PURPOSE_PRESETS:
            logger.warning("unknown purpose=%s topic=%s — skipping (removed preset or stale data)", purpose, topic_id)
            continue
        downloaded += _run_purpose(topic_id, purpose, search_terms, sorting, topic["max_new_per_cycle"], slug, topic["sources"])

    # An empty toplist result is a valid, completed outcome (niche topics can
    # genuinely have nothing in Wallhaven's toplist window) — advance to
    # date_added regardless, so the topic isn't stuck retrying toplist forever.
    # Only a raised exception (network/API failure) should skip this and retry.
    if not topic["backfilled"]:
        db.mark_backfilled(topic_id)

    # No sync_albums() here: freshly written files aren't indexed by Synology
    # Photos yet, so an immediate sync sees nothing. The periodic 5-min job
    # (start_all) picks them up once indexing catches up.
    return downloaded


def _run_purpose(
    topic_id: int,
    purpose: str,
    search_terms: list[str],
    sorting: str,
    max_new: int,
    slug: str,
    sources: list[str],
) -> int:
    new_count = 0
    # max_new is a per-purpose cap shared across sources, filled in list order.
    # ponytail: first source with fresh content wins the quota each cycle;
    # once it's exhausted (download_exists skips it) the next source fills in.
    # Add per-source sub-quotas here if a spammy source ever starves a good one.
    for src_name in sources:
        if new_count >= max_new:
            break
        src = _SOURCES.get(src_name)
        if src is None:
            logger.warning("unknown source=%s topic=%s — skipping", src_name, topic_id)
            continue
        try:
            results = src.search(search_terms, purpose, sorting)
        except Exception as exc:
            logger.warning("search failed topic=%s purpose=%s source=%s: %s", topic_id, purpose, src_name, exc)
            continue
        for item in results:
            if new_count >= max_new:
                break
            image_id = item["id"]
            if db.download_exists(topic_id, purpose, image_id):
                continue
            try:
                image_bytes = src.download_image(item["path"])
            except Exception as exc:
                logger.warning("download failed topic=%s purpose=%s id=%s: %s", topic_id, purpose, image_id, exc)
                continue
            # Strip any query string before the extension — reddit preview URLs
            # carry ?width=...&s=... which would otherwise land in the filename.
            ext = item["path"].rsplit("?", 1)[0].rsplit(".", 1)[-1]
            dest_dir = _PHOTOS_ROOT / purpose / slug
            dest_dir.mkdir(parents=True, exist_ok=True)
            # Touch parent dirs to trigger Synology Photos folder indexing.
            # New folders created by the container aren't visible to Photos until touched.
            for d in [dest_dir, dest_dir.parent, dest_dir.parent.parent]:
                if d.exists() and d != Path("/"):
                    os.utime(d, None)
            # image_id may be namespaced ("yr:123"); ":" is legal on the volume
            # but keep filenames clean with "-".
            filename = f"{image_id.replace(':', '-')}.{ext}"
            dest_path = dest_dir / filename
            dest_path.write_bytes(image_bytes)
            # Touch file to trigger Synology Photos indexing (doesn't auto-index
            # files written by the container — needs a filesystem mtime change).
            os.utime(dest_path, None)
            db.record_download(topic_id, purpose, image_id, filename)
            new_count += 1
    return new_count


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

    # Periodic album sync — picks up files once the host-side cron touch (every
    # 2 min) has let Synology index them. Kept at 2 min to match the cron cadence
    # so a fresh Scout lands in albums within ~2-4 min instead of waiting a cycle.
    sched.add_job(
        photos_albums.sync_albums,
        trigger=IntervalTrigger(minutes=2),
        id="album-sync",
        replace_existing=True,
    )
