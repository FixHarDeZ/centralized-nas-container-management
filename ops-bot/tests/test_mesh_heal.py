from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

import app.config
import app.db
from app import maintenance, mesh_heal
from app.router_client import RouterResult

T0 = 1_800_000_000.0
MIN = 60


@pytest_asyncio.fixture
async def env(tmp_path, monkeypatch):
    monkeypatch.setenv("MESH_NODE_HOST", "10.0.0.172")
    monkeypatch.setenv("ROUTER_SSH_HOST", "10.0.0.1")
    monkeypatch.setenv("MESH_STATE_FILE", str(tmp_path / "mesh.json"))
    monkeypatch.setenv("DB_PATH", str(tmp_path / "ops.db"))
    monkeypatch.setenv("MAINTENANCE_FILE", str(tmp_path / "until"))
    app.config._config = None
    app.db._db = None
    await app.db.init_db()
    maintenance._held.clear()
    maintenance._quiet_until = 0.0
    mesh_heal._group_skipped = False
    mesh_heal._state_cache = None
    probe = AsyncMock(return_value=False)
    restart = AsyncMock(return_value=RouterResult(True, "Done."))
    said: list[str] = []

    async def say(text, retry=False):
        said.append(text)

    with patch("app.mesh_heal.probe", probe), \
         patch("app.mesh_heal.router_client.restart_network", restart), \
         patch("app.mesh_heal.say", side_effect=say):
        yield probe, restart, said
    await app.db.close_db()
    app.db._db = None
    maintenance._held.clear()
    maintenance._quiet_until = 0.0


async def _rows(sql):
    db = await app.db.get_db()
    return [tuple(r) for r in await (await db.execute(sql)).fetchall()]


def test_disabled_without_hosts(monkeypatch):
    app.config._config = None
    assert mesh_heal.enabled() is False


@pytest.mark.asyncio
async def test_down_under_threshold_does_nothing(env):
    probe, restart, said = env
    mesh_heal.on_down(T0)
    await mesh_heal.tick(T0 + 4 * MIN)
    restart.assert_not_called()
    assert said == []


@pytest.mark.asyncio
async def test_up_before_threshold_is_silent_and_resets(env):
    probe, restart, said = env
    mesh_heal.on_down(T0)
    await mesh_heal.on_up(T0 + 3 * MIN)
    await mesh_heal.tick(T0 + 10 * MIN)
    restart.assert_not_called()
    assert said == []


@pytest.mark.asyncio
async def test_repeat_down_keeps_first_timestamp(env):
    probe, restart, said = env
    mesh_heal.on_down(T0)
    mesh_heal.on_down(T0 + 4 * MIN)
    await mesh_heal.tick(T0 + 5 * MIN)
    restart.assert_called_once()


@pytest.mark.asyncio
async def test_fixes_after_threshold_and_warns_first(env):
    probe, restart, said = env
    mesh_heal.on_down(T0)
    await mesh_heal.tick(T0 + 5 * MIN)
    restart.assert_called_once()
    assert said and said[0].startswith("🔧")
    assert maintenance.active(T0 + 5 * MIN + 1)  # quiet window open
    incidents = await _rows("select service_name, status from incidents")
    assert incidents == [("Mesh Node", "down")]
    actions = await _rows("select action_type, commands_executed from actions")
    assert actions == [("router_restart", "service restart_net_and_phy")]


@pytest.mark.asyncio
async def test_reachable_node_at_threshold_is_left_alone(env):
    probe, restart, said = env
    probe.return_value = True
    mesh_heal.on_down(T0)
    await mesh_heal.tick(T0 + 5 * MIN)
    restart.assert_not_called()
    probe.return_value = False
    await mesh_heal.tick(T0 + 20 * MIN)  # state was cleared, not re-armed
    restart.assert_not_called()


@pytest.mark.asyncio
async def test_up_after_fix_reports_success(env):
    probe, restart, said = env
    mesh_heal.on_down(T0)
    await mesh_heal.tick(T0 + 5 * MIN)
    await mesh_heal.on_up(T0 + 6 * MIN)
    assert said[-1].startswith("✅")
    assert await _rows("select status from incidents") == [("healed",)]
    assert await _rows("select success from actions") == [(1,)]


