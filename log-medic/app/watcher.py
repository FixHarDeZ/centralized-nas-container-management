from __future__ import annotations

import collections
import hashlib
import re

import asyncio
import logging
import os
import threading
from datetime import UTC, datetime

import docker

from app import analyzer, db, gate
from app.notifier import notify

logger = logging.getLogger(__name__)

RECONNECT_BACKOFF_SECONDS = 5
HOT_RELOAD_INTERVAL_SECONDS = 30

DEFAULT_REGEX = re.compile(r"WARN|ERROR")

_TS_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?"
)
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
_PATH_RE = re.compile(r"(?:/[\w.\-]+){2,}")
_NUM_RE = re.compile(r"\b\d+\b")


def normalize_message(line: str) -> str:
    """Strip transient values (timestamps, UUIDs, hex/memory addresses,
    machine-specific paths, bare numbers) so recurrences of the same
    logical error hash to the same fingerprint."""
    s = _TS_RE.sub("<TS>", line)
    s = _UUID_RE.sub("<UUID>", s)
    s = _HEX_RE.sub("<HEX>", s)
    s = _PATH_RE.sub("<PATH>", s)
    s = _NUM_RE.sub("<NUM>", s)
    return s


def fingerprint(container: str, line: str) -> str:
    normalized = normalize_message(line)
    digest = hashlib.sha256(f"{container}:{normalized}".encode()).hexdigest()
    return digest[:12]


class RingBuffer:
    """Per-container sliding window: keeps up to `before` lines seen so far;
    `capture()` combines them with the trigger line and up to `after` lines
    read immediately afterward."""

    def __init__(self, before: int = 30, after: int = 10):
        self._before: collections.deque[str] = collections.deque(maxlen=before)
        self._after_max = after

    def push(self, line: str) -> None:
        self._before.append(line)

    def capture(self, trigger_line: str, tail_lines: list[str]) -> str:
        return "\n".join([*self._before, trigger_line, *tail_lines[: self._after_max]])


def _workspace_dir(container_row) -> str:
    repo = (container_row["repo"] or "").rstrip("/")
    repo_name = os.path.basename(repo)
    subdir = container_row["subdir"] or ""
    return os.path.join("/workspaces", repo_name, subdir)


def process_event(conn, container_row, fp: str, excerpt: str, trigger_line: str, started_at: datetime) -> None:
    name = container_row["name"]

    if container_row["notify_only"]:
        db.record_event(conn, fp, name, status="notified")
        notify(f"🔔 {name}\n{trigger_line}")
        return

    if container_row["maturity"] == "dev":
        db.record_event(conn, fp, name, status="new")
        return

    workspace_dir = _workspace_dir(container_row)
    reason = gate.evaluate(conn, container_row, fp, started_at, workspace_dir)
    db.record_event(conn, fp, name, status="gated" if reason else "new", gate_reason=reason)
    gate.maybe_trip_breaker(conn, name)

    if reason:
        if reason in ("quota", "dirty_repo"):
            notify(f"⏸ {name} gated ({reason})\n{trigger_line}")
        return

    analysis = analyzer.analyze(container_row, fp, excerpt)
    verdict = analysis.get("verdict", "infra")
    db.update_event_status(conn, fp, name, status="analyzed", analysis=analysis["text"], verdict=verdict)
    db.increment_quota(conn)
    icon = "🐛" if verdict == "code" else "🌐"
    notify(f"🔎 {name} [{icon} {verdict}]\nRoot cause: {analysis['text']}")

    if (
        container_row["maturity"] == "stable"
        and os.environ.get("ENABLE_FIX_RUNNER", "false").lower() == "true"
        and verdict == "code"
    ):
        pr_url = analyzer.run_fix(container_row, fp, analysis, workspace_dir)
        if pr_url:
            db.update_event_status(conn, fp, name, status="pr_opened", pr_url=pr_url)
            notify(f"🛠 PR opened for {name}: {pr_url}")
        else:
            db.update_event_status(conn, fp, name, status="analyzed", gate_reason="fix_rejected")


def _parse_started_at(iso: str) -> datetime:
    # Docker's State.StartedAt is RFC3339 with nanoseconds, e.g. "2026-07-04T10:00:00.123456789Z"
    trimmed = iso[:26] + "Z" if iso.endswith("Z") else iso
    return datetime.strptime(trimmed, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _watch_once(docker_client, row, conn, stop_event: threading.Event, last_image_id: dict, streams: dict) -> None:
    name = row["name"]
    container = docker_client.containers.get(name)
    image_id = container.image.id
    started_at = _parse_started_at(container.attrs["State"]["StartedAt"])
    if name in last_image_id and last_image_id[name] != image_id:
        started_at = datetime.now(UTC)  # image change resets the grace-period clock
    last_image_id[name] = image_id

    pattern = re.compile(row["regex_override"]) if row["regex_override"] else DEFAULT_REGEX
    ring = RingBuffer()

    stream = container.logs(stream=True, follow=True, tail=0)
    streams[name] = stream
    try:
        for raw in stream:
            if stop_event.is_set():
                return
            line = raw.decode(errors="replace").rstrip("\n")
            if pattern.search(line):
                fp = fingerprint(name, line)
                excerpt = ring.capture(line, [])
                process_event(conn, row, fp, excerpt, line, started_at)
            ring.push(line)
    finally:
        streams.pop(name, None)


class WatcherManager:
    def __init__(self, docker_client=None):
        self._docker = docker_client or docker.from_env()
        self._tasks: dict[str, asyncio.Task] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._last_image_id: dict[str, str] = {}
        self._streams: dict[str, object] = {}
        self._paused = False

    @property
    def is_paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    async def reload(self, conn) -> None:
        if self._paused:
            for name in list(self._tasks):
                self._cancel(name)
            return
        rows = {r["name"]: r for r in db.list_monitored_containers(conn) if not r["paused"]}
        for name in list(self._tasks):
            if name not in rows:
                self._cancel(name)
        for name, row in rows.items():
            if name not in self._tasks:
                stop_event = threading.Event()
                self._stop_events[name] = stop_event
                self._tasks[name] = asyncio.create_task(self._watch(row, stop_event))

    def _cancel(self, name: str) -> None:
        self._stop_events[name].set()
        stream = self._streams.get(name)
        if stream is not None:
            stream.close()
        self._tasks[name].cancel()
        del self._tasks[name]
        del self._stop_events[name]
        self._streams.pop(name, None)

    async def _watch(self, row, stop_event: threading.Event) -> None:
        conn = db.get_conn()
        try:
            while not stop_event.is_set():
                try:
                    await asyncio.to_thread(
                        _watch_once, self._docker, row, conn, stop_event, self._last_image_id, self._streams
                    )
                # Broad catch: treats permanent errors (bad config, docker API incompatibility) the same as
                # transient disconnects — retries forever either way. A `since=0` bug like this one hid
                # silently until found in review; consider narrowing if this recurs.
                except Exception:
                    logger.exception("watcher for %s crashed, reconnecting", row["name"])
                await asyncio.sleep(RECONNECT_BACKOFF_SECONDS)
        finally:
            conn.close()
