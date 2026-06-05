from fastapi import APIRouter

from app.config import get_config, update_config

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


@router.get("")
def get_schedule():
    return get_config()


@router.post("")
def post_schedule(body: dict):
    allowed_keys = {"digest_times", "enabled_sources", "summarizer_provider", "summarizer_model", "retention_days", "summarizer_fallback", "custom_sources"}
    filtered = {k: v for k, v in body.items() if k in allowed_keys}
    if "retention_days" in filtered:
        try:
            filtered["retention_days"] = max(1, int(filtered["retention_days"]))
        except (TypeError, ValueError):
            del filtered["retention_days"]
    if "summarizer_fallback" in filtered:
        valid_providers = {"anthropic", "openrouter", "mimo"}
        fb = filtered["summarizer_fallback"]
        if isinstance(fb, list):
            filtered["summarizer_fallback"] = [
                {"provider": str(e.get("provider", "anthropic")), "model": str(e.get("model", ""))}
                for e in fb
                if isinstance(e, dict) and e.get("provider") in valid_providers
            ]
        else:
            del filtered["summarizer_fallback"]
    if "custom_sources" in filtered:
        cs = filtered["custom_sources"]
        if isinstance(cs, list):
            filtered["custom_sources"] = [
                {"key": str(e.get("key", "")).strip(), "name": str(e.get("name", "")).strip(), "url": str(e.get("url", "")).strip()}
                for e in cs
                if isinstance(e, dict)
                and str(e.get("key", "")).strip()
                and str(e.get("url", "")).strip().startswith("http")
            ]
        else:
            del filtered["custom_sources"]
    return update_config(filtered)
