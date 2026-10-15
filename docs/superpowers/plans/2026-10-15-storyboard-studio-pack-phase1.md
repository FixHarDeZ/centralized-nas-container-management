# Storyboard Studio Pack — Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** From a reviewed Shorts Script, the bot produces a Google Flow Storyboard Studio pack for the Cards the human marks 🎬 Flow. It then takes back one stitched export, cuts it per Card, and renders the Short using the narration it already measured. Every other Card keeps its Pexels footage.

**Architecture:** New pure module `app/studio.py` (shot maths, pack files, cutter, inbox) and `app/characters.py` (character library in `/config`, English cache in `/data`). Extensions to `storyboard.py` (studio planning + `script.md`) and `render.build` (`narration=`, `hold=`). The bot gets a 🎞 Studio button and a `clip_wait` of `kind: "studio"`. The read-only dashboard serves the pack page. The Shop API service gains one upload route into `/output/studio-inbox/`, which the bot's existing poll loop picks up.

**Tech Stack:** Python 3.12, FastAPI (dashboard + Shop API), httpx Telegram long-poll, edge-tts, ffmpeg/ffprobe, Jinja2, pytest.

**Spec:** `docs/superpowers/specs/2026-10-15-storyboard-studio-pack-design.md`

## Global Constraints

- Shot length is exactly **8 s**. `shots = ceil((span + 0.5) / 8)`, at least 1. The last Card's span includes `render.TAIL_PAD` (0.2).
- Export accepted when `abs(duration - shots_total * 8) <= 0.5`. Otherwise refuse and offer **"cut evenly"** (`duration / shots_total` per shot). Never cut on a guess.
- `script.md` is English only. It holds no Thai, no narration, no dialogue. Every scene repeats the `@tag` and the full `locked_prompt_tag` when there is a character.
- Default footage: Card 1 (hook) = Flow, rest = Pexels. The rule comes from `/config/characters.json` key `footage` ∈ `hook | none | all`.
- `/config/characters.json` is written only by the dashboard (`POST /settings`). `/data/character_tags.json` is written only by the bot.
- The dashboard stays read-only except `POST /settings` (`WRITING_ROUTES == {"/settings"}`). It must never import PIL or edge_tts. `app/studio.py` imports `app.render` only inside the function that needs it.
- The bot opens no port (ADR 0002). Uploads land in `/output/studio-inbox/<token>.mp4` through the Shop API, under existing nginx Basic Auth plus Shop CSRF. The bot polls the folder.
- Shop API does not decode media (its module docstring). It checks the token format, the `ftyp` magic at bytes 4–8, and the 100 MiB cap only. The bot ffprobes.
- Token: `secrets.token_hex(6)`, regex `^[a-f0-9]{12}$`.
- Callback prefixes (≤64 bytes): `studio` (review button), `stt:<clip>:<card>` toggle, `stc:<clip>:<choice>` character, `stp:<clip>` all Pexels, `stx:<clip>` ✂️ shorten, `ste:<clip>:<token>` cut evenly, `str:<clip>` render when the bot was busy.
- A clip with any Card `footage_source == "flow-studio"` is excluded from `experiment.tally`.
- `FLOW_CREDITS_PER_SHOT` env, default `12`.
- Studio files live in `/data/studio/<clip_id>/`. They are deleted on upload success or `clip_wait` expiry.
- Do not edit `app/mimo.py` or `app/telegram.py`. They are vendored copies of `shared/`.
- No new spend, no Flow automation.

**Test commands** (run from the repo root). Task 1 Step 0 creates `shorts-factory/scripts/sf-test`. It is a committed wrapper, not a shell variable: every Bash call starts a fresh zsh, and zsh does not word-split an unquoted `$VAR`.

```bash
# once per session, and again after requirements/Dockerfile change
docker build -t shorts-factory:studio shorts-factory
# any test file; app/ and tests/ are mounted, so no rebuild per edit
shorts-factory/scripts/sf-test tests/test_studio.py -q
```

The full regression excludes the one live-TTS test:
`shorts-factory/scripts/sf-test tests/ -q --deselect tests/test_shorts_factory.py::test_narration_is_one_take_with_a_start_per_card`

---

### Task 1: Character library (`app/characters.py`)

**Files:**
- Create: `shorts-factory/scripts/sf-test`
- Create: `shorts-factory/app/characters.py`
- Test: `shorts-factory/tests/test_studio_characters.py`

**Interfaces:**
- Produces:
  - `validate(payload: dict) -> dict` (raises `ValueError`)
  - `stored() -> dict`
  - `save(payload: dict) -> dict`
  - `get(cid: str) -> dict | None`
  - `default_for(channel: str) -> str`
  - `default_sources(count: int) -> list[str]`
  - `from_form(form) -> dict`
  - `cached_english(character: dict) -> str`
  - `remember_english(character: dict, english: str) -> None`
  - Constants: `CHANNELS = ("th", "en", "shop")`, `FLOW = "flow"`, `PEXELS = "pexels"`
- Character dict: `{"id": str, "tag": "@Name", "thai": str, "english": str, "flow_ready": bool}`

- [ ] **Step 0: Test wrapper**

```sh
#!/bin/sh
# shorts-factory/scripts/sf-test — pytest inside the stack image, with this
# checkout's app/ and tests/ mounted read-only and no network (no live TTS,
# no model calls). Build the image first: docker build -t shorts-factory:studio shorts-factory
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
exec docker run --rm --network none \
  -v "$here/app:/app/app:ro" -v "$here/tests:/app/tests:ro" \
  "${SF_IMAGE:-shorts-factory:studio}" pytest "$@"
```

Run: `chmod +x shorts-factory/scripts/sf-test && docker build -t shorts-factory:studio shorts-factory && shorts-factory/scripts/sf-test tests/test_dashboard.py -q`
Expected: the existing dashboard tests pass.

- [ ] **Step 1: Write the failing tests**

```python
# shorts-factory/tests/test_studio_characters.py
import json

import pytest

from app import characters


@pytest.fixture(autouse=True)
def dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    (tmp_path / "config").mkdir()
    (tmp_path / "data").mkdir()
    return tmp_path


def nong(**extra):
    return {"id": "nong", "tag": "@Nong", "thai": "ผู้หญิงไทย 28 ปี ผมบ๊อบ แว่นกลม",
            "english": "", "flow_ready": False, **extra}


def test_missing_file_means_empty_library_and_hook_rule():
    assert characters.stored()["characters"] == []
    assert characters.default_for("th") == ""
    assert characters.default_sources(4) == ["flow", "pexels", "pexels", "pexels"]


def test_save_round_trips_and_defaults_per_channel(dirs):
    saved = characters.save({"characters": [nong()],
                             "defaults": {"th": "nong", "en": "", "shop": "nong"},
                             "footage": "all"})
    assert saved["defaults"]["th"] == "nong"
    assert characters.get("nong")["tag"] == "@Nong"
    assert characters.default_for("shop") == "nong"
    assert characters.default_sources(3) == ["flow", "flow", "flow"]
    assert json.loads((dirs / "config" / "characters.json").read_text())["footage"] == "all"


@pytest.mark.parametrize("bad", [
    {"characters": [nong(tag="Nong")]},                       # tag needs @
    {"characters": [nong(id="Has Space")]},                   # id slug
    {"characters": [nong(), nong()]},                         # duplicate id
    {"characters": [nong(thai="")]},                          # thai required
    {"characters": [nong(english="ผู้หญิง")]},                 # english must be latin
    {"characters": [nong()], "defaults": {"th": "ghost"}},    # unknown default
    {"characters": [], "footage": "sometimes"},               # unknown rule
])
def test_invalid_payload_writes_nothing(dirs, bad):
    with pytest.raises(ValueError):
        characters.save(bad)
    assert not (dirs / "config" / "characters.json").exists()


def test_unknown_default_on_disk_falls_back_to_none(dirs):
    (dirs / "config" / "characters.json").write_text(json.dumps(
        {"characters": [], "defaults": {"th": "gone"}, "footage": "hook"}))
    assert characters.default_for("th") == ""


def test_english_cache_is_keyed_by_the_thai_text(dirs):
    c = nong()
    assert characters.cached_english(c) == ""
    characters.remember_english(c, "the same 28-year-old Thai woman")
    assert characters.cached_english(c) == "the same 28-year-old Thai woman"
    assert characters.cached_english(nong(thai="ผู้ชายไทย")) == ""
    assert characters.cached_english(nong(english="typed by hand")) == "typed by hand"


def test_from_form_reads_rows_and_drops_blank_ones():
    form = {"char_0_id": "nong", "char_0_tag": "@Nong", "char_0_thai": "ผู้หญิง",
            "char_0_english": "", "char_0_ready": "on",
            "char_1_id": "", "char_1_tag": "", "char_1_thai": "",
            "default_th": "nong", "default_en": "", "default_shop": "", "footage": "hook"}
    payload = characters.from_form(form)
    assert payload["characters"] == [{"id": "nong", "tag": "@Nong", "thai": "ผู้หญิง",
                                      "english": "", "flow_ready": True}]
    assert payload["defaults"] == {"th": "nong", "en": "", "shop": ""}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `shorts-factory/scripts/sf-test tests/test_studio_characters.py -q`
Expected: FAIL with `ImportError: cannot import name 'characters'`

- [ ] **Step 3: Implement**

```python
# shorts-factory/app/characters.py
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
    rows = payload.get("characters") or []
    if not isinstance(rows, list) or len(rows) > MAX_CHARACTERS:
        raise ValueError(f"ตัวละครต้องเป็นลิสต์ ไม่เกิน {MAX_CHARACTERS} ตัว")
    out, seen = [], set()
    for row in rows:
        cid = str(row.get("id", "")).strip()
        tag = str(row.get("tag", "")).strip()
        thai = str(row.get("thai", "")).strip()
        english = str(row.get("english", "")).strip()
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
    """Rows `char_<n>_*`; a row with an empty id is a blank slot, not an error."""
    rows, n = [], 0
    while f"char_{n}_id" in form:
        cid = str(form.get(f"char_{n}_id", "")).strip()
        if cid:
            rows.append({"id": cid,
                         "tag": str(form.get(f"char_{n}_tag", "")).strip(),
                         "thai": str(form.get(f"char_{n}_thai", "")).strip(),
                         "english": str(form.get(f"char_{n}_english", "")).strip(),
                         "flow_ready": bool(form.get(f"char_{n}_ready"))})
        n += 1
    return {"characters": rows,
            "defaults": {c: str(form.get(f"default_{c}", "")) for c in CHANNELS},
            "footage": str(form.get("footage", "hook"))}


def _key(character: dict) -> str:
    return hashlib.sha256(character["thai"].encode("utf-8")).hexdigest()[:16]


def _cache() -> dict:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `shorts-factory/scripts/sf-test tests/test_studio_characters.py -q`
Expected: 12 passed

- [ ] **Step 5: Commit**

```bash
git add shorts-factory/scripts/sf-test shorts-factory/app/characters.py shorts-factory/tests/test_studio_characters.py
git commit -m "feat(shorts-factory): character library for Studio packs"
```

---

### Task 2: Shot maths, pack files and inbox (`app/studio.py`)

**Files:**
- Create: `shorts-factory/app/studio.py`
- Test: `shorts-factory/tests/test_studio.py`

**Interfaces:**
- Produces:
  - Constants: `SHOT_SECONDS = 8.0`, `MARGIN = 0.5`, `TOLERANCE = 0.5`, `TOKEN` (regex)
  - Shot maths:
    - `spans(starts: list[float], total: float, tail_pad: float) -> list[float]`
    - `shots_for(span: float) -> int`
    - `pending_cards(sources: list[str], have: set[int]) -> list[int]`
    - `shot_map(spans: list[float], pending: list[int]) -> dict[int, int]`
    - `total_shots(shots: dict[int, int]) -> int`
    - `credits(total: int) -> int`
    - `new_token() -> str`
    - `fits(duration: float, total: int) -> bool`
    - `shot_length(duration: float, total: int, even: bool) -> float`
  - Files:
    - `root(clip_id: str) -> Path`
    - `segment_path(clip_id: str, card: int) -> Path`
    - `have_segments(clip_id: str, count: int) -> set[int]`
    - `write_pack(clip_id: str, pack: dict, markdown: str) -> None`
    - `read_pack(clip_id: str) -> dict | None`
    - `read_markdown(clip_id: str) -> str | None`
    - `discard(clip_id: str) -> None`
  - Inbox:
    - `inbox_dir() -> Path`
    - `claim_inbox(tokens: set[str]) -> list[tuple[str, Path]]`
    - `sweep_inbox(live: set[str], hours: float = 72) -> int`
  - `version_for_message(wait: dict, message_id: int | None) -> str | None`
- Pack dict keys (written by Task 7):
  - identity: `clip_id`, `token`, `version`, `title`, `locale`, `created_at`
  - `character`: `{"choice","id","tag","locked","flow_ready","portrait"}` or `None`
  - planning: `sources`, `pending`, `shots` (`{"0": 2}`), `total_shots`, `credits`, `spans`
  - `scenes`: list of `{"n","card","image_prompt","motion","narration","span"}`

- [ ] **Step 1: Write the failing tests**

