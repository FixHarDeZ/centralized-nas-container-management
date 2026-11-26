#!/usr/bin/env python3
"""Status heartbeat for a running clip job — a line to Fix when Hermes has gone quiet mid-run.

huawei-watchfit5 (2026-11-23): post ran 73 min without one message (house-rules -> Status lines asks for a
line per stage, but a 5-minute reasoning turn cannot send anything) and Fix had to ask "ค้างไหม". This runs
from Hermes' cron in no-agent mode (stdout is delivered to Fix as is, nothing printed = nothing sent):

  hermes cron create "every 5m" --name "clip heartbeat" --no-agent --script clip_heartbeat.py \
      --deliver telegram:<chat> --failure-deliver local

It prints ONE line when all hold:
  - a clip job is open (/opt/data/clips/jobs/*.json, status "open");
  - the agent is mid-turn: its newest message is a tool call or a tool result, not a final reply and not a
    `clarify` waiting for Fix (a turn that ended or waits on him is his move; no nagging);
  - nothing Fix could see went out for QUIET_MIN minutes: a final reply, a `clarify`, a call naming a sender
    (send_* / *status* scripts, clipjob ready|pack|deliver, the Bot API), the last-sent stamp send_status.py /
    send_photo.py write, or this heartbeat's own last line.
A turn with no new message for STUCK_MIN minutes gets a different line (maybe hung) once. A job still before its
board PREP_CAP_MIN after intake gets one line naming the photo gate, so Fix can answer it (his message interrupts
the turn) — cal-d-protein-1mo 2026-11-25: 191 min of hand pixel work on one ad photo, never asked.
Always exits 0 (a failing cron job only notifies `local`).
"""
import datetime as dt
import glob
import json
import os
import re
import sqlite3
import sys
import time

QUIET_MIN = 15                          # replayed on ps2-hdd-175: 10 min = 17 lines in 4 h, noise
STUCK_MIN = 20
PREP_CAP_MIN = 30                       # intake -> board; cal-d-protein-1mo 2026-11-25 spent 191 min on one photo
DB = os.environ.get("HERMES_STATE_DB", "/opt/data/state.db")
JOBS = os.environ.get("CLIPJOB_DIR", "/opt/data/clips/jobs")
STAMP = os.environ.get("HEARTBEAT_STAMP", "/opt/data/clips/logs/heartbeat.json")
SENT = os.environ.get("CLIP_SENT_STAMP", "/opt/data/clips/logs/last-sent.json")   # send_status / send_photo
# a call naming a sender script put something on his phone — send_status.py, send_photo.py and a scratch
# sendphoto_x.py / status1_x.py alike — but `clipjob.py status` (run all the time) sends nothing
SENDER_RX = re.compile(r"\b\w*(?:send|status)\w*\.py\b|clipjob\.py (?:ready|pack|deliver)\b|api\.telegram\.org")
FRESH_H = 12                                    # an open job untouched this long is abandoned, not running
TOOL_TH = {"vision_analyze": "อ่านภาพ", "terminal": "รันสคริปต์", "execute_code": "รันสคริปต์",
           "browser_exec": "คุม Chrome", "write_file": "เขียนไฟล์", "read_file": "อ่านไฟล์", "patch": "แก้ไฟล์"}


def calls(msg):
    try:
        return [c.get("function") or {} for c in json.loads(msg.get("tool_calls") or "[]")]
    except (ValueError, TypeError):
        return []


def is_visible(msg):
    """Did this message put something on Fix's phone?"""
    if msg["role"] != "assistant":
        return False
    cs = calls(msg)
    if not cs:
        return bool((msg.get("content") or "").strip())
    return any(c.get("name") == "clarify" or SENDER_RX.search(c.get("arguments") or "") for c in cs)


def open_job(jobs, now=None):
    now = now or dt.datetime.now().astimezone()
    def fresh(j):
        try:
            return (now - dt.datetime.fromisoformat(j.get("updated") or "")).total_seconds() < FRESH_H * 3600
        except (TypeError, ValueError):
            return False
    live = [j for j in jobs if j.get("status") == "open" and fresh(j)]
    # a queued order (clipjob intake behind another open job) is not the one running: naming it, or its
    # 30-min photo-gate line, would be wrong while the job ahead is still open
    names = {j["job"] for j in live}
    live = [j for j in live if not names & set(j.get("queued_behind") or ())] or live
    return max(live, key=lambda j: j.get("updated") or "") if live else None


def stage_of(job):
    shots = job.get("shots") or []
    if job.get("stage") and job["stage"] != "intake":
        return job["stage"]
    if not shots:
        return "เตรียมงาน"
    gen = ("reserved", "submitting", "submitted")
    if any(s.get("state") in gen for s in shots):
        k = next(s["k"] for s in shots if s.get("state") in gen)
        return f"gen ช็อต {k}"
    if all(s.get("state") == "approved" for s in shots):
        return "post (ซับ/กราฟิก/ปก)"
    return "รีวิวช็อต"


