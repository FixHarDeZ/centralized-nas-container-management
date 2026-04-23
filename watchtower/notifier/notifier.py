"""
Watchtower LINE Notifier - Sidecar Script
อ่าน Watchtower logs ผ่าน Docker socket API โดยตรง (ไม่พึ่ง docker CLI binary)
Patterns ปรับให้ตรงกับ Watchtower 1.7.x structured log format
"""

import os
import re
import time
import json
import socket
import requests
from datetime import datetime
from zoneinfo import ZoneInfo

# ─── Config ────────────────────────────────────────────────────────────────
LINE_API_URL         = "https://api.line.me/v2/bot/message/push"
CHANNEL_ACCESS_TOKEN = os.environ["WATCHTOWER_LINE_CHANNEL_ACCESS_TOKEN"]
LINE_USER_ID         = os.environ["WATCHTOWER_LINE_USER_ID"]
WATCHTOWER_CONTAINER = os.environ.get("WATCHTOWER_CONTAINER_NAME", "watchtower")
DOCKER_SOCKET        = os.environ.get("DOCKER_SOCKET", "/var/run/docker.sock")
TZ                   = ZoneInfo(os.environ.get("TZ", "Asia/Bangkok"))

# ─── Watchtower 1.7.x structured log patterns ──────────────────────────────
# ตัวอย่าง log จริง:
#   msg="Watchtower 1.7.1"
#   msg="Found new ghcr.io/gethomepage/homepage:latest image (8d2d6aa5c260)"
#   msg="Stopping /homepage (9e6b3f146289) with SIGTERM"
#   msg="Creating /homepage"
#   msg="Removing image 1c1658cf4ceb"
#   msg="Session done" Failed=0 Scanned=4 Updated=1
#   msg="Session done" Failed=0 Scanned=4 Updated=0

PAT_SESSION_START = re.compile(r'msg="Watchtower \d+\.\d+|msg="Starting Watchtower', re.I)
PAT_FOUND_NEW     = re.compile(r'msg="Found new ([^\s"]+) image \(([a-f0-9]+)\)"', re.I)
PAT_STOPPING      = re.compile(r'msg="Stopping /([^\s"]+)', re.I)
PAT_CREATING      = re.compile(r'msg="Creating /([^\s"]+)"', re.I)
PAT_REMOVING      = re.compile(r'msg="Removing image ([a-f0-9]+)"', re.I)
PAT_SESSION_DONE  = re.compile(r'msg="Session done".*?Updated=(\d+)', re.I)
PAT_ERROR         = re.compile(r'level=error|level=fatal|panic:', re.I)

# state ระหว่าง session
_pending_updates: dict[str, dict] = {}      # container_name -> {"image_name": str, "new_id": str, "old_id": str|None}
_image_queue: list[dict] = []               # FIFO queue of {"name": image_name, "id": new_id} waiting for Creating
_containers_updated_order: list[str] = []   # FIFO ลำดับ container ที่ update แล้ว รอ Removing image
_session_start_time: datetime | None = None


def now() -> str:
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


def extract_msg(log_line: str) -> str:
    """ดึงค่า msg="..." ออกมา ถ้าไม่มีคืน log เดิม"""
    m = re.search(r'msg="([^"]+)"', log_line)
    return m.group(1) if m else log_line


