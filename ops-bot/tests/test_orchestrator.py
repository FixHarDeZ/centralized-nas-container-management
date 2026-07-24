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
