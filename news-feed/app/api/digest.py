import os
import sqlite3
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request

from app.config import get_config
from app.deps import get_db
from app.models import get_conn, get_digest_history, get_recent_articles_for_digest, insert_digest_log, select_digest_articles
from app.notifier import send_digest

router = APIRouter(prefix="/api/digest", tags=["digest"])


@router.get("/history")
def digest_history(db: Annotated[sqlite3.Connection, Depends(get_db)]):
    return get_digest_history(db)


@router.post("/trigger")
def trigger_digest(x_admin_token: Optional[str] = Header(None)):
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected or x_admin_token != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
    from app.config import DB_PATH
    config = get_config()
    conn = get_conn(DB_PATH)
    try:
        candidates = get_recent_articles_for_digest(conn, hours=12, limit=50)
        articles = select_digest_articles(candidates, sent_ids=set())
        sent = send_digest(articles, config)
        if sent and articles:
            insert_digest_log(
                conn,
                datetime.now(timezone.utc).isoformat(),
                [a["id"] for a in articles],
                ",".join(sent),
            )
        return {"sent_to": sent, "article_count": len(articles)}
    finally:
        conn.close()


@router.post("/test")
def test_digest(request: Request):
    """Send a test digest immediately (no admin token required — protected by nginx basic auth)."""
    db_path = request.app.state.db_path
    config = get_config()
    conn = get_conn(db_path)
    try:
        # Check articles available — diagnostic info
        candidates_12h = get_recent_articles_for_digest(conn, hours=12, limit=50)
        candidates_24h = get_recent_articles_for_digest(conn, hours=24, limit=50)

        history = get_digest_history(conn, limit=20)
        sent_ids = {aid for entry in history for aid in entry["article_ids"]}
        articles_12h = select_digest_articles(candidates_12h, sent_ids)

        # Use 24h window as fallback if nothing in 12h
        articles = articles_12h or select_digest_articles(candidates_24h, sent_ids)
        used_window = "12h" if articles_12h else ("24h" if articles else "none")

        sent = send_digest(articles, config)
        if sent and articles:
            insert_digest_log(
                conn,
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                [a["id"] for a in articles],
                ",".join(sent),
            )
        return {
            "sent_to": sent,
            "article_count": len(articles),
            "window_used": used_window,
            "available_12h": len(candidates_12h),
            "available_24h": len(candidates_24h),
            "already_sent_ids": len(sent_ids),
        }
    finally:
        conn.close()
