"""Persistent state store backed by a JSON file on a Docker volume.

State shape:
  {
    "pending":         { user_id: {"data": write_payload, "ts": float} },
    "pending_general": { user_id: {"data": original_question, "ts": float} },
    "pending_note":    { user_id: {"data": note_creation_state, "ts": float} },
    "history":         { user_id: [ {role, content}, ... ] }  # max MAX_HISTORY exchanges
  }

Writes are atomic: write to .tmp then os.replace().
No threading lock needed — FastAPI handles one event loop; concurrency here
is negligible for a personal bot.
"""

from __future__ import annotations

import json
import logging
import os
import time

logger = logging.getLogger(__name__)

MAX_HISTORY = 4  # exchanges (= 8 messages) kept per user
PENDING_TTL = 6 * 3600  # 6 hours — pending confirmations auto-expire after this


def _wrap(data) -> dict:
    return {"data": data, "ts": time.time()}


def _unwrap(entry):
    """Return the payload from a wrapped or legacy entry."""
    if isinstance(entry, dict) and "data" in entry and "ts" in entry:
        return entry["data"]
    return entry  # backward compat: old format stored raw payload


def _expired(entry) -> bool:
    if isinstance(entry, dict) and "ts" in entry:
        return time.time() - entry["ts"] > PENDING_TTL
    return False  # old format: no expiry

_DATA_FILE = "/data/state.json"

_state: dict = {
    "pending": {},
    "pending_general": {},
    "pending_note": {},
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
    entry = _state["pending"].get(user_id)
    return _unwrap(entry) if entry is not None else None


def set_pending(user_id: str, payload: dict) -> None:
    _state["pending"][user_id] = _wrap(payload)
    _save()


def pop_pending(user_id: str) -> dict | None:
    entry = _state["pending"].pop(user_id, None)
    if entry is not None:
        _save()
    return _unwrap(entry) if entry is not None else None


def has_pending(user_id: str) -> bool:
    entry = _state["pending"].get(user_id)
    if entry is None:
        return False
    if _expired(entry):
        _state["pending"].pop(user_id, None)
        _save()
        logger.info(f"Expired pending for {user_id}")
        return False
    return True


# ── pending_general ───────────────────────────────────────────────

def get_pending_general(user_id: str) -> str | None:
    entry = _state["pending_general"].get(user_id)
    return _unwrap(entry) if entry is not None else None


def set_pending_general(user_id: str, question: str) -> None:
    _state["pending_general"][user_id] = _wrap(question)
    _save()


def pop_pending_general(user_id: str) -> str | None:
    entry = _state["pending_general"].pop(user_id, None)
    if entry is not None:
        _save()
    return _unwrap(entry) if entry is not None else None


def has_pending_general(user_id: str) -> bool:
    entry = _state["pending_general"].get(user_id)
    if entry is None:
        return False
    if _expired(entry):
        _state["pending_general"].pop(user_id, None)
        _save()
        logger.info(f"Expired pending_general for {user_id}")
        return False
    return True


# ── pending_note ──────────────────────────────────────────────────

def get_pending_note(user_id: str) -> dict | None:
    entry = _state["pending_note"].get(user_id)
    return _unwrap(entry) if entry is not None else None


def set_pending_note(user_id: str, payload: dict) -> None:
    _state["pending_note"][user_id] = _wrap(payload)
    _save()


def pop_pending_note(user_id: str) -> dict | None:
    entry = _state["pending_note"].pop(user_id, None)
    if entry is not None:
        _save()
    return _unwrap(entry) if entry is not None else None


def has_pending_note(user_id: str) -> bool:
    entry = _state["pending_note"].get(user_id)
    if entry is None:
        return False
    if _expired(entry):
        _state["pending_note"].pop(user_id, None)
        _save()
        logger.info(f"Expired pending_note for {user_id}")
        return False
    return True


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


def clear_history(user_id: str) -> None:
    if user_id in _state["history"]:
        del _state["history"][user_id]
        _save()
