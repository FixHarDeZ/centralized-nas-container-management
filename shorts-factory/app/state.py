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
    locale=locales.DEFAULT, review_at=None,
)

# How long a Parked Clip waits for its Footage before it is written off.
PARK_LIFETIME = timedelta(hours=int(os.environ.get("FLOW_PARK_HOURS", "24")))
# How long a sent Storyboard waits for the finished clip the human assembles
# from it. Longer than a Parked Clip on purpose: that one is a single 8-second
# shot, this one is every scene generated, cut together and exported.
CLIP_WAIT_LIFETIME = timedelta(hours=int(os.environ.get("STORYBOARD_CLIP_HOURS", "72")))
# How long a Script waits for the human to press one of its buttons. Review had
# no clock until 2026-09-22, and the unattended trends round only fires from an
# idle bot: one Script nobody answered silenced every channel's schedule for
# good. A review left open at 15:05 on 09-21 ate th 17:00, en 19:00 and 23:00,
# and th 08:00 the next morning, without one line in the log to say so.
# Shorter than both waits above on purpose: those hold a human who is off doing
# work elsewhere (generating footage, cutting a board together), this one is
# waiting on a tap. A Script nobody has answered in this long is abandoned.
REVIEW_LIFETIME = timedelta(hours=int(os.environ.get("REVIEW_LIFETIME_HOURS", "6")))


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


def to_review(state: dict, **fields) -> None:
    """Hand a Script to the human and start its clock.

    The stamp lives here rather than at the three call sites for the same
    reason this module exists: a site that forgets it is a path back to a
    review that never ends. `fields` is whatever that entrance also sets --
    the Script itself, the Topic, the id of the message holding the buttons.
    """
    state.update(mode="review",
                 review_at=datetime.now().isoformat(timespec="seconds"),
                 **fields)


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


def _aged_out(record: dict, lifetime: timedelta, now: datetime | None,
              key: str = "created_at") -> bool:
    try:
        born = datetime.fromisoformat(record[key])
    except (KeyError, TypeError, ValueError):
        return False
    return (now or datetime.now()) - born > lifetime


def parked_expired(state: dict, now: datetime | None = None) -> bool:
    """Whether a Parked Clip has waited for its Footage long enough."""
    return _aged_out(state.get("parked") or {}, PARK_LIFETIME, now)


def clip_wait_expired(state: dict, now: datetime | None = None) -> bool:
    """Whether a sent Storyboard has waited long enough for its finished clip.

    The wait holds nothing but a message id and the metadata to file the clip
    under, so letting it go costs nothing — but leaving it forever means a
    video replied to that message months later lands on a Topic nobody
    remembers.
    """
    return _aged_out(state.get("clip_wait") or {}, CLIP_WAIT_LIFETIME, now)


def review_expired(state: dict, now: datetime | None = None) -> bool:
    """Whether a Script has waited for its button press long enough.

    Reads the live state rather than a sub-record, because a review *is* the
    live state -- there is no record to hand to the sweep, only `message_id`
    and `clip_id`. An unstamped review never expires: _aged_out says False on
    a missing key, so a Script mid-flight over an upgrade keeps the old
    behaviour instead of being dropped on a guessed age. `stamp_review()`
    closes that window at startup.
    """
    if state.get("mode") != "review":
        return False
    return _aged_out(state, REVIEW_LIFETIME, now, key="review_at")


def stamp_review(state: dict) -> bool:
    """Give a review that has no clock one, and say whether it needed it.

    Called at startup. Without it the one review that was open when this
    shipped -- and any review carried across a restart by a state file written
    before it -- would still be immortal, which is the whole bug.
    """
    if state.get("mode") != "review" or state.get("review_at"):
        return False
    state["review_at"] = datetime.now().isoformat(timespec="seconds")
    return True


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
