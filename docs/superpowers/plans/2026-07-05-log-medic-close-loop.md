# log-medic Close-the-Loop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the v1 pipeline loop: triage analysis verdicts (code vs infra) before running the fix runner, detect PR merges by polling GitHub, and auto-deploy merged fixes to the NAS runtime dirs.

**Architecture:** Three additive changes to the existing watch → gate → analyze → PR pipeline. (1) The analyze prompt emits a mandatory `VERDICT: code|infra` first line; the watcher only invokes the fix runner on `code`. (2) A new APScheduler job polls `gh pr view` every 5 minutes for events stuck at `pr_opened`. (3) A new `app/deployer.py` syncs the workspace clone, copies git-tracked files into `/stacks/<stack>/` (a new bind mount of `/volume2/docker`), and runs `docker compose up -d --build` through the mounted socket, then verifies the container is running.

**Tech Stack:** Python 3.12, FastAPI, APScheduler (`BackgroundScheduler`), docker-py 7.1.0, `gh` CLI (already in image), docker CLI + compose plugin (added to image), SQLite, pytest with `unittest.mock.patch`.

**Spec:** `docs/superpowers/specs/2026-07-05-log-medic-close-loop-design.md`

## Global Constraints

- Working dir for all commands: `log-medic/` unless stated otherwise.
- Run tests with: `python3 -m pytest tests/ -v` (workstation has `docker==7.1.0` installed via `--break-system-packages`; all other deps in global env).
- Verdict fail-safe: unparseable/missing verdict → `"infra"` — a malformed response must NEVER trigger the fix runner.
- Deploy copies ONLY git-tracked files — never delete anything in the destination, never touch `.env`, `data/`, `.htpasswd`, `*.db`.
- `deploy_failed` is terminal: no automatic retry.
- `gh` binary and `GITHUB_TOKEN` already provisioned (v1) — no new secrets.
- Never add a `Co-Authored-By: Claude` trailer to commits.
- Status vocabulary after this plan: `new, notified, gated, analyzed, pr_opened, pr_closed, merged, deployed, deploy_failed`.

---

### Task 1: DB — `verdict` column, status-query helper, `verdict` in `update_event_status`

**Files:**
- Modify: `log-medic/app/db.py`
- Test: `log-medic/tests/test_db.py`

**Interfaces:**
- Produces: `events.verdict TEXT` column (nullable); `db.get_events_by_status(conn, status: str) -> list[sqlite3.Row]`; `db.update_event_status(..., verdict: str | None = None)` (keyword, COALESCE semantics like the other optional fields).
- Consumed by: Task 3 (watcher stores verdict), Task 5 (poll job queries `pr_opened` events).

- [ ] **Step 1: Write the failing tests**

Append to `log-medic/tests/test_db.py`:

```python
def test_verdict_column_and_migration_is_idempotent(tmp_path):
    from app import db
    conn = db.get_conn(str(tmp_path / "t.db"))
    db.init_db(conn)
    db.init_db(conn)  # second run must not raise (duplicate column guard)
    db.record_event(conn, "fp1", "c1", status="analyzed")
    db.update_event_status(conn, "fp1", "c1", status="analyzed", verdict="code")
    row = conn.execute("SELECT verdict FROM events WHERE fingerprint='fp1'").fetchone()
    assert row["verdict"] == "code"


def test_verdict_column_added_to_existing_db(tmp_path):
    """DB created with the v1 schema (no verdict) must gain the column on init_db."""
    import sqlite3
    from app import db
    path = str(tmp_path / "old.db")
    old = sqlite3.connect(path)
    old.execute(
        "CREATE TABLE events (fingerprint TEXT NOT NULL, container TEXT NOT NULL,"
        " first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,"
        " count INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL,"
        " gate_reason TEXT, analysis TEXT, pr_url TEXT,"
        " PRIMARY KEY (fingerprint, container))"
    )
    old.commit()
    old.close()
    conn = db.get_conn(path)
    db.init_db(conn)
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(events)").fetchall()]
    assert "verdict" in cols


def test_get_events_by_status(tmp_path):
    from app import db
    conn = db.get_conn(str(tmp_path / "t.db"))
    db.init_db(conn)
    db.record_event(conn, "fp1", "c1", status="analyzed")
    db.record_event(conn, "fp2", "c1", status="analyzed")
    db.update_event_status(conn, "fp2", "c1", status="pr_opened", pr_url="https://github.com/o/r/pull/1")
    rows = db.get_events_by_status(conn, "pr_opened")
    assert len(rows) == 1
    assert rows[0]["fingerprint"] == "fp2"
    assert rows[0]["pr_url"] == "https://github.com/o/r/pull/1"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_db.py -v`
Expected: 3 new tests FAIL (`no such column: verdict` / `AttributeError: ... get_events_by_status` / `TypeError: ... unexpected keyword argument 'verdict'`).

- [ ] **Step 3: Implement**

In `log-medic/app/db.py`:

Add `verdict TEXT,` to the `events` CREATE TABLE in `_SCHEMA` (after `pr_url TEXT,`):

```python
CREATE TABLE IF NOT EXISTS events (
    fingerprint TEXT NOT NULL,
    container TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL,
    gate_reason TEXT,
    analysis TEXT,
    pr_url TEXT,
    verdict TEXT,
    PRIMARY KEY (fingerprint, container)
);
```

