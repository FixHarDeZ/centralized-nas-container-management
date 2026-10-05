from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import app.config
from app import maintenance, mesh_heal
from app.main import app as fastapi_app


def _body(name, status, msg=""):
    return {
        "heartbeat": {"status": status, "time": "2026-10-05 03:49:07", "msg": msg},
        "monitor": {"name": name},
    }


@pytest.fixture
def mesh_env(tmp_path, monkeypatch):
    monkeypatch.setenv("MESH_NODE_HOST", "10.0.0.172")
    monkeypatch.setenv("ROUTER_SSH_HOST", "10.0.0.1")
    monkeypatch.setenv("MESH_STATE_FILE", str(tmp_path / "mesh.json"))
    monkeypatch.setenv("MAINTENANCE_FILE", str(tmp_path / "until"))
    app.config._config = None
    mesh_heal._state_cache = None
    mesh_heal._group_skipped = False
    maintenance._held.clear()
    maintenance._quiet_until = 0.0
    yield tmp_path
    maintenance._held.clear()
    maintenance._quiet_until = 0.0
    mesh_heal._state_cache = None
    mesh_heal._group_skipped = False


async def _post(body):
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return (await client.post("/webhook/uptime-kuma", json=body)).json()


@pytest.mark.asyncio
async def test_mesh_down_and_up_never_reach_llm(mesh_env):
    with patch("app.webhook.handle_incident", new_callable=AsyncMock) as incident, \
         patch("app.webhook.handle_recovery", new_callable=AsyncMock) as recovery, \
         patch("app.webhook.mesh_heal.on_up", new_callable=AsyncMock) as on_up:
        assert (await _post(_body("Mesh Node", 0, "unreachable")))["status"] == "mesh_heal"
        assert mesh_heal._load()["down_since"] is not None
        assert (await _post(_body("Mesh Node", 1)))["status"] == "mesh_heal"
    incident.assert_not_called()
    recovery.assert_not_called()
    on_up.assert_awaited_once()


@pytest.mark.asyncio
async def test_mesh_down_in_deploy_window_is_not_held(mesh_env):
    (mesh_env / "until").write_text(f"{int(time.time()) + 600}\nhomepage\n")
    with patch("app.webhook.handle_incident", new_callable=AsyncMock) as incident:
        assert (await _post(_body("Mesh Node", 0)))["status"] == "mesh_heal"
    incident.assert_not_called()
    assert "Mesh Node" not in maintenance._held


@pytest.mark.asyncio
async def test_group_with_only_mesh_is_skipped_both_ways(mesh_env):
    with patch("app.webhook.handle_incident", new_callable=AsyncMock) as incident, \
         patch("app.webhook.handle_recovery", new_callable=AsyncMock) as recovery:
        down = _body("Home Network Monitor", 0, "Child monitors down: Mesh Node")
        assert (await _post(down))["status"] == "mesh_heal"
        assert (await _post(_body("Home Network Monitor", 1)))["status"] == "mesh_heal"
    incident.assert_not_called()
    recovery.assert_not_called()


@pytest.mark.asyncio
async def test_group_with_other_children_is_still_diagnosed(mesh_env):
    with patch("app.webhook.handle_incident", new_callable=AsyncMock) as incident:
        down = _body("Home Network Monitor", 0, "Child monitors down: Mesh Node, DDNS x")
        assert (await _post(down))["status"] == "accepted"
    incident.assert_called_once()


@pytest.mark.asyncio
async def test_collateral_down_in_quiet_window_is_held(mesh_env):
    maintenance.quiet(time.time() + 180)
    with patch("app.webhook.handle_incident", new_callable=AsyncMock) as incident:
        assert (await _post(_body("DDNS x", 0)))["status"] == "maintenance"
    incident.assert_not_called()
    assert "DDNS x" in maintenance._held


@pytest.mark.asyncio
async def test_disabled_mesh_goes_the_old_way(monkeypatch, tmp_path):
    monkeypatch.setenv("MAINTENANCE_FILE", str(tmp_path / "until"))
    app.config._config = None
    with patch("app.webhook.handle_incident", new_callable=AsyncMock) as incident:
        assert (await _post(_body("Mesh Node", 0)))["status"] == "accepted"
    incident.assert_called_once()
