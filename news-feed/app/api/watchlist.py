import sqlite3
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from app.deps import get_db
from app.models import get_watchlist, set_watchlist, toggle_watchlist

router = APIRouter(prefix="/api/watchlist", tags=["watchlist"])

_DbDep = Annotated[sqlite3.Connection, Depends(get_db)]


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@router.get("")
def list_watchlist(conn: _DbDep):
    return {"model_ids": get_watchlist(conn)}


@router.post("")
def replace_watchlist(body: dict, conn: _DbDep):
    model_ids = [str(m) for m in body.get("model_ids", []) if str(m).strip()]
    set_watchlist(conn, model_ids, _now())
    return {"model_ids": get_watchlist(conn)}


@router.patch("/{model_id:path}")
def toggle(model_id: str, conn: _DbDep):
    model_id = model_id.strip()
    in_watchlist = toggle_watchlist(conn, model_id, _now())
    return {"model_id": model_id, "in_watchlist": in_watchlist}
