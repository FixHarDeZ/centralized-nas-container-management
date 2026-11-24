#!/usr/bin/env python3
"""clipjob — one Shopee clip order, from mode pick to delivery. Local state, no n8n.

State: $CLIPJOB_DIR/<job>.json (default /opt/data/clips/jobs). Pacing clock: $CLIPJOB_DIR/pacing.json.
This CLI is the only sanctioned way to move a Flow-mode clip forward. It refuses out-of-order steps.

  clipjob.py intake JOB --product "..." [--link URL] [--mode M]   # right after the duplicate check: the job exists
  clipjob.py board JOB                              # the storyboard just went out (again): Flow `new` needs a reply after it
                                                    # (status lists it) before Q1/board, so a lost context can resume
  clipjob.py new JOB --mode presenter|product|hands|gameplay --product "..." [--link URL] [--shots N] [--seconds 8,6] [--ref IMG ...] [--character NAME]
                                                    # on an intake job: fills it in (same slug)
  clipjob.py cost [JOB] [--seconds 8,6] [--res 720p|360p]   # estimated credits, Omni 1.2 Flash
  clipjob.py production JOB auto|prompt            # Fix's answer to Q2 (Flow modes only)
  clipjob.py reshape JOB --shots N [--seconds 10]   # change the shot plan before any render (no attempt on any shot)
  clipjob.py status [JOB]
  # auto (IU drives Flow)
  clipjob.py reserve JOB K [--wait]                 # BEFORE clicking Start generation; exit 4 = pacing
  clipjob.py submitted JOB K [--edit-id ID] [--credits N]
  clipjob.py edit-id JOB K ID                       # record the real Flow edit id once the tile is opened
  clipjob.py submit-failed JOB K --reason "..." [--credits-spent]   # unusual activity -> auto fallback
  clipjob.py trouble JOB --step NAME --reason "..."  # picker/chip/CDP failure; 2nd on a step -> fallback
  clipjob.py fallback JOB --reason "..."            # switch to prompt pack from the first shot not rendered
  # prompt pack (Fix runs Flow, replies to each shot's prompt message with the mp4)
  clipjob.py pack JOB [--shot K] [--no-send]
  clipjob.py ingest JOB FILE (--reply-text "<replied-to message text>" | --shot K)
  # both
  clipjob.py scan JOB K --raw FILE                  # ✋ required before ready: frame sheets every 0.5 s (a face lasts <1 s)
  clipjob.py idcheck JOB K --raw FILE               # Flow modes, required before ready: refs + 6 frames on one sheet
  clipjob.py ready JOB K --raw FILE --frame pass|flag:<what you saw> --identity match|drift:<what>|count:<what>|presenter:<what> [--no-send]
                                                    # 📝 (Fix's own Flow file): --frame/--identity optional, no idcheck/scan —
                                                    # Fix's reply IS the review: the shot is approved at once, no buttons
  clipjob.py startframe JOB K                       # the start-frame jpg for shot K (🧑: newest earlier shot showing her face)
  clipjob.py ready JOB K --resend                   # the review message failed to send: send it again (no re-check)
  clipjob.py decide (--text "<Fix's button text>" | JOB K approve|regen)
                                                    # also 🤖 ไอยูกด Flow แทน · JOB (📝 -> 🤖) and 🏁
  clipjob.py assemble-check JOB                     # approved files in shot order, exit 0 only when all approved
  clipjob.py deliver JOB --final F.mp4 --report report.json --gfx gfx.json --hashtags "..." --cover C.jpg \
                         --caption "..." [--hook-id ID] [--category C] [--notes "..."] [--ack "<flag text>=<Fix's call>" ...]
                         # 🎬 only: --report may be omitted; --style footage for a brand product film
                         # a re-run after a failed send skips the steps already done and logs the clip once
                         # its last message carries the 🏁 จบงาน button; the job closes itself CLOSE_S (300 s) later
                         # then a detached `mirror --auto` sends a copy (clip + copy-button message + cover) to the
                         # Secretary bot chat when SECRETARY_TELEGRAM_BOT_TOKEN + _CHAT_ID are set; it messages
                         # Fix only when the copy fails, and never blocks or delays the delivery
  clipjob.py mirror JOB                             # resend a failed Secretary copy of the delivered clip
  clipjob.py close [JOB]                            # close now (Fix's 🏁 tap = decide --text); no JOB = every delivered
                                                    # job still waiting to close. Deletes only provable junk of that job
                                                    # (frame sheets, .v.jpg, last frames, logs, copies of the kept final,
                                                    # Downloads twins); the revision set, cover and workdir stay
  clipjob.py cancel JOB --reason "..."
  clipjob.py note JOB "..."                         # stage marker in the job's events (🎬: what is done, what is next)
  clipjob.py stage JOB footage|endcard|vo|build|cover  # 🎬: a stage starts; the delivered timing splits by these
                                                    # (note / wait / stage print the job's vision count vs budget)
  clipjob.py wait JOB "..."                         # the turn is about to end on Fix (question, turn budget): starts the wait clock;
                                                    # the next clipjob event stops it (resume with `note JOB "resumed"`)
  clipjob.py reopen JOB --reason "..."              # a delivered job gets a revision; the next deliver logs a REVISED row

Exit codes: 0 ok · 1 refused by a rule (message printed) · 2 setup/usage error · 4 pacing (wait_s printed).
Shot states: pending -> submitting -> submitted -> in_review -> approved
             in_review|failed --decide regen--> regen_approved -> (submitting|ingest) ...
             submitting --submit-failed (no credits)--> pending ; --credits-spent--> failed
Shot prompts live in <workdir>/shot<K>.txt (written by IU from the approved storyboard before `pack`/`reserve`).
"""
import argparse
import datetime as dt
import glob
import hashlib
import json
import math
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
DIR = os.environ.get("CLIPJOB_DIR", "/opt/data/clips/jobs")
WORK = os.environ.get("CLIPJOB_WORK", "/opt/data/clips/work")   # durable: cache/scratch is pruned after ~24 h idle
PROMPT_CHUNK = 3500        # Telegram text cap is 4096; leave room for the tag line and HTML
CHAT = os.environ.get("CLIPJOB_CHAT", "8663614341")
CLIP_LOG = os.environ.get("CLIP_LOG", "/opt/data/clips/logs/clip-log.jsonl")
PACING_S = 300
WAIT_CAP_S = 150           # one `reserve --wait` sleeps at most this long: the Hermes terminal tool times out at 180 s
FLOW_MODEL = "Omni 1.2 Flash"   # Omni 1.1 Flash and Veo 3.1 Fast/Quality leave Flow on 2026-12-05
SHOT_SECONDS = 10          # default and cap of one generation: seconds 11-15 bill at double rate
SHOT_MIN = 3
# credits per second for a 3-10 s generation. 720p is measured (withat-softener 2026-11-15: Flow's panel read
# "6 Sec · Generating will use 18 credits", an 8 s shot billed 24); 360p is a third-party figure. Flow's line
# wins, and `submitted --credits` records what was read.
RATE = {"720p": 3, "360p": 1}
# Fix 2026-11-17: "หลังทำคลิปเสร็จและส่งงานแล้ว อยากให้ส่งคลิป, hashtag กับ link ปักตะกร้าไปแชทของ secretary"
# The copy is sent AS the Secretary bot (a file_id from Hermes' bot is useless to another bot), so the mp4 is
# uploaded again. The token stays in the env: the send scripts get only its NAME (TG_TOKEN_ENV), never argv.
MIRROR_TOKEN_ENV = "SECRETARY_TELEGRAM_BOT_TOKEN"
MIRROR_CHAT_ENV = "SECRETARY_TELEGRAM_CHAT_ID"
# 2026-11-17 d-branner-toothpaste: Hermes ran `deliver` from its execute_code tool, whose child env drops every
# name that looks like a secret (and TZ). The Secretary copy was silently off and the stamps were UTC. The gateway
# process (same uid, same container) holds the compose env, so missing names are taken from there.
HERMES_DB = os.environ.get("CLIPJOB_STATE_DB", "/opt/data/state.db")   # Hermes sessions: clarify waits
GATEWAY_PID = os.environ.get("CLIPJOB_GATEWAY_PID", "/opt/data/gateway.pid")
PROC = "/proc"
ADOPT_ENV = (MIRROR_TOKEN_ENV, MIRROR_CHAT_ENV, "TZ")
FINALS_DIR = os.environ.get("CLIPJOB_FINALS", "/opt/data/clips/finals")   # delivered final + cover, for review
KEEP_DAYS = 7              # Fix 2026-11-16: keep them a week (cleanup deletes the workdir and Downloads copies)
CHAR_DIR = os.environ.get("CLIPJOB_CHARS", "/opt/data/clips/characters")   # <name>.jpg portrait per roster name
# Fix 2026-11-16: "หลังส่งงาน ... ขึ้นปุ่มกดจบงาน ถ้าไม่กดภายใน 5 นาทีให้จบงานเอง"
CLOSE_S = int(os.environ.get("CLIPJOB_CLOSE_S", "300"))
CLOSE_GRACE_S = 60         # the lazy sweep leaves a just-due job to its own sleeper for this long
CLOSE_BTN = "🏁 จบงาน"
CLOSE_RE = re.compile(r"^🏁 จบงาน · ([a-z0-9][a-z0-9-]{0,40})$")
# Fix 2026-11-23: "เลือกให้ gen prompt ... อยากให้มีปุ่มเผื่อเปลี่ยนใจให้ hermes ทำให้ต่อเองได้" (genme switched by
# typing). No "ทำต่อ" in the label: pending-work-triage takes that word as a resume order.
TAKEOVER_BTN = "🤖 ไอยูกด Flow แทน"
TAKEOVER_RE = re.compile(r"^🤖 ไอยูกด Flow แทน · ([a-z0-9][a-z0-9-]{0,40})$")
DOWNLOADS = [d for d in os.environ.get("CLIPJOB_DOWNLOADS", "/opt/data/Downloads:/opt/data/home/Downloads").split(":") if d]
# regenerable leftovers of a delivered job: frame/contact sheets, vision preps, start frames, logs, html dumps
JUNK_RE = re.compile(r"(sheet[^/]*\.(jpe?g|png|webp)|\.v\.jpe?g|_last(frame)?\.jpe?g|\.(log|html))$", re.I)
INFO_FLAGS = [re.compile(r"auto-added")]   # report flags that only inform (post_presenter adds the CTA pill itself)
FLOW_MODES = ("presenter", "product", "hands")   # hands = product pipeline, hands in frame, no face
MODES = FLOW_MODES + ("gameplay",)
JOB_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
# champion-trashbag-roll 2026-11-22: the prompt said "The presenter is น้องเอิร์ธ" and Flow painted that name on the
# wall for 2 s. A Thai nickname outside the quoted voiceover is refused before credits / Fix's time are spent.
NAME_RE = re.compile(r"น้อง[ก-๙]+")
QUOTED_RE = re.compile(r'["“][^"”]*["”]')
# --identity kinds: what drifted decides the wording of the review line (eucerin 2026-11-19 read "สินค้าเพี้ยน"
# for a wrong presenter) and a count drift (onesuper 2026-11-22: 2 compartments vs 3) puts 🔁 first.
IDENTITY_KINDS = {"drift": "สินค้าไม่ตรงรูปอ้างอิง", "count": "จำนวนชิ้น/ช่องไม่ตรงรูปอ้างอิง",
                  "presenter": "หน้าคนไม่ตรงตัวละคร"}
FIX_REVIEWED = "ฟิกรีวิวเองตอน gen ใน Flow"   # Fix 2026-11-22: "gen prompt แล้วผม reply กลับ ถือว่ารีวิวแล้ว ตีผ่านหมด"
APPROVE, REGEN = "✅ ผ่าน", "🔁 gen ใหม่"
DECISION_RE = re.compile(r"^(✅ ผ่าน|🔁 gen ใหม่) ช็อต (\d+) · ([a-z0-9][a-z0-9-]{0,40})$")
TAG_RE = re.compile(r"\[ช็อต (\d+) · ([a-z0-9][a-z0-9-]{0,40})\]")
MIN_W, MIN_H, MIN_KBPS = 720, 1280, 1500
CJK_RE = re.compile(r"[　-ヿ㐀-䶿一-鿿가-힯＀-￯]")
MONEY_RE = re.compile(r"฿|\$|%|บาท|ราคา|ส่วนลด|ลด\s*\d|\b(price|sale|off|baht|discount|promo|cheap)\b", re.I)
# whisper small spells "ลิงก์อยู่ใต้คลิป" as "ลิ้งอยู่ต้ายคลิป" — loose on purpose; a false positive only flags.
CTA_PATTERNS = [
    ("ลิงก์", re.compile(r"ลิ[่้]?ง[กค]?|ลิ้น[กค]|\blink\b", re.I)),
    ("ใต้คลิป", re.compile(r"(ใต้|ไต้|ใต|ต้าย|ไต)\s*คลิป")),
    ("คำอธิบาย", re.compile(r"คำอธิบาย")),
    ("พิกัด", re.compile(r"พิกัด")),
    ("ตะกร้า", re.compile(r"ตร?ะ?กร้า")),
]


class Refused(Exception):
    """A rule said no. Exit 1, nothing written."""


class Pacing(Exception):
    def __init__(self, wait_s):
        super().__init__(f"pacing: wait {wait_s}s before the next Flow submit")
        self.wait_s = wait_s


# ---------------------------------------------------------------- pure helpers (unit-tested)
def now():
    return time.time()


def iso(t=None):
    return dt.datetime.fromtimestamp(t if t is not None else now()).astimezone().isoformat(timespec="seconds")


def parse_seconds(text, shots):
    """'8' or '8,6,8' -> one length per shot. Empty = SHOT_SECONDS each."""
    if not text:
        return [SHOT_SECONDS] * shots
    try:
        secs = [int(x) for x in str(text).split(",")]
    except ValueError:
        raise Refused("--seconds takes whole numbers: 8 or 8,6,8")
    if len(secs) == 1 and shots:
        secs *= shots
    if shots and len(secs) != shots:
        raise Refused(f"--seconds names {len(secs)} lengths for {shots} shots")
    bad = [s for s in secs if not SHOT_MIN <= s <= SHOT_SECONDS]
    if bad:
        raise Refused(f"a shot is {SHOT_MIN}-{SHOT_SECONDS} s ({bad}): {FLOW_MODEL} bills seconds 11-15 at double "
                      "rate, so split a longer beat into two shots or cover it in post")
    return secs


def cost(secs, res="720p"):
    """Estimated credits for the given shot lengths. An estimate: the Flow panel line is the truth."""
    if res not in RATE:
        raise Refused(f"--res must be one of {sorted(RATE)}")
    per = [s * RATE[res] for s in secs]
    return {"model": FLOW_MODEL, "res": res, "seconds": secs, "credits": per, "total": sum(per),
            "regen_one": max(per) if per else 0,
            "note": "estimate from published rates; quote Flow's 'Generating will use N credits' line when read"}


def shot_seconds(s):
    return s.get("seconds") or SHOT_SECONDS


def character_image(name):
    for ext in ("jpg", "jpeg", "png"):
        f = os.path.join(CHAR_DIR, f"{name}.{ext}")
        if name and os.path.exists(f):
            return f
    return None


