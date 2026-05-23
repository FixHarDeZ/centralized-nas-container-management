import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import digest, health, news, prices, schedule
from app.config import DB_PATH, DATA_DIR
from app.models import get_conn, init_db
from app.scheduler import setup_scheduler

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Allow tests to pre-set app.state.db_path via fixture before TestClient enters
    db_path = getattr(app.state, "db_path", None) or DB_PATH
    if db_path == DB_PATH:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_conn(db_path)
    init_db(conn)
    conn.close()
    app.state.db_path = db_path

    scheduler = setup_scheduler(db_path)
    scheduler.start()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="News Feed Bot", lifespan=lifespan)

app.include_router(news.router)
app.include_router(prices.router)
app.include_router(schedule.router)
app.include_router(digest.router)
app.include_router(health.router)

_static = Path(__file__).parent / "static"
if _static.exists():
    app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")