Extend `init_db` with an additive migration for DBs created before this column existed:

```python
def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA)
    # Additive migration: v1 DBs lack events.verdict. CREATE TABLE IF NOT EXISTS
    # skips existing tables, so ALTER explicitly and swallow the duplicate error.
    try:
        conn.execute("ALTER TABLE events ADD COLUMN verdict TEXT")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()
```

Add `verdict` to `update_event_status` (same COALESCE pattern as the other optional fields):

```python
def update_event_status(
    conn: sqlite3.Connection,
    fingerprint: str,
    container: str,
    status: str,
    gate_reason: str | None = None,
    analysis: str | None = None,
    pr_url: str | None = None,
    verdict: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE events SET status=?,
        gate_reason=COALESCE(?, gate_reason),
        analysis=COALESCE(?, analysis),
        pr_url=COALESCE(?, pr_url),
        verdict=COALESCE(?, verdict)
        WHERE fingerprint=? AND container=?
        """,
        (status, gate_reason, analysis, pr_url, verdict, fingerprint, container),
    )
    conn.commit()
```

Add the status query helper (place next to `get_recent_events`):

```python
def get_events_by_status(conn: sqlite3.Connection, status: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM events WHERE status=? ORDER BY last_seen DESC", (status,)
    ).fetchall()
```

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS (45 existing + 3 new).

- [ ] **Step 5: Commit**

```bash
git add log-medic/app/db.py log-medic/tests/test_db.py
git commit -m "feat(log-medic): events.verdict column + get_events_by_status"
```

---

### Task 2: Analyzer — VERDICT line in prompt, parse into `analysis["verdict"]`

**Files:**
- Modify: `log-medic/prompts/analyze.md`
- Modify: `log-medic/app/analyzer.py`
- Test: `log-medic/tests/test_analyzer.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `analyzer.analyze(...)` now returns `{"text": str, "excerpt": str, "verdict": "code" | "infra"}`. The `VERDICT:` line is stripped from `text`. Module-level `analyzer.parse_verdict(raw_text: str) -> tuple[str, str]` returning `(verdict, remaining_text)`.

- [ ] **Step 1: Write the failing tests**

Append to `log-medic/tests/test_analyzer.py`:

```python
def test_parse_verdict_code():
    import app.analyzer as analyzer
    verdict, text = analyzer.parse_verdict("VERDICT: code\nRoot cause: off-by-one in loop.")
    assert verdict == "code"
    assert text == "Root cause: off-by-one in loop."


def test_parse_verdict_infra_case_insensitive():
    import app.analyzer as analyzer
    verdict, text = analyzer.parse_verdict("verdict:  INFRA\nUpstream API returned 503.")
    assert verdict == "infra"
    assert text == "Upstream API returned 503."


def test_parse_verdict_missing_defaults_to_infra():
    import app.analyzer as analyzer
    verdict, text = analyzer.parse_verdict("Root cause: something.")
    assert verdict == "infra"
    assert text == "Root cause: something."


def test_parse_verdict_garbage_value_defaults_to_infra():
    import app.analyzer as analyzer
    verdict, text = analyzer.parse_verdict("VERDICT: maybe\nUnclear.")
    assert verdict == "infra"
    # unrecognized verdict line is left in the text untouched
    assert text == "VERDICT: maybe\nUnclear."


@patch("subprocess.run")
def test_analyze_returns_verdict(mock_run):
    import app.analyzer as analyzer
    mock_run.return_value = MagicMock(
        stdout='{"result": "VERDICT: code\\nRoot cause: bad regex."}', returncode=0
    )
    row = {"name": "torrentwatch", "repo": "/workspaces/r", "subdir": "torrentwatch"}
    result = analyzer.analyze(row, "fp123", "ERROR boom")
    assert result["verdict"] == "code"
    assert result["text"] == "Root cause: bad regex."
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_analyzer.py -v`
Expected: 5 new tests FAIL (`AttributeError: module 'app.analyzer' has no attribute 'parse_verdict'`, missing `verdict` key).

- [ ] **Step 3: Implement**

In `log-medic/prompts/analyze.md`, replace the `## Task` section with:

```markdown
## Task
1. Identify the root cause of this error.
2. Classify it:
   - `code` — the root cause lives in this service's source code in this repo; a code change can fix it.
   - `infra` — network failure, external API outage or rate limit, disk/permission problem, or runtime configuration issue; a code change cannot fix it.
3. Propose a fix as a description of the change (not an actual diff/patch).

## Response format (mandatory)
The FIRST line of your response must be exactly one of:

VERDICT: code
VERDICT: infra

Then a few sentences of root cause, followed by the proposed fix description.
```

In `log-medic/app/analyzer.py`, add near the top (after the constants):

```python
_VERDICT_RE = re.compile(r"^\s*VERDICT:\s*(code|infra)\s*$", re.IGNORECASE)


def parse_verdict(raw_text: str) -> tuple[str, str]:
    """Extract the mandatory VERDICT first line. Fail-safe: anything
    unparseable is 'infra' so a malformed response never triggers the fix
    runner; in that case the text is returned untouched for the notification."""
    first, _, rest = raw_text.partition("\n")
    m = _VERDICT_RE.match(first)
    if m:
        return m.group(1).lower(), rest.strip()
    return "infra", raw_text.strip()
```

