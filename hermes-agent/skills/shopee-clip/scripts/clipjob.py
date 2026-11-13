#!/usr/bin/env python3
"""clipjob — one Shopee clip order, from mode pick to delivery. Local state, no n8n.

State: $CLIPJOB_DIR/<job>.json (default /opt/data/clips/jobs). Pacing clock: $CLIPJOB_DIR/pacing.json.
This CLI is the only sanctioned way to move a Flow-mode clip forward. It refuses out-of-order steps.

  clipjob.py new JOB --mode presenter|product|hands|gameplay --product "..." [--link URL] [--shots N] [--ref IMG ...] [--character NAME]
  clipjob.py production JOB auto|prompt            # Fix's answer to Q2 (Flow modes only)
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
  clipjob.py ready JOB K --raw FILE --frame pass|flag:<what you saw> [--no-send]
  clipjob.py ready JOB K --resend                   # the review message failed to send: send it again (no re-check)
  clipjob.py decide (--text "<Fix's button text>" | JOB K approve|regen)
  clipjob.py assemble-check JOB                     # approved files in shot order, exit 0 only when all approved
  clipjob.py deliver JOB --final F.mp4 --report report.json --gfx gfx.json --hashtags "..." --cover C.jpg \
                         --caption "..." [--hook-id ID] [--category C] [--notes "..."] [--ack "<flag text>=<Fix's call>" ...]
                         # 🎬 only: --report may be omitted; --style footage for a brand product film
                         # a re-run after a failed send skips the steps already done and logs the clip once
  clipjob.py cancel JOB --reason "..."
  clipjob.py note JOB "..."                         # stage marker in the job's events (🎬: what is done, what is next)
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
import hashlib
import json
import os
import re
import shutil
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
SHOT_SECONDS = 10          # one Omni 1.1 Flash generation (house-rules.md -> Duration)
INFO_FLAGS = [re.compile(r"auto-added")]   # report flags that only inform (post_presenter adds the CTA pill itself)
FLOW_MODES = ("presenter", "product", "hands")   # hands = product pipeline, hands in frame, no face
MODES = FLOW_MODES + ("gameplay",)
JOB_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
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


def new_job(job, mode, product, link="", shots=0, refs=(), workdir=None, character=None):
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
    t = now()
    return {"job": job, "mode": mode, "product": product, "link": link, "status": "open",
            "production": None, "character": character, "refs": [os.path.abspath(r) for r in refs],
            "workdir": workdir or os.path.join(WORK, job),
            "created": iso(t), "updated": iso(t), "fallback": None, "trouble": {},
            "shots": [{"k": k, "state": "pending", "attempts": [], "raw": None, "file": None,
                       "gates": None, "pack_msg": None} for k in range(1, shots + 1)] if mode in FLOW_MODES else [],
            "events": [], "delivery": None}


def workdir_started(wd, before):
    """Earliest file mtime in the workdir when it is older than `before`: intake and the photo gate run
    before `new`, so the job's clock starts at the first file they wrote."""
    ts = [before]
    for root, _, files in os.walk(wd) if os.path.isdir(wd) else ():
        ts += [os.path.getmtime(os.path.join(root, f)) for f in files]
    return min(ts)


def _epoch(ts):
    return dt.datetime.fromisoformat(ts).timestamp()


def timeline(j, end=None):
    """Where the time went, in minutes, from the job's own events. A revision counts from its reopen."""
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
    wait, ready_at = 0.0, {}
    for (t, m), nxt in zip(ev, [t for t, _ in ev[1:]] + [end]):
        if m.startswith("wait:"):                       # the turn ended on Fix; the next event is the resume
            wait += max(0, nxt - t)
    for t, m in ev:
        mm = re.match(r"(ready|decide) shot (\d+)", m)
        if mm and mm.group(1) == "ready":
            ready_at[mm.group(2)] = t
        elif mm and mm.group(2) in ready_at:
            wait += t - ready_at.pop(mm.group(2))
    if decides:
        stages += [["gen+รีวิว", mins(created, decides[-1])], ["post", mins(decides[-1], end)]]
    else:
        stages.append(["ทำคลิป", mins(created, end)])
    return {"total_min": mins(start, end), "stages": stages, "wait_fix_min": round(wait / 60)}


