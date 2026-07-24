# ops-bot Agentic Diagnosis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace ops-bot's fixed-script diagnosis with an agentic tool-use loop where mimo iteratively picks read-only diagnostic commands, narrates key findings live to Telegram, and returns a structured multi-section report.

**Architecture:** `LLMClient.diagnose_agentic()` runs the loop over mimo native function-calling with three tools (`run_diagnostic`, `note_finding`, `submit_report`). The orchestrator injects two async callbacks — `execute(cmd)` (SSH + persist a diagnostics row) and `narrate(text)` (Telegram) — keeping the LLM client decoupled from SSH/DB/Telegram. The structured report is stored as `report_json` and rendered on Telegram and the dashboard. Read-only is enforced by the existing SSH whitelist, which every `run_diagnostic` routes through.

**Tech Stack:** Python 3.12, OpenAI SDK (AsyncOpenAI → mimo), FastAPI, aiosqlite, Jinja2, pytest.

## Global Constraints

- Python 3.9 compatibility for type annotations (`from __future__ import annotations` or `Optional[X]`, not `X | None`) — the codebase targets it.
- mimo model/base/key from `get_config()`; never hardcode.
- Read-only only: no new command reaches SSH outside the existing `ALLOWED_PREFIXES` whitelist in `app/ssh_client.py`. No fix execution (Phase 2).
- Iteration cap: **10**.
- All user-facing strings in Thai.
- Tests use existing `tests/conftest.py` isolation (env + aiosqlite cleanup). Run with `cd ops-bot && python3 -m pytest`.
- Commit after each task.

---

## File Structure

| File | Responsibility | Action |
| :--- | :--- | :--- |
| `app/llm_client.py` | Agent loop, tool schemas, report dataclasses, parsing | Modify (replace `analyze_diagnostic`/`LLMAnalysis`/`SYSTEM_PROMPT`) |
| `app/orchestrator.py` | Wire callbacks, persist diagnostics + report_json, send report | Modify |
| `app/db.py` | Add `report_json` column | Modify |
| `app/telegram_bot.py` | Structured-report formatter | Modify |
| `app/dashboard.py` + `templates/incident_detail.html` | Render report_json | Modify |
| `app/diagnostics.py` | Fixed diagnostic script | Delete (fully replaced) |
| `tests/test_llm_client.py` | Agent-loop tests | Rewrite |
| `tests/test_orchestrator.py` | Pipeline test with new interface | Modify |
| `tests/test_diagnostics.py` | Tests for deleted module | Delete |

---

## Task 1: DB schema — `report_json` column

**Files:**
- Modify: `ops-bot/app/db.py` (analyses table in `SCHEMA`)
- Test: `ops-bot/tests/test_db.py`

**Interfaces:**
- Produces: `analyses` table gains `report_json TEXT` column.

- [ ] **Step 1: Write failing test**

```python
# append to tests/test_db.py
import pytest

@pytest.mark.asyncio
async def test_analyses_has_report_json_column(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "t.db"))
    import app.config, app.db
    app.config._config = None
    app.db._db = None
    await app.db.init_db()
    db = await app.db.get_db()
    cols = [r[1] for r in await (await db.execute("PRAGMA table_info(analyses)")).fetchall()]
    assert "report_json" in cols
```

- [ ] **Step 2: Run test, verify fails**
  Run: `cd ops-bot && python3 -m pytest tests/test_db.py::test_analyses_has_report_json_column -v`
  Expected: FAIL (no such column `report_json`)

- [ ] **Step 3: Add column to schema**

In `app/db.py`, inside the `analyses` `CREATE TABLE`, add `report_json` after `fix_commands`:

```sql
CREATE TABLE IF NOT EXISTS analyses (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id INTEGER REFERENCES incidents(id),
    root_cause TEXT,
    severity TEXT,
    suggested_fix TEXT,
    fix_commands TEXT,
    report_json TEXT,
    llm_tokens_used INTEGER,
    created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
);
```

- [ ] **Step 4: Run test, verify passes**
  Run: `cd ops-bot && python3 -m pytest tests/test_db.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ops-bot/app/db.py ops-bot/tests/test_db.py
git commit -m "feat(ops-bot): add report_json column to analyses table"
```

---

## Task 2: Report dataclasses + tool schemas + parser

**Files:**
- Modify: `ops-bot/app/llm_client.py`
- Test: `ops-bot/tests/test_llm_client.py` (rewrite)

**Interfaces:**
- Produces:
  - `FixOption(title: str, recommended: bool, detail: str, commands: list[str])` dataclass.
  - `AgenticReport(summary: str, severity: str, evidence: list[dict], machine_status: str, fix_options: list[FixOption], tokens_used: int, findings: list[str], truncated: bool)` dataclass.
  - `TOOLS: list[dict]` — OpenAI tool schemas for `run_diagnostic`, `note_finding`, `submit_report`.
  - `parse_report(args: dict, *, tokens_used: int, findings: list[str], truncated: bool) -> AgenticReport`.

