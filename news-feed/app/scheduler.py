import json
import logging
from datetime import datetime, timezone, timedelta
from datetime import time as _time
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_config  # DB_PATH removed — db_path passed in
from app.sqlite_backup import backup_db
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

_MIN_WINDOW_HOURS = 4.0
_MAX_WINDOW_HOURS = 36.0
_FALLBACK_WINDOW_HOURS = 12.0


def _parse_digest_times(raw: list[str]) -> list[_time]:
    """Parse 'HH:MM' strings → sorted unique time objects. Invalid entries silently dropped."""
    seen: set[tuple[int, int]] = set()
    out: list[_time] = []
    for s in raw:
        try:
            h, m = s.strip().split(":")
            t = _time(int(h), int(m))
        except (ValueError, AttributeError):
            continue
        key = (t.hour, t.minute)
        if key in seen:
            continue
        seen.add(key)
        out.append(t)
    out.sort()
    return out


def _compute_digest_window(
    now: datetime,
    digest_times: list[str],
    buffer_hours: float = 1.0,
) -> float:
    """Lookback hours = (now - previous digest tick) + buffer, clamped to [4, 36].

    If `digest_times` is empty or all invalid, returns 12.0 (legacy default).

    Raises:
        ValueError: if `now` is naive (no tzinfo).
    """
    if now.tzinfo is None:
        raise ValueError("_compute_digest_window: 'now' must be timezone-aware")
    times = _parse_digest_times(digest_times)
    if not times:
        return _FALLBACK_WINDOW_HOURS

    # Floor `now` to the minute so a digest tick that fired a few microseconds late
    # (APScheduler fires at HH:MM:00.xxxxxx) doesn't treat the current tick as its
    # own previous tick — wrap to the prior tick / yesterday instead.
    now_minute = now.replace(second=0, microsecond=0)
    today = now.date()
    candidates_today = [
        datetime.combine(today, t, tzinfo=now.tzinfo) for t in times
    ]
    prev_ticks = [d for d in candidates_today if d < now_minute]
    if prev_ticks:
        prev = max(prev_ticks)
    else:
        # Wrap to yesterday's last tick
        yesterday = today - timedelta(days=1)
        prev = datetime.combine(yesterday, times[-1], tzinfo=now.tzinfo)

    gap_hours = (now - prev).total_seconds() / 3600.0
    window = gap_hours + buffer_hours
    return max(_MIN_WINDOW_HOURS, min(_MAX_WINDOW_HOURS, window))


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
            bkk = ZoneInfo("Asia/Bangkok")
            now_local = datetime.now(bkk)
            window_hours = _compute_digest_window(
                now_local,
                config.get("digest_times", ["07:00", "12:00", "18:00"]),
                buffer_hours=float(config.get("digest_window_buffer_hours", 1.0)),
            )
            history = get_digest_history(conn, limit=20)
            sent_ids = {aid for entry in history for aid in entry["article_ids"]}
            candidates = get_recent_articles_for_digest(conn, hours=window_hours, limit=100)
            unsent_candidates = [c for c in candidates if c["id"] not in sent_ids]
            base = int(float(config.get("digest_size_base", 5)))
            size_max = int(float(config.get("digest_size_max", 10)))
            extra_max = max(0, size_max - base)
            articles = select_digest_articles(
                candidates, sent_ids,
                base=base,
                extra_max=extra_max,
                max_per_source=int(float(config.get("digest_max_per_source", 2))),
            )
            sent = send_digest(articles, config)
            if sent and articles:
                insert_digest_log(
                    conn,
                    datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    [a["id"] for a in articles],
                    ",".join(sent),
                )
            logger.info(
                "digest_job sent to: %s (window=%.1fh, candidates=%d, selected=%d)",
                sent, window_hours, len(candidates), len(articles),
            )

            # Alert if summarizer appears broken (candidates exist but none have summaries)
            state = _load_summarizer_state(data_dir)
            if unsent_candidates and not articles:
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

    def _backup_job() -> None:
        import os
        backup_dir = os.environ.get("NEWS_FEED_BACKUP_DIR", "/data/backups")
        retention = int(os.environ.get("NEWS_FEED_BACKUP_RETENTION_DAYS", "30"))
        path = backup_db(db_path, backup_dir, prefix="news", retention_days=retention)
        if path:
            logger.info("backup_job: %s", path)
        else:
            logger.warning("backup_job: failed or nothing to backup")

    scheduler.add_job(
        _backup_job,
        trigger=CronTrigger(hour=3, minute=0),
        id="backup_job",
        replace_existing=True,
        max_instances=1,
    )

    return scheduler
