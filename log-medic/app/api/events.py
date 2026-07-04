from fastapi import APIRouter, Depends

from app import db
from app.deps import get_db

router = APIRouter(prefix="/api/events")


@router.get("")
def list_events(limit: int = 50, container: str | None = None, conn=Depends(get_db)):
    return [dict(r) for r in db.get_recent_events(conn, limit=limit, container=container)]