Change the tail of `analyze()`:

```python
    try:
        payload = json.loads(result.stdout or "{}")
        text = payload.get("result", result.stdout.strip())
    except json.JSONDecodeError:
        text = result.stdout.strip()
    verdict, text = parse_verdict(text)
    return {"text": text, "excerpt": excerpt, "verdict": verdict}
```

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS. (`test_analyze_invokes_claude_readonly_and_parses_json` still passes: its stdout has no VERDICT line, so `text` is unchanged and the extra `verdict` key is ignored by the assertion.)

- [ ] **Step 5: Commit**

```bash
git add log-medic/prompts/analyze.md log-medic/app/analyzer.py log-medic/tests/test_analyzer.py
git commit -m "feat(log-medic): mandatory VERDICT triage line in analysis"
```

---

### Task 3: Watcher — route fix runner on verdict, store verdict, verdict emoji in notify

**Files:**
- Modify: `log-medic/app/watcher.py` (in `process_event`, currently lines 99–110)
- Test: `log-medic/tests/test_watcher.py`

**Interfaces:**
- Consumes: `analysis["verdict"]` from Task 2; `db.update_event_status(..., verdict=...)` from Task 1.
- Produces: fix runner only fires when `maturity == "stable" AND ENABLE_FIX_RUNNER AND verdict == "code"`. Telegram root-cause message becomes `f"🔎 {name} [{icon} {verdict}]\nRoot cause: ..."` with 🐛 for code, 🌐 for infra.

- [ ] **Step 1: Write the failing tests**

Append to `log-medic/tests/test_watcher.py`. Match the file's existing style for `process_event` tests (tmp-file DB via `db.get_conn(str(tmp_path / "t.db"))` + `db.init_db`, container row dict, `@patch` on `app.watcher.notify` / `app.watcher.analyzer`, `monkeypatch.setenv("ENABLE_FIX_RUNNER", "true")`) — read the existing `process_event` tests in the file first and reuse their setup helper if one exists:

```python
def _stable_row(name="svc1"):
    return {
        "name": name,
        "repo": "/workspaces/centralized-nas-container-management",
        "subdir": name,
        "maturity": "stable",
        "notify_only": 0,
        "paused": 0,
    }


@patch("app.watcher.gate.evaluate", return_value=None)
@patch("app.watcher.notify")
@patch("app.watcher.analyzer")
def test_infra_verdict_skips_fix_runner_on_stable(mock_analyzer, mock_notify, _gate, monkeypatch, tmp_path):
    from datetime import UTC, datetime
    from app import db, watcher
    monkeypatch.setenv("ENABLE_FIX_RUNNER", "true")
    conn = db.get_conn(str(tmp_path / "t.db"))  # not ":memory:" — get_conn makedirs(dirname) would get ""
    db.init_db(conn)
    mock_analyzer.analyze.return_value = {"text": "upstream 503", "excerpt": "E", "verdict": "infra"}
    watcher.process_event(conn, _stable_row(), "fp1", "E", "ERROR x", datetime.now(UTC))
    mock_analyzer.run_fix.assert_not_called()
    row = conn.execute("SELECT status, verdict FROM events WHERE fingerprint='fp1'").fetchone()
    assert row["status"] == "analyzed"
    assert row["verdict"] == "infra"
    assert "🌐 infra" in mock_notify.call_args_list[0].args[0]


@patch("app.watcher.gate.evaluate", return_value=None)
@patch("app.watcher.notify")
@patch("app.watcher.analyzer")
def test_code_verdict_runs_fix_on_stable(mock_analyzer, mock_notify, _gate, monkeypatch, tmp_path):
    from datetime import UTC, datetime
    from app import db, watcher
    monkeypatch.setenv("ENABLE_FIX_RUNNER", "true")
    conn = db.get_conn(str(tmp_path / "t.db"))
    db.init_db(conn)
    mock_analyzer.analyze.return_value = {"text": "bad regex", "excerpt": "E", "verdict": "code"}
    mock_analyzer.run_fix.return_value = "https://github.com/o/r/pull/7"
    watcher.process_event(conn, _stable_row(), "fp2", "E", "ERROR x", datetime.now(UTC))
    mock_analyzer.run_fix.assert_called_once()
    row = conn.execute("SELECT status, verdict, pr_url FROM events WHERE fingerprint='fp2'").fetchone()
    assert row["status"] == "pr_opened"
    assert row["verdict"] == "code"
    assert row["pr_url"] == "https://github.com/o/r/pull/7"
    assert "🐛 code" in mock_notify.call_args_list[0].args[0]
```

