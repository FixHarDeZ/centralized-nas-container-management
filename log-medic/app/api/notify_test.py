from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.notifier import notify

router = APIRouter(prefix="/api/notify")


@router.post("/test")
def test_notification():
    errors = notify("🧪 log-medic: test notification")
    if errors:
        raise HTTPException(status_code=502, detail={"errors": errors})
    return {"ok": True}
