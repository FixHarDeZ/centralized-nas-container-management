# ops-bot/tests/test_llm_client.py
import pytest
import json
from unittest.mock import AsyncMock, patch

from app.llm_client import LLMClient, LLMAnalysis


@pytest.fixture
def mock_config(monkeypatch):
    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    monkeypatch.setenv("MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1")
    monkeypatch.setenv("MIMO_MODEL", "mimo-v2.5-pro")
    from app.config import _config
    import app.config
    app.config._config = None
    yield
    app.config._config = None


def test_llm_analysis_dataclass():
    a = LLMAnalysis(
        root_cause="OOM Kill",
        severity="critical",
        suggested_fix="เพิ่ม mem_limit",
        fix_commands=["docker compose up -d"],
        tokens_used=500,
    )
    assert a.severity == "critical"
    assert len(a.fix_commands) == 1


@pytest.mark.asyncio
async def test_analyze_diagnostic_returns_analysis(mock_config):
    mock_response = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "root_cause": "OOM Kill — container ใช้ RAM เกิน 3GB limit",
                    "severity": "critical",
                    "suggested_fix": "เพิ่ม mem_limit จาก 3g เป็น 5g",
                    "fix_commands": [
                        "sed -i 's/mem_limit: 3g/mem_limit: 5g/' ~/outliner/docker-compose.yml",
                        "cd ~/outliner && docker compose up -d outliner"
                    ]
                })
            }
        }],
        "usage": {"total_tokens": 450}
    }

    with patch("app.llm_client.AsyncOpenAI") as MockClient:
        instance = MockClient.return_value
        instance.chat.completions.create = AsyncMock(
            return_value=type("Response", (), {
                "choices": [type("Choice", (), {
                    "message": type("Msg", (), {
                        "content": json.dumps({
                            "root_cause": "OOM Kill — container ใช้ RAM เกิน 3GB limit",
                            "severity": "critical",
                            "suggested_fix": "เพิ่ม mem_limit จาก 3g เป็น 5g",
                            "fix_commands": [
                                "sed -i 's/mem_limit: 3g/mem_limit: 5g/' ~/outliner/docker-compose.yml",
                                "cd ~/outliner && docker compose up -d outliner"
                            ]
                        })
                    })()
                })()],
                "usage": type("Usage", (), {"total_tokens": 450})()
            })()
        )

        client = LLMClient()
        result = await client.analyze_diagnostic("Outline Wiki", {
            "container_status": "OOMKilled: true, Exit Code: 137",
            "system_resources": "RAM: 12.9GB available",
        })

        assert isinstance(result, LLMAnalysis)
        assert "OOM" in result.root_cause
        assert result.severity == "critical"
        assert len(result.fix_commands) > 0