Note: `gate.evaluate` is patched to bypass `check_dirty_repo` (no real workspace exists in tests). If the existing `process_event` tests patch differently (e.g. patch `app.watcher.gate` wholesale), copy their approach exactly — but then also make the patched `maybe_trip_breaker` a no-op mock.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_watcher.py -v`
Expected: the 2 new tests FAIL — `run_fix` currently called regardless of verdict; no `verdict` stored; no emoji in message.

- [ ] **Step 3: Implement**

In `log-medic/app/watcher.py`, replace `process_event` lines 99–110 with:

```python
    analysis = analyzer.analyze(container_row, fp, excerpt)
    verdict = analysis.get("verdict", "infra")
    db.update_event_status(conn, fp, name, status="analyzed", analysis=analysis["text"], verdict=verdict)
    db.increment_quota(conn)
    icon = "🐛" if verdict == "code" else "🌐"
    notify(f"🔎 {name} [{icon} {verdict}]\nRoot cause: {analysis['text']}")

    if (
        container_row["maturity"] == "stable"
        and os.environ.get("ENABLE_FIX_RUNNER", "false").lower() == "true"
        and verdict == "code"
    ):
        pr_url = analyzer.run_fix(container_row, fp, analysis, workspace_dir)
        if pr_url:
            db.update_event_status(conn, fp, name, status="pr_opened", pr_url=pr_url)
            notify(f"🛠 PR opened for {name}: {pr_url}")
        else:
            db.update_event_status(conn, fp, name, status="analyzed", gate_reason="fix_rejected")
```

If existing `process_event` tests stub `analyze` with a dict lacking `verdict`, they keep passing via the `.get(..., "infra")` default — but any that assert `run_fix` WAS called must have `"verdict": "code"` added to their stub return. Update those stubs, not the assertion.

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add log-medic/app/watcher.py log-medic/tests/test_watcher.py
git commit -m "feat(log-medic): gate fix runner on code verdict"
```

---

### Task 4: Deployer module — sync, tracked-copy, compose up, verify

**Files:**
- Create: `log-medic/app/deployer.py`
- Test: `log-medic/tests/test_deployer.py` (new)

**Interfaces:**
- Consumes: `db.update_event_status` (Task 1), `notify` from `app.notifier`, docker-py client passed in.
- Produces: `deployer.deploy(conn, container_row, fingerprint: str, pr_url: str, docker_client=None, sleep=time.sleep) -> bool` — the only function Task 5 calls. Also (unit-tested directly): `copy_tracked_files(workspace_repo_root: str, subdir: str, dest_stack_dir: str) -> int` and `SELF_STACK = "log-medic"`.

- [ ] **Step 1: Write the failing tests**

Create `log-medic/tests/test_deployer.py`:

```python
import subprocess
from unittest.mock import MagicMock, patch


def _row(name="torrentwatch", subdir="torrentwatch"):
    return {
        "name": name,
        "repo": "/workspaces/centralized-nas-container-management",
        "subdir": subdir,
        "maturity": "stable",
    }


def _init_repo(path):
    def run(args):
        subprocess.run(args, cwd=str(path), check=True, capture_output=True, text=True)
    run(["git", "init", "-b", "main"])
    run(["git", "config", "user.email", "t@e.com"])
    run(["git", "config", "user.name", "T"])
    return run


def test_copy_tracked_files_copies_tracked_and_spares_env(tmp_path):
    """Real-git test: tracked files under subdir are copied; untracked .env and
    data/ in the destination survive untouched; files outside subdir ignored."""
    from app import deployer
    ws = tmp_path / "ws"
    ws.mkdir()
    run = _init_repo(ws)
    (ws / "torrentwatch").mkdir()
    (ws / "torrentwatch" / "main.py").write_text("v2\n")
    (ws / "torrentwatch" / "sub").mkdir()
    (ws / "torrentwatch" / "sub" / "util.py").write_text("u\n")
    (ws / "other-stack").mkdir()
    (ws / "other-stack" / "x.py").write_text("x\n")
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", "init"])

    dest = tmp_path / "stacks" / "torrentwatch"
    dest.mkdir(parents=True)
    (dest / ".env").write_text("SECRET=1\n")
    (dest / "data").mkdir()
    (dest / "data" / "app.db").write_text("blob")
    (dest / "main.py").write_text("v1\n")

    n = deployer.copy_tracked_files(str(ws), "torrentwatch", str(dest))
    assert n == 2
    assert (dest / "main.py").read_text() == "v2\n"
    assert (dest / "sub" / "util.py").read_text() == "u\n"
    assert (dest / ".env").read_text() == "SECRET=1\n"
    assert (dest / "data" / "app.db").read_text() == "blob"
    assert not (dest / "x.py").exists()


@patch("app.deployer.notify")
def test_deploy_self_stack_skips_and_notifies(mock_notify, tmp_path):
    from app import db, deployer
    conn = db.get_conn(str(tmp_path / "t.db"))
    db.init_db(conn)
    db.record_event(conn, "fp1", "log-medic", status="merged")
    ok = deployer.deploy(conn, _row(name="log-medic", subdir="log-medic"), "fp1", "https://github.com/o/r/pull/9")
    assert ok is False
    assert "manually" in mock_notify.call_args.args[0]
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp1'").fetchone()
    assert row["status"] == "merged"  # terminal, not deploy_failed


@patch("app.deployer.notify")
@patch("app.deployer.copy_tracked_files", return_value=3)
@patch("subprocess.run")
def test_deploy_happy_path(mock_run, mock_copy, mock_notify, tmp_path):
    from app import db, deployer
    conn = db.get_conn(str(tmp_path / "t.db"))
    db.init_db(conn)
    db.record_event(conn, "fp2", "torrentwatch", status="merged")

    mock_run.return_value = MagicMock(returncode=0, stdout="")
    docker_client = MagicMock()
    container = MagicMock()
    container.attrs = {"State": {"Running": True}, "RestartCount": 0}
    docker_client.containers.get.return_value = container

    ok = deployer.deploy(conn, _row(), "fp2", "https://github.com/o/r/pull/10",
                         docker_client=docker_client, sleep=lambda s: None)
    assert ok is True
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp2'").fetchone()
    assert row["status"] == "deployed"
    assert "🚀" in mock_notify.call_args.args[0]

    calls = [c.args[0] for c in mock_run.call_args_list]
    assert ["git", "fetch", "origin"] in calls
    assert ["git", "checkout", "-B", "main", "origin/main"] in calls
    assert ["git", "reset", "--hard", "origin/main"] in calls
    assert any(c[:3] == ["docker", "compose", "--project-directory"] for c in calls)


@patch("app.deployer.notify")
@patch("app.deployer.copy_tracked_files", return_value=3)
@patch("subprocess.run")
def test_deploy_compose_failure_marks_deploy_failed(mock_run, mock_copy, mock_notify, tmp_path):
    from app import db, deployer
    conn = db.get_conn(str(tmp_path / "t.db"))
    db.init_db(conn)
    db.record_event(conn, "fp3", "torrentwatch", status="merged")

    def side_effect(args, **kwargs):
        if args[:2] == ["docker", "compose"]:
            raise subprocess.CalledProcessError(1, args, stderr="build failed")
        return MagicMock(returncode=0, stdout="")

    mock_run.side_effect = side_effect
    ok = deployer.deploy(conn, _row(), "fp3", "https://github.com/o/r/pull/11",
                         docker_client=MagicMock(), sleep=lambda s: None)
    assert ok is False
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp3'").fetchone()
    assert row["status"] == "deploy_failed"
    assert "❌" in mock_notify.call_args.args[0]


@patch("app.deployer.notify")
@patch("app.deployer.copy_tracked_files", return_value=3)
@patch("subprocess.run")
def test_deploy_container_not_running_marks_deploy_failed(mock_run, mock_copy, mock_notify, tmp_path):
    from app import db, deployer
    conn = db.get_conn(str(tmp_path / "t.db"))
    db.init_db(conn)
    db.record_event(conn, "fp4", "torrentwatch", status="merged")

    mock_run.return_value = MagicMock(returncode=0, stdout="")
    docker_client = MagicMock()
    container = MagicMock()
    container.attrs = {"State": {"Running": False}, "RestartCount": 4}
    docker_client.containers.get.return_value = container

    ok = deployer.deploy(conn, _row(), "fp4", "https://github.com/o/r/pull/12",
                         docker_client=docker_client, sleep=lambda s: None)
    assert ok is False
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp4'").fetchone()
    assert row["status"] == "deploy_failed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_deployer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.deployer'`.

