# Wallpaper Scout Stack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `wallpaper-scout`, a new stack that lets the user register "topics" (e.g. "Wuthering Waves", "IU") with a target purpose (mobile/laptop/pc wallpaper), periodically searches Wallhaven for SFW images matching each topic+purpose, downloads new (never-before-seen) images, and drops them into a filesystem folder tree that Synology Photos auto-indexes.

**Architecture:** FastAPI + APScheduler + SQLite, same shape as `torrentwatch`/`friendly-reminder`. One in-process scheduler job per topic (interval = 86400s / frequency_per_day) calls Wallhaven's public search API, filters by a hardcoded purpose→ratio/resolution preset, skips already-downloaded Wallhaven IDs (SQLite unique constraint), and writes accepted images to a bind-mounted host path under the NAS user's `Photos/wallpapers/<purpose>/<topic-slug>/` folder. A small LLM call (MiMo primary, Anthropic fallback — reusing the exact provider-switch pattern already in `news-feed/app/summarizer.py`) expands a topic string into alias search terms once, at topic-creation time, to widen Wallhaven recall on foreign/ambiguous names (e.g. "IU" → "IU, Lee Ji-eun, 아이유"). Dashboard is a small vanilla-JS SPA (matches `friendly-reminder/app/static`), behind an nginx basic-auth sidecar, LAN-only (no public HTTPS proxy port needed — this stack doesn't receive inbound webhooks).

**Tech Stack:** Python 3.12, FastAPI 0.115.5, Uvicorn 0.32.1, APScheduler 3.10.4, httpx 0.28.0, anthropic 0.40.0, SQLite (stdlib `sqlite3`), vanilla JS frontend, nginx:alpine sidecar for basic auth.

## Global Constraints

- Reuse `shared/http_client.py`, `shared/notify.py`, `shared/sqlite_backup.py` verbatim (vendored copy, `make sync-shared` keeps them byte-identical — do not hand-edit the vendored copies after the initial `cp`).
- No DSM Photos REST API, no DSM session/login anywhere in this stack (avoids the documented DSM auto-block gotcha in root `CLAUDE.md`).
- Purity filter is hardcoded SFW-only (`purity=100`) — not user-configurable in v1.
- Purpose presets (`mobile`/`laptop`/`pc`) are hardcoded constants — only *which* purposes apply to a topic is user-selectable, not the ratio/resolution values.
- Dedup is exact Wallhaven-ID only (SQLite unique constraint on `(topic_id, purpose, wallhaven_id)`) — no perceptual hashing in v1.
- No auto-delete/retention job — downloaded images are kept forever.
- Sort strategy is two-phase per topic: one-time `toplist` backfill when a topic is first created, `date_added` on every subsequent scheduled cycle.
- LLM usage is text-only (alias expansion), no vision/image analysis in v1.
- Notifications: LINE only, one daily summary message, no per-cycle notify.
- Follow the release process in root `CLAUDE.md`: update stack README, update root `CLAUDE.md`/`README.md` stacks table, one atomic commit with docs, never commit `.env`/`.env.deploy`/plaintext secrets, use `make edit-vault` for vault edits.

---

## File Structure

```
wallpaper-scout/
├── app/
│   ├── __init__.py
│   ├── main.py            — FastAPI app: lifespan wiring, /api/topics CRUD, /api/status, static mount
│   ├── db.py               — SQLite schema + CRUD (topics, downloads)
│   ├── wallhaven.py        — Wallhaven API client + purpose presets
│   ├── llm.py              — alias/query expansion (anthropic/mimo provider switch)
│   ├── scheduler.py        — APScheduler: per-topic scrape cycle + daily summary job
│   ├── http_client.py      — vendored shared/http_client.py
│   ├── notify.py           — vendored shared/notify.py
│   ├── sqlite_backup.py    — vendored shared/sqlite_backup.py
│   └── static/
│       ├── index.html
│       ├── app.js
│       └── style.css
├── nginx/
│   └── nginx.conf           (nginx/.htpasswd is created manually on deploy, gitignored)
├── tests/
│   ├── __init__.py
│   ├── test_db.py
│   ├── test_wallhaven.py
│   ├── test_llm.py
│   └── test_scheduler.py
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── secrets.manifest.yaml
└── .notes/
    ├── 00_INDEX.md
    └── daily_log.md
```

**Port:** `5067` (host) → nginx → `8000` (container, internal-only via `expose`). Confirmed free — no other stack in this repo uses 5067/15067.

**NAS output path:** container writes into a bind mount whose host side is `/volume1/homes/fixhardez/Photos/wallpapers` (Synology Photos personal-space root the user gave us). Container path: `/photos_root`. Final file lands at `/photos_root/<purpose>/<topic-slug>/<wallhaven_id>.<ext>`, i.e. host-side `/volume1/homes/fixhardez/Photos/wallpapers/<purpose>/<topic-slug>/<wallhaven_id>.<ext>`.

---

### Task 1: Scaffold the stack skeleton

**Files:**
- Create: `wallpaper-scout/Dockerfile`
- Create: `wallpaper-scout/docker-compose.yml`
- Create: `wallpaper-scout/requirements.txt`
- Create: `wallpaper-scout/app/__init__.py`
- Create: `wallpaper-scout/app/http_client.py` (copy of `shared/http_client.py`)
- Create: `wallpaper-scout/app/notify.py` (copy of `shared/notify.py`)
- Create: `wallpaper-scout/app/sqlite_backup.py` (copy of `shared/sqlite_backup.py`)
- Create: `wallpaper-scout/tests/__init__.py`
- Modify: `CLAUDE.md` (stacks table)

**Interfaces:**
- Produces: container listens on `0.0.0.0:8000`, reads `DATA_DIR` (default `/data`) and `TZ` env vars — later tasks' `db.py`/`main.py` rely on these.

- [ ] **Step 1: Create directory skeleton and vendor shared modules**

```bash
mkdir -p wallpaper-scout/app/static wallpaper-scout/nginx wallpaper-scout/tests
touch wallpaper-scout/app/__init__.py wallpaper-scout/tests/__init__.py
cp shared/http_client.py wallpaper-scout/app/http_client.py
cp shared/notify.py wallpaper-scout/app/notify.py
cp shared/sqlite_backup.py wallpaper-scout/app/sqlite_backup.py
```

- [ ] **Step 2: Write `wallpaper-scout/requirements.txt`**

```
fastapi==0.115.5
uvicorn[standard]==0.32.1
apscheduler==3.10.4
httpx==0.28.0
anthropic==0.40.0

pytest==8.3.4
pytest-mock==3.14.0
```

- [ ] **Step 3: Write `wallpaper-scout/Dockerfile`**

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

RUN mkdir -p /data /photos_root

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

No `USER` directive and no baked-in uid/gid: the host `fixhardez` UID is only known at deploy time (Task 8 discovers it via `id fixhardez` over SSH), so ownership is set with the `user:` directive in `docker-compose.yml` at run time instead of a fixed Dockerfile user, matching how `friendly-reminder`'s Dockerfile bakes `uid=1000` (there it's fine because nothing outside the container needs that uid to line up with a host account; here it does).

- [ ] **Step 4: Write `wallpaper-scout/docker-compose.yml`**

```yaml
services:
  wallpaper-scout:
    build: .
    container_name: wallpaper-scout
    restart: unless-stopped
    user: "${PHOTOS_UID}:${PHOTOS_GID}"
    expose:
      - "8000"
    env_file: .env
    environment:
      - TZ=Asia/Bangkok
      - DATA_DIR=/data
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/status', timeout=5)"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    volumes:
      - ${NAS_WALLPAPER_SCOUT_DATA_PATH}:/data
      - ${NAS_PHOTOS_WALLPAPERS_PATH}:/photos_root

  nginx:
    image: nginx:alpine
    container_name: wallpaper-scout-nginx
    restart: unless-stopped
    ports:
      - "5067:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./nginx/.htpasswd:/etc/nginx/.htpasswd:ro
    environment:
      - TZ=Asia/Bangkok
    depends_on:
      - wallpaper-scout
```

- [ ] **Step 5: Write `wallpaper-scout/nginx/nginx.conf`**

