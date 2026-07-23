# ops-bot/tests/test_orchestrator.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.orchestrator import handle_incident


@pytest.mark.asyncio
async def test_handle_incident_skips_watchtower_update():
    with (
        patch("app.orchestrator.is_watchtower_update", new_callable=AsyncMock, return_value=True),
        patch("app.orchestrator.get_db") as mock_db,
    ):
        mock_db_instance = AsyncMock()
        mock_db_instance.execute = AsyncMock(
            return_value=type("Cursor", (), {"lastrowid": 1})()
        )
        mock_db_instance.commit = AsyncMock()
        mock_db.return_value = mock_db_instance

        result = await handle_incident("test-service", "test-container", "down", "test alert")

        assert result == 1  # incident created but skipped


@pytest.mark.asyncio
async def test_handle_incident_runs_full_pipeline():
    mock_ssh_result = type("R", (), {"stdout": "output", "stderr": "", "exit_code": 0})()
    mock_ssh = AsyncMock()
    mock_ssh.execute_command = AsyncMock(return_value=mock_ssh_result)

    mock_analysis = type("A", (), {
        "root_cause": "OOM Kill",
        "severity": "critical",
        "suggested_fix": "เพิ่ม mem_limit",
        "fix_commands": ["cmd1"],
        "safety_note": "⚠️ confirm ก่อน",
        "tokens_used": 100,
    })()

    mock_db_instance = AsyncMock()
    mock_cursor = AsyncMock()
    mock_cursor.lastrowid = 1
    mock_cursor.__aiter__ = AsyncMock(return_value=iter([]))
    mock_db_instance.execute = AsyncMock(return_value=mock_cursor)
    mock_db_instance.commit = AsyncMock()

    with (
        patch("app.orchestrator.is_watchtower_update", new_callable=AsyncMock, return_value=False),
        patch("app.orchestrator.run_diagnostics", new_callable=AsyncMock, return_value={"container_status": "test"}) as mock_diag,
        patch("app.orchestrator.get_llm_client") as mock_llm,
        patch("app.orchestrator.get_telegram_bot") as mock_tg,
        patch("app.orchestrator.get_db", return_value=mock_db_instance),
    ):
        mock_llm.return_value = type("C", (), {"analyze_diagnostic": AsyncMock(return_value=mock_analysis)})()
        mock_tg.return_value = type("T", (), {"send_incident_report": AsyncMock()})()

        result = await handle_incident("test-service", "test-container", "down", "test alert")

        assert result == 1
        mock_diag.assert_called_once_with("test-container")