def new_job(job, mode, product, link="", shots=0, refs=(), workdir=None, character=None, seconds=None):
    if not JOB_RE.match(job):
        raise Refused("job slug must match [a-z0-9][a-z0-9-]{0,40}")
    if mode not in MODES:
        raise Refused(f"mode must be one of {MODES}")
    if mode in FLOW_MODES and not 1 <= shots <= 8:
        raise Refused("Flow modes need --shots 1..8 (from the approved storyboard)")
    if mode == "presenter" and not character:
        raise Refused("presenter needs --character (the roster pick; the prompt pack tells Fix which one to attach)")
    if mode in FLOW_MODES and not refs:
        raise Refused("Flow modes need at least one clean product photo (--ref) — run the photo gate first")
    secs = parse_seconds(seconds, shots) if mode in FLOW_MODES else []
    t = now()
    return {"job": job, "mode": mode, "product": product, "link": link, "status": "open",
            "production": None, "character": character, "refs": [os.path.abspath(r) for r in refs],
            "workdir": workdir or os.path.join(WORK, job),
            "created": iso(t), "updated": iso(t), "fallback": None, "trouble": {},
            "shots": fresh_shots(secs) if mode in FLOW_MODES else [],
            "events": [], "delivery": None}


def fresh_shots(secs):
    return [{"k": k, "seconds": sec, "state": "pending", "attempts": [], "raw": None, "file": None,
             "gates": None, "pack_msg": None} for k, sec in enumerate(secs, 1)]


def reshape(j, shots, seconds=None):
    """Change the approved shot plan before anything was rendered (gotg-encore-s2 2026-11-20: 6+4 s -> one 10 s
    scene meant cancel + a new job). -> the new seconds list."""
    need_open(j); need_flow(j)
    used = [s["k"] for s in j["shots"] if s["attempts"]]
    if used:
        raise Refused(f"shot(s) {used} already have a render or a Flow attempt — reshape is only for before any "
                      "spend; regenerate per shot, or cancel and open a new job")
    if not 1 <= shots <= 8:
        raise Refused("--shots 1..8")
    secs = parse_seconds(seconds, shots)
    old = [shot_seconds(s) for s in j["shots"]]
    j["shots"] = fresh_shots(secs)
    log(j, f"reshaped: {old} -> {secs}")
    return secs


def workdir_started(wd, before):
    """Earliest file mtime in the workdir when it is older than `before`: intake and the photo gate run
    before `new`, so the job's clock starts at the first file they wrote."""
    ts = [before]
    for root, _, files in os.walk(wd) if os.path.isdir(wd) else ():
        ts += [os.path.getmtime(os.path.join(root, f)) for f in files]
    return min(ts)


def _epoch(ts):
    return dt.datetime.fromisoformat(ts).timestamp()


def clarify_spans(a, b, db=None):
    """(asked, answered) epochs of Hermes `clarify` calls between a and b, read from its state.db.

    A clarify blocks the turn on Fix without any clipjob event (nikos-bath-toy 2026-11-18: two timed-out asks,
    21 min, logged as wait_fix_min 0). Read-only and best effort: no db / a locked or changed schema = []."""
    db = db or HERMES_DB
    if not os.path.exists(db):
        return []
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            asked = {}
            for ts, tc in c.execute("SELECT timestamp, tool_calls FROM messages WHERE role='assistant' "
                                    "AND timestamp BETWEEN ? AND ? AND tool_calls LIKE '%clarify%'", (a, b)):
                for call in json.loads(tc or "[]"):
                    if (call.get("function") or {}).get("name") == "clarify":
                        asked[call.get("id") or call.get("call_id")] = ts
            asked.pop(None, None)
            if not asked:
                return []
            marks = ",".join("?" * len(asked))
            rows = c.execute(f"SELECT tool_call_id, timestamp FROM messages WHERE role='tool' "
                             f"AND tool_call_id IN ({marks})", list(asked)).fetchall()
        finally:
            c.close()
    except (sqlite3.Error, ValueError, TypeError, AttributeError):
        return []
    return sorted({(asked[i], min(t, b)) for i, t in rows if i in asked and t > asked[i]})


def board_replies(since, db=None):
    """[(epoch, text)] of Fix's replies after `since`: his messages + answered `clarify` calls (state.db).
    None = the db cannot be read (no verdict). plaid-shoulder-blanket 2026-11-23: Fix's 'ไอยูทำใน flow ให้เลยนะ'
    (01:02, before the board existed at 01:19) sat queued through two timed-out board asks, was replayed at 01:41
    and taken as approval: 60 cr on a board he never saw. A queued message keeps its ARRIVAL time, so it is older
    than the board and does not count here."""
    db = db or HERMES_DB
    if not os.path.exists(db):
        return None
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            out = [(ts, (txt or "")[:120]) for ts, txt in c.execute(
                "SELECT timestamp, content FROM messages WHERE role='user' AND timestamp > ? ORDER BY timestamp", (since,))]
            for ts, txt in c.execute("SELECT timestamp, content FROM messages WHERE role='tool' AND tool_name='clarify' "
                                     "AND timestamp > ? ORDER BY timestamp", (since,)):
                try:
                    for r in json.loads(txt or "{}").get("responses", []):
                        if r.get("status") == "answered":
                            out.append((ts, "clarify: " + str(r.get("user_response", ""))[:110]))
                except (ValueError, AttributeError):
                    continue
        finally:
            c.close()
    except sqlite3.Error:
        return None
    return sorted(out)


REVISE_RE = re.compile(r"แก้|ยกเลิก|เลิกทำ|พักงาน|ไม่ผ่าน")   # board answers that are not a go


def board_gate(old, mode):
    """`new` for a Flow mode: the board went out (`clipjob.py board`) and Fix replied after it. -> board record."""
    if mode not in FLOW_MODES:
        return None
    b = (old or {}).get("board") or {}
    if not b.get("sent"):
        raise Refused("no storyboard on record: send the board, run `clipjob.py board <job>`, wait for Fix's reply "
                      "(router step 6 — a standing gate, \"don't ask me\" does not waive it)")
    replies = board_replies(_epoch(b["sent"]))
    if replies is None:
        return {**b, "answer": None, "unverified": "state.db unreadable"}
    if not replies:
        raise Refused(f"no reply from Fix since the board went out at {b['sent'][11:16]} — a message he sent BEFORE it "
                      "(a queued 'ทำเลย' / 'ไอยูทำให้เลย') is not an approval (plaid-shoulder-blanket 2026-11-23: 60 cr "
                      "on a board he never answered). Wait for his tap; zero spend meanwhile")
    ts, txt = replies[-1]
    if txt.startswith("clarify: ") and REVISE_RE.search(txt):
        raise Refused(f"Fix's last answer to the board was {txt[9:]!r}: revise / cancel, not approval. A revised board "
                      "goes out with a new `clipjob.py board <job>`, then ask again")
    return {**b, "answer": txt, "answer_at": iso(ts)}


# Thai chars per second Flow can speak in a shot (codepoints ก-๙ + Latin/digits, the measure of 2026-11-23):
# CTA cut at 12.2 (genme-fly-duck-tee shot 2, 4 s: 'ลิงก์อยู่ใต้คลิปนะ' SKIPPED) and 12.7 (plaid shot 3, 6 s: 50% heard);
# 9-11.4 c/s shipped clean on 30+ presenter shots. The last shot carries the link line and gets the tighter cap.
VO_RATE_MAX = 12.0
VO_RATE_MAX_LAST = 11.5
VO_RE = re.compile(r'Audio \(Thai voiceover\)[^"“]*["“](.+?)["”]', re.S)


def vo_rate(j, k):
    """-> (chars, seconds, chars/s) of shot k's spoken line, or None (no shot file / a silent shot)."""
    path = os.path.join(j["workdir"], f"shot{k}.txt")
    if j.get("mode") != "presenter" or not os.path.exists(path):
        return None
    m = VO_RE.search(open(path, encoding="utf-8").read())
    if not m:
        return None
    n = len(re.findall(r"[ก-๙A-Za-z0-9]", m.group(1)))
    sec = shot_seconds(shot(j, k))
    return n, sec, round(n / sec, 1)


def vo_rate_check(j, k):
    """Before credits / Fix's time: a line too long for its shot loses its tail (the CTA) in Flow."""
    r = vo_rate(j, k)
    if not r or os.environ.get("VO_DENSE_OK"):
        return
    cap = VO_RATE_MAX_LAST if k == len(j["shots"]) else VO_RATE_MAX
    n, sec, rate = r
    if rate > cap:
        need = min(10, math.ceil(n / cap))
        raise Refused(f"shot {k}: {n} Thai chars in {sec} s = {rate}/s > {cap}/s — Flow drops the end of the line "
                      f"(genme shot 2 12.2/s and plaid shot 3 12.7/s lost 'ลิงก์อยู่ใต้คลิปนะ'). Cut the line to "
                      f"≤{int(cap * sec)} chars" + (f" or make the shot {need} s (clipjob.py reshape)" if need > sec else "")
                      + " (VO_DENSE_OK=1 only when Fix ordered this exact script)")


VISION_TIMEOUT_S = 400        # a call this long hit Hermes' 420 s tool deadline (aux vision timeout does not hold)


def vision_calls(a, b, db=None):
    """[(asked, answered)] epochs of Hermes `vision_analyze` calls between a and b (state.db); a call with no
    result yet counts up to b. switch2-oblivion-rd 2026-11-22: 13 calls + one 420 s hang on a 🎬 job whose budget
    is ~8 — the budget was prose only. Read-only, best effort: no db / a changed schema = []."""
    db = db or HERMES_DB
    if not os.path.exists(db):
        return []
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
        try:
            asked = {}
            for ts, tc in c.execute("SELECT timestamp, tool_calls FROM messages WHERE role='assistant' "
                                    "AND timestamp BETWEEN ? AND ? AND tool_calls LIKE '%vision_analyze%'", (a, b)):
                for call in json.loads(tc or "[]"):
                    if (call.get("function") or {}).get("name") == "vision_analyze":
                        asked[call.get("id") or call.get("call_id") or f"anon{len(asked)}"] = ts
            done = {}
            if asked:
                marks = ",".join("?" * len(asked))
                done = dict(c.execute(f"SELECT tool_call_id, timestamp FROM messages WHERE role='tool' "
                                      f"AND tool_call_id IN ({marks})", list(asked)).fetchall())
        finally:
            c.close()
    except (sqlite3.Error, ValueError, TypeError, AttributeError):
        return []
    return sorted((t, min(done.get(i) or b, b)) for i, t in asked.items())


def vision_budget(j):
    """Router 'Vision budget per job': intake 1 + photo gate 2 + post sheet 1 + cover 2 = 6, + 1 per 🤖 shot;
    🎬 = 6 + footage windows sheet + one stage sheet = 8."""
    if j["mode"] == "gameplay":
        return 8
    return 6 + sum(1 for sh in j["shots"] if any(at.get("via") == "auto" for at in sh["attempts"]))


def job_vision(j, end=None):
    end = end if end is not None else now()
    start = min(_epoch(j["created"]), _epoch(j["started"])) if j.get("started") else _epoch(j["created"])
    calls = vision_calls(start, end)
    return {"calls": len(calls), "budget": vision_budget(j), "min": round(sum(b - a for a, b in calls) / 60),
            "timeouts": sum(1 for a, b in calls if b - a >= VISION_TIMEOUT_S)}


def vision_warning(v):
    if v["calls"] < v["budget"]:
        return None
    return (f"vision {v['calls']}/{v['budget']} for this job ({v['min']} min) — budget used: decide on what you have "
            "and `note` why; no more vision_analyze unless Fix asks")


def job_asks(j, end):
    """clarify waits inside this job's clock (see timeline)."""
    start = min(_epoch(j["created"]), _epoch(j["started"])) if j.get("started") else _epoch(j["created"])
    return clarify_spans(start, end)


def timeline(j, end=None, asks=()):
    """Where the time went, in minutes, from the job's own events. A revision counts from its reopen.
    `asks` = extra (start, end) waits on Fix that left no event (Hermes clarify calls, job_asks)."""
    ev = [(_epoch(e["ts"]), e["msg"]) for e in j["events"]]
    end = end if end is not None else (ev[-1][0] if ev else now())
    created = _epoch(j["created"])
    mins = lambda a, b: max(0, round((b - a) / 60))
    reopened = [t for t, m in ev if m.startswith("reopened for a revision")]
    if reopened:
        return {"total_min": mins(reopened[-1], end), "stages": [["แก้งาน", mins(reopened[-1], end)]], "wait_fix_min": 0}
    start = min(created, _epoch(j["started"])) if j.get("started") else created
    stages = [["เตรียม", mins(start, created)]]
    decides = [t for t, m in ev if m.startswith("decide shot")]
    spans, ready_at = list(asks), {}
    for (t, m), nxt in zip(ev, [t for t, _ in ev[1:]] + [end]):
        if m.startswith("wait:"):                       # the turn ended on Fix; the next event is the resume
            spans.append((t, max(t, nxt)))
    for t, m in ev:
        mm = re.match(r"(ready|decide) shot (\d+)", m)
        if mm and mm.group(1) == "ready":
            ready_at[mm.group(2)] = t
        elif mm and mm.group(2) in ready_at:
            spans.append((ready_at.pop(mm.group(2)), t))
    wait, upto = 0.0, 0.0                               # union: three shots in review at once are one wait, not three
    for a, b in sorted(spans):
        wait += max(0.0, b - max(a, upto))
        upto = max(upto, b)
    marks = [(t, m[len("stage: "):]) for t, m in ev if m.startswith("stage: ")]
    if decides:
        stages += [["gen+รีวิว", mins(created, decides[-1])], ["post", mins(decides[-1], end)]]
    elif marks:                                         # 🎬: `clipjob.py stage JOB footage|endcard|vo|build|cover`
        if marks[0][0] > created + 60:
            stages.append(["ทำคลิป", mins(created, marks[0][0])])
        for (t, name), nxt in zip(marks, [t for t, _ in marks[1:]] + [end]):
            stages.append([name, mins(t, nxt)])
    else:
        stages.append(["ทำคลิป", mins(created, end)])
    return {"total_min": mins(start, end), "stages": stages, "wait_fix_min": round(wait / 60)}


def timeline_text(tl):
    h, m = divmod(tl["total_min"], 60)
    parts = [f"{k} {v} น." + (f" (รอฟิกตอบ {tl['wait_fix_min']} น.)" if k in ("gen+รีวิว", "ทำคลิป") and tl["wait_fix_min"] else "")
             for k, v in tl["stages"]]
    if tl["wait_fix_min"] and not any(k in ("gen+รีวิว", "ทำคลิป") for k, _ in tl["stages"]):
        parts.append(f"รอฟิกตอบ {tl['wait_fix_min']} น.")      # 🎬 split by `stage`: the wait has no host stage
    return f"⏱ รวม {f'{h} ชม. ' if h else ''}{m} น. · " + " · ".join(parts)


def shot(j, k):
    if not 1 <= k <= len(j["shots"]):
        raise Refused(f"shot {k} out of range 1..{len(j['shots'])}")
    return j["shots"][k - 1]


def log(j, msg):
    j["events"].append({"ts": iso(), "msg": msg})
    j["updated"] = iso()


