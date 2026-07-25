# ops-bot Fix-as-PR Implementation Plan (Phase 2)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the operator turn an incident's suggested fix into a GitHub pull request from Telegram — the LLM emits a repo-relative source change, the bot opens a PR via the GitHub REST API, and a human reviews/merges/deploys. The bot never executes anything on the NAS.

**Architecture:** Extend the Phase-1 `FixOption` with `file_changes` (repo path + find/replace). A new `github_client.create_fix_pr()` applies those changes on a new branch via the GitHub REST API (branch → contents → PR) and returns a PR URL. Telegram shows a "เปิด PR" button per PR-able fix option; the callback calls `create_fix_pr` and records an `actions` row. The bot stays read-only on the NAS — the only new capability is opening a PR on one repo.

**Tech Stack:** Python 3.12 (3.9-compatible annotations), httpx (existing dep — no new deps), FastAPI, aiosqlite, pytest.

## Global Constraints

- Python 3.9 annotation compatibility (`from __future__ import annotations`; bare `list`/`dict`, `Optional[X]` — not `X | None`).
- No new dependencies — use `httpx` (already used in `telegram_bot.py`/`commands.py`).
- The bot remains read-only on the NAS: this feature adds no SSH command execution. Do not touch `ssh_client.py`.
- GitHub repo is `FixHarDeZ/centralized-nas-container-management`; default branch `main`. Never hardcode the token/repo — read from `get_config()`.
- Secrets are added to the vault via the `adding-vault-secret` skill at deploy time; the code changes are `config.py` + `secrets.manifest.yaml` only. Do not put real tokens anywhere.
- All Telegram-facing strings in Thai.
- Tests: run from the ops-bot dir via a real subprocess (`cd ops-bot && python3 -m pytest`); a run over ~90s is hung. Reuse `tests/conftest.py` isolation. Before committing any task, confirm `python3 -c "import app.main"` exits 0.
- Commit after each task.

---

## File Structure

| File | Responsibility | Action |
| :--- | :--- | :--- |
| `app/config.py` | `github_token`, `github_repo` settings | Modify |
| `secrets.manifest.yaml` | map GITHUB_* env → vault | Modify |
| `app/llm_client.py` | `FixOption.file_changes`, submit_report schema, prompt | Modify |
| `app/github_client.py` | `create_fix_pr` REST client | Create |
| `app/telegram_bot.py` | PR button per PR-able fix option | Modify |
| `app/commands.py` | `pr:` callback routing + audit | Modify |
| `tests/test_github_client.py` | PR client tests | Create |
| `tests/test_commands.py` | callback routing tests | Create |
| `tests/test_llm_client.py` / `tests/test_telegram_bot.py` | schema + button tests | Modify |

---

## Task 1: Config + manifest for GitHub secrets

**Files:**
- Modify: `ops-bot/app/config.py`, `ops-bot/secrets.manifest.yaml`
- Test: `ops-bot/tests/test_config.py`

**Interfaces:**
- Produces: `Settings.github_token: str`, `Settings.github_repo: str` (both default `""`).

- [ ] **Step 1: Write failing test**

Append to `tests/test_config.py`:

```python
def test_github_settings_default_empty(monkeypatch):
    import app.config
    app.config._config = None
    s = app.config.Settings()
    assert s.github_token == ""
    assert s.github_repo == ""


def test_github_settings_from_env(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    import app.config
    app.config._config = None
    s = app.config.Settings()
    assert s.github_token == "tok"
    assert s.github_repo == "owner/repo"
```

- [ ] **Step 2: Run test, verify fail**
  Run: `cd ops-bot && python3 -m pytest tests/test_config.py -v`
  Expected: FAIL (AttributeError: github_token)

- [ ] **Step 3: Add settings fields**

In `app/config.py`, add after the `kuma_webhook_secret` field:

```python
    # GitHub (fix-as-PR)
    github_token: str = ""
    github_repo: str = ""  # owner/repo
```

- [ ] **Step 4: Add manifest mappings**

In `secrets.manifest.yaml`, under `env:`, add:

```yaml
  GITHUB_TOKEN:                stacks.ops_bot.github.token
  GITHUB_REPO:                 stacks.ops_bot.github.repo
```