```nginx
server {
    listen 80;

    location / {
        auth_basic           "Restricted";
        auth_basic_user_file /etc/nginx/.htpasswd;

        proxy_pass          http://wallpaper-scout:8000;
        proxy_http_version  1.1;
        proxy_set_header    Host              $http_host;
        proxy_set_header    X-Real-IP         $remote_addr;
        proxy_set_header    X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header    X-Forwarded-Proto $scheme;
        proxy_buffering     off;
    }
}
```

- [ ] **Step 6: Register the stack in root `CLAUDE.md`**

Add this row to the "Stacks & Ports Directory" table (`CLAUDE.md`), keeping the existing rows unchanged:

```
| `wallpaper-scout/` | Wallpaper research/curation bot | 5067 / — | FastAPI + SQLite (Volume `/data`) + Nginx Basic Auth. Topics (search query + purpose(s) + frequency) แจ้งผ่านหน้า dashboard, ค้นรูปจาก Wallhaven API (SFW only) ตาม preset ความละเอียด/สัดส่วนคงที่ 3 แบบ (`mobile`/`laptop`/`pc`) เขียนไฟล์ตรงไปที่ `/volume1/homes/fixhardez/Photos/wallpapers/<purpose>/<topic>/` ให้ Synology Photos auto-index (Folders tab, ไม่ใช้ DSM Photos API). Dedup ด้วย Wallhaven image id เท่านั้น (ไม่มี perceptual hash). Sort: `toplist` ครั้งแรกตอนสร้าง topic แล้วสลับเป็น `date_added` รอบถัดไป. LLM (MiMo primary / Anthropic fallback switch, reuse `shared.llm.*` vault keys) ใช้ขยาย alias คำค้นเท่านั้น (text-only, ไม่มี vision). แจ้งสรุปยอดดาวน์โหลดรายวันผ่าน LINE ครั้งเดียวต่อวัน. **Container `user:` ต้องตรงกับ UID/GID ของ DSM user `fixhardez`** ไม่งั้น synofoto จะไม่เห็นไฟล์ที่เขียนเข้าไป |
```

- [ ] **Step 7: Commit scaffold**

```bash
git add wallpaper-scout/Dockerfile wallpaper-scout/docker-compose.yml wallpaper-scout/requirements.txt wallpaper-scout/app/__init__.py wallpaper-scout/app/http_client.py wallpaper-scout/app/notify.py wallpaper-scout/app/sqlite_backup.py wallpaper-scout/nginx/nginx.conf wallpaper-scout/tests/__init__.py CLAUDE.md
git commit -m "scaffold: wallpaper-scout stack skeleton"
```

---

### Task 2: `db.py` — schema and CRUD

**Files:**
- Create: `wallpaper-scout/app/db.py`
- Test: `wallpaper-scout/tests/test_db.py`

**Interfaces:**
- Consumes: `os.environ["DATA_DIR"]` (default `/data`)
- Produces (used by Tasks 4-6):
  - `init_db() -> None`
  - `get_conn()` — FastAPI dependency, yields `sqlite3.Connection` with `row_factory = sqlite3.Row`
  - `create_topic(query: str, purposes: list[str], frequency_per_day: int, max_new_per_cycle: int) -> int` (returns new topic id)
  - `get_topic(topic_id: int) -> dict | None`
  - `list_topics() -> list[dict]`
  - `update_topic(topic_id: int, **fields) -> None` (accepts any of `query`, `purposes`, `frequency_per_day`, `max_new_per_cycle`, `enabled`)
  - `delete_topic(topic_id: int) -> None`
  - `set_search_terms(topic_id: int, terms: list[str]) -> None`
  - `mark_backfilled(topic_id: int) -> None`
  - `download_exists(topic_id: int, purpose: str, wallhaven_id: str) -> bool`
  - `record_download(topic_id: int, purpose: str, wallhaven_id: str, filename: str) -> None`
  - `daily_download_counts(day: str) -> dict[str, int]` — maps topic `query` → count of downloads with `date(downloaded_at) == day`
  - All dict rows returned to callers have `purposes` and `search_terms` already `json.loads`'d back into a `list[str]` (or `None` for `search_terms` before the first LLM expansion runs).

- [ ] **Step 1: Write the failing tests**

```python
# wallpaper-scout/tests/test_db.py
import json
import os
import sqlite3
import tempfile

import pytest


@pytest.fixture
def db(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmpdir)
    import importlib
    import app.db as db_module
    importlib.reload(db_module)
    db_module.init_db()
    return db_module


def test_create_and_get_topic(db):
    topic_id = db.create_topic("IU", ["mobile", "pc"], frequency_per_day=2, max_new_per_cycle=5)
    topic = db.get_topic(topic_id)
    assert topic["query"] == "IU"
    assert topic["purposes"] == ["mobile", "pc"]
    assert topic["frequency_per_day"] == 2
    assert topic["max_new_per_cycle"] == 5
    assert topic["enabled"] == 1
    assert topic["backfilled"] == 0
    assert topic["search_terms"] is None


def test_list_topics(db):
    db.create_topic("IU", ["mobile"], 1, 5)
    db.create_topic("Genshin Impact", ["laptop", "pc"], 3, 5)
    topics = db.list_topics()
    assert len(topics) == 2
    assert {t["query"] for t in topics} == {"IU", "Genshin Impact"}


def test_update_topic(db):
    topic_id = db.create_topic("IU", ["mobile"], 1, 5)
    db.update_topic(topic_id, enabled=0, frequency_per_day=4)
    topic = db.get_topic(topic_id)
    assert topic["enabled"] == 0
    assert topic["frequency_per_day"] == 4


def test_delete_topic(db):
    topic_id = db.create_topic("IU", ["mobile"], 1, 5)
    db.delete_topic(topic_id)
    assert db.get_topic(topic_id) is None


def test_set_search_terms_and_mark_backfilled(db):
    topic_id = db.create_topic("IU", ["mobile"], 1, 5)
    db.set_search_terms(topic_id, ["IU", "Lee Ji-eun", "아이유"])
    db.mark_backfilled(topic_id)
    topic = db.get_topic(topic_id)
    assert topic["search_terms"] == ["IU", "Lee Ji-eun", "아이유"]
    assert topic["backfilled"] == 1


def test_download_dedup(db):
    topic_id = db.create_topic("IU", ["mobile"], 1, 5)
    assert db.download_exists(topic_id, "mobile", "wallhaven-abc") is False
    db.record_download(topic_id, "mobile", "wallhaven-abc", "wallhaven-abc.jpg")
    assert db.download_exists(topic_id, "mobile", "wallhaven-abc") is True
    # same id under a different purpose is a separate row, not a dedup hit
    assert db.download_exists(topic_id, "pc", "wallhaven-abc") is False


def test_daily_download_counts(db):
    topic_id = db.create_topic("IU", ["mobile"], 1, 5)
    db.record_download(topic_id, "mobile", "wallhaven-abc", "wallhaven-abc.jpg")
    db.record_download(topic_id, "mobile", "wallhaven-def", "wallhaven-def.jpg")
    from datetime import date
    today = date.today().isoformat()
    counts = db.daily_download_counts(today)
    assert counts == {"IU": 2}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd wallpaper-scout && python -m pytest tests/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 3: Write `wallpaper-scout/app/db.py`**

```python
"""SQLite database setup and CRUD for wallpaper-scout."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.environ.get("DATA_DIR", "/data")) / "wallpaper-scout.db"


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS topics (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                query               TEXT    NOT NULL,
                search_terms        TEXT,
                purposes            TEXT    NOT NULL,
                frequency_per_day   INTEGER NOT NULL DEFAULT 1,
                max_new_per_cycle   INTEGER NOT NULL DEFAULT 5,
                enabled             INTEGER NOT NULL DEFAULT 1,
                backfilled          INTEGER NOT NULL DEFAULT 0,
                created_at          TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS downloads (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id        INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
                purpose         TEXT    NOT NULL,
                wallhaven_id    TEXT    NOT NULL,
                filename        TEXT    NOT NULL,
                downloaded_at   TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
                UNIQUE(topic_id, purpose, wallhaven_id)
            );
        """)


