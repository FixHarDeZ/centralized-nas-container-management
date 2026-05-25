import logging
from datetime import datetime, timezone

import httpx

from app.models import get_conn, upsert_price

logger = logging.getLogger(__name__)

_OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"


def fetch_prices(db_path: str) -> int:
    try:
        resp = httpx.get(_OPENROUTER_MODELS_URL, timeout=30.0)
        resp.raise_for_status()
    except Exception as exc:
        logger.error("pricer fetch failed: %s", exc)
        return 0

    models = resp.json().get("data", [])
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn = get_conn(db_path)
    count = 0
    try:
        for m in models:
            model_id = m.get("id", "")
            if not model_id:
                continue
            pricing = m.get("pricing", {})
            prompt_str = pricing.get("prompt", "0") or "0"
            complete_str = pricing.get("completion", "0") or "0"
            upsert_price(conn, {
                "model_id": model_id,
                "provider": model_id.split("/")[0] if "/" in model_id else "unknown",
                "name": m.get("name", model_id),
                "prompt_price": float(prompt_str) * 1_000_000,
                "complete_price": float(complete_str) * 1_000_000,
                "context_length": m.get("context_length"),
                "updated_at": updated_at,
            })
            count += 1
    finally:
        conn.close()
    logger.info("pricer upserted %d models", count)
    return count
