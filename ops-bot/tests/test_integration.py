"""Integration test: simulate full webhook → diagnose → LLM → Telegram flow."""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
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
    """Mock SSH client that returns realistic diagnostic output."""
    mock = AsyncMock()
    responses = {
        "docker ps": type("R", (), {
            "stdout": "outliner-outline-1   Restarting (137)   2 minutes ago\n",
            "stderr": "", "exit_code": 0
        })(),
        "docker inspect": type("R", (), {
            "stdout": json.dumps({
                "OOMKilled": True,
                "ExitCode": 137,
                "Running": False,
                "Restarting": True,
                "StartedAt": "2026-07-23T07:40:00Z"
            }),
            "stderr": "", "exit_code": 0
        })(),
        "docker logs": type("R", (), {
            "stdout": "2026-07-23 07:40:00 Starting Outline Wiki...\n2026-07-23 07:40:05 OOMKilled\n",
            "stderr": "", "exit_code": 0
        })(),
        "df": type("R", (), {
            "stdout": "Filesystem      Size  Used Avail Use% Mounted on\n/dev/vda1       100G   53G   47G  53% /\n",
            "stderr": "", "exit_code": 0
        })(),
        "free": type("R", (), {
            "stdout": "              total        used        free      shared  buff/cache   available\nMem:          12900        8200        2100         300        2600        4400\n",
            "stderr": "", "exit_code": 0
        })(),
        "uptime": type("R", (), {
            "stdout": " 07:41:00 up 30 days,  1:23,  1 user,  load average: 1.37, 0.95, 0.82\n",
            "stderr": "", "exit_code": 0
        })(),
        "curl": type("R", (), {
            "stdout": "000",
            "stderr": "curl: (7) Failed to connect to localhost port 3000: Connection refused",
            "exit_code": 7
        })(),
        "docker network": type("R", (), {
            "stdout": json.dumps({"outliner_default": {"Driver": "bridge"}}),
            "stderr": "", "exit_code": 0
        })(),
        "docker port": type("R", (), {
            "stdout": "3000/tcp -> 0.0.0.0:3000\n",
            "stderr": "", "exit_code": 0
        })(),
        "compose logs": type("R", (), {
            "stdout": "outliner-1  | Starting...\noutliner-1  | OOMKilled\n",
            "stderr": "", "exit_code": 0
        })(),
    }

    def side_effect(cmd, **kwargs):
        # Watchtower returns empty (no recent update)
        if "watchtower" in cmd:
            return type("R", (), {"stdout": "", "stderr": "", "exit_code": 1})()
        for key, resp in responses.items():
            if key in cmd:
                return resp
        return type("R", (), {"stdout": "", "stderr": "", "exit_code": 0})()

    mock.execute_command = AsyncMock(side_effect=side_effect)
    return mock


@pytest.fixture
def mock_llm():
    """Mock LLM client that returns realistic analysis."""
    from app.llm_client import LLMAnalysis
    mock = AsyncMock()
    mock.analyze_diagnostic = AsyncMock(return_value=LLMAnalysis(
        root_cause="OOM Kill — container ใช้ RAM เกิน 3GB limit (mem_limit: 3g)",
        severity="critical",
        suggested_fix="เพิ่ม mem_limit จาก 3g เป็น 5g (เครื่องมี RAM ว่าง ~12.9GB)",
        fix_commands=[
            "sed -i 's/mem_limit: 3g/mem_limit: 5g/' ~/outliner/docker-compose.yml",
            "cd ~/outliner && docker compose up -d outliner"
        ],
        safety_note="⚠️ fix_commands เป็นข้อเสนอแนะเท่านั้น — กรุณา confirm ก่อนรันเสมอ",
        tokens_used=450,
    ))
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
    """Simulate: Kuma DOWN → webhook → SSH diagnostics → LLM analysis → Telegram notify."""
    import app.config
    app.config._config = None

    import app.main
    fastapi_app = app.main.app

    with (
        patch("app.diagnostics.get_ssh_client", return_value=mock_ssh),
        patch("app.watchtower.get_ssh_client", return_value=mock_ssh),
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

            # Verify SSH diagnostics were called
            assert mock_ssh.execute_command.call_count >= 5
            calls = [str(c) for c in mock_ssh.execute_command.call_args_list]
            assert any("docker ps" in c for c in calls), "Should run docker ps"
            assert any("docker inspect" in c for c in calls), "Should run docker inspect"
            assert any("docker logs" in c for c in calls), "Should run docker logs"
            assert any("df" in c for c in calls), "Should run df"
            assert any("free" in c for c in calls), "Should run free"

            # Verify LLM was called with diagnostic results
            mock_llm.analyze_diagnostic.assert_called_once()
            llm_args = mock_llm.analyze_diagnostic.call_args
            assert llm_args[0][0] == "Outline Wiki"  # service_name
            assert isinstance(llm_args[0][1], dict)  # diagnostic_results

            # Verify Telegram notification was sent
            mock_telegram.send_incident_report.assert_called_once()
            tg_args = mock_telegram.send_incident_report.call_args
            assert tg_args[0][0] == "Outline Wiki"  # service_name
            analysis = tg_args[0][1]
            assert "OOM" in analysis.root_cause
            assert analysis.severity == "critical"
            assert analysis.safety_note  # safety_note must be present
            assert len(analysis.fix_commands) > 0

            print("\n✅ FULL DOWN FLOW PASSED:")
            print(f"   Webhook → accepted")
            print(f"   SSH diagnostics → {mock_ssh.execute_command.call_count} commands")
            print(f"   LLM analysis → {analysis.root_cause}")
            print(f"   Telegram → sent with safety_note: {analysis.safety_note[:40]}...")


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
        patch("app.diagnostics.get_ssh_client", return_value=mock_ssh),
        patch("app.watchtower.get_ssh_client", return_value=mock_ssh),
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
            assert mock_llm.analyze_diagnostic.call_count == 1

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