- [ ] **Step 1: Replace the test file header + add report tests**

Rewrite `tests/test_llm_client.py` to start with:

```python
# ops-bot/tests/test_llm_client.py
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.llm_client import (
    AgenticReport, FixOption, TOOLS, parse_report, LLMClient,
)


def test_fixoption_dataclass():
    f = FixOption(title="เพิ่ม mem_limit", recommended=True, detail="แก้ compose", commands=["docker compose up -d"])
    assert f.recommended is True
    assert f.commands == ["docker compose up -d"]


def test_tools_expose_three_functions():
    names = {t["function"]["name"] for t in TOOLS}
    assert names == {"run_diagnostic", "note_finding", "submit_report"}


def test_parse_report_full():
    args = {
        "summary": "OOM Kill",
        "severity": "critical",
        "evidence": [{"factor": "OOMKilled", "value": "true"}],
        "machine_status": "เครื่องปกติ",
        "fix_options": [
            {"title": "เพิ่ม mem_limit", "recommended": True, "detail": "3g→5g", "commands": ["docker compose up -d"]}
        ],
    }
    r = parse_report(args, tokens_used=1200, findings=["เจอ restart-loop"], truncated=False)
    assert r.summary == "OOM Kill"
    assert r.severity == "critical"
    assert r.evidence[0]["factor"] == "OOMKilled"
    assert r.fix_options[0].recommended is True
    assert r.tokens_used == 1200
    assert r.findings == ["เจอ restart-loop"]
    assert r.truncated is False


def test_parse_report_missing_fields_falls_back():
    r = parse_report({"summary": "x"}, tokens_used=0, findings=[], truncated=True)
    assert r.severity == "warning"
    assert r.evidence == []
    assert r.fix_options == []
    assert r.truncated is True
```

- [ ] **Step 2: Run tests, verify fail**
  Run: `cd ops-bot && python3 -m pytest tests/test_llm_client.py -v`
  Expected: FAIL (ImportError: cannot import AgenticReport)

- [ ] **Step 3: Replace `llm_client.py` top section** (imports, SYSTEM_PROMPT, dataclasses, TOOLS, parse_report)

Replace lines 1–52 (through the `LLMAnalysis` dataclass) of `app/llm_client.py` with:

```python
# ops-bot/app/llm_client.py
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Optional

from openai import AsyncOpenAI

from app.config import get_config

logger = logging.getLogger(__name__)

MAX_ITERS = 10

SYSTEM_PROMPT = """คุณเป็น AI ops engineer เชี่ยวชาญ Docker diagnostics บน Synology NAS

โหมด READ-ONLY เท่านั้น — ห้าม restart/แก้ config/ลบ. วินิจฉัยด้วยการเรียก tool:

- run_diagnostic(cmd): รันคำสั่ง read-only (docker ps/inspect/logs, df, free, uptime, curl ฯลฯ). ระบบมี whitelist กัน — ถ้าคำสั่งถูก block ให้เปลี่ยนไปใช้คำสั่งอื่น
- note_finding(text): เมื่อเจอเบาะแสสำคัญ ให้เรียกด้วยข้อความไทยสั้นๆ ก่อนตรวจต่อ (เช่น "เจอแล้ว — restart-loop exit 137")
- submit_report(...): เมื่อวินิจฉัยเสร็จ เรียกครั้งเดียวเพื่อส่งรายงานสรุป

ขั้นตอน: ดู container ที่เกี่ยวข้อง → ดู log/inspect หาสาเหตุ → เช็คทรัพยากรเครื่อง → สรุป.
fix_options เป็นข้อเสนอเท่านั้น (ผู้ใช้ต้อง confirm เอง). ทุกข้อความเป็นภาษาไทย."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_diagnostic",
            "description": "รันคำสั่ง diagnostic แบบ read-only บน NAS ผ่าน SSH",
            "parameters": {
                "type": "object",
                "properties": {"cmd": {"type": "string", "description": "คำสั่ง shell read-only"}},
                "required": ["cmd"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "note_finding",
            "description": "แจ้งเบาะแสสำคัญที่เจอ ให้ผู้ใช้เห็นแบบ real-time",
            "parameters": {
                "type": "object",
                "properties": {"text": {"type": "string", "description": "ข้อความไทยสั้นๆ"}},
                "required": ["text"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "submit_report",
            "description": "ส่งรายงานวินิจฉัยฉบับสมบูรณ์ (เรียกครั้งเดียวตอนจบ)",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"factor": {"type": "string"}, "value": {"type": "string"}},
                            "required": ["factor", "value"],
                        },
                    },
                    "machine_status": {"type": "string"},
                    "fix_options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "recommended": {"type": "boolean"},
                                "detail": {"type": "string"},
                                "commands": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["title", "detail"],
                        },
                    },
                },
                "required": ["summary", "severity"],
            },
        },
    },
]


@dataclass
class FixOption:
    title: str
    recommended: bool
    detail: str
    commands: list


@dataclass
class AgenticReport:
    summary: str
    severity: str
    evidence: list
    machine_status: str
    fix_options: list
    tokens_used: int
    findings: list = field(default_factory=list)
    truncated: bool = False


def parse_report(args: dict, *, tokens_used: int, findings: list, truncated: bool) -> AgenticReport:
    fix_options = [
        FixOption(
            title=o.get("title", ""),
            recommended=bool(o.get("recommended", False)),
            detail=o.get("detail", ""),
            commands=o.get("commands", []) or [],
        )
        for o in (args.get("fix_options") or [])
    ]
    return AgenticReport(
        summary=args.get("summary", ""),
        severity=args.get("severity", "warning"),
        evidence=args.get("evidence") or [],
        machine_status=args.get("machine_status", ""),
        fix_options=fix_options,
        tokens_used=tokens_used,
        findings=findings,
        truncated=truncated,
    )


# transitional: telegram_bot.py still imports this until Task 5 removes it.
# Keeping it keeps the module import chain intact between tasks. Delete in Task 5.
@dataclass
class LLMAnalysis:
    root_cause: str
    severity: str
    suggested_fix: str
    fix_commands: list
    safety_note: str
    tokens_used: int
```