```python
# shorts-factory/tests/test_studio.py
import os
import time

import pytest

from app import studio


@pytest.fixture(autouse=True)
def dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("STUDIO_INBOX", str(tmp_path / "inbox"))
    return tmp_path


@pytest.mark.parametrize("span, shots", [(7.4, 1), (7.5, 1), (7.6, 2), (13.3, 2), (15.6, 3), (0.0, 1)])
def test_shots_per_span(span, shots):
    assert studio.shots_for(span) == shots


def test_spans_pad_the_last_card():
    assert studio.spans([0.0, 7.0, 16.0], 24.0, 0.2) == [7.0, 9.0, pytest.approx(8.2)]


def test_pending_skips_pexels_and_cards_with_footage():
    assert studio.pending_cards(["flow", "pexels", "flow", "flow"], {2}) == [0, 3]


def test_shot_map_and_totals():
    shots = studio.shot_map([7.0, 9.0, 8.2], [0, 2])
    assert shots == {0: 1, 2: 2}
    assert studio.total_shots(shots) == 3
    assert studio.credits(3) == 36


def test_fits_within_half_a_second():
    assert studio.fits(24.0, 3) and studio.fits(23.6, 3) and studio.fits(24.5, 3)
    assert not studio.fits(21.0, 3)
    assert studio.shot_length(24.0, 3, even=False) == 8.0
    assert studio.shot_length(21.0, 3, even=True) == 7.0


def test_tokens_are_twelve_hex():
    token = studio.new_token()
    assert studio.TOKEN.fullmatch(token) and token != studio.new_token()


def test_pack_round_trip_and_discard():
    studio.write_pack("20261015-170226-065", {"token": "a" * 12}, "# Shot list")
    assert studio.read_pack("20261015-170226-065")["token"] == "a" * 12
    assert studio.read_markdown("20261015-170226-065") == "# Shot list"
    studio.discard("20261015-170226-065")
    assert studio.read_pack("20261015-170226-065") is None


def test_unsafe_clip_ids_are_refused():
    with pytest.raises(ValueError):
        studio.root("../etc")


def test_have_segments_lists_cards_with_files():
    path = studio.segment_path("20261015-170226-065", 2)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")
    assert studio.have_segments("20261015-170226-065", 4) == {2}


def test_claim_inbox_takes_only_live_tokens_once(dirs):
    inbox = dirs / "inbox"
    inbox.mkdir()
    (inbox / ("a" * 12 + ".mp4")).write_bytes(b"x")
    (inbox / ("b" * 12 + ".mp4")).write_bytes(b"x")
    (inbox / ("a" * 12 + ".mp4.part")).write_bytes(b"x")
    taken = studio.claim_inbox({"a" * 12})
    assert [t for t, _ in taken] == ["a" * 12]
    assert taken[0][1].name.endswith(".taken")
    assert studio.claim_inbox({"a" * 12}) == []


def test_sweep_removes_stale_and_unknown_old_files(dirs):
    inbox = dirs / "inbox"
    inbox.mkdir()
    old = inbox / ("c" * 12 + ".mp4")
    old.write_bytes(b"x")
    past = time.time() - 73 * 3600
    os.utime(old, (past, past))
    fresh = inbox / ("d" * 12 + ".mp4")
    fresh.write_bytes(b"x")
    assert studio.sweep_inbox(set()) == 1
    assert fresh.exists() and not old.exists()


def test_version_for_message():
    wait = {"kind": "studio", "versions": {"a" * 12: {"message_id": 5}, "b" * 12: {"message_id": 9}}}
    assert studio.version_for_message(wait, 9) == "b" * 12
    assert studio.version_for_message(wait, 4) is None
    assert studio.version_for_message({"message_id": 9}, 9) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `shorts-factory/scripts/sf-test tests/test_studio.py -q`
Expected: FAIL with `ImportError: cannot import name 'studio'`

- [ ] **Step 3: Implement**

```python
# shorts-factory/app/studio.py
"""Storyboard Studio packs: the maths and the files behind 🎞 Studio.

Flow's Storyboard Studio makes the pictures. This module decides how many 8s
shots each Flow Card needs (from narration measured before planning), keeps
the pack the dashboard shows, and cuts the one stitched export the human
brings back into per-Card footage. Pure apart from ffmpeg and the filesystem.
The dashboard imports it, so `app.render` (Pillow, edge-tts) is imported
only inside the functions that need it. See
docs/superpowers/specs/2026-10-15-storyboard-studio-pack-design.md.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import secrets
import shutil
import subprocess
import time
from pathlib import Path

SHOT_SECONDS = 8.0
MARGIN = 0.5       # join silence + voice tail inside one shot
TOLERANCE = 0.5    # export length vs shots × 8
TOKEN = re.compile(r"^[a-f0-9]{12}$")
CLIP_ID = re.compile(r"^\d{8}-\d{6}-\d{3}$")


def spans(starts: list[float], total: float, tail_pad: float) -> list[float]:
    """Seconds each Card is on screen; the last one runs past the narration."""
    out = [starts[i + 1] - starts[i] for i in range(len(starts) - 1)]
    out.append(total - starts[-1] + tail_pad)
    return out


def shots_for(span: float) -> int:
    return max(1, math.ceil((span + MARGIN) / SHOT_SECONDS - 1e-9))


def pending_cards(sources: list[str], have: set[int]) -> list[int]:
    """Flow Cards that still need footage from Flow."""
    return [i for i, source in enumerate(sources) if source == "flow" and i not in have]


def shot_map(card_spans: list[float], pending: list[int]) -> dict[int, int]:
    return {i: shots_for(card_spans[i]) for i in pending}


def total_shots(shots: dict[int, int]) -> int:
    return sum(shots.values())


def credits(total: int) -> int:
    return total * int(os.environ.get("FLOW_CREDITS_PER_SHOT", "12"))


def new_token() -> str:
    return secrets.token_hex(6)


def fits(duration: float, total: int) -> bool:
    return abs(duration - total * SHOT_SECONDS) <= TOLERANCE + 1e-9


def shot_length(duration: float, total: int, even: bool) -> float:
    return duration / total if even else SHOT_SECONDS


# --- files -------------------------------------------------------------------

def _base() -> Path:
    return Path(os.environ.get("DATA_DIR", "/data")) / "studio"


def root(clip_id: str) -> Path:
    if not CLIP_ID.fullmatch(clip_id or ""):
        raise ValueError(f"clip id ไม่ถูกต้อง: {clip_id!r}")
    return _base() / clip_id


def segment_path(clip_id: str, card: int) -> Path:
    return root(clip_id) / "segments" / f"c{card:02d}.mp4"


def have_segments(clip_id: str, count: int) -> set[int]:
    return {i for i in range(count) if segment_path(clip_id, i).is_file()}


def write_pack(clip_id: str, pack: dict, markdown: str) -> None:
    where = root(clip_id)
    where.mkdir(parents=True, exist_ok=True)
    for name, text in (("pack.json", json.dumps(pack, ensure_ascii=False, indent=2)),
                       ("script.md", markdown)):
        temporary = where / f"{name}.tmp"
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(where / name)


def read_pack(clip_id: str) -> dict | None:
    try:
        return json.loads((root(clip_id) / "pack.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_markdown(clip_id: str) -> str | None:
    try:
        return (root(clip_id) / "script.md").read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None


def discard(clip_id: str) -> None:
    try:
        shutil.rmtree(root(clip_id), ignore_errors=True)
    except ValueError:
        pass


# --- narration ----------------------------------------------------------------

def say_digest() -> str:
    from app import render
    try:
        return hashlib.sha256(render.SAY_PATH.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


async def prepare_narration(script: dict, locale: str, clip_id: str) -> dict:
    """Speak the Script once, keep the take, and report each Card's span.

    The same single edge-tts call the renderer makes, so the cut points the
    shot counts are planned from are the cut points the clip is rendered with.
    """
    from app import render
    work = root(clip_id) / "tts"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    audio, starts = await render._narration_track(script["cards"], work, locale)
    total = render.audio_seconds(audio)
    meta = {"audio": str(audio), "starts": starts, "total": total,
            "spans": spans(starts, total, render.TAIL_PAD), "say": say_digest()}
    (root(clip_id) / "narration.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def load_narration(clip_id: str) -> tuple[Path, list[float]] | None:
    """The saved take, unless `/say` changed since it was spoken."""
    try:
        meta = json.loads((root(clip_id) / "narration.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    audio = Path(meta["audio"])
    if meta.get("say") != say_digest() or not audio.is_file():
        return None
    return audio, list(meta["starts"])


# --- the export ----------------------------------------------------------------

def duration(path: Path) -> float:
    done = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    try:
        return float(done.stdout.strip())
    except ValueError as exc:
        raise RuntimeError(f"อ่านความยาวไฟล์ไม่ได้: {done.stderr.strip()[-300:]}") from exc


def cut(export: Path, pending: list[int], shots: dict[int, int], clip_id: str,
        shot_len: float) -> dict[int, Path]:
    """One file per pending Card: its consecutive shots, silent, re-encoded.

    Re-encoded, not stream-copied: Flow exports carry a keyframe every 3s, so
    a copy would start each Card on the wrong frame.
    """
    made, offset = {}, 0
    for card in pending:
        count = shots[card]
        dest = segment_path(clip_id, card)
        dest.parent.mkdir(parents=True, exist_ok=True)
        temporary = dest.with_suffix(".part.mp4")
        done = subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{offset * shot_len:.3f}", "-i", str(export),
             "-t", f"{count * shot_len:.3f}", "-an",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", str(temporary)],
            capture_output=True, text=True, timeout=1800,
        )
        if done.returncode != 0:
            temporary.unlink(missing_ok=True)
            raise RuntimeError(f"หั่นคลิปไม่สำเร็จ: {done.stderr.strip()[-400:]}")
        temporary.replace(dest)
        made[card] = dest
        offset += count
    return made


# --- the inbox the Shop API writes into ----------------------------------------

def inbox_dir() -> Path:
    return Path(os.environ.get("STUDIO_INBOX", "/output/studio-inbox"))


def claim_inbox(tokens: set[str]) -> list[tuple[str, Path]]:
    """Exports for live pack versions, renamed so the next tick cannot take them twice."""
    inbox = inbox_dir()
    if not inbox.is_dir():
        return []
    taken = []
    for token in sorted(tokens):
        ready = inbox / f"{token}.mp4"
        if ready.is_file():
            claimed = inbox / f"{token}.mp4.taken"
            ready.replace(claimed)
            taken.append((token, claimed))
    return taken


def sweep_inbox(live: set[str], hours: float = 72) -> int:
    """Delete inbox files nobody will claim: past the wait, whatever their token."""
    inbox = inbox_dir()
    if not inbox.is_dir():
        return 0
    cutoff = time.time() - hours * 3600
    removed = 0
    for path in inbox.iterdir():
        token = path.name.split(".", 1)[0]
        if path.is_file() and path.stat().st_mtime < cutoff and (
                token not in live or path.name.endswith(".part")):
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def version_for_message(wait: dict, message_id: int | None) -> str | None:
    if wait.get("kind") != "studio" or not message_id:
        return None
    for token, version in (wait.get("versions") or {}).items():
        if version.get("message_id") == message_id:
            return token
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `shorts-factory/scripts/sf-test tests/test_studio.py -q`
Expected: 17 passed

- [ ] **Step 5: Commit**

```bash
git add shorts-factory/app/studio.py shorts-factory/tests/test_studio.py
git commit -m "feat(shorts-factory): Studio shot maths, pack files and inbox"
```

---

### Task 3: Cutter and saved narration against real ffmpeg

**Files:**
- Modify: `shorts-factory/tests/test_studio.py` (append)

**Interfaces:**
- Consumes: from Task 2, `studio.cut`, `studio.duration`, `studio.load_narration`, `studio.say_digest`.

- [ ] **Step 1: Write the failing tests**

Append to `shorts-factory/tests/test_studio.py`:

```python
import json as _json
import subprocess


def testsrc(path, seconds):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size=720x1280:rate=24:duration={seconds}",
                    "-f", "lavfi", "-i", f"sine=duration={seconds}", "-shortest",
                    "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(path)],
                   check=True, capture_output=True)
    return path


def has_audio(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
                          "stream=index", "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return bool(out.stdout.strip())


def test_cut_gives_each_card_its_shots_silently(dirs):
    export = testsrc(dirs / "export.mp4", 24)
    assert studio.duration(export) == pytest.approx(24.0, abs=0.05)
    made = studio.cut(export, [0, 2], {0: 1, 2: 2}, "20261015-170226-065", 8.0)
    assert set(made) == {0, 2}
    assert studio.duration(made[0]) == pytest.approx(8.0, abs=0.1)
    assert studio.duration(made[2]) == pytest.approx(16.0, abs=0.1)
    assert not has_audio(made[0])


def test_cut_evenly_splits_the_real_length(dirs):
    export = testsrc(dirs / "short.mp4", 21)
    shot = studio.shot_length(studio.duration(export), 3, even=True)
    made = studio.cut(export, [1], {1: 3}, "20261015-170226-065", shot)
    assert studio.duration(made[1]) == pytest.approx(21.0, abs=0.1)


def test_saved_narration_is_dropped_when_say_changes(dirs, monkeypatch):
    from app import render
    monkeypatch.setattr(render, "SAY_PATH", dirs / "data" / "say.json")
    where = studio.root("20261015-170226-065")
    where.mkdir(parents=True)
    audio = where / "take.wav"
    audio.write_bytes(b"RIFF")
    (where / "narration.json").write_text(_json.dumps(
        {"audio": str(audio), "starts": [0.0, 7.0], "total": 15.0, "spans": [7.0, 8.2],
         "say": studio.say_digest()}))
    assert studio.load_narration("20261015-170226-065") == (audio, [0.0, 7.0])
    render.SAY_PATH.write_text('{"พาส": "พาสะ"}', encoding="utf-8")
    assert studio.load_narration("20261015-170226-065") is None
```

- [ ] **Step 2: Run the tests**

Run: `shorts-factory/scripts/sf-test tests/test_studio.py -q`
Expected: 20 passed. Task 2 already implements these functions; this task adds coverage against real ffmpeg. If any test fails, fix `studio.cut` or `studio.load_narration`, not the test.

- [ ] **Step 3: Commit**

```bash
git add shorts-factory/tests/test_studio.py
git commit -m "test(shorts-factory): Studio cutter and say-aware narration reuse"
```

---

### Task 4: `render.build` takes saved narration and holds studio footage

**Files:**
- Modify: `shorts-factory/app/render.py`: `_segment_over_footage` (around line 394) and `build` (around line 597)
- Test: `shorts-factory/tests/test_studio_render.py`

**Interfaces:**
- Produces:
  - `render.build(script, workdir, supplied=None, locale=..., narration: tuple[Path, list[float]] | None = None, hold: frozenset[int] | set[int] = frozenset()) -> tuple[Path, dict]`
  - `details["cards"][i]["footage_source"]` is one of `"flow-studio"` (i in hold), `"flow"`, `"pexels"`, or `None`
  - `details["narration_reused"]: bool`
  - `render._segment_over_footage(card_png, seconds, clip, out, hold: bool = False)`

- [ ] **Step 1: Write the failing tests**

```python
# shorts-factory/tests/test_studio_render.py
import asyncio
import os
import subprocess

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "42")

from PIL import Image  # noqa: E402

from app import footage, render  # noqa: E402


def clip(path, seconds):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size=720x1280:rate=24:duration={seconds}",
                    "-c:v", "libx264", "-preset", "ultrafast", str(path)], check=True, capture_output=True)
    return path


def tone(path, seconds):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"sine=duration={seconds}", str(path)],
                   check=True, capture_output=True)
    return path


def test_hold_freezes_the_last_frame_instead_of_looping(tmp_path):
    png = tmp_path / "card.png"
    Image.new("RGBA", (render.W, render.H), (0, 0, 0, 0)).save(png)
    out = render._segment_over_footage(png, 3.0, clip(tmp_path / "c.mp4", 1), tmp_path / "s.mp4", hold=True)
    assert render.audio_seconds(out) == __import__("pytest").approx(3.0, abs=0.1)


def test_build_reuses_narration_and_labels_studio_footage(tmp_path, monkeypatch):
    async def no_tts(*args, **kwargs):
        raise AssertionError("narration was supplied; TTS must not run")

    async def no_footage(query, dest):
        return None

    monkeypatch.setattr(render, "_narration_track", no_tts)
    monkeypatch.setattr(footage, "fetch", no_footage)
    monkeypatch.setattr(render, "pick_music", lambda: None)
    script = {"title": "t", "cards": [
        {"lines": ["หนึ่ง"], "narration": "หนึ่ง", "spoken": "หนึ่ง", "query": "x"},
        {"lines": ["สอง"], "narration": "สอง", "spoken": "สอง", "query": "y"}]}
    audio = tone(tmp_path / "n.wav", 4)
    seg = clip(tmp_path / "flow.mp4", 1)
    out, details = asyncio.run(render.build(script, tmp_path / "work", supplied={0: seg},
                                            narration=(audio, [0.0, 2.0]), hold={0}))
    assert out.is_file()
    assert details["narration_reused"] is True
    assert details["cards"][0]["footage_source"] == "flow-studio"
    assert details["cards"][1]["footage_source"] is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `shorts-factory/scripts/sf-test tests/test_studio_render.py -q`
Expected: FAIL with `TypeError: _segment_over_footage() got an unexpected keyword argument 'hold'`

- [ ] **Step 3: Implement.** Replace `_segment_over_footage` in `render.py`:

```python
def _segment_over_footage(card_png: Path, seconds: float, clip: Path, out: Path,
                          hold: bool = False) -> Path:
    """Stock footage, held back by a scrim, with the card laid over it.

    No zoompan here — the footage already moves. `-stream_loop -1` covers a
    Card that outlasts the clip. Studio footage (`hold`) is cut to the Card
    from a longer shot and is never looped: a loop visibly jumps back to the
    shot's first frame, so the last frame is held instead. Video only.
    """
    _run([
        "ffmpeg", "-y",
        *([] if hold else ["-stream_loop", "-1"]), "-i", str(clip),
        "-loop", "1", "-i", str(card_png),
        "-filter_complex",
        (
            "[0:v]"
            + (f"tpad=stop_mode=clone:stop_duration={seconds:.3f}," if hold else "")
            + f"scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},fps={ZOOM_FPS},"
            f"drawbox=x=0:y=0:w=iw:h=ih:color={SCRIM}:t=fill[bg];"
            "[bg][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
        ),
        "-map", "[v]", "-t", f"{seconds:.3f}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-r", str(ZOOM_FPS), "-an", str(out),
    ])
    return out
```

In `build`, change the signature and the start of the body:

```python
async def build(script: dict, workdir: Path,
                supplied: dict[int, Path] | None = None,
                locale: str = locales.DEFAULT,
                narration: tuple[Path, list[float]] | None = None,
                hold: frozenset[int] | set[int] = frozenset()) -> tuple[Path, dict]:
    """Script → mp4, plus the parameters it was actually built with.

    The second return value is what the Manifest records: the workdir is wiped
    after every render, so anything not handed back here is gone for good.

    `supplied` maps a Card index to Footage a human generated in Google Flow
    (docs/adr/0005). Those Cards skip the Pexels search entirely; the rest are
    unaffected. `narration` is a take already spoken for a Storyboard Studio
    pack: reusing it keeps the cut points the shots were planned from. `hold`
    names the supplied Cards that come from that pack, whose footage is held
    on its last frame rather than looped.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    cards = script["cards"]
    supplied = {i: Path(p) for i, p in (supplied or {}).items() if Path(p).is_file()}

    async def given() -> tuple[Path, list[float]]:
        return narration

    narration_result, clips = await asyncio.gather(
        given() if narration else _narration_track(cards, workdir, locale),
        asyncio.gather(
            *(_ready(supplied[i]) if i in supplied
              else footage.fetch(c.get("query", ""), workdir / f"broll{i:02d}.mp4")
              for i, c in enumerate(cards))
        ),
    )
    audio, starts = narration_result
