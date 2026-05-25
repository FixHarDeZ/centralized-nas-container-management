import sqlite3
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, Query

from app.deps import get_db
from app.models import get_price_updated_at, get_prices

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.get("/updated")
def price_updated_at(db: Annotated[sqlite3.Connection, Depends(get_db)]):
    return {"updated_at": get_price_updated_at(db)}


@router.get("")
def list_prices(
    db: Annotated[sqlite3.Connection, Depends(get_db)],
    provider: Optional[str] = Query(None),
    sort: Literal["prompt_asc", "prompt_desc", "complete_asc", "combined_asc"] = Query("combined_asc"),
):
    return get_prices(db, provider=provider, sort=sort)
