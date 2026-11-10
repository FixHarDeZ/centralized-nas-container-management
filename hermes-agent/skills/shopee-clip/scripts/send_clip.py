#!/usr/bin/env python3
"""Verified Telegram video delivery — the MEDIA: bug killer.

`hermes send 'MEDIA:<path>'` can return exit 0 even when NO attachment leaves
this box (2026-10-31, Fix: "ผมยังไม่ได้คลิปเลย"). So never trust a delivery
that was not asserted: this script posts the file through the Bot API itself
and exits 0 ONLY when Telegram answers ok:true with a message_id and
video.file_size == the local byte count. Every attempt is appended to
logs/delivery-log.jsonl so check_delivery.py can audit it afterwards.

Usage:
  send_clip.py <file.mp4> "<caption>" [chat_id] [label]

Exit: 0 = verified delivered, 1 = NOT verified (retry it or report to Fix;
never claim "sent" on exit 1).
"""
import hashlib
import json
import os
import subprocess
import sys
import time

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.environ.get(
    "CLIP_LEDGER",
    "/opt/data/clips/logs/delivery-log.jsonl",
)
ENV = "/opt/data/.env"
DEFAULT_CHAT = "8663614341"
TRIES = 2
UPLOAD_TIMEOUT = 500


def read_token():
    with open(ENV) as fh:
        for line in fh:
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                tok = line.split("=", 1)[1].strip()
                if tok:
                    return tok
    raise SystemExit("TELEGRAM_BOT_TOKEN missing from " + ENV)


def post(tok, path, caption, chat, tmp):
    cmd = [
        "curl", "-sS", "--max-time", str(UPLOAD_TIMEOUT), "-X", "POST",
        "https://api.telegram.org/bot%s/sendVideo" % tok,
        "-F", "chat_id=%s" % chat,
        "-F", "video=@%s" % path,
        "-F", "caption=%s" % caption,
        "-o", tmp, "-w", "%{http_code}",
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True,
                           timeout=UPLOAD_TIMEOUT + 30)
    except subprocess.TimeoutExpired:
        return None, "curl timeout"
    http = (p.stdout or "").strip()
    try:
        with open(tmp) as fh:
            data = json.load(fh)
    except Exception as exc:
        return {"http": http}, "unparsable body: %s" % exc
    data["http"] = http
    return data, None


def append_row(row):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main():
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    path, caption = sys.argv[1], sys.argv[2]
    chat = sys.argv[3] if len(sys.argv) > 3 and sys.argv[3] else DEFAULT_CHAT
    label = sys.argv[4] if len(sys.argv) > 4 and sys.argv[4] else os.path.basename(path)
    if not os.path.isfile(path):
        raise SystemExit("no such file: " + path)

    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        sha = hashlib.sha256(fh.read()).hexdigest()
    tok = read_token()
    tmp = os.path.join("/tmp", "send_clip_%d.json" % os.getpid())

    verdict = {"file": path, "size": size, "ok": False}
    for attempt in range(1, TRIES + 1):
        data, err = post(tok, path, caption, chat, tmp)
        res = (data or {}).get("result") or {}
        remote = (res.get("video") or {}).get("file_size")
        ok = bool(data and data.get("ok") and res.get("message_id")
                  and (remote is None or remote == size))
        reason = err or ("" if ok else
                         "ok=%s message_id=%s remote_size=%s http=%s desc=%s" % (
                             (data or {}).get("ok"), res.get("message_id"),
                             remote, (data or {}).get("http"),
                             (data or {}).get("description")))
        row = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "label": label,
            "file": os.path.basename(path),
            "path": path,
            "size": size,
            "sha256": sha,
            "chat": chat,
            "attempt": attempt,
            "ok": ok,
            "message_id": res.get("message_id"),
            "remote_size": remote,
            "http": (data or {}).get("http"),
            "reason": None if ok else reason,
        }
        append_row(row)
        verdict = {"file": path, "size": size, "ok": ok,
                   "message_id": row["message_id"], "attempt": attempt}
        if ok:
            print(json.dumps(verdict, ensure_ascii=False))
            return 0
        time.sleep(3)

    try:
        os.remove(tmp)
    except OSError:
        pass
    print(json.dumps(dict(verdict, last_reason=reason), ensure_ascii=False))
    return 1


if __name__ == "__main__":
    sys.exit(main())
