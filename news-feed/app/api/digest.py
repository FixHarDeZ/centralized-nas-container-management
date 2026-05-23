import os
import sqlite3
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException

from app.config import get_config
from app.deps import get_db
from app.models import get_conn, get_digest_history, get_recent_articles_for_digest, insert_digest_log
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
        articles = get_recent_articles_for_digest(conn, hours=6, limit=5)
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