@contextmanager
def _conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def get_conn():
    """FastAPI dependency — yields a connection per request."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _row_to_topic(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["purposes"] = json.loads(d["purposes"])
    d["search_terms"] = json.loads(d["search_terms"]) if d["search_terms"] else None
    return d


def create_topic(
    query: str,
    purposes: list[str],
    frequency_per_day: int,
    max_new_per_cycle: int,
) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO topics (query, purposes, frequency_per_day, max_new_per_cycle) "
            "VALUES (?, ?, ?, ?)",
            (query, json.dumps(purposes), frequency_per_day, max_new_per_cycle),
        )
        return cur.lastrowid


def get_topic(topic_id: int) -> dict | None:
    with _conn() as conn:
        row = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
        return _row_to_topic(row) if row else None


def list_topics() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute("SELECT * FROM topics ORDER BY created_at DESC").fetchall()
        return [_row_to_topic(r) for r in rows]


_UPDATABLE = {"query", "purposes", "frequency_per_day", "max_new_per_cycle", "enabled"}


def update_topic(topic_id: int, **fields) -> None:
    updates = {k: v for k, v in fields.items() if k in _UPDATABLE}
    if not updates:
        return
    if "purposes" in updates:
        updates["purposes"] = json.dumps(updates["purposes"])
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    with _conn() as conn:
        conn.execute(
            f"UPDATE topics SET {set_clause} WHERE id = ?",
            (*updates.values(), topic_id),
        )


def delete_topic(topic_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM topics WHERE id = ?", (topic_id,))


def set_search_terms(topic_id: int, terms: list[str]) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE topics SET search_terms = ? WHERE id = ?",
            (json.dumps(terms), topic_id),
        )


def mark_backfilled(topic_id: int) -> None:
    with _conn() as conn:
        conn.execute("UPDATE topics SET backfilled = 1 WHERE id = ?", (topic_id,))


def download_exists(topic_id: int, purpose: str, wallhaven_id: str) -> bool:
    with _conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM downloads WHERE topic_id = ? AND purpose = ? AND wallhaven_id = ?",
            (topic_id, purpose, wallhaven_id),
        ).fetchone()
        return row is not None


def record_download(topic_id: int, purpose: str, wallhaven_id: str, filename: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT INTO downloads (topic_id, purpose, wallhaven_id, filename) VALUES (?, ?, ?, ?)",
            (topic_id, purpose, wallhaven_id, filename),
        )


def daily_download_counts(day: str) -> dict[str, int]:
    with _conn() as conn:
        rows = conn.execute(
            """
            SELECT t.query AS query, COUNT(*) AS n
            FROM downloads d
            JOIN topics t ON t.id = d.topic_id
            WHERE date(d.downloaded_at) = ?
            GROUP BY t.query
            """,
            (day,),
        ).fetchall()
        return {r["query"]: r["n"] for r in rows}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd wallpaper-scout && python -m pytest tests/test_db.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add wallpaper-scout/app/db.py wallpaper-scout/tests/test_db.py
git commit -m "feat(wallpaper-scout): SQLite schema and CRUD for topics/downloads"
```

---

### Task 3: `wallhaven.py` — API client and purpose presets

**Files:**
- Create: `wallpaper-scout/app/wallhaven.py`
- Test: `wallpaper-scout/tests/test_wallhaven.py`

**Interfaces:**
- Consumes: `app.http_client.get(url, **kwargs) -> httpx.Response` (from Task 1's vendored copy)
- Produces (used by Task 5):
  - `PURPOSE_PRESETS: dict[str, dict[str, str]]` — keys `"mobile"`, `"laptop"`, `"pc"`, each `{"ratios": str, "atleast": str}`
  - `search(query_terms: list[str], purpose: str, sorting: str, page: int = 1) -> list[dict]` — each dict has at least `id`, `path`, `file_type` (mirrors Wallhaven's `/search` JSON `data[]` entries)
  - `download_image(url: str) -> bytes`

- [ ] **Step 1: Write the failing tests**

```python
# wallpaper-scout/tests/test_wallhaven.py
import httpx
import pytest

import app.wallhaven as wallhaven


class _FakeResponse:
    def __init__(self, json_data=None, content=b""):
        self._json = json_data
        self.content = content

    def json(self):
        return self._json


def test_purpose_presets_has_three_fixed_keys():
    assert set(wallhaven.PURPOSE_PRESETS) == {"mobile", "laptop", "pc"}
    assert wallhaven.PURPOSE_PRESETS["mobile"]["atleast"] == "1080x1920"
    assert wallhaven.PURPOSE_PRESETS["pc"]["atleast"] == "2560x1440"


def test_search_builds_expected_params(mocker):
    captured = {}

    def fake_get(url, *, params=None, timeout=None, **kwargs):
        captured["url"] = url
        captured["params"] = params
        return _FakeResponse(json_data={"data": [{"id": "abc123", "path": "https://x/abc123.jpg", "file_type": "image/jpeg"}]})

    mocker.patch("app.wallhaven.http_client.get", side_effect=fake_get)

    results = wallhaven.search(["IU", "Lee Ji-eun"], "mobile", "toplist", page=1)

    assert captured["url"] == wallhaven.BASE_URL
    p = captured["params"]
    assert p["categories"] == "111"
    assert p["purity"] == "100"
    assert p["ratios"] == "9x16,9x19.5,9x20"
    assert p["atleast"] == "1080x1920"
    assert p["sorting"] == "toplist"
    assert p["page"] == 1
    assert "IU" in p["q"] and "Lee Ji-eun" in p["q"]
    assert results == [{"id": "abc123", "path": "https://x/abc123.jpg", "file_type": "image/jpeg"}]


def test_search_omits_apikey_when_not_set(mocker, monkeypatch):
    monkeypatch.delenv("WALLHAVEN_API_KEY", raising=False)
    captured = {}

    def fake_get(url, *, params=None, timeout=None, **kwargs):
        captured["params"] = params
        return _FakeResponse(json_data={"data": []})

    mocker.patch("app.wallhaven.http_client.get", side_effect=fake_get)
    wallhaven.search(["IU"], "mobile", "date_added")
    assert "apikey" not in captured["params"]


def test_search_includes_apikey_when_set(mocker, monkeypatch):
    monkeypatch.setenv("WALLHAVEN_API_KEY", "test-key")
    captured = {}

    def fake_get(url, *, params=None, timeout=None, **kwargs):
        captured["params"] = params
        return _FakeResponse(json_data={"data": []})

    mocker.patch("app.wallhaven.http_client.get", side_effect=fake_get)
    wallhaven.search(["IU"], "mobile", "date_added")
    assert captured["params"]["apikey"] == "test-key"


def test_download_image_returns_bytes(mocker):
    mocker.patch("app.wallhaven.http_client.get", return_value=_FakeResponse(content=b"fake-jpeg-bytes"))
    data = wallhaven.download_image("https://x/abc123.jpg")
    assert data == b"fake-jpeg-bytes"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd wallpaper-scout && python -m pytest tests/test_wallhaven.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.wallhaven'`

- [ ] **Step 3: Write `wallpaper-scout/app/wallhaven.py`**

```python
"""Wallhaven public API client — search + image download.