def timeline_text(tl):
    h, m = divmod(tl["total_min"], 60)
    parts = [f"{k} {v} น." + (f" (รอฟิกตอบ {tl['wait_fix_min']} น.)" if k in ("gen+รีวิว", "ทำคลิป") and tl["wait_fix_min"] else "")
             for k, v in tl["stages"]]
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


def set_production(j, prod):
    need_open(j); need_flow(j)
    if prod not in ("auto", "prompt"):
        raise Refused("production must be auto or prompt")
    if j["production"] == "prompt" and prod == "auto" and j["fallback"]:
        raise Refused("this job already fell back to prompt pack; start a new job to retry auto")
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


def submitted(j, k, edit_id=None, credits=None):
    s = shot(j, k)
    if s["state"] != "submitting":
        raise Refused(f"shot {k} is {s['state']}, not submitting (reserve first)")
    s["state"] = "submitted"
    s["attempts"][-1].update({"submitted_at": iso(), "edit_id": real_edit_id(edit_id), "credits": credits})
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


def ingest(j, k, path):
    """Record Fix's file for shot k. -> the durable copy's path inside the job workdir (inbound media
    caches are pruned by age; a 📝 job can wait a day for Fix)."""
    need_open(j); need_flow(j)
    s = shot(j, k)
    if s["state"] not in ("pending", "packed", "regen_approved", "in_review"):
        raise Refused(f"shot {k} is {s['state']}; cannot take a file for it")
    if s["state"] == "in_review":
        raise Refused(f"shot {k} already has a file in review — Fix taps 🔁 first, then sends the new one")
    n = len(s["attempts"]) + 1
    dst = os.path.join(j["workdir"], f"shot{k}_a{n}{os.path.splitext(path)[1] or '.mp4'}")
    s["state"] = "submitted"
    s["attempts"].append({"via": "prompt", "submitted_at": iso(), "file_in": dst, "source": os.path.abspath(path)})
    log(j, f"ingest shot {k}: {os.path.basename(path)} -> {os.path.basename(dst)}")
    return dst


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


def review_keyboard(job, k, approve=True):
    row = ([{"text": f"{APPROVE} ช็อต {k} · {job}"}] if approve else []) + [{"text": f"{REGEN} ช็อต {k} · {job}"}]
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