- [ ] **Step 3: Implement**

Create `log-medic/app/deployer.py`:

```python
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time

import docker

from app import db
from app.notifier import notify

logger = logging.getLogger(__name__)

STACKS_ROOT = os.environ.get("STACKS_ROOT", "/stacks")
SELF_STACK = "log-medic"
COMPOSE_TIMEOUT_SECONDS = 600
VERIFY_DELAY_SECONDS = 60


def _workspace_repo_root(container_row) -> str:
    repo = (container_row["repo"] or "").rstrip("/")
    return os.path.join("/workspaces", os.path.basename(repo))


def copy_tracked_files(workspace_repo_root: str, subdir: str, dest_stack_dir: str) -> int:
    """Copy every git-tracked file under subdir into the runtime stack dir.
    Never deletes anything at the destination, so .env / data volumes /
    .htpasswd living only on the NAS are structurally untouchable."""
    listed = subprocess.run(
        ["git", "ls-files", "-z", subdir],
        cwd=workspace_repo_root, capture_output=True, text=True, check=True,
    ).stdout
    files = [f for f in listed.split("\0") if f]
    prefix = subdir.rstrip("/") + "/"
    for tracked in files:
        rel = tracked[len(prefix):] if tracked.startswith(prefix) else tracked
        src = os.path.join(workspace_repo_root, tracked)
        dst = os.path.join(dest_stack_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    return len(files)


def deploy(conn, container_row, fingerprint: str, pr_url: str,
           docker_client=None, sleep=time.sleep) -> bool:
    name = container_row["name"]
    subdir = (container_row["subdir"] or "").strip("/")

    if subdir == SELF_STACK:
        notify(f"⚠️ PR merged for {SELF_STACK} itself — deploy manually from the workstation\n{pr_url}")
        return False  # status stays 'merged' (terminal for self-deploy)

    repo_root = _workspace_repo_root(container_row)
    stack_dir = os.path.join(STACKS_ROOT, subdir)
    step = "sync_workspace"
    try:
        subprocess.run(["git", "fetch", "origin"], cwd=repo_root, check=True,
                       capture_output=True, text=True)
        subprocess.run(["git", "checkout", "-B", "main", "origin/main"], cwd=repo_root,
                       check=True, capture_output=True, text=True)
        subprocess.run(["git", "reset", "--hard", "origin/main"], cwd=repo_root,
                       check=True, capture_output=True, text=True)

        step = "copy_files"
        copied = copy_tracked_files(repo_root, subdir, stack_dir)

        step = "compose_up"
        subprocess.run(
            ["docker", "compose", "--project-directory", stack_dir,
             "-f", os.path.join(stack_dir, "docker-compose.yml"),
             "up", "-d", "--build"],
            check=True, capture_output=True, text=True, timeout=COMPOSE_TIMEOUT_SECONDS,
        )

        step = "verify"
        client = docker_client or docker.from_env()
        baseline = client.containers.get(name).attrs.get("RestartCount", 0)
        sleep(VERIFY_DELAY_SECONDS)
        container = client.containers.get(name)
        running = container.attrs["State"]["Running"]
        restarts = container.attrs.get("RestartCount", 0)
        if not running or restarts > baseline:
            raise RuntimeError(f"container not healthy (running={running}, restarts={restarts})")
    except Exception as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        logger.exception("deploy failed for %s at %s", name, step)
        db.update_event_status(conn, fingerprint, name, status="deploy_failed")
        notify(
            f"❌ Deploy failed for {name} at step {step}: {str(detail)[:300]}\n"
            f"Recovery: git revert the fix commit and merge the revert PR."
        )
        return False

    db.update_event_status(conn, fingerprint, name, status="deployed")
    notify(f"🚀 Deployed {name} ({copied} files) — PR merged: {pr_url}")
    return True
```

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS (5 new deployer tests).

