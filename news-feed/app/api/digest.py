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


def _run_digest(db_path: str, *, log_when_sent: bool = True) -> dict:
    """Shared digest execution path for /trigger and /test."""
    from zoneinfo import ZoneInfo
    from app.scheduler import _compute_digest_window

    config = get_config()
    conn = get_conn(db_path)
    try:
        bkk = ZoneInfo("Asia/Bangkok")
        window_hours = _compute_digest_window(
            datetime.now(bkk),
            config.get("digest_times", ["07:00", "12:00", "18:00"]),
            buffer_hours=float(config.get("digest_window_buffer_hours", 1.0)),
        )
        history = get_digest_history(conn, limit=20)
        sent_ids = {aid for entry in history for aid in entry["article_ids"]}
        candidates = get_recent_articles_for_digest(conn, hours=window_hours, limit=100)
        base = int(float(config.get("digest_size_base", 5)))
        size_max = int(float(config.get("digest_size_max", 10)))
        max_per_source = int(float(config.get("digest_max_per_source", 2)))
        articles = select_digest_articles(
            candidates, sent_ids,
            base=base,
            extra_max=max(0, size_max - base),
            max_per_source=max_per_source,
        )
        sent = send_digest(articles, config)
        if log_when_sent and sent and articles:
            insert_digest_log(
                conn,
                datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                [a["id"] for a in articles],
                ",".join(sent),
            )
        return {
            "sent_to": sent,
            "article_count": len(articles),
            "window_computed_hours": round(window_hours, 2),
            "candidates_in_window": len(candidates),
            "already_sent_ids": len(sent_ids),
            "config": {
                "size_base": base,
                "size_max": size_max,
                "max_per_source": max_per_source,
            },
        }
    finally:
        conn.close()


@router.post("/trigger")
def trigger_digest(x_admin_token: Optional[str] = Header(None)):
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected or x_admin_token != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
    from app.config import DB_PATH
    return _run_digest(DB_PATH)


@router.post("/test")
def test_digest(request: Request):
    """Send a test digest immediately (no admin token required — protected by nginx basic auth)."""
    return _run_digest(request.app.state.db_path)