```

In the segment loop, change the footage branch to:

```python
        if clip:
            segments.append(_segment_over_footage(png, seconds, clip, out, hold=i in hold))
```

In `details`, add `"narration_reused": bool(narration),` after `"bgm"`. Change the `footage_source` expression to:

```python
             "footage_source": (("flow-studio" if i in hold else "flow") if i in supplied
                                else "pexels") if clip_path else None,
```

- [ ] **Step 4: Run the new tests and the existing render tests**

Run: `shorts-factory/scripts/sf-test tests/test_studio_render.py tests/test_shorts_factory.py -q -k "studio or footage or build or segment" --deselect tests/test_shorts_factory.py::test_narration_is_one_take_with_a_start_per_card`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add shorts-factory/app/render.py shorts-factory/tests/test_studio_render.py
git commit -m "feat(shorts-factory): render reuses a saved take and holds studio footage"
```

---

### Task 5: Storyboard studio planning and `script.md`

**Files:**
- Modify: `shorts-factory/app/storyboard.py`
- Test: `shorts-factory/tests/test_studio_storyboard.py`

**Interfaces:**
- Consumes: `script._say`, `script._client`, `script._parse` (already imported in storyboard.py)
- Produces:
  - `validate(data, ratio, scenes_wanted=None, choice=AUTO, max_scenes=MAX_SCENES)` (new kwarg)
  - `plan(brief, ratio, cards=None, choice=AUTO, character="", *, scenes_wanted=None, max_scenes=MAX_SCENES, fixed_tag="", script_rule=None, finish=None)`
  - `async for_studio(script, pending, shots, choice=AUTO, character="", fixed_tag="", topic="") -> dict`: the board, with `scene["card"]` set
  - `studio_markdown(board: dict, tag: str) -> str`
  - `portrait_prompt(locked: str) -> str`
  - `async english_character(thai: str) -> str`
  - Constants: `STUDIO_MAX_SHOTS = 24`, `AUTO_TAG = "@Lead"`

- [ ] **Step 1: Write the failing tests**

```python
# shorts-factory/tests/test_studio_storyboard.py
import asyncio
import json
import os

os.environ.setdefault("MIMO_API_KEY", "test-key")
os.environ.setdefault("MIMO_BASE_URL", "https://example.invalid/v1")

import pytest  # noqa: E402

from app import storyboard  # noqa: E402

LOCK = "the same 28-year-old Thai woman with a short black bob and round glasses"
SCRIPT = {"title": "ดอกเบี้ย 2.60%", "cards": [
    {"lines": ["ดอกเบี้ย 2.60%"], "narration": "สินเชื่อบ้านดอกเบี้ย", "query": "house key"},
    {"lines": ["ธอส."], "narration": "โครงการนี้คือ", "query": "bank"},
    {"lines": ["สรุป"], "narration": "สรุปนะ", "query": "couple"}]}


def board(n, tag=LOCK):
    return {"overview": {"title": "ชื่อ", "mood_tone_progression": "อุ่น", "target_audience": "คนทำงาน",
                         "master_character": {"name": "Nong", "age": 28, "ethnicity": "Thai",
                                              "appearance": "bob", "outfit": "linen",
                                              "locked_prompt_tag": "anything the model wrote"}},
            "scenes": [{"scene_number": i + 1, "camera": "กล้อง", "scene_description": "ฉาก",
                        "visual_details": "รายละเอียด", "scene_mood_note": "อารมณ์",
                        "sound_verbatim": "", "on_screen_text": "",
                        "image_gen_prompt": f"{tag} holds a key, 9:16, no text, no watermark, no UI, no split-screen",
                        "motion": "slow push in"} for i in range(n)]}


def fake_model(monkeypatch, replies):
    calls = []

    async def say(client, messages, temperature, budget):
        calls.append(messages)
        return json.dumps(replies.pop(0))

    monkeypatch.setattr(storyboard, "_say", say)
    monkeypatch.setattr(storyboard, "_client", lambda: None)
    return calls


def test_for_studio_pins_the_tag_and_maps_shots_to_cards(monkeypatch):
    calls = fake_model(monkeypatch, [board(3)])
    result = asyncio.run(storyboard.for_studio(SCRIPT, [0, 2], {0: 1, 2: 2},
                                               choice=storyboard.OWN, character=LOCK, fixed_tag=LOCK))
    assert [s["card"] for s in result["scenes"]] == [0, 2, 2]
    assert result["scenes"][1]["sound_verbatim"] == "สรุปนะ"
    assert result["overview"]["master_character"]["locked_prompt_tag"] == LOCK
    brief = calls[0][1]["content"]
    assert "2 shot" in brief and "ธอส." not in brief


def test_a_board_with_the_wrong_shot_count_is_retried(monkeypatch):
    calls = fake_model(monkeypatch, [board(2), board(3)])
    asyncio.run(storyboard.for_studio(SCRIPT, [0, 2], {0: 1, 2: 2},
                                      choice=storyboard.OWN, character=LOCK, fixed_tag=LOCK))
    assert len(calls) == 2 and "3" in calls[1][-1]["content"]


def test_markdown_is_english_with_tag_lock_and_no_narration(monkeypatch):
    fake_model(monkeypatch, [board(3)])
    result = asyncio.run(storyboard.for_studio(SCRIPT, [0, 2], {0: 1, 2: 2},
                                               choice=storyboard.OWN, character=LOCK, fixed_tag=LOCK))
    text = storyboard.studio_markdown(result, "@Nong")
    assert not storyboard.THAI.search(text)
    assert "9:16" in text and "8 seconds" in text and "No dialogue" in text
    assert text.count("[SCENE ") == 3
    for block in text.split("[SCENE ")[1:]:
        assert "@Nong" in block and LOCK in block
    assert "CHARACTERS: @Nong — " + LOCK in text


def test_markdown_without_a_character_has_no_tag(monkeypatch):
    plain = board(1, tag="A brass house key on a desk")
    plain["overview"]["master_character"] = None
    fake_model(monkeypatch, [plain])
    result = asyncio.run(storyboard.for_studio(SCRIPT, [1], {1: 1}, choice=storyboard.NONE))
    text = storyboard.studio_markdown(result, "")
    assert "CHARACTERS" not in text and "@" not in text


def test_english_character_rejects_thai(monkeypatch):
    replies = ["ผู้หญิง", "the same 30-year-old Thai man with a buzz cut"]

    async def say(client, messages, temperature, budget):
        return replies.pop(0)

    monkeypatch.setattr(storyboard, "_say", say)
    monkeypatch.setattr(storyboard, "_client", lambda: None)
    assert asyncio.run(storyboard.english_character("ผู้ชายไทย 30 ปี")).startswith("the same 30")


def test_portrait_prompt():
    text = storyboard.portrait_prompt(LOCK)
    assert LOCK in text and "9:16" in text and "no text" in text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `shorts-factory/scripts/sf-test tests/test_studio_storyboard.py -q`
Expected: FAIL with `AttributeError: module 'app.storyboard' has no attribute 'for_studio'`

- [ ] **Step 3: Implement** in `storyboard.py`.

Change `_system` to accept a rule override:

```python
def _system(ratio: str, shorts: bool, choice: str = AUTO, script_rule: str | None = None) -> str:
    return SYSTEM_PROMPT.format(
        ratio=ratio,
        negatives=NEGATIVES,
        layout=SHORTS_LAYOUT if shorts else LONG_LAYOUT,
        script_rule=script_rule or (SHORTS_SCRIPT_RULE if shorts else LONG_SCRIPT_RULE),
        character_rule=CHARACTER_RULES.get(choice, CHARACTER_AUTO),
    )
```

In `validate`, add the parameter `max_scenes: int = MAX_SCENES` and replace the range check with:

```python
    if not MIN_SCENES <= len(scenes) <= max_scenes:
        raise ScriptError(f"ต้องมี {MIN_SCENES}-{max_scenes} ฉาก แต่ได้ {len(scenes)}")
```

Also change `MIN_SCENES, MAX_SCENES = 2, 8` to `MIN_SCENES, MAX_SCENES = 1, 8`. A one-Card studio pack (only the hook) is a 1-shot board. The long-form path still defaults to 4 scenes.

Replace `plan` with:

```python
async def plan(brief: str, ratio: str, cards: list[dict] | None = None,
               choice: str = AUTO, character: str = "", *,
               scenes_wanted: int | None = None, max_scenes: int = MAX_SCENES,
               fixed_tag: str = "", script_rule: str | None = None,
               finish=None) -> dict:
    """A brief (or a Script) → a validated storyboard. One retry, told what broke.

    `fixed_tag` is a library character's English, translated once and reused
    across clips: it is written over whatever the model named the character,
    so validation checks every prompt against *that* text, not the model's.
    """
    if choice not in CHOICES:
        choice = AUTO
    messages = [
        {"role": "system", "content": _system(ratio, shorts=cards is not None, choice=choice,
                                              script_rule=script_rule)},
        {"role": "user", "content": _with_character(brief, choice, character)},
    ]
    client = _client()
    wanted = scenes_wanted if scenes_wanted is not None else (len(cards) if cards else None)
    last: Exception | None = None
    for attempt in range(2):
        raw = await _say(client, messages, temperature=0.8, budget=BUDGET_SECONDS)
        try:
            data = _parse(raw)
            if fixed_tag and isinstance(data.get("overview"), dict):
                person = data["overview"].get("master_character") or {}
                if isinstance(person, dict):
                    person["locked_prompt_tag"] = fixed_tag
                    data["overview"]["master_character"] = person
            data = validate(data, ratio, wanted, choice, max_scenes=max_scenes)
            if finish:
                return finish(data)
            return lock_to_script(data, cards) if cards else data
        except ScriptError as exc:
            logger.warning("storyboard ผิดกติกา: %s", exc)
            last = exc
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content": f"ผิดกติกา: {exc} — ส่ง JSON ใหม่ให้ถูกกติกา"},
            ]
    raise ScriptError(str(last))
```

Append the studio section after `as_script`:

```python
# --- Storyboard Studio packs (docs/superpowers/specs/2026-10-15-storyboard-studio-pack-design.md)

STUDIO_MAX_SHOTS = 24
AUTO_TAG = "@Lead"
STUDIO_SCRIPT_RULE = (
    "The shots are given below and are fixed: write exactly one scene per shot, in "
    "the same order and the same number. Shots that belong to the same Card show the "
    "same beat from another angle, a closer framing or the next action — never a new "
    "story beat. Every shot is one continuous 8-second take. Leave `sound_verbatim` "
    "and `on_screen_text` empty; they are filled in from the Script.")
