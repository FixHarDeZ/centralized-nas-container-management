import os
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta

from app.db import event_exists, get_today_quota

GRACE_PERIOD_MINUTES = int(os.getenv("GRACE_PERIOD_MINUTES", "15"))
COOLDOWN_HOURS = int(os.getenv("COOLDOWN_HOURS", "6"))
DAILY_QUOTA = int(os.getenv("DAILY_QUOTA", "50"))
STORM_THRESHOLD_PER_HOUR = int(os.getenv("STORM_THRESHOLD_PER_HOUR", "10"))
REPO_IDLE_HOURS = int(os.getenv("REPO_IDLE_HOURS", "24"))


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
    if not event_exists(conn, fingerprint, container):
        return False
    row = conn.execute(
        "SELECT first_seen FROM events WHERE fingerprint=? AND container=?",
        (fingerprint, container),
    ).fetchone()
    if not row:
        return False
    first_seen = datetime.fromisoformat(row["first_seen"])
    return (now - first_seen).total_seconds() < COOLDOWN_HOURS * 3600


def quota_exceeded(conn: sqlite3.Connection) -> bool:
    """Check if daily quota exceeded."""
    return get_today_quota(conn) >= DAILY_QUOTA


def check_dirty_repo(workspace_dir: str, fingerprint: str, now: datetime | None = None) -> bool:
    """Check if repo is dirty (has uncommitted changes, recent commits, or active fix branch)."""
    now = now or datetime.now(UTC)

    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=workspace_dir, capture_output=True, text=True, check=True
        ).stdout.strip()
        if status:
            return True
    except subprocess.CalledProcessError:
        return False

    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=workspace_dir, capture_output=True, text=True, check=True
        ).stdout.strip()
        if branch != "main" and branch != "master":
            return True
    except subprocess.CalledProcessError:
        return False

    try:
        last_commit_ts = subprocess.run(
            ["git", "log", "-1", "--format=%ct"], cwd=workspace_dir, capture_output=True, text=True, check=True
        ).stdout.strip()
        last_commit_dt = datetime.fromtimestamp(int(last_commit_ts), tz=UTC)
        if (now - last_commit_dt) < timedelta(hours=REPO_IDLE_HOURS):
            return True
    except subprocess.CalledProcessError:
        return False

    try:
        branches = subprocess.run(
            ["git", "branch", "-a"], cwd=workspace_dir, capture_output=True, text=True, check=True
        ).stdout
        if f"fix/{fingerprint}" in branches:
            return True
    except subprocess.CalledProcessError:
        pass

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