API docs: https://wallhaven.cc/help/api
No auth required; WALLHAVEN_API_KEY (if set) raises rate limits.
"""
from __future__ import annotations

import os

import app.http_client as http_client

BASE_URL = "https://wallhaven.cc/api/v1/search"

PURPOSE_PRESETS: dict[str, dict[str, str]] = {
    "mobile": {"ratios": "9x16,9x19.5,9x20", "atleast": "1080x1920"},
    "laptop": {"ratios": "16x9,16x10", "atleast": "1920x1080"},
    "pc": {"ratios": "16x9,21x9,32x9", "atleast": "2560x1440"},
}


def _build_query(query_terms: list[str]) -> str:
    """Join alias terms with OR so one request covers all aliases."""
    parts = [f'"{t}"' if " " in t else t for t in query_terms]
    return " OR ".join(parts)


def search(query_terms: list[str], purpose: str, sorting: str, page: int = 1) -> list[dict]:
    preset = PURPOSE_PRESETS[purpose]
    params = {
        "q": _build_query(query_terms),
        "categories": "111",
        "purity": "100",
        "ratios": preset["ratios"],
        "atleast": preset["atleast"],
        "sorting": sorting,
        "order": "desc",
        "page": page,
    }
    api_key = os.environ.get("WALLHAVEN_API_KEY", "")
    if api_key:
        params["apikey"] = api_key
    resp = http_client.get(BASE_URL, params=params, timeout=30.0)
    return resp.json().get("data", [])


def download_image(url: str) -> bytes:
    resp = http_client.get(url, timeout=60.0)
    return resp.content
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd wallpaper-scout && python -m pytest tests/test_wallhaven.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add wallpaper-scout/app/wallhaven.py wallpaper-scout/tests/test_wallhaven.py
git commit -m "feat(wallpaper-scout): Wallhaven API client with fixed purpose presets"
```

---

### Task 4: `llm.py` — alias/query expansion

**Files:**
- Create: `wallpaper-scout/app/llm.py`
- Test: `wallpaper-scout/tests/test_llm.py`

**Interfaces:**
- Consumes: `app.http_client.post` (for the MiMo fallback), `anthropic.Anthropic` (for the primary path)
- Produces (used by Task 5): `expand_query(topic: str) -> list[str]` — always returns a non-empty list of strings, first element is always the original `topic` if no aliases were found or all providers failed.

- [ ] **Step 1: Write the failing tests**

```python
# wallpaper-scout/tests/test_llm.py
import json

import app.llm as llm


class _FakeMimoResponse:
    def __init__(self, text):
        self._text = text

    def raise_for_status(self):
        pass

    def json(self):
        return {"choices": [{"message": {"content": self._text}}]}


def test_expand_query_parses_json_array(mocker):
    mocker.patch(
        "app.llm.http_client.post",
        return_value=_FakeMimoResponse(json.dumps(["IU", "Lee Ji-eun", "아이유"])),
    )

    terms = llm.expand_query("IU")
    assert terms == ["IU", "Lee Ji-eun", "아이유"]


def test_expand_query_falls_back_to_topic_on_bad_json(mocker):
    mocker.patch("app.llm.http_client.post", return_value=_FakeMimoResponse("not json"))

    terms = llm.expand_query("Wuthering Waves")
    assert terms == ["Wuthering Waves"]


def test_expand_query_falls_back_to_anthropic_when_mimo_raises(mocker):
    mocker.patch("app.llm.http_client.post", side_effect=RuntimeError("mimo down"))
    fake_client = mocker.Mock()
    fake_client.messages.create.return_value = mocker.Mock(
        content=[mocker.Mock(text=json.dumps(["Genshin Impact", "原神"]))]
    )
    mocker.patch("app.llm.anthropic.Anthropic", return_value=fake_client)

    terms = llm.expand_query("Genshin Impact")
    assert terms == ["Genshin Impact", "原神"]


def test_expand_query_falls_back_to_topic_when_both_providers_raise(mocker):
    mocker.patch("app.llm.http_client.post", side_effect=RuntimeError("mimo down"))
    fake_client = mocker.Mock()
    fake_client.messages.create.side_effect = RuntimeError("anthropic down too")
    mocker.patch("app.llm.anthropic.Anthropic", return_value=fake_client)
    mocker.patch(
        "app.llm._anthropic_retry",
        side_effect=lambda fn, retries=3: (_ for _ in ()).throw(RuntimeError("anthropic down too")),
    )

    terms = llm.expand_query("Genshin Impact")
    assert terms == ["Genshin Impact"]


def test_expand_query_caps_at_five_terms(mocker):
    mocker.patch(
        "app.llm.http_client.post",
        return_value=_FakeMimoResponse(json.dumps(["a", "b", "c", "d", "e", "f", "g"])),
    )

    terms = llm.expand_query("a")
    assert len(terms) == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd wallpaper-scout && python -m pytest tests/test_llm.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.llm'`

- [ ] **Step 3: Write `wallpaper-scout/app/llm.py`**

```python
"""Text-only topic → search-alias expansion.

Provider switch mirrors news-feed/app/summarizer.py's dispatch shape, but
with mimo primary and anthropic fallback (same vault keys, reversed
priority order). No vision/image analysis here —
this only turns a topic string into a small list of alternate search
terms (romanization, alt names) to widen Wallhaven recall.
"""
from __future__ import annotations

import json
import logging
import os
import time

import anthropic

import app.http_client as http_client

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You expand a wallpaper-search topic into alternate search terms "
    "(romanization, translations, well-known alternate names) to widen "
    "search recall on an image site. Respond with ONLY a JSON array of "
    "strings, at most 5 items, including the original term."
)


def _anthropic_retry(fn, retries: int = 3):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            if attempt == retries - 1:
                raise
            wait = 2**attempt
            logger.warning("anthropic retry %d/%d after %ds: %s", attempt + 1, retries, wait, exc)
            time.sleep(wait)


def _expand_anthropic(topic: str, model: str) -> str:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

    def call():
        resp = client.messages.create(
            model=model,
            max_tokens=200,
            system=_SYSTEM,
            messages=[{"role": "user", "content": topic}],
        )
        return resp.content[0].text

    return _anthropic_retry(call)


def _expand_mimo(topic: str, model: str) -> str:
    api_key = os.getenv("MIMO_API_KEY", "")
    base_url = os.getenv("MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1").rstrip("/")

    resp = http_client.post(
        f"{base_url}/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": model,
            "max_tokens": 200,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": topic},
            ],
        },
        timeout=60.0,
        retries=3,
        backoff=1.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _dispatch(provider: str, topic: str, model: str) -> str:
    if provider == "mimo":
        return _expand_mimo(topic, model)
    return _expand_anthropic(topic, model)


def _parse(text: str, topic: str) -> list[str]:
    try:
        data = json.loads(text)
        if isinstance(data, list) and data and all(isinstance(x, str) for x in data):
            return data[:5]
    except (json.JSONDecodeError, TypeError):
        pass
    return [topic]


def expand_query(topic: str) -> list[str]:
    chain = [
        {
            "provider": os.getenv("LLM_PROVIDER", "mimo"),
            "model": os.getenv("LLM_MODEL", "xiaomi/mimo-v2.5"),
        },
        {
            "provider": os.getenv("LLM_FALLBACK_PROVIDER", "anthropic"),
            "model": os.getenv("LLM_FALLBACK_MODEL", "claude-sonnet-4-6"),
        },
    ]
    for slot in chain:
        try:
            text = _dispatch(slot["provider"], topic, slot["model"])
            return _parse(text, topic)
        except Exception as exc:
            logger.warning("expand_query failed provider=%s: %s", slot["provider"], exc)
    return [topic]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd wallpaper-scout && python -m pytest tests/test_llm.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add wallpaper-scout/app/llm.py wallpaper-scout/tests/test_llm.py
git commit -m "feat(wallpaper-scout): LLM alias expansion, mimo/anthropic provider switch"
```

---

### Task 5: `scheduler.py` — per-topic scrape cycle and daily summary

**Files:**
- Create: `wallpaper-scout/app/scheduler.py`
- Test: `wallpaper-scout/tests/test_scheduler.py`

**Interfaces:**
- Consumes: `app.db` (Task 2), `app.wallhaven` (Task 3), `app.llm.expand_query` (Task 4), `app.notify.Notifier`/`LineCreds` (vendored in Task 1)
- Produces (used by Task 6):
  - `run_topic_cycle(topic_id: int) -> None` — the job body; safe to call directly in tests without APScheduler.
  - `send_daily_summary() -> None`
  - `schedule_topic(sched, topic: dict) -> None`
  - `unschedule_topic(sched, topic_id: int) -> None`
  - `start_all(sched) -> None` — schedules every enabled topic plus the daily summary job (`CronTrigger` at `os.environ["DAILY_SUMMARY_TIME"]`, default `09:00`)
  - `slugify(text: str) -> str` — lowercase, non-alnum runs collapsed to a single `-`, stripped of leading/trailing `-`

- [ ] **Step 1: Write the failing tests**

```python
# wallpaper-scout/tests/test_scheduler.py
import os
import tempfile

import pytest


@pytest.fixture
def env(monkeypatch):
    data_dir = tempfile.mkdtemp()
    photos_dir = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", data_dir)
    monkeypatch.setenv("PHOTOS_ROOT", photos_dir)
    import importlib
    import app.db as db_module
    import app.scheduler as scheduler_module
    importlib.reload(db_module)
    importlib.reload(scheduler_module)
    db_module.init_db()
    return scheduler_module, db_module, photos_dir


def test_slugify(env):
    scheduler, _, _ = env
    assert scheduler.slugify("Wuthering Waves") == "wuthering-waves"
    assert scheduler.slugify("IU!!") == "iu"


def test_first_cycle_uses_toplist_and_marks_backfilled(env, mocker):
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("IU", ["mobile"], frequency_per_day=1, max_new_per_cycle=5)

    mocker.patch("app.scheduler.llm.expand_query", return_value=["IU"])
    search_mock = mocker.patch(
        "app.scheduler.wallhaven.search",
        return_value=[{"id": "abc", "path": "https://x/abc.jpg", "file_type": "image/jpeg"}],
    )
    mocker.patch("app.scheduler.wallhaven.download_image", return_value=b"fake-bytes")

    scheduler.run_topic_cycle(topic_id)

    assert search_mock.call_args.args[2] == "toplist"
    topic = db.get_topic(topic_id)
    assert topic["backfilled"] == 1
    assert topic["search_terms"] == ["IU"]
    assert db.download_exists(topic_id, "mobile", "abc") is True

    written = os.path.join(photos_dir, "mobile", "iu", "abc.jpg")
    assert os.path.exists(written)
    with open(written, "rb") as f:
        assert f.read() == b"fake-bytes"


def test_second_cycle_uses_date_added_and_skips_existing(env, mocker):
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("IU", ["mobile"], frequency_per_day=1, max_new_per_cycle=5)
    db.set_search_terms(topic_id, ["IU"])
    db.mark_backfilled(topic_id)
    db.record_download(topic_id, "mobile", "abc", "abc.jpg")

    mocker.patch("app.scheduler.llm.expand_query")  # should not be called again
    search_mock = mocker.patch(
        "app.scheduler.wallhaven.search",
        return_value=[
            {"id": "abc", "path": "https://x/abc.jpg", "file_type": "image/jpeg"},
            {"id": "def", "path": "https://x/def.jpg", "file_type": "image/jpeg"},
        ],
    )
    download_mock = mocker.patch("app.scheduler.wallhaven.download_image", return_value=b"fake-bytes")

    scheduler.run_topic_cycle(topic_id)

    assert search_mock.call_args.args[2] == "date_added"
    scheduler.llm.expand_query.assert_not_called()
    download_mock.assert_called_once_with("https://x/def.jpg")
    assert db.download_exists(topic_id, "mobile", "def") is True


def test_cycle_stops_at_max_new_per_cycle(env, mocker):
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("IU", ["mobile"], frequency_per_day=1, max_new_per_cycle=1)
    db.set_search_terms(topic_id, ["IU"])
    db.mark_backfilled(topic_id)

    mocker.patch(
        "app.scheduler.wallhaven.search",
        return_value=[
            {"id": "one", "path": "https://x/one.jpg", "file_type": "image/jpeg"},
            {"id": "two", "path": "https://x/two.jpg", "file_type": "image/jpeg"},
        ],
    )
    download_mock = mocker.patch("app.scheduler.wallhaven.download_image", return_value=b"fake-bytes")

    scheduler.run_topic_cycle(topic_id)

    download_mock.assert_called_once()
    assert db.download_exists(topic_id, "mobile", "one") is True
    assert db.download_exists(topic_id, "mobile", "two") is False


def test_disabled_topic_is_skipped(env, mocker):
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("IU", ["mobile"], frequency_per_day=1, max_new_per_cycle=5)
    db.update_topic(topic_id, enabled=0)
    search_mock = mocker.patch("app.scheduler.wallhaven.search")

    scheduler.run_topic_cycle(topic_id)

    search_mock.assert_not_called()


def test_send_daily_summary_sends_aggregated_message(env, mocker):
    scheduler, db, photos_dir = env
    topic_id = db.create_topic("IU", ["mobile"], frequency_per_day=1, max_new_per_cycle=5)
    from datetime import date
    today = date.today().isoformat()
    db.record_download(topic_id, "mobile", "abc", "abc.jpg")
    db.record_download(topic_id, "mobile", "def", "def.jpg")

    sent = mocker.patch("app.scheduler.notifier.send")
    scheduler.send_daily_summary()

    assert sent.called
    text = sent.call_args.args[0]
    assert "IU" in text
    assert "2" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd wallpaper-scout && python -m pytest tests/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.scheduler'`

- [ ] **Step 3: Write `wallpaper-scout/app/scheduler.py`**

```python
"""APScheduler jobs: per-topic scrape cycle + daily LINE summary.