def need_open(j):
    if j["status"] != "open":
        raise Refused(f"job {j['job']} is {j['status']}")


def need_flow(j):
    if j["mode"] not in FLOW_MODES:
        raise Refused(f"mode {j['mode']} has no Flow shots")


INTAKE_CMDS = ("note", "wait", "cancel", "status", "board")


def intake_job(job, product, link="", mode=None, workdir=None):
    """A job record from the first minute (Fix 2026-11-19 tune): before this a 🧑 job existed only after the
    board was approved, so when a mimo `content_filter` refusal wiped Hermes' history (nual-loop-240w, 46 min
    rebuilding context) `clipjob.py status` showed nothing. `new` fills it in later."""
    if not JOB_RE.match(job):
        raise Refused("job slug must match [a-z0-9][a-z0-9-]{0,40}")
    if mode is not None and mode not in MODES:
        raise Refused(f"mode must be one of {MODES}")
    t = now()
    return {"job": job, "mode": mode, "product": product, "link": link, "status": "open", "stage": "intake",
            "production": None, "character": None, "refs": [], "workdir": workdir or os.path.join(WORK, job),
            "created": iso(t), "updated": iso(t), "fallback": None, "trouble": {}, "shots": [],
            "events": [], "delivery": None}


def promote_intake(old, new):
    """`new` on an intake job: the new record keeps the intake's clock and history."""
    if old.get("stage") != "intake" or old["status"] != "open":
        raise Refused(f"job {old['job']} exists (pick another slug)")
    new.update({"created": old["created"], "events": old["events"]})
    if old.get("started"):
        new["started"] = old["started"]
    return new


def set_production(j, prod):
    need_open(j); need_flow(j)
    if prod not in ("auto", "prompt"):
        raise Refused("production must be auto or prompt")
    if j["production"] == "prompt" and prod == "auto" and j["fallback"]:
        raise Refused("this job already fell back to prompt pack; start a new job to retry auto")
    if prod == "auto":
        # a pack sent in prompt mode leaves shots at 'packed', which reserve() refuses;
        # Fix switching to auto mid-run must un-pack them (nothing was rendered or ingested)
        for s in j["shots"]:
            if s["state"] == "packed":
                s["state"] = "pending"
                s.pop("pack_msg", None)
                log(j, f"shot {s['k']}: packed -> pending (production switched to auto)")
    j["production"] = prod
    log(j, f"production={prod}")


def reserve(j, k, last_reserve, t=None):
    """-> new last_reserve. Raises Pacing / Refused."""
    t = now() if t is None else t
    need_open(j); need_flow(j)
    if j["production"] != "auto":
        raise Refused("reserve is for auto production only (prompt pack: Fix submits in his own Flow)")
    s = shot(j, k)
    if s["state"] not in ("pending", "regen_approved"):
        raise Refused(f"shot {k} is {s['state']}; a rendered or failed shot needs Fix's 🔁 first")
    cta_order_check(j, k)
    name_check(j, k)
    vo_rate_check(j, k)
    if k > 1:
        prev = shot(j, k - 1)
        if prev["state"] not in ("in_review", "approved"):
            raise Refused(f"shot {k - 1} has not rendered yet (its last frame is shot {k}'s start frame)")
        if prev["state"] == "in_review" and not gates_passed(prev.get("gates") or {}):
            raise Refused(f"shot {k - 1} is in review with a failed gate — its last frame may be thrown away. "
                          f"Wait for Fix's ✅/🔁 on shot {k - 1} before spending credits on shot {k}")
    if last_reserve and t - last_reserve < PACING_S:
        raise Pacing(int(PACING_S - (t - last_reserve)) + 1)
    s["state"] = "submitting"
    s["attempts"].append({"via": "auto", "reserved_at": iso(t)})
    log(j, f"reserve shot {k}")
    return t


def real_edit_id(edit_id):
    """A placeholder ('pending-…', empty) is not an id."""
    e = (edit_id or "").strip()
    return e if e and not e.lower().startswith("pending") else None


def set_edit_id(j, k, edit_id):
    s = shot(j, k)
    if not s["attempts"]:
        raise Refused(f"shot {k} has no attempt to attach an edit id to")
    if not real_edit_id(edit_id):
        raise Refused("that is a placeholder, not a Flow edit id")
    s["attempts"][-1]["edit_id"] = edit_id.strip()
    log(j, f"edit id shot {k} = {edit_id.strip()}")


def est_credits(s):
    return shot_seconds(s) * RATE["720p"]


def submitted(j, k, edit_id=None, credits=None):
    s = shot(j, k)
    if s["state"] != "submitting":
        raise Refused(f"shot {k} is {s['state']}, not submitting (reserve first)")
    s["state"] = "submitted"
    s["attempts"][-1].update({"submitted_at": iso(), "edit_id": real_edit_id(edit_id),
                              "credits": credits if credits is not None else est_credits(s),
                              **({} if credits is not None else {"credits_est": True})})
    log(j, f"submitted shot {k} edit_id={edit_id}")


def billed_credits(j):
    """Credits per submitted attempt; a failed card that Flow refunded (no --credits-spent) is not billed."""
    return [at.get("credits") for s in j["shots"] for at in s["attempts"]
            if at.get("submitted_at") and not (at.get("failed") and not at.get("credits_spent"))]


def submit_failed(j, k, reason, credits_spent=False):
    """-> True when this failure triggers the fallback to prompt pack."""
    s = shot(j, k)
    if s["state"] not in ("submitting", "submitted"):
        raise Refused(f"shot {k} is {s['state']}")
    s["attempts"][-1].update({"failed": reason, "credits_spent": bool(credits_spent), "failed_at": iso()})
    s["state"] = "failed" if credits_spent else "pending"
    log(j, f"submit failed shot {k}: {reason} (credits_spent={bool(credits_spent)})")
    fails = sum(1 for x in j["shots"] for a in x["attempts"] if a.get("failed"))
    return "unusual activity" in reason.lower() or fails >= 2


def trouble(j, step, reason):
    """Count a Flow-driving failure on a named step. -> True on the 2nd hit (fallback)."""
    need_open(j); need_flow(j)
    j["trouble"][step] = j["trouble"].get(step, 0) + 1
    log(j, f"trouble {step}#{j['trouble'][step]}: {reason}")
    return j["trouble"][step] >= 2


def fallback(j, reason):
    """Switch to prompt pack. -> shots that still need generating (pending / regen_approved / failed)."""
    need_open(j); need_flow(j)
    for s in j["shots"]:
        if s["state"] == "submitting":          # reserved, never confirmed sent: treat as not sent
            s["state"] = "pending"
            s["attempts"][-1]["abandoned"] = "fallback"
    j["production"] = "prompt"
    todo = [s["k"] for s in j["shots"] if s["state"] in ("pending", "regen_approved")]
    j["fallback"] = {"at": iso(), "reason": reason, "pack_shots": todo,
                     "credits_spent_shots": spent_shots(j),
                     "in_flight": [s["k"] for s in j["shots"] if s["state"] == "submitted"]}
    log(j, f"fallback to prompt pack: {reason}")
    return todo


def spent_shots(j):
    out = []
    for s in j["shots"]:
        if any(a.get("submitted_at") or a.get("credits_spent") for a in s["attempts"]):
            out.append(s["k"])
    return out


def prompt_messages(job, k, total, prompt, seconds, chain=""):
    """Telegram texts for one shot. Every part carries the tag, so a reply to any part maps back."""
    parts = [prompt[i:i + PROMPT_CHUNK] for i in range(0, len(prompt), PROMPT_CHUNK)] or [""]
    out = []
    for i, part in enumerate(parts, 1):
        head = f"{shot_tag(job, k)} ช็อต {k}/{total} · 9:16 · {seconds} วิ"
        if len(parts) > 1:
            head += f" · ส่วน {i}/{len(parts)} (ก๊อปทุกส่วนต่อกัน)"
        if i == 1:
            head += f"{chain}\nreply ข้อความนี้พร้อมแนบ mp4 ของช็อตนี้"
        text = f"{head}\n\n<pre>{html_escape(part)}</pre>"
        if len(text) > 4096:
            raise Refused(f"shot {k} prompt part {i} is {len(text)} chars after HTML escaping (> 4096)")
        out.append(text)
    return out


def pack_targets(j, only=None):
    need_open(j); need_flow(j)
    if j["production"] != "prompt":
        raise Refused("pack needs production=prompt (Fix's choice or a fallback)")
    if only:
        s = shot(j, only)
        if s["state"] not in ("pending", "regen_approved", "packed"):
            raise Refused(f"shot {only} is {s['state']}; it needs Fix's 🔁 before it is packed again")
        return [only]
    return [s["k"] for s in j["shots"] if s["state"] in ("pending", "regen_approved")]


def shot_tag(job, k):
    return f"[ช็อต {k} · {job}]"


def parse_tag(text):
    m = TAG_RE.search(text or "")
    return (m.group(2), int(m.group(1))) if m else None


def ingest(j, k, path, credits=None):
    """Record Fix's file for shot k. -> the durable copy's path inside the job workdir (inbound media
    caches are pruned by age; a 📝 job can wait a day for Fix). credits: the real figure when Fix says it
    (a shot rendered on Omni 1.1 = half the 1.2 estimate; ps2-hdd-175-pres shot 2, 2026-11-24)."""
    need_open(j); need_flow(j)
    s = shot(j, k)
    if s["state"] == "approved" and j["production"] == "prompt":
        log(j, f"shot {k}: Fix sent a new file for an approved shot — it replaces the old one")
    elif s["state"] not in ("pending", "packed", "regen_approved", "in_review"):
        raise Refused(f"shot {k} is {s['state']}; cannot take a file for it")
    if s["state"] == "in_review":
        raise Refused(f"shot {k} already has a file in review — Fix taps 🔁 first, then sends the new one")
    n = len(s["attempts"]) + 1
    dst = os.path.join(j["workdir"], f"shot{k}_a{n}{os.path.splitext(path)[1] or '.mp4'}")
    s["state"] = "submitted"
    # 📝: Fix renders in his own Flow, so the spend is the published rate for the shot's length (clip-log had
    # credits: null on six 📝 jobs of 11-19..22 — the board's quota line then under-counted the day)
    s["attempts"].append({"via": "prompt", "submitted_at": iso(), "file_in": dst, "source": os.path.abspath(path),
                          **({"credits": credits} if credits is not None
                             else {"credits": est_credits(s), "credits_est": True})})
    log(j, f"ingest shot {k}: {os.path.basename(path)} -> {os.path.basename(dst)}")
    return dst


def has_face(img):
    """Haar face in a still (facecheck.py). -> True / False / None when the check itself failed."""
    p = subprocess.run(["uv", "run", "--with", "opencv-python-headless<5", "--with", "numpy", "python",
                        os.path.join(HERE, "facecheck.py"), img], capture_output=True, text=True)
    try:
        return bool(json.loads(p.stdout.strip().splitlines()[-1])["face"]) if p.returncode == 0 else None
    except (ValueError, IndexError, KeyError):
        return None


def shot_file(s):
    """The newest file of a shot: the reviewed one, else the last ingested attempt."""
    return s.get("file") or next((a.get("file_in") for a in reversed(s["attempts"]) if a.get("file_in")), None)


def start_frame_for(j, k, files=None):
    """Start frame for shot k = the last frame of shot k-1 (same room, light, outfit). 🧑: a last frame with no
    face is skipped for the newest earlier one that shows her (uneed-pb-1 2026-11-18: hands-only shot 2 -> a new
    woman in shot 3, three gens). No earlier face = no start frame; character chip + refs carry her.
    -> {"file": jpg|None, "from": shot|None, "faceless": [shots skipped], "unchecked": bool}"""
    files = files or {}
    res = {"file": None, "from": None, "faceless": [], "unchecked": False}
    for m in range(k - 1, 0, -1):
        src = files.get(m) or shot_file(shot(j, m))
        if not src:
            break
        lf = last_frame(src, os.path.join(j["workdir"], f"shot{m}_last.jpg"))
        if not lf:
            break
        face = has_face(lf) if j["mode"] == "presenter" else True
        if face is None:                     # the check failed: old behaviour, say so
            res["unchecked"] = True
        if face is not False:
            res.update({"file": lf, "from": m})
            return res
        res["faceless"].append(m)
    return res


def start_frame_text(j, k, sf):
    """The line that goes with shot k's start frame (or with its absence)."""
    if sf["file"]:
        note = (f" · ช็อต {', '.join(map(str, sf['faceless']))} ไม่เห็นหน้า เลยใช้ท้ายช็อต {sf['from']}"
                if sf["faceless"] else "")
        return f"เฟรมเริ่มของช็อต {k} (= เฟรมท้ายช็อต {sf['from']}{note}) · {j['job']}\nแนบเป็น start frame ตอน gen ช็อต {k}"
    who = f"ตัวละคร {j['character']} + " if j.get("character") else ""
    return (f"ช็อต {k} · {j['job']}: ไม่ต้องแนบ start frame — ช็อตก่อนหน้าไม่เห็นหน้า "
            f"(Flow จะวาดคนใหม่) แนบแค่{who}รูปสินค้า เหมือนช็อต 1")


def next_start_frame(j, k, file):
    """📝 mode: shot k's file just arrived and shot k+1 is not generated yet. -> start_frame_for(k+1) or None."""
    nxt = next((s for s in j["shots"] if s["k"] == k + 1), None)
    if not nxt or nxt["state"] not in ("pending", "packed", "regen_approved"):
        return None
    return start_frame_for(j, k + 1, {k: file})


def keep_final(label, final, cover, t=None):
    """Copy the delivered final + cover to FINALS_DIR and drop copies older than KEEP_DAYS. -> kept paths."""
    os.makedirs(FINALS_DIR, exist_ok=True)
    t = t if t is not None else now()
    for f in glob.glob(os.path.join(FINALS_DIR, "*")):
        if os.path.isfile(f) and t - os.path.getmtime(f) > KEEP_DAYS * 86400:
            os.remove(f)
    kept = []
    for src, name in ((final, label + ".mp4"), (cover, f"{label}_cover{os.path.splitext(cover)[1] or '.jpg'}")):
        kept.append(shutil.copyfile(src, os.path.join(FINALS_DIR, name)))
    return kept


# ---------------------------------------------------------------- close (🏁 tap or 5 min after deliver)
def close_keyboard(job):
    return {"keyboard": [[{"text": f"{CLOSE_BTN} · {job}"}]], "one_time_keyboard": True, "resize_keyboard": True}


def arm_close(j, t=None):
    """Called by deliver: the job closes itself CLOSE_S later unless Fix taps 🏁 first.
    The token ties the timer to THIS delivery: a reopen or a re-deliver makes an older timer a no-op."""
    t = t if t is not None else now()
    j["close"] = {"state": "pending", "due": iso(t + CLOSE_S), "due_ts": t + CLOSE_S,
                  "token": f"{(j.get('delivery') or {}).get('sha256', '')[:12]}-{int(t)}"}
    return j["close"]


def parse_close_text(text):
    m = CLOSE_RE.match((text or "").strip())
    return m.group(1) if m else None