**Keep the transitional `LLMAnalysis` dataclass** shown above — `telegram_bot.py` imports it at module level and would break the whole import chain if removed now. It is deleted in Task 5. Delete the old `analyze_diagnostic` method and the old `SYSTEM_PROMPT` (removed by the replacement above and Task 3). Keep `LLMClient.__init__`, `get_llm_client`, and the `_llm_client` singleton — Task 3 fills the `LLMClient` body.

Do NOT delete the old `test_analyze_diagnostic_returns_analysis` / `test_llm_analysis_dataclass` tests by hand — the Step 1 rewrite of `tests/test_llm_client.py` already replaces the whole file, so they are gone. Confirm after Step 3 that the app still imports:
`cd ops-bot && python3 -c "import app.main"` → must print nothing and exit 0.

- [ ] **Step 4: Run tests, verify pass**
  Run: `cd ops-bot && python3 -m pytest tests/test_llm_client.py -v`
  Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add ops-bot/app/llm_client.py ops-bot/tests/test_llm_client.py
git commit -m "feat(ops-bot): add agentic report dataclasses, tool schemas, parser"
```

---

## Task 3: `diagnose_agentic()` loop

**Files:**
- Modify: `ops-bot/app/llm_client.py` (`LLMClient` body)
- Test: `ops-bot/tests/test_llm_client.py` (append)

**Interfaces:**
- Consumes: `TOOLS`, `parse_report`, `AgenticReport` (Task 2).
- Produces:
  - `LLMClient.diagnose_agentic(service_name: str, container_name: str, alert_message: str, *, execute: Callable[[str], Awaitable[str]], narrate: Callable[[str], Awaitable[None]]) -> AgenticReport`
  - `execute(cmd)` returns the command's text output; `narrate(text)` is fire-and-forget.

- [ ] **Step 1: Write failing tests**

Append to `tests/test_llm_client.py`:

```python
def _mk_toolcall(call_id, name, args):
    fn = MagicMock()
    fn.name = name
    fn.arguments = json.dumps(args)
    tc = MagicMock()
    tc.id = call_id
    tc.function = fn
    return tc


def _mk_response(tool_calls, tokens=100):
    msg = MagicMock()
    msg.content = ""
    msg.tool_calls = tool_calls
    return type("R", (), {
        "choices": [type("C", (), {"message": msg})()],
        "usage": type("U", (), {"total_tokens": tokens})(),
    })()


@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "k")
    monkeypatch.setenv("MIMO_BASE_URL", "https://x/v1")
    import app.config
    app.config._config = None
    yield
    app.config._config = None


@pytest.mark.asyncio
async def test_diagnose_agentic_happy_path(mock_config):
    responses = [
        _mk_response([_mk_toolcall("1", "run_diagnostic", {"cmd": "docker ps -a"})]),
        _mk_response([_mk_toolcall("2", "note_finding", {"text": "เจอ restart-loop"})]),
        _mk_response([_mk_toolcall("3", "submit_report", {
            "summary": "OOM", "severity": "critical",
            "evidence": [{"factor": "OOMKilled", "value": "true"}],
            "machine_status": "ปกติ",
            "fix_options": [{"title": "เพิ่ม mem", "recommended": True, "detail": "3g→5g", "commands": ["c"]}],
        })]),
    ]
    executed, narrated = [], []
    async def execute(cmd): executed.append(cmd); return "output"
    async def narrate(text): narrated.append(text)

    with patch("app.llm_client.AsyncOpenAI") as MockClient:
        MockClient.return_value.chat.completions.create = AsyncMock(side_effect=responses)
        client = LLMClient()
        report = await client.diagnose_agentic("Outline", "outline", "down", execute=execute, narrate=narrate)

    assert executed == ["docker ps -a"]
    assert narrated == ["เจอ restart-loop"]
    assert report.summary == "OOM"
    assert report.severity == "critical"
    assert report.tokens_used == 300


