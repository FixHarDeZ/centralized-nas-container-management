from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.db import init_db, close_db
from app.webhook import router as webhook_router
from app.dashboard import router as dashboard_router
from app.commands import start_telegram_polling, stop_telegram_polling
from app.orchestrator import handle_incident
from app import maintenance, mesh_heal
from app.telegram_bot import get_telegram_bot


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await start_telegram_polling()
    maintenance.start(handle_incident, lambda text: get_telegram_bot().send_message(text))
    mesh_heal.start()
    yield
    await mesh_heal.stop()
    await maintenance.stop()
    await stop_telegram_polling()
    await close_db()


app = FastAPI(title="ops-bot", lifespan=lifespan)
app.include_router(webhook_router)
app.include_router(dashboard_router)

app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