# ---------------------------------------------------------------- 🤖 takeover (📝 job, Fix changes his mind)
def takeover_todo(j):
    """Shots Hermes would render if Fix hands Flow back. [] = no 🤖 button (not 📝, a fallback job, nothing left)."""
    if (j.get("status") != "open" or j.get("mode") not in FLOW_MODES or j.get("production") != "prompt"
            or j.get("fallback")):
        return []
    return [s["k"] for s in j["shots"] if s["state"] in ("pending", "packed", "regen_approved")]


def takeover_keyboard(j):
    if not takeover_todo(j):
        return None
    return {"keyboard": [[{"text": f"{TAKEOVER_BTN} · {j['job']}"}]], "one_time_keyboard": True,
            "resize_keyboard": True}


def takeover_cost(j, todo):
    return sum(est_credits(shot(j, k)) for k in todo)


def takeover_offer_text(j):
    todo = takeover_todo(j)
    return (f"เปลี่ยนใจให้ไอยูกด Flow เองก็ได้ค่ะ: กดปุ่ม {TAKEOVER_BTN} ด้านล่าง\n"
            f"ไอยูเริ่มที่ช็อต {todo[0]} · ช็อต {', '.join(map(str, todo))} ≈{takeover_cost(j, todo)} เครดิต\n"
            "ถ้ากำลัง gen ช็อตไหนใน Flow อยู่ ส่งไฟล์ช็อตนั้นกลับมาก่อนแล้วค่อยกด (ไม่งั้นเสียเครดิตซ้ำ)")


def parse_takeover_text(text):
    m = TAKEOVER_RE.match((text or "").strip())
    return m.group(1) if m else None


def takeover(j):
    """Fix's 🤖 tap: this 📝 job becomes 🤖 for the shots left. -> {"todo": [...], "credits": N} or {"why": ...}
    (a reason Fix reads; nothing changed)."""
    if j.get("status") != "open":
        return {"why": f"งาน {j['job']} ปิดไปแล้วค่ะ"}
    if j.get("production") == "auto":
        return {"why": f"ไอยูกด Flow ให้งาน {j['job']} อยู่แล้วค่ะ"}
    if j.get("fallback"):
        return {"why": f"งาน {j['job']} สลับมาโหมด prompt เพราะ Flow ติด ({j['fallback'].get('reason', '')}) "
                       "ไอยูเลยกดต่อไม่ได้ค่ะ ฟิกส่งไฟล์มาตามเดิมนะคะ"}
    todo = takeover_todo(j)
    if not todo:
        return {"why": f"งาน {j['job']} ไม่มีช็อตเหลือให้ gen แล้วค่ะ"}
    set_production(j, "auto")
    log(j, f"🤖 takeover tap: shots {todo}")
    return {"todo": todo, "credits": takeover_cost(j, todo)}


def _under(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path.startswith(root.rstrip("/") + "/")


def _rm(path, removed):
    """-> bytes freed; 0 when the file vanished meanwhile (a tap racing the timer, the agent's own cleanup)."""
    try:
        size = os.path.getsize(path)
        os.remove(path)
    except OSError:
        return 0
    removed.append(path)
    return size


def close_cleanup(j):
    """Delete only what is provably this job's and regenerable. -> {"removed": [...], "freed": bytes}.
    Never removes a directory (a deleted cwd breaks every later terminal call, 2026-11-15) and keeps the
    revision set: shot files, scenes, plan/subs/gfx/fx, fonts, refs, board, report, the cover (a re-deliver
    needs --cover, and the cover is picked by hand, not rebuilt by a script)."""
    d = j.get("delivery") or {}
    kept = [k for k in (d.get("kept") if isinstance(d.get("kept"), list) else [])
            if k.lower().endswith(".mp4") and os.path.isfile(k)]           # the final only
    kept_sha = {}
    for k in kept:
        kept_sha.setdefault(os.path.getsize(k), set()).add(sha256(k))
    removed, freed, twins = [], 0, {}
    wd = j.get("workdir")
    if wd and os.path.isdir(wd) and _under(wd, WORK):
        for root, dirs, files in os.walk(wd):
            dirs[:] = [x for x in dirs if x != "fonts"]
            for f in files:
                p = os.path.join(root, f)
                try:
                    if os.path.islink(p) or not os.path.isfile(p):
                        continue
                    size = os.path.getsize(p)
                    if JUNK_RE.search(f) or (size in kept_sha and sha256(p) in kept_sha[size]):
                        freed += _rm(p, removed)  # the final lives on in FINALS_DIR
                    elif f.lower().endswith(".mp4"):
                        twins.setdefault(size, []).append(p)
                except OSError:
                    continue
    for dl in DOWNLOADS:
        if not os.path.isdir(dl):
            continue
        for f in os.listdir(dl):
            p = os.path.join(dl, f)
            try:
                if os.path.islink(p) or not os.path.isfile(p):
                    continue
                size = os.path.getsize(p)
                if size not in kept_sha and size not in twins:
                    continue
                h = sha256(p)
                if h in kept_sha.get(size, ()):
                    freed += _rm(p, removed)
                    continue
                twin = next((w for w in twins.get(size, []) if os.path.isfile(w) and sha256(w) == h), None)
            except OSError:
                continue
            if twin:                              # a shot download the workdir holds byte-for-byte
                for s in j.get("shots") or []:
                    if s.get("file") and os.path.abspath(s["file"]) == os.path.abspath(p):
                        s["file"] = twin          # repointed before the delete, saved with the close
                freed += _rm(p, removed)
    return {"removed": removed, "freed": freed}


def close_job(j, by):
    """-> result dict. Idempotent: a second close (tap after the timer, or the other way round) changes nothing."""
    c = j.get("close") or {}
    if c.get("state") == "closed":
        return {"job": j["job"], "already_closed": c}
    if j["status"] != "delivered":
        raise Refused(f"job {j['job']} is {j['status']}; only a delivered job is closed")
    res = close_cleanup(j)
    mb = round(res["freed"] / 1e6, 1)
    j["close"] = {"state": "closed", "at": iso(), "by": by, "freed_mb": mb,
                  "removed": [os.path.basename(p) for p in res["removed"]]}
    log(j, f"closed by {by}: {len(res['removed'])} file(s), {mb} MB")
    return {"job": j["job"], "closed": j["close"]}


def close_text(j):
    c = j["close"]
    how = "อัตโนมัติ (ไม่ได้กดใน 5 นาที)" if c["by"].startswith("auto") else "ตามที่กด"
    kept = (j.get("delivery") or {}).get("kept")
    return (f"🏁 ปิดงาน {j['job']} แล้วค่ะ · {how}\nลบไฟล์ชั่วคราว {len(c['removed'])} ไฟล์ ({c['freed_mb']} MB)"
            + (f"\nคลิป + ปกเก็บไว้ที่ clips/finals {KEEP_DAYS} วัน" if isinstance(kept, list) else ""))


def spawn_closer(j):
    """Detached sleeper: its own session, no inherited pipes, so the terminal tool returns at once and
    Hermes does not track it as a background process. A gateway restart kills it; the sweep covers that."""
    if os.environ.get("CLIPJOB_NO_TIMER"):
        return None
    os.makedirs(os.path.dirname(CLIP_LOG), exist_ok=True)
    out = open(os.path.join(os.path.dirname(CLIP_LOG), "close-timer.log"), "a")
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "close", j["job"], "--auto",
                          "--token", j["close"]["token"], "--after", str(CLOSE_S)],
                         stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                         start_new_session=True, close_fds=True, cwd="/")
    out.close()
    return p.pid


def due_closes(t=None):
    """Delivered jobs whose close is overdue (their sleeper died with a gateway restart)."""
    t = t if t is not None else now()
    out = []
    for f in sorted(os.listdir(DIR)) if os.path.isdir(DIR) else []:
        if not f.endswith(".json") or f == "pacing.json":
            continue
        try:
            jj = json.load(open(os.path.join(DIR, f), encoding="utf-8"))
        except (OSError, ValueError):
            continue
        c = jj.get("close") or {}
        if jj.get("status") == "delivered" and c.get("state") == "pending" and c.get("due_ts", 0) + CLOSE_GRACE_S < t:
            out.append(jj["job"])
    return out


def sweep_closes():
    """Runs before every clipjob command; never lets a close problem break the command itself."""
    try:
        for job in due_closes():
            j = load(job)
            close_job(j, "auto (late)"); save(j)
            notify(close_text(j))
    except Exception as e:                     # best effort by design
        print(f"close sweep skipped: {e}", file=sys.stderr)


def probe_verdict(info):
    """ffprobe dict -> gate. info: {w,h,dur,kbps,vcodec,has_audio}."""
    if not info:
        return {"ok": False, "note": "ffprobe failed"}
    probs = []
    if info["dur"] <= 1.0:
        probs.append(f"สั้น {info['dur']:.1f} วิ")
    if info["w"] < MIN_W or info["h"] < MIN_H:
        probs.append(f"ความละเอียด {info['w']}x{info['h']} ต่ำกว่า 720x1280 (Telegram บีบไฟล์? ส่งแบบไฟล์แทน)")
    elif info.get("kbps") and info["kbps"] < MIN_KBPS:
        probs.append(f"bitrate {info['kbps']} kbps ต่ำ (Telegram บีบไฟล์? ส่งแบบไฟล์แทน)")
    if info["h"] and info["w"] and abs(info["w"] / info["h"] - 9 / 16) > 0.02:
        probs.append(f"สัดส่วน {info['w']}x{info['h']} ไม่ใช่ 9:16")
    return {"ok": not probs, "dur": round(info["dur"], 2), "note": "; ".join(probs)}


def cta_order_check(j, k):
    """Final presenter shot: the link line closes the script (ctarule.py). Before credits / Fix's time are spent."""
    if j.get("mode") != "presenter" or k != len(j["shots"]) or os.environ.get("CTA_ORDER_OK"):
        return
    path = os.path.join(j["workdir"], f"shot{k}.txt")
    if not os.path.exists(path):
        return
    import ctarule
    why = ctarule.problem(ctarule.voiceover(open(path, encoding="utf-8").read()))
    if why:
        raise Refused(f"shot {k} ({path}): {why}. แก้ลำดับใน Audio (Thai voiceover) แล้วสั่งใหม่ "
                      "(ฟิกสั่งให้เรียงแบบนี้เองเท่านั้นถึงใช้ CTA_ORDER_OK=1)")


def name_check(j, k):
    """No Thai nickname (or the roster name) in the prompt outside the quoted voiceover: Flow draws it as text."""
    path = os.path.join(j["workdir"], f"shot{k}.txt")
    if not os.path.exists(path):
        return
    bare = QUOTED_RE.sub("", open(path, encoding="utf-8").read())
    hits = set(NAME_RE.findall(bare))
    if j.get("character") and j["character"] in bare:
        hits.add(j["character"])
    if hits:
        raise Refused(f"shot {k} ({path}) names {', '.join(sorted(hits))} — Flow paints a name it reads in the prompt "
                      "(champion-trashbag-roll: 'น้องเอิร์ธ' on the wall). Refer to her as 'the presenter (the attached "
                      "character chip)' and describe the look from the portrait; a name may appear only inside the "
                      "quoted voiceover line")


def cta_hits(text):
    return [label for label, rx in CTA_PATTERNS if rx.search(text or "")]


def parse_frame(arg):
    if arg == "pass":
        return {"ok": True, "note": ""}
    if arg.startswith("flag:") and arg[5:].strip():
        return {"ok": False, "note": arg[5:].strip()}
    raise Refused("--frame must be 'pass' or 'flag:<what you saw>' (vision-check the shot first)")


def gates_passed(gates):
    return all(g.get("ok") is True for g in gates.values())


def mark_ready(j, k, file, gates):
    s = shot(j, k)
    if s["state"] != "submitted":
        raise Refused(f"shot {k} is {s['state']}, not submitted")
    s.update({"state": "in_review", "file": os.path.abspath(file), "gates": gates})
    if s.get("chain_stale"):
        s["chain_stale"] = "review"          # rendered from a start frame that was regenerated since
    s["attempts"][-1]["ready_at"] = iso()
    log(j, f"ready shot {k} pass={gates_passed(gates)}")


def parse_decision_text(text):
    m = DECISION_RE.match((text or "").strip())
    if not m:
        return None
    return m.group(3), int(m.group(2)), "approve" if m.group(1) == APPROVE else "regen"


def decide(j, k, decision):
    need_open(j)
    s = shot(j, k)
    stale = bool(s.get("chain_stale"))
    if decision == "approve":
        if s["state"] != "in_review" and not (stale and s["state"] == "approved"):
            raise Refused(f"shot {k} is {s['state']}; only a shot in review can be approved")
        s["state"] = "approved"
        s.pop("chain_stale", None)           # Fix keeps it despite the regenerated start frame
    elif decision == "regen":
        if s["state"] not in ("in_review", "failed") and not (stale and s["state"] == "approved"):
            raise Refused(f"shot {k} is {s['state']}; nothing to regenerate")
        s["state"] = "regen_approved"
        s.pop("chain_stale", None)
    else:
        raise Refused("decision must be approve or regen")
    log(j, f"decide shot {k}: {decision}")
    return mark_chain_stale(j, k) if decision == "regen" else None


def mark_chain_stale(j, k):
    """Shot k is being regenerated, so shot k+1 (which starts on k's last frame) no longer chains.
    -> None, or {"shot", "state", "ask"}; ask=True when Fix must choose keep/regen for k+1 now."""
    if k >= len(j["shots"]):
        return None
    n = j["shots"][k]
    if n["state"] == "submitting":           # reserved, not sent: just take the reservation back
        n["state"] = "pending"
        n["attempts"][-1]["abandoned"] = f"shot {k} regenerated"
        log(j, f"shot {k + 1} reservation dropped (shot {k} regenerated)")
        return {"shot": k + 1, "state": "pending", "ask": False}
    if n["state"] in ("submitted", "in_review", "approved"):
        n["chain_stale"] = "review" if n["state"] != "submitted" else "rendering"
        log(j, f"shot {k + 1} chain is stale (shot {k} regenerated)")
        return {"shot": k + 1, "state": n["state"], "ask": n["state"] != "submitted"}
    return None


def assemble_files(j):
    need_flow(j)
    bad = [f"{s['k']}:{s['state']}" for s in j["shots"] if s["state"] != "approved"]
    if bad:
        raise Refused("not every shot is approved: " + ", ".join(bad))
    stale = [str(s["k"]) for s in j["shots"] if s.get("chain_stale")]
    if stale:
        raise Refused("Fix has not chosen keep/regen for shot(s) " + ", ".join(stale) + " (start frame regenerated)")
    return [s["file"] for s in j["shots"]]


def hashtag_problems(tags):
    out = []
    if len(tags) > 150:
        out.append(f"{len(tags)} chars > 150")
    if CJK_RE.search(tags):
        out.append("CJK/full-width characters")
    if MONEY_RE.search(tags):
        out.append("price/discount wording")
    if not tags.strip().startswith("#"):
        out.append("not a hashtag string")
    return out


def gfx_elements(plan):
    keys = ("headlines", "stickers", "callouts", "badges", "endcard", "image_stickers")
    return sum(len(plan[k]) if isinstance(plan.get(k), list) else (1 if plan.get(k) else 0) for k in keys)


def parse_acks(acks):
    out = []
    for a in acks or []:
        if "=" not in a or not a.split("=", 1)[1].strip():
            raise Refused(f"--ack must be '<flag text>=<what Fix decided>': {a!r}")
        k, v = a.split("=", 1)
        out.append((k.strip(), v.strip()))
    return out


