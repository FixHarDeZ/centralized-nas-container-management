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
