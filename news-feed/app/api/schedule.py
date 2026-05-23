from fastapi import APIRouter

from app.config import get_config, update_config

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


@router.get("")
def get_schedule():
    return get_config()


@router.post("")
def post_schedule(body: dict):
    allowed_keys = {"digest_times", "enabled_sources", "summarizer_provider", "summarizer_model"}
    filtered = {k: v for k, v in body.items() if k in allowed_keys}
    return update_config(filtered)
