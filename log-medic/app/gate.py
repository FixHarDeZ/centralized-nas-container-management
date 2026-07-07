from __future__ import annotations

import os
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta

GRACE_PERIOD_MINUTES = int(os.environ.get("GRACE_PERIOD_MINUTES", "20"))
COOLDOWN_HOURS = int(os.environ.get("COOLDOWN_HOURS", "6"))
DAILY_QUOTA = int(os.environ.get("DAILY_QUOTA", "5"))
STORM_THRESHOLD_PER_HOUR = int(os.environ.get("STORM_THRESHOLD_PER_HOUR", "10"))
REPO_IDLE_HOURS = int(os.environ.get("REPO_IDLE_HOURS", "2"))


def in_grace_period(started_at: datetime, now: datetime | None = None) -> bool:
    """Grace period: suppress analysis for container within first N minutes of boot."""
    now = now or datetime.now(UTC)
    return (now - started_at).total_seconds() < GRACE_PERIOD_MINUTES * 60


def count_new_fingerprints_since(conn: sqlite3.Connection, container: str, since: datetime) -> int:
    """Count unique fingerprints (new events) since threshold for storm detection."""
    row = conn.execute(
        "SELECT COUNT(*) c FROM events WHERE container=? AND first_seen > ?",
        (container, since.isoformat()),
    ).fetchone()
    return row["c"]


def is_breaker_tripped(conn: sqlite3.Connection, container: str) -> bool:
    """Circuit breaker: tripped if tripped_at is not NULL."""
    row = conn.execute(
        "SELECT tripped_at FROM circuit_breaker WHERE container=?", (container,)
    ).fetchone()
    return bool(row and row["tripped_at"])


def maybe_trip_breaker(conn: sqlite3.Connection, container: str, now: datetime | None = None) -> None:
    """Trip breaker if storm detected (N+ new fingerprints in 1 hour)."""
    now = now or datetime.now(UTC)
    if is_breaker_tripped(conn, container):
        return
    if count_new_fingerprints_since(conn, container, now - timedelta(hours=1)) >= STORM_THRESHOLD_PER_HOUR:
        conn.execute(
            "INSERT INTO circuit_breaker (container, tripped_at, last_new_fp_at) VALUES (?, ?, ?) "
            "ON CONFLICT(container) DO UPDATE SET tripped_at=excluded.tripped_at, last_new_fp_at=excluded.last_new_fp_at",
            (container, now.isoformat(), now.isoformat()),
        )
        conn.commit()


def maybe_reset_breaker(conn: sqlite3.Connection, container: str, now: datetime | None = None) -> bool:
    """Called periodically by scheduler. Resets tripped breaker once 6h pass with no new fingerprint for container. Returns True if reset."""
    now = now or datetime.now(UTC)
    if not is_breaker_tripped(conn, container):
        return False
    if count_new_fingerprints_since(conn, container, now - timedelta(hours=6)) == 0:
        conn.execute(
            "UPDATE circuit_breaker SET tripped_at=NULL WHERE container=?", (container,)
        )
        conn.commit()
        return True
    return False


def in_cooldown(conn: sqlite3.Connection, fingerprint: str, container: str, now: datetime | None = None) -> bool:
    """Cooldown: suppress re-analysis of same fingerprint within N hours."""
    now = now or datetime.now(UTC)
    row = conn.execute(
        "SELECT last_seen FROM events WHERE fingerprint=? AND container=?",
        (fingerprint, container),
    ).fetchone()
    if not row:
        return False
    last_seen = datetime.fromisoformat(row["last_seen"])
    return now - last_seen < timedelta(hours=COOLDOWN_HOURS)


def quota_exceeded(conn: sqlite3.Connection) -> bool:
    """Check if daily quota exceeded."""
    from app import db

    return db.get_today_quota(conn) >= DAILY_QUOTA


def check_dirty_repo(workspace_dir: str, fingerprint: str, now: datetime | None = None) -> bool:
    """Check if repo is dirty (has uncommitted changes, recent commits, or active fix branch).
    Returns False if workspace is not a git repo (e.g. container has no repo configured)."""
    now = now or datetime.now(UTC)

    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=workspace_dir, capture_output=True, text=True, check=True
        ).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    if status.strip():
        return True

    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=workspace_dir, capture_output=True, text=True, check=True
    ).stdout.strip()
    if branch not in ("main", "master"):
        return True

    last_commit_ts = subprocess.run(
        ["git", "log", "-1", "--format=%ct"], cwd=workspace_dir, capture_output=True, text=True, check=True
    ).stdout.strip()
    if last_commit_ts:
        last_commit_dt = datetime.fromtimestamp(int(last_commit_ts), tz=UTC)
        if now - last_commit_dt < timedelta(hours=REPO_IDLE_HOURS):
            return True

    branches = subprocess.run(
        ["git", "branch", "-a"], cwd=workspace_dir, capture_output=True, text=True, check=True
    ).stdout
    if f"fix/{fingerprint}" in branches:
        return True

    return False


def evaluate(
    conn: sqlite3.Connection,
    container: sqlite3.Row,
    fingerprint: str,
    started_at: datetime,
    workspace_dir: str,
    now: datetime | None = None,
) -> str | None:
    """Gates 2-5 (grace period, circuit breaker, cooldown/quota, dirty repo).
    Gate 1 (maturity) and notify_only routing happen in watcher.py.
    Never called if already triggered. Returns gate_reason to record, None to proceed to analyzer phase 1."""
    now = now or datetime.now(UTC)
    name = container["name"]

    if in_grace_period(started_at, now):
        return "grace_period"
    if is_breaker_tripped(conn, name):
        return "circuit_breaker"
    if in_cooldown(conn, fingerprint, name, now):
        return "cooldown"
    if quota_exceeded(conn):
        return "quota"
    if check_dirty_repo(workspace_dir, fingerprint, now):
        return "dirty_repo"
    return None