def prep_minutes(job, now):
    """Minutes since intake while the job is still before its board (photo gate / storyboard), else None."""
    if job.get("stage") != "intake" or job.get("board") or job.get("shots"):
        return None
    try:
        return (now - dt.datetime.fromisoformat(job.get("started") or job.get("created") or "").timestamp()) / 60
    except (TypeError, ValueError):
        return None


def decide(now, job, msgs, stamp, sent=0):
    """now: epoch s, msgs: newest first [{role, content, tool_calls, tool_name, timestamp}], stamp: dict,
    sent: epoch of the last send_status / send_photo. -> (line or None, new stamp)."""
    if not job or not msgs:
        return None, stamp
    last = msgs[0]
    if last["role"] == "assistant" and (not calls(last) or any(c.get("name") == "clarify" for c in calls(last))):
        return None, stamp                                     # turn ended, or waiting on Fix
    if last["role"] not in ("assistant", "tool"):
        return None, stamp
    prep = prep_minutes(job, now)
    if prep is not None and prep >= PREP_CAP_MIN and stamp.get("prep_cap") != job["job"]:
        line = (f"⚠️ {job['job']} · เตรียมรูปสินค้ามา {int(prep)} นาทีแล้ว ยังไม่ถึงบอร์ด — ถ้ารูปมีปัญหา "
                "ตอบไอยูได้เลย: ใช้รูปที่ดีที่สุดไปก่อน / จะส่งรูปสินค้าใหม่")
        return line, {**stamp, "sent": now, "prep_cap": job["job"], "job": job["job"]}
    seen = max([m["timestamp"] for m in msgs if is_visible(m)] + [stamp.get("sent", 0), sent])
    quiet, idle = (now - seen) / 60, (now - last["timestamp"]) / 60
    tool = last.get("tool_name") or next((c.get("name") for c in calls(last)), "") or ""
    doing = TOOL_TH.get(tool, tool or "คิด")
    if last["role"] == "tool":
        doing = "คิดต่อจาก" + TOOL_TH.get(tool, tool or "ผลล่าสุด")
    if idle >= STUCK_MIN:
        if stamp.get("stuck_at") == last["timestamp"]:
            return None, stamp
        what = f"{doing} ยังไม่จบ" if last["role"] == "assistant" else doing
        line = f"⚠️ {job['job']} · {what} นาน {int(idle)} นาทีแล้ว — ถ้าไม่ขยับต่อ พิมพ์ถามไอยูได้เลยค่ะ"
        return line, {**stamp, "sent": now, "stuck_at": last["timestamp"], "job": job["job"]}
    if quiet < QUIET_MIN:
        return None, stamp
    line = f"⏳ ยังทำอยู่ค่ะ · {job['job']} · {stage_of(job)} · เงียบมา {int(quiet)} นาที (ตอนนี้: {doing})"
    return line, {**stamp, "sent": now, "job": job["job"]}


def load_msgs(n=200):          # a busy turn writes ~80 rows in 35 min; 60 lost the last status line
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=5)
    try:
        cur = c.execute("select role, content, tool_calls, tool_name, timestamp from messages "
                        "order by id desc limit ?", (n,))
        return [dict(zip(("role", "content", "tool_calls", "tool_name", "timestamp"), r)) for r in cur]
    finally:
        c.close()


def main():
    try:
        jobs = []
        for p in glob.glob(os.path.join(JOBS, "*.json")):
            try:
                with open(p, encoding="utf-8") as f:
                    j = json.load(f)
                if isinstance(j, dict) and "job" in j:
                    jobs.append(j)
            except (OSError, ValueError):
                continue
        job = open_job(jobs)
        if not job:
            return 0
        try:
            with open(STAMP, encoding="utf-8") as f:
                stamp = json.load(f)
        except (OSError, ValueError):
            stamp = {}
        try:
            with open(SENT, encoding="utf-8") as f:
                sent = float(json.load(f).get("ts") or 0)
        except (OSError, ValueError, AttributeError):
            sent = 0
        line, new = decide(time.time(), job, load_msgs(), stamp, sent)
        if line:
            os.makedirs(os.path.dirname(STAMP), exist_ok=True)
            with open(STAMP + ".tmp", "w", encoding="utf-8") as f:
                json.dump({**new, "at": dt.datetime.now().isoformat(timespec="seconds")}, f)
            os.replace(STAMP + ".tmp", STAMP)
            print(line)
    except Exception as e:                                      # never fail the cron run
        print(f"clip_heartbeat: {e}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
