import json
import logging

from config import STATE_FILE

log = logging.getLogger("game-codes")


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            s.setdefault("seen", {})
            s.setdefault("health", {})
            s.setdefault("rate_limited_until", {})
            return s
        except Exception as e:
            log.warning("bad state file (%s), starting fresh", e)
    return {"seen": {}, "health": {}, "rate_limited_until": {}}


def save_state(state: dict) -> None:
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def diff_new(src: dict, entries: list[dict], state: dict) -> list[dict]:
    key = src["key"]
    first_time = key not in state["seen"]
    seen = set(state["seen"].get(key, []))
    fresh = [e for e in entries if e["code"] not in seen]
    state["seen"][key] = sorted(seen | {e["code"] for e in entries})
    return [] if first_time else fresh