Sort strategy per topic: the first cycle after a topic is created runs
`toplist` (grab a good initial batch of existing wallpapers). Every
subsequent cycle runs `date_added` — `toplist` is a near-static ranking,
so a recurring scraper hitting it repeatedly would find zero new results
within days, making the topic's frequency setting pointless.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.jobstores.base import JobLookupError

import app.db as db
import app.llm as llm
import app.wallhaven as wallhaven
from app.notify import LineCreds, Notifier

logger = logging.getLogger(__name__)

_TZ = ZoneInfo(os.environ.get("TZ", "Asia/Bangkok"))
_PHOTOS_ROOT = Path(os.environ.get("PHOTOS_ROOT", "/photos_root"))

notifier = Notifier(
    line=LineCreds(
        token=os.environ.get("WALLPAPER_SCOUT_LINE_ACCESS_TOKEN", ""),
        to=os.environ.get("WALLPAPER_SCOUT_LINE_USER_ID", ""),
    )
    if os.environ.get("WALLPAPER_SCOUT_LINE_ACCESS_TOKEN") and os.environ.get("WALLPAPER_SCOUT_LINE_USER_ID")
    else None,
)


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug or "topic"


def run_topic_cycle(topic_id: int) -> None:
    topic = db.get_topic(topic_id)
    if topic is None or not topic["enabled"]:
        return

    if topic["search_terms"]:
        search_terms = topic["search_terms"]
    else:
        search_terms = llm.expand_query(topic["query"])
        db.set_search_terms(topic_id, search_terms)

    sorting = "toplist" if not topic["backfilled"] else "date_added"
    slug = slugify(topic["query"])

    for purpose in topic["purposes"]:
        _run_purpose(topic_id, purpose, search_terms, sorting, topic["max_new_per_cycle"], slug)

    if not topic["backfilled"]:
        db.mark_backfilled(topic_id)


def _run_purpose(
    topic_id: int,
    purpose: str,
    search_terms: list[str],
    sorting: str,
    max_new: int,
    slug: str,
) -> None:
    results = wallhaven.search(search_terms, purpose, sorting)
    new_count = 0
    for item in results:
        if new_count >= max_new:
            break
        wallhaven_id = item["id"]
        if db.download_exists(topic_id, purpose, wallhaven_id):
            continue
        try:
            image_bytes = wallhaven.download_image(item["path"])
        except Exception as exc:
            logger.warning("download failed topic=%s purpose=%s id=%s: %s", topic_id, purpose, wallhaven_id, exc)
            continue
        ext = item["path"].rsplit(".", 1)[-1]
        dest_dir = _PHOTOS_ROOT / purpose / slug
        dest_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{wallhaven_id}.{ext}"
        (dest_dir / filename).write_bytes(image_bytes)
        db.record_download(topic_id, purpose, wallhaven_id, filename)
        new_count += 1


def send_daily_summary() -> None:
    today = date.today().isoformat()
    counts = db.daily_download_counts(today)
    total = sum(counts.values())
    if total == 0:
        return
    breakdown = ", ".join(f"{query} ({n})" for query, n in counts.items())
    text = f"วันนี้ดาวน์โหลดรูปใหม่ {total} รูป: {breakdown}"
    notifier.send(text)


def schedule_topic(sched, topic: dict) -> None:
    job_id = f"topic-{topic['id']}"
    seconds = max(1, int(86400 / topic["frequency_per_day"]))
    sched.add_job(
        run_topic_cycle,
        trigger=IntervalTrigger(seconds=seconds),
        args=[topic["id"]],
        id=job_id,
        replace_existing=True,
        # IntervalTrigger's default first fire is now+interval — without this,
        # a freshly created topic (or one re-enabled) would show zero images
        # for up to a full interval, defeating the toplist backfill-on-create design.
        next_run_time=datetime.now(_TZ),
    )


def unschedule_topic(sched, topic_id: int) -> None:
    try:
        sched.remove_job(f"topic-{topic_id}")
    except JobLookupError:
        pass