@pytest.mark.asyncio
async def test_diagnose_agentic_cap_returns_truncated(mock_config):
    # never emits submit_report
    loop_resp = _mk_response([_mk_toolcall("x", "run_diagnostic", {"cmd": "docker ps"})])
    async def execute(cmd): return "out"
    async def narrate(text): pass

    with patch("app.llm_client.AsyncOpenAI") as MockClient:
        MockClient.return_value.chat.completions.create = AsyncMock(return_value=loop_resp)
        client = LLMClient()
        report = await client.diagnose_agentic("S", "c", "down", execute=execute, narrate=narrate)

    assert report.truncated is True
    assert report.severity == "warning"


@pytest.mark.asyncio
async def test_diagnose_agentic_mimo_error_returns_fallback(mock_config):
    async def execute(cmd): return "out"
    async def narrate(text): pass
    with patch("app.llm_client.AsyncOpenAI") as MockClient:
        MockClient.return_value.chat.completions.create = AsyncMock(side_effect=RuntimeError("boom"))
        client = LLMClient()
        report = await client.diagnose_agentic("S", "c", "down", execute=execute, narrate=narrate)
    assert report.truncated is True
    assert "boom" in report.summary or report.summary != ""
```

- [ ] **Step 2: Run tests, verify fail**
  Run: `cd ops-bot && python3 -m pytest tests/test_llm_client.py -k diagnose_agentic -v`
  Expected: FAIL (no attribute `diagnose_agentic`)

- [ ] **Step 3: Implement `LLMClient` body**

Replace the `LLMClient` class body in `app/llm_client.py` with:

```python
class LLMClient:
    def __init__(self):
        cfg = get_config()
        self.client = AsyncOpenAI(api_key=cfg.mimo_api_key, base_url=cfg.mimo_base_url)
        self.model = cfg.mimo_model

    async def diagnose_agentic(
        self,
        service_name: str,
        container_name: str,
        alert_message: str,
        *,
        execute: Callable[[str], Awaitable[str]],
        narrate: Callable[[str], Awaitable[None]],
    ) -> AgenticReport:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"บริการ: {service_name}\ncontainer: {container_name}\n"
                f"alert: {alert_message}\n\nช่วยวินิจฉัยสาเหตุที่ล่ม"
            )},
        ]
        tokens = 0
        findings: list = []

        try:
            for _ in range(MAX_ITERS):
                resp = await self.client.chat.completions.create(
                    model=self.model, messages=messages, tools=TOOLS,
                    tool_choice="auto", temperature=0.1, max_tokens=1200,
                )
                tokens += resp.usage.total_tokens if resp.usage else 0
                msg = resp.choices[0].message
                tool_calls = msg.tool_calls or []

                if not tool_calls:
                    # model answered without a tool — nudge it to use tools
                    messages.append({"role": "assistant", "content": msg.content or ""})
                    messages.append({"role": "user", "content": "กรุณาใช้ tool submit_report เมื่อวินิจฉัยเสร็จ"})
                    continue

                messages.append({
                    "role": "assistant",
                    "content": msg.content or "",
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                        for tc in tool_calls
                    ],
                })

                for tc in tool_calls:
                    name = tc.function.name
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except json.JSONDecodeError:
                        args = {}

                    if name == "submit_report":
                        return parse_report(args, tokens_used=tokens, findings=findings, truncated=False)

                    if name == "run_diagnostic":
                        out = await execute(args.get("cmd", ""))
                        result = out
                    elif name == "note_finding":
                        text = args.get("text", "")
                        findings.append(text)
                        await narrate(text)
                        result = "ok"
                    else:
                        result = f"unknown tool: {name}"

                    messages.append({
                        "role": "tool", "tool_call_id": tc.id, "content": result[:4000],
                    })

            # cap reached without submit_report
            return AgenticReport(
                summary="วิเคราะห์ไม่ครบ — ถึงเพดานรอบการตรวจ",
                severity="warning", evidence=[], machine_status="",
                fix_options=[], tokens_used=tokens, findings=findings, truncated=True,
            )
        except Exception as e:
            logger.error(f"diagnose_agentic failed: {e}")
            return AgenticReport(
                summary=f"วิเคราะห์ไม่ได้: {e}",
                severity="warning", evidence=[], machine_status="",
                fix_options=[], tokens_used=tokens, findings=findings, truncated=True,
            )
```

- [ ] **Step 4: Run tests, verify pass**
  Run: `cd ops-bot && python3 -m pytest tests/test_llm_client.py -v`
  Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add ops-bot/app/llm_client.py ops-bot/tests/test_llm_client.py
git commit -m "feat(ops-bot): add agentic diagnosis tool-use loop"
```

---

## Task 4: Orchestrator wiring

