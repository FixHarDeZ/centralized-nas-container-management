from __future__ import annotations

from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app import db, gate
from app.notifier import notify


def _quota_reset_job(db_path: str) -> None:
    # daily_quota keyed by date already, "reset" no-op — new
    # day naturally starts fresh row via db.increment_quota's upsert.
    # Kept explicit job so matches spec's stated jobs
    # so future quota-notification hook somewhere live.
    pass


def breaker_auto_reset_job(db_path: str) -> None:
    conn = db.get_conn(db_path)
    try:
        for row in db.list_monitored_containers(conn):
            if gate.is_breaker_tripped(conn, row["name"]):
                gate.maybe_reset_breaker(conn, row["name"])
    finally:
        conn.close()


def daily_digest_job(db_path: str) -> None:
    conn = db.get_conn(db_path)
    try:
        now = datetime.now(UTC)
        lines = []
        for row in db.list_monitored_containers(conn):
            if gate.is_breaker_tripped(conn, row["name"]):
                count = gate.count_new_fingerprints_since(conn, row["name"], now.replace(hour=0, minute=0, second=0, microsecond=0))
                lines.append(f"- {row['name']}: {count} new fingerprints today, breaker tripped")
        if lines:
            notify("📋 log-medic daily digest (18:00)\n" + "\n".join(lines))
    finally:
        conn.close()


def setup_scheduler(db_path: str | None = None) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Bangkok")
    scheduler.add_job(_quota_reset_job, CronTrigger(hour=0, minute=0), id="daily_quota_reset", args=[db_path])
    scheduler.add_job(breaker_auto_reset_job, IntervalTrigger(minutes=30), id="breaker_auto_reset", args=[db_path])
    scheduler.add_job(daily_digest_job, CronTrigger(hour=18, minute=0), id="daily_digest", args=[db_path])
    return scheduler