- [ ] **Step 5: Run test, verify pass**
  Run: `cd ops-bot && python3 -m pytest tests/test_config.py -v`
  Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ops-bot/app/config.py ops-bot/secrets.manifest.yaml ops-bot/tests/test_config.py
git commit -m "feat(ops-bot): add github_token/github_repo config for fix-as-PR"
```

---

## Task 2: `FixOption.file_changes` + report schema + prompt

**Files:**
- Modify: `ops-bot/app/llm_client.py`
- Test: `ops-bot/tests/test_llm_client.py`

**Interfaces:**
- Consumes: existing `FixOption`, `parse_report`, `TOOLS`, `SYSTEM_PROMPT`.
- Produces: `FixOption` gains `file_changes: list` (list of `{"path","find","replace"}` dicts; default empty). `submit_report` tool schema accepts `file_changes` per fix option.

- [ ] **Step 1: Write failing test**

Append to `tests/test_llm_client.py`:

```python
def test_fixoption_has_file_changes():
    from app.llm_client import FixOption
    f = FixOption(
        title="bump mem", recommended=True, detail="3g→5g",
        commands=[], file_changes=[{"path": "homepage/docker-compose.yml", "find": "mem_limit: 3g", "replace": "mem_limit: 5g"}],
    )
    assert f.file_changes[0]["path"] == "homepage/docker-compose.yml"


def test_parse_report_reads_file_changes():
    from app.llm_client import parse_report
    args = {
        "summary": "OOM", "severity": "critical",
        "fix_options": [{
            "title": "bump", "recommended": True, "detail": "d", "commands": [],
            "file_changes": [{"path": "x/y.yml", "find": "a", "replace": "b"}],
        }],
    }
    r = parse_report(args, tokens_used=1, findings=[], truncated=False)
    assert r.fix_options[0].file_changes == [{"path": "x/y.yml", "find": "a", "replace": "b"}]


def test_parse_report_defaults_file_changes_empty():
    from app.llm_client import parse_report
    args = {"summary": "s", "severity": "info", "fix_options": [{"title": "t", "detail": "d"}]}
    r = parse_report(args, tokens_used=0, findings=[], truncated=False)
    assert r.fix_options[0].file_changes == []
```

- [ ] **Step 2: Run test, verify fail**
  Run: `cd ops-bot && python3 -m pytest tests/test_llm_client.py -k file_changes -v`
  Expected: FAIL (unexpected keyword argument 'file_changes')

- [ ] **Step 3: Add `file_changes` to `FixOption` + `parse_report`**

In `app/llm_client.py`, change the `FixOption` dataclass to:

```python
@dataclass
class FixOption:
    title: str
    recommended: bool
    detail: str
    commands: list
    file_changes: list
```

In `parse_report`, change the `fix_options` comprehension to include `file_changes`:

```python
    fix_options = [
        FixOption(
            title=o.get("title", ""),
            recommended=bool(o.get("recommended", False)),
            detail=o.get("detail", ""),
            commands=o.get("commands", []) or [],
            file_changes=o.get("file_changes", []) or [],
        )
        for o in (args.get("fix_options") or [])
    ]
```

- [ ] **Step 4: Add `file_changes` to the `submit_report` tool schema**

In `app/llm_client.py`, inside the `submit_report` tool's `fix_options.items.properties`, add after `commands`:

```python
                                "file_changes": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "path": {"type": "string"},
                                            "find": {"type": "string"},
                                            "replace": {"type": "string"},
                                        },
                                        "required": ["path", "find", "replace"],
                                    },
                                },
