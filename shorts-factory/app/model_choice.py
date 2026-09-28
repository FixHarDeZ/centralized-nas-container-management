"""Which mimo model the bot writes with, picked from the dashboard.

Sits next to the trends schedule on the same `/config` volume, in its own
file — `/config/models.json` — so `schedule.validate()` keeps treating every
top-level key of its file as a Locale. No file, or an empty choice, means the
environment decides exactly as it did before this existed (`MIMO_MODEL`,
`MIMO_FALLBACK_MODEL` through `app/mimo.py`).

A closed list, not free text: the dashboard holds no API key (docs/adr/0007)
so it cannot ask the endpoint whether a name exists, and a typo would break
the unattended /trends rounds with nobody watching. The list itself is live:
the bot, which has the key, pulls `GET /models` at startup and every
`CATALOG_HOURS` into `/data/mimo_models.json`, and the dashboard reads that
through its `/data:ro` mount. New mimo releases appear without a deploy; no
catalog yet means `CHOICES`. Read on every call, not
cached at import: the dashboard is a different process and the bot must see
an edit without a restart.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path

from app import mimo

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
PATH = CONFIG_DIR / "models.json"

CATALOG = Path(os.environ.get("DATA_DIR", "/data")) / "mimo_models.json"
CATALOG_HOURS = float(os.environ.get("MIMO_CATALOG_HOURS", "6"))

CHOICES = ("mimo-v2.5-pro", "mimo-v2.5")
ROLES = ("primary", "fallback")

# `/models` also lists speech models (asr, tts-*) that 400 on a chat request.
NOT_CHAT = re.compile(r"-(asr|tts)\b")


def _newest_first(name: str) -> tuple:
    """Natural order, newest version first: v2.10 after v2.9, not before v2.2."""
    return tuple(-int(part) if part.isdigit() else 0
                 for part in re.split(r"(\d+)", name) if part)


def chat_models(names: list[str]) -> list[str]:
    return sorted({n for n in names if n.startswith("mimo") and not NOT_CHAT.search(n)},
                  key=lambda n: (_newest_first(n), n))


def catalog() -> dict:
    """`{"fetched_at", "models"}` as the bot last wrote it, or `{}`."""
    try:
        data = json.loads(CATALOG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) and data.get("models") else {}


def choices() -> tuple[str, ...]:
    return tuple(catalog().get("models") or CHOICES)


_last_refresh = 0.0


def refresh_due() -> bool:
    return time.monotonic() - _last_refresh >= CATALOG_HOURS * 3600 or not _last_refresh


async def refresh() -> list[str]:
    """Ask the endpoint what exists and store the chat models. Bot only.

    A failure keeps the previous catalog: a stale list beats an empty dropdown.
    """
    global _last_refresh
    _last_refresh = time.monotonic()
    try:
        reply = await asyncio.wait_for(mimo.client().models.list(), timeout=30)
        models = chat_models([m.id for m in reply.data])
    except Exception:
        logger.warning("ดึงรายชื่อ model ของ mimo ไม่ได้ ใช้ลิสต์เดิม", exc_info=True)
        return []
    if not models:
        return []
    temporary = CATALOG.with_suffix(".tmp")
    temporary.write_text(json.dumps({
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
        "models": models,
    }, indent=2), encoding="utf-8")
    temporary.replace(CATALOG)
    return models


def validate(payload: dict) -> dict:
    """The whole choice or ValueError — never half of it."""
    if not isinstance(payload, dict):
        raise ValueError("ต้องเป็น object")
    clean = {}
    for role in ROLES:
        name = str(payload.get(role) or "").strip()
        if name and name not in choices():
            raise ValueError(f"{role}: ไม่รู้จัก model {name!r}")
        clean[role] = name
    return clean


def stored() -> dict:
    """What the dashboard saved; empty strings where it left the default."""
    try:
        return validate(json.loads(PATH.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return validate({})
    except (json.JSONDecodeError, OSError, ValueError):
        logger.warning("%s เก็บค่าที่ใช้ไม่ได้ ใช้ค่าจาก env", PATH, exc_info=True)
        return validate({})


def save(payload: dict) -> dict:
    clean = validate(payload)
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temporary = PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    temporary.replace(PATH)
    return clean


def primary() -> str:
    return stored()["primary"] or mimo.model()


def fallback() -> str:
    return stored()["fallback"] or mimo.fallback_model()
