# ops-bot/app/mesh_heal.py
"""Mesh Node auto-heal: Kuma DOWN for the AiMesh node lasting longer than
MESH_DOWN_MINUTES → restart the router's network over SSH (router_client).

Why this works: the node's Ethernet backhaul flaps, and afterwards the node
can stay half-attached (router still has its ARP entry and bridge MAC, but
nothing answers) until the router restarts its LAN. Rebooting the node does
not help. Spec: docs/superpowers/specs/2026-10-05-ops-bot-mesh-heal-design.md

The node never goes to the LLM path: it is not on the NAS and the diagnosis
there has never found anything (#103, #105, #106).

State lives in a JSON file on the data volume, not only in memory: Kuma only
notifies on change, so a DOWN lost to an ops-bot restart would never fire.
A stale down_since (UP missed while restarting) is caught by the probe right
before acting — ARP/bridge state is not a liveness check, both looked healthy
while the node was broken."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

from app import maintenance, router_client
from app.config import get_config
from app.db import get_db
from app.telegram_bot import get_telegram_bot

logger = logging.getLogger(__name__)

DAY = 24 * 3600
SAY_ATTEMPTS = 6  # x 30 s: the fix takes the NAS's internet with it
SAY_BACKOFF = 30

_state_cache: Optional[dict] = None
_group_skipped = False  # group DOWN skipped, so its UP is skipped too
_task: Optional[asyncio.Task] = None
_sends: set[asyncio.Task] = set()


def enabled() -> bool:
    cfg = get_config()
    return bool(cfg.mesh_node_host and cfg.router_ssh_host)


def is_mesh(service_name: str) -> bool:
    return enabled() and service_name == get_config().mesh_monitor_name


def only_mesh_down(alert_message: str) -> bool:
    """Kuma group message: `Child monitors down: A, B`."""
    _, sep, rest = (alert_message or "").partition("Child monitors down:")
    if not sep:
        return False
    names = {n.strip() for n in rest.split(",") if n.strip()}
    return names == {get_config().mesh_monitor_name}


def skip_group_down(service_name: str, alert_message: str) -> bool:
    global _group_skipped
    if not enabled() or service_name != get_config().mesh_group_name:
        return False
    if not only_mesh_down(alert_message):
        return False
    _group_skipped = True
    return True


def skip_group_up(service_name: str) -> bool:
    global _group_skipped
    if not enabled() or service_name != get_config().mesh_group_name or not _group_skipped:
        return False
    _group_skipped = False
    return True


# --- state ---------------------------------------------------------------

def _fresh() -> dict:
    return {
        "down_since": None,     # epoch of the first DOWN in this outage
        "fixes": [],            # epochs of every command sent (rolling cap)
        "last_fix_at": None,
        "awaiting_until": None, # verify deadline after a command
        "failures": 0,
        "paused": False,        # gave up; wait for a human / the next UP
        "incident_id": None,
        "action_id": None,
    }


def _load() -> dict:
    global _state_cache
    if _state_cache is None:
        try:
            with open(get_config().mesh_state_file) as f:
                _state_cache = {**_fresh(), **json.load(f)}
        except (OSError, ValueError):
            _state_cache = _fresh()
    return _state_cache


def _save(state: dict) -> None:
    path = get_config().mesh_state_file
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, path)


def _end_outage(state: dict) -> None:
    keep = {"fixes": state["fixes"], "last_fix_at": state["last_fix_at"]}
    state.clear()
    state.update({**_fresh(), **keep})


# --- side effects (patched in tests) ---------------------------------------

async def probe() -> bool:
    cfg = get_config()
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(cfg.mesh_node_host, cfg.mesh_node_probe_port), 3,
        )
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    return True


async def say(text: str, retry: bool = False) -> None:
    """retry=True runs in the background and keeps trying while the
    internet comes back after the LAN restart."""
    async def send() -> None:
        for attempt in range(SAY_ATTEMPTS if retry else 1):
            try:
                await get_telegram_bot().send_message(text)
                return
            except Exception:
                logger.warning(f"Telegram send failed (attempt {attempt + 1})")
                if retry:
                    await asyncio.sleep(SAY_BACKOFF)

    if not retry:
        await send()
        return
    task = asyncio.create_task(send())
    _sends.add(task)
    task.add_done_callback(_sends.discard)


async def _db_exec(sql: str, args: tuple) -> Optional[int]:
    db = await get_db()
    cursor = await db.execute(sql, args)
    await db.commit()
    return cursor.lastrowid


# --- events ---------------------------------------------------------------

def on_down(now: Optional[float] = None) -> None:
    state = _load()
    if state["down_since"] is None:
        state["down_since"] = now if now is not None else time.time()
        _save(state)
        logger.info("Mesh Node DOWN recorded")


async def _healed(state: dict, now: float, how: str) -> None:
    since = state["last_fix_at"] or now
    if state["action_id"] is not None:
        await _db_exec("UPDATE actions SET success = 1 WHERE id = ?", (state["action_id"],))
    if state["incident_id"] is not None:
        await _db_exec("UPDATE incidents SET status = 'healed' WHERE id = ?", (state["incident_id"],))
    await say(f"✅ Mesh Node กลับมาแล้ว {how} — {int(now - since)} วินาทีหลัง restart", retry=True)
    _end_outage(state)
    _save(state)


async def on_up(now: Optional[float] = None) -> None:
    now = now if now is not None else time.time()
    state = _load()
    if state["awaiting_until"] is not None:
        await _healed(state, now, "(Kuma UP)")
        return
    if state["paused"]:
        await say("🟢 Mesh Node กลับมาแล้ว — auto-heal กลับมาทำงานต่อ", retry=True)
    _end_outage(state)
    _save(state)


async def _give_up(state: dict, why: str) -> None:
    state["paused"] = True
    state["awaiting_until"] = None
    if state["incident_id"] is not None:
        await _db_exec("UPDATE incidents SET status = 'gave_up' WHERE id = ?", (state["incident_id"],))
    _save(state)
    await say(f"🆘 Mesh Node ยังล่ม — {why}\nหยุด auto-heal จนกว่า node จะกลับมา ช่วยเช็คสาย LAN/node ด้วย", retry=True)


async def _fix(state: dict, now: float) -> None:
    cfg = get_config()
    recent = [t for t in state["fixes"] if now - t < DAY]
    if len(recent) >= cfg.mesh_daily_cap:
        await _give_up(state, f"restart ครบ {cfg.mesh_daily_cap} ครั้งใน 24 ชม. แล้ว")
        return

    minutes = int((now - state["down_since"]) / 60)
    round_note = f" (รอบ {state['failures'] + 1})" if state["failures"] else ""
    await say(
        f"🔧 Mesh Node ล่ม {minutes} นาที — กำลัง restart เครือข่าย router{round_note}\n"
        f"เน็ตบ้านจะกระตุก ~1 นาที"
    )
    if state["incident_id"] is None:
        state["incident_id"] = await _db_exec(
            "INSERT INTO incidents (service_name, container_name, status, alert_message) VALUES (?, ?, ?, ?)",
            (cfg.mesh_monitor_name, "mesh-node", "down", f"ล่ม {minutes} นาที → auto-heal"),
        )
    maintenance.quiet(now + cfg.mesh_quiet_minutes * 60)
    # Saved before SSH: a crash mid-command must not resend right away
    state["fixes"] = recent + [now]
    state["last_fix_at"] = now
    _save(state)

    result = await router_client.restart_network()
    state["action_id"] = await _db_exec(
        "INSERT INTO actions (incident_id, action_type, commands_executed, result_output, success) "
        "VALUES (?, ?, ?, ?, ?)",
        (state["incident_id"], "router_restart", router_client.COMMAND, result.output, None if result.ok else 0),
    )
    if result.ok:
        state["awaiting_until"] = now + cfg.mesh_verify_minutes * 60
    else:
        state["awaiting_until"] = now  # counted as a failure on the next tick
        await say(f"❌ สั่ง router ไม่สำเร็จ: {result.output[:300]}", retry=True)
    _save(state)


async def tick(now: Optional[float] = None) -> None:
    if not enabled():
        return
    now = now if now is not None else time.time()
    cfg = get_config()
    state = _load()

    if state["awaiting_until"] is not None:
        if now < state["awaiting_until"]:
            return
        if await probe():  # Kuma UP lost, node answers anyway
            await _healed(state, now, "(เช็คเอง)")
            return
        state["failures"] += 1
        state["awaiting_until"] = None
        if state["action_id"] is not None:
            await _db_exec("UPDATE actions SET success = 0 WHERE id = ?", (state["action_id"],))
        if state["failures"] >= cfg.mesh_max_failures:
            await _give_up(state, f"restart {state['failures']} รอบแล้วไม่กลับ")
            return
        await _fix(state, now)  # retry belongs to this outage: no cooldown
        return

    if state["paused"]:
        # The UP that ends a pause can be lost (Kuma doesn't retry a 502 while
        # ops-bot restarts); without this the next outage is never handled
        if await probe():
            await on_up(now)
        return
    if state["down_since"] is None:
        return
    if now - state["down_since"] < cfg.mesh_down_minutes * 60:
        return
    if await probe():
        logger.info("Mesh Node answers at threshold — UP must have been missed; clearing")
        _end_outage(state)
        _save(state)
        return
    if state["last_fix_at"] is not None and now - state["last_fix_at"] < cfg.mesh_cooldown_minutes * 60:
        return
    await _fix(state, now)


async def _watch() -> None:
    while True:
        await asyncio.sleep(30)
        try:
            await tick()
        except Exception:
            logger.exception("Mesh heal tick failed")


def start() -> None:
    global _task
    if enabled():
        _task = asyncio.create_task(_watch())


async def stop() -> None:
    if _task is not None:
        _task.cancel()
