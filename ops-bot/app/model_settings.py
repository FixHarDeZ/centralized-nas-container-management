"""Persistent model override; environment config remains the reset/default value."""
from __future__ import annotations

import re

from app.config import get_config
from app.db import get_db

MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


async def model_settings() -> dict:
    db = await get_db()
    row = await (await db.execute("SELECT value FROM settings WHERE key = 'mimo_model'")).fetchone()
    default = get_config().mimo_model
    return {"model": row[0] if row else default, "default": default,
            "source": "dashboard" if row else "environment"}


async def save_model(model: str | None) -> dict:
    if model is not None and (not isinstance(model, str) or not MODEL_ID.fullmatch(model)):
        raise ValueError("Model ID ต้องมี 1–128 ตัวอักษร ใช้ตัวอักษรอังกฤษ ตัวเลข . _ : / - เท่านั้น")
    db = await get_db()
    if model is None:
        await db.execute("DELETE FROM settings WHERE key = 'mimo_model'")
    else:
        await db.execute(
            "INSERT INTO settings (key, value) VALUES ('mimo_model', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (model,))
    await db.commit()
    return await model_settings()