def open_flags(flags, acks):
    """Flags that are neither informational nor acknowledged by Fix's decision."""
    left = []
    for fl in flags:
        fl = str(fl)
        if any(rx.search(fl) for rx in INFO_FLAGS):
            continue
        if any(k and k in fl for k, _ in acks):
            continue
        left.append(fl)
    return left


def deliver_problems(j, report, gfx, tags, acks=()):
    probs = []
    if j["status"] != "open":
        probs.append(f"job is {j['status']}")
    if j["mode"] in FLOW_MODES:
        bad = [f"{s['k']}:{s['state']}" for s in j["shots"] if s["state"] != "approved"]
        if bad:
            probs.append("shots not approved: " + ", ".join(bad))
        stale = [str(s["k"]) for s in j["shots"] if s.get("chain_stale")]
        if stale:
            probs.append("shot(s) " + ", ".join(stale) + " start on a frame that was regenerated — Fix has not "
                         "chosen keep/regen for them yet")
        if gfx_elements(gfx) == 0:
            probs.append("graphics plan is empty — graphics are mandatory on Flow-mode clips")
    flags = open_flags(report.get("flags") or [], acks)
    if flags:
        probs.append(f"report has {len(flags)} FLAG(s) Fix has not decided on (tell him, then --ack '<flag>=<his call>'): "
                     + " | ".join(flags)[:600])
    if report.get("v_dur") and report.get("a_dur") and abs(report["v_dur"] - report["a_dur"]) > 0.1:
        probs.append(f"audio {report['a_dur']} s != video {report['v_dur']} s")
    probs += [f"hashtags: {p}" for p in hashtag_problems(tags)]
    if not (j.get("link") or "").startswith("https://"):
        probs.append("no https basket link on the job (clipjob.py new --link)")
    return probs


# ---------------------------------------------------------------- I/O
def path_of(job):
    return os.path.join(DIR, f"{job}.json")


def load(job):
    p = path_of(job)
    if not os.path.exists(p):
        raise Refused(f"no job {job} (clipjob.py status lists open jobs)")
    return json.load(open(p, encoding="utf-8"))


def save(j):
    os.makedirs(DIR, exist_ok=True)
    tmp = path_of(j["job"]) + ".tmp"
    json.dump(j, open(tmp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    os.replace(tmp, path_of(j["job"]))


def pacing_get():
    p = os.path.join(DIR, "pacing.json")
    return json.load(open(p)).get("last_reserve") if os.path.exists(p) else None


def pacing_set(t):
    os.makedirs(DIR, exist_ok=True)
    json.dump({"last_reserve": t, "at": iso(t)}, open(os.path.join(DIR, "pacing.json"), "w"))


def ffprobe(path):
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "stream=codec_type,codec_name,width,height:format=duration,bit_rate", "-of", "json", path],
                       capture_output=True, text=True)
    if p.returncode:
        return None
    js = json.loads(p.stdout)
    v = next((s for s in js.get("streams", []) if s.get("codec_type") == "video"), None)
    if not v:
        return None
    fmt = js.get("format", {})
    return {"w": int(v.get("width") or 0), "h": int(v.get("height") or 0), "vcodec": v.get("codec_name"),
            "dur": float(fmt.get("duration") or 0), "kbps": int(int(fmt.get("bit_rate") or 0) / 1000),
            "has_audio": any(s.get("codec_type") == "audio" for s in js.get("streams", []))}


def av_durations(path):
    """-> (video_s, audio_s) from the streams, None for a missing stream."""
    p = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", path],
                       capture_output=True, text=True)
    if p.returncode:
        return None, None
    d = {}
    for st in json.loads(p.stdout).get("streams", []):
        try:
            d.setdefault(st.get("codec_type"), float(st.get("duration")))
        except (TypeError, ValueError):
            pass
    return d.get("video"), d.get("audio")


def repeats_gate(raw, script):
    """detect_repeats on a presenter shot -> (gate, file_to_use, asr_text)."""
    cut = os.path.splitext(raw)[0] + "_cut.mp4"
    p = subprocess.run(["uv", "run", "--with", "faster-whisper", "--with", "numpy", "python",
                        os.path.join(HERE, "detect_repeats.py"), raw, "--script", script, "--cut", cut],
                       capture_output=True, text=True)
    if p.returncode == 75:               # heavylock: another heavy job is running
        raise Refused(f"detect_repeats could not start: {p.stderr.strip()[-300:]}")
    try:
        out = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "note": f"detect_repeats exit {p.returncode}: {p.stderr[-200:]}"}, raw, ""
    if p.returncode == 0:
        return {"ok": True, "note": ""}, raw, out.get("asr", "")
    if p.returncode == 3 and out.get("cut_file"):
        cut_s = "; ".join(f"{r['text']} @{r['t0']}s" for r in out["repeats"])
        return {"ok": True, "note": f"ตัดคำซ้ำแล้ว: {cut_s}"}, out["cut_file"], out.get("asr", "")
    return {"ok": False, "note": f"detect_repeats exit {p.returncode}"}, raw, out.get("asr", "")


def tg(method, payload=None, files=None):
    if os.environ.get("CLIPJOB_NO_TG"):
        return {"message_id": 0}
    sys.path.insert(0, HERE)
    from send_clip import read_token
    tok = read_token()
    url = f"https://api.telegram.org/bot{tok}/{method}"
    if files:
        args = ["curl", "-s", "-m", "120"]
        for k, v in (payload or {}).items():
            args += ["-F", f"{k}={v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}"]
        for k, v in files.items():
            args += ["-F", f"{k}=@{v}"]
        r = subprocess.run(args + [url], capture_output=True, text=True)
        js = json.loads(r.stdout or "{}")
    else:
        req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode(),
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            js = json.loads(r.read())
    if not js.get("ok") or not js.get("result", {}).get("message_id"):
        raise Refused(f"Telegram {method} failed: {str(js)[:300]}")
    return js["result"]


def html_escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def review_keyboard(job, k, approve=True, regen_first=False):
    row = ([{"text": f"{APPROVE} ช็อต {k} · {job}"}] if approve else []) + [{"text": f"{REGEN} ช็อต {k} · {job}"}]
    if regen_first:
        row.reverse()
    return {"keyboard": [row], "one_time_keyboard": True, "resize_keyboard": True}


def notify(text, keyboard=None):
    """Best-effort message to Fix. -> True when sent."""
    try:
        tg("sendMessage", {"chat_id": CHAT, "text": text,
                           "reply_markup": keyboard or {"remove_keyboard": True}})
        return True
    except (Refused, OSError, ValueError):
        return False


def stale_text(j, k):
    return (f"⚠️ ช็อต {k} · {j['product']}\nช็อตนี้เริ่มจากเฟรมท้ายของช็อต {k - 1} ชุดเดิม ซึ่งกำลัง gen ใหม่ "
            f"ภาพตรงรอยต่ออาจไม่ต่อเนื่อง\nผ่าน = เก็บช็อต {k} ไว้ · gen ใหม่ = ทำช็อต {k} ใหม่ต่อจากช็อต {k - 1} ชุดใหม่"
            + (" (เสียเครดิต)" if j["production"] == "auto" else ""))


def run(cmd):
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def last_frame(video, out):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-sseof", "-0.1", "-i", video, "-frames:v", "1", "-update", "1",
                    out], check=False)
    return out if os.path.exists(out) else None


SCAN_Q = ("In ANY tile: a face, head, hair, shoulder, torso or a second person (check the tile EDGES); an arm shown "
          "above the forearm; text or a brand name drawn on a prop; a room or product load state that differs from the "
          "previous shot. Answer per tile number; one hit = --frame flag:<what, which tile>.")


def file_sig(path):
    st = os.stat(path)
    return [os.path.abspath(path), st.st_size, int(st.st_mtime)]


def scan_sheets(video, prefix):
    """Tile one frame every 0.5 s, 10 tiles per sheet (5x2, 320 px wide each): a 3-frame check misses what lasts <1 s."""
    for old in glob.glob(prefix + "*.jpg"):
        os.remove(old)
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", video, "-vf", "fps=2,scale=320:-1,tile=5x2",
                    "-q:v", "3", prefix + "%d.jpg"], check=False)
    return sorted(glob.glob(prefix + "*.jpg"))


ID_FRACS = (0.05, 0.25, 0.45, 0.65, 0.85)   # + the last frame: aukey-pby92 morphed between 2 s and 5 s


def id_question(n_refs, times):
    tiles = [f"tile {i} = REFERENCE photo {i}" for i in range(1, n_refs + 1)]
    tiles += [f"tile {n_refs + i} = shot at {t:.1f} s" for i, t in enumerate(times, 1)]
    return ("Tiles left to right: " + "; ".join(tiles) + ". Compare EVERY shot tile with the reference: body shape and "
            "thickness, colour/finish, screen/display size and position, ports, built-in cables, straps, printed "
            "logo. Name each part that differs and in which tiles; a product that changes BETWEEN tiles is drift too. "
            "Answer MATCH, DRIFT: <part, tiles>, COUNT: <part count that differs> (compartments, buttons, pieces) or "
            "PRESENTER: <face/hair differs>. Then ready … --identity match|drift:<what>|count:<what>|presenter:<what>")


def id_sheet(raw, refs, out, dur):
    """refs + 6 frames of the shot, one row, 360 px tall."""
    wd = os.path.dirname(out)
    times = [round(dur * f, 2) for f in ID_FRACS] + [max(0.0, round(dur - 0.1, 2))]
    parts = []
    for i, r in enumerate(refs[:2]):
        parts.append(r)
    for i, t in enumerate(times):
        f = os.path.join(wd, f"_id_{i}.jpg")
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t:.2f}", "-i", raw, "-frames:v", "1", "-update", "1",
                        f], check=False)
        if os.path.exists(f):
            parts.append(f)
    n = len(parts)
    graph = ";".join(f"[{i}:v]scale=-2:360,setsar=1[v{i}]" for i in range(n))
    graph += ";" + "".join(f"[v{i}]" for i in range(n)) + f"hstack=inputs={n}[o]"
    cmd = ["ffmpeg", "-y", "-v", "error"]
    for f in parts:
        cmd += ["-i", f]
    subprocess.run(cmd + ["-filter_complex", graph, "-map", "[o]", "-frames:v", "1", "-q:v", "3", out], check=False)
    for f in parts:
        if os.path.basename(f).startswith("_id_"):
            os.remove(f)
    return (out if os.path.exists(out) else None), times


def cmd_idcheck(j, k, raw):
    need_flow(j)
    if not j["refs"]:
        raise Refused("job has no reference photo to compare against")
    if not raw or not os.path.exists(raw):
        raise Refused(f"no such file: {raw}")
    info = ffprobe(raw)
    if not info or not info["dur"]:
        raise Refused(f"ffprobe cannot read {raw}")
    sheet, times = id_sheet(raw, j["refs"], os.path.join(j["workdir"], f"shot{k}_id.jpg"), info["dur"])
    if not sheet:
        raise Refused(f"ffmpeg made no identity sheet from {raw}")
    shot(j, k)["idcheck"] = {"sig": file_sig(raw), "sheet": sheet}
    log(j, f"idcheck shot {k}")
    return {"shot": k, "sheet": sheet, "ask_vision": id_question(min(len(j["refs"]), 2), times),
            "next": f"ONE vision_analyze on the sheet, then clipjob.py ready {j['job']} {k} --raw {raw} "
                    "--frame pass|flag:<…> --identity match|drift:<…>|count:<…>|presenter:<…>"}


def parse_identity(arg):
    if arg == "match":
        return {"ok": True, "note": ""}
    kind, _, what = (arg or "").partition(":")
    if kind in IDENTITY_KINDS and what.strip():
        return {"ok": False, "kind": kind, "note": f"{IDENTITY_KINDS[kind]}: {what.strip()}"}
    raise Refused("--identity must be match | drift:<product part that differs> | count:<part count that differs, "
                  "e.g. 2 compartments vs 3> | presenter:<how her face/hair differs> (from the idcheck sheet)")


def cmd_scan(j, k, raw):
    if j["mode"] not in FLOW_MODES:
        raise Refused(f"mode {j['mode']} has no Flow shots")
    if not raw or not os.path.exists(raw):
        raise Refused(f"no such file: {raw}")
    sheets = scan_sheets(raw, os.path.join(j["workdir"], f"shot{k}_scan"))
    if not sheets:
        raise Refused(f"ffmpeg made no sheet from {raw}")
    shot(j, k)["scan"] = {"sig": file_sig(raw), "sheets": sheets}
    log(j, f"scan shot {k}: {len(sheets)} sheet(s)")
    return {"shot": k, "sheets": sheets, "ask_vision": SCAN_Q,
            "next": "one vision_analyze per sheet, then clipjob.py ready … --frame pass|flag:<what>"}


# ---------------------------------------------------------------- commands
START_FRAME_RX = re.compile(r"last[- ]frame image|start[- ]frame", re.I)


