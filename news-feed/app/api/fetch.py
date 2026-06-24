import os

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import get_config
from app.fetcher import fetch_all

router = APIRouter(prefix="/api/fetch", tags=["fetch"])


@router.post("/trigger")
def trigger_fetch(request: Request, x_admin_token: str | None = Header(None)):
    expected = os.getenv("ADMIN_TOKEN", "")
    if not expected or x_admin_token != expected:
        raise HTTPException(status_code=403, detail="Forbidden")
    config = get_config()
    db_path = request.app.state.db_path
    new_ids = fetch_all(db_path, config)
    return {"new_articles": len(new_ids)}


@router.post("/now")
def fetch_now(request: Request):
    """Force a fetch immediately (no admin token — protected by nginx basic auth)."""
    config = get_config()
    db_path = request.app.state.db_path
    new_ids = fetch_all(db_path, config)
    return {"new_articles": len(new_ids)}
