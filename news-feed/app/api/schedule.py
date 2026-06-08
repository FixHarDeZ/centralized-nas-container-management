from fastapi import APIRouter

from app.config import get_config, update_config

router = APIRouter(prefix="/api/schedule", tags=["schedule"])


@router.get("")
def get_schedule():
    return get_config()


@router.post("")
def post_schedule(body: dict):
    allowed_keys = {
        "digest_times", "enabled_sources", "summarizer_provider", "summarizer_model",
        "retention_days", "summarizer_fallback", "custom_sources",
        "digest_window_buffer_hours", "digest_size_base", "digest_size_max",
        "digest_max_per_source",
    }
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

    # Range validation for the four new tuning keys.
    def _clamp_int(key: str, lo: int, hi: int) -> None:
        if key not in filtered:
            return
        try:
            v = int(filtered[key])
        except (TypeError, ValueError):
            del filtered[key]
            return
        if v < lo or v > hi:
            del filtered[key]
        else:
            filtered[key] = v

    def _clamp_float(key: str, lo: float, hi: float) -> None:
        if key not in filtered:
            return
        try:
            v = float(filtered[key])
        except (TypeError, ValueError):
            del filtered[key]
            return
        if v < lo or v > hi:
            del filtered[key]
        else:
            filtered[key] = v

    _clamp_float("digest_window_buffer_hours", 0.0, 6.0)
    _clamp_int("digest_size_base", 1, 20)
    _clamp_int("digest_size_max", 1, 20)
    _clamp_int("digest_max_per_source", 1, 5)

    # Cross-field: max must be ≥ base. Compare against the merged result so a partial update
    # (only max sent, base from existing config) is validated correctly.
    if "digest_size_max" in filtered:
        existing = get_config()
        prospective_base = filtered.get("digest_size_base", existing.get("digest_size_base", 5))
        if filtered["digest_size_max"] < int(prospective_base):
            del filtered["digest_size_max"]

    return update_config(filtered)