def cmd_pack(j, only, no_send, no_start_frame=False):
    """no_start_frame: this pack attaches NO start frame (a Flow refusal test, a scene plate): the chain line
    says so and no frame photo goes out. ps2-hdd-175-pres 2026-11-24: the 'no start frame' re-pack still told
    Fix to attach it, so that round never tested what Hermes said it tested."""
    targets = pack_targets(j, only)
    no_frame_text = set()
    if not targets:
        raise Refused("nothing to pack (every shot is submitted, in review or approved)")
    wd = j["workdir"]
    missing = [k for k in targets if not os.path.exists(os.path.join(wd, f"shot{k}.txt"))]
    if missing:
        raise Refused(f"write the prompt files first: {', '.join(f'{wd}/shot{k}.txt' for k in missing)}")
    for k in targets:
        cta_order_check(j, k)
        name_check(j, k)
        vo_rate_check(j, k)
        with open(os.path.join(wd, f"shot{k}.txt"), encoding="utf-8") as f:
            asks_frame = START_FRAME_RX.search(f.read())
        if not asks_frame:
            no_frame_text.add(k)
        if no_start_frame and asks_frame:
            raise Refused(f"--no-start-frame but shot{k}.txt still asks for a start / last-frame image: "
                          "take that sentence out first")
    sent = []
    char_img = character_image(j.get("character"))
    if not no_send and not only:
        head = (f"📝 โหมดเตรียม prompt · {j['product']}\n"
                + (f"สลับจากโหมดอัตโนมัติ: {j['fallback']['reason']}\n" if j.get("fallback") else "")
                + (f"ตัวละคร: {j['character']} (แนบจาก Characters ใน Flow ทุกช็อต"
                   + (" · account ที่ไม่มีตัวนี้ ให้แนบรูปตัวละครด้านล่างเป็น Ingredient แทน" if char_img else "")
                   + ")\n" if j.get("character") else "")
                + f"โมเดล: {FLOW_MODEL} · 720p · x1 (ห้ามเกิน 10 วิ/ช็อต วินาทีที่ 11-15 คิดเครดิต 2 เท่า)\n"
                + f"ช็อตที่ต้องทำ: {', '.join(map(str, targets))}\n\n"
                  "วิธีใช้: เซฟรูปอ้างอิงด้านล่างไปแนบใน Flow (Ingredients) → ก๊อป prompt ของแต่ละช็อต "
                  "→ gen ใน Flow → กด reply ข้อความ prompt ของช็อตนั้นแล้วแนบ mp4 กลับมา "
                  "(ส่งแบบ 'ไฟล์' จะได้ไม่โดนบีบ ไม่เกิน 20 MB)\n"
                  "ไฟล์ที่ส่งกลับมา = ฟิกรีวิวแล้ว ไอยูใช้เลย ไม่ถามซ้ำ"
                  + ("\nทำทีละช็อตตามลำดับ: ส่งช็อตก่อนหน้ากลับมาก่อน แล้วใช้รูปเฟรมเริ่มที่ไอยูส่งให้ "
                     "(gen พร้อมกันสินค้า/ฉากจะไม่ต่อกัน)" if len(targets) > 1 else ""))
        tg("sendMessage", {"chat_id": CHAT, "text": head})
        for i, r in enumerate(j["refs"], 1):
            tg("sendPhoto", {"chat_id": CHAT, "caption": f"รูปอ้างอิง {i}/{len(j['refs'])} · {j['job']}"},
               files={"photo": r})
        if char_img:
            tg("sendPhoto", {"chat_id": CHAT, "caption": f"ตัวละคร {j['character']} · ใช้เมื่อ account นี้ไม่มีตัวละครนี้ "
                                                         "(แนบเป็น Ingredient ทุกช็อต)"}, files={"photo": char_img})
    for k in targets:
        prompt = open(os.path.join(wd, f"shot{k}.txt"), encoding="utf-8").read().strip()
        prev = shot(j, k - 1) if k > 1 else None
        chain = ""
        if prev and no_start_frame:
            chain = "\nเฟรมเริ่ม: รอบนี้ไม่ต้องแนบ แนบแค่ตัวละคร + รูปสินค้าเหมือนช็อต 1"
        elif prev and shot_file(prev):
            sf = start_frame_for(j, k)
            if sf["file"]:
                if not no_send:
                    tg("sendPhoto", {"chat_id": CHAT, "caption": start_frame_text(j, k, sf)}, files={"photo": sf["file"]})
                chain = "\nเฟรมเริ่ม: แนบรูปเฟรมเริ่มที่ส่งไปเมื่อกี้เป็น start frame"
            elif sf["faceless"]:
                chain = "\nเฟรมเริ่ม: ไม่ต้องแนบ (ช็อตก่อนหน้าไม่เห็นหน้า) แนบตัวละคร + รูปสินค้าเหมือนช็อต 1"
        elif prev:
            chain = (f"\nเฟรมเริ่ม: ส่ง mp4 ของช็อต {k - 1} กลับมาก่อน แล้วรอรูป 'เฟรมเริ่มของช็อต {k}' ที่ไอยูส่งให้ "
                     "แนบรูปนั้นเป็น start frame (ห้อง แสง ชุด จะต่อเนื่อง)")
        mid = None
        for text in prompt_messages(j["job"], k, len(j["shots"]), prompt, shot_seconds(shot(j, k)), chain):
            if not no_send:
                r = tg("sendMessage", {"chat_id": CHAT, "text": text, "parse_mode": "HTML"})
                mid = mid or r["message_id"]
        s = shot(j, k)
        s.update({"state": "packed", "pack_msg": mid})
        row = {"shot": k, "message_id": mid}
        if "แนบรูปเฟรมเริ่ม" in chain and k in no_frame_text:
            row["warn"] = (f"shot {k}: Fix was told to attach the start frame, but shot{k}.txt never mentions one — "
                           "if this round is meant to run WITHOUT it (a refusal test), re-pack with --no-start-frame")
        sent.append(row)
    log(j, f"packed shots {targets}")
    kb = takeover_keyboard(j)
    if kb and not no_send:
        tg("sendMessage", {"chat_id": CHAT, "text": takeover_offer_text(j), "reply_markup": kb})
    return sent


def send_review(j, k):
    """Send shot k's file and its gate verdict with the ✅/🔁 keyboard. Raises Refused when a send fails."""
    s = shot(j, k)
    gates, file, total = s["gates"], s["file"], len(j["shots"])
    cap = f"รีวิวช็อต {k}/{total} · {j['product']}"[:1000]
    rc, out, err = run(["python3", os.path.join(HERE, "send_clip.py"), file, cap, CHAT, f"{j['job']}_shot{k}_review"])
    if rc:
        raise Refused(f"shot send FAILED: {out[-300:]} {err[-300:]}")
    lines = [f"🎬 รีวิวช็อต {k}/{total} · {j['product']}", ""]
    for name, g in gates.items():
        lines.append(("✅ " if g.get("ok") else "❌ ") + name + (f" — {g['note']}" if g.get("note") else ""))
    count = (gates.get("identity") or {}).get("kind") == "count"
    if count:
        lines += ["", "❌ จำนวนชิ้น/ช่องไม่ตรงสินค้าจริง — แก้ใน post ไม่ได้ ไอยูแนะนำ 🔁 gen ใหม่"]
    lines += ["", "ผ่านทุกข้อ" if gates_passed(gates) else "⚠️ มีข้อไม่ผ่าน ไอยูแนะนำ gen ใหม่",
              "ผ่าน = ล็อกช็อตนี้ · gen ใหม่ = " + ("เสียเครดิต" if j["production"] == "auto" else "ฟิกทำใน Flow ใหม่")]
    if s.get("chain_stale"):
        lines += ["", f"⚠️ ช็อตนี้เริ่มจากเฟรมท้ายของช็อต {k - 1} ชุดเดิม (ช็อต {k - 1} กำลัง gen ใหม่) รอยต่ออาจไม่ต่อเนื่อง"]
    tg("sendMessage", {"chat_id": CHAT, "text": "\n".join(lines),
                       "reply_markup": review_keyboard(j["job"], k, regen_first=count)})
    s["review_sent"] = iso()


def cmd_ready(j, k, raw, frame_arg, no_send, resend=False, identity_arg=None):
    if resend:
        if shot(j, k)["state"] != "in_review":
            raise Refused(f"shot {k} is {shot(j, k)['state']}; --resend is for a shot already in review")
        send_review(j, k)
        return {"shot": k, "resent": True, "pass": gates_passed(shot(j, k)["gates"])}
    reviewed = fix_reviewed(j, k)
    if not raw or not (frame_arg or reviewed):
        raise Refused("ready needs --raw FILE and --frame pass|flag:<what you saw>")
    frame = parse_frame(frame_arg) if frame_arg else {"ok": True, "note": FIX_REVIEWED}
    if not os.path.exists(raw):
        raise Refused(f"no such file: {raw}")
    if shot(j, k)["state"] != "submitted":
        raise Refused(f"shot {k} is {shot(j, k)['state']}, not submitted")
    if reviewed:
        return ready_reviewed(j, k, raw, frame, identity_arg, no_send)
    if j["mode"] == "hands" and (shot(j, k).get("scan") or {}).get("sig") != file_sig(raw):
        raise Refused(f"✋ shot {k} has no frame scan of this file: run clipjob.py scan {j['job']} {k} --raw {raw}, "
                      "vision-read every sheet (a face at the frame edge lasted under 1 s in the first ✋ job), then ready")
    identity = None
    if j["mode"] in FLOW_MODES and j["refs"]:
        if (shot(j, k).get("idcheck") or {}).get("sig") != file_sig(raw):
            raise Refused(f"shot {k} has no identity sheet of this file: run clipjob.py idcheck {j['job']} {k} --raw {raw}, "
                          "vision-read it against the reference (aukey-pby92 2026-11-18: the powerbank morphed inside "
                          "the shot and the review went to Fix as a pass), then ready … --identity match|drift:<what>")
        identity = parse_identity(identity_arg)
    gates, file = auto_gates(j, k, raw)
    gates["frame"] = frame
    if identity:
        gates["identity"] = identity
    mark_ready(j, k, file, gates)
    res = {"shot": k, "pass": gates_passed(gates), "file": os.path.abspath(file), "gates": gates}
    if not no_send:
        save(j)                              # the checks are done: keep them even when the send fails
        try:
            send_review(j, k)
        except Refused as e:
            raise Refused(f"{e} — the shot IS in review; send it with: clipjob.py ready {j['job']} {k} --resend") from None
    return res


def fix_reviewed(j, k):
    """📝: the file came from Fix's own Flow as a reply to the prompt — he watched it before sending it."""
    at = (shot(j, k).get("attempts") or [{}])[-1]
    return at.get("via") == "prompt"          # stays his review when he hands Flow to Hermes after sending it


def ready_reviewed(j, k, raw, frame, identity_arg, no_send):
    """Fix 2026-11-22: a 📝 reply is his review — the shot is approved now, no ✅/🔁 message. Only the gates that
    change the file (probe, the repeated-line cut) run; a note goes to Fix only when one of them found something."""
    gates, file = auto_gates(j, k, raw)
    gates["frame"] = frame
    if identity_arg:
        gates["identity"] = parse_identity(identity_arg)
    mark_ready(j, k, file, gates)
    decide(j, k, "approve")
    log(j, f"shot {k} approved: {FIX_REVIEWED}")
    notes = [f"{n}: {g['note']}" for n, g in gates.items() if g.get("note") and g["note"] != FIX_REVIEWED]
    if notes and not no_send:
        notify(f"ℹ️ ช็อต {k} · {j['product']} รับแล้ว (ผ่านอัตโนมัติ)\n" + "\n".join(notes)[:900],
               takeover_keyboard(j))
    left = [s["k"] for s in j["shots"] if s["state"] != "approved"]
    return {"shot": k, "pass": True, "auto_approved": True, "file": os.path.abspath(file), "gates": gates,
            "next": ("all shots approved -> post-production" if not left
                     else f"wait for Fix's file(s) for shot {', '.join(map(str, left))}")}


def auto_gates(j, k, raw):
    """The file checks that need no vision: probe, and for a presenter the repeated-line cut + early CTA."""
    info = ffprobe(raw)
    gates = {"probe": probe_verdict(info)}
    file = raw
    if j["mode"] == "presenter":
        script = os.path.join(j["workdir"], f"shot{k}.txt")
        if not os.path.exists(script):
            raise Refused(f"missing {script} (the shot prompt; detect_repeats needs its voiceover line)")
        gates["repeats"], file, asr = repeats_gate(raw, script)
        if k < len(j["shots"]):
            hits = cta_hits(asr)
            gates["cta"] = {"ok": not hits, "note": ("คำ CTA ในช็อตที่ไม่ใช่ช็อตสุดท้าย: " + ", ".join(hits)) if hits else ""}
        if info and not info["has_audio"]:
            gates["probe"] = {"ok": False, "note": "ไม่มีเสียง — presenter ต้องมีเสียงพากย์จาก Flow"}
    return gates, file


def adopt_gateway_env():
    """Fill ADOPT_ENV names missing from this process from the gateway's own environ. -> names adopted.
    Children (the detached mirror, the send scripts) inherit them; the token never goes on argv."""
    missing = [n for n in ADOPT_ENV if not os.environ.get(n, "").strip()]
    if not missing:
        return []
    try:
        with open(GATEWAY_PID, encoding="utf-8") as f:
            pid = int(json.load(f)["pid"])
        with open(os.path.join(PROC, str(pid), "environ"), "rb") as f:
            env = dict(kv.split(b"=", 1) for kv in f.read().split(b"\0") if b"=" in kv)
    except (OSError, ValueError, KeyError, TypeError):
        return []
    got = []
    for n in missing:
        v = env.get(n.encode(), b"").decode("utf-8", "replace").strip()
        if v:
            os.environ[n] = v
            got.append(n)
    if "TZ" in got:
        time.tzset()
    return got


def mirror_chat():
    """The Secretary chat id when both its env vars are set, else None (no copy, silently)."""
    if os.environ.get(MIRROR_TOKEN_ENV, "").strip():
        return os.environ.get(MIRROR_CHAT_ENV, "").strip() or None
    return None


def _store_mirror(job, m):
    """Write only delivery.mirror back: the close sleeper / a 🏁 tap may have saved the job meanwhile."""
    j = load(job)
    if (j.get("delivery") or {}).get("sha256") == m.get("sha256"):
        j["delivery"]["mirror"] = m
        save(j)
    return j


def send_mirror(job):
    """Send the delivered clip + copy-button message + cover to the Secretary chat. Never raises.
    Steps already ok are skipped, so a rerun (`clipjob.py mirror JOB`) never double-posts."""
    j = load(job)
    m = (j.get("delivery") or {}).get("mirror")
    if not m:
        return None
    chat = mirror_chat()
    if not chat:
        m["state"] = "off"
        _store_mirror(job, m)
        return m
    via = ["env", f"TG_TOKEN_ENV={MIRROR_TOKEN_ENV}", "python3"]
    steps = [("clip", via + [os.path.join(HERE, "send_clip.py"), m["file"], m["caption"], chat, m["label"] + "_secretary"]),
             ("copy_buttons", via + [os.path.join(HERE, "send_copy_buttons.py"), m["hashtags"], m["link"], chat, m["product"]])]
    if m.get("cover"):                              # Fix 2026-11-17: the cover goes to the Secretary chat too
        steps.append(("cover", via + [os.path.join(HERE, "send_photo.py"), m["cover"], "ปกคลิป", chat,
                                      m["label"] + "_cover_secretary"]))
    sent = m.setdefault("sent", {})
    for name, cmd in steps:
        if sent.get(name) == "ok":
            continue
        if os.environ.get("CLIPJOB_NO_TG"):
            sent[name] = "skipped (CLIPJOB_NO_TG)"
            continue
        need = m["cover"] if name == "cover" else m["file"]
        if not os.path.exists(need):
            sent[name] = f"failed: {need} is gone"
            break
        try:
            rc, out, err = run(cmd)
        except OSError as e:
            rc, out, err = 1, "", str(e)
        if rc:
            sent[name] = "failed: " + (out[-200:] + " " + err[-200:]).strip()
            break                                   # no copy buttons under a clip that never arrived
        sent[name] = "ok"
        _store_mirror(job, m)
    if all(sent.get(n) == "ok" for n, _ in steps):
        m["state"] = "ok"
    elif sent and all(str(v).startswith("skipped") for v in sent.values()):
        m["state"] = "skipped"
    else:
        m["state"] = "failed"
    j = _store_mirror(job, m)
    log(j, f"secretary copy: {m['state']}"); save(j)
    return m


def mirror_fail_text(m):
    return (f"⚠️ ส่งสำเนาคลิป {m['label']} ไปแชท Secretary ไม่สำเร็จค่ะ (คลิปของฟิกส่งครบแล้ว)\n"
            f"ส่งซ้ำ: clipjob.py mirror {m['job']}")


def spawn_mirror(j):
    """Detached like spawn_closer: the delivery returns at once, the second upload runs on its own."""
    if os.environ.get("CLIPJOB_MIRROR_INLINE") or os.environ.get("CLIPJOB_NO_TG"):
        return send_mirror(j["job"])
    os.makedirs(os.path.dirname(CLIP_LOG), exist_ok=True)
    out = open(os.path.join(os.path.dirname(CLIP_LOG), "mirror.log"), "a")
    p = subprocess.Popen([sys.executable, os.path.abspath(__file__), "mirror", j["job"], "--auto"],
                         stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                         start_new_session=True, close_fds=True, cwd="/")
    out.close()
    return p.pid


