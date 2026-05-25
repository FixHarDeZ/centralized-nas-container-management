import sqlite3
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from app.deps import get_db
from app.models import get_article, get_articles, get_source_counts

router = APIRouter(prefix="/api/news", tags=["news"])


@router.get("/sources")
def list_source_counts(
    db: Annotated[sqlite3.Connection, Depends(get_db)],
    hours: int = Query(24, ge=1, le=168),
):
    """Return article count per source for the last N hours (default 24h)."""
    return get_source_counts(db, hours=hours)


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
