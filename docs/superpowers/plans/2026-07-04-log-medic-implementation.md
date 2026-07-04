# log-medic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `log-medic/`, a single Python 3.12 FastAPI+SQLite+APScheduler stack that tails Docker container logs on the NAS, fingerprints WARN/ERROR lines, gates them through a 5-step safety pipeline, hands qualifying events to headless Claude Code for root-cause analysis, and — only for `stable`-maturity containers with an explicit opt-in flag — opens a GitHub PR with a proposed fix (never auto-merged).

**Architecture:** One asyncio task per monitored container streams logs via `docker-py` (blocking I/O bridged through `asyncio.to_thread`, since docker-py, sqlite3, subprocess/git, and `claude -p` are all blocking anyway — this satisfies "asyncio task per container" from the approved design while avoiding an unnecessary async rewrite of blocking libraries). Every matched line runs through `gate.py`'s ordered checks, then `analyzer.py`'s two Claude Code phases, notified via a vendored copy of `shared/notify.py` (Telegram only, reusing news-feed's bot). Dashboard + `/api/*` sit behind an nginx Basic-Auth sidecar, following the `friendly-reminder` pattern.

**Tech Stack:** Python 3.12, FastAPI, `docker` (docker-py SDK), APScheduler, stdlib `sqlite3` (no ORM), stdlib `urllib` (via vendored `notify.py`), `claude` CLI (via MiMo's Anthropic-compatible proxy), `git`/`gh` CLI subprocess calls, nginx:alpine sidecar.

## Global Constraints

- Port: internal 5070, host 15070 (nginx-exposed only; the `log-medic` app service is not host-published).
- All log-medic implementation commits land on branch `feat/log-medic`, never directly on `main`. Merge to `main` only after the spec's Definition of Done passes end-to-end on the NAS.
- No ORM — raw `sqlite3` with `row_factory = sqlite3.Row`, matching `wallpaper-scout`/`news-feed`.
- `shared/notify.py` is vendored verbatim (copy, not rewritten) into `log-medic/app/notify.py`; `tests/test_shared_sync.py` at the repo root auto-discovers it via `git ls-files` once committed — no Makefile change needed.
- Docker socket mounted read-only (`/var/run/docker.sock:ro`); the persistent git clone lives at `/volume2/docker/log-medic/workspaces/` (bind-mounted to `/workspaces` in the container), set up once outside the app, `git fetch` only — the app never runs `git clone`.
- Config literals with exact defaults (from the spec): `ENABLE_FIX_RUNNER=false`, `DAILY_QUOTA=5`, `COOLDOWN_HOURS=6`, `GRACE_PERIOD_MINUTES=20`, `STORM_THRESHOLD_PER_HOUR=10`, `REPO_IDLE_HOURS=2`.
- New vault secrets (add via `make edit-vault`, never edit `vault.sops.yaml` directly): `stacks.log_medic.dashboard.{user,password}`, `stacks.log_medic.github_token`.
- No auto-merge, ever. Phase 2 (fix + PR) requires BOTH `maturity=stable` AND `ENABLE_FIX_RUNNER=true`.
- `nginx/.htpasswd` is gitignored (root `.gitignore` already covers `.htpasswd` globally) and generated manually once via `htpasswd -c log-medic/nginx/.htpasswd <user>` before first deploy — same as `friendly-reminder`, documented as a `.notes/00_INDEX.md` gap, not automated.

---

### Task 1: Scaffolding — branch, Dockerfile, compose, manifest, db schema

**Files:**
- Create: `log-medic/Dockerfile`
- Create: `log-medic/requirements.txt`
- Create: `log-medic/docker-compose.yml`
- Create: `log-medic/secrets.manifest.yaml`
- Create: `log-medic/.env.example`
- Create: `log-medic/nginx/nginx.conf`
- Create: `log-medic/app/__init__.py`
- Create: `log-medic/app/db.py`
- Create: `log-medic/tests/test_db.py`
- Create: `log-medic/.notes/00_INDEX.md`

**Interfaces:**
- Produces: `db.DATA_DIR`, `db.DB_PATH`, `db.get_conn(db_path=None) -> sqlite3.Connection`, `db.init_db(conn) -> None`, `db.list_monitored_containers(conn) -> list[sqlite3.Row]`, `db.get_monitored_container(conn, name) -> sqlite3.Row | None`, `db.upsert_monitored_container(conn, name, repo, subdir, maturity, notify_only, paused, regex_override) -> None`, `db.delete_monitored_container(conn, name) -> None`, `db.event_exists(conn, fingerprint, container) -> bool`, `db.record_event(conn, fingerprint, container, status, gate_reason=None, now=None) -> None`, `db.update_event_status(conn, fingerprint, container, status, gate_reason=None, analysis=None, pr_url=None) -> None`, `db.get_recent_events(conn, limit=50, container=None) -> list[sqlite3.Row]`, `db.get_today_quota(conn) -> int`, `db.increment_quota(conn) -> None`, `db.write_audit(conn, action, payload) -> None`.

- [ ] **Step 1: Write the failing test for schema + monitored_containers CRUD**

```python
# log-medic/tests/test_db.py
import os
import tempfile

import pytest


@pytest.fixture
def conn(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmpdir)
    import importlib
    import app.db as db_module
    importlib.reload(db_module)
    c = db_module.get_conn(os.path.join(tmpdir, "test.db"))
    db_module.init_db(c)
    return c


def test_upsert_and_list_containers(conn):
    import app.db as db
    db.upsert_monitored_container(conn, "torrentwatch", "/workspaces/repo", "torrentwatch", "stable", 0, 0, None)
    rows = db.list_monitored_containers(conn)
    assert len(rows) == 1
    assert rows[0]["name"] == "torrentwatch"
    assert rows[0]["maturity"] == "stable"


def test_upsert_is_idempotent_update(conn):
    import app.db as db
    db.upsert_monitored_container(conn, "x", None, None, "dev", 1, 0, None)
    db.upsert_monitored_container(conn, "x", None, None, "staging", 1, 1, None)
    row = db.get_monitored_container(conn, "x")
    assert row["maturity"] == "staging"
    assert row["paused"] == 1


def test_delete_container(conn):
    import app.db as db
    db.upsert_monitored_container(conn, "x", None, None, "dev", 0, 0, None)
    db.delete_monitored_container(conn, "x")
    assert db.get_monitored_container(conn, "x") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd log-medic && python -m pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db'` (or `app` package missing)

- [ ] **Step 3: Create the scaffolding files**

```python
# log-medic/app/__init__.py
```

```dockerfile
# log-medic/Dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && curl -fsSL -o /tmp/gh.tar.gz https://github.com/cli/cli/releases/download/v2.63.2/gh_2.63.2_linux_amd64.tar.gz \
    && tar -xz -C /usr/local --strip-components=2 -f /tmp/gh.tar.gz gh_2.63.2_linux_amd64/bin/gh \
    && rm -f /tmp/gh.tar.gz \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/
COPY prompts/ ./prompts/
COPY config.yaml .

RUN mkdir -p /data /workspaces

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "5070"]
```

```text
# log-medic/requirements.txt
fastapi==0.115.5
uvicorn[standard]==0.32.1
apscheduler==3.10.4
docker==7.1.0
pyyaml==6.0.2

pytest==8.3.4
pytest-mock==3.14.0
```

```yaml
# log-medic/docker-compose.yml
services:
  log-medic:
    build: .
    container_name: log-medic
    restart: unless-stopped
    mem_limit: 2g
    expose:
      - "5070"
    env_file: .env
    environment:
      - TZ=Asia/Bangkok
      - DATA_DIR=/data
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:5070/health', timeout=5)"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 30s
    volumes:
      - log_medic_data:/data
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /volume2/docker/log-medic/workspaces:/workspaces

  log-medic-nginx:
    image: nginx:alpine
    container_name: log-medic-nginx
    restart: unless-stopped
    ports:
      - "15070:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/conf.d/default.conf:ro
      - ./nginx/.htpasswd:/etc/nginx/.htpasswd:ro
    environment:
      - TZ=Asia/Bangkok
    depends_on:
      - log-medic

volumes:
  log_medic_data:
```

```nginx
# log-medic/nginx/nginx.conf
server {
    listen 80;

    location / {
        auth_basic           "Restricted";
        auth_basic_user_file /etc/nginx/.htpasswd;

        proxy_pass          http://log-medic:5070;
        proxy_http_version  1.1;
        proxy_set_header    Host              $http_host;
        proxy_set_header    X-Real-IP         $remote_addr;
        proxy_set_header    X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header    X-Forwarded-Proto $scheme;
        proxy_buffering     off;
    }
}
```

```yaml
# log-medic/secrets.manifest.yaml
env:
  DASHBOARD_USER:                     stacks.log_medic.dashboard.user
  DASHBOARD_PASSWORD:                 stacks.log_medic.dashboard.password
  GH_TOKEN:                           stacks.log_medic.github_token
  ANTHROPIC_API_KEY:                  shared.mimo.anthropic_api_key
  LOG_MEDIC_TELEGRAM_BOT_TOKEN:       stacks.news_feed.telegram.bot_token
  LOG_MEDIC_TELEGRAM_CHAT_ID:         stacks.news_feed.telegram.chat_id

literals:
  ANTHROPIC_BASE_URL:        https://token-plan-sgp.xiaomimimo.com/anthropic
  DATA_DIR:                  /data
  ENABLE_FIX_RUNNER:         "false"
  DAILY_QUOTA:               "5"
  COOLDOWN_HOURS:            "6"
  GRACE_PERIOD_MINUTES:      "20"
  STORM_THRESHOLD_PER_HOUR:  "10"
  REPO_IDLE_HOURS:           "2"
```

```bash
# log-medic/.env.example
DASHBOARD_USER=changeme
DASHBOARD_PASSWORD=changeme
GH_TOKEN=changeme
ANTHROPIC_API_KEY=changeme
ANTHROPIC_BASE_URL=https://token-plan-sgp.xiaomimimo.com/anthropic
LOG_MEDIC_TELEGRAM_BOT_TOKEN=changeme
LOG_MEDIC_TELEGRAM_CHAT_ID=changeme
DATA_DIR=/data
ENABLE_FIX_RUNNER=false
DAILY_QUOTA=5
COOLDOWN_HOURS=6
GRACE_PERIOD_MINUTES=20
STORM_THRESHOLD_PER_HOUR=10
REPO_IDLE_HOURS=2
```

```python
# log-medic/app/db.py
from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DB_PATH = os.path.join(DATA_DIR, "log-medic.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS monitored_containers (
    name            TEXT PRIMARY KEY,
    repo            TEXT,
    subdir          TEXT,
    maturity        TEXT NOT NULL DEFAULT 'dev',
    notify_only     INTEGER NOT NULL DEFAULT 0,
    paused          INTEGER NOT NULL DEFAULT 0,
    regex_override  TEXT,
    added_at        TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    fingerprint   TEXT NOT NULL,
    container     TEXT NOT NULL,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    count         INTEGER NOT NULL DEFAULT 1,
    status        TEXT NOT NULL,
    gate_reason   TEXT,
    analysis      TEXT,
    pr_url        TEXT,
    PRIMARY KEY (fingerprint, container)
);

CREATE TABLE IF NOT EXISTS daily_quota (
    date            TEXT PRIMARY KEY,
    analyzed_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS circuit_breaker (
    container       TEXT PRIMARY KEY,
    tripped_at      TEXT,
    last_new_fp_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
    ts       TEXT NOT NULL,
    action   TEXT NOT NULL,
    payload  TEXT
);
"""


def get_conn(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    conn.commit()


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def list_monitored_containers(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM monitored_containers").fetchall()


def get_monitored_container(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM monitored_containers WHERE name=?", (name,)
    ).fetchone()


def upsert_monitored_container(
    conn: sqlite3.Connection,
    name: str,
    repo: str | None,
    subdir: str | None,
    maturity: str,
    notify_only: int,
    paused: int,
    regex_override: str | None,
) -> None:
    now = _now_iso()
    conn.execute(
        """
        INSERT INTO monitored_containers
            (name, repo, subdir, maturity, notify_only, paused, regex_override, added_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET
            repo=excluded.repo, subdir=excluded.subdir, maturity=excluded.maturity,
            notify_only=excluded.notify_only, paused=excluded.paused,
            regex_override=excluded.regex_override, updated_at=excluded.updated_at
        """,
        (name, repo, subdir, maturity, notify_only, paused, regex_override, now, now),
    )
    conn.commit()


def delete_monitored_container(conn: sqlite3.Connection, name: str) -> None:
    conn.execute("DELETE FROM monitored_containers WHERE name=?", (name,))
    conn.commit()


def event_exists(conn: sqlite3.Connection, fingerprint: str, container: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM events WHERE fingerprint=? AND container=?",
            (fingerprint, container),
        ).fetchone()
        is not None
    )


def record_event(
    conn: sqlite3.Connection,
    fingerprint: str,
    container: str,
    status: str,
    gate_reason: str | None = None,
    now: str | None = None,
) -> None:
    """Insert-or-bump the occurrence for this matched log line. Call exactly
    once per matched line; use update_event_status() for later status
    transitions on the same occurrence (analyzed/pr_opened/etc.) so count
    isn't double-bumped."""
    now = now or _now_iso()
    if event_exists(conn, fingerprint, container):
        conn.execute(
            "UPDATE events SET last_seen=?, count=count+1, status=?, gate_reason=? "
            "WHERE fingerprint=? AND container=?",
            (now, status, gate_reason, fingerprint, container),
        )
    else:
        conn.execute(
            "INSERT INTO events (fingerprint, container, first_seen, last_seen, count, status, gate_reason) "
            "VALUES (?, ?, ?, ?, 1, ?, ?)",
            (fingerprint, container, now, now, status, gate_reason),
        )
    conn.commit()


def update_event_status(
    conn: sqlite3.Connection,
    fingerprint: str,
    container: str,
    status: str,
    gate_reason: str | None = None,
    analysis: str | None = None,
    pr_url: str | None = None,
) -> None:
    conn.execute(
        "UPDATE events SET status=?, "
        "gate_reason=COALESCE(?, gate_reason), "
        "analysis=COALESCE(?, analysis), "
        "pr_url=COALESCE(?, pr_url) "
        "WHERE fingerprint=? AND container=?",
        (status, gate_reason, analysis, pr_url, fingerprint, container),
    )
    conn.commit()


def get_recent_events(
    conn: sqlite3.Connection, limit: int = 50, container: str | None = None
) -> list[sqlite3.Row]:
    if container:
        return conn.execute(
            "SELECT * FROM events WHERE container=? ORDER BY last_seen DESC LIMIT ?",
            (container, limit),
        ).fetchall()
    return conn.execute(
        "SELECT * FROM events ORDER BY last_seen DESC LIMIT ?", (limit,)
    ).fetchall()


def get_today_quota(conn: sqlite3.Connection) -> int:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT analyzed_count FROM daily_quota WHERE date=?", (today,)
    ).fetchone()
    return row["analyzed_count"] if row else 0


def increment_quota(conn: sqlite3.Connection) -> None:
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    conn.execute(
        "INSERT INTO daily_quota (date, analyzed_count) VALUES (?, 1) "
        "ON CONFLICT(date) DO UPDATE SET analyzed_count=analyzed_count+1",
        (today,),
    )
    conn.commit()


def write_audit(conn: sqlite3.Connection, action: str, payload: str) -> None:
    conn.execute(
        "INSERT INTO audit_log (ts, action, payload) VALUES (?, ?, ?)",
        (_now_iso(), action, payload),
    )
    conn.commit()
```

```markdown
# log-medic/.notes/00_INDEX.md
# log-medic — Index

## Gaps / TODOs
- `nginx/.htpasswd` not generated yet — run `htpasswd -c log-medic/nginx/.htpasswd <user>` before first deploy (same manual step as `friendly-reminder`).
- Vault keys not added yet — run `make edit-vault`, add `stacks.log_medic.dashboard.{user,password}` and `stacks.log_medic.github_token`.
- `/volume2/docker/log-medic/workspaces/<repo>/` must be `git clone`d once manually on the NAS before first use — the app only ever runs `git fetch` there.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd log-medic && python -m pytest tests/test_db.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git checkout -b feat/log-medic
git add log-medic/
git commit -m "feat(log-medic): scaffold stack + db schema and CRUD helpers"
```

---

### Task 2: Vendor notify.py

**Files:**
- Create: `log-medic/app/notify.py` (verbatim copy of `shared/notify.py`)

**Interfaces:**
- Consumes: nothing new
- Produces: `notify.LineCreds`, `notify.TgCreds`, `notify.Notifier(line=None, telegram=None, post=None, timeout=15.0).send(text) -> list[str]`

- [ ] **Step 1: Copy the file**

```bash
cp shared/notify.py log-medic/app/notify.py
```

- [ ] **Step 2: Verify the vendored copy matches**

Run: `python -m pytest tests/test_shared_sync.py -v -k log_medic`
Expected: PASS — `test_vendored_copy_matches_canonical[notify.py]` passes once `log-medic/app/notify.py` is `git add`ed (the test discovers copies via `git ls-files`, so stage it first: `git add log-medic/app/notify.py`)

- [ ] **Step 3: Commit**

```bash
git add log-medic/app/notify.py
git commit -m "feat(log-medic): vendor shared/notify.py"
```

---

### Task 3: Notification wrapper + config.yaml seeding

**Files:**
- Create: `log-medic/config.yaml`
- Create: `log-medic/app/config_seed.py`
- Create: `log-medic/app/notifier.py`
- Create: `log-medic/tests/test_config_seed.py`

**Interfaces:**
- Consumes: `db.upsert_monitored_container`, `db.list_monitored_containers`, `notify.Notifier`, `notify.TgCreds`
- Produces: `config_seed.seed_from_config_if_empty(conn, config_path) -> None`, `notifier.notify(text) -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
# log-medic/tests/test_config_seed.py
import os
import tempfile

import pytest
import yaml


@pytest.fixture
def conn(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmpdir)
    import importlib
    import app.db as db_module
    importlib.reload(db_module)
    c = db_module.get_conn(os.path.join(tmpdir, "test.db"))
    db_module.init_db(c)
    return c


@pytest.fixture
def config_file(tmp_path):
    cfg = {
        "containers": {
            "torrentwatch": {
                "repo": "/workspaces/centralized-nas-container-management",
                "subdir": "torrentwatch",
                "maturity": "stable",
            },
            "jellyfin": {"notify_only": True},
        }
    }
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(cfg))
    return str(path)


def test_seeds_when_table_empty(conn, config_file):
    import app.config_seed as config_seed
    import app.db as db
    config_seed.seed_from_config_if_empty(conn, config_file)
    rows = {r["name"]: r for r in db.list_monitored_containers(conn)}
    assert rows["torrentwatch"]["maturity"] == "stable"
    assert rows["jellyfin"]["notify_only"] == 1
    assert rows["jellyfin"]["maturity"] == "dev"  # default when omitted


def test_does_not_reseed_when_table_has_rows(conn, config_file):
    import app.config_seed as config_seed
    import app.db as db
    db.upsert_monitored_container(conn, "manual-add", None, None, "dev", 0, 0, None)
    config_seed.seed_from_config_if_empty(conn, config_file)
    rows = db.list_monitored_containers(conn)
    assert len(rows) == 1
    assert rows[0]["name"] == "manual-add"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd log-medic && python -m pytest tests/test_config_seed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.config_seed'`

- [ ] **Step 3: Implement**

```yaml
# log-medic/config.yaml
containers:
  torrentwatch:
    repo: /workspaces/centralized-nas-container-management
    subdir: torrentwatch
    maturity: stable
  news-feed:
    repo: /workspaces/centralized-nas-container-management
    subdir: news-feed
    maturity: stable
  secretary:
    repo: /workspaces/centralized-nas-container-management
    subdir: secretary
    maturity: staging
  jellyfin:
    notify_only: true
```

```python
# log-medic/app/config_seed.py
from __future__ import annotations

import sqlite3

import yaml

from app import db


def seed_from_config_if_empty(conn: sqlite3.Connection, config_path: str) -> None:
    """Seed monitored_containers from config.yaml, but only on first boot
    (table empty). After that, all changes go through the dashboard/API —
    config.yaml is never read again or written back to."""
    if db.list_monitored_containers(conn):
        return
    with open(config_path) as f:
        cfg = yaml.safe_load(f) or {}
    for name, entry in (cfg.get("containers") or {}).items():
        db.upsert_monitored_container(
            conn,
            name,
            entry.get("repo"),
            entry.get("subdir"),
            entry.get("maturity", "dev"),
            1 if entry.get("notify_only") else 0,
            0,
            entry.get("regex_override"),
        )
```

```python
# log-medic/app/notifier.py
import os

from app.notify import Notifier, TgCreds

_notifier = Notifier(
    telegram=TgCreds(
        os.environ.get("LOG_MEDIC_TELEGRAM_BOT_TOKEN", ""),
        os.environ.get("LOG_MEDIC_TELEGRAM_CHAT_ID", ""),
    ),
    timeout=10,
)


def notify(text: str) -> list[str]:
    return _notifier.send(text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd log-medic && python -m pytest tests/test_config_seed.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add log-medic/config.yaml log-medic/app/config_seed.py log-medic/app/notifier.py log-medic/tests/test_config_seed.py
git commit -m "feat(log-medic): config.yaml seeding + Telegram notifier wrapper"
```

---

### Task 4: Fingerprinting + ring buffer

**Files:**
- Create: `log-medic/app/watcher.py` (this task only adds the pure functions; Task 6 adds the streaming class)
- Create: `log-medic/tests/test_watcher.py`

**Interfaces:**
- Produces: `watcher.DEFAULT_REGEX: re.Pattern`, `watcher.normalize_message(line: str) -> str`, `watcher.fingerprint(container: str, line: str) -> str`, `watcher.RingBuffer(before=30, after=10)` with `.push(line: str) -> None` and `.capture(trigger_line: str, tail_lines: list[str]) -> str`

- [ ] **Step 1: Write the failing test**

```python
# log-medic/tests/test_watcher.py
from app.watcher import RingBuffer, fingerprint, normalize_message


def test_normalize_strips_timestamp():
    line = "2026-07-04T18:03:12.481Z ERROR db timeout"
    assert "2026-07-04" not in normalize_message(line)


def test_normalize_strips_uuid():
    line = "ERROR request 550e8400-e29b-41d4-a716-446655440000 failed"
    assert "550e8400" not in normalize_message(line)


def test_normalize_strips_hex_and_numbers_and_paths():
    line = "ERROR at 0xdeadbeef reading /volume2/docker/foo/bar line 42"
    normalized = normalize_message(line)
    assert "0xdeadbeef" not in normalized
    assert "/volume2/docker/foo/bar" not in normalized
    assert "42" not in normalized


def test_fingerprint_same_for_normalized_equivalent_lines():
    a = fingerprint("torrentwatch", "2026-07-04T18:00:00Z ERROR conn 42 failed")
    b = fingerprint("torrentwatch", "2026-07-04T19:30:00Z ERROR conn 99 failed")
    assert a == b
    assert len(a) == 12


def test_fingerprint_differs_by_container():
    a = fingerprint("torrentwatch", "ERROR boom")
    b = fingerprint("news-feed", "ERROR boom")
    assert a != b


def test_ring_buffer_capture():
    rb = RingBuffer(before=3, after=2)
    for line in ["l1", "l2", "l3", "l4"]:
        rb.push(line)
    excerpt = rb.capture("TRIGGER", ["after1", "after2", "after3"])
    assert excerpt.splitlines() == ["l2", "l3", "l4", "TRIGGER", "after1", "after2"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd log-medic && python -m pytest tests/test_watcher.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.watcher'`

- [ ] **Step 3: Implement**

```python
# log-medic/app/watcher.py
from __future__ import annotations

import collections
import hashlib
import re

DEFAULT_REGEX = re.compile(r"WARN|ERROR")

_TS_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?"
)
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
_PATH_RE = re.compile(r"(?:/[\w.\-]+){2,}")
_NUM_RE = re.compile(r"\b\d+\b")


def normalize_message(line: str) -> str:
    """Strip transient values (timestamps, UUIDs, hex/memory addresses,
    machine-specific paths, bare numbers) so recurrences of the same
    logical error hash to the same fingerprint."""
    s = _TS_RE.sub("<TS>", line)
    s = _UUID_RE.sub("<UUID>", s)
    s = _HEX_RE.sub("<HEX>", s)
    s = _PATH_RE.sub("<PATH>", s)
    s = _NUM_RE.sub("<NUM>", s)
    return s


def fingerprint(container: str, line: str) -> str:
    normalized = normalize_message(line)
    digest = hashlib.sha256(f"{container}:{normalized}".encode()).hexdigest()
    return digest[:12]


class RingBuffer:
    """Per-container sliding window: keeps up to `before` lines seen so far;
    `capture()` combines them with the trigger line and up to `after` lines
    read immediately afterward."""

    def __init__(self, before: int = 30, after: int = 10):
        self._before: collections.deque[str] = collections.deque(maxlen=before)
        self._after_max = after

    def push(self, line: str) -> None:
        self._before.append(line)

    def capture(self, trigger_line: str, tail_lines: list[str]) -> str:
        return "\n".join([*self._before, trigger_line, *tail_lines[: self._after_max]])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd log-medic && python -m pytest tests/test_watcher.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add log-medic/app/watcher.py log-medic/tests/test_watcher.py
git commit -m "feat(log-medic): fingerprint normalization + ring buffer"
```

---

### Task 5: Gate chain (grace period, circuit breaker, cooldown/quota, dirty repo)

**Files:**
- Create: `log-medic/app/gate.py`
- Create: `log-medic/tests/test_gate.py`

**Interfaces:**
- Consumes: `db.event_exists`, `db.get_today_quota`
- Produces: `gate.GRACE_PERIOD_MINUTES/COOLDOWN_HOURS/DAILY_QUOTA/STORM_THRESHOLD_PER_HOUR/REPO_IDLE_HOURS` (ints, read from env at import time), `gate.in_grace_period(started_at: datetime, now=None) -> bool`, `gate.count_new_fingerprints_since(conn, container, since) -> int`, `gate.is_breaker_tripped(conn, container) -> bool`, `gate.maybe_trip_breaker(conn, container, now=None) -> None`, `gate.maybe_reset_breaker(conn, container, now=None) -> bool`, `gate.in_cooldown(conn, fingerprint, container, now=None) -> bool`, `gate.quota_exceeded(conn) -> bool`, `gate.check_dirty_repo(workspace_dir, fingerprint, now=None) -> bool`, `gate.evaluate(conn, container: sqlite3.Row, fingerprint: str, started_at: datetime, workspace_dir: str) -> str | None` (returns `"grace_period"|"circuit_breaker"|"cooldown"|"quota"|"dirty_repo"` or `None` to proceed)

- [ ] **Step 1: Write the failing test**

```python
# log-medic/tests/test_gate.py
import os
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta

import pytest


@pytest.fixture
def conn(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmpdir)
    import importlib
    import app.db as db_module
    importlib.reload(db_module)
    c = db_module.get_conn(os.path.join(tmpdir, "test.db"))
    db_module.init_db(c)
    return c


def test_in_grace_period(monkeypatch):
    import app.gate as gate
    now = datetime.now(UTC)
    assert gate.in_grace_period(now - timedelta(minutes=5), now=now) is True
    assert gate.in_grace_period(now - timedelta(minutes=30), now=now) is False


def test_circuit_breaker_trips_after_threshold(conn, monkeypatch):
    monkeypatch.setenv("STORM_THRESHOLD_PER_HOUR", "3")
    import importlib
    import app.gate as gate
    import app.db as db
    importlib.reload(gate)
    now = datetime.now(UTC)
    for i in range(4):
        db.record_event(conn, f"fp{i}", "c1", status="new", now=now.isoformat())
    gate.maybe_trip_breaker(conn, "c1", now=now)
    assert gate.is_breaker_tripped(conn, "c1") is True


def test_circuit_breaker_resets_after_quiet_window(conn, monkeypatch):
    monkeypatch.setenv("STORM_THRESHOLD_PER_HOUR", "1")
    import importlib
    import app.gate as gate
    import app.db as db
    importlib.reload(gate)
    old = datetime.now(UTC) - timedelta(hours=7)
    db.record_event(conn, "fp1", "c1", status="new", now=old.isoformat())
    db.record_event(conn, "fp2", "c1", status="new", now=old.isoformat())
    gate.maybe_trip_breaker(conn, "c1", now=old)
    assert gate.is_breaker_tripped(conn, "c1") is True
    reset = gate.maybe_reset_breaker(conn, "c1", now=datetime.now(UTC))
    assert reset is True
    assert gate.is_breaker_tripped(conn, "c1") is False


def test_cooldown(conn, monkeypatch):
    monkeypatch.setenv("COOLDOWN_HOURS", "6")
    import importlib
    import app.gate as gate
    import app.db as db
    importlib.reload(gate)
    now = datetime.now(UTC)
    db.record_event(conn, "fp1", "c1", status="new", now=(now - timedelta(hours=1)).isoformat())
    assert gate.in_cooldown(conn, "fp1", "c1", now=now) is True
    db.record_event(conn, "fp2", "c1", status="new", now=(now - timedelta(hours=7)).isoformat())
    assert gate.in_cooldown(conn, "fp2", "c1", now=now) is False


def test_quota_exceeded(conn, monkeypatch):
    monkeypatch.setenv("DAILY_QUOTA", "2")
    import importlib
    import app.gate as gate
    import app.db as db
    importlib.reload(gate)
    assert gate.quota_exceeded(conn) is False
    db.increment_quota(conn)
    db.increment_quota(conn)
    assert gate.quota_exceeded(conn) is True


def test_dirty_repo_uncommitted_changes(tmp_path):
    import app.gate as gate
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-m", "main"], cwd=repo, check=True)
    (repo / "f.txt").write_text("dirty")
    assert gate.check_dirty_repo(str(repo), "fp1") is True


def test_dirty_repo_clean_is_false(tmp_path, monkeypatch):
    monkeypatch.setenv("REPO_IDLE_HOURS", "0")
    import importlib
    import app.gate as gate
    importlib.reload(gate)
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-m", "main"], cwd=repo, check=True)
    assert gate.check_dirty_repo(str(repo), "fp1") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd log-medic && python -m pytest tests/test_gate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.gate'`

- [ ] **Step 3: Implement**

```python
# log-medic/app/gate.py
from __future__ import annotations

import os
import sqlite3
import subprocess
from datetime import UTC, datetime, timedelta

GRACE_PERIOD_MINUTES = int(os.environ.get("GRACE_PERIOD_MINUTES", "20"))
COOLDOWN_HOURS = int(os.environ.get("COOLDOWN_HOURS", "6"))
DAILY_QUOTA = int(os.environ.get("DAILY_QUOTA", "5"))
STORM_THRESHOLD_PER_HOUR = int(os.environ.get("STORM_THRESHOLD_PER_HOUR", "10"))
REPO_IDLE_HOURS = int(os.environ.get("REPO_IDLE_HOURS", "2"))


def in_grace_period(started_at: datetime, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    return now - started_at < timedelta(minutes=GRACE_PERIOD_MINUTES)


def count_new_fingerprints_since(conn: sqlite3.Connection, container: str, since: datetime) -> int:
    row = conn.execute(
        "SELECT COUNT(*) c FROM events WHERE container=? AND first_seen > ?",
        (container, since.isoformat()),
    ).fetchone()
    return row["c"]


def is_breaker_tripped(conn: sqlite3.Connection, container: str) -> bool:
    row = conn.execute(
        "SELECT tripped_at FROM circuit_breaker WHERE container=?", (container,)
    ).fetchone()
    return bool(row and row["tripped_at"])


def maybe_trip_breaker(conn: sqlite3.Connection, container: str, now: datetime | None = None) -> None:
    now = now or datetime.now(UTC)
    if is_breaker_tripped(conn, container):
        return
    if count_new_fingerprints_since(conn, container, now - timedelta(hours=1)) >= STORM_THRESHOLD_PER_HOUR:
        conn.execute(
            "INSERT INTO circuit_breaker (container, tripped_at, last_new_fp_at) VALUES (?, ?, ?) "
            "ON CONFLICT(container) DO UPDATE SET tripped_at=excluded.tripped_at, last_new_fp_at=excluded.last_new_fp_at",
            (container, now.isoformat(), now.isoformat()),
        )
        conn.commit()


def maybe_reset_breaker(conn: sqlite3.Connection, container: str, now: datetime | None = None) -> bool:
    """Called periodically by the scheduler. Resets a tripped breaker once
    6h pass with no new fingerprint for that container. Returns True if reset."""
    now = now or datetime.now(UTC)
    if not is_breaker_tripped(conn, container):
        return False
    if count_new_fingerprints_since(conn, container, now - timedelta(hours=6)) == 0:
        conn.execute(
            "UPDATE circuit_breaker SET tripped_at=NULL WHERE container=?", (container,)
        )
        conn.commit()
        return True
    return False


def in_cooldown(conn: sqlite3.Connection, fingerprint: str, container: str, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    row = conn.execute(
        "SELECT last_seen FROM events WHERE fingerprint=? AND container=?",
        (fingerprint, container),
    ).fetchone()
    if not row:
        return False
    last_seen = datetime.fromisoformat(row["last_seen"])
    return now - last_seen < timedelta(hours=COOLDOWN_HOURS)


def quota_exceeded(conn: sqlite3.Connection) -> bool:
    from app import db

    return db.get_today_quota(conn) >= DAILY_QUOTA


def check_dirty_repo(workspace_dir: str, fingerprint: str, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=workspace_dir, capture_output=True, text=True, check=True
    ).stdout
    if status.strip():
        return True

    branch = subprocess.run(
        ["git", "branch", "--show-current"], cwd=workspace_dir, capture_output=True, text=True, check=True
    ).stdout.strip()
    if branch not in ("main", "master"):
        return True

    last_commit_ts = subprocess.run(
        ["git", "log", "-1", "--format=%ct"], cwd=workspace_dir, capture_output=True, text=True, check=True
    ).stdout.strip()
    if last_commit_ts:
        last_commit_dt = datetime.fromtimestamp(int(last_commit_ts), tz=UTC)
        if now - last_commit_dt < timedelta(hours=REPO_IDLE_HOURS):
            return True

    branches = subprocess.run(
        ["git", "branch", "-a"], cwd=workspace_dir, capture_output=True, text=True, check=True
    ).stdout
    if f"fix/{fingerprint}" in branches:
        return True

    return False


def evaluate(
    conn: sqlite3.Connection,
    container: sqlite3.Row,
    fingerprint: str,
    started_at: datetime,
    workspace_dir: str,
    now: datetime | None = None,
) -> str | None:
    """Gates 2-5 (grace period, circuit breaker, cooldown/quota, dirty repo).
    Gate 1 (maturity) and notify_only routing happen in watcher.py before
    this is ever called. Returns the gate_reason to record, or None to
    proceed to analyzer phase 1."""
    now = now or datetime.now(UTC)
    name = container["name"]

    if in_grace_period(started_at, now):
        return "grace_period"
    if is_breaker_tripped(conn, name):
        return "circuit_breaker"
    if in_cooldown(conn, fingerprint, name, now):
        return "cooldown"
    if quota_exceeded(conn):
        return "quota"
    if check_dirty_repo(workspace_dir, fingerprint, now):
        return "dirty_repo"
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd log-medic && python -m pytest tests/test_gate.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add log-medic/app/gate.py log-medic/tests/test_gate.py
git commit -m "feat(log-medic): 5-gate pipeline (grace, breaker, cooldown/quota, dirty repo)"
```

---

### Task 6: Docker log watcher + hot-reload manager + event pipeline

**Files:**
- Modify: `log-medic/app/watcher.py` (append streaming classes to the file created in Task 4)
- Modify: `log-medic/tests/test_watcher.py` (append tests)

**Interfaces:**
- Consumes: `db.get_conn`, `db.record_event`, `db.update_event_status`, `db.increment_quota`, `db.list_monitored_containers`, `gate.evaluate`, `gate.maybe_trip_breaker`, `notifier.notify`, `analyzer.analyze`, `analyzer.run_fix`
- Produces: `watcher.process_event(conn, container_row: sqlite3.Row, fp: str, excerpt: str, trigger_line: str, started_at: datetime) -> None`, `watcher.WatcherManager(docker_client=None)` with `.reload(conn) -> None` (async), `.pause() -> None`, `.resume() -> None`, `.is_paused -> bool`

- [ ] **Step 1: Write the failing test**

```python
# log-medic/tests/test_watcher.py (append)
import os
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def conn(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmpdir)
    import importlib
    import app.db as db_module
    importlib.reload(db_module)
    c = db_module.get_conn(os.path.join(tmpdir, "test.db"))
    db_module.init_db(c)
    return c


def test_process_event_notify_only_skips_gates(conn, monkeypatch):
    import app.watcher as watcher
    notify_mock = MagicMock(return_value=["telegram"])
    monkeypatch.setattr(watcher, "notify", notify_mock)
    row = {"name": "jellyfin", "notify_only": 1, "maturity": "dev", "repo": None, "subdir": None}
    watcher.process_event(conn, row, "fp1", "excerpt", "ERROR boom", datetime.now(UTC))
    notify_mock.assert_called_once()
    import app.db as db
    events = db.get_recent_events(conn)
    assert events[0]["status"] == "notified"


def test_process_event_dev_maturity_logs_only_no_calls(conn, monkeypatch):
    import app.watcher as watcher
    notify_mock = MagicMock()
    analyze_mock = MagicMock()
    monkeypatch.setattr(watcher, "notify", notify_mock)
    monkeypatch.setattr(watcher, "analyzer", MagicMock(analyze=analyze_mock))
    row = {"name": "x", "notify_only": 0, "maturity": "dev", "repo": None, "subdir": None}
    watcher.process_event(conn, row, "fp1", "excerpt", "ERROR boom", datetime.now(UTC))
    notify_mock.assert_not_called()
    analyze_mock.assert_not_called()
    import app.db as db
    events = db.get_recent_events(conn)
    assert events[0]["status"] == "new"


def test_process_event_gated_records_reason(conn, monkeypatch):
    import app.watcher as watcher
    monkeypatch.setattr(watcher.gate, "evaluate", lambda *a, **k: "grace_period")
    notify_mock = MagicMock()
    monkeypatch.setattr(watcher, "notify", notify_mock)
    row = {"name": "x", "notify_only": 0, "maturity": "staging", "repo": "/workspaces/r", "subdir": "sub"}
    watcher.process_event(conn, row, "fp1", "excerpt", "ERROR boom", datetime.now(UTC))
    import app.db as db
    events = db.get_recent_events(conn)
    assert events[0]["status"] == "gated"
    assert events[0]["gate_reason"] == "grace_period"
    notify_mock.assert_not_called()  # grace_period is silent, unlike quota/dirty_repo


def test_process_event_proceeds_to_analyze_and_notifies(conn, monkeypatch):
    import app.watcher as watcher
    monkeypatch.setattr(watcher.gate, "evaluate", lambda *a, **k: None)
    monkeypatch.setattr(watcher.gate, "maybe_trip_breaker", lambda *a, **k: None)
    notify_mock = MagicMock()
    monkeypatch.setattr(watcher, "notify", notify_mock)
    monkeypatch.setattr(watcher.analyzer, "analyze", lambda *a, **k: {"text": "root cause X"})
    monkeypatch.setenv("ENABLE_FIX_RUNNER", "false")
    row = {"name": "x", "notify_only": 0, "maturity": "staging", "repo": "/workspaces/r", "subdir": "sub"}
    watcher.process_event(conn, row, "fp1", "excerpt", "ERROR boom", datetime.now(UTC))
    import app.db as db
    events = db.get_recent_events(conn)
    assert events[0]["status"] == "analyzed"
    assert events[0]["analysis"] == "root cause X"
    assert notify_mock.called


def test_watcher_manager_reload_starts_and_cancels_tasks(conn):
    import asyncio

    import app.watcher as watcher
    import app.db as db

    async def run():
        mgr = watcher.WatcherManager(docker_client=MagicMock())
        db.upsert_monitored_container(conn, "c1", None, None, "dev", 1, 0, None)
        await mgr.reload(conn)
        assert "c1" in mgr._tasks
        db.delete_monitored_container(conn, "c1")
        await mgr.reload(conn)
        assert "c1" not in mgr._tasks
        for t in list(mgr._tasks.values()):
            t.cancel()

    asyncio.run(run())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd log-medic && python -m pytest tests/test_watcher.py -v -k "process_event or WatcherManager or reload"`
Expected: FAIL — `AttributeError: module 'app.watcher' has no attribute 'process_event'`

- [ ] **Step 3: Implement (append to `log-medic/app/watcher.py`)**

```python
# log-medic/app/watcher.py (append below RingBuffer)
import asyncio
import logging
import os
import threading
from datetime import UTC, datetime

import docker

from app import analyzer, db, gate
from app.notifier import notify

logger = logging.getLogger(__name__)

RECONNECT_BACKOFF_SECONDS = 5
HOT_RELOAD_INTERVAL_SECONDS = 30


def _workspace_dir(container_row) -> str:
    repo = (container_row["repo"] or "").rstrip("/")
    repo_name = os.path.basename(repo)
    subdir = container_row["subdir"] or ""
    return os.path.join("/workspaces", repo_name, subdir)


def process_event(conn, container_row, fp: str, excerpt: str, trigger_line: str, started_at: datetime) -> None:
    name = container_row["name"]

    if container_row["notify_only"]:
        db.record_event(conn, fp, name, status="notified")
        notify(f"🔔 {name}\n{trigger_line}")
        return

    if container_row["maturity"] == "dev":
        db.record_event(conn, fp, name, status="new")
        return

    workspace_dir = _workspace_dir(container_row)
    reason = gate.evaluate(conn, container_row, fp, started_at, workspace_dir)
    db.record_event(conn, fp, name, status="gated" if reason else "new", gate_reason=reason)
    gate.maybe_trip_breaker(conn, name)

    if reason:
        if reason in ("quota", "dirty_repo"):
            notify(f"⏸ {name} gated ({reason})\n{trigger_line}")
        return

    analysis = analyzer.analyze(container_row, fp, excerpt)
    db.update_event_status(conn, fp, name, status="analyzed", analysis=analysis["text"])
    db.increment_quota(conn)
    notify(f"🔎 {name}\nRoot cause: {analysis['text']}")

    if container_row["maturity"] == "stable" and os.environ.get("ENABLE_FIX_RUNNER", "false").lower() == "true":
        pr_url = analyzer.run_fix(container_row, fp, analysis, workspace_dir)
        if pr_url:
            db.update_event_status(conn, fp, name, status="pr_opened", pr_url=pr_url)
            notify(f"🛠 PR opened for {name}: {pr_url}")
        else:
            db.update_event_status(conn, fp, name, status="analyzed", gate_reason="fix_rejected")


def _parse_started_at(iso: str) -> datetime:
    # Docker's State.StartedAt is RFC3339 with nanoseconds, e.g. "2026-07-04T10:00:00.123456789Z"
    trimmed = iso[:26] + "Z" if iso.endswith("Z") else iso
    return datetime.strptime(trimmed, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def _watch_once(docker_client, row, conn, stop_event: threading.Event, last_image_id: dict) -> None:
    name = row["name"]
    container = docker_client.containers.get(name)
    image_id = container.image.id
    started_at = _parse_started_at(container.attrs["State"]["StartedAt"])
    if last_image_id.get(name) != image_id:
        started_at = datetime.now(UTC)  # image change resets the grace-period clock
    last_image_id[name] = image_id

    pattern = re.compile(row["regex_override"]) if row["regex_override"] else DEFAULT_REGEX
    ring = RingBuffer()

    for raw in container.logs(stream=True, follow=True, since=0):
        if stop_event.is_set():
            return
        line = raw.decode(errors="replace").rstrip("\n")
        if pattern.search(line):
            fp = fingerprint(name, line)
            excerpt = ring.capture(line, [])
            process_event(conn, row, fp, excerpt, line, started_at)
        ring.push(line)


class WatcherManager:
    def __init__(self, docker_client=None):
        self._docker = docker_client or docker.from_env()
        self._tasks: dict[str, asyncio.Task] = {}
        self._stop_events: dict[str, threading.Event] = {}
        self._last_image_id: dict[str, str] = {}
        self._paused = False

    @property
    def is_paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    async def reload(self, conn) -> None:
        if self._paused:
            for name in list(self._tasks):
                self._cancel(name)
            return
        rows = {r["name"]: r for r in db.list_monitored_containers(conn) if not r["paused"]}
        for name in list(self._tasks):
            if name not in rows:
                self._cancel(name)
        for name, row in rows.items():
            if name not in self._tasks:
                stop_event = threading.Event()
                self._stop_events[name] = stop_event
                self._tasks[name] = asyncio.create_task(self._watch(row, stop_event))

    def _cancel(self, name: str) -> None:
        self._stop_events[name].set()
        self._tasks[name].cancel()
        del self._tasks[name]
        del self._stop_events[name]

    async def _watch(self, row, stop_event: threading.Event) -> None:
        conn = db.get_conn()
        try:
            while not stop_event.is_set():
                try:
                    await asyncio.to_thread(
                        _watch_once, self._docker, row, conn, stop_event, self._last_image_id
                    )
                except Exception:
                    logger.exception("watcher for %s crashed, reconnecting", row["name"])
                await asyncio.sleep(RECONNECT_BACKOFF_SECONDS)
        finally:
            conn.close()
```

Note: add `import re` to the top of `watcher.py` alongside the existing imports (it's already used by `DEFAULT_REGEX` from Task 4, so this is a no-op if Task 4's imports already include it).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd log-medic && python -m pytest tests/test_watcher.py -v`
Expected: PASS (11 tests total — 6 from Task 4 + 5 new)

- [ ] **Step 5: Commit**

```bash
git add log-medic/app/watcher.py log-medic/tests/test_watcher.py
git commit -m "feat(log-medic): docker-py watcher, hot-reload manager, event pipeline"
```

---

### Task 7: Analyzer phase 1 (read-only root-cause analysis)

**Files:**
- Create: `log-medic/prompts/analyze.md`
- Create: `log-medic/app/analyzer.py`
- Create: `log-medic/tests/test_analyzer.py`

**Interfaces:**
- Consumes: nothing new (calls `subprocess.run(["claude", ...])` directly)
- Produces: `analyzer.workspace_dir(container_row: sqlite3.Row | dict) -> str`, `analyzer.render_prompt(template_path: str, **kwargs) -> str`, `analyzer.analyze(container_row, fingerprint: str, excerpt: str) -> dict` (dict has key `"text"`)

- [ ] **Step 1: Write the failing test**

```python
# log-medic/tests/test_analyzer.py
from unittest.mock import MagicMock, patch


def test_render_prompt_substitutes_placeholders(tmp_path):
    import app.analyzer as analyzer
    template = tmp_path / "t.md"
    template.write_text("Container: {{container}}\nExcerpt:\n{{excerpt}}")
    rendered = analyzer.render_prompt(str(template), container="torrentwatch", excerpt="ERROR boom")
    assert "torrentwatch" in rendered
    assert "ERROR boom" in rendered


def test_workspace_dir_joins_repo_and_subdir():
    import app.analyzer as analyzer
    row = {"repo": "/workspaces/centralized-nas-container-management", "subdir": "torrentwatch"}
    assert analyzer.workspace_dir(row) == "/workspaces/centralized-nas-container-management/torrentwatch"


@patch("subprocess.run")
def test_analyze_invokes_claude_readonly_and_parses_json(mock_run):
    import app.analyzer as analyzer
    mock_run.return_value = MagicMock(stdout='{"result": "root cause: db pool exhausted"}', returncode=0)
    row = {"name": "torrentwatch", "repo": "/workspaces/r", "subdir": "torrentwatch"}
    result = analyzer.analyze(row, "fp123", "ERROR boom")
    assert result["text"] == "root cause: db pool exhausted"
    args = mock_run.call_args.args[0]
    assert args[0] == "claude"
    assert "-p" in args
    assert "Edit" not in " ".join(args)
    assert "Write" not in " ".join(args)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd log-medic && python -m pytest tests/test_analyzer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.analyzer'`

- [ ] **Step 3: Implement**

```markdown
# log-medic/prompts/analyze.md
You are analyzing a WARN/ERROR log event from the Docker container `{{container}}`.

## Log excerpt (30 lines before, trigger line, up to 10 lines after)
```
{{excerpt}}
```

## Repository context
The service's source lives at `{{repo}}/{{subdir}}`. You may use `git log` and
`git diff` to check recent history, and `Read`/`Grep`/`Glob` to inspect the
current code. Do NOT edit any files — this is read-only root-cause analysis.

## Task
1. Identify the root cause of this error.
2. Propose a fix as a description of the change (not an actual diff/patch).
3. Respond concisely — a few sentences of root cause, followed by the proposed fix description.
```

```python
# log-medic/app/analyzer.py
from __future__ import annotations

import json
import os
import subprocess

PHASE1_ALLOWED_TOOLS = "Read,Grep,Glob,Bash(git log:*),Bash(git diff:*)"
PHASE1_TIMEOUT_SECONDS = 600

_PROMPT_DIR = os.path.join(os.path.dirname(__file__), "..", "prompts")


def render_prompt(template_path: str, **kwargs) -> str:
    with open(template_path) as f:
        text = f.read()
    for key, value in kwargs.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


def workspace_dir(container_row) -> str:
    repo = (container_row["repo"] or "").rstrip("/")
    repo_name = os.path.basename(repo)
    subdir = container_row["subdir"] or ""
    return os.path.join("/workspaces", repo_name, subdir) if repo_name else ""


def analyze(container_row, fingerprint: str, excerpt: str) -> dict:
    prompt = render_prompt(
        os.path.join(_PROMPT_DIR, "analyze.md"),
        container=container_row["name"],
        excerpt=excerpt,
        repo=container_row["repo"] or "",
        subdir=container_row["subdir"] or "",
    )
    result = subprocess.run(
        [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--max-turns", "15",
            "--allowedTools", PHASE1_ALLOWED_TOOLS,
        ],
        cwd=workspace_dir(container_row) or None,
        capture_output=True,
        text=True,
        timeout=PHASE1_TIMEOUT_SECONDS,
    )
    try:
        payload = json.loads(result.stdout or "{}")
        text = payload.get("result", result.stdout.strip())
    except json.JSONDecodeError:
        text = result.stdout.strip()
    return {"text": text, "excerpt": excerpt}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd log-medic && python -m pytest tests/test_analyzer.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add log-medic/prompts/analyze.md log-medic/app/analyzer.py log-medic/tests/test_analyzer.py
git commit -m "feat(log-medic): analyzer phase 1 (read-only root-cause analysis)"
```

---

### Task 8: Analyzer phase 2 (fix + PR, with safety rails)

**Files:**
- Modify: `log-medic/app/analyzer.py` (append)
- Modify: `log-medic/tests/test_analyzer.py` (append)

**Interfaces:**
- Consumes: `notifier.notify`
- Produces: `analyzer.FORBIDDEN_FIX_FILES: re.Pattern`, `analyzer.MAX_DIFF_LINES: int`, `analyzer.run_fix(container_row, fingerprint: str, analysis: dict, workspace_dir: str) -> str | None` (returns PR URL, or `None` if rejected/no PR created — caller records `gate_reason="fix_rejected"` when `None`)

- [ ] **Step 1: Write the failing test**

```python
# log-medic/tests/test_analyzer.py (append)
from unittest.mock import MagicMock, patch


@patch("app.analyzer.notify")
@patch("subprocess.run")
def test_run_fix_happy_path_creates_pr(mock_run, mock_notify):
    import app.analyzer as analyzer

    def side_effect(args, **kwargs):
        if args[:2] == ["git", "diff"] and "--name-only" in args:
            return MagicMock(stdout="src/foo.py\n")
        if args[:2] == ["git", "diff"] and "--stat" in args:
            return MagicMock(stdout="1 file changed, 2 insertions(+)")
        if args == ["git", "diff"]:
            return MagicMock(stdout="+line1\n+line2\n")
        if args[:2] == ["gh", "pr"]:
            return MagicMock(stdout="https://github.com/org/repo/pull/42\n")
        return MagicMock(stdout="")

    mock_run.side_effect = side_effect
    row = {"name": "torrentwatch", "repo": "/workspaces/r", "subdir": "torrentwatch"}
    analysis = {"text": "root cause X", "excerpt": "ERROR boom"}
    pr_url = analyzer.run_fix(row, "fp123", analysis, "/workspaces/r/torrentwatch")
    assert pr_url == "https://github.com/org/repo/pull/42"

    calls = [c.args[0] for c in mock_run.call_args_list]
    assert ["git", "fetch", "origin"] in calls
    assert any(c[:3] == ["git", "checkout", "-b"] and c[3] == "fix/fp123" for c in calls)


@patch("app.analyzer.notify")
@patch("subprocess.run")
def test_run_fix_rejects_forbidden_file(mock_run, mock_notify):
    import app.analyzer as analyzer

    def side_effect(args, **kwargs):
        if args[:2] == ["git", "diff"] and "--name-only" in args:
            return MagicMock(stdout="docker-compose.yml\n")
        if args[:2] == ["git", "diff"] and "--stat" in args:
            return MagicMock(stdout="1 file changed")
        if args == ["git", "diff"]:
            return MagicMock(stdout="+line1\n")
        return MagicMock(stdout="")

    mock_run.side_effect = side_effect
    row = {"name": "torrentwatch", "repo": "/workspaces/r", "subdir": "torrentwatch"}
    analysis = {"text": "root cause X", "excerpt": "ERROR boom"}
    pr_url = analyzer.run_fix(row, "fp123", analysis, "/workspaces/r/torrentwatch")
    assert pr_url is None
    mock_notify.assert_called_once()
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert not any(c[:2] == ["gh", "pr"] for c in calls)


@patch("app.analyzer.notify")
@patch("subprocess.run")
def test_run_fix_rejects_oversized_diff(mock_run, mock_notify):
    import app.analyzer as analyzer

    big_diff = "\n".join(f"+line{i}" for i in range(250))

    def side_effect(args, **kwargs):
        if args[:2] == ["git", "diff"] and "--name-only" in args:
            return MagicMock(stdout="src/foo.py\n")
        if args[:2] == ["git", "diff"] and "--stat" in args:
            return MagicMock(stdout="1 file changed")
        if args == ["git", "diff"]:
            return MagicMock(stdout=big_diff)
        return MagicMock(stdout="")

    mock_run.side_effect = side_effect
    row = {"name": "torrentwatch", "repo": "/workspaces/r", "subdir": "torrentwatch"}
    analysis = {"text": "root cause X", "excerpt": "ERROR boom"}
    pr_url = analyzer.run_fix(row, "fp123", analysis, "/workspaces/r/torrentwatch")
    assert pr_url is None
    mock_notify.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd log-medic && python -m pytest tests/test_analyzer.py -v -k run_fix`
Expected: FAIL — `AttributeError: module 'app.analyzer' has no attribute 'run_fix'`

- [ ] **Step 3: Implement (append to `log-medic/app/analyzer.py`)**

```python
# log-medic/app/analyzer.py (append)
import re

from app.notifier import notify

PHASE2_ALLOWED_TOOLS = "Read,Grep,Glob,Edit,Write"
PHASE2_TIMEOUT_SECONDS = 900
FORBIDDEN_FIX_FILES = re.compile(r"(^|/)(\.env\S*|docker-compose\S*\.ya?ml|\S+\.db)$")
MAX_DIFF_LINES = 200

_FIX_PROMPT_TEMPLATE = """You are fixing a bug in `{container}` based on this root-cause analysis:

{analysis}

Make the minimal code change needed. Do NOT edit `.env*`, `docker-compose*.yml`,
or any `*.db` file. Do NOT run any `docker` or `docker compose` commands.
"""


def run_fix(container_row, fingerprint: str, analysis: dict, workspace_dir: str) -> str | None:
    name = container_row["name"]
    branch = f"fix/{fingerprint}"

    subprocess.run(["git", "fetch", "origin"], cwd=workspace_dir, check=True)
    subprocess.run(["git", "checkout", "-b", branch, "origin/main"], cwd=workspace_dir, check=True)

    prompt = _FIX_PROMPT_TEMPLATE.format(container=name, analysis=analysis["text"])
    subprocess.run(
        [
            "claude", "-p", prompt,
            "--output-format", "json",
            "--max-turns", "15",
            "--allowedTools", PHASE2_ALLOWED_TOOLS,
        ],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        timeout=PHASE2_TIMEOUT_SECONDS,
    )

    changed_files = subprocess.run(
        ["git", "diff", "--name-only"], cwd=workspace_dir, capture_output=True, text=True
    ).stdout.splitlines()
    diff_stat = subprocess.run(
        ["git", "diff", "--stat"], cwd=workspace_dir, capture_output=True, text=True
    ).stdout
    diff_text = subprocess.run(
        ["git", "diff"], cwd=workspace_dir, capture_output=True, text=True
    ).stdout
    diff_lines = sum(
        1 for line in diff_text.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---"))
    )

    forbidden_hit = any(FORBIDDEN_FIX_FILES.search(f) for f in changed_files)
    if forbidden_hit or diff_lines > MAX_DIFF_LINES:
        subprocess.run(["git", "checkout", "origin/main"], cwd=workspace_dir)
        subprocess.run(["git", "branch", "-D", branch], cwd=workspace_dir)
        reason = "touched a forbidden file" if forbidden_hit else f"diff too large ({diff_lines} lines)"
        notify(f"🚫 Fix rejected for {name} (fingerprint {fingerprint}): {reason}")
        return None

    subprocess.run(["git", "add", "-A"], cwd=workspace_dir, check=True)
    subprocess.run(["git", "commit", "-m", f"fix: log-medic auto-fix for {fingerprint}"], cwd=workspace_dir, check=True)
    subprocess.run(["git", "push", "origin", branch], cwd=workspace_dir, check=True)

    pr_body = (
        f"## Log excerpt\n```\n{analysis.get('excerpt', '')}\n```\n\n"
        f"## Root cause\n{analysis['text']}\n\n"
        f"## What changed\n{diff_stat}\n\n"
        f"## How to test\nRe-run the scenario that produced the original log line; confirm the WARN/ERROR no longer occurs.\n"
    )
    result = subprocess.run(
        [
            "gh", "pr", "create",
            "--title", f"fix: {name} ({fingerprint})",
            "--body", pr_body,
            "--label", "auto-fix",
            "--base", "main",
            "--head", branch,
        ],
        cwd=workspace_dir,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()
```

Note: `import subprocess` is already present at the top of `analyzer.py` from Task 7 — do not duplicate it.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd log-medic && python -m pytest tests/test_analyzer.py -v`
Expected: PASS (6 tests total — 3 from Task 7 + 3 new)

- [ ] **Step 5: Commit**

```bash
git add log-medic/app/analyzer.py log-medic/tests/test_analyzer.py
git commit -m "feat(log-medic): analyzer phase 2 (fix + PR) with safety rails"
```

---

### Task 9: Scheduler (quota reset, breaker auto-reset, 18:00 digest)

**Files:**
- Create: `log-medic/app/scheduler.py`
- Create: `log-medic/tests/test_scheduler.py`

**Interfaces:**
- Consumes: `db.list_monitored_containers`, `gate.maybe_reset_breaker`, `gate.is_breaker_tripped`, `gate.count_new_fingerprints_since`, `notifier.notify`
- Produces: `scheduler.setup_scheduler(db_path: str | None = None) -> apscheduler.schedulers.background.BackgroundScheduler`, `scheduler.breaker_auto_reset_job(db_path) -> None`, `scheduler.daily_digest_job(db_path) -> None`

- [ ] **Step 1: Write the failing test**

```python
# log-medic/tests/test_scheduler.py
import os
import tempfile
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def db_path(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmpdir)
    import importlib
    import app.db as db_module
    importlib.reload(db_module)
    path = os.path.join(tmpdir, "test.db")
    conn = db_module.get_conn(path)
    db_module.init_db(conn)
    conn.close()
    return path


def test_breaker_auto_reset_job_resets_quiet_containers(db_path, monkeypatch):
    import app.db as db
    import app.scheduler as scheduler

    conn = db.get_conn(db_path)
    db.upsert_monitored_container(conn, "c1", None, None, "stable", 0, 0, None)
    old = datetime.now(UTC) - timedelta(hours=8)
    db.record_event(conn, "fp1", "c1", status="new", now=old.isoformat())
    import app.gate as gate
    gate.maybe_trip_breaker(conn, "c1", now=old)
    assert gate.is_breaker_tripped(conn, "c1") is True
    conn.close()

    scheduler.breaker_auto_reset_job(db_path)

    conn = db.get_conn(db_path)
    assert gate.is_breaker_tripped(conn, "c1") is False


def test_daily_digest_job_notifies_only_when_something_tripped(db_path, monkeypatch):
    import app.db as db
    import app.scheduler as scheduler

    notify_mock = MagicMock()
    monkeypatch.setattr(scheduler, "notify", notify_mock)

    conn = db.get_conn(db_path)
    db.upsert_monitored_container(conn, "c1", None, None, "stable", 0, 0, None)
    now = datetime.now(UTC)
    db.record_event(conn, "fp1", "c1", status="new", now=now.isoformat())
    import app.gate as gate
    gate.maybe_trip_breaker(conn, "c1", now=now)
    conn.close()

    scheduler.daily_digest_job(db_path)
    notify_mock.assert_called_once()
    assert "c1" in notify_mock.call_args.args[0]


def test_setup_scheduler_registers_three_jobs(db_path):
    import app.scheduler as scheduler
    sched = scheduler.setup_scheduler(db_path)
    job_ids = {job.id for job in sched.get_jobs()}
    assert job_ids == {"daily_quota_reset", "breaker_auto_reset", "daily_digest"}
    sched.shutdown(wait=False)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd log-medic && python -m pytest tests/test_scheduler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.scheduler'`

- [ ] **Step 3: Implement**

```python
# log-medic/app/scheduler.py
from __future__ import annotations

from datetime import UTC, datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app import db, gate
from app.notifier import notify


def _quota_reset_job(db_path: str) -> None:
    # daily_quota is keyed by date already, so "reset" is a no-op — a new
    # day naturally starts a fresh row via db.increment_quota's upsert.
    # Kept as an explicit job so the schedule matches the spec's stated jobs
    # and so a future quota-notification hook has somewhere to live.
    pass


def breaker_auto_reset_job(db_path: str) -> None:
    conn = db.get_conn(db_path)
    try:
        for row in db.list_monitored_containers(conn):
            if gate.is_breaker_tripped(conn, row["name"]):
                gate.maybe_reset_breaker(conn, row["name"])
    finally:
        conn.close()


def daily_digest_job(db_path: str) -> None:
    conn = db.get_conn(db_path)
    try:
        now = datetime.now(UTC)
        lines = []
        for row in db.list_monitored_containers(conn):
            if gate.is_breaker_tripped(conn, row["name"]):
                count = gate.count_new_fingerprints_since(conn, row["name"], now.replace(hour=0, minute=0, second=0, microsecond=0))
                lines.append(f"- {row['name']}: {count} new fingerprints today, breaker tripped")
        if lines:
            notify("📋 log-medic daily digest (18:00)\n" + "\n".join(lines))
    finally:
        conn.close()


def setup_scheduler(db_path: str | None = None) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="Asia/Bangkok")
    scheduler.add_job(
        _quota_reset_job, CronTrigger(hour=0, minute=0), args=[db_path], id="daily_quota_reset"
    )
    scheduler.add_job(
        breaker_auto_reset_job, IntervalTrigger(minutes=30), args=[db_path], id="breaker_auto_reset"
    )
    scheduler.add_job(
        daily_digest_job, CronTrigger(hour=18, minute=0), args=[db_path], id="daily_digest"
    )
    scheduler.start()
    return scheduler
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd log-medic && python -m pytest tests/test_scheduler.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add log-medic/app/scheduler.py log-medic/tests/test_scheduler.py
git commit -m "feat(log-medic): scheduler (breaker auto-reset + 18:00 digest)"
```

---

### Task 10: API routes (health, containers, events, watcher control)

**Files:**
- Create: `log-medic/app/api/__init__.py`
- Create: `log-medic/app/api/health.py`
- Create: `log-medic/app/api/containers.py`
- Create: `log-medic/app/api/events.py`
- Create: `log-medic/app/api/watcher_control.py`
- Create: `log-medic/app/deps.py`
- Create: `log-medic/tests/test_api.py`

**Interfaces:**
- Consumes: `db.*` helpers, `docker` SDK (`docker_client.containers.list()`), `app.main.app.state.watcher_manager` (set in Task 11)
- Produces: `deps.get_db() -> sqlite3.Connection` (FastAPI dependency), routers `health.router`, `containers.router`, `events.router`, `watcher_control.router`, all mounted under `/api` except `health.router` which exposes bare `/health`

- [ ] **Step 1: Write the failing test**

```python
# log-medic/tests/test_api.py
import os
import tempfile
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("DATA_DIR", tmpdir)
    import importlib
    import app.db as db_module
    importlib.reload(db_module)

    import app.main as main_module
    importlib.reload(main_module)
    main_module.app.state.db_path = os.path.join(tmpdir, "test.db")
    main_module.app.state.docker_client = MagicMock(containers=MagicMock(list=MagicMock(return_value=[])))

    with TestClient(main_module.app) as c:
        yield c


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200


def test_containers_crud_flow(client):
    resp = client.post(
        "/api/containers",
        json={"name": "c1", "repo": None, "subdir": None, "maturity": "dev", "notify_only": False},
    )
    assert resp.status_code == 200

    resp = client.get("/api/containers")
    assert resp.status_code == 200
    names = [c["name"] for c in resp.json() if "name" in c]
    assert "c1" in names

    resp = client.patch("/api/containers/c1", json={"maturity": "staging"})
    assert resp.status_code == 200
    assert resp.json()["maturity"] == "staging"

    resp = client.delete("/api/containers/c1")
    assert resp.status_code == 200


def test_events_list(client):
    resp = client.get("/api/events?limit=10")
    assert resp.status_code == 200
    assert resp.json() == []


def test_watcher_pause_resume(client):
    resp = client.post("/api/watcher/pause")
    assert resp.status_code == 200
    resp = client.post("/api/watcher/resume")
    assert resp.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd log-medic && python -m pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'` (Task 11 creates it) — for this task, run only the router-import-independent parts first is not possible since TestClient needs `app.main`; proceed to Step 3 which creates both the routers and a minimal `main.py` stub, with Task 11 completing `main.py`'s lifespan wiring.

- [ ] **Step 3: Implement**

```python
# log-medic/app/api/__init__.py
```

```python
# log-medic/app/deps.py
from fastapi import Request

from app import db


def get_db(request: Request):
    conn = db.get_conn(getattr(request.app.state, "db_path", None))
    try:
        yield conn
    finally:
        conn.close()
```

```python
# log-medic/app/api/health.py
from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}
```

```python
# log-medic/app/api/containers.py
from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request

from app import db
from app.deps import get_db

router = APIRouter(prefix="/api/containers")


@router.get("")
def list_containers(request: Request, conn=Depends(get_db)):
    monitored = {r["name"]: dict(r) for r in db.list_monitored_containers(conn)}
    docker_client = request.app.state.docker_client
    running = {c.name for c in docker_client.containers.list()}
    discovered = [{"name": n, "monitored": False} for n in running if n not in monitored]
    return list(monitored.values()) + discovered


@router.post("")
def add_container(payload: dict, request: Request, conn=Depends(get_db)):
    name = payload["name"]
    docker_client = request.app.state.docker_client
    running_names = {c.name for c in docker_client.containers.list()}
    if running_names and name not in running_names:
        raise HTTPException(status_code=400, detail=f"container '{name}' not found on docker")
    db.upsert_monitored_container(
        conn,
        name,
        payload.get("repo"),
        payload.get("subdir"),
        payload.get("maturity", "dev"),
        1 if payload.get("notify_only") else 0,
        0,
        payload.get("regex_override"),
    )
    db.write_audit(conn, "add_container", json.dumps(payload))
    return dict(db.get_monitored_container(conn, name))


@router.patch("/{name}")
def patch_container(name: str, payload: dict, conn=Depends(get_db)):
    row = db.get_monitored_container(conn, name)
    if not row:
        raise HTTPException(status_code=404, detail="not found")
    merged = dict(row)
    merged.update(payload)
    db.upsert_monitored_container(
        conn,
        name,
        merged.get("repo"),
        merged.get("subdir"),
        merged.get("maturity"),
        1 if merged.get("notify_only") else 0,
        1 if merged.get("paused") else 0,
        merged.get("regex_override"),
    )
    db.write_audit(conn, "patch_container", json.dumps({"name": name, **payload}))
    return dict(db.get_monitored_container(conn, name))


@router.delete("/{name}")
def delete_container(name: str, conn=Depends(get_db)):
    db.delete_monitored_container(conn, name)
    db.write_audit(conn, "delete_container", json.dumps({"name": name}))
    return {"deleted": name}
```

```python
# log-medic/app/api/events.py
from fastapi import APIRouter, Depends

from app import db
from app.deps import get_db

router = APIRouter(prefix="/api/events")


@router.get("")
def list_events(limit: int = 50, container: str | None = None, conn=Depends(get_db)):
    return [dict(r) for r in db.get_recent_events(conn, limit=limit, container=container)]
```

```python
# log-medic/app/api/watcher_control.py
from fastapi import APIRouter, Request

router = APIRouter(prefix="/api/watcher")


@router.post("/pause")
def pause_watcher(request: Request):
    request.app.state.watcher_manager.pause()
    return {"paused": True}


@router.post("/resume")
def resume_watcher(request: Request):
    request.app.state.watcher_manager.resume()
    return {"paused": False}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd log-medic && python -m pytest tests/test_api.py -v` (after Task 11's `main.py` exists)
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add log-medic/app/api/ log-medic/app/deps.py log-medic/tests/test_api.py
git commit -m "feat(log-medic): API routes (containers, events, watcher control, health)"
```

---

### Task 11: main.py wiring

**Files:**
- Create: `log-medic/app/main.py`

**Interfaces:**
- Consumes: `db.init_db`, `db.get_conn`, `db.DB_PATH`, `config_seed.seed_from_config_if_empty`, `watcher.WatcherManager`, `scheduler.setup_scheduler`, all `api.*` routers
- Produces: `main.app: FastAPI` with `app.state.watcher_manager`, `app.state.docker_client`, `app.state.db_path`

- [ ] **Step 1: Write the failing test**

(Covered by Task 10's `test_api.py`, which imports `app.main`. No new test file — this task exists to make Task 10's tests pass for real, and to be the actual app entrypoint.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd log-medic && python -m pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 3: Implement**

```python
# log-medic/app/main.py
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import docker
from fastapi import FastAPI

from app import config_seed, db, scheduler as scheduler_module
from app.api import containers, events, health, watcher_control
from app.watcher import HOT_RELOAD_INTERVAL_SECONDS, WatcherManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.yaml")


async def _hot_reload_loop(app: FastAPI) -> None:
    while True:
        conn = db.get_conn(app.state.db_path)
        try:
            await app.state.watcher_manager.reload(conn)
        except Exception:
            logger.exception("watcher hot-reload failed")
        finally:
            conn.close()
        await asyncio.sleep(HOT_RELOAD_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = getattr(app.state, "db_path", None) or db.DB_PATH
    conn = db.get_conn(db_path)
    try:
        db.init_db(conn)
        config_seed.seed_from_config_if_empty(conn, CONFIG_PATH)
    finally:
        conn.close()
    app.state.db_path = db_path

    if not hasattr(app.state, "docker_client"):
        app.state.docker_client = docker.from_env()
    app.state.watcher_manager = WatcherManager(docker_client=app.state.docker_client)

    reload_task = asyncio.create_task(_hot_reload_loop(app))
    sched = scheduler_module.setup_scheduler(db_path)

    yield

    reload_task.cancel()
    sched.shutdown(wait=False)


app = FastAPI(title="log-medic", lifespan=lifespan)
app.include_router(health.router)
app.include_router(containers.router)
app.include_router(events.router)
app.include_router(watcher_control.router)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd log-medic && python -m pytest tests/test_api.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add log-medic/app/main.py
git commit -m "feat(log-medic): wire FastAPI app, lifespan, hot-reload loop, scheduler"
```

---

### Task 12: Dashboard (Containers tab + Events tab)

**Files:**
- Create: `log-medic/app/static/index.html`
- Create: `log-medic/app/static/app.js`
- Modify: `log-medic/app/main.py` (mount static files after routers, matching the `news-feed` pattern)

**Interfaces:**
- Consumes: `GET/POST /api/containers`, `PATCH/DELETE /api/containers/{name}`, `GET /api/events`, `POST /api/watcher/{pause,resume}`
- Produces: static dashboard served at `/`

- [ ] **Step 1: Manual test (no automated test — static UI, verified by hand per the spec's Definition of Done)**

- [ ] **Step 2: Implement**

```html
<!-- log-medic/app/static/index.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>log-medic</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 2rem; background: #111; color: #eee; }
    table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
    th, td { border: 1px solid #333; padding: 0.4rem 0.6rem; text-align: left; font-size: 0.9rem; }
    button { cursor: pointer; }
    .tabs button { margin-right: 0.5rem; padding: 0.4rem 1rem; }
    .tab-content { display: none; }
    .tab-content.active { display: block; }
  </style>
</head>
<body>
  <h1>log-medic</h1>
  <div class="tabs">
    <button onclick="showTab('containers')">Containers</button>
    <button onclick="showTab('events')">Events</button>
    <button id="watcher-toggle" onclick="toggleWatcher()">Pause watcher</button>
  </div>

  <div id="containers" class="tab-content active">
    <h2>Add container</h2>
    <input id="add-name" placeholder="name" />
    <input id="add-repo" placeholder="repo (blank = notify_only)" />
    <input id="add-subdir" placeholder="subdir" />
    <select id="add-maturity">
      <option>dev</option><option>staging</option><option>stable</option>
    </select>
    <label><input type="checkbox" id="add-notify-only" /> notify_only</label>
    <button onclick="addContainer()">Add</button>
    <table id="containers-table">
      <thead><tr><th>Name</th><th>Maturity</th><th>Notify only</th><th>Paused</th><th>Actions</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <div id="events" class="tab-content">
    <table id="events-table">
      <thead><tr><th>Time</th><th>Container</th><th>Fingerprint</th><th>Count</th><th>Status</th><th>Gate reason</th></tr></thead>
      <tbody></tbody>
    </table>
  </div>

  <script src="/static/app.js"></script>
</body>
</html>
```

```javascript
// log-medic/app/static/app.js
function showTab(id) {
  document.querySelectorAll(".tab-content").forEach((el) => el.classList.remove("active"));
  document.getElementById(id).classList.add("active");
  if (id === "events") loadEvents();
  if (id === "containers") loadContainers();
}

async function loadContainers() {
  const res = await fetch("/api/containers");
  const rows = await res.json();
  const tbody = document.querySelector("#containers-table tbody");
  tbody.innerHTML = "";
  for (const c of rows) {
    if (!c.name) continue;
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${c.name}</td>
      <td>${c.maturity ?? "-"}</td>
      <td>${c.notify_only ? "yes" : "no"}</td>
      <td>${c.paused ? "yes" : "no"}</td>
      <td>
        <button onclick="patchContainer('${c.name}', {paused: ${c.paused ? 0 : 1}})">${c.paused ? "resume" : "pause"}</button>
        <button onclick="removeContainer('${c.name}')">remove</button>
      </td>`;
    tbody.appendChild(tr);
  }
}

async function addContainer() {
  const name = document.getElementById("add-name").value.trim();
  if (!name) return;
  const repo = document.getElementById("add-repo").value.trim() || null;
  const subdir = document.getElementById("add-subdir").value.trim() || null;
  const maturity = document.getElementById("add-maturity").value;
  const notify_only = document.getElementById("add-notify-only").checked;
  await fetch("/api/containers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, repo, subdir, maturity, notify_only }),
  });
  loadContainers();
}

async function patchContainer(name, payload) {
  await fetch(`/api/containers/${name}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  loadContainers();
}

async function removeContainer(name) {
  if (!confirm(`Remove ${name} from monitoring? (event history is kept) Confirm again to proceed.`)) return;
  await fetch(`/api/containers/${name}`, { method: "DELETE" });
  loadContainers();
}

async function loadEvents() {
  const res = await fetch("/api/events?limit=50");
  const rows = await res.json();
  const tbody = document.querySelector("#events-table tbody");
  tbody.innerHTML = "";
  for (const e of rows) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${e.last_seen}</td><td>${e.container}</td><td>${e.fingerprint}</td><td>${e.count}</td><td>${e.status}</td><td>${e.gate_reason ?? "-"}</td>`;
    tbody.appendChild(tr);
  }
}

let watcherPaused = false;
async function toggleWatcher() {
  const endpoint = watcherPaused ? "resume" : "pause";
  await fetch(`/api/watcher/${endpoint}`, { method: "POST" });
  watcherPaused = !watcherPaused;
  document.getElementById("watcher-toggle").textContent = watcherPaused ? "Resume watcher" : "Pause watcher";
}

loadContainers();
```

```python
# log-medic/app/main.py (add near the bottom, after app.include_router calls)
from pathlib import Path

from fastapi.staticfiles import StaticFiles

_static = Path(__file__).parent / "static"
if _static.exists():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
```

- [ ] **Step 3: Manual verification**

Run: `cd log-medic && DATA_DIR=/tmp/lm uvicorn app.main:app --port 5070` then open `http://localhost:5070/` in a browser; confirm the Containers tab lists nothing initially, adding a container via the form calls `POST /api/containers` and re-renders the table, and the Events tab loads without error.

- [ ] **Step 4: Commit**

```bash
git add log-medic/app/static/ log-medic/app/main.py
git commit -m "feat(log-medic): dashboard (Containers + Events tabs)"
```

---

### Task 13: README, docs, final review pass

**Files:**
- Create: `log-medic/README.md`
- Modify: `log-medic/.notes/00_INDEX.md` (expand with schema/API summary)
- Create: `log-medic/.notes/daily_log.md`
- Modify: root `CLAUDE.md` (add `log-medic/` row to the Stacks & Ports table)
- Modify: root `README.md` (if it has a stacks list — check and add log-medic entry to match)

**Interfaces:** none (docs only)

- [ ] **Step 1: Write README.md**

```markdown
# log-medic

Monitors Docker container logs on the NAS, detects WARN/ERROR lines, fingerprints
and deduplicates them, and — depending on the target container's declared
maturity — either just records the event, sends a Telegram notification with
root-cause analysis (via headless Claude Code), or opens a GitHub PR with a
proposed fix (`stable` maturity + `ENABLE_FIX_RUNNER=true` only; never auto-merged).

## Maturity levels
- `dev` — log only, no Claude/Telegram call.
- `staging` — root-cause analysis + Telegram notify, no code edit.
- `stable` — analysis + notify, and (if `ENABLE_FIX_RUNNER=true`) opens a PR.

## Gate order (per matched log line)
1. Maturity (`dev` stops here) / `notify_only` (bypasses everything else)
2. Grace period — `GRACE_PERIOD_MINUTES` after container start/restart or image change
3. Circuit breaker — `STORM_THRESHOLD_PER_HOUR` new fingerprints/hour trips it; auto-resets after 6h quiet
4. Cooldown/quota — `COOLDOWN_HOURS` per fingerprint, `DAILY_QUOTA` analyses/day system-wide
5. Dirty repo — uncommitted changes, non-main branch, stale commits (`REPO_IDLE_HOURS`), or an existing `fix/<fp>` branch

## One-time setup before first deploy
1. `make edit-vault` — add `stacks.log_medic.dashboard.{user,password}` and `stacks.log_medic.github_token`.
2. `htpasswd -c log-medic/nginx/.htpasswd <user>` locally (gitignored, not committed).
3. On the NAS: `git clone <remote> /volume2/docker/log-medic/workspaces/centralized-nas-container-management` — the app only ever runs `git fetch` there, never `git clone`.

## Dashboard
`https://<nas>:15070/` — Containers tab (add/pause/remove monitored containers,
merged with running-but-undiscovered containers) and Events tab (last 50 events).
Protected by nginx Basic Auth.
```

- [ ] **Step 2: Write `.notes/daily_log.md` and expand `.notes/00_INDEX.md`**

```markdown
# log-medic/.notes/daily_log.md
## 2026-07-04 — Initial implementation (feat/log-medic)
Built the full stack per docs/superpowers/plans/2026-07-04-log-medic-implementation.md:
db schema, vendored notify.py, config.yaml seeding, fingerprint normalization +
ring buffer, 5-gate pipeline, docker-py watcher with hot reload, analyzer
phase 1 (read-only) + phase 2 (fix+PR with forbidden-file/diff-size safety
rails), scheduler (breaker auto-reset + 18:00 digest), API routes, dashboard.
Not yet deployed to NAS — vault keys and nginx/.htpasswd still need the
one-time manual setup in README.md.
```

Update `log-medic/.notes/00_INDEX.md` to append (below the existing Gaps/TODOs from Task 1):

```markdown

## Schema
See `app/db.py` — `monitored_containers`, `events`, `daily_quota`, `circuit_breaker`, `audit_log`.

## API
`GET/POST /api/containers`, `PATCH/DELETE /api/containers/{name}`, `GET /api/events`,
`POST /api/watcher/{pause,resume}`, `GET /health`. All behind nginx Basic Auth except
health (also behind auth per spec — no public exception for log-medic, unlike
friendly-reminder's LINE webhook).
```

- [ ] **Step 3: Update root docs**

Add a row to the Stacks & Ports table in root `CLAUDE.md` (alphabetical-ish, after `jellyfin/`):

```markdown
| `log-medic/` | Docker log monitor + Claude-powered auto-fix | 5070 / 15070 | Watches container logs via docker-py, fingerprints WARN/ERROR, 5-gate pipeline (maturity/grace/breaker/cooldown-quota/dirty-repo). `staging`+ maturity gets Telegram root-cause analysis via headless `claude -p`; `stable` + `ENABLE_FIX_RUNNER=true` additionally opens a GitHub PR (never auto-merged). Dashboard + `/api/*` behind nginx Basic Auth (`stacks.log_medic.dashboard.*`). Persistent git clone at `/volume2/docker/log-medic/workspaces/` — `git fetch` only, never re-cloned by the app. |
```

Check root `README.md` for a stacks list/table; if present, add the same one-line entry there for consistency.

- [ ] **Step 4: Commit**

```bash
git add log-medic/README.md log-medic/.notes/ CLAUDE.md README.md
git commit -m "docs(log-medic): README, notes, root stacks table entry"
```

---

## Self-Review

**Spec coverage** — every section of `docs/superpowers/specs/2026-07-04-log-medic-design.md` maps to a task:
- Architecture/file tree → Tasks 1, 3, 6, 7, 8, 9, 10, 11, 12
- Data model → Task 1 (`db.py`)
- Watch → Gate → Act pipeline (5 gates, hot reload, ring buffer, normalization) → Tasks 4, 5, 6
- Analyzer phase 1 → Task 7; phase 2 (branch naming, `ENABLE_FIX_RUNNER`, forbidden files, diff cap, PR body) → Task 8
- Dashboard + API + audit log → Tasks 10, 12 (audit log calls added in `containers.py`'s mutating routes)
- Notifications (Telegram reuse) → Tasks 2, 3
- LLM config (MiMo proxy) → Task 1 (`secrets.manifest.yaml`, `.env.example`)
- New secrets → Task 1 manifest + Task 13 README setup steps
- Config literals with exact defaults → Task 1 manifest/`.env.example`, consumed in Tasks 5, 6
- Testing/DoD → covered by each task's own tests; the `docker compose up -d --build` + `log-medic-test` container + dashboard-flow checks are manual, called out in Task 12/README
- Implementation branch policy (`feat/log-medic`) → Global Constraints + Task 1 Step 5 (branch created there)

**Placeholder scan** — no "TBD"/"TODO"/"add appropriate X" found; the one deliberately-empty function is `scheduler._quota_reset_job`, which has a code comment explaining it's a documented no-op (daily_quota is date-keyed, so nothing to reset) rather than an unfinished stub.

**Type/signature consistency** — checked across tasks:
- `db.record_event(conn, fingerprint, container, status, gate_reason=None, now=None)` used identically in Tasks 1, 5, 6, 9 tests.
- `db.update_event_status(conn, fingerprint, container, status, gate_reason=None, analysis=None, pr_url=None)` used identically in Tasks 1, 6.
- `gate.evaluate(conn, container, fingerprint, started_at, workspace_dir, now=None)` signature matches its Task 5 definition and its Task 6 call site.
- `analyzer.analyze(container_row, fingerprint, excerpt) -> dict` and `analyzer.run_fix(container_row, fingerprint, analysis, workspace_dir) -> str | None` match between Tasks 7/8 definitions and Task 6's `process_event` call sites.
- `notifier.notify(text) -> list[str]` used consistently as `from app.notifier import notify` in Tasks 6, 8, 9 (watcher.py imports it as `from app.notifier import notify`, matching the module-level `notify` name patched in tests via `monkeypatch.setattr(watcher, "notify", ...)` and `patch("app.analyzer.notify")`).

**Fix applied during self-review:** Task 6's original draft had `watcher.py` importing `notify` from `app.notify` (the vendored low-level `Notifier` class) instead of `app.notifier` (the pre-configured wrapper built in Task 3). Corrected the import to `from app.notifier import notify` so `watcher.py` doesn't need to reconstruct `TgCreds` itself — this also matches what the Task 6 tests patch (`monkeypatch.setattr(watcher, "notify", ...)`, which requires `notify` to be a name bound directly in `watcher`'s module namespace).