- [ ] **Step 5: Commit**

```bash
git add log-medic/app/deployer.py log-medic/tests/test_deployer.py
git commit -m "feat(log-medic): deployer — sync workspace, copy tracked files, compose up, verify"
```

---

### Task 5: Scheduler — `poll_pr_merges` job (every 5 min)

**Files:**
- Modify: `log-medic/app/scheduler.py`
- Test: `log-medic/tests/test_scheduler.py`

**Interfaces:**
- Consumes: `db.get_events_by_status(conn, "pr_opened")` (Task 1), `deployer.deploy(...)` (Task 4), `analyzer.workspace_dir(row)` (existing), `db.get_monitored_container` (existing).
- Produces: `scheduler.poll_pr_merges_job(db_path: str | None) -> None`, registered as job id `poll_pr_merges` with `IntervalTrigger(minutes=5)`.

- [ ] **Step 1: Write the failing tests**

Append to `log-medic/tests/test_scheduler.py`:

```python
import json
from unittest.mock import MagicMock, patch


def _seed_pr_event(tmp_path, name="torrentwatch"):
    from app import db
    path = str(tmp_path / "t.db")
    conn = db.get_conn(path)
    db.init_db(conn)
    db.upsert_monitored_container(conn, name, "/workspaces/repo", name, "stable", 0, 0, None)
    db.record_event(conn, "fp1", name, status="analyzed")
    db.update_event_status(conn, "fp1", name, status="pr_opened",
                           pr_url="https://github.com/o/r/pull/5")
    return path, conn


@patch("app.scheduler.deployer")
@patch("app.scheduler.subprocess.run")
def test_poll_merged_pr_triggers_deploy(mock_run, mock_deployer, tmp_path):
    from app import scheduler
    path, conn = _seed_pr_event(tmp_path)
    mock_run.return_value = MagicMock(
        returncode=0, stdout=json.dumps({"state": "MERGED", "mergedAt": "2026-07-05T10:00:00Z"})
    )
    scheduler.poll_pr_merges_job(path)
    mock_deployer.deploy.assert_called_once()
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp1'").fetchone()
    # status is 'merged' when deploy is invoked; deploy itself moves it on (mocked here)
    assert row["status"] == "merged"


@patch("app.scheduler.notify")
@patch("app.scheduler.deployer")
@patch("app.scheduler.subprocess.run")
def test_poll_closed_pr_marks_pr_closed_no_deploy(mock_run, mock_deployer, mock_notify, tmp_path):
    from app import scheduler

    def side_effect(args, **kwargs):
        if args[:3] == ["gh", "pr", "view"]:
            return MagicMock(returncode=0, stdout=json.dumps({"state": "CLOSED", "mergedAt": None}))
        return MagicMock(returncode=0, stdout="")

    path, conn = _seed_pr_event(tmp_path)
    mock_run.side_effect = side_effect
    scheduler.poll_pr_merges_job(path)
    mock_deployer.deploy.assert_not_called()
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp1'").fetchone()
    assert row["status"] == "pr_closed"
    assert "without merge" in mock_notify.call_args.args[0]
    calls = [c.args[0] for c in mock_run.call_args_list]
    assert ["git", "push", "origin", "--delete", "fix/fp1"] in calls


@patch("app.scheduler.deployer")
@patch("app.scheduler.subprocess.run")
def test_poll_open_pr_left_alone(mock_run, mock_deployer, tmp_path):
    from app import scheduler
    path, conn = _seed_pr_event(tmp_path)
    mock_run.return_value = MagicMock(returncode=0, stdout=json.dumps({"state": "OPEN", "mergedAt": None}))
    scheduler.poll_pr_merges_job(path)
    mock_deployer.deploy.assert_not_called()
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp1'").fetchone()
    assert row["status"] == "pr_opened"


@patch("app.scheduler.deployer")
@patch("app.scheduler.subprocess.run")
def test_poll_gh_error_skips_event_without_crashing(mock_run, mock_deployer, tmp_path):
    from app import scheduler
    path, conn = _seed_pr_event(tmp_path)
    mock_run.side_effect = RuntimeError("gh exploded")
    scheduler.poll_pr_merges_job(path)  # must not raise
    mock_deployer.deploy.assert_not_called()
    row = conn.execute("SELECT status FROM events WHERE fingerprint='fp1'").fetchone()
    assert row["status"] == "pr_opened"  # untouched, retried next cycle


def test_poll_job_registered():
    from unittest.mock import patch as p
    with p("app.scheduler.BackgroundScheduler") as mock_sched_cls:
        from app import scheduler
        scheduler.setup_scheduler(":memory:")
        job_ids = [c.kwargs.get("id") for c in mock_sched_cls.return_value.add_job.call_args_list]
        assert "poll_pr_merges" in job_ids
```

