#!/usr/bin/env python3
"""One-line status message to the clip chat, mid-run, WITHOUT ending the turn.

SKILL.md -> Talking to Fix: a long silent stretch (post-production, browser drive)
needs a short line at each stage transition, sent at that moment.

Usage:
  python3 send_status.py "ผ่านทั้ง 2 ช็อต -> กำลังทำซับ/กราฟิก"
  python3 send_status.py "<line>" <chat_id>
  python3 send_status.py --check "<clarify question>"   # scan only, sends nothing

CJK gate (house-rules -> Talking to Fix): a line holding a CJK / full-width character (the same ranges as the
hashtag gate in clipjob.py; emoji pass) is REFUSED, exit 3, nothing sent. The refusal names the positions,
never the characters. `--check` runs the same scan on a string that goes out another way (a `clarify`).

Same convention as the other senders: prints {"ok": ..., "message_id": ...}, exit 0 on
success, non-zero when Telegram rejected it. Token = send_clip.read_token().
"""
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from send_clip import DEFAULT_CHAT, read_token  # noqa: E402


# Same character class as clipjob.CJK_RE (test_send_status.py keeps them equal).
CJK_RE = re.compile(r"[\u3000-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff00-\uffef]")


def cjk_hits(text):
    """Character offsets of CJK / full-width characters (emoji and Thai pass)."""
    return [m.start() for m in CJK_RE.finditer(text)]


def refuse_cjk(text):
    hits = cjk_hits(text)
    if hits:
        print(f"REFUSED: {len(hits)} CJK/full-width character(s) at offset(s) {hits} — retype that word in Thai; "
              "do not quote the characters back to Fix", file=sys.stderr)
        sys.exit(3)


SENT_STAMP = os.environ.get("CLIP_SENT_STAMP", "/opt/data/clips/logs/last-sent.json")


def stamp_sent(kind):
    """Record that Fix just got a message (clip_heartbeat.py counts silence from here). Never fails the send."""
    try:
        import time
        os.makedirs(os.path.dirname(SENT_STAMP), exist_ok=True)
        with open(SENT_STAMP + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"ts": time.time(), "kind": kind}, f)
        os.replace(SENT_STAMP + ".tmp", SENT_STAMP)
    except OSError:
        pass


def main():
    args = sys.argv[1:]
    check = bool(args) and args[0] == "--check"
    if check:
        args = args[1:]
    if not args or not args[0].strip():
        sys.exit(__doc__)
    text = args[0]
    refuse_cjk(text)
    if check:
        print("OK: no CJK/full-width characters")
        return
    chat = args[1] if len(args) > 1 else DEFAULT_CHAT
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
    stamp_sent("status")


if __name__ == "__main__":
    main()