**Files:**
- Modify: `ops-bot/app/orchestrator.py`
- Test: `ops-bot/tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `get_llm_client().diagnose_agentic(...)` (Task 3), `AgenticReport`.
- Produces: `handle_incident(service_name, container_name, status, alert_message) -> int` (unchanged signature). Internally builds `execute`/`narrate` callbacks; persists a `diagnostics` row per command; stores `report_json` + back-compat columns; sends the report via `telegram_bot.send_incident_report(service_name, report, incident_id)` (Task 5 signature).

- [ ] **Step 1: Update the pipeline test**

Replace `test_handle_incident_runs_full_pipeline` in `tests/test_orchestrator.py` with:

```python
@pytest.mark.asyncio
async def test_handle_incident_runs_agentic_pipeline():
    from app.llm_client import AgenticReport, FixOption
    report = AgenticReport(
        summary="OOM", severity="critical", evidence=[{"factor": "OOMKilled", "value": "true"}],
        machine_status="ปกติ",
        fix_options=[FixOption(title="เพิ่ม mem", recommended=True, detail="3g→5g", commands=["c"])],
        tokens_used=300, findings=["เจอ restart-loop"], truncated=False,
    )

    mock_db_instance = AsyncMock()
    mock_cursor = AsyncMock()
    mock_cursor.lastrowid = 1
    mock_db_instance.execute = AsyncMock(return_value=mock_cursor)
    mock_db_instance.commit = AsyncMock()

    async def fake_diagnose(service_name, container_name, alert_message, *, execute, narrate):
        # exercise the injected callbacks
        await execute("docker ps -a")
        await narrate("เจอ restart-loop")
        return report

    with (
        patch("app.orchestrator.is_watchtower_update", new_callable=AsyncMock, return_value=False),
        patch("app.orchestrator.get_llm_client") as mock_llm,
        patch("app.orchestrator.get_telegram_bot") as mock_tg,
        patch("app.orchestrator.get_ssh_client") as mock_ssh,
        patch("app.orchestrator.get_db", return_value=mock_db_instance),
    ):
        mock_llm.return_value = type("C", (), {"diagnose_agentic": AsyncMock(side_effect=fake_diagnose)})()
        send_report = AsyncMock()
        send_msg = AsyncMock()
        mock_tg.return_value = type("T", (), {"send_incident_report": send_report, "send_message": send_msg})()
        ssh_result = type("R", (), {"stdout": "out", "stderr": "", "exit_code": 0})()
        mock_ssh.return_value = type("S", (), {"execute_command": AsyncMock(return_value=ssh_result)})()

        result = await handle_incident("Outline", "outline", "down", "down alert")

        assert result == 1
        send_report.assert_called_once()
        # report_json persisted: some execute call includes an INSERT into analyses with report_json
        inserts = [c.args[0] for c in mock_db_instance.execute.call_args_list]
        assert any("report_json" in q for q in inserts)
```

- [ ] **Step 2: Run test, verify fails**
  Run: `cd ops-bot && python3 -m pytest tests/test_orchestrator.py -v`
  Expected: FAIL (orchestrator still calls `run_diagnostics`)

- [ ] **Step 3: Rewrite `handle_incident`**

Replace the body of `handle_incident` in `app/orchestrator.py` (keep the incident-insert and watchtower-skip blocks) so the diagnostics/analysis/report section reads:

```python
import json
import logging

from app.db import get_db
from app.llm_client import get_llm_client
from app.ssh_client import get_ssh_client
from app.telegram_bot import get_telegram_bot
from app.watchtower import is_watchtower_update

logger = logging.getLogger(__name__)


async def handle_incident(service_name, container_name, status, alert_message):
    db = await get_db()
    cursor = await db.execute(
        "INSERT INTO incidents (service_name, container_name, status, alert_message) VALUES (?, ?, ?, ?)",
        (service_name, container_name, status, alert_message),
    )
    incident_id = cursor.lastrowid
    await db.commit()

    if await is_watchtower_update(container_name):
        await db.execute("UPDATE incidents SET is_watchtower_update = TRUE WHERE id = ?", (incident_id,))
        await db.commit()
        logger.info(f"Incident {incident_id}: watchtower update, skipping")
        return incident_id

    ssh = get_ssh_client()
    tg = get_telegram_bot()
    await tg.send_message(f"🔧 กำลังตรวจสอบ {service_name} แบบ read-only...")

    async def execute(cmd: str) -> str:
        res = await ssh.execute_command(cmd)
        output = res.stdout
        if res.stderr:
            output += f"\n[stderr] {res.stderr}"
        await db.execute(
            "INSERT INTO diagnostics (incident_id, step_name, raw_output) VALUES (?, ?, ?)",
            (incident_id, cmd, f"$ {cmd}\n{output}"),
        )
        await db.commit()
        return output or res.stderr or "(no output)"

    async def narrate(text: str) -> None:
        await tg.send_message(text)

    llm = get_llm_client()
    report = await llm.diagnose_agentic(
        service_name, container_name, alert_message, execute=execute, narrate=narrate,
    )

    recommended = next((o for o in report.fix_options if o.recommended), None)
    await db.execute(
        "INSERT INTO analyses (incident_id, root_cause, severity, suggested_fix, fix_commands, report_json, llm_tokens_used) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            incident_id, report.summary, report.severity,
            recommended.detail if recommended else "",
            json.dumps(recommended.commands if recommended else []),
            json.dumps({
                "summary": report.summary, "severity": report.severity,
                "evidence": report.evidence, "machine_status": report.machine_status,
                "fix_options": [
                    {"title": o.title, "recommended": o.recommended, "detail": o.detail, "commands": o.commands}
                    for o in report.fix_options
                ],
                "truncated": report.truncated,
            }, ensure_ascii=False),
            report.tokens_used,
        ),
    )
    await db.commit()

    await tg.send_incident_report(service_name, report, incident_id)
    return incident_id
