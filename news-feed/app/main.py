from fastapi import FastAPI
from app.api import news, prices, schedule, digest, health

app = FastAPI()
app.include_router(news.router)
app.include_router(prices.router)
app.include_router(schedule.router)
app.include_router(digest.router)
app.include_router(health.router)