STUDIO_STYLE = (
    "STYLE: Photorealistic cinematic, vertical 9:16, one shot per scene, each shot exactly 8 seconds.\n"
    "No dialogue, no voiceover, no on-screen text, no subtitles, no watermark, no UI, no split-screen.\n"
    "Keep clean negative space in the centre of the frame for captions added later.")
ENGLISH_CHARACTER_PROMPT = (
    "Translate the character description into ONE English noun phrase that starts with "
    "\"the same\" and names age, ethnicity, hair, accessories and clothing colours, e.g. "
    "\"the same 28-year-old Thai woman with a short black bob, round glasses, and a beige "
    "linen shirt\". Keep every detail given; invent only what is missing. Reply with the "
    "phrase only — no quotes, no Thai, no real people or brands.")


def _brief_for_studio(script: dict, pending: list[int], shots: dict[int, int],
                      topic: str = "") -> str:
    parts = [f"หัวข้อคลิป: {script['title']}", ""]
    if topic and topic.strip() and topic.strip() != script["title"]:
        parts = [f"หัวข้อที่คนพิมพ์มาเอง: {topic.strip()} (ใช้เฉพาะรายละเอียดภาพ)", ""] + parts
    for card in pending:
        c = script["cards"][card]
        parts += [
            f"การ์ด {card + 1}: {shots[card]} shot",
            f"  เรื่องที่พูดในการ์ดนี้ (ห้ามใส่ลงภาพเป็นตัวหนังสือ): {c['narration']}",
            f"  ภาพที่คิดไว้คร่าวๆ: {c.get('query', '-')}",
        ]
    return "\n".join(parts)


def _assign_cards(data: dict, script: dict, pending: list[int], shots: dict[int, int]) -> dict:
    order = [card for card in pending for _ in range(shots[card])]
    for scene, card in zip(data["scenes"], order):
        scene["card"] = card
        scene["sound_verbatim"] = script["cards"][card]["narration"]
        scene["on_screen_text"] = " ".join(script["cards"][card]["lines"])
    return data


async def for_studio(script: dict, pending: list[int], shots: dict[int, int],
                     choice: str = AUTO, character: str = "", fixed_tag: str = "",
                     topic: str = "") -> dict:
    """A shot list for the Flow Cards only, one scene per 8s shot."""
    total = sum(shots[c] for c in pending)
    return await plan(
        _brief_for_studio(script, pending, shots, "" if choice == NONE else topic),
        SHORTS_RATIO, cards=[script["cards"][c] for c in pending],
        choice=choice, character=character,
        scenes_wanted=total, max_scenes=STUDIO_MAX_SHOTS, fixed_tag=fixed_tag,
        script_rule=STUDIO_SCRIPT_RULE,
        finish=lambda data: _assign_cards(data, script, pending, shots))


def portrait_prompt(locked: str) -> str:
    return (f"A photorealistic 9:16 portrait of {locked}, neutral studio lighting, "
            f"plain background, full body visible, {NEGATIVES}")


def studio_markdown(board: dict, tag: str) -> str:
    """What Storyboard Studio reads. English only, and nothing anyone says:
    Thai narration in here could make Veo animate speech."""
    person = board["overview"].get("master_character") or None
    locked = (person or {}).get("locked_prompt_tag", "")
    lines = [f"# Shot list ({len(board['scenes'])} shots x 8 seconds)", "", STUDIO_STYLE, ""]
    if person and tag:
        lines += [f"CHARACTERS: {tag} — {locked}", ""]
    for i, scene in enumerate(board["scenes"], 1):
        prompt = scene["image_gen_prompt"]
        lines += [f"[SCENE {i}]",
                  f"{tag}: {prompt}" if person and tag else prompt,
                  f"CAMERA: {scene['motion']}, 8 seconds.", ""]
    return "\n".join(lines).rstrip() + "\n"


async def english_character(thai: str) -> str:
    """A library character's Thai description → its English lock. One retry."""
    messages = [{"role": "system", "content": ENGLISH_CHARACTER_PROMPT},
                {"role": "user", "content": thai}]
    client = _client()
    for attempt in range(2):
        raw = (await _say(client, messages, temperature=0.3, budget=BUDGET_SECONDS)).strip().strip('"')
        if raw and not THAI.search(raw):
            return raw[:300]
        messages += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": "ต้องเป็นภาษาอังกฤษล้วน วลีเดียว"}]
    raise ScriptError("แปลตัวละครเป็นภาษาอังกฤษไม่สำเร็จ")
```

- [ ] **Step 4: Run the new tests and the existing storyboard tests**

Run: `shorts-factory/scripts/sf-test tests/test_studio_storyboard.py tests/test_shorts_factory.py -q -k "storyboard or studio"`
Expected: all pass. If an existing test asserted `MIN_SCENES == 2`, update it to `1` and note in the commit message why: a one-Card studio pack is a 1-shot board.

- [ ] **Step 5: Commit**

```bash
git add shorts-factory/app/storyboard.py shorts-factory/tests/test_studio_storyboard.py shorts-factory/tests/test_shorts_factory.py
git commit -m "feat(shorts-factory): Storyboard Studio shot list and script.md"
```

---

### Task 6: Shop API upload inbox

**Files:**
- Modify: `shorts-factory/app/shop_api.py`: add a route inside `create_app`, after the `/shop/api/jobs/{job_id}/scenes/{scene_id}/accept` route
- Test: `shorts-factory/tests/test_shop_api.py` (append)

**Interfaces:**
- Produces: `POST /shop/api/studio-inbox/{token}` (multipart field `file`) → `201 {"ok": true, "bytes": int}`. Errors are 422 with `detail`. The route writes `<STUDIO_INBOX>/<token>.mp4`.

- [ ] **Step 1: Write the failing tests** (append):

```python
MP4_HEAD = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 100


def test_studio_inbox_accepts_an_mp4_for_a_token(client, tmp_path, monkeypatch):
    headers = browser(client)
    token = "a1b2c3d4e5f6"
    reply = client.post(f"/shop/api/studio-inbox/{token}", headers=headers,
                        files={"file": ("x.mp4", io.BytesIO(MP4_HEAD), "video/mp4")})
    assert reply.status_code == 201
    inbox = tmp_path / "inbox"
    assert (inbox / f"{token}.mp4").read_bytes() == MP4_HEAD
    assert not list(inbox.glob("*.part"))


def test_studio_inbox_refuses_bad_token_bad_media_and_no_csrf(client, tmp_path):
    headers = browser(client)
    files = {"file": ("x.mp4", io.BytesIO(MP4_HEAD), "video/mp4")}
    assert client.post("/shop/api/studio-inbox/../../etc", headers=headers, files=files).status_code in (404, 422)
    assert client.post("/shop/api/studio-inbox/ZZZZZZZZZZZZ", headers=headers, files=files).status_code == 422
    assert client.post("/shop/api/studio-inbox/a1b2c3d4e5f6", headers=headers,
                       files={"file": ("x.mp4", io.BytesIO(b"not a video at all"), "video/mp4")}).status_code == 422
    assert client.post("/shop/api/studio-inbox/a1b2c3d4e5f6",
                       files={"file": ("x.mp4", io.BytesIO(MP4_HEAD), "video/mp4")}).status_code == 403
    assert not (tmp_path / "inbox" / "a1b2c3d4e5f6.mp4").exists()
```

Change the `client` fixture at the top of the file to also set the inbox. Add one line:

```python
@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_AUTOMATION_TOKEN", "scoped-secret")
    monkeypatch.setenv("STUDIO_INBOX", str(tmp_path / "inbox"))
    return TestClient(create_app(tmp_path))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `shorts-factory/scripts/sf-test tests/test_shop_api.py -q -k studio_inbox`
Expected: FAIL. The first assertion gets 404 instead of 201.

- [ ] **Step 3: Implement.** In `shop_api.py`, add `import re` at the top, and after `REPORT_LIMIT` add:

```python
STUDIO_TOKEN = re.compile(r"^[a-f0-9]{12}$")
STUDIO_LIMIT = 100 * 1024 * 1024
```

Inside `create_app`, after the scene `accept` route, add:

```python
    studio_inbox = Path(os.environ.get("STUDIO_INBOX", "/output/studio-inbox"))

    @app.post("/shop/api/studio-inbox/{token}", status_code=201)
    def studio_upload(token: str, file: UploadFile = File(...)):
        """A Storyboard Studio export for the bot to pick up (docs/adr/0016).

        No decoding here (see the module docstring): the bot probes the file
        when it claims it. This route checks the token's shape, the MP4/MOV
        `ftyp` box and the size, and renames into place so the bot never sees
        half a file.
        """
        if not STUDIO_TOKEN.fullmatch(token):
            raise Invalid("token ไม่ถูกต้อง")
        head = file.file.read(12)
        if len(head) < 12 or head[4:8] != b"ftyp":
            raise Invalid("ต้องเป็นไฟล์ MP4/MOV ที่ export จาก Flow")
        studio_inbox.mkdir(parents=True, exist_ok=True)
        part = studio_inbox / f"{token}.mp4.part"
        written = len(head)
        with part.open("wb") as out:
            out.write(head)
            while chunk := file.file.read(1 << 20):
                written += len(chunk)
                if written > STUDIO_LIMIT:
                    break
                out.write(chunk)
        if written > STUDIO_LIMIT:
            part.unlink(missing_ok=True)
            raise Invalid("ไฟล์ใหญ่เกิน 100 MiB")
        part.replace(studio_inbox / f"{token}.mp4")
        return {"ok": True, "bytes": written}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `shorts-factory/scripts/sf-test tests/test_shop_api.py -q`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add shorts-factory/app/shop_api.py shorts-factory/tests/test_shop_api.py
git commit -m "feat(shorts-factory): Shop API inbox for Storyboard Studio exports"
```

---

### Task 7: 🎞 Studio in the bot: pack, toggles, character

**Files:**
- Modify: `shorts-factory/app/main.py`
- Test: `shorts-factory/tests/test_studio_bot.py`

**Interfaces:**
- Consumes:
  - from Task 1: `characters.default_for`, `default_sources`, `get`, `stored`, `cached_english`, `remember_english`
  - from Task 2: `studio.prepare_narration`, `have_segments`, `pending_cards`, `shot_map`, `total_shots`, `credits`, `new_token`, `write_pack`
  - from Task 5: `storyboard.for_studio`, `studio_markdown`, `portrait_prompt`, `english_character`, `AUTO_TAG`
- Produces:
  - in `main.py`: `STUDIO_CB = "studio"`, `on_studio(client, state)`, `publish_pack(client, state)`, `studio_keyboard(wait) -> dict`, `on_studio_callback(client, state, data)`, `send_document(client, path, caption="", **extra)`, `pack_url(clip_id) -> str`, `async render_studio(client, state, clip_id)` (filled in by Task 8; here a stub that Task 8 replaces)
  - `clip_wait` for studio:
    - identity: `kind: "studio"`, `clip_id`, `script`, `topic`, `locale`, `spans` (from `prepare_narration`)
    - choices: `choice` (a library id, `"auto"` or `"none"`), `sources` (list)
    - `versions`: `{token: {"message_id", "pending", "shots": {"0": 1}}}`
    - bookkeeping: `busy`, `created_at`, `uneven: {}`

- [ ] **Step 1: Write the failing tests**