```

Remove the `from app.diagnostics import run_diagnostics` import.

- [ ] **Step 4: Run tests, verify pass**
  Run: `cd ops-bot && python3 -m pytest tests/test_orchestrator.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add ops-bot/app/orchestrator.py ops-bot/tests/test_orchestrator.py
git commit -m "feat(ops-bot): wire orchestrator to agentic diagnosis loop"
```

---

## Task 5: Telegram structured-report formatter

**Files:**
- Modify: `ops-bot/app/telegram_bot.py`
- Test: `ops-bot/tests/test_telegram_bot.py`

**Interfaces:**
- Consumes: `AgenticReport` (Task 2).
- Produces:
  - `format_report_message(service_name: str, report: AgenticReport) -> str`
  - `TelegramBot.send_incident_report(service_name, report, incident_id)` — new 3-arg signature.

- [ ] **Step 1: Write failing test**

Append to `tests/test_telegram_bot.py`:

```python
def test_format_report_message_has_sections():
    from app.llm_client import AgenticReport, FixOption
    from app.telegram_bot import format_report_message
    report = AgenticReport(
        summary="OOM Kill", severity="critical",
        evidence=[{"factor": "OOMKilled", "value": "true"}, {"factor": "Exit", "value": "137"}],
        machine_status="เครื่องปกติ — disk 53%",
        fix_options=[FixOption(title="เพิ่ม mem_limit", recommended=True, detail="3g→5g", commands=["docker compose up -d"])],
        tokens_used=300,
    )
    msg = format_report_message("Outline Wiki", report)
    assert "OOM Kill" in msg
    assert "OOMKilled" in msg and "137" in msg      # evidence table
    assert "เครื่องปกติ" in msg                       # machine_status
    assert "เพิ่ม mem_limit" in msg                    # fix option
    assert "⭐" in msg                                 # recommended marker
    assert "docker compose up -d" in msg              # command
```

- [ ] **Step 2: Run test, verify fails**
  Run: `cd ops-bot && python3 -m pytest tests/test_telegram_bot.py::test_format_report_message_has_sections -v`
  Expected: FAIL (no `format_report_message`)

- [ ] **Step 3: Implement formatter + update `send_incident_report`**

In `app/telegram_bot.py`, add `format_report_message` and replace `format_incident_message` usage. Replace the old `format_incident_message` function and `send_incident_report` with:

```python
def format_report_message(service_name: str, report) -> str:
    emoji = SEVERITY_EMOJI.get(report.severity, "⚪")
    thai = SEVERITY_THAI.get(report.severity, report.severity)
    lines = [
        f"📋 **ผลการวินิจฉัย — {service_name}**",
        f"{emoji} ระดับ: {thai}\n",
        f"**สรุปสาเหตุ:** {report.summary}",
    ]
    if report.evidence:
        rows = "\n".join(f"{e.get('factor','')}: {e.get('value','')}" for e in report.evidence)
        lines.append(f"\n**ปัจจัย:**\n```\n{rows}\n```")
    if report.machine_status:
        lines.append(f"\n**สถานะเครื่อง:** {report.machine_status}")
    if report.fix_options:
        lines.append("\n**ขั้นตอนแก้ (รออนุมัติจากคุณ):**")
        for o in report.fix_options:
            star = "⭐ " if o.recommended else ""
            lines.append(f"{star}**{o.title}** — {o.detail}")
            if o.commands:
                cmds = "\n".join(o.commands)
                lines.append(f"```\n{cmds}\n```")
    if report.truncated:
        lines.append("\n⚠️ วิเคราะห์ไม่ครบ (ถึงเพดานรอบ)")
    return "\n".join(lines)
```

Then change `send_incident_report`:

```python
    async def send_incident_report(self, service_name: str, report, incident_id: int) -> None:
        msg = format_report_message(service_name, report)
        keyboard = {"inline_keyboard": [[{"text": "📋 ดู Logs เพิ่มเติม", "callback_data": f"logs:{incident_id}"}]]}
        await self.send_message(msg, reply_markup=keyboard)
