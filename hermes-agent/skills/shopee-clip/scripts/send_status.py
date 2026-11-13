#!/usr/bin/env python3
"""One-line status message to the clip chat, mid-run, WITHOUT ending the turn.

SKILL.md -> Talking to Fix: a long silent stretch (post-production, browser drive)
needs a short line at each stage transition, sent at that moment.

Usage:
  python3 send_status.py "ผ่านทั้ง 2 ช็อต -> กำลังทำซับ/กราฟิก"
  python3 send_status.py "<line>" <chat_id>

Same convention as the other senders: prints {"ok": ..., "message_id": ...}, exit 0 on
success, non-zero when Telegram rejected it. Token = send_clip.read_token().
"""
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from send_clip import DEFAULT_CHAT, read_token  # noqa: E402


def main():
    if len(sys.argv) < 2 or not sys.argv[1].strip():
        sys.exit(__doc__)
    text = sys.argv[1]
    chat = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_CHAT
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{read_token()}/sendMessage",
        data=json.dumps({"chat_id": chat, "text": text}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        out = json.loads(resp.read())
    print(json.dumps({"ok": out.get("ok"),
                      "message_id": (out.get("result") or {}).get("message_id")}))
    if not out.get("ok"):
        sys.exit(1)


if __name__ == "__main__":
    main()
