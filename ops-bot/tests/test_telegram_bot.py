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