```python
# shorts-factory/tests/test_studio_bot.py
import asyncio
import json
import os
import pathlib

os.environ.setdefault("TELEGRAM_BOT_TOKEN", "test-token")
os.environ.setdefault("TELEGRAM_CHAT_ID", "42")
os.environ.setdefault("MIMO_API_KEY", "test-key")
os.environ.setdefault("MIMO_BASE_URL", "https://example.invalid/v1")

import pytest  # noqa: E402

from app import characters, main, storyboard, studio  # noqa: E402

CLIP = "20261015-170226-065"
LOCK = "the same 28-year-old Thai woman with a short black bob"
SPAWNED = []


def run(coro):
    """Run a handler, then everything it spawned, in order (spawn is patched)."""
    async def go():
        await coro
        while SPAWNED:
            await SPAWNED.pop(0)
    asyncio.run(go())


def a_script(n=3):
    return {"title": "หัวข้อ", "description": "", "hashtags": [], "cards": [
        {"lines": [f"การ์ด {i}"], "narration": f"พูด {i}", "spoken": f"พูด {i}", "query": "q"}
        for i in range(n)]}


@pytest.fixture
def bot(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("STUDIO_INBOX", str(tmp_path / "inbox"))
    monkeypatch.setenv("SHOP_PUBLIC_URL", "https://nas.example")
    (tmp_path / "config").mkdir()
    sent = []

    async def say(client, text, **extra):
        sent.append(("say", text, extra))
        return {"message_id": 100 + len(sent)}

    async def send_document(client, path, caption="", **extra):
        sent.append(("doc", pathlib.Path(path).read_text(encoding="utf-8"), extra))
        return {"message_id": 100 + len(sent)}

    async def close(*args, **kwargs):
        return None

    async def narration(script, locale, clip_id):
        return {"audio": "x", "starts": [0.0, 7.0, 16.0], "total": 24.0,
                "spans": [7.0, 9.0, 8.2], "say": ""}

    async def board(script, pending, shots, **kwargs):
        sent.append(("board", kwargs, pending))
        scenes = [{"card": c, "image_gen_prompt": f"{LOCK} at a desk, 9:16, no text",
                   "motion": "slow push in", "sound_verbatim": script["cards"][c]["narration"]}
                  for c in pending for _ in range(shots[c])]
        return {"overview": {"title": "t", "master_character": {"locked_prompt_tag": LOCK}},
                "scenes": scenes, "ratio": "9:16"}

    monkeypatch.setattr(main, "say", say)
    monkeypatch.setattr(main, "send_document", send_document)
    monkeypatch.setattr(main, "close_prompt", close)
    monkeypatch.setattr(main, "save_state", lambda state: None)
    SPAWNED.clear()
    monkeypatch.setattr(main, "spawn", lambda coro, label: SPAWNED.append(coro))
    monkeypatch.setattr(studio, "prepare_narration", narration)
    monkeypatch.setattr(storyboard, "for_studio", board)
    return sent


def review_state():
    return {"mode": "review", "script": a_script(), "clip_id": CLIP, "topic": "หัวข้อ",
            "locale": "th", "message_id": 9}


def test_studio_button_builds_a_hook_pack_and_frees_the_bot(bot):
    state = review_state()
    run(main.on_studio(None, state))
    wait = state["clip_wait"]
    assert state["mode"] == "idle" and wait["kind"] == "studio"
    assert wait["sources"] == ["flow", "pexels", "pexels"]
    (token, version), = wait["versions"].items()
    assert version["pending"] == [0] and version["shots"] == {"0": 1}
    pack = studio.read_pack(CLIP)
    assert pack["token"] == token and pack["total_shots"] == 1 and pack["credits"] == 12
    doc = next(item for item in bot if item[0] == "doc")
    assert "[SCENE 1]" in doc[1] and "@Lead" in doc[1]
    message = next(item for item in bot if item[0] == "say" and "Studio pack" in item[1])
    assert "https://nas.example/storyboard/" + CLIP in message[1]


def test_toggling_a_card_makes_a_new_version(bot):
    state = review_state()
    run(main.on_studio(None, state))
    run(main.on_studio_callback(None, state, f"stt:{CLIP}:1"))
    wait = state["clip_wait"]
    assert wait["sources"] == ["flow", "flow", "pexels"]
    newest = studio.read_pack(CLIP)
    assert newest["pending"] == [0, 1] and newest["shots"] == {"0": 1, "1": 2}
    assert len(wait["versions"]) == 2


def test_all_pexels_renders_without_a_pack(bot, monkeypatch):
    rendered = []

    async def fake_render(client, state, clip_id):
        rendered.append(clip_id)

    monkeypatch.setattr(main, "render_studio", fake_render)
    state = review_state()
    run(main.on_studio(None, state))
    run(main.on_studio_callback(None, state, f"stp:{CLIP}"))
    assert rendered == [CLIP] and state["clip_wait"]["sources"] == ["pexels"] * 3


def test_library_default_character_is_used_and_translated_once(bot, monkeypatch, tmp_path):
    characters.save({"characters": [{"id": "nong", "tag": "@Nong", "thai": "ผู้หญิงไทย",
                                      "english": "", "flow_ready": True}],
                     "defaults": {"th": "nong"}, "footage": "hook"})
    calls = []

    async def english(thai):
        calls.append(thai)
        return LOCK

    monkeypatch.setattr(storyboard, "english_character", english)
    state = review_state()
    run(main.on_studio(None, state))
    run(main.on_studio_callback(None, state, f"stt:{CLIP}:2"))
    assert calls == ["ผู้หญิงไทย"]
    boards = [item for item in bot if item[0] == "board"]
    assert boards[0][1]["fixed_tag"] == LOCK and boards[0][1]["choice"] == storyboard.OWN
    pack = studio.read_pack(CLIP)
    assert pack["character"]["tag"] == "@Nong" and pack["character"]["flow_ready"] is True


def test_switching_character_to_none(bot):
    state = review_state()
    run(main.on_studio(None, state))
    run(main.on_studio_callback(None, state, f"stc:{CLIP}:none"))
    assert state["clip_wait"]["choice"] == "none"
    assert [item for item in bot if item[0] == "board"][-1][1]["choice"] == storyboard.NONE


def test_stale_callback_is_refused(bot):
    state = review_state()
    run(main.on_studio(None, state))
    run(main.on_studio_callback(None, state, "stt:20200101-000000-000:0"))
    assert any("เก่าแล้ว" in item[1] for item in bot if item[0] == "say")


def test_shorten_returns_the_script_to_review(bot):
    state = review_state()
    run(main.on_studio(None, state))
    run(main.on_studio_callback(None, state, f"stx:{CLIP}"))
    assert state["mode"] == "review" and "clip_wait" not in state
    assert any("การ์ด 2" in item[1] for item in bot if item[0] == "say")


def test_review_keyboard_offers_studio():
    flat = [b["callback_data"] for row in main.REVIEW_KEYBOARD["inline_keyboard"] for b in row]
    assert main.STUDIO_CB in flat
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `shorts-factory/scripts/sf-test tests/test_studio_bot.py -q`
Expected: FAIL with `AttributeError: module 'app.main' has no attribute 'on_studio'`

- [ ] **Step 3: Implement in `main.py`.**

(a) Imports: add `characters` and `studio` to the `from app import ...` line at the top of `main.py`.

(b) Constants, next to `STORYBOARD_CB = "storyboard"` (around line 50):

```python
# 🎞 on a Script: a Storyboard Studio pack for the Cards marked Flow
# (docs/adr/0016). Callbacks carry the clip id, so a stale pack message is
# recognised rather than acted on.
STUDIO_CB = "studio"
STUDIO_PREFIXES = ("stt:", "stc:", "stp:", "stx:", "ste:", "str:")
```

(c) In `REVIEW_KEYBOARD`, change the second row to three buttons:

```python
        [
            {"text": "🎞 Studio (Flow)", "callback_data": STUDIO_CB},
            {"text": "📋 prompt ทำ storyboard", "callback_data": STORYBOARD_CB},
            {"text": "🗑 ทิ้ง", "callback_data": DISCARD_CB},
        ],
```

(d) After `send_video` (around line 330), add:

```python
async def send_document(client: httpx.AsyncClient, path: Path, caption: str = "", **extra) -> dict | None:
    return await _bot(client).send_document(path, caption, **extra)
```

(e) Add the section below after `drop_clip_wait` (around line 1224):

```python
# --- Storyboard Studio packs (docs/adr/0016) ----------------------------------

def pack_url(clip_id: str) -> str:
    base = os.environ.get("SHOP_PUBLIC_URL", "").rstrip("/")
    return f"{base}/storyboard/{clip_id}" if base else f"/storyboard/{clip_id} บน dashboard"


def _studio_wait(state: dict, clip_id: str) -> dict | None:
    wait = state.get("clip_wait") or {}
    if wait.get("kind") == "studio" and wait.get("clip_id") == clip_id:
        return wait
    return None


def studio_keyboard(wait: dict) -> dict:
    clip_id = wait["clip_id"]
    toggles = [{"text": f"{i + 1} {'🎬' if s == characters.FLOW else '🖼'}",
                "callback_data": f"stt:{clip_id}:{i}"} for i, s in enumerate(wait["sources"])]
    rows = [toggles[i:i + 3] for i in range(0, len(toggles), 3)]
    people = [{"text": f"{c['tag']}{' ✓' if wait['choice'] == c['id'] else ''}",
               "callback_data": f"stc:{clip_id}:{c['id']}"}
              for c in characters.stored()["characters"]]
    people += [{"text": f"🤖 แต่งใหม่{' ✓' if wait['choice'] == 'auto' else ''}",
                "callback_data": f"stc:{clip_id}:auto"},
               {"text": f"🚫 ไม่มีคน{' ✓' if wait['choice'] == 'none' else ''}",
                "callback_data": f"stc:{clip_id}:none"}]
    rows += [people[i:i + 3] for i in range(0, len(people), 3)]
    rows.append([{"text": "✅ Pexels ทั้งหมด — render เลย", "callback_data": f"stp:{clip_id}"},
                 {"text": "✂️ ย่อการ์ดยาว", "callback_data": f"stx:{clip_id}"}])
    return {"inline_keyboard": rows}


async def _character_for(choice: str) -> tuple[str, str, str, dict | None]:
    """(storyboard choice, character text, fixed English, pack profile)."""
    if choice == "none":
        return storyboard.NONE, "", "", None
    person = characters.get(choice) if choice not in ("auto", "") else None
    if not person:
        return storyboard.AUTO, "", "", {"choice": "auto", "id": "", "tag": storyboard.AUTO_TAG,
                                        "flow_ready": False}
    english = characters.cached_english(person)
    if not english:
        english = await storyboard.english_character(person["thai"])
        characters.remember_english(person, english)
    return storyboard.OWN, english, english, {
        "choice": person["id"], "id": person["id"], "tag": person["tag"], "locked": english,
        "flow_ready": person["flow_ready"], "portrait": storyboard.portrait_prompt(english)}


