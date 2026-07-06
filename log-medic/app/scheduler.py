from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app import analyzer, db, deployer, gate
from app.notifier import notify

logger = logging.getLogger(__name__)


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


def poll_pr_merges_job(db_path: str | None = None) -> None:
    """Every 5 min: check each pr_opened event's PR state on GitHub.
    MERGED -> deploy; CLOSED -> mark pr_closed + delete remote branch.
    Per-event errors are logged and retried next cycle — never crash the job."""
    conn = db.get_conn(db_path)
    try:
        for event in db.get_events_by_status(conn, "pr_opened"):
            name = event["container"]
            try:
                row = db.get_monitored_container(conn, name)
                if row is None or not event["pr_url"]:
                    continue
                workspace = analyzer.workspace_dir(row)
                result = subprocess.run(
                    ["gh", "pr", "view", event["pr_url"], "--json", "state,mergedAt"],
                    cwd=workspace, capture_output=True, text=True, check=True, timeout=60,
                )
                state = json.loads(result.stdout).get("state")
                if state == "MERGED":
                    db.update_event_status(conn, event["fingerprint"], name, status="merged")
                    deployer.deploy(conn, row, event["fingerprint"], event["pr_url"])
                elif state == "CLOSED":
                    db.update_event_status(conn, event["fingerprint"], name, status="pr_closed")
                    subprocess.run(
                        ["git", "push", "origin", "--delete", f"fix/{event['fingerprint']}"],
                        cwd=workspace, capture_output=True, text=True,
                    )  # best-effort, no check=True
                    notify(f"🚮 PR closed without merge for {name}, no deploy\n{event['pr_url']}")
                # OPEN: leave as-is
            except Exception:
                logger.exception("poll_pr_merges: %s/%s failed, retrying next cycle",
                                 name, event["fingerprint"])
    finally:
        conn.close()


def setup_scheduler(db_path: str | None = None) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Bangkok")
    scheduler.add_job(_quota_reset_job, CronTrigger(hour=0, minute=0), id="daily_quota_reset", args=[db_path])
    scheduler.add_job(breaker_auto_reset_job, IntervalTrigger(minutes=30), id="breaker_auto_reset", args=[db_path])
    scheduler.add_job(daily_digest_job, CronTrigger(hour=18, minute=0), id="daily_digest", args=[db_path])
    scheduler.add_job(poll_pr_merges_job, IntervalTrigger(minutes=5), id="poll_pr_merges", args=[db_path])
    scheduler.start()
    return scheduler
