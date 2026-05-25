import sqlite3
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.deps import get_db
from app.models import get_price_updated_at, get_prices, set_free_expiry

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


class ExpiryUpdate(BaseModel):
    expires_at: Optional[str] = None


@router.patch("/{model_id:path}/expiry")
def patch_expiry(
    model_id: str,
    body: ExpiryUpdate,
    db: Annotated[sqlite3.Connection, Depends(get_db)],
):
    try:
        found = set_free_expiry(db, model_id, body.expires_at)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if not found:
        raise HTTPException(status_code=404, detail="Model not found")
    return {"model_id": model_id, "free_expires_at": body.expires_at}
