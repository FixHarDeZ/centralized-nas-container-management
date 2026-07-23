# ops-bot/tests/test_telegram_bot.py
import pytest
from unittest.mock import AsyncMock, patch

from app.telegram_bot import TelegramBot, format_incident_message
from app.llm_client import LLMAnalysis


@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    from app.config import _config
    import app.config
    app.config._config = None
    yield
    app.config._config = None


def test_format_incident_message():
    analysis = LLMAnalysis(
        root_cause="OOM Kill — container ใช้ RAM เกิน 3GB limit",
        severity="critical",
        suggested_fix="เพิ่ม mem_limit จาก 3g เป็น 5g",
        fix_commands=["sed -i 's/3g/5g/' docker-compose.yml"],
        tokens_used=500,
    )
    diagnostic_results = {
        "container_status": "$ docker ps\noutliner-outline-1 Restarting",
        "system_resources": "$ free -m\nMem: 12900",
    }

    msg = format_incident_message("Outline Wiki", analysis, diagnostic_results)

    assert "Outline Wiki" in msg
    assert "OOM" in msg
    assert "critical" in msg.lower() or "วิกฤต" in msg
    assert "mem_limit" in msg
