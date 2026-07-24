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
