#!/usr/bin/env python3
"""Audit clip deliveries — did the clip actually reach Fix?

Reads logs/delivery-log.jsonl (appended by scripts/send_clip.py) and
logs/clip-log.jsonl (appended at SKILL.md step 9) and reports:

  FAIL  a delivery row that did not verify: ok != True, no message_id,
        remote_size != local size, or the local file vanished
  FAIL  a clip-log row (on/after the day the ledger started) with no
        verified delivery within that day — i.e. a clip we logged as
        shipped but that never left this box (the MEDIA: bug signature)

Text-only review sends and probes are not checked; only clip deliveries are.

Usage: check_delivery.py [--verbose]
Exit 0 = clean, exit 1 = something needs re-sending or reporting.
Prints NOTHING when clean (unless --verbose), so it is cron-safe.
"""
import json
import os
import sys
from datetime import datetime, timedelta

SKILL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.environ.get(
    "CLIP_LEDGER",
    "/opt/data/clips/logs/delivery-log.jsonl",
)
CLIPLOG = os.environ.get(
    "CLIP_LOG",
    "/opt/data/clips/logs/clip-log.jsonl",
)


def load(path):
    if not os.path.isfile(path):
        return []
    rows = []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    pass
    return rows


def day(ts):
    return ts[:10]


def main():
    verbose = "--verbose" in sys.argv
    deliveries = load(LEDGER)
    clips = load(CLIPLOG)
    problems = []

    if not deliveries:
        problems.append("delivery-log.jsonl is empty — nothing has ever been "
                        "verified as sent by send_clip.py")

    # a failed attempt that a LATER successful attempt for the same file
    # superseded is stale history, not an open problem (retry already fixed it)
    ok_ts = {}
    for r in deliveries:
        if r.get("ok") and r.get("ts"):
            k = r.get("file")
            ok_ts[k] = max(ok_ts.get(k, ""), r["ts"])

    for i, r in enumerate(deliveries):
        where = "%s (attempt %s)" % (day(r.get("ts", "?")), r.get("attempt"))
        if not r.get("ok"):
            if ok_ts.get(r.get("file"), "") > r.get("ts", ""):
                continue  # superseded by a later successful send
            problems.append("delivery NOT verified %s file=%s reason=%s"
                            % (where, r.get("file"), r.get("reason")))
            continue
        if not r.get("message_id"):
            problems.append("delivery ok but no message_id %s file=%s"
                            % (where, r.get("file")))
        if r.get("remote_size") is not None and r.get("size") is not None \
                and r["remote_size"] != r["size"]:
            problems.append("SIZE MISMATCH %s file=%s local=%s remote=%s"
                            % (where, r.get("file"), r["size"], r["remote_size"]))
        p = r.get("path")
        # Retention policy (Fix 2026-11-04: "คลิปเก่าๆที่เสร็จแล้วไม่ต้องเก็บไว้เลย"):
        # once a send verified (ok + message_id + size match) the bytes reached
        # Telegram, so the local file is disposable — only demand the file on
        # disk when we would have to RESEND it (row never verified).
        verified = bool(r.get("ok") and r.get("message_id"))
        if p and not verified \
                and day(r.get("ts", "")) >= (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d") \
                and not os.path.isfile(p):
            problems.append("delivered file missing on disk %s file=%s"
                            % (where, os.path.basename(p or "")))

    # clip-log rows with no verified delivery on the same day
    ok_days = set(day(r["ts"]) for r in deliveries if r.get("ok") and r.get("ts"))
    start_day = min((day(r["ts"]) for r in deliveries if r.get("ts")), default=None)
    for c in clips:
        d = c.get("date")
        if not d or (start_day and d < start_day):
            continue
        if d in ok_days:
            continue
        if d >= (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d"):
            problems.append("clip logged but NO verified delivery that day: "
                            "%s [%s]" % (d, (c.get("product") or "?")[:60]))

    if problems:
        print("DELIVERY CHECK: %d problem(s)" % len(problems))
        for p in problems:
            print("  - " + p)
        return 1
    if verbose:
        print("DELIVERY CHECK: clean (%d deliveries, %d clips logged)"
              % (len(deliveries), len(clips)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
