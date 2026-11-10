#!/usr/bin/env python3
"""Send a cover / thumbnail JPG to Telegram via the Bot API (same token + ledger as send_clip.py).

Usage: python3 send_photo.py cover.jpg "<caption>" [chat_id] [label]
Sends as a DOCUMENT-free photo (sendPhoto); exit 0 only when ok:true + message_id came back.
Appends the attempt to logs/delivery-log.jsonl with kind=photo (check_delivery ignores photos).
"""
import json, os, subprocess, sys, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from send_clip import read_token

def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    path, cap = sys.argv[1], sys.argv[2]
    chat = sys.argv[3] if len(sys.argv) > 3 else "8663614341"
    label = sys.argv[4] if len(sys.argv) > 4 else os.path.basename(path)
    tok = read_token()
    r = subprocess.run(["curl", "-s", "-m", "120", "-F", f"chat_id={chat}", "-F", f"caption={cap}",
                        "-F", f"photo=@{path}", f"https://api.telegram.org/bot{tok}/sendPhoto"],
                       capture_output=True, text=True)
    try:
        j = json.loads(r.stdout)
    except Exception:
        j = {"ok": False, "raw": r.stdout[:200]}
    ok = bool(j.get("ok")) and bool(j.get("result", {}).get("message_id"))
    row = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "kind": "photo", "label": label, "file": os.path.basename(path),
           "path": os.path.abspath(path), "size": os.path.getsize(path), "chat": chat, "ok": ok,
           "message_id": j.get("result", {}).get("message_id")}
    with open(os.environ.get("CLIP_LEDGER", "/opt/data/clips/logs/delivery-log.jsonl"), "a") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(json.dumps({"ok": ok, "message_id": row["message_id"], "file": path}))
    sys.exit(0 if ok else 1)

if __name__ == "__main__":
    main()