def start_all(sched) -> None:
    for topic in db.list_topics():
        if topic["enabled"]:
            schedule_topic(sched, topic)

    hour, minute = os.environ.get("DAILY_SUMMARY_TIME", "09:00").split(":")
    sched.add_job(
        send_daily_summary,
        trigger=CronTrigger(hour=int(hour), minute=int(minute), timezone=_TZ),
        id="daily-summary",
        replace_existing=True,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd wallpaper-scout && python -m pytest tests/test_scheduler.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add wallpaper-scout/app/scheduler.py wallpaper-scout/tests/test_scheduler.py
git commit -m "feat(wallpaper-scout): per-topic scrape cycle, two-phase sort, daily summary"
```

---

### Task 6: `main.py` — FastAPI app, topic CRUD API, static mount

**Files:**
- Create: `wallpaper-scout/app/main.py`
- Create: `wallpaper-scout/app/static/index.html` (placeholder stub — Task 7 overwrites it with the real dashboard)
- Test: `wallpaper-scout/tests/test_main.py`

**Interfaces:**
- Consumes: `app.db` (Task 2), `app.scheduler` (Task 5)
- Produces: FastAPI app importable as `app.main:app` (matches `Dockerfile` CMD from Task 1). Routes:
  - `GET /api/status -> {"status": "ok"}`
  - `GET /api/topics -> list[dict]` (each dict = full topic row plus `downloaded_today: int`)
  - `POST /api/topics {query, purposes, frequency_per_day, max_new_per_cycle} -> dict` (201, full topic row)
  - `PATCH /api/topics/{topic_id} {enabled?, frequency_per_day?, max_new_per_cycle?, purposes?, query?} -> dict`
  - `DELETE /api/topics/{topic_id} -> 204`

- [ ] **Step 1: Write the failing tests**

```python
# wallpaper-scout/tests/test_main.py
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch, mocker):
    monkeypatch.setenv("DATA_DIR", tempfile.mkdtemp())
    monkeypatch.setenv("PHOTOS_ROOT", tempfile.mkdtemp())
    mocker.patch("app.scheduler.llm.expand_query", return_value=["stub"])
    import importlib
    import app.db as db_module
    import app.scheduler as scheduler_module
    import app.main as main_module
    importlib.reload(db_module)
    importlib.reload(scheduler_module)
    importlib.reload(main_module)
    with TestClient(main_module.app) as c:
        yield c


def test_status(client):
    resp = client.get("/api/status")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_create_list_topic(client):
    resp = client.post(
        "/api/topics",
        json={"query": "IU", "purposes": ["mobile", "pc"], "frequency_per_day": 2, "max_new_per_cycle": 5},
    )
    assert resp.status_code == 201
    created = resp.json()
    assert created["query"] == "IU"
    assert created["purposes"] == ["mobile", "pc"]

    listed = client.get("/api/topics").json()
    assert len(listed) == 1
    assert listed[0]["query"] == "IU"
    assert listed[0]["downloaded_today"] == 0


def test_patch_topic(client):
    created = client.post(
        "/api/topics",
        json={"query": "IU", "purposes": ["mobile"], "frequency_per_day": 1, "max_new_per_cycle": 5},
    ).json()

    resp = client.patch(f"/api/topics/{created['id']}", json={"enabled": False, "frequency_per_day": 4})
    assert resp.status_code == 200
    assert resp.json()["enabled"] == 0
    assert resp.json()["frequency_per_day"] == 4


def test_delete_topic(client):
    created = client.post(
        "/api/topics",
        json={"query": "IU", "purposes": ["mobile"], "frequency_per_day": 1, "max_new_per_cycle": 5},
    ).json()

    resp = client.delete(f"/api/topics/{created['id']}")
    assert resp.status_code == 204
    assert client.get("/api/topics").json() == []


def test_get_dashboard_static_index(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd wallpaper-scout && python -m pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Write `wallpaper-scout/app/main.py`**

```python
"""Wallpaper Scout — FastAPI app: topic CRUD + dashboard."""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import app.db as db
import app.scheduler as scheduler

_STATIC_DIR = Path(__file__).parent / "static"
_sched = BackgroundScheduler()


@asynccontextmanager
async def _lifespan(_app: FastAPI):
    db.init_db()
    scheduler.start_all(_sched)
    _sched.start()
    yield
    _sched.shutdown(wait=False)


app = FastAPI(lifespan=_lifespan)


class TopicCreate(BaseModel):
    query: str
    purposes: list[str]
    frequency_per_day: int = 1
    max_new_per_cycle: int = 5


class TopicUpdate(BaseModel):
    query: str | None = None
    purposes: list[str] | None = None
    frequency_per_day: int | None = None
    max_new_per_cycle: int | None = None
    enabled: bool | None = None


def _with_today_count(topic: dict) -> dict:
    today = date.today().isoformat()
    topic["downloaded_today"] = db.daily_download_counts(today).get(topic["query"], 0)
    return topic


@app.get("/api/status")
def status():
    return {"status": "ok"}


@app.get("/api/topics")
def list_topics():
    return [_with_today_count(t) for t in db.list_topics()]


@app.post("/api/topics", status_code=201)
def create_topic(payload: TopicCreate):
    topic_id = db.create_topic(payload.query, payload.purposes, payload.frequency_per_day, payload.max_new_per_cycle)
    topic = db.get_topic(topic_id)
    scheduler.schedule_topic(_sched, topic)
    return _with_today_count(topic)


@app.patch("/api/topics/{topic_id}")
def update_topic(topic_id: int, payload: TopicUpdate):
    topic = db.get_topic(topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="topic not found")

    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    if "enabled" in fields:
        fields["enabled"] = int(fields["enabled"])
    db.update_topic(topic_id, **fields)

    updated = db.get_topic(topic_id)
    if updated["enabled"]:
        scheduler.schedule_topic(_sched, updated)
    else:
        scheduler.unschedule_topic(_sched, topic_id)
    return _with_today_count(updated)


@app.delete("/api/topics/{topic_id}", status_code=204)
def delete_topic(topic_id: int):
    scheduler.unschedule_topic(_sched, topic_id)
    db.delete_topic(topic_id)
    return Response(status_code=204)


app.mount("/", StaticFiles(directory=str(_STATIC_DIR), html=True), name="static")
```

Create a placeholder `wallpaper-scout/app/static/index.html` so `StaticFiles(html=True)` has something to serve (Task 7 replaces this content with the real dashboard — this stub only exists so this task's suite is green on its own):

```html
<!DOCTYPE html>
<html>
<head><title>Wallpaper Scout</title></head>
<body>Wallpaper Scout dashboard — placeholder, replaced in Task 7.</body>
</html>
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd wallpaper-scout && python -m pytest tests/test_main.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add wallpaper-scout/app/main.py wallpaper-scout/app/static/index.html wallpaper-scout/tests/test_main.py
git commit -m "feat(wallpaper-scout): FastAPI topic CRUD API and scheduler wiring"
```

---

### Task 7: Dashboard static UI

**Files:**
- Modify: `wallpaper-scout/app/static/index.html` (Task 6 created a placeholder stub — replace its content below)
- Create: `wallpaper-scout/app/static/app.js`
- Create: `wallpaper-scout/app/static/style.css`

**Interfaces:**
- Consumes: Task 6's `/api/topics` (GET/POST/PATCH/DELETE)
- No automated test — matches this repo's convention (`friendly-reminder/app/static` etc. are also verified manually in-browser, not via pytest). Verify manually per Step 4 below.

- [ ] **Step 1: Write `wallpaper-scout/app/static/index.html`**

```html
<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Wallpaper Scout</title>
<link rel="stylesheet" href="/style.css" />
</head>
<body>
<h1>Wallpaper Scout</h1>

<form id="topic-form">
  <input type="text" id="query" placeholder="เช่น IU, Wuthering Waves" required />
  <label><input type="checkbox" name="purpose" value="mobile" /> Mobile</label>
  <label><input type="checkbox" name="purpose" value="laptop" /> Laptop</label>
  <label><input type="checkbox" name="purpose" value="pc" /> PC</label>
  <label>รอบ/วัน <input type="number" id="frequency" value="1" min="1" max="24" /></label>
  <label>รูป/รอบ <input type="number" id="max_new" value="5" min="1" max="50" /></label>
  <button type="submit">เพิ่ม Topic</button>
</form>

<table id="topics-table">
  <thead>
    <tr><th>Query</th><th>Purpose</th><th>รอบ/วัน</th><th>รูป/รอบ</th><th>วันนี้</th><th>สถานะ</th><th></th></tr>
  </thead>
  <tbody></tbody>
</table>

<script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Write `wallpaper-scout/app/static/app.js`**

```javascript
async function loadTopics() {
  const res = await fetch("/api/topics");
  const topics = await res.json();
  const tbody = document.querySelector("#topics-table tbody");
  tbody.innerHTML = "";
  for (const t of topics) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${t.query}</td>
      <td>${t.purposes.join(", ")}</td>
      <td>${t.frequency_per_day}</td>
      <td>${t.max_new_per_cycle}</td>
      <td>${t.downloaded_today}</td>
      <td>${t.enabled ? "เปิด" : "หยุด"}</td>
      <td>
        <button data-action="toggle" data-id="${t.id}" data-enabled="${t.enabled}">${t.enabled ? "หยุด" : "เปิด"}</button>
        <button data-action="delete" data-id="${t.id}">ลบ</button>
      </td>`;
    tbody.appendChild(tr);
  }
}

document.getElementById("topic-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const purposes = Array.from(document.querySelectorAll('input[name="purpose"]:checked')).map((c) => c.value);
  if (purposes.length === 0) {
    alert("เลือกอย่างน้อย 1 purpose");
    return;
  }
  await fetch("/api/topics", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      query: document.getElementById("query").value,
      purposes,
      frequency_per_day: Number(document.getElementById("frequency").value),
      max_new_per_cycle: Number(document.getElementById("max_new").value),
    }),
  });
  e.target.reset();
  loadTopics();
});

document.querySelector("#topics-table tbody").addEventListener("click", async (e) => {
  const btn = e.target.closest("button");
  if (!btn) return;
  const id = btn.dataset.id;
  if (btn.dataset.action === "delete") {
    await fetch(`/api/topics/${id}`, { method: "DELETE" });
  } else if (btn.dataset.action === "toggle") {
    const enabled = btn.dataset.enabled === "true";
    await fetch(`/api/topics/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: !enabled }),
    });
  }
  loadTopics();
});