# ─── LINE ──────────────────────────────────────────────────────────────────
def send_line(text: str) -> None:
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {CHANNEL_ACCESS_TOKEN}",
    }
    payload = {"to": LINE_USER_ID, "messages": [{"type": "text", "text": text}]}
    try:
        resp = requests.post(LINE_API_URL, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        print(f"[{now()}] LINE sent: {text[:100].replace(chr(10), ' ')}")
    except Exception as e:
        print(f"[{now()}] ERROR sending LINE: {e}")


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
            except socket.timeout:
                break
        sock.close()
        parts = data.split(b"\r\n\r\n", 1)
        header = parts[0].decode(errors="replace")
        body   = parts[1].decode(errors="replace") if len(parts) > 1 else ""
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
        path = f"/containers/{container_id}/logs?follow=1&stdout=1&stderr=1&tail=0"
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
            buf     = buf[8 + frame_size :]
            for line in payload.decode(errors="replace").rstrip("\n").splitlines():
                if line.strip():
                    yield line.strip()


# ─── Log handler ───────────────────────────────────────────────────────────
def handle_line(log_line: str) -> None:
    global _pending_updates, _image_queue, _containers_updated_order, _session_start_time

    print(f"[LOG] {log_line}")

    # ── Watchtower version line = session start ─────────────────────────────
    if PAT_SESSION_START.search(log_line):
        _pending_updates = {}
        _image_queue.clear()
        _containers_updated_order.clear()
        _session_start_time = None
        send_line(
            f"🟢 Watchtower เริ่มทำงานแล้ว\n"
            f"📋 กำลังตรวจสอบ container updates...\n"
            f"🕒 {now()}"
        )
        return

    # ── Found new image → เก็บไว้รอ Creating ─────────────────────────────
    m = PAT_FOUND_NEW.search(log_line)
    if m:
        image_name = m.group(1)        # e.g. ghcr.io/gethomepage/homepage:latest
        new_id     = m.group(2)[:12]   # e.g. 8d2d6aa5c260
        _image_queue.append({"name": image_name, "id": new_id})
        if _session_start_time is None:
            _session_start_time = datetime.now(TZ)
        return

    # ── Creating /container = update สำเร็จ ────────────────────────────────
    m = PAT_CREATING.search(log_line)
    if m:
        container_name = m.group(1)
        img = _image_queue.pop(0) if _image_queue else {"name": "unknown image", "id": "?"}
        _pending_updates[container_name] = {"image_name": img["name"], "new_id": img["id"], "old_id": None}
        _containers_updated_order.append(container_name)
        send_line(
            f"🔄 Container อัปเดตแล้ว!\n"
            f"📦 {container_name}\n"
            f"🖼 {img['name']}\n"
            f"  🆕 {img['id']}\n"
            f"🕒 {now()}"
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
            send_line(
                f"✅ ตรวจสอบเสร็จ — อัปเดต {updated_count} container\n"
                f"{chr(10).join(lines)}{duration}\n🕒 {now()}"
            )
        else:
            send_line(
                f"✅ ตรวจสอบเสร็จ — ไม่มี container ที่ต้องอัปเดต"
                f"{duration}\n🕒 {now()}"
            )
        _pending_updates = {}
        _image_queue.clear()
        _containers_updated_order.clear()
        _session_start_time = None   # fix: reset ทุก session ไม่งั้น session ถัดไปนับเวลาผิด
        return

    # ── Error ──────────────────────────────────────────────────────────────
    if PAT_ERROR.search(log_line):
        send_line(f"🔴 Watchtower พบ Error!\n📋 {extract_msg(log_line)[:200]}\n🕒 {now()}")


# ─── Main loop ─────────────────────────────────────────────────────────────
def main() -> None:
    print(f"[{now()}] Notifier starting (Docker socket API mode)")
    print(f"[{now()}] Socket: {DOCKER_SOCKET} | Container: {WATCHTOWER_CONTAINER}")
    send_line(
        f"🤖 LINE Notifier พร้อมทำงานแล้ว\n"
        f"👁 กำลังติดตาม: {WATCHTOWER_CONTAINER}\n"
        f"🕒 {now()}"
    )

    docker = DockerSocketSession(DOCKER_SOCKET)

    while True:
        try:
            container_id = docker.get_container_id(WATCHTOWER_CONTAINER)
            if not container_id:
                print(f"[{now()}] Container '{WATCHTOWER_CONTAINER}' not found, retrying in 15s...")
                time.sleep(15)
                continue

            print(f"[{now()}] Streaming logs for {WATCHTOWER_CONTAINER} ({container_id[:12]})")
            for line in docker.stream_logs(container_id):
                handle_line(line)

            print(f"[{now()}] Log stream ended, reconnecting in 10s...")

        except Exception as e:
            print(f"[{now()}] ERROR: {e}, retrying in 10s...")

        time.sleep(10)


if __name__ == "__main__":
    main()