ENDCARD = os.path.join(os.path.dirname(SKILL), "gameplay-clips", "scripts", "endcard_check.py")


def endcard_rect(j, final):
    """The end-card picture rect build_v5 wrote (work/timeline_v5.json in the job's workdir; the last build is the
    one shipped) -> "x0,y0,x1,y1" or None (no timeline / an older build_v5 without the key)."""
    tl = os.path.join(j.get("workdir") or "", "work", "timeline_v5.json")
    try:
        r = json.load(open(tl, encoding="utf-8")).get("endcard_rect")
    except (OSError, ValueError):
        return None
    if not (isinstance(r, list) and len(r) == 4):
        return None
    return ",".join(str(int(v)) for v in r)


def endcard_problems(final, rect=None):
    """🎬 end card: a title cut by the 1:1 window (ffr-swt-dec04 'L FANTASY RESONANCE', sniper-elite3-sw
    'NIPER ELITE', 2026-11-20/21) or by the card picture's own top/bottom (switch2-oblivion-rd 2026-11-22, a crop
    that left "OUT NOW" 1 px from the edge). OCR of the last seconds; text touching the left/right frame edge
    or, with `rect`, the picture's top/bottom = cut."""
    cmd = ["uv", "run", "-q", "--with", "rapidocr-onnxruntime", "--with", "numpy", "--with", "pillow",
           "python", ENDCARD, final]
    if rect:
        cmd += ["--rect", rect]
    rc, out, err = run(cmd)
    try:
        v = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return [f"endcard_check printed no verdict (rc {rc}): {(out + err)[-300:]} — fix it or rerun with ENDCARD_OK=1 "
                "after looking at the last 2 s yourself"]
    if v.get("ok"):
        return []
    cut = "; ".join(f"'{h['text']}' at {h['t']} s ({h['side']} edge)" for h in v.get("hits", [])[:4])
    return [f"end card text touches the frame / picture edge = cut: {cut}. End-card seg = the ORIGINAL trailer with "
            "\"wide\": true, or \"crop\" from `endcard_crop.py` (margins around the title), never a pre-cropped "
            "endcard file; rebuild. ENDCARD_OK=1 only when that text is HUD / gameplay, not the title"]