```

Delete the now-unused `format_incident_message` and `_build_inline_keyboard` functions and the `from app.llm_client import LLMAnalysis` import (replace with nothing — `report` is duck-typed).

- [ ] **Step 4: Remove the transitional `LLMAnalysis` shim**

Now that telegram_bot no longer imports it, delete the transitional `LLMAnalysis` dataclass (and its `# transitional:` comment) from `app/llm_client.py`. Confirm zero importers remain and the app still imports:

```bash
cd ops-bot && grep -rn "LLMAnalysis" app/ tests/    # expect: no matches
cd ops-bot && python3 -c "import app.main"           # expect: exit 0, no output
```

- [ ] **Step 5: Run tests, verify pass**
  Run: `cd ops-bot && python3 -m pytest tests/test_telegram_bot.py -v`
  Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add ops-bot/app/telegram_bot.py ops-bot/app/llm_client.py ops-bot/tests/test_telegram_bot.py
git commit -m "feat(ops-bot): structured report formatter for Telegram; drop LLMAnalysis"
```

---

## Task 6: Dashboard renders `report_json`

**Files:**
- Modify: `ops-bot/app/dashboard.py`, `ops-bot/app/templates/incident_detail.html`

**Interfaces:**
- Consumes: `analyses.report_json` (Task 1), stored by orchestrator (Task 4).
- Produces: incident detail page rendering summary, evidence `<table>`, machine_status, and fix-option cards; falls back to legacy columns when `report_json` is null.

- [ ] **Step 1: Parse `report_json` in `dashboard.py`**

In `dashboard_incident`, after fetching `analysis`, add report parsing. The `analyses` SELECT already uses `SELECT root_cause, severity, suggested_fix, fix_commands, llm_tokens_used, created_at`. Change it to also pull `report_json`:

```python
    cursor = await db.execute(
        "SELECT root_cause, severity, suggested_fix, fix_commands, llm_tokens_used, created_at, report_json "
        "FROM analyses WHERE incident_id = ?",
        (incident_id,),
    )
    analysis = await cursor.fetchone()

    report = None
    if analysis and analysis[6]:
        report = json.loads(analysis[6])
```

And pass `report` into the template context (add `"report": report,`). Keep `fix_commands` context for the legacy fallback.

- [ ] **Step 2: Render report in the template**

In `incident_detail.html`, replace the `{% if analysis %}...ผลวิเคราะห์...{% endif %}` block with:

```html
    {% if report %}
    <h2>ผลการวินิจฉัย</h2>
    <div class="card">
        <strong>สรุปสาเหตุ:</strong> {{ report.summary }}<br>
        <strong>Severity:</strong> <span class="severity-{{ report.severity }}">{{ report.severity }}</span>
        {% if report.truncated %}<br><em>⚠️ วิเคราะห์ไม่ครบ (ถึงเพดานรอบ)</em>{% endif %}
    </div>
    {% if report.evidence %}
    <div class="card">
        <strong>ปัจจัย</strong>
        <table>
            <tr><th>ปัจจัย</th><th>ค่า</th></tr>
            {% for e in report.evidence %}
            <tr><td>{{ e.factor }}</td><td>{{ e.value }}</td></tr>
            {% endfor %}
        </table>
    </div>
    {% endif %}
    {% if report.machine_status %}
    <div class="card"><strong>สถานะเครื่อง:</strong> {{ report.machine_status }}</div>
    {% endif %}
    {% if report.fix_options %}
    <h2>ขั้นตอนแก้ (รออนุมัติ)</h2>
    {% for o in report.fix_options %}
    <div class="card">
        <strong>{% if o.recommended %}⭐ {% endif %}{{ o.title }}</strong><br>
        {{ o.detail }}
        {% if o.commands %}<pre>{{ o.commands | join('\n') }}</pre>{% endif %}
    </div>
    {% endfor %}
    {% endif %}
    {% elif analysis %}
    <h2>ผลวิเคราะห์</h2>
    <div class="card">
        <strong>Root Cause:</strong> {{ analysis[0] }}<br>
        <strong>Severity:</strong> <span class="severity-{{ analysis[1] }}">{{ analysis[1] }}</span><br>
        <strong>แนะนำ:</strong> {{ analysis[2] }}
    </div>
    {% endif %}
```

- [ ] **Step 3: Manual render check (local Jinja)**

Run:

```bash
cd ops-bot && python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('app/templates'))
t = env.get_template('incident_detail.html')
report = {'summary':'OOM','severity':'critical','truncated':False,
  'evidence':[{'factor':'OOMKilled','value':'true'}],'machine_status':'ปกติ',
  'fix_options':[{'title':'เพิ่ม mem','recommended':True,'detail':'3g→5g','commands':['docker compose up -d']}]}