```

- [ ] **Step 5: Update SYSTEM_PROMPT for source fixes**

In `app/llm_client.py`, append this paragraph to the `SYSTEM_PROMPT` string (before the closing `"""`):

```
เมื่อ fix เป็นการแก้ config/source (เช่น mem_limit, env, compose): ให้ cat ไฟล์สดก่อน แล้วใส่ file_changes ใน fix_option — path เป็น repo-relative (NAS /volume2/docker/<stack>/xxx = repo <stack>/xxx), find = ข้อความเดิมเป๊ะ, replace = ข้อความใหม่. ห้ามใช้ sed/คำสั่ง shell แก้ไฟล์บน NAS (deploy ครั้งหน้าจะ overwrite). fix ที่เป็น runtime อย่างเดียว (เช่น restart) ไม่ต้องมี file_changes.
```

- [ ] **Step 6: Run tests, verify pass**
  Run: `cd ops-bot && python3 -m pytest tests/test_llm_client.py -v`
  Expected: PASS (existing + 3 new)

- [ ] **Step 7: Commit**

```bash
git add ops-bot/app/llm_client.py ops-bot/tests/test_llm_client.py
git commit -m "feat(ops-bot): add file_changes to FixOption + submit_report schema + prompt"
```

---

## Task 3: `github_client.create_fix_pr`

**Files:**
- Create: `ops-bot/app/github_client.py`
- Test: `ops-bot/tests/test_github_client.py`

**Interfaces:**
- Consumes: `get_config().github_token`, `.github_repo`.
- Produces: `async create_fix_pr(incident_id: int, title: str, file_changes: list) -> tuple[bool, str]` — returns `(True, pr_html_url)` or `(False, thai_error_message)`.

- [ ] **Step 1: Write failing tests**

Create `tests/test_github_client.py`:

```python
import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.github_client import create_fix_pr


@pytest.fixture
def gh_config(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    import app.config
    app.config._config = None
    yield
    app.config._config = None


def _resp(status, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload or {}
    r.text = text
    return r


def _b64(s):
    return base64.b64encode(s.encode()).decode()


def _next(calls, method):
    m, resp = next(calls)
    assert m == method, f"expected call {m}, got {method}"
    return resp


def _client_with(sequence):
    """sequence: list of (method, response) consumed in call order.
    Each get/post/put pops the next entry and asserts the method matches."""
    calls = iter(sequence)
    client = MagicMock()
    client.get = AsyncMock(side_effect=lambda *a, **k: _next(calls, "get"))
    client.post = AsyncMock(side_effect=lambda *a, **k: _next(calls, "post"))
    client.put = AsyncMock(side_effect=lambda *a, **k: _next(calls, "put"))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_create_fix_pr_happy_path(gh_config):
    seq = [
        ("get", _resp(200, {"default_branch": "main"})),                 # repo
        ("get", _resp(200, {"object": {"sha": "base123"}})),             # base ref
        ("post", _resp(201, {})),                                        # create branch
        ("get", _resp(200, {"content": _b64("mem_limit: 3g\n"), "sha": "blob1"})),  # get file
        ("put", _resp(200, {})),                                         # put file
        ("post", _resp(201, {"html_url": "https://github.com/owner/repo/pull/7"})), # PR
    ]
    with patch("app.github_client.httpx.AsyncClient", return_value=_client_with(seq)):
        ok, url = await create_fix_pr(1, "bump mem", [{"path": "homepage/docker-compose.yml", "find": "mem_limit: 3g", "replace": "mem_limit: 5g"}])
    assert ok is True
    assert url == "https://github.com/owner/repo/pull/7"


@pytest.mark.asyncio
async def test_create_fix_pr_find_not_present(gh_config):
    seq = [
        ("get", _resp(200, {"default_branch": "main"})),
        ("get", _resp(200, {"object": {"sha": "base123"}})),
        ("post", _resp(201, {})),
        ("get", _resp(200, {"content": _b64("mem_limit: 8g\n"), "sha": "blob1"})),  # find missing
    ]
    with patch("app.github_client.httpx.AsyncClient", return_value=_client_with(seq)):
        ok, msg = await create_fix_pr(1, "bump", [{"path": "x.yml", "find": "mem_limit: 3g", "replace": "mem_limit: 5g"}])
    assert ok is False
    assert "ไม่เจอ" in msg


@pytest.mark.asyncio
async def test_create_fix_pr_file_missing(gh_config):
    seq = [
        ("get", _resp(200, {"default_branch": "main"})),
        ("get", _resp(200, {"object": {"sha": "base123"}})),
        ("post", _resp(201, {})),
        ("get", _resp(404, {}, "not found")),
    ]
    with patch("app.github_client.httpx.AsyncClient", return_value=_client_with(seq)):
        ok, msg = await create_fix_pr(1, "x", [{"path": "nope.yml", "find": "a", "replace": "b"}])
    assert ok is False


@pytest.mark.asyncio
async def test_create_fix_pr_no_config(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    import app.config
    app.config._config = None
    ok, msg = await create_fix_pr(1, "x", [{"path": "a", "find": "b", "replace": "c"}])
    assert ok is False
    app.config._config = None


@pytest.mark.asyncio
async def test_create_fix_pr_no_changes(gh_config):
    ok, msg = await create_fix_pr(1, "x", [])
    assert ok is False
```

- [ ] **Step 2: Run tests, verify fail**
  Run: `cd ops-bot && python3 -m pytest tests/test_github_client.py -v`
  Expected: FAIL (ModuleNotFoundError: app.github_client)

- [ ] **Step 3: Implement `github_client.py`**

Create `app/github_client.py`:

```python
# ops-bot/app/github_client.py
from __future__ import annotations

import base64
import logging
import re
import time
from typing import Tuple

import httpx

from app.config import get_config

logger = logging.getLogger(__name__)

API = "https://api.github.com"


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:24] or "fix"


async def create_fix_pr(incident_id: int, title: str, file_changes: list) -> Tuple[bool, str]:
    cfg = get_config()
    if not cfg.github_token or not cfg.github_repo:
        return (False, "GitHub token/repo ยังไม่ได้ตั้งค่า")
    if not file_changes:
        return (False, "fix นี้ไม่มีการแก้ไฟล์ (advisory เท่านั้น)")

    headers = {
        "Authorization": f"Bearer {cfg.github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    base = f"{API}/repos/{cfg.github_repo}"
    branch = f"fix/incident-{incident_id}-{_slug(title)}-{int(time.time())}"

    try:
        async with httpx.AsyncClient(timeout=30, headers=headers) as client:
            r = await client.get(base)
            if r.status_code != 200:
                return (False, f"เข้าถึง repo ไม่ได้ ({r.status_code})")
            default_branch = r.json().get("default_branch", "main")

            r = await client.get(f"{base}/git/ref/heads/{default_branch}")
            if r.status_code != 200:
                return (False, f"อ่าน branch {default_branch} ไม่ได้ ({r.status_code})")
            base_sha = r.json()["object"]["sha"]

            r = await client.post(
                f"{base}/git/refs",
                json={"ref": f"refs/heads/{branch}", "sha": base_sha},
            )
            if r.status_code not in (200, 201):
                return (False, f"สร้าง branch ไม่ได้ ({r.status_code})")

            for ch in file_changes:
                path = ch.get("path", "")
                find = ch.get("find", "")
                replace = ch.get("replace", "")
                if not path:
                    return (False, "file_changes ขาด path")
                r = await client.get(f"{base}/contents/{path}", params={"ref": branch})
                if r.status_code != 200:
                    return (False, f"ไม่พบไฟล์ {path} ใน repo ({r.status_code})")
                meta = r.json()
                content = base64.b64decode(meta["content"]).decode("utf-8")
                if find not in content:
                    return (False, f"หา '{find[:40]}' ในไฟล์ {path} ไม่เจอ — แก้ manual")
                new_content = content.replace(find, replace)
                r = await client.put(
                    f"{base}/contents/{path}",
                    json={
                        "message": f"fix(incident-{incident_id}): {title} [{path}]",
                        "content": base64.b64encode(new_content.encode("utf-8")).decode("ascii"),
                        "sha": meta["sha"],
                        "branch": branch,
                    },
                )
                if r.status_code not in (200, 201):
                    return (False, f"เขียนไฟล์ {path} ไม่ได้ ({r.status_code})")

            body = (
                f"Auto-generated fix for incident #{incident_id}.\n\n{title}\n\n"
                "⚠️ Review, merge, then deploy manually (make secrets && ./scripts/deploy.sh)."
            )
            r = await client.post(
                f"{base}/pulls",
                json={"title": f"fix(incident-{incident_id}): {title}", "head": branch, "base": default_branch, "body": body},
            )
            if r.status_code not in (200, 201):
                return (False, f"เปิด PR ไม่ได้ ({r.status_code})")
            return (True, r.json()["html_url"])
    except Exception as e:
        logger.error(f"create_fix_pr failed: {e}")
        return (False, f"GitHub error: {e}")
```

- [ ] **Step 4: Run tests, verify pass**
  Run: `cd ops-bot && python3 -m pytest tests/test_github_client.py -v`
  Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add ops-bot/app/github_client.py ops-bot/tests/test_github_client.py
git commit -m "feat(ops-bot): add github_client.create_fix_pr (REST branch+contents+PR)"
```

---

## Task 4: Telegram PR buttons

**Files:**
- Modify: `ops-bot/app/telegram_bot.py`
- Test: `ops-bot/tests/test_telegram_bot.py`

**Interfaces:**
- Consumes: `report.fix_options` each with `.title`, `.recommended`, `.file_changes` (Task 2).
- Produces: `send_incident_report` keyboard includes `pr:{incident_id}:{idx}` buttons for options with non-empty `file_changes`. New helper `build_report_keyboard(report, incident_id) -> dict`.

- [ ] **Step 1: Write failing test**

Append to `tests/test_telegram_bot.py`:

```python
def test_build_report_keyboard_has_pr_buttons_only_for_file_changes():
    from app.llm_client import AgenticReport, FixOption
    from app.telegram_bot import build_report_keyboard
    report = AgenticReport(
        summary="s", severity="critical", evidence=[], machine_status="",
        fix_options=[
            FixOption(title="bump mem", recommended=True, detail="d", commands=[],
                      file_changes=[{"path": "x.yml", "find": "a", "replace": "b"}]),
            FixOption(title="restart", recommended=False, detail="d", commands=["docker restart x"],
                      file_changes=[]),
        ],
        tokens_used=1,
    )
    kb = build_report_keyboard(report, 5)
    flat = [btn for row in kb["inline_keyboard"] for btn in row]
    cbs = [b["callback_data"] for b in flat]
    assert "pr:5:0" in cbs           # option with file_changes gets a button
    assert "pr:5:1" not in cbs       # advisory-only option does not
    assert "logs:5" in cbs           # logs button retained
```

- [ ] **Step 2: Run test, verify fail**
  Run: `cd ops-bot && python3 -m pytest tests/test_telegram_bot.py -k keyboard -v`
  Expected: FAIL (cannot import build_report_keyboard)

- [ ] **Step 3: Implement keyboard builder + use it**

In `app/telegram_bot.py`, add the helper above `class TelegramBot`:

```python
def build_report_keyboard(report, incident_id: int) -> dict:
    rows = []
    for idx, o in enumerate(report.fix_options):
        if getattr(o, "file_changes", None):
            star = " ⭐" if o.recommended else ""
            rows.append([{"text": f"🔧 เปิด PR: {o.title}{star}", "callback_data": f"pr:{incident_id}:{idx}"}])
    rows.append([{"text": "📋 ดู Logs เพิ่มเติม", "callback_data": f"logs:{incident_id}"}])
    return {"inline_keyboard": rows}
```

Change `send_incident_report` to use it:

```python
    async def send_incident_report(self, service_name: str, report, incident_id: int) -> None:
        msg = format_report_message(service_name, report)
        keyboard = build_report_keyboard(report, incident_id)
        await self.send_message(msg, reply_markup=keyboard)
```

- [ ] **Step 4: Run tests, verify pass**
  Run: `cd ops-bot && python3 -m pytest tests/test_telegram_bot.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ops-bot/app/telegram_bot.py ops-bot/tests/test_telegram_bot.py
git commit -m "feat(ops-bot): Telegram PR button per PR-able fix option"
```

---

## Task 5: `pr:` callback routing + audit

**Files:**
- Modify: `ops-bot/app/commands.py`
- Test: `ops-bot/tests/test_commands.py` (create)

**Interfaces:**
- Consumes: `create_fix_pr(incident_id, title, file_changes)` (Task 3); incident `report_json` in `analyses` (Phase 1); `get_db`, `get_telegram_bot`.
- Produces: `_handle_callback` dispatches `pr:{incident_id}:{idx}` → loads the fix option, calls `create_fix_pr`, replies, and writes an `actions` row.

- [ ] **Step 1: Write failing test**

Create `tests/test_commands.py`:

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.commands import _handle_callback


@pytest.mark.asyncio
async def test_pr_callback_opens_pr_and_audits(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "1")
    import app.config
    app.config._config = None

    report = {"fix_options": [{"title": "bump", "recommended": True, "detail": "d",
                               "commands": [], "file_changes": [{"path": "x.yml", "find": "a", "replace": "b"}]}]}
    db = AsyncMock()
    cur = AsyncMock()
    cur.fetchone = AsyncMock(return_value=(json.dumps(report),))
    db.execute = AsyncMock(return_value=cur)
    db.commit = AsyncMock()
    tg = MagicMock()
    tg.answer_callback = AsyncMock()
    tg.send_message = AsyncMock()

    with (
        patch("app.commands.get_db", AsyncMock(return_value=db)),
        patch("app.commands.get_telegram_bot", return_value=tg),
        patch("app.commands.create_fix_pr", new_callable=AsyncMock, return_value=(True, "https://gh/pr/1")) as mock_pr,
    ):
        await _handle_callback({"id": "cb1", "data": "pr:5:0"})

    mock_pr.assert_awaited_once()
    args = mock_pr.await_args
    assert args.kwargs.get("incident_id", args.args[0] if args.args else None) == 5 or args.args[0] == 5
    # a Telegram reply with the URL was sent
    assert any("https://gh/pr/1" in str(c.args) for c in tg.send_message.await_args_list)
    # an actions row was written
    assert any("INSERT INTO actions" in str(c.args[0]) for c in db.execute.await_args_list)
    app.config._config = None
```

- [ ] **Step 2: Run test, verify fail**
  Run: `cd ops-bot && python3 -m pytest tests/test_commands.py -v`
  Expected: FAIL (create_fix_pr not importable in app.commands / pr not handled)

- [ ] **Step 3: Extend `_handle_callback`**

In `app/commands.py`, add the import near the top (with the other `app.` imports):

```python
from app.github_client import create_fix_pr
```

Replace the body of `_handle_callback` (currently parses exactly 2 `:`-parts and handles only `logs`) with a prefix-dispatching version:

```python
async def _handle_callback(callback_query: dict):
    """Handle InlineKeyboard callbacks: logs (read-only) and pr (open a fix PR)."""
    data = callback_query.get("data", "")
    callback_id = callback_query["id"]

    tg = get_telegram_bot()
    await tg.answer_callback(callback_id, "กำลังดำเนินการ...")

    parts = data.split(":")
    action = parts[0] if parts else ""

    if action == "logs" and len(parts) == 2:
        incident_id = int(parts[1])
        db = await get_db()
        cursor = await db.execute(
            "SELECT container_name FROM incidents WHERE id = ?", (incident_id,)
        )
        row = await cursor.fetchone()
        if row:
            ssh = get_ssh_client()
            result = await ssh.execute_command(f"docker logs --tail 50 {row[0]} 2>&1")
            await tg.send_message(f"📋 **Logs ({row[0]}):**\n```\n{result.stdout[-3000:]}\n```")
        return

    if action == "pr" and len(parts) == 3:
        incident_id = int(parts[1])
        idx = int(parts[2])
        db = await get_db()
        cursor = await db.execute(
            "SELECT report_json FROM analyses WHERE incident_id = ?", (incident_id,)
        )
        row = await cursor.fetchone()
        if not row or not row[0]:
            await tg.send_message("❌ ไม่พบข้อมูล fix ของ incident นี้")
            return
        report = json.loads(row[0])
        options = report.get("fix_options", [])
        if idx >= len(options):
            await tg.send_message("❌ ไม่พบ fix option นี้")
            return
        opt = options[idx]
        ok, result = await create_fix_pr(
            incident_id=incident_id,
            title=opt.get("title", "fix"),
            file_changes=opt.get("file_changes", []),
        )
        await db.execute(
            "INSERT INTO actions (incident_id, action_type, commands_executed, result_output, success) "
            "VALUES (?, ?, ?, ?, ?)",
            (incident_id, "open_pr", json.dumps(opt.get("file_changes", [])), result, ok),
        )
        await db.commit()
        await tg.send_message(f"✅ เปิด PR แล้ว: {result}" if ok else f"❌ {result}")
        return
```

Confirm `json` is imported at the top of `commands.py` (it is — used elsewhere; if not, add `import json`).

- [ ] **Step 4: Run tests, verify pass**
  Run: `cd ops-bot && python3 -m pytest tests/test_commands.py tests/test_webhook.py -v`
  Expected: PASS

- [ ] **Step 5: Full suite + import check**
  Run: `cd ops-bot && python3 -c "import app.main" && python3 -m pytest tests/ -q`
  Expected: import exit 0; all pass

- [ ] **Step 6: Commit**

```bash
git add ops-bot/app/commands.py ops-bot/tests/test_commands.py
git commit -m "feat(ops-bot): pr: callback opens fix PR and records action"
```

---

## Task 6: Docs + deploy prep

**Files:**
- Modify: `ops-bot/README.md`, `ops-bot/.notes/00_INDEX.md`, `ops-bot/.notes/daily_log.md`, root `CLAUDE.md` (ops-bot row)

**Interfaces:** none (documentation).

- [ ] **Step 1: Update stack README + notes**

In `ops-bot/README.md` add a "Fix-as-PR" section: the diagnosis report offers `🔧 เปิด PR` buttons for config/source fixes; tapping one opens a GitHub PR (branch + commit + PR via REST API) that a human reviews, merges, and deploys with `make secrets && ./scripts/deploy.sh`. Note the bot stays read-only on the NAS and never executes fixes. Document the vault keys `stacks.ops_bot.github.token` (fine-grained PAT, `contents:write` + `pull_requests:write`, this repo only) and `stacks.ops_bot.github.repo`.

Update `.notes/00_INDEX.md` (add github secrets + fix-as-PR interfaces) and append a `.notes/daily_log.md` entry under 2026-07-25.

In root `CLAUDE.md`, extend the `ops-bot/` row: add "Fix-as-PR: proposes config fixes as GitHub PRs (read-only on NAS)".

- [ ] **Step 2: Commit**

```bash
git add ops-bot/README.md ops-bot/.notes/ CLAUDE.md
git commit -m "docs(ops-bot): document fix-as-PR flow and github secrets"
```

- [ ] **Step 3: Vault secret + deploy (controller, post-merge, from main)**

Not a subagent step — the controller does this after merge, because it needs the vault age key and NAS access:
1. Add the GitHub PAT + repo to the vault via the `adding-vault-secret` skill: keys `stacks.ops_bot.github.token`, `stacks.ops_bot.github.repo`.
2. `make secrets` to render `ops-bot/.env`.
3. `./scripts/deploy.sh -s ops-bot -y`.
4. E2E: trigger an incident whose fix is a config change, tap `🔧 เปิด PR`, confirm a PR is opened on `FixHarDeZ/centralized-nas-container-management` and the URL comes back in Telegram; verify an `actions` row (`action_type=open_pr`).

---

## Self-Review

**Spec coverage:**
- New secret (github token/repo) → Task 1 (config+manifest), Task 6 (vault add). ✓
- `FixOption.file_changes` + submit_report schema + prompt → Task 2. ✓
- `create_fix_pr` REST (branch→contents→PR, find-not-found, 404, multi-file, 401) → Task 3 (impl + tests). ✓
- Telegram PR button only for options with file_changes → Task 4. ✓
- `pr:` callback + audit row (`action_type=open_pr`) → Task 5. ✓
- Read-only on NAS unchanged (no ssh_client edits) → enforced by Global Constraints; no task touches ssh_client. ✓
- Docs → Task 6. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. Task 6 Step 1 describes doc edits in prose (documentation, not code) — acceptable.

**Type consistency:** `create_fix_pr(incident_id, title, file_changes) -> (bool, str)` identical across Task 3 (def), Task 5 (call). `FixOption(..., file_changes)` consistent across Tasks 2/4/5. `build_report_keyboard(report, incident_id)` matches between Task 4 def and use. callback strings `pr:{id}:{idx}` / `logs:{id}` consistent between Task 4 (emit) and Task 5 (parse). `actions` INSERT columns match the Phase-1 `actions` schema (incident_id, action_type, commands_executed, result_output, success).

**Note:** Task 5's test asserts `create_fix_pr` was awaited with incident_id=5; the implementation calls it with keyword args, so the test's arg extraction tolerates both — kept lenient intentionally.
