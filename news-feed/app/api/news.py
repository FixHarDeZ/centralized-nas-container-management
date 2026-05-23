import sqlite3
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_db
from app.models import get_article, get_articles

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("")
def list_news(
    db: Annotated[sqlite3.Connection, Depends(get_db)],
    source: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    return get_articles(db, source=source, date=date, limit=limit)


@router.get("/{article_id}")
def get_news_item(
    article_id: str,
    db: Annotated[sqlite3.Connection, Depends(get_db)],
):
    article = get_article(db, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    return article
