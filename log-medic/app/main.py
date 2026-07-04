from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import docker
from fastapi import FastAPI

from app import config_seed, db, scheduler as scheduler_module
from app.api import containers, events, health, watcher_control
from app.watcher import HOT_RELOAD_INTERVAL_SECONDS, WatcherManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.yaml")


async def _hot_reload_loop(app: FastAPI) -> None:
    while True:
        conn = db.get_conn(app.state.db_path)
        try:
            await app.state.watcher_manager.reload(conn)
        except Exception:
            logger.exception("watcher hot-reload failed")
        finally:
            conn.close()
        await asyncio.sleep(HOT_RELOAD_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db_path = getattr(app.state, "db_path", None) or db.DB_PATH
    conn = db.get_conn(db_path)
    try:
        db.init_db(conn)
        config_seed.seed_from_config_if_empty(conn, CONFIG_PATH)
    finally:
        conn.close()
    app.state.db_path = db_path

    if not hasattr(app.state, "docker_client"):
        app.state.docker_client = docker.from_env()
    app.state.watcher_manager = WatcherManager(docker_client=app.state.docker_client)

    reload_task = asyncio.create_task(_hot_reload_loop(app))
    sched = scheduler_module.setup_scheduler(db_path)

    yield

    reload_task.cancel()
    sched.shutdown(wait=False)


app = FastAPI(title="log-medic", lifespan=lifespan)
app.include_router(health.router)
app.include_router(containers.router)
app.include_router(events.router)
app.include_router(watcher_control.router)

from pathlib import Path

from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

_static = Path(__file__).parent / "static"
if _static.exists():
    app.mount("/static", StaticFiles(directory=str(_static)), name="static")

    @app.get("/")
    async def _index() -> FileResponse:
        return FileResponse(str(_static / "index.html"))
