"""Integration test: simulate full webhook → diagnose → LLM → Telegram flow."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient, ASGITransport


@pytest.fixture
def mock_env(monkeypatch):
    """Set all required env vars for testing."""
    monkeypatch.setenv("MIMO_API_KEY", "test-key")
    monkeypatch.setenv("MIMO_BASE_URL", "https://test.api.com/v1")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("SSH_HOST", "192.168.1.1")
    monkeypatch.setenv("SSH_USER", "testuser")
    monkeypatch.setenv("KUMA_WEBHOOK_SECRET", "test-secret-123")
    monkeypatch.setenv("DB_PATH", "/tmp/ops_bot_test.db")
    # Reset config singleton
    import app.config
    app.config._config = None
    yield
    app.config._config = None


@pytest.fixture
def mock_ssh():
    """Mock SSH client used by the orchestrator's `execute` callback."""
    ssh_result = type("R", (), {"stdout": "out", "stderr": "", "exit_code": 0})()
    mock = type("S", (), {"execute_command": AsyncMock(return_value=ssh_result)})()
    return mock


@pytest.fixture
def mock_llm():
    """Mock LLM client whose diagnose_agentic returns a real AgenticReport,
    exercising the injected execute/narrate callbacks once."""
    from app.llm_client import AgenticReport, FixOption

    report = AgenticReport(
        summary="OOM Kill — container ใช้ RAM เกิน 3GB limit (mem_limit: 3g)",
        severity="critical",
        evidence=[{"factor": "OOMKilled", "value": "true"}],
        machine_status="ปกติ",
        fix_options=[
            FixOption(
                title="เพิ่ม mem_limit",
                recommended=True,
                detail="เพิ่ม mem_limit จาก 3g เป็น 5g (เครื่องมี RAM ว่าง ~12.9GB)",
                commands=[
                    "sed -i 's/mem_limit: 3g/mem_limit: 5g/' ~/outliner/docker-compose.yml",
                    "cd ~/outliner && docker compose up -d outliner",
                ],
            )
        ],
        tokens_used=450,
        findings=["เจอ restart-loop"],
        truncated=False,
    )

    async def fake_diagnose(service_name, container_name, alert_message, *, execute, narrate):
        # exercise the injected callbacks like the real agentic loop would
        await execute("docker ps -a")
        await narrate("เจอ restart-loop")
        return report

    mock = type("C", (), {"diagnose_agentic": AsyncMock(side_effect=fake_diagnose)})()
    return mock