@pytest.mark.asyncio
async def test_no_up_retries_once_then_gives_up(env):
    probe, restart, said = env
    mesh_heal.on_down(T0)
    await mesh_heal.tick(T0 + 5 * MIN)
    await mesh_heal.tick(T0 + 9 * MIN)  # still inside verify window
    assert restart.call_count == 1
    await mesh_heal.tick(T0 + 10 * MIN + 1)  # verify timed out -> retry now
    assert restart.call_count == 2
    await mesh_heal.tick(T0 + 15 * MIN + 2)  # second timeout -> give up
    assert restart.call_count == 2
    assert said[-1].startswith("🆘")
    await mesh_heal.tick(T0 + 90 * MIN)  # paused until UP
    assert restart.call_count == 2
    assert await _rows("select status from incidents") == [("gave_up",)]


@pytest.mark.asyncio
async def test_paused_resumes_after_up(env):
    probe, restart, said = env
    mesh_heal.on_down(T0)
    for t in (5, 10.1, 15.2):
        await mesh_heal.tick(T0 + t * MIN)
    await mesh_heal.on_up(T0 + 20 * MIN)
    assert said[-1].startswith("🟢")
    mesh_heal.on_down(T0 + 60 * MIN)
    await mesh_heal.tick(T0 + 65 * MIN)
    assert restart.call_count == 3


@pytest.mark.asyncio
async def test_ssh_error_counts_as_failure_and_retries(env):
    probe, restart, said = env
    restart.return_value = RouterResult(False, "connect failed: no route")
    mesh_heal.on_down(T0)
    await mesh_heal.tick(T0 + 5 * MIN)
    assert any("connect failed" in s for s in said)
    await mesh_heal.tick(T0 + 5 * MIN + 30)  # next watcher tick retries
    assert restart.call_count == 2
    await mesh_heal.tick(T0 + 5 * MIN + 60)
    assert restart.call_count == 2 and said[-1].startswith("🆘")


@pytest.mark.asyncio
async def test_retry_finds_node_back_without_up(env):
    probe, restart, said = env
    mesh_heal.on_down(T0)
    await mesh_heal.tick(T0 + 5 * MIN)
    probe.return_value = True  # Kuma UP lost, node answers
    await mesh_heal.tick(T0 + 10 * MIN + 1)
    assert restart.call_count == 1
    assert said[-1].startswith("✅")


@pytest.mark.asyncio
async def test_cooldown_delays_next_episode(env):
    probe, restart, said = env
    mesh_heal.on_down(T0)
    await mesh_heal.tick(T0 + 5 * MIN)
    await mesh_heal.on_up(T0 + 6 * MIN)
    mesh_heal.on_down(T0 + 10 * MIN)
    await mesh_heal.tick(T0 + 20 * MIN)  # 15 min after last fix
    assert restart.call_count == 1
    await mesh_heal.tick(T0 + 35 * MIN + 1)  # cooldown over, still down
    assert restart.call_count == 2


@pytest.mark.asyncio
async def test_daily_cap_pauses_and_asks_human(env):
    probe, restart, said = env
    t = T0
    for _ in range(3):
        mesh_heal.on_down(t)
        await mesh_heal.tick(t + 5 * MIN)
        await mesh_heal.on_up(t + 6 * MIN)
        t += 40 * MIN
    mesh_heal.on_down(t)
    await mesh_heal.tick(t + 5 * MIN)
    assert restart.call_count == 3
    assert said[-1].startswith("🆘")
    # rolling 24 h: a day after the first fix the budget is back
    mesh_heal.on_down(T0 + 25 * 60 * MIN)
    await mesh_heal.on_up(T0 + 25 * 60 * MIN)  # UP clears the pause
    mesh_heal.on_down(T0 + 26 * 60 * MIN)
    await mesh_heal.tick(T0 + 26 * 60 * MIN + 5 * MIN)
    assert restart.call_count == 4


@pytest.mark.asyncio
async def test_state_survives_restart(env):
    probe, restart, said = env
    mesh_heal.on_down(T0)
    mesh_heal._state_cache = None  # what a process restart loses
    await mesh_heal.tick(T0 + 5 * MIN)
    restart.assert_called_once()


def test_group_message_only_mesh():
    assert mesh_heal.only_mesh_down("Child monitors down: Mesh Node")
    assert not mesh_heal.only_mesh_down("Child monitors down: Mesh Node, DDNS fixhardez.synology.me")
    assert not mesh_heal.only_mesh_down("Child monitors down: DDNS fixhardez.synology.me")
    assert not mesh_heal.only_mesh_down("")