async def on_studio(client: httpx.AsyncClient, state: dict) -> None:
    """🎞 pressed: speak the Script once, then publish the first pack.

    Mirrors 🎨: the review closes and the bot goes idle, with everything the
    clip needs snapshotted into `clip_wait`. A failure re-posts the Script so
    its buttons come back.
    """
    script = state["script"]
    clip_id = state.get("clip_id")
    live = state.get("clip_wait") or {}
    if live.get("kind") == "studio" and live.get("clip_id") != clip_id:
        # Same rule as 🎨's one Parked Clip: a second pack would orphan credits
        # already spent in Flow on the first. The Script stays in review.
        await say(client, f"ยังมี Studio pack ค้างอยู่: {live['script']['title']}\n"
                          "ส่งคลิปของอันนั้นก่อน (หรือรอหมดอายุ) แล้วค่อยกด 🎞 อันนี้")
        return
    await close_prompt(client, state.get("message_id"),
                       f"🎞 {script['title']} — กำลังอัดเสียงและวาง shot")
    state.update(mode="writing", message_id=None)
    save_state(state)
    locale = state.get("locale", locales.DEFAULT)
    try:
        meta = await studio.prepare_narration(script, locale, clip_id)
    except Exception as exc:
        logger.exception("studio narration failed")
        sent = await say(client, format_script(script), reply_markup=REVIEW_KEYBOARD)
        st.to_review(state, message_id=(sent or {}).get("message_id"))
        save_state(state)
        await say(client, f"อัดเสียงสำหรับ Studio ไม่สำเร็จ: {exc}")
        return
    state["clip_wait"] = {
        "kind": "studio", "clip_id": clip_id, "script": script,
        "topic": state.get("topic"), "locale": locale, "spans": meta["spans"],
        "choice": characters.default_for(locale) or "auto",
        "sources": characters.default_sources(len(script["cards"])),
        "versions": {}, "uneven": {}, "busy": False,
        # A queued 🌏 half belongs to this clip, not to whatever renders next
        # while Flow is being shot — same reason on_flow() parks it.
        "pair": state.pop("pair", None),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    st.to_idle(state)
    save_state(state)
    await publish_pack(client, state)


async def publish_pack(client: httpx.AsyncClient, state: dict) -> None:
    """A new pack version for the current choices, or a render if nothing is pending."""
    wait = state.get("clip_wait") or {}
    clip_id, script, card_spans = wait["clip_id"], wait["script"], wait["spans"]
    pending = studio.pending_cards(wait["sources"], studio.have_segments(clip_id, len(script["cards"])))
    if not pending:
        await render_studio(client, state, clip_id)
        return
    shots = studio.shot_map(card_spans, pending)
    wait["busy"] = True
    save_state(state)
    try:
        choice, text, fixed, profile = await _character_for(wait["choice"])
        board = await storyboard.for_studio(script, pending, shots, choice=choice,
                                            character=text, fixed_tag=fixed,
                                            topic=wait.get("topic") or "")
    except Exception as exc:
        logger.exception("studio plan failed")
        wait["busy"] = False
        save_state(state)
        await say(client, f"วาง shot ไม่สำเร็จ: {exc}\nกดปุ่มบน pack อีกครั้งเพื่อลองใหม่")
        return
    tag = (profile or {}).get("tag", "")
    if profile and profile.get("id") == "":
        person = board["overview"].get("master_character") or {}
        profile.update(locked=person.get("locked_prompt_tag", ""),
                       portrait=storyboard.portrait_prompt(person.get("locked_prompt_tag", "")))
    markdown = storyboard.studio_markdown(board, tag)
    token = studio.new_token()
    total = studio.total_shots(shots)
    pack = {
        "clip_id": clip_id, "token": token, "version": len(wait["versions"]) + 1,
        "title": script["title"], "locale": wait["locale"],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "character": profile, "sources": wait["sources"], "pending": pending,
        "shots": {str(k): v for k, v in shots.items()}, "total_shots": total,
        "credits": studio.credits(total), "spans": card_spans,
        "scenes": [{"n": i + 1, "card": s["card"], "image_prompt": s["image_gen_prompt"],
                    "motion": s["motion"], "narration": script["cards"][s["card"]]["narration"],
                    "span": round(card_spans[s["card"]], 2)}
                   for i, s in enumerate(board["scenes"])],
    }
    studio.write_pack(clip_id, pack, markdown)
    await send_document(client, studio.root(clip_id) / "script.md",
                        f"script.md — pack v{pack['version']}")
    flow_cards = ", ".join(str(c + 1) for c in pending)
    sent = await say(
        client,
        f"🎞 Studio pack v{pack['version']} — {script['title']}\n"
        f"การ์ด Flow: {flow_cards} · {total} shot × 8 วิ = {total * 8} วิ ≈ {pack['credits']} เครดิต\n"
        f"หน้า copy + อัปไฟล์: {pack_url(clip_id)}\n"
        "ไฟล์ ≤20MB reply ข้อความนี้ได้เลย · สลับ 🎬/🖼 หรือเปลี่ยนตัวละครด้วยปุ่มข้างล่าง",
        reply_markup=studio_keyboard(wait),
    )
    wait["versions"][token] = {"message_id": (sent or {}).get("message_id"),
                               "pending": pending, "shots": pack["shots"]}
    for stale in list(wait["versions"])[:-5]:
        wait["versions"].pop(stale, None)
    wait["busy"] = False
    save_state(state)


async def on_studio_callback(client: httpx.AsyncClient, state: dict, data: str) -> None:
    kind, _, rest = data.partition(":")
    clip_id, _, arg = rest.partition(":")
    wait = _studio_wait(state, clip_id)
    if not wait:
        await say(client, "pack นี้เก่าแล้ว (หมดอายุหรือมีอันใหม่กว่า) กด 🎞 ที่สคริปต์ใหม่นะ")
        return
    if kind == "ste":
        await cut_evenly(client, state, arg)
        return
    if kind == "str":
        await render_studio(client, state, clip_id)
        return
    if wait.get("busy"):
        await say(client, "กำลังทำ pack อยู่ รอสักครู่แล้วค่อยกดใหม่")
        return
    if kind == "stt":
        try:
            card = int(arg)
            wait["sources"][card] = (characters.PEXELS if wait["sources"][card] == characters.FLOW
                                     else characters.FLOW)
        except (ValueError, IndexError):
            return
    elif kind == "stc":
        wait["choice"] = arg
    elif kind == "stp":
        wait["sources"] = [characters.PEXELS] * len(wait["sources"])
    elif kind == "stx":
        await shorten_cards(client, state, wait)
        return
    save_state(state)
    spawn(publish_pack(client, state), "publish_pack")


async def shorten_cards(client: httpx.AsyncClient, state: dict, wait: dict) -> None:
    """✂️: back to review with the long Cards named. The bot never rewrites approved text."""
    if state.get("mode", "idle") != "idle":
        await say(client, st.busy_note(state.get("mode", "idle")))
        return
    long_cards = [f"การ์ด {i + 1} ({span:.1f} วิ)" for i, span in enumerate(wait["spans"])
                  if studio.shots_for(span) > 1]
    state.pop("clip_wait", None)
    studio.discard(wait["clip_id"])
    state.update(script=wait["script"], clip_id=wait["clip_id"], topic=wait.get("topic"),
                 locale=wait["locale"])
    sent = await say(client, format_script(wait["script"]), reply_markup=REVIEW_KEYBOARD)
    st.to_review(state, message_id=(sent or {}).get("message_id"))
    save_state(state)
    hint = ", ".join(long_cards) or "ไม่มีการ์ดที่เกิน 1 shot"
    await say(client, f"✂️ การ์ดที่ยาวเกิน 1 shot: {hint}\n"
                      f"พิมพ์ feedback ได้เลย เช่น: ย่อ{long_cards[0].split(' (')[0] if long_cards else 'การ์ด 2'} "
                      "ให้พูดไม่เกิน 7 วินาที")


async def render_studio(client: httpx.AsyncClient, state: dict, clip_id: str) -> None:
    """Replaced in Task 8."""
    await say(client, "render Studio ยังไม่พร้อม")


async def cut_evenly(client: httpx.AsyncClient, state: dict, token: str) -> None:
    """Replaced in Task 8."""
```

(f) In `on_callback` (around line 1788), add the following branch next to the `SBCHAR_CB` branch, above the mode guard. The pack outlives the review, so its buttons must work while the bot is idle.

```python
    if data.startswith(STUDIO_PREFIXES):
        await on_studio_callback(client, state, data)
        return
```

In the branch chain under the mode guard (next to `elif query.get("data") == FLOW_CB:`), add:

```python
    elif query.get("data") == STUDIO_CB:
        spawn(on_studio(client, state), "on_studio")
```

- [ ] **Step 4: Run the tests**

Run: `shorts-factory/scripts/sf-test tests/test_studio_bot.py -q`
Expected: 8 passed (`test_all_pexels_renders_without_a_pack` uses the monkeypatched `render_studio`).

Then run the existing keyboard tests: `shorts-factory/scripts/sf-test tests/test_shorts_factory.py -q -k "keyboard or review"`
Expected: pass. If a test pins `REVIEW_KEYBOARD`'s exact shape, update it to the new 3-button second row.

- [ ] **Step 5: Commit**

```bash
git add shorts-factory/app/main.py shorts-factory/tests/test_studio_bot.py shorts-factory/tests/test_shorts_factory.py
git commit -m "feat(shorts-factory): 🎞 Studio pack with per-Card Flow/Pexels and character switch"
```

---

### Task 8: Return leg: inbox, reply, cut, render, cleanup

**Files:**
- Modify: `shorts-factory/app/main.py`: replace the `render_studio`/`cut_evenly` stubs; extend `do_render`, video routing in `handle` (around line 2267), the poll loop (around line 2362), `do_upload` (around line 1297)
- Test: `shorts-factory/tests/test_studio_bot.py` (append)

**Interfaces:**
- Consumes:
  - from Task 2: `studio.duration`, `fits`, `shot_length`, `cut`, `claim_inbox`, `sweep_inbox`, `version_for_message`, `load_narration`, `have_segments`, `segment_path`, `discard`, `inbox_dir`
  - from Task 4: `render.build(narration=, hold=)`
- Produces:
  - `do_render(client, state, supplied=None, narration=None, hold=frozenset())`
  - `async process_export(client, state, token, path, even=False)`
  - `async on_studio_reply(client, state, message, token)`
  - real `render_studio`, `cut_evenly`

- [ ] **Step 1: Write the failing tests** (append to `tests/test_studio_bot.py`):

```python
import subprocess  # noqa: E402


def testsrc(path, seconds):
    subprocess.run(["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=size=720x1280:rate=24:duration={seconds}",
                    "-c:v", "libx264", "-preset", "ultrafast", str(path)], check=True, capture_output=True)
    return path


def capture_render(monkeypatch):
    calls = []

    async def fake(client, state, supplied=None, narration=None, hold=frozenset()):
        calls.append({"supplied": supplied, "narration": narration, "hold": set(hold),
                      "clip_id": state.get("clip_id")})

    monkeypatch.setattr(main, "do_render", fake)
    return calls


def studio_ready(bot):
    state = review_state()
    run(main.on_studio(None, state))
    token, = state["clip_wait"]["versions"]
    return state, token


def test_inbox_export_is_cut_and_rendered_with_the_saved_take(bot, monkeypatch, tmp_path):
    calls = capture_render(monkeypatch)
    monkeypatch.setattr(studio, "load_narration", lambda clip_id: (pathlib.Path("take.wav"), [0.0, 7.0, 16.0]))
    state, token = studio_ready(bot)
    inbox = studio.inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    testsrc(inbox / f"{token}.mp4", 8)
    (claimed_token, path), = studio.claim_inbox({token})
    asyncio.run(main.process_export(None, state, claimed_token, path))
    assert calls and calls[0]["hold"] == {0}
    assert calls[0]["supplied"] == {0: studio.segment_path(CLIP, 0)}
    assert calls[0]["narration"][1] == [0.0, 7.0, 16.0]
    assert not path.exists()


def test_wrong_length_waits_for_cut_evenly(bot, monkeypatch):
    calls = capture_render(monkeypatch)
    monkeypatch.setattr(studio, "load_narration", lambda clip_id: None)
    state, token = studio_ready(bot)
    inbox = studio.inbox_dir()
    inbox.mkdir(parents=True, exist_ok=True)
    path = testsrc(inbox / f"{token}.mp4.taken", 5)
    asyncio.run(main.process_export(None, state, token, path))
    assert not calls and token in state["clip_wait"]["uneven"]
    assert any("cut evenly" in str(item[2]) or "หั่นเท่า" in str(item[2]) for item in bot if item[0] == "say")
    run(main.on_studio_callback(None, state, f"ste:{CLIP}:{token}"))
    assert calls and calls[0]["narration"] is None
    assert any("/say" in item[1] for item in bot if item[0] == "say")


def test_busy_bot_keeps_a_render_button(bot, monkeypatch):
    calls = capture_render(monkeypatch)
    state, token = studio_ready(bot)
    state["mode"] = "rendering"
    asyncio.run(main.render_studio(None, state, CLIP))
    assert not calls
    last = [item for item in bot if item[0] == "say"][-1]
    assert f"str:{CLIP}" in json.dumps(last[2])


def test_reply_routes_to_the_version_it_answered(bot, monkeypatch):
    state, token = studio_ready(bot)
    monkeypatch.setattr(main, "is_ours", lambda update: True)
    labels = []
    monkeypatch.setattr(main, "spawn", lambda coro, label: labels.append(label) or coro.close())
    message_id = state["clip_wait"]["versions"][token]["message_id"]
    for replied, expected in ((message_id, "on_studio_reply"), (1, "on_footage")):
        message = {"video": {"file_id": "f", "file_size": 10}, "reply_to_message": {"message_id": replied}}
        asyncio.run(main.handle(None, state, {"message": message}))
    assert labels == ["on_studio_reply", "on_footage"]


def test_oversize_reply_points_to_the_web_page(bot):
    state, token = studio_ready(bot)
    message = {"video": {"file_id": "f", "file_size": main.TELEGRAM_FILE_LIMIT + 1}}
    asyncio.run(main.on_studio_reply(None, state, message, token))
    assert any("/storyboard/" in item[1] for item in bot if item[0] == "say")


def test_flow_to_pexels_after_render_keeps_other_footage(bot, monkeypatch):
    calls = capture_render(monkeypatch)
    monkeypatch.setattr(studio, "load_narration", lambda clip_id: None)
    state, token = studio_ready(bot)
    seg = studio.segment_path(CLIP, 0)
    seg.parent.mkdir(parents=True, exist_ok=True)
    seg.write_bytes(b"x")
    state["clip_wait"]["sources"] = ["flow", "flow", "pexels"]
    state["clip_wait"]["versions"].clear()
    run(main.on_studio_callback(None, state, f"stt:{CLIP}:1"))
    assert calls and calls[-1]["hold"] == {0}


def test_a_flow_card_without_footage_is_never_rendered_on_pexels(bot, monkeypatch):
    calls = capture_render(monkeypatch)
    state, token = studio_ready(bot)
    seg = studio.segment_path(CLIP, 0)
    seg.parent.mkdir(parents=True, exist_ok=True)
    seg.write_bytes(b"x")
    state["clip_wait"]["sources"] = ["flow", "flow", "pexels"]
    run(main.render_studio(None, state, CLIP))
    assert not calls
    assert any("การ์ด 2" in item[1] for item in bot if item[0] == "say")


def test_a_queued_pair_waits_inside_the_studio_pack(bot, monkeypatch):
    calls = capture_render(monkeypatch)
    state = review_state()
    state["pair"] = {"pair_id": CLIP, "topic": "หัวข้อ"}
    run(main.on_studio(None, state))
    assert "pair" not in state and state["clip_wait"]["pair"]["pair_id"] == CLIP
    seg = studio.segment_path(CLIP, 0)
    seg.parent.mkdir(parents=True, exist_ok=True)
    seg.write_bytes(b"x")
    run(main.render_studio(None, state, CLIP))
    assert calls and state["pair"]["pair_id"] == CLIP


def test_a_second_studio_pack_is_refused_while_one_is_live(bot):
    state = review_state()
    run(main.on_studio(None, state))
    other = {**review_state(), "clip_id": "20261016-090000-000",
             "clip_wait": state["clip_wait"]}
    run(main.on_studio(None, other))
    assert other["mode"] == "review" and other["clip_wait"]["clip_id"] == CLIP
    assert any("ค้างอยู่" in item[1] for item in bot if item[0] == "say")


def test_redo_keeps_the_flow_footage(bot, monkeypatch):
    rendered = []

    async def fake(client, state, clip_id):
        rendered.append(clip_id)

    monkeypatch.setattr(main, "render_studio", fake)
    state, token = studio_ready(bot)
    state.update(last_script=state["clip_wait"]["script"], last_clip_id=CLIP, mode="idle")
    run(main.on_redo(None, state))
    assert rendered == [CLIP]


def test_upload_success_cleans_the_studio_files(bot, monkeypatch, tmp_path):
    state, token = studio_ready(bot)
    assert studio.read_pack(CLIP)
    main.finish_studio_after_upload(state, CLIP)
    assert "clip_wait" not in state and studio.read_pack(CLIP) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `shorts-factory/scripts/sf-test tests/test_studio_bot.py -q`
Expected: FAIL with `AttributeError: module 'app.main' has no attribute 'process_export'`

- [ ] **Step 3: Implement.**

(a) `do_render`: change the signature and the `render.build` call:

```python
async def do_render(client: httpx.AsyncClient, state: dict,
                    supplied: dict[int, Path] | None = None,
                    narration: tuple[Path, list[float]] | None = None,
                    hold: frozenset[int] | set[int] = frozenset()) -> None:
```

```python
            clip, details = await render.build(
                script, workdir, supplied=supplied,
                locale=state.get("locale", locales.DEFAULT),
                narration=narration, hold=hold,
            )
```

(b) Replace the two stubs from Task 7 with:

```python
async def render_studio(client: httpx.AsyncClient, state: dict, clip_id: str) -> None:
    """Render with every Flow Card's kept footage; Pexels for the rest.

    Takes the live slots the way render_parked() does, so it needs an idle
    bot; a busy one gets a button rather than a dropped render.
    """
    wait = _studio_wait(state, clip_id)
    if not wait:
        await say(client, "pack นี้เก่าแล้ว กด 🎞 ที่สคริปต์ใหม่นะ")
        return
    mode = state.get("mode", "idle")
    if mode != "idle":
        note = st.busy_note(mode) if mode in st.HOLDING_MODES else "ยังมีสคริปต์ค้างรีวิวอยู่"
        await say(client, f"{note}\nfootage พร้อมแล้ว กด render เมื่อบอทว่าง",
                  reply_markup={"inline_keyboard": [[
                      {"text": "🎬 render Studio", "callback_data": f"str:{clip_id}"}]]})
        return
    count = len(wait["script"]["cards"])
    have = studio.have_segments(clip_id, count)
    missing = studio.pending_cards(wait["sources"], have)
    if missing:
        # A 🎬 Card with no footage is never quietly rendered on Pexels.
        await say(client, f"การ์ด {', '.join(str(c + 1) for c in missing)} ตั้งเป็น 🎬 Flow "
                          "แต่ยังไม่มี footage — ใช้ pack ล่าสุด หรือสลับการ์ดนั้นเป็น 🖼")
        return
    supplied = {i: studio.segment_path(clip_id, i) for i in have
                if wait["sources"][i] == characters.FLOW}
    narration = studio.load_narration(clip_id)
    if narration is None:
        await say(client, "🔁 เสียงพากย์เปลี่ยน (/say) หรือหาไฟล์เดิมไม่เจอ — อัดเสียงใหม่ "
                          "จุดตัดอาจคลาดเล็กน้อย")
    if wait.get("pair"):
        state["pair"] = wait.pop("pair")
    state.update(script=wait["script"], topic=wait.get("topic"), clip_id=clip_id,
                 style="", locale=wait["locale"], message_id=None)
    save_state(state)
    await do_render(client, state, supplied=supplied, narration=narration, hold=set(supplied))


async def process_export(client: httpx.AsyncClient, state: dict, token: str, path: Path,
                         even: bool = False) -> None:
    """One stitched export → per-Card footage → render. Never cut on a guess."""
    wait = state.get("clip_wait") or {}
    version = (wait.get("versions") or {}).get(token) if wait.get("kind") == "studio" else None
    if not version:
        path.unlink(missing_ok=True)
        await say(client, "ได้ไฟล์มา แต่ pack นั้นเก่าแล้ว — ใช้ pack ล่าสุดนะ")
        return
    shots = {int(k): v for k, v in version["shots"].items()}
    total = studio.total_shots(shots)
    try:
        seconds = await asyncio.to_thread(studio.duration, path)
    except RuntimeError as exc:
        path.unlink(missing_ok=True)
        await say(client, f"อ่านไฟล์ไม่ได้: {exc}\nexport จาก Flow ใหม่แล้วส่งอีกครั้ง")
        return
    if not even and not studio.fits(seconds, total):
        wait.setdefault("uneven", {})[token] = str(path)
        save_state(state)
        await say(client,
                  f"ได้ {seconds:.1f} วิ แต่ pack นี้มี {total} shot × 8 = {total * 8} วิ\n"
                  "เช็คว่าใน Scenes เรียงครบทุก shot ไม่ได้ตัดต่อ แล้ว export ใหม่ "
                  "หรือกดหั่นเท่าๆ กันถ้ามั่นใจว่าลำดับถูก",
                  reply_markup={"inline_keyboard": [[{"text": "✂️ หั่นเท่าๆ กัน (cut evenly)",
                                                      "callback_data": f"ste:{wait['clip_id']}:{token}"}]]})
        return
    try:
        await asyncio.to_thread(studio.cut, path, version["pending"], shots, wait["clip_id"],
                                studio.shot_length(seconds, total, even))
    except RuntimeError as exc:
        await say(client, f"หั่นคลิปไม่สำเร็จ: {exc}")
        return
    path.unlink(missing_ok=True)
    wait.get("uneven", {}).pop(token, None)
    save_state(state)
    await say(client, f"✂️ หั่น {total} shot แล้ว กำลัง render")
    await render_studio(client, state, wait["clip_id"])


async def cut_evenly(client: httpx.AsyncClient, state: dict, token: str) -> None:
    wait = state.get("clip_wait") or {}
    held = (wait.get("uneven") or {}).get(token)
    if not held or not Path(held).is_file():
        await say(client, "ไม่เจอไฟล์ที่รอหั่นแล้ว ส่งใหม่ได้เลย")
        return
    spawn(process_export(client, state, token, Path(held), even=True), "studio_cut_even")


async def on_studio_reply(client: httpx.AsyncClient, state: dict, message: dict, token: str) -> None:
    media = message.get("video") or message.get("document") or {}
    wait = state.get("clip_wait") or {}
    if (media.get("file_size") or 0) > TELEGRAM_FILE_LIMIT:
        await say(client, "ไฟล์ใหญ่เกิน 20MB — อัปที่หน้าเว็บแทน (ไม่โดนบีบภาพ): "
                          f"{pack_url(wait.get('clip_id', ''))}")
        return
    file_id = media.get("file_id")
    if not file_id:
        await say(client, "ไม่เจอไฟล์ในข้อความนี้ แนบคลิปมาด้วยนะ")
        return
    dest = studio.inbox_dir() / f"{token}.mp4.taken"
    await say(client, "⬇️ กำลังรับคลิปจาก Flow...")
    if not await download_footage(client, file_id, dest):
        dest.unlink(missing_ok=True)
        return
    await process_export(client, state, token, dest)


def finish_studio_after_upload(state: dict, clip_id: str | None) -> None:
    """The clip is on YouTube: its pack, take and footage have done their job."""
    if clip_id and _studio_wait(state, clip_id):
        state.pop("clip_wait", None)
        studio.discard(clip_id)
```

(c) Video routing in `handle`: before the existing `if replied and replied == waiting.get("message_id"):` line, insert:

```python
        token = studio.version_for_message(waiting, replied)
        if token:
            spawn(on_studio_reply(client, state, message, token), "on_studio_reply")
            return
```

(d) Poll loop: just before `if take_auto_pick(state):`, add the block below. In the existing `clip_wait_expired` branch, after `stale = state.pop("clip_wait", None)`, also add `if (stale or {}).get("kind") == "studio": studio.discard(stale["clip_id"])`.

```python
            waiting = state.get("clip_wait") or {}
            if waiting.get("kind") == "studio":
                # Exports uploaded through the Shop API land here; the bot has
                # no port of its own (docs/adr/0002), so the poll loop collects them.
                for token, path in studio.claim_inbox(set(waiting.get("versions") or {})):
                    spawn(process_export(client, state, token, path), "studio_export")
            studio.sweep_inbox(set(waiting.get("versions") or {}))
```

(f) `/redo` must not throw the Flow footage away. In `on_redo`, insert the block below after the `if not script:` guard. Without it, `/redo` (which `do_render`'s footer recommends after `/say`) re-renders with no `supplied` footage, so every Card falls back to Pexels and the clip re-enters the experiment tally:

```python
    wait = state.get("clip_wait") or {}
    if wait.get("kind") == "studio" and wait.get("clip_id") == state.get("last_clip_id"):
        await say(client, f"🔁 render ซ้ำด้วย footage จาก Flow เดิม: {script['title']}")
        spawn(render_studio(client, state, wait["clip_id"]), "render_studio")
        return
```

(e) `do_upload`: after the `manifest.update(...)` call that records `video_id`, add:

```python
    finish_studio_after_upload(state, clip_id or state.get("last_clip_id"))
    save_state(state)
```

- [ ] **Step 4: Run the tests**

Run: `shorts-factory/scripts/sf-test tests/test_studio_bot.py tests/test_studio.py -q`
Expected: all pass.

Then run: `shorts-factory/scripts/sf-test tests/test_shorts_factory.py -q --deselect tests/test_shorts_factory.py::test_narration_is_one_take_with_a_start_per_card`
Expected: all pass. Existing `fake_render(client, state, supplied=None)` doubles still work, because the new kwargs are only passed by `render_studio`.

- [ ] **Step 5: Commit**

```bash
git add shorts-factory/app/main.py shorts-factory/tests/test_studio_bot.py
git commit -m "feat(shorts-factory): take Studio exports back, cut per Card and render"
```

---

### Task 9: Keep Studio clips out of the hook experiment

**Files:**
- Modify: `shorts-factory/app/experiment.py`: `tally` (around line 102)
- Test: `shorts-factory/tests/test_studio.py` (append)

**Interfaces:**
- Produces: `experiment.studio_clip(record: dict) -> bool`

- [ ] **Step 1: Write the failing test** (append):

```python
def test_studio_clips_are_left_out_of_the_tally():
    from app import experiment
    arm = sorted(experiment.VARIANTS)[0]
    plain = {"variant": arm, "outcome": "rendered", "render": {"cards": [{"footage_source": "flow"}]}}
    flow = {"variant": arm, "outcome": "rendered",
            "render": {"cards": [{"footage_source": "flow-studio"}, {"footage_source": "pexels"}]}}
    assert experiment.studio_clip(flow) and not experiment.studio_clip(plain)
    assert experiment.tally([plain, flow])[arm]["clips"] == 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `shorts-factory/scripts/sf-test tests/test_studio.py -q -k tally`
Expected: FAIL with `AttributeError: ... has no attribute 'studio_clip'`

- [ ] **Step 3: Implement.** Add above `tally`:

```python
def studio_clip(record: dict) -> bool:
    """Whether any Card came from a Storyboard Studio pack (docs/adr/0016).

    A clip shot in Flow differs from a Pexels one far more than one hook clause
    does, so counting it would credit an arm with the footage.
    """
    cards = (record.get("render") or {}).get("cards") or []
    return any(c.get("footage_source") == "flow-studio" for c in cards)
```

In `tally`'s loop, make the first statement `if studio_clip(record): continue`.

- [ ] **Step 4: Run the tests**

Run: `shorts-factory/scripts/sf-test tests/test_studio.py tests/test_shorts_factory.py -q -k "tally or experiment or studio"`
Expected: pass

- [ ] **Step 5: Commit**

```bash
git add shorts-factory/app/experiment.py shorts-factory/tests/test_studio.py
git commit -m "feat(shorts-factory): exclude Studio clips from the hook experiment"
```

---

### Task 10: Characters in dashboard `/settings`

**Files:**
- Modify: `shorts-factory/app/dashboard.py`: `_settings_page`, `settings_save`
- Modify: `shorts-factory/app/templates/settings.html`: add a section before `<div class="settings-actions">`
- Test: `shorts-factory/tests/test_dashboard.py` (append)

**Interfaces:**
- Consumes: `characters.stored`, `characters.from_form`, `characters.validate`, `characters.save`, `characters.CHANNELS`
- Produces: template context `library` (`characters.stored()` result, or the submitted payload on error), `channels`

- [ ] **Step 1: Write the failing tests** (append):

```python
def settings_form_data(**extra):
    data = {"th_hours": "8", "th_minutes": "15", "en_hours": "", "en_minutes": "15",
            "model_primary": "", "model_fallback": "",
            "char_0_id": "nong", "char_0_tag": "@Nong", "char_0_thai": "ผู้หญิงไทย 28 ปี",
            "char_0_english": "", "char_0_ready": "on",
            "char_1_id": "", "char_1_tag": "", "char_1_thai": "", "char_1_english": "",
            "default_th": "nong", "default_en": "", "default_shop": "", "footage": "hook"}
    data.update(extra)
    return data


def test_settings_saves_the_character_library(client, config_dir):
    reply = client.post("/settings", data=settings_form_data())
    assert reply.status_code == 200
    saved = json.loads((config_dir / "characters.json").read_text(encoding="utf-8"))
    assert saved["characters"][0]["tag"] == "@Nong" and saved["defaults"]["th"] == "nong"
    assert "@Nong" in client.get("/settings").text


def test_a_bad_character_stores_nothing_at_all(client, config_dir):
    reply = client.post("/settings", data=settings_form_data(char_0_tag="Nong"))
    assert reply.status_code == 400
    assert not (config_dir / "characters.json").exists()
    assert not (config_dir / "schedule.json").exists()
    assert 'value="Nong"' in reply.text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `shorts-factory/scripts/sf-test tests/test_dashboard.py -q -k character`
Expected: FAIL, because `characters.json` is not written

- [ ] **Step 3: Implement.**

In `dashboard.py`, add `characters` to the `from app import (...)` list.

In `settings_save`, read the library before the `try`, validate it with the others, and save it last:

```python
    library = characters.from_form(form)
    try:
        # All three checked before any is written: one bad field stores nothing.
        schedule.validate(payload)
        model_choice.validate(models)
        characters.validate(library)
        stored = schedule.save(payload)
        chosen = model_choice.save(models)
        characters.save(library)
    except ValueError as exc:
        return _settings_page(request, schedule.settings(), model_choice.stored(),
                              error=str(exc), status=400, submitted=form, library=library)
    return _settings_page(request, stored, chosen, saved=True)
```

Add a `library: dict | None = None` parameter to `_settings_page`. Add these context keys:

```python
        "library": library or characters.stored(),
        "channels": characters.CHANNELS,
```

Also update `settings_save`'s docstring to name `/config/characters.json`.

In `settings.html`, insert before `<div class="settings-actions">`:

```html
<section class="card model-settings"><div class="card-head"><h2>ตัวละครประจำ (Storyboard Studio)</h2>{{ icon('flask') }}</div>
<p class="muted small">ตั้งครั้งเดียว ใช้ทุกคลิป tag ต้องตรงกับ Asset Profile ใน Flow · ช่อง English เว้นว่างได้ บอทแปลให้ครั้งแรกแล้วจำไว้</p>
{% set rows = library.characters + [{'id': '', 'tag': '', 'thai': '', 'english': '', 'flow_ready': False}] %}
{% for c in rows %}<fieldset class="card channel-settings"><legend>{{ c.tag or 'เพิ่มตัวละครใหม่' }}</legend>
<div class="form-grid">
<div class="field"><label for="char-{{ loop.index0 }}-id">id (a-z, 0-9) — ลบตัวละคร = ล้างช่องนี้</label><input id="char-{{ loop.index0 }}-id" name="char_{{ loop.index0 }}_id" value="{{ c.id }}"></div>
<div class="field"><label for="char-{{ loop.index0 }}-tag">tag ใน Flow</label><input id="char-{{ loop.index0 }}-tag" name="char_{{ loop.index0 }}_tag" value="{{ c.tag }}" placeholder="@Nong"></div>
</div>
<div class="field"><label for="char-{{ loop.index0 }}-thai">ลักษณะ (ไทย)</label><input id="char-{{ loop.index0 }}-thai" name="char_{{ loop.index0 }}_thai" value="{{ c.thai }}" placeholder="ผู้หญิงไทย 28 ปี ผมบ๊อบสีดำ แว่นกลม เสื้อเชิ้ตลินินสีเบจ"></div>
<div class="field"><label for="char-{{ loop.index0 }}-english">English (ไม่บังคับ)</label><input id="char-{{ loop.index0 }}-english" name="char_{{ loop.index0 }}_english" value="{{ c.english }}"></div>
<label class="toggle" for="char-{{ loop.index0 }}-ready"><input id="char-{{ loop.index0 }}-ready" type="checkbox" name="char_{{ loop.index0 }}_ready"{% if c.flow_ready %} checked{% endif %}><span>สร้าง Asset Profile ใน Flow แล้ว</span></label>
</fieldset>{% endfor %}
<div class="form-grid">{% for ch in channels %}<div class="field"><label for="default-{{ ch }}">ตัวละครเริ่มต้นช่อง {{ ch|upper }}</label><select id="default-{{ ch }}" name="default_{{ ch }}"><option value="">🤖 ให้บอทแต่ง</option>{% for c in library.characters %}<option value="{{ c.id }}"{% if library.defaults[ch] == c.id %} selected{% endif %}>{{ c.tag }}</option>{% endfor %}</select></div>{% endfor %}
<div class="field"><label for="footage-rule">แหล่งภาพเริ่มต้นของแต่ละการ์ด</label><select id="footage-rule" name="footage">{% for value, label in [('hook', 'hook = Flow, ที่เหลือ Pexels'), ('none', 'Pexels ทั้งหมด'), ('all', 'Flow ทั้งหมด')] %}<option value="{{ value }}"{% if library.footage == value %} selected{% endif %}>{{ label }}</option>{% endfor %}</select></div></div>
</section>
```

- [ ] **Step 4: Run the dashboard suite**

Run: `shorts-factory/scripts/sf-test tests/test_dashboard.py tests/test_dashboard_studio.py -q`
Expected: all pass, including `test_only_the_schedule_route_can_write`, which stays unchanged.

- [ ] **Step 5: Commit**

```bash
git add shorts-factory/app/dashboard.py shorts-factory/app/templates/settings.html shorts-factory/tests/test_dashboard.py
git commit -m "feat(shorts-factory): character library on the settings page"
```

---

### Task 11: Dashboard pack page with copy boxes and upload

**Files:**
- Modify: `shorts-factory/app/dashboard.py`: two GET routes
- Create: `shorts-factory/app/templates/storyboard.html`
- Create: `shorts-factory/app/static/studio.js`
- Test: `shorts-factory/tests/test_dashboard.py` (append)

**Interfaces:**
- Consumes: from Task 2, `studio.read_pack` and `studio.read_markdown`. `studio` imports no PIL at module level.
- Produces: `GET /storyboard/{clip_id}` (HTML) and `GET /storyboard/{clip_id}/script.md` (text/markdown attachment)

- [ ] **Step 1: Write the failing tests** (append):

```python
def write_pack(data_dir, character):
    where = data_dir / "studio" / "20261015-170226-065"
    where.mkdir(parents=True)
    (where / "pack.json").write_text(json.dumps({
        "clip_id": "20261015-170226-065", "token": "a1b2c3d4e5f6", "version": 2, "title": "หัวข้อ",
        "character": character, "sources": ["flow", "pexels"], "pending": [0],
        "shots": {"0": 2}, "total_shots": 2, "credits": 24, "spans": [9.1, 8.0],
        "scenes": [{"n": 1, "card": 0, "image_prompt": "P1", "motion": "M1", "narration": "พูด", "span": 9.1},
                   {"n": 2, "card": 0, "image_prompt": "P2", "motion": "M2", "narration": "พูด", "span": 9.1}]},
        ensure_ascii=False), encoding="utf-8")
    (where / "script.md").write_text("# Shot list\n", encoding="utf-8")


def test_pack_page_shows_boxes_and_upload_token(client, data_dir):
    write_pack(data_dir, {"id": "nong", "tag": "@Nong", "locked": "L", "flow_ready": False, "portrait": "PORTRAIT"})
    page = client.get("/storyboard/20261015-170226-065")
    assert page.status_code == 200
    text = page.text
    assert "PORTRAIT" in text and "# Shot list" in text and "P2" in text and "M1" in text
    assert "2 shot × 8 วิ = 16 วิ" in text and "a1b2c3d4e5f6" in text


def test_ready_character_box_is_collapsed(client, data_dir):
    write_pack(data_dir, {"id": "nong", "tag": "@Nong", "locked": "L", "flow_ready": True, "portrait": "PORTRAIT"})
    text = client.get("/storyboard/20261015-170226-065").text
    assert "<details" in text.split("PORTRAIT")[0].rsplit("<section", 1)[1]


def test_script_md_downloads_and_bad_ids_404(client, data_dir):
    write_pack(data_dir, None)
    reply = client.get("/storyboard/20261015-170226-065/script.md")
    assert reply.status_code == 200 and reply.text == "# Shot list\n"
    assert "attachment" in reply.headers["content-disposition"]
    assert client.get("/storyboard/..%2Fetc").status_code == 404
    assert client.get("/storyboard/20200101-000000-000").status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `shorts-factory/scripts/sf-test tests/test_dashboard.py -q -k "pack_page or script_md or ready_character"`
Expected: FAIL with 404

- [ ] **Step 3: Implement.**

In `dashboard.py`, add `studio` to the `from app import (...)` list, add `PlainTextResponse` to the `fastapi.responses` import and `HTTPException` to the `fastapi` import, then add these routes before `/settings`:

```python
def _pack_or_404(clip_id: str) -> dict:
    try:
        pack = studio.read_pack(clip_id)
    except ValueError:
        pack = None
    if not pack:
        raise HTTPException(status_code=404)
    return pack


@app.get("/storyboard/{clip_id}", response_class=HTMLResponse)
def storyboard_pack(request: Request, clip_id: str):
    """The Storyboard Studio pack (docs/adr/0016): read-only, like every page
    but /settings. The upload form posts to the Shop API, not to this app."""
    pack = _pack_or_404(clip_id)
    return TEMPLATES.TemplateResponse(request, "storyboard.html", {
        "pack": pack, "markdown": studio.read_markdown(clip_id) or "", "gate": None})


@app.get("/storyboard/{clip_id}/script.md")
def storyboard_markdown(clip_id: str):
    _pack_or_404(clip_id)
    return PlainTextResponse(studio.read_markdown(clip_id) or "", media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="{clip_id}-script.md"'})
```

Create `templates/storyboard.html`:

```html
{% extends "base.html" %}
{% block title %}Studio pack — {{ pack.title }}{% endblock %}
{% block page_header %}<div class="page-head"><div><span class="eyebrow">STORYBOARD STUDIO · PACK v{{ pack.version }}</span><h1>{{ pack.title }}</h1><p class="sub">{{ pack.total_shots }} shot × 8 วิ = {{ pack.total_shots * 8 }} วิ · ≈ {{ pack.credits }} เครดิต · การ์ด Flow: {% for c in pack.pending %}{{ c + 1 }}{% if not loop.last %}, {% endif %}{% endfor %}</p></div></div>{% endblock %}
{% block content %}
<section class="card"><div class="card-head"><h2>0 · ตั้ง project ใน Flow</h2></div><ul>
<li>Storyboard Studio → ตั้งสัดส่วน <b>9:16</b>, preset Photorealistic</li>
<li>ตอน Animate: Video · Ingredients · 9:16 · 720p · <b>8s</b> · x1</li>
<li>ใช้ project เดิมที่มี Asset Profile ตัวละครอยู่แล้ว</li></ul></section>

{% if pack.character and pack.character.portrait %}
<section class="card"><div class="card-head"><h2>1 · ตัวละคร {{ pack.character.tag }}</h2></div>
{% if pack.character.flow_ready %}<details><summary>ใช้ {{ pack.character.tag }} ใน project เดิม (กดเพื่อดู prompt)</summary>{% endif %}
<p class="muted small">เจนภาพนี้ใน Flow แล้วสร้าง Asset Profile ชื่อ {{ pack.character.tag }} · ติ๊ก "สร้างแล้ว" ที่หน้า ตั้งค่า</p>
<pre id="portrait" class="script-copy">{{ pack.character.portrait }}</pre>
<button class="copy-button" type="button" data-copy="portrait" data-feedback="portrait-result" hidden>{{ icon('copy') }} คัดลอก</button><p id="portrait-result" class="copy-feedback" role="status" aria-live="polite"></p>
{% if pack.character.flow_ready %}</details>{% endif %}
</section>{% endif %}

<section class="card"><div class="card-head"><h2>3 · Script สำหรับ Storyboard Studio</h2>
<button class="copy-button" type="button" data-copy="script-md" data-feedback="script-result" hidden>{{ icon('copy') }} คัดลอกทั้งหมด</button></div>
<p><a class="shop-button" href="/storyboard/{{ pack.clip_id }}/script.md" download>ดาวน์โหลด script.md</a></p>
<pre id="script-md" class="script-copy">{{ markdown }}</pre><p id="script-result" class="copy-feedback" role="status" aria-live="polite"></p></section>

<section class="card"><div class="card-head"><h2>4 · Animate ทีละ shot</h2></div>
{% for s in pack.scenes %}<details class="disclosure"><summary>Shot {{ s.n }} · การ์ด {{ s.card + 1 }} · พูด {{ s.span }} วิ</summary>
<p class="muted small">แนบ Ingredients: {% if pack.character %}(1) {{ pack.character.tag }} {% endif %}(2) frame ของ shot นี้ (3) frame ถัดไปของฉากเดียวกัน (ถ้ามี)</p>
<p class="small">🔊 {{ s.narration }}</p>
<pre id="motion-{{ s.n }}" class="script-copy">{{ s.image_prompt }}, {{ s.motion }}</pre>
<button class="copy-button" type="button" data-copy="motion-{{ s.n }}" data-feedback="motion-{{ s.n }}-result" hidden>{{ icon('copy') }} คัดลอก</button><p id="motion-{{ s.n }}-result" class="copy-feedback" role="status" aria-live="polite"></p>
</details>{% endfor %}</section>

<section class="card"><div class="card-head"><h2>5 · Export แล้วอัปกลับ</h2></div>
<p>Scenes → เรียง {{ pack.total_shots }} shot ตามลำดับ → export (เสียงติดมาได้ บอทตัดทิ้ง) → ไฟล์ควรยาว <b>{{ pack.total_shots * 8 }} วิ</b></p>
<form id="studio-upload" data-token="{{ pack.token }}"><input type="file" name="file" accept="video/mp4,video/quicktime" required>
<button class="primary" type="submit">อัปไฟล์ให้บอท</button></form>
<p id="studio-upload-result" class="copy-feedback" role="status" aria-live="polite"></p>
<p class="muted small">token {{ pack.token }} · ใช้ได้กับ pack v{{ pack.version }} เท่านั้น ถ้าสลับการ์ดใน Telegram ให้เปิดหน้านี้ใหม่</p></section>
<script src="/static/studio.js" defer></script>
{% endblock %}
```

Create `static/studio.js`:

```javascript
// Upload a Flow export to the Shop API inbox (docs/adr/0016). Same origin
// through nginx; the Shop API's double-submit CSRF needs the session token.
(() => {
  const form = document.getElementById('studio-upload');
  if (!form) return;
  const result = document.getElementById('studio-upload-result');
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const file = form.querySelector('input[type=file]').files[0];
    if (!file) return;
    result.textContent = 'กำลังอัป...';
    try {
      const session = await fetch('/shop/api/session', {credentials: 'same-origin'});
      const csrf = (await session.json()).csrf_token;
      const body = new FormData();
      body.append('file', file);
      const reply = await fetch('/shop/api/studio-inbox/' + form.dataset.token, {
        method: 'POST', body, credentials: 'same-origin', headers: {'X-CSRF-Token': csrf}});
      const data = await reply.json().catch(() => ({}));
      result.textContent = reply.ok
        ? 'อัปแล้ว ' + Math.round(data.bytes / 1e6) + ' MB — บอทจะแจ้งใน Telegram ภายใน ~30 วิ'
        : 'อัปไม่ผ่าน: ' + (data.detail || reply.status);
    } catch (error) {
      result.textContent = 'อัปไม่ผ่าน: ' + error;
    }
  });
})();
```

- [ ] **Step 4: Run the dashboard suite**

Run: `shorts-factory/scripts/sf-test tests/test_dashboard.py tests/test_dashboard_studio.py -q`
Expected: all pass, including the PIL/edge_tts import guard and `test_only_the_schedule_route_can_write`.

- [ ] **Step 5: Commit**

```bash
git add shorts-factory/app/dashboard.py shorts-factory/app/templates/storyboard.html shorts-factory/app/static/studio.js shorts-factory/tests/test_dashboard.py
git commit -m "feat(shorts-factory): dashboard pack page with copy boxes and upload"
```

---

### Task 12: ADR, docs, full regression

**Files:**
- Create: `docs/adr/0016-storyboard-studio-pack.md`
- Modify: `shorts-factory/README.md` (new section "Storyboard Studio (🎞)")
- Modify: `CLAUDE.md`: one sentence appended to the `shorts-factory/` row
- Modify: `shorts-factory/.notes/daily_log.md`, `shorts-factory/.notes/00_INDEX.md`

- [ ] **Step 1: Write ADR 0016**

```markdown
# Storyboard Studio packs: the human shoots in Flow, the bot assembles

Shop Flow Studio and the 📋 storyboard made the human loop per scene: copy a
prompt, generate, download, upload, accept. That loop was the cost.

Flow cannot be driven by code without risking the Google account. It has no
API. Every unofficial driver works against reCAPTCHA. gflow-cli cannot generate
headless or in a container. flowkit users report accounts blocked from
generating by hand after automating (flowkit #67, 2026-10). The paid Veo API is
excluded: no new spend.

So the bot meets Flow's own **Storyboard Studio** halfway. For the Cards the
human marks 🎬 (default: the hook), it speaks the Script once, gives each Card
`ceil((span + 0.5) / 8)` shots of 8 s, and writes an English-only `script.md`
plus a copy-box page. The human generates and stitches in Flow and brings back
**one** export. The bot cuts it at multiples of 8 s, which was measured exact on
a real export (24.000 s, cuts at 8.0/16.0). It renders with the take it already
spoke. Other Cards keep Pexels. A wrong length is refused with a "cut evenly"
button, never cut on a guess (ADR 0005).

Boundaries kept: the bot still has no port (ADR 0002). Exports over Telegram's
20 MB ceiling go through one new Shop API route into `/output/studio-inbox`,
which the poll loop collects. The dashboard is still read-only apart from
`/settings`, which now also stores the character library (ADR 0009). The bot
never rewrites approved text. ✂️ returns the Script to review. Studio clips are
left out of the hook experiment (ADR 0004) because the footage, not the hook,
would be measured.

Extends 0005 (Flow footage for any Card, still human-generated) and 0006 (the
bot now consumes a Flow export for Shorts; no long-form assembly still holds).
```

- [ ] **Step 2: README section.** Add a `## Storyboard Studio (🎞)` section to `shorts-factory/README.md`. It covers: the button, the per-Card toggles, the character library in `/settings`, the pack page `/storyboard/<clip_id>`, upload vs reply ≤20 MB, the 8 s rule and "cut evenly", files in `/data/studio/<clip_id>/` deleted on upload or 72 h, `FLOW_CREDITS_PER_SHOT`, and the experiment exclusion.

- [ ] **Step 3: CLAUDE.md.** Append to the end of the `shorts-factory/` row:
  > **🎞 Studio** (ADR 0016): per-Card Flow/Pexels; pack = English `script.md` + `/storyboard/<id>`; one stitched Flow export comes back via Shop API `/shop/api/studio-inbox/<token>` → `/output/studio-inbox` (bot polls, no port) or a reply ≤20 MB; the bot cuts every 8 s and renders with the saved take; characters in `/config/characters.json`, English cache `/data/character_tags.json`; Studio clips are excluded from `experiment.tally`.

- [ ] **Step 4: Full regression in a freshly built image**

```bash
docker build -t shorts-factory:studio shorts-factory
docker run --rm --network none shorts-factory:studio pytest tests/ -q \
  --deselect tests/test_shorts_factory.py::test_narration_is_one_take_with_a_start_per_card
make check
```

Expected: all pass (baseline 426 + the new tests), 2 repository-wiring skips as before. `make check` (doc-drift + shared-sync) passes.

- [ ] **Step 5: Notes + commit**

In `shorts-factory/.notes/daily_log.md`, add a dated entry: what shipped, the test counts, "not deployed", and the open live checks (STYLE header, `@tag` binding, Storyboard frame aspect, monthly credits). Update the top of `00_INDEX.md` to match.

```bash
git add docs/adr/0016-storyboard-studio-pack.md shorts-factory/README.md CLAUDE.md shorts-factory/.notes
git commit -m "docs(shorts-factory): ADR 0016 Storyboard Studio packs"
```

Live acceptance (after deploy, before calling Phase 1 done): one real clip end to end, **including a web upload over 20 MB through the external URL**. The stack nginx allows 102m, but the DSM reverse proxy in front of it has never carried a 45–80 MB body to `/shop/api/…` and may answer 413 first. A hook-only pack is about 7 MB per shot (21.3 MB ÷ 3), so the Telegram reply covers the common case either way.

Deployment is **not** part of this plan. It needs the user's go-ahead: `scripts/deploy.sh -s shorts-factory -y` while the bot is idle, then one live clip end to end (Phase 2 of the spec).