loadTopics();
```

- [ ] **Step 3: Write `wallpaper-scout/app/static/style.css`**

```css
body { font-family: system-ui, sans-serif; max-width: 800px; margin: 2rem auto; padding: 0 1rem; }
form { display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: center; margin-bottom: 2rem; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 0.5rem; border-bottom: 1px solid #ddd; }
button { cursor: pointer; }
```

- [ ] **Step 4: Manual verification**

```bash
cd wallpaper-scout
docker compose up --build
```

Open `http://localhost:8000/` (or via nginx at `http://localhost:5067/` once `.htpasswd` exists — see Task 8) in a browser. Add a topic, confirm it appears in the table, toggle it off/on, delete it. Confirm `test_get_dashboard_static_index` (Task 6) now passes:

Run: `cd wallpaper-scout && python -m pytest tests/test_main.py -v`
Expected: PASS (5 tests, all green now that `static/index.html` exists)

- [ ] **Step 5: Commit**

```bash
git add wallpaper-scout/app/static
git commit -m "feat(wallpaper-scout): dashboard UI for topic CRUD"
```

---

### Task 8: Secrets, docs, and NAS deployment

**Files:**
- Create: `wallpaper-scout/secrets.manifest.yaml`
- Create: `wallpaper-scout/README.md`
- Create: `wallpaper-scout/.notes/00_INDEX.md`
- Create: `wallpaper-scout/.notes/daily_log.md`
- Modify: root `README.md`

**Interfaces:** none (deployment/config only — no new code).

- [ ] **Step 1: Write `wallpaper-scout/secrets.manifest.yaml`**

```yaml
env:
  NAS_PHOTOS_WALLPAPERS_PATH:         stacks.wallpaper_scout.photos_path
  NAS_WALLPAPER_SCOUT_DATA_PATH:      stacks.wallpaper_scout.data_path
  PHOTOS_UID:                         stacks.wallpaper_scout.photos_uid
  PHOTOS_GID:                         stacks.wallpaper_scout.photos_gid
  ANTHROPIC_API_KEY:                  shared.llm.anthropic_api_key
  MIMO_API_KEY:                       shared.llm.mimo_api_key
  WALLHAVEN_API_KEY:                  stacks.wallpaper_scout.wallhaven_api_key
  WALLPAPER_SCOUT_LINE_ACCESS_TOKEN:  stacks.wallpaper_scout.line.access_token
  WALLPAPER_SCOUT_LINE_USER_ID:       stacks.wallpaper_scout.line.user_id

literals:
  LLM_PROVIDER:           mimo
  LLM_MODEL:              xiaomi/mimo-v2.5
  LLM_FALLBACK_PROVIDER:  anthropic
  LLM_FALLBACK_MODEL:     claude-sonnet-4-6
  MIMO_BASE_URL:          https://token-plan-sgp.xiaomimimo.com/v1
  DAILY_SUMMARY_TIME:     "09:00"
  DATA_DIR:               /data
  PHOTOS_ROOT:            /photos_root
```

`stacks.wallpaper_scout.wallhaven_api_key` may be left as an empty string in the vault — Wallhaven works unauthenticated (Task 3 already handles the empty-key case by omitting the `apikey` param).

- [ ] **Step 2: Determine the NAS user's UID/GID and add vault entries**

SSH to the NAS (per this repo's `nas_ssh` memory: port 2222, key `~/.ssh/id_ed25519`) and run:

```bash
ssh -p 2222 <NAS_USER>@<NAS_HOST> "id fixhardez"
```

Expected output like `uid=1026(fixhardez) gid=100(users) groups=...`. Take the numeric `uid` and `gid` values.

Then:

```bash
make edit-vault
```

Add (replacing `<uid>`/`<gid>` with the real numbers from the `id` output):

```yaml
stacks:
  wallpaper_scout:
    photos_path: /volume1/homes/fixhardez/Photos/wallpapers
    data_path: /volume2/docker/wallpaper-scout/data
    photos_uid: "<uid>"
    photos_gid: "<gid>"
    wallhaven_api_key: ""
    line:
      access_token: <real LINE channel access token>
      user_id: <real LINE user/group id>
```

- [ ] **Step 3: Pre-create the host wallpapers and data directories with correct ownership**

Bind-mounting a host path that doesn't exist yet creates it owned by root, which the container (running as `fixhardez`'s uid via `user:` in `docker-compose.yml`) then can't write into. This applies to BOTH bind mounts in `docker-compose.yml` — `/photos_root` (obviously) and `/data` (its SQLite file). A named volume for `/data` would silently keep root ownership since Docker only chowns a fresh named volume to the image's build-time owner, which is unknown here (no baked-in uid) — hence `/data` is a bind mount too, pre-created the same way. Pre-create both as the NAS admin user before first deploy:

```bash
ssh -p 2222 <NAS_USER>@<NAS_HOST> "sudo mkdir -p /volume1/homes/fixhardez/Photos/wallpapers /volume2/docker/wallpaper-scout/data && sudo chown fixhardez:users /volume1/homes/fixhardez/Photos/wallpapers /volume2/docker/wallpaper-scout/data"
```

- [ ] **Step 4: Create the nginx basic-auth password file**

Not part of the vault/secrets pipeline (matches `friendly-reminder`'s precedent — see its `.notes/00_INDEX.md` "Gaps/TODOs" entry):

```bash
htpasswd -c wallpaper-scout/nginx/.htpasswd <basic-auth-username>
```

This file is gitignored (`.htpasswd` is in root `.gitignore`) — it must be created locally before `./scripts/deploy.sh` (which tars the project and ships it, including this file, over SSH).

- [ ] **Step 5: Render secrets and run repo-level tests**

```bash
make secrets
make test
```

Expected: `wallpaper-scout/.env` is generated, `make test` passes (includes `tests/test_shared_sync.py` confirming the vendored `http_client.py`/`notify.py`/`sqlite_backup.py` copies match `shared/`).

- [ ] **Step 6: Write `wallpaper-scout/README.md`**

```markdown
# Wallpaper Scout

Research + curate wallpapers from Wallhaven into Synology Photos, split by purpose (mobile/laptop/pc) and topic.

## How it works

1. Add a "topic" (a search term like `IU` or `Wuthering Waves`) via the dashboard, choosing which purpose(s) apply and how many times/day to scrape.
2. On first run for a topic, an LLM (MiMo primary, Anthropic fallback) expands the topic into a few alias search terms (romanization, alt names) to widen Wallhaven recall.
3. Each scheduled cycle searches Wallhaven (SFW only) for that topic+purpose, using a hardcoded ratio/resolution preset per purpose, and downloads up to `max_new_per_cycle` images it hasn't downloaded before (Wallhaven's own image ID is the dedup key).
4. Images land in `/photos_root/<purpose>/<topic-slug>/<wallhaven-id>.<ext>`, bind-mounted to `/volume1/homes/fixhardez/Photos/wallpapers/...` on the NAS — Synology Photos auto-indexes this under its "Folders" tab (not "Albums" — no DSM API/login used anywhere in this stack).
5. Once/day, a LINE message summarizes how many new images were downloaded, broken down by topic.

## Known limitations (v1)

- Celebrity/idol topics are best-effort: Wallhaven's `people` category skews model/cosplay and idol tagging is thin, so a niche celebrity topic may return few or no results under the SFW+resolution filters.
- No perceptual-hash dedup — only exact Wallhaven-ID dedup. A different upload of visually-identical art won't be caught.
- No auto-delete/retention — downloaded images are kept forever; storage is bounded only by how many topics are enabled and their frequency/per-cycle-cap settings.

## Ports

| Context | Port |
|---|---|
| Container internal | 8000 |
| NAS host (LAN, via nginx basic auth) | 5067 |

## Deploy checklist

See `docs/superpowers/plans/2026-07-01-wallpaper-scout-stack.md` Task 8 for the one-time NAS setup (fixhardez UID/GID lookup, wallpapers directory pre-creation, `nginx/.htpasswd`).
```

- [ ] **Step 7: Write `wallpaper-scout/.notes/00_INDEX.md`**

```markdown
# Wallpaper Scout — Project Index (Memory Blueprint)

> อัปเดตล่าสุด: 2026-07-01 (initial build)
> ใช้ไฟล์นี้เป็น cold-start memory ก่อนเริ่มงานทุกครั้ง

## Overview

FastAPI stack ที่ให้ผู้ใช้ลงทะเบียน "topic" (คำค้น เช่น "IU", "Wuthering Waves") พร้อมระบุ purpose (mobile/laptop/pc wallpaper), scrape รูปจาก Wallhaven API (SFW only) ตาม preset สัดส่วน/ความละเอียดคงที่ เขียนไฟล์ตรงเข้า `/volume1/homes/fixhardez/Photos/wallpapers/<purpose>/<topic>/` ให้ Synology Photos auto-index (ไม่ใช้ DSM Photos API เลย)

## Tech Stack

| Component | Detail |
|---|---|
| Runtime | Python 3.12 · FastAPI · Uvicorn |
| Database | SQLite — `/data/wallpaper-scout.db` |
| Image source | Wallhaven public API (`https://wallhaven.cc/api/v1/search`) |
| LLM | MiMo (`xiaomi/mimo-v2.5`) primary, Anthropic (`claude-sonnet-4-6`) fallback — text-only alias expansion, no vision |
| Scheduler | APScheduler `BackgroundScheduler` — one `IntervalTrigger` job per topic + one daily `CronTrigger` summary job |
| Frontend | Vanilla JS SPA |
| Auth | Nginx Basic Auth sidecar (LAN-only, no public HTTPS proxy — no inbound webhook needed) |

## Ports

| Context | Port |
|---|---|
| Container internal | `8000` |
| NAS host (LAN) | `5067` |

## Key design decisions

- **Dedup:** exact Wallhaven-ID only, `UNIQUE(topic_id, purpose, wallhaven_id)` in SQLite. No perceptual hashing.
- **Sort:** `toplist` once per topic (first cycle, `backfilled=0`), then `date_added` forever after — `toplist` is near-static and would starve a recurring scrape of new results.
- **Purpose presets are hardcoded**, not user-configurable: `mobile` (portrait, ≥1080x1920), `laptop` (16:9/16:10, ≥1920x1080), `pc` (16:9/21:9/32:9, ≥2560x1440).
- **No DSM Photos API** — plain filesystem writes only, to avoid the DSM auto-block gotcha documented in root `CLAUDE.md`. Container `user:` must match host `fixhardez` UID/GID or synofoto won't index the files.
- **Retention:** keep forever, no cleanup job (unlike torrentwatch's 7-day inbox retention — this is a keep collection, not a transient inbox).

## Gaps / TODOs

- `nginx/.htpasswd` created manually, not via vault (`htpasswd -c nginx/.htpasswd <user>`).
- Celebrity/people topic coverage on Wallhaven not yet smoke-tested against the live API — first few days of real usage should confirm whether e.g. "IU" returns enough SFW+portrait results to be useful.
- Perceptual-hash near-dup detection deferred — revisit only if exact-ID dedup proves insufficient in practice.
```

- [ ] **Step 8: Write `wallpaper-scout/.notes/daily_log.md`**

```markdown
# Daily Log

## 2026-07-01
- Initial build: db schema (topics/downloads), Wallhaven client with 3 fixed purpose presets, LLM alias-expansion (mimo primary/anthropic fallback switch), APScheduler per-topic cycle with two-phase sort (toplist backfill → date_added), FastAPI CRUD + dashboard, nginx basic-auth sidecar.
- Deploy checklist: looked up `fixhardez` UID/GID on NAS, pre-created `/volume1/homes/fixhardez/Photos/wallpapers`, added vault entries under `stacks.wallpaper_scout.*`, created `nginx/.htpasswd`.
```

- [ ] **Step 9: Update root `README.md` stacks table**

Add a row for `wallpaper-scout/` matching the row already added to `CLAUDE.md` in Task 1 Step 6 (check the exact table format in root `README.md` first — copy its column structure, don't assume it matches `CLAUDE.md`'s table verbatim).

- [ ] **Step 10: Deploy**

```bash
./scripts/deploy.sh
```

Then in DSM → Container Manager → Project → Create, point to `/volume2/docker/wallpaper-scout`, matching how every other stack in this repo is brought up on the NAS.

- [ ] **Step 11: Verify Synology Photos indexing end-to-end**

Add one real topic via the dashboard (`http://<NAS_HOST>:5067/`, e.g. query=`Genshin Impact`, purpose=`mobile`), wait for the first scheduled cycle (or trigger it manually via `docker exec wallpaper-scout python -c "import app.scheduler as s; s.run_topic_cycle(1)"`), then:

```bash
ssh -p 2222 <NAS_USER>@<NAS_HOST> "ls -la /volume1/homes/fixhardez/Photos/wallpapers/mobile/genshin-impact/"
```

Confirm files are owned by `fixhardez` (not root), then open the Synology Photos app/web UI as `fixhardez` and confirm the `wallpapers/mobile/genshin-impact` folder appears under the **Folders** tab within a minute or two. If files exist on disk but don't appear in Photos, check DSM's indexing service status before assuming the app code is at fault — this is a DSM-side indexing latency/permissions issue, not a code bug.

- [ ] **Step 12: Commit docs**

```bash
git add wallpaper-scout/secrets.manifest.yaml wallpaper-scout/README.md wallpaper-scout/.notes README.md
git commit -m "docs(wallpaper-scout): README, notes, secrets manifest, root README stacks table"
```

---

## Self-Review Notes

- **Spec coverage:** curation-not-generation (Task 3), Wallhaven source + SFW purity + 3 hardcoded purpose presets (Task 3), LLM text-only alias expansion + mimo-primary/anthropic-fallback reuse (Task 4), celebrity best-effort documented as a limitation (Task 8 README + `.notes`), filesystem-drop delivery + no DSM API + UID/GID gotcha (Tasks 1, 5, 8), purpose-first folder layout (Task 5 `_run_purpose`), two-phase sort (Task 5), single per-cycle quota (Task 5/2), exact-ID dedup (Task 2/5), keep-forever retention (no cleanup job anywhere in the plan — intentional), dashboard intake (Tasks 6-7), daily-only LINE summary (Task 5) — all covered.
- **Placeholder scan:** no TBD/TODO markers in code steps; every step has complete, runnable code.
- **Type consistency checked:** `db.get_topic`/`list_topics` return `purposes`/`search_terms` already decoded to `list[str]`/`None` — `scheduler.py` and `main.py` consume them as such (no double-`json.loads`). `wallhaven.search(query_terms, purpose, sorting, page=1)` signature matches every call site in `scheduler.py` and `test_wallhaven.py`. `expand_query(topic: str) -> list[str]` signature matches its one call site in `scheduler.run_topic_cycle`.