# ---------------------------------------------------------------- commands
def cmd_pack(j, only, no_send):
    targets = pack_targets(j, only)
    if not targets:
        raise Refused("nothing to pack (every shot is submitted, in review or approved)")
    wd = j["workdir"]
    missing = [k for k in targets if not os.path.exists(os.path.join(wd, f"shot{k}.txt"))]
    if missing:
        raise Refused(f"write the prompt files first: {', '.join(f'{wd}/shot{k}.txt' for k in missing)}")
    sent = []
    if not no_send and not only:
        head = (f"📝 โหมดเตรียม prompt · {j['product']}\n"
                + (f"สลับจากโหมดอัตโนมัติ: {j['fallback']['reason']}\n" if j.get("fallback") else "")
                + (f"ตัวละคร: {j['character']} (แนบจาก Characters ใน Flow ทุกช็อต)\n" if j.get("character") else "")
                + f"ช็อตที่ต้องทำ: {', '.join(map(str, targets))}\n\n"
                  "วิธีใช้: เซฟรูปอ้างอิงด้านล่างไปแนบใน Flow (Ingredients) → ก๊อป prompt ของแต่ละช็อต "
                  "→ gen ใน Flow → กด reply ข้อความ prompt ของช็อตนั้นแล้วแนบ mp4 กลับมา "
                  "(ส่งแบบ 'ไฟล์' จะได้ไม่โดนบีบ ไม่เกิน 20 MB)")
        tg("sendMessage", {"chat_id": CHAT, "text": head})
        for i, r in enumerate(j["refs"], 1):
            tg("sendPhoto", {"chat_id": CHAT, "caption": f"รูปอ้างอิง {i}/{len(j['refs'])} · {j['job']}"},
               files={"photo": r})
    for k in targets:
        prompt = open(os.path.join(wd, f"shot{k}.txt"), encoding="utf-8").read().strip()
        prev = shot(j, k - 1) if k > 1 else None
        chain = ""
        if prev and prev.get("file"):
            lf = last_frame(prev["file"], os.path.join(wd, f"shot{k - 1}_last.jpg"))
            if lf and not no_send:
                tg("sendPhoto", {"chat_id": CHAT, "caption": f"เฟรมเริ่มของช็อต {k} (= เฟรมท้ายช็อต {k - 1})"},
                   files={"photo": lf})
                chain = "\nเฟรมเริ่ม: แนบรูปเฟรมท้ายช็อตก่อนหน้าที่ส่งไปเมื่อกี้เป็น start frame"
        elif prev:
            chain = f"\nเฟรมเริ่ม: ถ้าทำช็อต {k - 1} เสร็จแล้ว ใช้เฟรมท้ายของมันเป็น start frame ภาพจะต่อเนื่อง"
        mid = None
        for text in prompt_messages(j["job"], k, len(j["shots"]), prompt, SHOT_SECONDS, chain):
            if not no_send:
                r = tg("sendMessage", {"chat_id": CHAT, "text": text, "parse_mode": "HTML"})
                mid = mid or r["message_id"]
        s = shot(j, k)
        s.update({"state": "packed", "pack_msg": mid})
        sent.append({"shot": k, "message_id": mid})
    log(j, f"packed shots {targets}")
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
    lines += ["", "ผ่านทุกข้อ" if gates_passed(gates) else "⚠️ มีข้อไม่ผ่าน ไอยูแนะนำ gen ใหม่",
              "ผ่าน = ล็อกช็อตนี้ · gen ใหม่ = " + ("เสียเครดิต" if j["production"] == "auto" else "ฟิกทำใน Flow ใหม่")]
    if s.get("chain_stale"):
        lines += ["", f"⚠️ ช็อตนี้เริ่มจากเฟรมท้ายของช็อต {k - 1} ชุดเดิม (ช็อต {k - 1} กำลัง gen ใหม่) รอยต่ออาจไม่ต่อเนื่อง"]
    tg("sendMessage", {"chat_id": CHAT, "text": "\n".join(lines), "reply_markup": review_keyboard(j["job"], k)})
    s["review_sent"] = iso()


def cmd_ready(j, k, raw, frame_arg, no_send, resend=False):
    if resend:
        if shot(j, k)["state"] != "in_review":
            raise Refused(f"shot {k} is {shot(j, k)['state']}; --resend is for a shot already in review")
        send_review(j, k)
        return {"shot": k, "resent": True, "pass": gates_passed(shot(j, k)["gates"])}
    if not raw or not frame_arg:
        raise Refused("ready needs --raw FILE and --frame pass|flag:<what you saw>")
    frame = parse_frame(frame_arg)
    if not os.path.exists(raw):
        raise Refused(f"no such file: {raw}")
    if shot(j, k)["state"] != "submitted":
        raise Refused(f"shot {k} is {shot(j, k)['state']}, not submitted")
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
    gates["frame"] = frame
    mark_ready(j, k, file, gates)
    res = {"shot": k, "pass": gates_passed(gates), "file": os.path.abspath(file), "gates": gates}
    if not no_send:
        save(j)                              # the checks are done: keep them even when the send fails
        try:
            send_review(j, k)
        except Refused as e:
            raise Refused(f"{e} — the shot IS in review; send it with: clipjob.py ready {j['job']} {k} --resend") from None
    return res


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
               "notes": notes.strip(" |"), "timing": timeline(j, now())}
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
    log(j, "delivered")
    j["timing"] = timeline(j)
    notify(f"ส่งงาน {j['job']} ครบแล้วค่ะ\n{timeline_text(j['timing'])}")        # also clears the review reply keyboard
    return j["delivery"]


