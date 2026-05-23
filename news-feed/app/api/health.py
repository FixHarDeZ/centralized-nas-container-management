import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import get_db
from app.models import get_article_count, get_last_fetch_time

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(db: Annotated[sqlite3.Connection, Depends(get_db)]):
    return {
        "status": "ok",
        "article_count": get_article_count(db),
        "last_fetch": get_last_fetch_time(db),
    }