html = t.render(incident={0:1,1:'Outline',2:'outline',3:'down',5:0,6:'t','id':1,'service_name':'Outline','container_name':'outline','status':'down','is_watchtower_update':0,'created_at':'t'}, report=report, diagnostics=[], analysis=None, actions=[], fix_commands=[])
assert 'OOMKilled' in html and '⭐' in html and 'docker compose up -d' in html
print('RENDER OK')
"
```

Expected: `RENDER OK`

- [ ] **Step 4: Commit**

```bash
git add ops-bot/app/dashboard.py ops-bot/app/templates/incident_detail.html
git commit -m "feat(ops-bot): dashboard renders structured agentic report"
```

---

## Task 7: Delete dead diagnostics module + full suite + deploy

**Files:**
- Delete: `ops-bot/app/diagnostics.py`, `ops-bot/tests/test_diagnostics.py`

**Interfaces:**
- Consumes: nothing new. Verifies no remaining importer of `app.diagnostics`.

- [ ] **Step 1: Confirm no importers remain**

Run:

```bash
cd ops-bot && grep -rn "diagnostics import\|import diagnostics\|run_diagnostics\|find_compose_file\|LLMAnalysis" app/ tests/
```

Expected: no matches (orchestrator import removed in Task 4; `LLMAnalysis` removed in Task 5). If any match remains, remove it before deleting. Then confirm the app still imports: `cd ops-bot && python3 -c "import app.main"` → exit 0.

- [ ] **Step 2: Delete the module and its test**

```bash
git rm ops-bot/app/diagnostics.py ops-bot/tests/test_diagnostics.py
```

- [ ] **Step 3: Run the full suite**
  Run: `cd ops-bot && python3 -m pytest tests/ -q`
  Expected: PASS (no collection errors, no ImportError for `app.diagnostics`)

- [ ] **Step 4: Commit**

```bash
git add -A ops-bot/
git commit -m "refactor(ops-bot): remove fixed-diagnostic module (replaced by agentic loop)"
```

- [ ] **Step 5: Deploy + live end-to-end verify**

```bash
./scripts/deploy.sh -s ops-bot -y
```

Then fire a test DOWN webhook and confirm: Telegram shows a "🔧 กำลังตรวจสอบ..." message, at least one live finding, and a final structured report; the dashboard incident page shows the evidence table.

```bash
SECRET=$(grep KUMA_WEBHOOK_SECRET ops-bot/.env | cut -d= -f2)
curl -s -X POST "http://<NAS_HOST>:5070/webhook/uptime-kuma?secret=${SECRET}" \
  -H 'Content-Type: application/json' \
  -d '{"heartbeat":{"status":0,"time":"now","msg":"e2e agentic test"},"monitor":{"name":"News Feed","url":"http://x","hostname":null,"port":null}}'
```

- [ ] **Step 6: Update stack notes**

Update `ops-bot/.notes/daily_log.md` and `ops-bot/.notes/00_INDEX.md` with the agentic-diagnosis change (new tools, loop cap, report schema, removed diagnostics.py). Commit.

```bash
git add ops-bot/.notes/
git commit -m "docs(ops-bot): note agentic diagnosis in stack notes"
```

---

## Self-Review

**Spec coverage:**
- Agent loop + native tool-calling → Task 3. ✓
- `run_diagnostic`/`note_finding`/`submit_report` tools → Task 2 (schemas), Task 3 (dispatch). ✓
- Narration option B (`note_finding` → Telegram) → Task 3 (narrate callback), Task 4 (wiring). ✓
- Read-only via existing whitelist → Task 4 `execute` routes through `ssh.execute_command`; whitelist unchanged. ✓
- Replace fixed path, no fallback → Task 4 (rewrite), Task 7 (delete diagnostics.py). ✓
- Report structure option C (summary/severity/evidence/machine_status/fix_options) → Task 2 schema, Task 5 Telegram, Task 6 dashboard. ✓
- Storage: `report_json` + back-compat columns → Task 1 (column), Task 4 (insert). ✓
- Iteration cap 10 + partial on cap → Task 3 (`MAX_ITERS`, truncated path), test in Task 3. ✓
- Error handling (mimo error, blocked cmd, cap, malformed) → Task 3 try/except + fallback; blocked-cmd behavior is inherent (whitelist returns error text fed back). ✓
- Tests → Tasks 2/3/4/5 TDD; full suite Task 7. ✓

**Placeholder scan:** No TBD/TODO; every code-changing step shows code. `<NAS_HOST>` in Task 7 is a deliberate placeholder per the repo's security rule (real IP resolved at run time).

**Type consistency:** `AgenticReport`/`FixOption` field names identical across Tasks 2–6. `diagnose_agentic(execute=, narrate=)` keyword args match between Task 3 definition and Task 4 call. `send_incident_report(service_name, report, incident_id)` matches between Task 4 call and Task 5 definition. `report_json` column name consistent Tasks 1/4/6.

Note: the blocked-command test named in the spec is covered implicitly — a blocked command returns whitelist error text through `execute`, which the loop feeds back with no special-casing. No dedicated task test is required beyond the happy-path/cap/error tests in Task 3, since `execute` is the caller's responsibility and already whitelisted in `ssh_client`.
