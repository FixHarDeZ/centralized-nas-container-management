import logging
from datetime import datetime, timezone, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_config  # DB_PATH removed — db_path passed in
from app.fetcher import fetch_all
from app.models import get_conn, get_digest_history, get_recent_articles_for_digest, insert_digest_log
from app.notifier import send_digest
from app.pricer import fetch_prices

logger = logging.getLogger(__name__)


def setup_scheduler(db_path: str) -> BackgroundScheduler:
    def _fetch_job() -> None:
        config = get_config()
        logger.info("fetch_job starting")
        new_ids = fetch_all(db_path, config)
        logger.info("fetch_job done: %d new articles", len(new_ids))

    def _price_job() -> None:
        logger.info("price_job starting")
        count = fetch_prices(db_path)
        logger.info("price_job done: %d models upserted", count)

    def _digest_job() -> None:
        config = get_config()
        conn = get_conn(db_path)
        try:
            history = get_digest_history(conn, limit=20)
            sent_ids = {aid for entry in history for aid in entry["article_ids"]}
            candidates = get_recent_articles_for_digest(conn, hours=6, limit=20)
            articles = [a for a in candidates if a["id"] not in sent_ids][:5]
            sent = send_digest(articles, config)
            if sent and articles:
                insert_digest_log(
                    conn,
                    datetime.now(timezone.utc).isoformat(),
                    [a["id"] for a in articles],
                    ",".join(sent),
                )
            logger.info("digest_job sent to: %s", sent)
        finally:
            conn.close()

    scheduler = BackgroundScheduler(timezone="Asia/Bangkok")

    scheduler.add_job(
        _fetch_job,
        trigger=IntervalTrigger(minutes=60),
        id="fetch_job",
        replace_existing=True,
        max_instances=1,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=5),
    )

    scheduler.add_job(
        _price_job,
        trigger=IntervalTrigger(hours=6),
        id="price_job",
        replace_existing=True,
        max_instances=1,
    )

    config = get_config()
    for t in config.get("digest_times", ["07:00", "12:00", "18:00"]):
        hour, minute = t.split(":")
        scheduler.add_job(
            _digest_job,
            trigger=CronTrigger(hour=int(hour), minute=int(minute)),
            id=f"digest_{t.replace(':', '')}",
            replace_existing=True,
            max_instances=1,
        )

    return scheduler