def summary(j):
    out = {"job": j["job"], "mode": j["mode"], "production": j["production"], "status": j["status"],
           "product": j["product"], "updated": j["updated"],
           "shots": {s["k"]: s["state"] for s in j["shots"]}}
    if j.get("fallback"):
        out["fallback"] = j["fallback"]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("new"); s.add_argument("job"); s.add_argument("--mode", required=True, choices=MODES)
    s.add_argument("--product", required=True); s.add_argument("--link", default="")
    s.add_argument("--shots", type=int, default=0); s.add_argument("--ref", action="append", default=[])
    s.add_argument("--workdir"); s.add_argument("--character")
    s = sub.add_parser("production"); s.add_argument("job"); s.add_argument("value", choices=["auto", "prompt"])
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
    s = sub.add_parser("ingest"); s.add_argument("job"); s.add_argument("file")
    s.add_argument("--reply-text"); s.add_argument("--shot", type=int)
    s = sub.add_parser("ready"); s.add_argument("job"); s.add_argument("shot", type=int)
    s.add_argument("--raw"); s.add_argument("--frame")
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
    s = sub.add_parser("reopen"); s.add_argument("job"); s.add_argument("--reason", required=True)
    a = ap.parse_args(argv)

    def out(obj):
        print(json.dumps(obj, ensure_ascii=False, indent=1)[:6000])
        return 0

    try:
        if a.cmd == "new":
            if os.path.exists(path_of(a.job)):
                raise Refused(f"job {a.job} exists (pick another slug)")
            missing = [r for r in a.ref if not os.path.exists(r)]
            if missing:
                raise Refused(f"ref not found: {missing}")
            j = new_job(a.job, a.mode, a.product, a.link, a.shots, a.ref, a.workdir, a.character)
            os.makedirs(j["workdir"], exist_ok=True)
            j["started"] = iso(workdir_started(j["workdir"], now()))
            log(j, "created"); save(j)
            return out(summary(j))
        if a.cmd == "status":
            if a.job:
                return out(load(a.job))
            rows = []
            for f in sorted(os.listdir(DIR)) if os.path.isdir(DIR) else []:
                if f.endswith(".json") and f != "pacing.json":
                    jj = json.load(open(os.path.join(DIR, f), encoding="utf-8"))
                    if jj["status"] == "open":
                        rows.append(summary(jj))
            return out({"open_jobs": rows})
        if a.cmd == "decide":
            if a.text:
                parsed = parse_decision_text(a.text)
                if not parsed:
                    raise Refused("text is not a review button (✅ ผ่าน / 🔁 gen ใหม่ ช็อต K · job)")
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
        if a.cmd == "production":
            set_production(j, a.value); save(j)
            return out(summary(j))
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
        if a.cmd in ("note", "wait"):
            need_open(j); log(j, f"{a.cmd}: {a.text}"); save(j)
            return out({**summary(j), "events": j["events"][-5:]})
        if a.cmd == "reopen":
            if j["status"] != "delivered":
                raise Refused(f"job {a.job} is {j['status']}; only a delivered job is reopened for a revision")
            j["status"] = "open"; j["revision"] = a.reason; log(j, f"reopened for a revision: {a.reason}"); save(j)
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
            sent = cmd_pack(j, a.shot, a.no_send); save(j)
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
            dst = ingest(j, k, a.file)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(a.file, dst)
            save(j)
            return out({**summary(j), "file": dst,
                        "next": f"vision-check frames, then clipjob.py ready {a.job} {k} --raw {dst} --frame …"})
        if a.cmd == "ready":
            res = cmd_ready(j, a.shot, a.raw, a.frame, a.no_send, a.resend); save(j)
            return out(res)
        if a.cmd == "assemble-check":
            files = assemble_files(j)
            print("\n".join(files))
            return 0
        if a.cmd == "deliver":
            d = cmd_deliver(j, a); save(j)
            rc, o, e = run(["python3", os.path.join(HERE, "check_delivery.py")])
            return out({"delivered": d, "check_delivery_exit": rc, "check_delivery": (o + e)[-600:]})
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
