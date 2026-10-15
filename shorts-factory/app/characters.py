"""Recurring characters for Storyboard Studio packs.

The dashboard writes `/config/characters.json` through `POST /settings` (the
one writing route, docs/adr/0009) and holds no model key, so it cannot turn a
Thai description into the English the prompts need. The bot does that once
and caches it in `/data/character_tags.json`, keyed by a hash of the Thai text:
the English stays word-for-word identical across clips until the description
is edited. One writer per file. Paths are read at call time, so the bot sees
an edit without a restart.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

CHANNELS = ("th", "en", "shop")
FLOW, PEXELS = "flow", "pexels"
RULES = ("hook", "none", "all")
MAX_CHARACTERS = 10

ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,19}$")
TAG = re.compile(r"^@[A-Za-z][A-Za-z0-9_]{0,23}$")
THAI = re.compile(r"[ก-๙]")


def _path() -> Path:
    return Path(os.environ.get("CONFIG_DIR", "/config")) / "characters.json"


def _cache_path() -> Path:
    return Path(os.environ.get("DATA_DIR", "/data")) / "character_tags.json"


def _empty() -> dict:
    return {"characters": [], "defaults": {c: "" for c in CHANNELS}, "footage": "hook"}


def validate(payload: dict) -> dict:
    """The whole library or nothing: one bad row rejects the request."""
    if not isinstance(payload, dict):
        raise ValueError("ต้องเป็น object")
    rows = payload.get("characters") or []
    if not isinstance(rows, list) or len(rows) > MAX_CHARACTERS:
        raise ValueError(f"ตัวละครต้องเป็นลิสต์ ไม่เกิน {MAX_CHARACTERS} ตัว")
    if not isinstance(payload.get("defaults") or {}, dict):
        raise ValueError("defaults ต้องเป็น object")
    out, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("ตัวละครแต่ละตัวต้องเป็น object")
        cid = str(row.get("id", "")).strip()
        tag = str(row.get("tag", "")).strip()
        thai = str(row.get("thai", "")).strip()
        english = str(row.get("english", "")).strip()
        if not cid:
            raise ValueError(f"ตัวละคร {tag or thai[:20]}: ต้องใส่ id (a-z 0-9 _ -)")
        if not ID.fullmatch(cid):
            raise ValueError(f"id '{cid}' ใช้ได้แค่ a-z 0-9 _ - ยาวไม่เกิน 20")
        if cid in seen:
            raise ValueError(f"id '{cid}' ซ้ำ")
        if not TAG.fullmatch(tag):
            raise ValueError(f"tag '{tag}' ต้องขึ้นต้นด้วย @ ตามด้วยอักษรอังกฤษ")
        if not thai:
            raise ValueError(f"{cid}: ต้องมีคำบรรยายภาษาไทย")
        if THAI.search(english):
            raise ValueError(f"{cid}: ช่อง English ต้องเป็นภาษาอังกฤษล้วน")
        seen.add(cid)
        out.append({"id": cid, "tag": tag, "thai": thai, "english": english,
                    "flow_ready": bool(row.get("flow_ready"))})
    defaults = {c: str((payload.get("defaults") or {}).get(c, "") or "") for c in CHANNELS}
    for channel, cid in defaults.items():
        if cid and cid not in seen:
            raise ValueError(f"ค่าเริ่มต้นช่อง {channel} ชี้ตัวละคร '{cid}' ที่ไม่มีอยู่")
    rule = str(payload.get("footage", "hook") or "hook")
    if rule not in RULES:
        raise ValueError(f"กติกา footage '{rule}' ไม่รู้จัก")
    return {"characters": out, "defaults": defaults, "footage": rule}


def stored() -> dict:
    try:
        return validate(json.loads(_path().read_text(encoding="utf-8")))
    except (OSError, ValueError):
        try:
            # A default pointing at a deleted character must not void the library.
            raw = json.loads(_path().read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                return _empty()
            raw["defaults"] = {}
            return validate(raw)
        except (OSError, ValueError):
            return _empty()


def save(payload: dict) -> dict:
    clean = validate(payload)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
    return clean


def get(cid: str) -> dict | None:
    return next((c for c in stored()["characters"] if c["id"] == cid), None)


def default_for(channel: str) -> str:
    cid = stored()["defaults"].get(channel, "")
    return cid if cid and get(cid) else ""


def default_sources(count: int) -> list[str]:
    rule = stored()["footage"]
    if rule == "all":
        return [FLOW] * count
    if rule == "none":
        return [PEXELS] * count
    return [FLOW] + [PEXELS] * (count - 1)


def from_form(form) -> dict:
    """Rows `char_<n>_*`. A fully blank row is the empty slot, not an error.

    A row with text but no id is kept, so `validate()` rejects it ("ต้องใส่ id")
    and the page redraws it: dropping it would lose a typed character silently.
    """
    rows, n = [], 0
    while f"char_{n}_id" in form:
        row = {"id": str(form.get(f"char_{n}_id", "")).strip(),
               "tag": str(form.get(f"char_{n}_tag", "")).strip(),
               "thai": str(form.get(f"char_{n}_thai", "")).strip(),
               "english": str(form.get(f"char_{n}_english", "")).strip(),
               "flow_ready": bool(form.get(f"char_{n}_ready"))}
        if row["id"] or row["tag"] or row["thai"] or row["english"]:
            rows.append(row)
        n += 1
    return {"characters": rows,
            "defaults": {c: str(form.get(f"default_{c}", "")) for c in CHANNELS},
            "footage": str(form.get("footage", "hook"))}


def _key(character: dict) -> str:
    return hashlib.sha256(character["thai"].encode("utf-8")).hexdigest()[:16]


def _cache() -> dict:
    try:
        cache = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return cache if isinstance(cache, dict) else {}


def cached_english(character: dict) -> str:
    """Typed English wins; otherwise the bot's translation of this exact Thai text."""
    if character.get("english"):
        return character["english"]
    return str(_cache().get(_key(character), ""))


def remember_english(character: dict, english: str) -> None:
    cache = _cache()
    cache[_key(character)] = english
    path = _cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
