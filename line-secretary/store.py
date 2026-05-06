"""Persistent state store backed by a JSON file on a Docker volume.

State shape:
  {
    "pending":         { user_id: write_payload },
    "pending_general": { user_id: original_question },
    "history":         { user_id: [ {role, content}, ... ] }  # max MAX_HISTORY exchanges
  }

Writes are atomic: write to .tmp then os.replace().
No threading lock needed — FastAPI handles one event loop; concurrency here
is negligible for a personal bot.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

MAX_HISTORY = 4  # exchanges (= 8 messages) kept per user

_DATA_FILE = "/data/state.json"

_state: dict = {
    "pending": {},
    "pending_general": {},
    "history": {},
}


def init(data_dir: str) -> None:
    global _DATA_FILE
    os.makedirs(data_dir, exist_ok=True)
    _DATA_FILE = os.path.join(data_dir, "state.json")
    if not os.path.exists(_DATA_FILE):
        return
    try:
        with open(_DATA_FILE, encoding="utf-8") as f:
            loaded = json.load(f)
        for k in _state:
            if k in loaded and isinstance(loaded[k], dict):
                _state[k] = loaded[k]
        logger.info(
            f"Store loaded — pending:{len(_state['pending'])} "
            f"history:{len(_state['history'])} users"
        )
    except Exception as e:
        logger.warning(f"Store load failed (starting fresh): {e}")


def _save() -> None:
    tmp = _DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_state, f, ensure_ascii=False)
    os.replace(tmp, _DATA_FILE)


# ── pending ──────────────────────────────────────────────────────

def get_pending(user_id: str) -> dict | None:
    return _state["pending"].get(user_id)


def set_pending(user_id: str, payload: dict) -> None:
    _state["pending"][user_id] = payload
    _save()


def pop_pending(user_id: str) -> dict | None:
    val = _state["pending"].pop(user_id, None)
    if val is not None:
        _save()
    return val


def has_pending(user_id: str) -> bool:
    return user_id in _state["pending"]


# ── pending_general ───────────────────────────────────────────────

def get_pending_general(user_id: str) -> str | None:
    return _state["pending_general"].get(user_id)


def set_pending_general(user_id: str, question: str) -> None:
    _state["pending_general"][user_id] = question
    _save()


def pop_pending_general(user_id: str) -> str | None:
    val = _state["pending_general"].pop(user_id, None)
    if val is not None:
        _save()
    return val


def has_pending_general(user_id: str) -> bool:
    return user_id in _state["pending_general"]


# ── history ───────────────────────────────────────────────────────

def get_history(user_id: str) -> list[dict]:
    return list(_state["history"].get(user_id, []))


def add_history(user_id: str, user_text: str, bot_text: str) -> None:
    hist = _state["history"].setdefault(user_id, [])
    hist.extend([
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": bot_text},
    ])
    if len(hist) > MAX_HISTORY * 2:
        _state["history"][user_id] = hist[-(MAX_HISTORY * 2):]
    _save()