def cmd_deliver(j, a):
    if a.report:
        report = json.load(open(a.report, encoding="utf-8"))
    elif j["mode"] == "gameplay" and os.path.exists(a.final):
        v, au = av_durations(a.final)        # build_v5 writes no report; its --check and the gates ran before
        if v is None or au is None:
            raise Refused(f"deliver refused: {a.final} has no {'video' if v is None else 'audio'} stream")
        report = {"v_dur": round(v, 2), "a_dur": round(au, 2), "flags": []}
    else:
        raise Refused("deliver needs --report report.json (only 🎬 gameplay may omit it)")
    gfx = json.load(open(a.gfx, encoding="utf-8")) if a.gfx else {}
    acks = parse_acks(a.ack)
    probs = deliver_problems(j, report, gfx, a.hashtags, acks)
    if a.style and not (j["mode"] == "gameplay" and a.style in ("gameplay", "footage")):
        probs.append("--style is only for 🎬 jobs: gameplay (a game) or footage (a brand product film)")
    if not os.path.exists(a.final):
        probs.append(f"no final file {a.final}")
    if not os.path.exists(a.cover):
        probs.append(f"no cover {a.cover}")
    if j["mode"] == "gameplay" and os.path.exists(a.final) and not os.environ.get("ENDCARD_OK"):
        probs += endcard_problems(a.final, endcard_rect(j, a.final))
    if probs:
        raise Refused("deliver refused:\n- " + "\n- ".join(probs))
    rc, out, err = run(["python3", os.path.join(HERE, "verify-clip.py"), a.final])
    if rc:
        raise Refused(f"verify-clip failed: {out[-400:]} {err[-400:]}")
    try:
        verdict = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise Refused(f"verify-clip printed no verdict: {out[-300:]}") from None
    final = verdict.get("sent_from") or a.final
    digest = sha256(final)
    if verdict.get("sha256") and verdict["sha256"] != digest:
        raise Refused("verify-clip checked a different file than the one about to be sent")
    prev = j.get("delivery") or {}
    if prev.get("sha256") != digest:          # a different final = a fresh delivery
        prev = {}
    done = dict(prev.get("partial") or {})
    if not prev.get("logged"):
        edit_ids = [at["edit_id"] for s in j["shots"] for at in s["attempts"] if real_edit_id(at.get("edit_id"))]
        credits = billed_credits(j)
        notes = (f"REVISED: {j['revision']} | " if j.get("revision") else "") + (a.notes or "")
        notes += f" | job {j['job']} production={j['production']}"
        if j.get("fallback"):
            notes += f" fallback: {j['fallback']['reason']}"
        if acks:
            notes += " | flags accepted by Fix: " + "; ".join(f"{k} -> {v}" for k, v in acks)
        notes += "".join(f" | {n}" for n in report.get("notes") or [])
        row = {"date": dt.date.today().isoformat(), "product": j["product"], "category": a.category,
               "style": a.style or j["mode"], "character": j.get("character"), "edit_id": edit_ids[-1] if edit_ids else None,
               "sha256": digest, "hook_id": a.hook_id, "hashtags": a.hashtags,
               "duration_s": round(float(report.get("v_dur") or 0), 2),
               "credits": (0 if j["mode"] == "gameplay" else
                           sum(c for c in credits if c) if credits and all(c is not None for c in credits) else None),
               **({"credits_est": True} if any(at.get("credits_est") for s in j["shots"] for at in s["attempts"]) else {}),
               "notes": notes.strip(" |"), "timing": timeline(j, now(), job_asks(j, now())),
               "vision": job_vision(j)}
        os.makedirs(os.path.dirname(CLIP_LOG), exist_ok=True)
        with open(CLIP_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    j["delivery"] = {"sha256": digest, "logged": True, "partial": done}
    label = j["job"] + ("-rev" if j.get("revision") else "")
    steps = [("clip", ["python3", os.path.join(HERE, "send_clip.py"), final, a.caption[:1000], CHAT, label]),
             ("copy_buttons", ["python3", os.path.join(HERE, "send_copy_buttons.py"), a.hashtags, j["link"], CHAT, j["product"]]),
             ("cover", ["python3", os.path.join(HERE, "send_photo.py"), a.cover, "ปกคลิป", CHAT, f"{label}_cover"])]
    for name, cmd in steps:
        if done.get(name) == "ok":
            continue
        if os.environ.get("CLIPJOB_NO_TG"):
            done[name] = "skipped (CLIPJOB_NO_TG)"
            continue
        rc, out, err = run(cmd)
        if rc:
            j["delivery"].update({"partial": done, "failed_at": name})
            log(j, f"deliver failed at {name}")
            save(j)
            raise Refused(f"{name} send FAILED — rerun the same deliver command (finished steps are skipped): "
                          f"{out[-300:]} {err[-300:]}")
        done[name] = "ok"
        j["delivery"]["partial"] = done
        save(j)
    j["status"] = "delivered"
    j.pop("revision", None)
    j["delivery"] = {"at": iso(), "sha256": digest, "file": final, "sent": done, "logged": True}
    try:
        j["delivery"]["kept"] = keep_final(label, final, a.cover)
    except OSError as e:                                # a full disk never blocks a delivery that already went out
        j["delivery"]["kept"] = f"not kept: {e}"
    log(j, "delivered")
    t_end = now()
    j["timing"] = timeline(j, t_end, job_asks(j, t_end))
    j["timing"]["vision"] = job_vision(j, t_end)
    kept = j["delivery"]["kept"]
    j["delivery"]["mirror"] = {"job": j["job"], "sha256": digest,
                               # pending = spawn_mirror sends it once this job is saved; off = recorded anyway,
                               # so `clipjob.py mirror JOB` can send it later from a process that has the env
                               **({"state": "pending"} if mirror_chat() else
                                  {"state": "off", "why": f"{MIRROR_TOKEN_ENV} / {MIRROR_CHAT_ENV} not set "
                                                          "in the deliver process"}),
                               "file": kept[0] if isinstance(kept, list) and kept else final,
                               "cover": kept[1] if isinstance(kept, list) and len(kept) > 1 else a.cover,
                               "caption": a.caption[:1000], "hashtags": a.hashtags,
                               "link": j["link"], "product": j["product"], "label": label}
    arm_close(j)
    notify(f"ส่งงาน {j['job']} ครบแล้วค่ะ\n{timeline_text(j['timing'])}\n"
           f"กด {CLOSE_BTN} เพื่อปิดงาน · ไม่กดภายใน {CLOSE_S // 60} นาที ปิดให้เอง",
           close_keyboard(j["job"]))                  # replaces the review reply keyboard
    return j["delivery"]


def summary(j):
    out = {"job": j["job"], "mode": j["mode"], "production": j["production"], "status": j["status"],
           "product": j["product"], "updated": j["updated"],
           "shots": {s["k"]: s["state"] for s in j["shots"]}}
    if j.get("stage"):
        out["stage"] = j["stage"]
    if j.get("fallback"):
        out["fallback"] = j["fallback"]
    if j.get("close"):
        out["close"] = {k: v for k, v in j["close"].items() if k in ("state", "due", "at", "by", "freed_mb")}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new"); s.add_argument("job"); s.add_argument("--mode", required=True, choices=MODES)
    s.add_argument("--product", required=True); s.add_argument("--link", default="")
    s.add_argument("--shots", type=int, default=0); s.add_argument("--ref", action="append", default=[])
    s.add_argument("--workdir"); s.add_argument("--character")
    s.add_argument("--seconds", help="per-shot length: 8 or 8,6,8 (3-10, default 10)")
    s = sub.add_parser("board"); s.add_argument("job")
    s = sub.add_parser("intake"); s.add_argument("job"); s.add_argument("--product", required=True)
    s.add_argument("--link", default=""); s.add_argument("--mode", choices=MODES); s.add_argument("--workdir")
    s = sub.add_parser("idcheck"); s.add_argument("job"); s.add_argument("shot", type=int); s.add_argument("--raw")
    s = sub.add_parser("startframe"); s.add_argument("job"); s.add_argument("shot", type=int)
    s = sub.add_parser("cost"); s.add_argument("job", nargs="?"); s.add_argument("--seconds")
    s.add_argument("--res", default="720p")
    s = sub.add_parser("production"); s.add_argument("job"); s.add_argument("value", choices=["auto", "prompt"])
    s = sub.add_parser("reshape"); s.add_argument("job"); s.add_argument("--shots", type=int, required=True)
    s.add_argument("--seconds")
    s = sub.add_parser("status"); s.add_argument("job", nargs="?")
    s = sub.add_parser("reserve"); s.add_argument("job"); s.add_argument("shot", type=int)
    s.add_argument("--wait", action="store_true")
    s = sub.add_parser("submitted"); s.add_argument("job"); s.add_argument("shot", type=int)
    s.add_argument("--edit-id"); s.add_argument("--credits", type=int)
    s = sub.add_parser("edit-id"); s.add_argument("job"); s.add_argument("shot", type=int); s.add_argument("edit_id")
    s = sub.add_parser("submit-failed"); s.add_argument("job"); s.add_argument("shot", type=int)
    s.add_argument("--reason", required=True); s.add_argument("--credits-spent", action="store_true")
    s = sub.add_parser("trouble"); s.add_argument("job"); s.add_argument("--step", required=True)
    s.add_argument("--reason", required=True)
    s = sub.add_parser("fallback"); s.add_argument("job"); s.add_argument("--reason", required=True)
    s = sub.add_parser("pack"); s.add_argument("job"); s.add_argument("--shot", type=int)
    s.add_argument("--no-send", action="store_true")
    s.add_argument("--no-start-frame", action="store_true",
                   help="attach no start frame this round (the chain line says so; the prompt must not ask for one)")
    s = sub.add_parser("ingest"); s.add_argument("job"); s.add_argument("file")
    s.add_argument("--reply-text"); s.add_argument("--shot", type=int)
    s.add_argument("--credits", type=int, help="the real spend when Fix names it (Omni 1.1 = 1.5/s)")
    s = sub.add_parser("scan"); s.add_argument("job"); s.add_argument("shot", type=int); s.add_argument("--raw")
    s = sub.add_parser("ready"); s.add_argument("job"); s.add_argument("shot", type=int)
    s.add_argument("--raw"); s.add_argument("--frame"); s.add_argument("--identity")
    s.add_argument("--no-send", action="store_true"); s.add_argument("--resend", action="store_true")
    s = sub.add_parser("decide"); s.add_argument("job", nargs="?"); s.add_argument("shot", nargs="?", type=int)
    s.add_argument("decision", nargs="?", choices=["approve", "regen"]); s.add_argument("--text")
    s = sub.add_parser("assemble-check"); s.add_argument("job")
    s = sub.add_parser("deliver"); s.add_argument("job")
    for k in ("--final", "--hashtags", "--cover", "--caption"):
        s.add_argument(k, required=True)
    s.add_argument("--report"); s.add_argument("--style"); s.add_argument("--gfx"); s.add_argument("--hook-id"); s.add_argument("--category")
    s.add_argument("--notes"); s.add_argument("--ack", action="append", default=[])
    s = sub.add_parser("cancel"); s.add_argument("job"); s.add_argument("--reason", required=True)
    s = sub.add_parser("note"); s.add_argument("job"); s.add_argument("text")
    s = sub.add_parser("wait"); s.add_argument("job"); s.add_argument("text")
    s = sub.add_parser("stage"); s.add_argument("job"); s.add_argument("text", metavar="name")
    s = sub.add_parser("reopen"); s.add_argument("job"); s.add_argument("--reason", required=True)
    s = sub.add_parser("mirror"); s.add_argument("job"); s.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)
    s = sub.add_parser("close"); s.add_argument("job", nargs="?")
    s.add_argument("--auto", action="store_true", help=argparse.SUPPRESS)       # the deliver timer
    s.add_argument("--token", help=argparse.SUPPRESS); s.add_argument("--after", type=float, help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    adopt_gateway_env()
    if a.cmd != "close":
        sweep_closes()

    def out(obj):
        print(json.dumps(obj, ensure_ascii=False, indent=1)[:6000])
        return 0

    try:
        if a.cmd == "intake":
            if os.path.exists(path_of(a.job)):
                raise Refused(f"job {a.job} exists (pick another slug, or `status {a.job}` to resume it)")
            j = intake_job(a.job, a.product, a.link, a.mode, a.workdir)
            os.makedirs(j["workdir"], exist_ok=True)
            j["started"] = iso(workdir_started(j["workdir"], now()))
            log(j, "intake"); save(j)
            return out({**summary(j), "next": "clipjob.py note <job> \"<done; next>\" after each stage (Q1, photo gate, "
                                               "board sent/approved); clipjob.py new <job> … after the board"})
        if a.cmd == "board":
            j = load(a.job); need_open(j)
            j["board"] = {"sent": iso()}
            log(j, "board sent"); save(j)
            return out({"job": a.job, "board": j["board"], "next": "NOW ask approval + Q3 (one clarify), then wait. "
                        "`new` refuses until Fix replies after this moment (stamped after his answer = refused)"})
        if a.cmd == "new":
            missing = [r for r in a.ref if not os.path.exists(r)]
            if missing:
                raise Refused(f"ref not found: {missing}")
            if (a.mode == "presenter" and a.character and not character_image(a.character)
                    and not os.environ.get("CLIPJOB_NO_PORTRAIT_OK")):
                raise Refused(f"no portrait {CHAR_DIR}/{a.character}.jpg — without it the identity check cannot compare "
                              "her face and the prompt pack cannot give Fix's other account the character "
                              "(champion-trashbag-roll 2026-11-22: น้องเอิร์ธ, the one MALE roster entry, came back a "
                              "woman). Save the character's Flow image there (flow-driver templates/character-prompt.md) "
                              "or pick a roster name that has one")
            j = new_job(a.job, a.mode, a.product, a.link, a.shots, a.ref, a.workdir, a.character, a.seconds)
            old = load(a.job) if os.path.exists(path_of(a.job)) else None
            board = board_gate(old, a.mode)
            if old:
                j = promote_intake(old, j)
                log(j, "created (from intake)")
            else:
                log(j, "created")
            if board:
                j["board"] = board
                log(j, "board approved: " + (f"{board['answer']!r} at {board['answer_at'][11:16]}" if board.get("answer")
                                             else f"unverified ({board.get('unverified')})"))
            os.makedirs(j["workdir"], exist_ok=True)
            j.setdefault("started", iso(workdir_started(j["workdir"], now())))
            save(j)
            rates = {k: vo_rate(j, k) for k in range(1, len(j["shots"]) + 1)}
            return out({**summary(j), **({"board": j["board"]} if j.get("board") else {}),
                        "vo_rate": {k: f"{r[0]} chars / {r[1]} s = {r[2]}/s" for k, r in rates.items() if r}})
        if a.cmd == "cost":
            if a.job:
                return out(cost([shot_seconds(s) for s in load(a.job)["shots"]], a.res))
            if not a.seconds:
                raise Refused("cost needs a job or --seconds 8,6")
            return out(cost(parse_seconds(a.seconds, 0), a.res))
        if a.cmd == "status":
            if a.job:
                j = load(a.job)
                return out({**j, "vision": job_vision(j)} if j["status"] == "open" else j)
            rows = []
            for f in sorted(os.listdir(DIR)) if os.path.isdir(DIR) else []:
                if f.endswith(".json") and f != "pacing.json":
                    jj = json.load(open(os.path.join(DIR, f), encoding="utf-8"))
                    if jj["status"] == "open":
                        rows.append({**summary(jj), "last": [e["msg"] for e in jj["events"][-3:]]})
            return out({"open_jobs": rows})
        if a.cmd == "close" and a.after is not None:         # the sleeper spawned by deliver
            time.sleep(max(0.0, a.after))
            j = load(a.job); c = j.get("close") or {}
            if j["status"] != "delivered" or c.get("state") != "pending" or c.get("token") != a.token:
                return out({"job": a.job, "skipped": "closed, reopened or re-delivered since this timer started"})
            res = close_job(j, "auto"); save(j); notify(close_text(j))
            return out(res)
        if a.cmd == "close" or (a.cmd == "decide" and parse_close_text(a.text)):
            jobs = [a.job or parse_close_text(a.text)] if (a.job or a.cmd == "decide") else due_closes(now() + CLOSE_S + CLOSE_GRACE_S)
            done = []
            for job in jobs:
                j = load(job); res = close_job(j, "tap" if a.cmd == "decide" else "manual"); save(j)
                notify(close_text(j) if "closed" in res else f"งาน {job} ปิดไปแล้วค่ะ")
                done.append(res)
            return out({"closed": done, "next": "end the turn: one short line, no cleanup of your own"})
        if a.cmd == "decide" and parse_takeover_text(a.text):
            j = load(parse_takeover_text(a.text)); res = takeover(j)
            if "why" in res:
                notify(res["why"])
                return out({**summary(j), "takeover": False, "why": res["why"], "next": "one short line at most, end the turn"})
            save(j)
            notify(f"รับทราบค่ะ ไอยูกด Flow ต่อเอง · ช็อต {', '.join(map(str, res['todo']))} ≈{res['credits']} เครดิต "
                   f"· เริ่มช็อต {res['todo'][0]}")
            unread = [s["k"] for s in j["shots"] if s["state"] == "submitted"]
            return out({**summary(j), "takeover": True, **res,
                        "next": (f"first clipjob.py ready {j['job']} K --raw <file> for shot {', '.join(map(str, unread))} "
                                 "(Fix's file = his review), then " if unread else "")
                                + f"load skill flow-driver and render shot {res['todo'][0]} (clipjob.py reserve; shot ≥2: "
                                  "clipjob.py startframe). A file Fix still sends for a shot: ingest it before its reserve"})
        if a.cmd == "decide":
            if a.text:
                parsed = parse_decision_text(a.text)
                if not parsed:
                    raise Refused("text is not a review button (✅ ผ่าน / 🔁 gen ใหม่ ช็อต K · job, "
                                  f"{TAKEOVER_BTN} · job, {CLOSE_BTN} · job)")
                job, k, dec = parsed
            else:
                if not (a.job and a.shot and a.decision):
                    print("decide JOB K approve|regen  (or --text)", file=sys.stderr)
                    return 2
                job, k, dec = a.job, a.shot, a.decision
            j = load(job); stale = decide(j, k, dec); save(j)
            notify(f"รับทราบ ช็อต {k} · {'ผ่าน' if dec == 'approve' else 'gen ใหม่'}")
            if stale and stale["ask"]:
                notify(stale_text(j, stale["shot"]), review_keyboard(job, stale["shot"]))
            nxt = ("next: all shots approved -> post-production" if all(s["state"] == "approved" for s in j["shots"])
                   else ("next: " + ("reserve + regenerate in Flow" if j["production"] == "auto" else f"clipjob.py pack {job} --shot {k}"))
                   if dec == "regen" else "next: wait for the remaining shots")
            return out({**summary(j), "next": nxt, **({"next_shot_chain": stale} if stale else {})})

        j = load(a.job)
        if j.get("stage") == "intake" and a.cmd not in INTAKE_CMDS:
            raise Refused(f"job {a.job} is still at intake: run clipjob.py new {a.job} --mode … after Fix approves the board")
        if a.cmd == "production":
            set_production(j, a.value); save(j)
            return out(summary(j))
        if a.cmd == "reshape":
            secs = reshape(j, a.shots, a.seconds); save(j)
            return out({**summary(j), "seconds": secs, "cost": cost(secs),
                        "next": "rewrite shot<K>.txt for the new plan (delete the extra ones), then pack / reserve; a "
                                "prompt message sent before the reshape now maps to the new shot of the same number"})
        if a.cmd == "reserve":
            try:
                t = reserve(j, a.shot, pacing_get())
            except Pacing as p:
                if not a.wait:
                    print(json.dumps({"pacing": True, "wait_s": p.wait_s}))
                    return 4
                w = min(p.wait_s + 2, WAIT_CAP_S)
                print(f"pacing: sleeping {w}s", file=sys.stderr)
                time.sleep(w)
                j = load(a.job)
                try:
                    t = reserve(j, a.shot, pacing_get())
                except Pacing as p2:             # the cap is shorter than the pacing window: call again
                    print(json.dumps({"pacing": True, "wait_s": p2.wait_s, "next": "run the same reserve --wait again"}))
                    return 4
            pacing_set(t); save(j)
            return out({"ok": True, "shot": a.shot, "next": "click Start generation, then clipjob.py submitted"})
        if a.cmd == "submitted":
            submitted(j, a.shot, a.edit_id, a.credits); save(j)
            return out({**summary(j), **({} if real_edit_id(a.edit_id) else
                                         {"next": f"once the tile is open: clipjob.py edit-id {a.job} {a.shot} <id>"})})
        if a.cmd == "edit-id":
            set_edit_id(j, a.shot, a.edit_id); save(j)
            return out(summary(j))
        if a.cmd in ("note", "wait", "stage"):
            need_open(j)
            if a.cmd == "stage":
                j["stage"] = a.text
            log(j, f"{a.cmd}: {a.text}"); save(j)
            v = job_vision(j)
            warn = vision_warning(v)
            return out({**summary(j), "events": j["events"][-5:], "vision": v, **({"warning": warn} if warn else {})})
        if a.cmd == "mirror":
            m = (j.get("delivery") or {}).get("mirror")
            if j["status"] != "delivered" or not m:
                raise Refused(f"job {a.job} has no Secretary copy to send (not delivered, or delivered before the copy "
                              "was recorded)")
            if not mirror_chat():
                raise Refused(f"{MIRROR_TOKEN_ENV} / {MIRROR_CHAT_ENV} not set in this container")
            if m.get("state") == "ok":
                return out({"job": a.job, "mirror": "already sent"})
            m = send_mirror(a.job)
            if m["state"] not in ("ok", "skipped"):
                if a.auto:                                  # the detached run after deliver: tell Fix, keep 🏁
                    c = load(a.job).get("close") or {}
                    notify(mirror_fail_text(m), close_keyboard(a.job) if c.get("state") == "pending" else None)
                raise Refused(f"Secretary copy failed: {m['sent']}")
            return out({"job": a.job, "mirror": m["sent"]})
        if a.cmd == "reopen":
            if j["status"] != "delivered":
                raise Refused(f"job {a.job} is {j['status']}; only a delivered job is reopened for a revision")
            j["status"] = "open"; j["revision"] = a.reason; j.pop("close", None)        # a waiting timer is now void
            log(j, f"reopened for a revision: {a.reason}"); save(j)
            return out({**summary(j), "next": "rebuild, rerun the gates, then the same deliver command with the new final"})
        if a.cmd in ("submit-failed", "trouble"):
            fb = (submit_failed(j, a.shot, a.reason, a.credits_spent) if a.cmd == "submit-failed"
                  else trouble(j, a.step, a.reason))
            asked = None
            if a.cmd == "submit-failed" and shot(j, a.shot)["state"] == "failed":
                save(j)
                asked = notify(f"❌ ช็อต {a.shot} · {j['product']}\nFlow ล้มหลังเสียเครดิตไปแล้ว: {a.reason[:300]}\n"
                               "gen ใหม่ = เสียเครดิตอีกรอบ · ไม่ทำต่อพิมพ์ \"เลิกทำ\"",
                               review_keyboard(a.job, a.shot, approve=False))
            if fb:
                todo = fallback(j, a.reason); save(j)
                return out({**summary(j), "FALLBACK": True, "pack_shots": todo,
                            **({"asked_fix_regen": asked} if asked is not None else {}),
                            "next": f"stop driving Flow; tell Fix in one line (reason, credits spent, shots left); "
                                    f"close Chrome; clipjob.py pack {a.job}"})
            save(j)
            return out({**summary(j), "FALLBACK": False, **({"asked_fix_regen": asked} if asked is not None else {})})
        if a.cmd == "fallback":
            todo = fallback(j, a.reason); save(j)
            return out({**summary(j), "pack_shots": todo, "next": f"clipjob.py pack {a.job}"})
        if a.cmd == "pack":
            sent = cmd_pack(j, a.shot, a.no_send, a.no_start_frame); save(j)
            return out({"packed": sent, "next": "wait for Fix's replies; each reply -> clipjob.py ingest"})
        if a.cmd == "ingest":
            if a.shot:
                k = a.shot
            else:
                tag = parse_tag(a.reply_text)
                if not tag:
                    raise Refused("the file is not a reply to a shot prompt — ask Fix which shot it is "
                                  "(never guess), then rerun with --shot K")
                if tag[0] != a.job:
                    raise Refused(f"reply belongs to job {tag[0]}, not {a.job}")
                k = tag[1]
            dst = ingest(j, k, a.file, a.credits)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(a.file, dst)
            save(j)
            sf = next_start_frame(j, k, dst)
            sent_sf = None
            if sf and (sf["file"] or sf["faceless"]):
                try:
                    kb = takeover_keyboard(j)
                    extra = {"reply_markup": kb} if kb else {}
                    if sf["file"]:
                        tg("sendPhoto", {"chat_id": CHAT, "caption": start_frame_text(j, k + 1, sf), **extra},
                           files={"photo": sf["file"]})
                    else:
                        tg("sendMessage", {"chat_id": CHAT, "text": start_frame_text(j, k + 1, sf), **extra})
                    sent_sf = k + 1
                except (Refused, OSError, ValueError) as e:
                    print(f"start frame for shot {k + 1} not sent: {e}", file=sys.stderr)
            return out({**summary(j), "file": dst, "start_frame_sent": sent_sf if sf and sf["file"] else None,
                        **({"start_frame": {kk: sf[kk] for kk in ("from", "faceless", "unchecked")}} if sf else {}),
                        "next": (f"clipjob.py ready {a.job} {k} --raw {dst} — Fix's reply is his review: no vision, no "
                                 "idcheck, the shot is approved at once" if fix_reviewed(j, k) else
                                 f"vision-check frames, then clipjob.py ready {a.job} {k} --raw {dst} --frame …")})
        if a.cmd == "scan":
            res = cmd_scan(j, a.shot, a.raw); save(j)
            return out(res)
        if a.cmd == "idcheck":
            res = cmd_idcheck(j, a.shot, a.raw); save(j)
            return out(res)
        if a.cmd == "startframe":
            need_flow(j)
            if a.shot < 2:
                raise Refused("shot 1 has no start frame")
            return out({"shot": a.shot, **start_frame_for(j, a.shot),
                        "next": "attach `file` as the start frame; file null = character chip + refs only"})
        if a.cmd == "ready":
            res = cmd_ready(j, a.shot, a.raw, a.frame, a.no_send, a.resend, a.identity); save(j)
            return out(res)
        if a.cmd == "assemble-check":
            files = assemble_files(j)
            print("\n".join(files))
            return 0
        if a.cmd == "deliver":
            d = cmd_deliver(j, a); save(j)
            try:
                pid = spawn_closer(j)
            except OSError as e:                                # the sweep closes it on a later call
                pid = f"timer not started: {e}"
            mirror = None
            if (j["delivery"].get("mirror") or {}).get("state") == "pending":
                try:
                    mirror = spawn_mirror(j)                    # Secretary copy: detached, reports its own failure
                except OSError as e:
                    mirror = f"copy not started: {e} (clipjob.py mirror {j['job']})"
                mirror = mirror if isinstance(mirror, (str, int)) else (mirror or {}).get("state")
            elif j["delivery"].get("mirror"):
                mirror = "off: " + j["delivery"]["mirror"].get("why", "")
            rc, o, e = run(["python3", os.path.join(HERE, "check_delivery.py")])
            return out({"delivered": d, "check_delivery_exit": rc, "check_delivery": (o + e)[-600:],
                        "close": {**j["close"], "timer_pid": pid}, "secretary_copy": mirror,
                        "next": f"one short line to Fix, then end the turn. No cleanup: Fix's {CLOSE_BTN} tap or the "
                                f"timer runs clipjob.py close in {CLOSE_S // 60} min"})
        if a.cmd == "cancel":
            need_open(j)
            j["status"] = "cancelled"; log(j, f"cancelled: {a.reason}"); save(j)
            notify(f"ยกเลิกงาน {a.job} แล้วค่ะ")
            return out({**summary(j), "spent_shots": spent_shots(j)})
    except Refused as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
