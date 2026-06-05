import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_config  # DB_PATH removed — db_path passed in
from app.fetcher import fetch_all
from app.models import (
    delete_articles_older_than,
    get_conn,
    get_digest_history,
    get_recent_articles_for_digest,
    insert_digest_log,
    select_digest_articles,
    snapshot_all_prices,
)
from app.notifier import send_digest, send_summarizer_alert
from app.pricer import fetch_prices

_ALERT_THRESHOLD = 2  # consecutive empty digests before alerting
_ALERT_COOLDOWN_HOURS = 6  # minimum hours between repeated alerts


def _load_summarizer_state(data_dir: Path) -> dict:
    p = data_dir / "summarizer_state.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            pass
    return {"consecutive_empty": 0, "last_alert_at": None}


def _save_summarizer_state(data_dir: Path, state: dict) -> None:
    try:
        (data_dir / "summarizer_state.json").write_text(json.dumps(state))
    except Exception as exc:
        logger.warning("Could not save summarizer state: %s", exc)

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
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        conn = get_conn(db_path)
        try:
            snapped = snapshot_all_prices(conn, today)
            logger.info("price_job snapshot: %d rows for %s", snapped, today)
        finally:
            conn.close()

    def _cleanup_job() -> None:
        days = int(get_config().get("retention_days", 30))
        conn = get_conn(db_path)
        try:
            deleted = delete_articles_older_than(conn, days)
            logger.info("cleanup_job done: %d articles older than %dd deleted", deleted, days)
        finally:
            conn.close()

    def _digest_job() -> None:
        config = get_config()
        conn = get_conn(db_path)
        data_dir = Path(db_path).parent
        try:
            history = get_digest_history(conn, limit=20)
            sent_ids = {aid for entry in history for aid in entry["article_ids"]}
            candidates = get_recent_articles_for_digest(conn, hours=12, limit=50)
            articles = select_digest_articles(candidates, sent_ids)
            sent = send_digest(articles, config)
            if sent and articles:
                insert_digest_log(
                    conn,
                    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    [a["id"] for a in articles],
                    ",".join(sent),
                )
            logger.info("digest_job sent to: %s", sent)

            # Alert if summarizer appears broken (candidates exist but none have summaries)
            state = _load_summarizer_state(data_dir)
            if candidates and not articles:
                state["consecutive_empty"] = state.get("consecutive_empty", 0) + 1
                logger.warning(
                    "digest_job: %d candidates but 0 articles sent (consecutive_empty=%d)",
                    len(candidates), state["consecutive_empty"],
                )
                if state["consecutive_empty"] >= _ALERT_THRESHOLD:
                    last = state.get("last_alert_at")
                    now = datetime.now(timezone.utc)
                    cooldown_ok = last is None or (
                        now - datetime.fromisoformat(last) > timedelta(hours=_ALERT_COOLDOWN_HOURS)
                    )
                    if cooldown_ok:
                        send_summarizer_alert(config)
                        state["last_alert_at"] = now.isoformat()
                        state["consecutive_empty"] = 0
                        logger.warning("summarizer_alert sent")
            else:
                state["consecutive_empty"] = 0
            _save_summarizer_state(data_dir, state)
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

    scheduler.add_job(
        _cleanup_job,
        trigger=CronTrigger(hour=3, minute=30),
        id="cleanup_job",
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
