# ops-bot/tests/test_telegram_bot.py
import pytest
from unittest.mock import AsyncMock, patch

from app.telegram_bot import TelegramBot


@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    from app.config import _config
    import app.config
    app.config._config = None
    yield
    app.config._config = None


def test_format_report_message_has_sections():
    from app.llm_client import AgenticReport, FixOption
    from app.telegram_bot import format_report_message
    report = AgenticReport(
        summary="OOM Kill", severity="critical",
        evidence=[{"factor": "OOMKilled", "value": "true"}, {"factor": "Exit", "value": "137"}],
        machine_status="เครื่องปกติ — disk 53%",
        fix_options=[FixOption(title="เพิ่ม mem_limit", recommended=True, detail="3g→5g", commands=["docker compose up -d"], file_changes=[])],
        tokens_used=300,
    )
    msg = format_report_message("Outline Wiki", report)
    assert "OOM Kill" in msg
    assert "OOMKilled" in msg and "137" in msg      # evidence table
    assert "เครื่องปกติ" in msg                       # machine_status
    assert "เพิ่ม mem_limit" in msg                    # fix option
    assert "⭐" in msg                                 # recommended marker
    assert "docker compose up -d" in msg              # command


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