Note: file-based DB (not `:memory:`) in the poll tests because the job opens its own connection via `db_path`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_scheduler.py -v`
Expected: new tests FAIL (`AttributeError: module 'app.scheduler' has no attribute 'poll_pr_merges_job'` etc.).

- [ ] **Step 3: Implement**

In `log-medic/app/scheduler.py`, add imports at the top:

```python
import json
import logging
import subprocess

from app import analyzer, db, deployer, gate

logger = logging.getLogger(__name__)
```

(Keep the existing `from app.notifier import notify` and datetime/apscheduler imports; merge the `from app import db, gate` line into the one above.)

Add the job function:

```python
def poll_pr_merges_job(db_path: str | None = None) -> None:
    """Every 5 min: check each pr_opened event's PR state on GitHub.
    MERGED -> deploy; CLOSED -> mark pr_closed + delete remote branch.
    Per-event errors are logged and retried next cycle — never crash the job."""
    conn = db.get_conn(db_path)
    try:
        for event in db.get_events_by_status(conn, "pr_opened"):
            name = event["container"]
            try:
                row = db.get_monitored_container(conn, name)
                if row is None or not event["pr_url"]:
                    continue
                workspace = analyzer.workspace_dir(row)
                result = subprocess.run(
                    ["gh", "pr", "view", event["pr_url"], "--json", "state,mergedAt"],
                    cwd=workspace, capture_output=True, text=True, check=True, timeout=60,
                )
                state = json.loads(result.stdout).get("state")
                if state == "MERGED":
                    db.update_event_status(conn, event["fingerprint"], name, status="merged")
                    deployer.deploy(conn, row, event["fingerprint"], event["pr_url"])
                elif state == "CLOSED":
                    db.update_event_status(conn, event["fingerprint"], name, status="pr_closed")
                    subprocess.run(
                        ["git", "push", "origin", "--delete", f"fix/{event['fingerprint']}"],
                        cwd=workspace, capture_output=True, text=True,
                    )  # best-effort, no check=True
                    notify(f"🚮 PR closed without merge for {name}, no deploy\n{event['pr_url']}")
                # OPEN: leave as-is
            except Exception:
                logger.exception("poll_pr_merges: %s/%s failed, retrying next cycle",
                                 name, event["fingerprint"])
    finally:
        conn.close()
```

Register it in `setup_scheduler` (after the existing three `add_job` calls):

```python
    scheduler.add_job(poll_pr_merges_job, IntervalTrigger(minutes=5), id="poll_pr_merges", args=[db_path])
```

Check the existing `add_job` calls: if they pass `id=` positionally rather than as kwarg, `test_poll_job_registered`'s kwarg lookup misses them — they use `id=` as kwarg (confirmed in current source), so the test is consistent.

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest tests/ -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add log-medic/app/scheduler.py log-medic/tests/test_scheduler.py
git commit -m "feat(log-medic): poll PR merge state every 5 min, deploy on merge"
```

---

### Task 6: Infra — Dockerfile docker CLI + compose plugin, `/stacks` mount, dashboard verdict column

**Files:**
- Modify: `log-medic/Dockerfile`
- Modify: `log-medic/docker-compose.yml`
- Modify: `log-medic/app/static/index.html:42`
- Modify: `log-medic/app/static/app.js:66`

**Interfaces:**
- Produces: `docker` + `docker compose` binaries in the image (used by `deployer.py`); `/stacks` bind mount of `/volume2/docker`; Events tab shows verdict.
- No unit tests — image/mount verified at on-NAS DoD (Task 7 checklist).

- [ ] **Step 1: Dockerfile — add docker CLI + compose plugin**