@pytest.fixture
def mock_telegram():
    """Mock Telegram bot to capture sent messages."""
    mock = AsyncMock()
    mock.send_incident_report = AsyncMock()
    mock.send_recovery_notification = AsyncMock()
    mock.send_fix_confirmation = AsyncMock()
    mock.send_message = AsyncMock(return_value={"ok": True})
    mock.answer_callback = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_full_down_alert_flow(mock_env, mock_ssh, mock_llm, mock_telegram):
    """Simulate: Kuma DOWN → webhook → agentic diagnosis → LLM report → Telegram notify."""
    import app.config
    app.config._config = None

    import app.main
    fastapi_app = app.main.app

    with (
        patch("app.orchestrator.is_watchtower_update", new_callable=AsyncMock, return_value=False),
        patch("app.orchestrator.get_ssh_client", return_value=mock_ssh),
        patch("app.orchestrator.get_llm_client", return_value=mock_llm),
        patch("app.orchestrator.get_telegram_bot", return_value=mock_telegram),
        patch("app.webhook.get_telegram_bot", return_value=mock_telegram),
        patch("app.webhook._last_alert", {}),
    ):
        transport = ASGITransport(app=fastapi_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Send DOWN alert from Uptime Kuma
            resp = await client.post(
                "/webhook/uptime-kuma?secret=test-secret-123",
                json={
                    "heartbeat": {
                        "status": 0,
                        "time": "2026-07-23 07:40:51",
                        "msg": "connect ECONNREFUSED 192.168.1.111:3000",
                    },
                    "monitor": {
                        "name": "Outline Wiki",
                        "url": "http://192.168.1.111:3000",
                        "hostname": "192.168.1.111",
                        "port": "3000",
                    },
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "accepted"
            assert data["service"] == "Outline Wiki"

            # Wait for background task to complete
            import asyncio
            await asyncio.sleep(0.5)

            # Verify the agentic loop was invoked with the diagnostic callbacks
            mock_llm.diagnose_agentic.assert_called_once()
            call_args = mock_llm.diagnose_agentic.call_args
            assert call_args.args[0] == "Outline Wiki"  # service_name
            assert call_args.args[1] == "outliner-outline-1"  # container_name
            assert mock_ssh.execute_command.call_count >= 1  # execute callback exercised

            # Verify Telegram notification was sent
            mock_telegram.send_incident_report.assert_called_once()
            tg_args = mock_telegram.send_incident_report.call_args
            assert tg_args[0][0] == "Outline Wiki"  # service_name
            report = tg_args[0][1]
            assert "OOM" in report.summary
            assert report.severity == "critical"
            assert len(report.fix_options) > 0

            print("\n✅ FULL DOWN FLOW PASSED:")
            print(f"   Webhook → accepted")
            print(f"   Agentic diagnosis → invoked with callbacks")
            print(f"   LLM report → {report.summary}")
            print(f"   Telegram → sent")


@pytest.mark.asyncio
async def test_full_recovery_flow(mock_env, mock_telegram):
    """Simulate: Kuma UP → webhook → recovery Telegram notification."""
    import app.config
    app.config._config = None

    import app.main
    fastapi_app = app.main.app

    with (
        patch("app.webhook.get_telegram_bot", return_value=mock_telegram),
        patch("app.orchestrator.get_telegram_bot", return_value=mock_telegram),
        patch("app.webhook._last_alert", {"Outline Wiki": 999999999}),
    ):
        transport = ASGITransport(app=fastapi_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Send recovery (UP) alert
            resp = await client.post(
                "/webhook/uptime-kuma?secret=test-secret-123",
                json={
                    "heartbeat": {
                        "status": 1,
                        "time": "2026-07-23 08:15:00",
                        "msg": "",
                    },
                    "monitor": {
                        "name": "Outline Wiki",
                        "url": "http://192.168.1.111:3000",
                    },
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "recovery_noted"

            import asyncio
            await asyncio.sleep(0.5)

            # Verify recovery notification sent
            mock_telegram.send_recovery_notification.assert_called_once_with("Outline Wiki")

            print("\n✅ RECOVERY FLOW PASSED:")
            print(f"   Webhook → recovery_noted")
            print(f"   Telegram → recovery notification sent")


@pytest.mark.asyncio
async def test_debounce_blocks_duplicate(mock_env, mock_ssh, mock_llm, mock_telegram):
    """Simulate: same DOWN alert within 15 min → debounced."""
    import app.config
    app.config._config = None

    import app.main
    fastapi_app = app.main.app
    import app.webhook

    # Clear debounce state
    app.webhook._last_alert = {}

    with (
        patch("app.orchestrator.is_watchtower_update", new_callable=AsyncMock, return_value=False),
        patch("app.orchestrator.get_ssh_client", return_value=mock_ssh),
        patch("app.orchestrator.get_llm_client", return_value=mock_llm),
        patch("app.orchestrator.get_telegram_bot", return_value=mock_telegram),
        patch("app.webhook.get_telegram_bot", return_value=mock_telegram),
    ):
        transport = ASGITransport(app=fastapi_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            payload = {
                "heartbeat": {"status": 0, "time": "2026-07-23 07:40:00", "msg": "down"},
                "monitor": {"name": "Komga", "url": "http://192.168.1.111:25600"},
            }

            # First alert → accepted
            resp1 = await client.post("/webhook/uptime-kuma?secret=test-secret-123", json=payload)
            assert resp1.json()["status"] == "accepted"

            import asyncio
            await asyncio.sleep(0.5)

            # Second alert within debounce window → debounced
            resp2 = await client.post("/webhook/uptime-kuma?secret=test-secret-123", json=payload)
            assert resp2.json()["status"] == "debounced"

            # Verify only one incident was processed
            assert mock_llm.diagnose_agentic.call_count == 1

            print("\n✅ DEBOUNCE FLOW PASSED:")
            print(f"   1st alert → accepted (processed)")
            print(f"   2nd alert → debounced (skipped)")


@pytest.mark.asyncio
async def test_wrong_secret_rejected(mock_env):
    """Simulate: wrong secret → 401 Unauthorized."""
    import app.config
    app.config._config = None

    import app.main
    fastapi_app = app.main.app

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhook/uptime-kuma?secret=wrong-secret",
            json={
                "heartbeat": {"status": 0, "time": "2026-07-23 07:40:00", "msg": "down"},
                "monitor": {"name": "Test", "url": "http://test"},
            },
        )

        assert resp.status_code == 401
        assert "Invalid webhook secret" in resp.json()["detail"]

        print("\n✅ SECRET VALIDATION PASSED:")
        print(f"   Wrong secret → 401 Unauthorized")


@pytest.mark.asyncio
async def test_no_secret_rejected_when_configured(mock_env):
    """Simulate: no secret param when secret is configured → 401."""
    import app.config
    app.config._config = None

    import app.main
    fastapi_app = app.main.app

    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/webhook/uptime-kuma",  # No secret param
            json={
                "heartbeat": {"status": 0, "time": "2026-07-23 07:40:00", "msg": "down"},
                "monitor": {"name": "Test", "url": "http://test"},
            },
        )

        assert resp.status_code == 401

        print("\n✅ MISSING SECRET REJECTED PASSED:")
        print(f"   No secret → 401 Unauthorized")
