"""Watchtower LINE Notifier - Sidecar Script
อ่าน Watchtower logs ผ่าน Docker socket API โดยตรง (ไม่พึ่ง docker CLI binary)
Patterns ปรับให้ตรงกับ Watchtower 1.7.x structured log format
"""

import json
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from notify import LineCreds, Notifier, TgCreds

# ─── Config ────────────────────────────────────────────────────────────────
LINE_API_URL = "https://api.line.me/v2/bot/message/push"
CHANNEL_ACCESS_TOKEN = os.environ["WATCHTOWER_LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID = os.environ["WATCHTOWER_LINE_USER_ID"]
WATCHTOWER_CONTAINER = os.environ.get("WATCHTOWER_CONTAINER_NAME", "watchtower")
DOCKER_SOCKET = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")
TZ = ZoneInfo(os.environ.get("TZ", "Asia/Bangkok"))
TELEGRAM_BOT_TOKEN = os.environ.get("WATCHTOWER_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# ─── Major-version watch ───────────────────────────────────────────────────
# Watchtower follows a moving tag (:2, :latest) but can NEVER cross a major:
# tag N freezes at vN once vN+1 ships (louislam/uptime-kuma:latest froze at v1
# in 2025-10). Nothing alerts you to the new major. This poller closes that gap
# by watching GitHub's latest *stable* release and pinging when major > pinned.
# Add a stack = one line here (same place you'd bump the pin).
MAJOR_WATCH = [
    {"repo": "louislam/uptime-kuma", "current": 2, "label": "Uptime Kuma"},
]
MAJOR_CHECK_INTERVAL_H = float(os.environ.get("MAJOR_CHECK_INTERVAL_HOURS", "24"))
_alerted_majors: set[tuple[str, int]] = set()  # in-memory dedupe; nag resets on restart

# ─── Watchtower 1.7.x structured log patterns ──────────────────────────────
# ตัวอย่าง log จริง:
#   msg="Watchtower 1.7.1"
#   msg="Found new ghcr.io/gethomepage/homepage:latest image (8d2d6aa5c260)"
#   msg="Stopping /homepage (9e6b3f146289) with SIGTERM"
#   msg="Creating /homepage"
#   msg="Removing image 1c1658cf4ceb"
#   msg="Session done" Failed=0 Scanned=4 Updated=1
#   msg="Session done" Failed=0 Scanned=4 Updated=0

PAT_SESSION_START = re.compile(
    r'msg="Watchtower \d+\.\d+|msg="Starting Watchtower',
    re.IGNORECASE,
)
PAT_FOUND_NEW = re.compile(
    r'msg="Found new ([^\s"]+) image \(([a-f0-9]+)\)"', re.IGNORECASE
)
PAT_STOPPING = re.compile(r'msg="Stopping /([^\s"]+)', re.IGNORECASE)
PAT_CREATING = re.compile(r'msg="Creating /([^\s"]+)"', re.IGNORECASE)
PAT_REMOVING = re.compile(r'msg="Removing image ([a-f0-9]+)"', re.IGNORECASE)
PAT_SESSION_DONE = re.compile(r'msg="Session done".*?Updated=(\d+)', re.IGNORECASE)
PAT_ERROR = re.compile(r"level=error|level=fatal|panic:", re.IGNORECASE)

# state ระหว่าง session
_pending_updates: dict[
    str,
    dict,
] = {}  # container_name -> {"image_name": str, "new_id": str, "old_id": str|None}
_image_queue: list[
    dict
] = []  # FIFO queue of {"name": image_name, "id": new_id} waiting for Creating
_containers_updated_order: list[
    str
] = []  # FIFO ลำดับ container ที่ update แล้ว รอ Removing image
_session_start_time: datetime | None = None


def now() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def extract_msg(log_line: str) -> str:
    """ดึงค่า msg="..." ออกมา ถ้าไม่มีคืน log เดิม"""
    m = re.search(r'msg="([^"]+)"', log_line)
    return m.group(1) if m else log_line


# ─── Notifier ────────────────────────────────────────────────────────────────
_notifier = Notifier(
    line=LineCreds(CHANNEL_ACCESS_TOKEN, LINE_USER_ID),
    telegram=TgCreds(TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID),  # plain text, no parse_mode
    timeout=10,
)


def notify(text: str) -> None:
    """Send to both LINE and Telegram (Telegram is optional — skipped if not configured)."""
    sent = _notifier.send(text)
    print(f"[{now()}] notify -> {sent or 'none'}: {text[:80].replace(chr(10), ' ')}")


# ─── Docker socket HTTP (no CLI needed) ────────────────────────────────────
class DockerSocketSession:
    def __init__(self, socket_path: str = "/var/run/docker.sock"):
        self.socket_path = socket_path

    def _raw_request(self, method: str, path: str) -> tuple[int, str]:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.socket_path)
        sock.settimeout(5)
        request = f"{method} {path} HTTP/1.0\r\nHost: localhost\r\n\r\n"
        sock.sendall(request.encode())
        data = b""
        while True:
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                data += chunk
            except TimeoutError:
                break
        sock.close()
        parts = data.split(b"\r\n\r\n", 1)
        header = parts[0].decode(errors="replace")
        body = parts[1].decode(errors="replace") if len(parts) > 1 else ""
        status = int(header.split(" ")[1]) if " " in header else 0
        return status, body

    def get_container_id(self, name: str) -> str | None:
        status, body = self._raw_request("GET", "/containers/json?all=1")
        if status != 200:
            return None
        for c in json.loads(body):
            if any(n.strip("/") == name for n in c.get("Names", [])):
                return c["Id"]
        return None

    def stream_logs(self, container_id: str):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.connect(self.socket_path)
        # tail=1, not 0: the docker engine on DSM treats tail=0 as "everything",
        # so reconnecting after a daemon restart replayed weeks of watchtower log
        # and flooded Telegram with historical "container updated" messages
        # (2026-08-19). Worst case now is one duplicate line per reconnect.
        path = f"/containers/{container_id}/logs?follow=1&stdout=1&stderr=1&tail=1"
        sock.sendall(f"GET {path} HTTP/1.0\r\nHost: localhost\r\n\r\n".encode())

        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(256)
            if not chunk:
                return
            buf += chunk
        buf = buf.split(b"\r\n\r\n", 1)[1]

        while True:
            while len(buf) < 8:
                chunk = sock.recv(4096)
                if not chunk:
                    sock.close()
                    return
                buf += chunk

            frame_size = int.from_bytes(buf[4:8], "big")
            while len(buf) < 8 + frame_size:
                chunk = sock.recv(4096)
                if not chunk:
                    sock.close()
                    return
                buf += chunk

            payload = buf[8 : 8 + frame_size]
            buf = buf[8 + frame_size :]
            for line in payload.decode(errors="replace").rstrip("\n").splitlines():
                if line.strip():
                    yield line.strip()


# ─── Log handler ───────────────────────────────────────────────────────────
def handle_line(log_line: str) -> None:
    global \
        _pending_updates, \
        _image_queue, \
        _containers_updated_order, \
        _session_start_time

    print(f"[LOG] {log_line}")

    # ── Watchtower version line = session start ─────────────────────────────
    if PAT_SESSION_START.search(log_line):
        _pending_updates = {}
        _image_queue.clear()
        _containers_updated_order.clear()
        _session_start_time = None
        notify(
            f"🟢 Watchtower เริ่มทำงานแล้ว\n"
            f"📋 กำลังตรวจสอบ container updates...\n"
            f"🕒 {now()}",
        )
        return

    # ── Found new image → เก็บไว้รอ Creating ─────────────────────────────
    m = PAT_FOUND_NEW.search(log_line)
    if m:
        image_name = m.group(1)  # e.g. ghcr.io/gethomepage/homepage:latest
        new_id = m.group(2)[:12]  # e.g. 8d2d6aa5c260
        _image_queue.append({"name": image_name, "id": new_id})
        if _session_start_time is None:
            _session_start_time = datetime.now(TZ)
        return

    # ── Creating /container = update สำเร็จ ────────────────────────────────
    m = PAT_CREATING.search(log_line)
    if m:
        container_name = m.group(1)
        img = (
            _image_queue.pop(0)
            if _image_queue
            else {"name": "unknown image", "id": "?"}
        )
        _pending_updates[container_name] = {
            "image_name": img["name"],
            "new_id": img["id"],
            "old_id": None,
        }
        _containers_updated_order.append(container_name)
        notify(
            f"🔄 Container อัปเดตแล้ว!\n"
            f"📦 {container_name}\n"
            f"🖼 {img['name']}\n"
            f"  🆕 {img['id']}\n"
            f"🕒 {now()}",
        )
        return

    # ── Removing image = บันทึก old image ID ──────────────────────────────
    m = PAT_REMOVING.search(log_line)
    if m and _containers_updated_order:
        old_id = m.group(1)[:12]
        container_name = _containers_updated_order.pop(0)
        if container_name in _pending_updates:
            _pending_updates[container_name]["old_id"] = old_id
        return

    # ── Session done → summary ─────────────────────────────────────────────
    m = PAT_SESSION_DONE.search(log_line)
    if m:
        updated_count = int(m.group(1))
        duration = ""
        if _session_start_time:
            elapsed = datetime.now(TZ) - _session_start_time
            duration = f"\n⏱ ใช้เวลา {int(elapsed.total_seconds() // 60)} นาที"

        if updated_count > 0:
            lines = []
            for k, v in _pending_updates.items():
                old = v.get("old_id") or "?"
                new = v.get("new_id") or "?"
                lines.append(f"  • {k}: {v['image_name']}\n    {old} → {new}")
            notify(
                f"✅ ตรวจสอบเสร็จ — อัปเดต {updated_count} container\n"
                f"{chr(10).join(lines)}{duration}\n🕒 {now()}",
            )
        else:
            notify(f"✅ ตรวจสอบเสร็จ — ไม่มี container ที่ต้องอัปเดต{duration}\n🕒 {now()}")
        _pending_updates = {}
        _image_queue.clear()
        _containers_updated_order.clear()
        _session_start_time = None  # fix: reset ทุก session ไม่งั้น session ถัดไปนับเวลาผิด
        return

    # ── Error ──────────────────────────────────────────────────────────────
    if PAT_ERROR.search(log_line):
        notify(f"🔴 Watchtower พบ Error!\n📋 {extract_msg(log_line)[:200]}\n🕒 {now()}")


# ─── Major-version poller ──────────────────────────────────────────────────
def newer_major(latest_tag: str, current_major: int) -> int | None:
    """Return the upstream major if it's ahead of the pinned one, else None.

    Tolerates a leading 'v' (v3.0.0). Prereleases are already excluded upstream
    by GitHub's /releases/latest, so beta tags never reach here.
    """
    tag = latest_tag.lstrip("vV")
    try:
        major = int(tag.split(".", 1)[0])
    except (ValueError, IndexError):
        return None
    return major if major > current_major else None


def github_latest_major(repo: str) -> int | None:
    """Fetch the latest stable release major from GitHub. None on any failure."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/releases/latest",
        headers={"User-Agent": "nas-watchtower-notifier", "Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            tag = json.loads(resp.read()).get("tag_name", "")
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as exc:
        print(f"[{now()}] major-watch: fetch {repo} failed: {exc}")
        return None
    m = re.match(r"v?(\d+)", tag)
    return int(m.group(1)) if m else None


def major_watch_loop() -> None:
    """Daily-ish poll of pinned upstreams; alert once per new major (in-memory dedupe)."""
    while True:
        for w in MAJOR_WATCH:
            try:
                latest = github_latest_major(w["repo"])
                if latest is None:
                    continue
                key = (w["repo"], latest)
                if latest > w["current"] and key not in _alerted_majors:
                    _alerted_majors.add(key)
                    notify(
                        f"🆙 มี Major version ใหม่!\n"
                        f"📦 {w['label']} (v{w['current']} → v{latest})\n"
                        f"⚠️ Watchtower อัปเดตข้าม major ให้ไม่ได้ — ต้อง bump tag :{latest} + backup DB เอง\n"
                        f"🔗 https://github.com/{w['repo']}/releases\n"
                        f"🕒 {now()}",
                    )
            except Exception as exc:  # a bad entry must not kill the thread
                print(f"[{now()}] major-watch: {w.get('repo')} error: {exc}")
        time.sleep(MAJOR_CHECK_INTERVAL_H * 3600)


# ─── Main loop ─────────────────────────────────────────────────────────────
def main() -> None:
    print(f"[{now()}] Notifier starting (Docker socket API mode)")
    print(f"[{now()}] Socket: {DOCKER_SOCKET} | Container: {WATCHTOWER_CONTAINER}")

    threading.Thread(target=major_watch_loop, daemon=True).start()
    print(f"[{now()}] Major-watch thread started ({len(MAJOR_WATCH)} repo, every {MAJOR_CHECK_INTERVAL_H}h)")

    docker = DockerSocketSession(DOCKER_SOCKET)

    while True:
        try:
            container_id = docker.get_container_id(WATCHTOWER_CONTAINER)
            if not container_id:
                print(
                    f"[{now()}] Container '{WATCHTOWER_CONTAINER}' not found, retrying in 15s...",
                )
                time.sleep(15)
                continue

            print(
                f"[{now()}] Streaming logs for {WATCHTOWER_CONTAINER} ({container_id[:12]})",
            )
            for line in docker.stream_logs(container_id):
                handle_line(line)

            print(f"[{now()}] Log stream ended, reconnecting in 10s...")

        except Exception as e:
            print(f"[{now()}] ERROR: {e}, retrying in 10s...")

        time.sleep(10)


if __name__ == "__main__":
    main()
