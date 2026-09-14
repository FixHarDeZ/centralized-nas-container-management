"""The bot's one shared record, and the only legal ways to change its mode.

`state.json` is a dict and stays one — every module reads it. What this module
adds is the set of transitions, so that "back to idle" clears the same fields
from every exit. Before 2026-09-15 there were six hand-written `state.update(
mode="idle", ...)` sites and they disagreed: one kept `locale`, one kept
`topic` and `message_id`, the startup one cleared only two fields. Every state
race fixed in this stack's history (`trends_running`, `pair` under `parked`,
the upload button's id) came from that kind of drift.

Nothing here writes the file. Callers save; the tests stub `main.save_state`
and a save hidden inside a transition would write to `/data` under them.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path

from app import locales, schedule

logger = logging.getLogger(__name__)

# Work that outlives one poll tick. Writing a Script takes 1-7 minutes and
# rendering takes longer; awaiting either inline froze the whole bot.
BUSY_MODES = {"writing", "rendering"}

#: What an idle bot holds: nothing about a Clip. Every return to idle applies
#: all of these — a field left behind is the next Clip's bug.
IDLE_FIELDS = dict(
    script=None, topic=None, clip_id=None, style="", message_id=None,
    locale=locales.DEFAULT,
)

# How long a Parked Clip waits for its Footage before it is written off.
PARK_LIFETIME = timedelta(hours=int(os.environ.get("FLOW_PARK_HOURS", "24")))


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "/data"))


def path() -> Path:
    return data_dir() / "state.json"


def load() -> dict:
    if path().exists():
        try:
            return json.loads(path().read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning("state.json อ่านไม่ได้ เริ่มใหม่")
    return {"mode": "idle", "offset": 0}


def save(state: dict) -> None:
    data_dir().mkdir(parents=True, exist_ok=True)
    path().write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


# --- transitions --------------------------------------------------------------

def to_idle(state: dict) -> None:
    """The only way back to idle. Does not touch `parked`, `pair`, `uploads`
    or the auto-run bookkeeping: those outlive a Clip on purpose."""
    state.update(mode="idle", **IDLE_FIELDS)


def busy_note(mode: str) -> str:
    """What to tell a human who sent work while the bot is mid-job."""
    job = "เขียนสคริปต์" if mode == "writing" else "render"
    return f"⏳ กำลัง{job}อยู่ รอให้เสร็จก่อนนะ"


# --- the unattended run -------------------------------------------------------

def auto_slots(state: dict, now: datetime | None = None) -> list[tuple[str, str]]:
    """The (locale, slot) trends rounds that are owed. Shaped like snapshots.due().

    Only the newest passed hour is ever owed per Locale: a bot that was down
    all day comes back and runs each channel once, not once per missed hour.
    The hours live in `/config/schedule.json`, which the dashboard writes
    (docs/adr/0009), so this reads them fresh every tick.
    """
    return schedule.due(state, now or datetime.now())


def auto_pick_due(state: dict, now: datetime | None = None) -> bool:
    """Whether the wait for a human choice has run out."""
    pending = state.get("auto_pick") or {}
    try:
        return (now or datetime.now()) >= datetime.fromisoformat(pending["deadline"])
    except (KeyError, TypeError, ValueError):
        return False


def parked_expired(state: dict, now: datetime | None = None) -> bool:
    """Whether a Parked Clip has waited for its Footage long enough."""
    parked = state.get("parked") or {}
    try:
        born = datetime.fromisoformat(parked["created_at"])
    except (KeyError, TypeError, ValueError):
        return False
    return (now or datetime.now()) - born > PARK_LIFETIME


def claim_auto_pick(state: dict, now: datetime | None = None) -> bool | None:
    """Drop an owed unattended pick and say whether to act on it.

    None when nothing was owed (state untouched). Otherwise the pick is gone
    either way: a human already busy — or off generating Footage for a Parked
    Clip — does not get one queued behind them to fire off a stale list.
    """
    if not auto_pick_due(state, now):
        return None
    state.pop("auto_pick", None)
    return state.get("mode", "idle") == "idle" and not state.get("parked")
