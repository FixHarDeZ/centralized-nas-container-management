# ops-bot/tests/test_diagnostics.py
import pytest
from unittest.mock import AsyncMock, patch

from app.diagnostics import run_diagnostics, find_compose_file, DIAGNOSTIC_STEPS


def test_diagnostic_steps_defined():
    assert len(DIAGNOSTIC_STEPS) >= 5
    step_names = [s["name"] for s in DIAGNOSTIC_STEPS]
    assert "container_status" in step_names
    assert "system_resources" in step_names
    assert "container_config" in step_names
    assert "service_health" in step_names
    assert "compose_logs" in step_names


@pytest.mark.asyncio
async def test_run_diagnostics_calls_ssh():
    mock_result = type("R", (), {"stdout": "output", "stderr": "", "exit_code": 0})()
    mock_ssh = AsyncMock()
    mock_ssh.execute_command = AsyncMock(return_value=mock_result)

    with patch("app.diagnostics.get_ssh_client", return_value=mock_ssh):
        results = await run_diagnostics("test-container")

    assert "container_status" in results
    assert mock_ssh.execute_command.call_count >= 5
