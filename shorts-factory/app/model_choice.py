"""Which mimo model the bot writes with, picked from the dashboard.

Sits next to the trends schedule on the same `/config` volume, in its own
file — `/config/models.json` — so `schedule.validate()` keeps treating every
top-level key of its file as a Locale. No file, or an empty choice, means the
environment decides exactly as it did before this existed (`MIMO_MODEL`,
`MIMO_FALLBACK_MODEL` through `app/mimo.py`).

A closed list, not free text: the dashboard holds no API key (docs/adr/0007)
so it cannot ask the endpoint whether a name exists, and a typo would break
the unattended /trends rounds with nobody watching. Read on every call, not
cached at import: the dashboard is a different process and the bot must see
an edit without a restart.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from app import mimo

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(os.environ.get("CONFIG_DIR", "/config"))
PATH = CONFIG_DIR / "models.json"

CHOICES = ("mimo-v2.5-pro", "mimo-v2.5")
ROLES = ("primary", "fallback")


def validate(payload: dict) -> dict:
    """The whole choice or ValueError — never half of it."""
    if not isinstance(payload, dict):
        raise ValueError("ต้องเป็น object")
    clean = {}
    for role in ROLES:
        name = str(payload.get(role) or "").strip()
        if name and name not in CHOICES:
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
