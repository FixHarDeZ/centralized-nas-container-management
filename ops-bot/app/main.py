from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.db import init_db, close_db
from app.webhook import router as webhook_router
from app.dashboard import router as dashboard_router
from app.commands import start_telegram_polling, stop_telegram_polling


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await start_telegram_polling()
    yield
    await stop_telegram_polling()
    await close_db()


app = FastAPI(title="ops-bot", lifespan=lifespan)
app.include_router(webhook_router)
app.include_router(dashboard_router)