In `log-medic/Dockerfile`, extend the existing single `RUN` layer: after the `gh` install lines (`&& rm -f /tmp/gh.tar.gz \`) and before `&& rm -rf /var/lib/apt/lists/*`, insert:

```dockerfile
    && curl -fsSL -o /tmp/docker.tgz https://download.docker.com/linux/static/stable/x86_64/docker-27.3.1.tgz \
    && tar -xz -C /usr/local/bin --strip-components=1 -f /tmp/docker.tgz docker/docker \
    && rm -f /tmp/docker.tgz \
    && mkdir -p /usr/local/lib/docker/cli-plugins \
    && curl -fsSL -o /usr/local/lib/docker/cli-plugins/docker-compose \
       https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-x86_64 \
    && chmod +x /usr/local/lib/docker/cli-plugins/docker-compose \
```

(Static pinned binaries, same style as the pinned `gh` tarball. DS925+ is x86_64.)

- [ ] **Step 2: docker-compose.yml — add /stacks mount**

In `log-medic/docker-compose.yml`, `log-medic` service `volumes:` — add one line after the workspaces mount:

```yaml
      - /volume2/docker:/stacks
```

(rw, no `:ro` — deployer writes stack files. Socket mount stays `:ro`; socket write() still works through a read-only bind mount, proven by v1 docker-py usage.)

- [ ] **Step 3: Dashboard verdict column**

`log-medic/app/static/index.html` line 42 — add `<th>Verdict</th>` after `<th>Status</th>`:

```html
      <thead><tr><th>Time</th><th>Container</th><th>Fingerprint</th><th>Count</th><th>Status</th><th>Verdict</th><th>Gate reason</th></tr></thead>
```

`log-medic/app/static/app.js` line 66 — add the matching cell after the status cell:

```javascript
    tr.innerHTML = `<td>${e.last_seen}</td><td>${e.container}</td><td>${e.fingerprint}</td><td>${e.count}</td><td>${e.status}</td><td>${e.verdict ?? "-"}</td><td>${e.gate_reason ?? "-"}</td>`;
```

(`GET /api/events` already returns `dict(row)` — the new column flows through with no API change.)

- [ ] **Step 4: Sanity checks**

Run: `docker compose -f log-medic/docker-compose.yml config -q 2>/dev/null || python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml')); print('yaml ok')"`
Expected: no output (compose ok) or `yaml ok`.

Run: `python3 -m pytest tests/ -v`
Expected: all PASS (nothing here touches tested code).

- [ ] **Step 5: Commit**

```bash
git add log-medic/Dockerfile log-medic/docker-compose.yml log-medic/app/static/index.html log-medic/app/static/app.js
git commit -m "feat(log-medic): docker cli+compose in image, /stacks mount, verdict column"
```

---

### Task 7: Docs — README, .notes, root CLAUDE.md

**Files:**
- Modify: `log-medic/README.md`
- Modify: `log-medic/.notes/00_INDEX.md`
- Modify: `log-medic/.notes/daily_log.md`
- Modify: `CLAUDE.md` (root — stacks table, log-medic row)

**Interfaces:** none — documentation of Tasks 1–6.

- [ ] **Step 1: Update `log-medic/README.md`**

Add a "Close the loop" section describing: VERDICT triage (`code` → fix runner eligible, `infra` → notify only, fail-safe infra), `poll_pr_merges` every 5 min via `gh pr view`, auto deploy (workspace sync → tracked-file copy to `/stacks/<stack>` → `compose up -d --build` → 60 s verify → 🚀/❌ Telegram), `deploy_failed` terminal + manual revert-and-merge recovery, self-deploy guard for log-medic itself. Update the status-flow list to: `new → analyzed → pr_opened → merged → deployed | deploy_failed` (+ `pr_closed`, `gated`, `notified`).

- [ ] **Step 2: Update `log-medic/.notes/00_INDEX.md`**

- Modules section: add `app/deployer.py` (deploy pipeline + `copy_tracked_files`), note `analyzer.parse_verdict`, scheduler job `poll_pr_merges` (5 min), watcher verdict routing.
- Schema section: `events.verdict` column (additive ALTER migration in `init_db`).
- Gaps section: add "on-NAS DoD for close-the-loop pending: needs `/volume2/docker:/stacks` mount live + image rebuild (docker cli/compose added); self-deploy of log-medic remains manual by design."

- [ ] **Step 3: Append `log-medic/.notes/daily_log.md`**

Dated entry (2026-07-05) summarizing: spec + plan links, the three gaps closed, files touched, test count.

- [ ] **Step 4: Update root `CLAUDE.md` stacks table**

Extend the `log-medic/` row's gotchas cell: after "…never auto-merged)", append: "Analysis verdict (`code`/`infra`) gates the fix runner — infra never auto-fixed. Merged PRs polled via `gh` every 5 min → auto deploy: copy git-tracked files from workspace to `/stacks/<stack>` (`/volume2/docker` mount) + `compose up -d --build` + verify; `deploy_failed` is terminal (manual revert+merge to recover); log-medic self-deploy stays manual."

- [ ] **Step 5: Commit**

```bash
git add log-medic/README.md log-medic/.notes/00_INDEX.md log-medic/.notes/daily_log.md CLAUDE.md
git commit -m "docs(log-medic): close-the-loop — triage verdict, merge poll, auto deploy"
```

---

## On-NAS Definition of Done (manual, after deploy of log-medic itself)

Not a plan task — operator checklist, gates real use:

1. Deploy log-medic v2 from the workstation (`./scripts/deploy.sh`, restart log-medic stack) — image rebuild picks up docker cli/compose; verify `/stacks` mount appears in `docker inspect log-medic`.
2. `docker exec log-medic docker compose version` → prints compose v2.32.4.
3. Set a test container to `stable`, `ENABLE_FIX_RUNNER=true`; trigger a known code-verdict error → PR opens → merge it on GitHub → within 5 min: 🚀 Telegram, container restarted with new code, event `deployed`.
4. Trigger an infra-verdict error (e.g. unplug an upstream) → Telegram shows `🌐 infra`, no fix branch created.
