"""AI provider management with automatic Groq→OpenRouter failover.

When both GROQ_API_KEY and OPENROUTER_API_KEY are set (auto mode):
  - Groq is used as the primary provider (free tier)
  - If Groq returns a rate-limit error, OpenRouter takes over automatically
  - Groq is retried once the rate-limit window expires (parsed from the error)

When only one key is set, that provider is used exclusively.
"""
import logging
import re
import time

from openai import AsyncOpenAI, RateLimitError

logger = logging.getLogger(__name__)

_GROQ = {
    "base_url": "https://api.groq.com/openai/v1",
    "main": "llama-3.3-70b-versatile",
    "small": "llama-3.1-8b-instant",
}
_OR = {
    "base_url": "https://openrouter.ai/api/v1",
    "main": "meta-llama/llama-3.3-70b-instruct",
    "small": "meta-llama/llama-3.1-8b-instruct",
}


class _State:
    groq_blocked_until: float = 0.0


_st = _State()


def _parse_wait(error: RateLimitError) -> float:
    """Parse retry-after seconds from a Groq rate-limit error.

    Tries the retry-after header first, then parses 'Xh Ym Zs' from the message.
    Falls back to 1 hour if neither is available (conservative for daily limits).
    """
    try:
        ra = error.response.headers.get("retry-after")
        if ra:
            return max(60.0, float(ra))
    except Exception:
        pass
    total = sum(
        float(v) * {"h": 3600, "m": 60, "s": 1}[u]
        for v, u in re.findall(r"([\d.]+)\s*([hms])", str(error).lower())
    )
    return total if total > 60 else 3600.0


def _groq_ready(settings) -> bool:
    return bool(settings.GROQ_API_KEY) and time.monotonic() >= _st.groq_blocked_until


def _auto_mode(settings) -> bool:
    """True when both keys are set — enables Groq-primary + OpenRouter-fallback."""
    return bool(settings.GROQ_API_KEY) and bool(settings.OPENROUTER_API_KEY)


def _build(cfg: dict, api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(base_url=cfg["base_url"], api_key=api_key)


def get_client(settings) -> tuple[AsyncOpenAI, str, str]:
    """Return (client, main_model, small_model) for the currently active provider."""
    if _auto_mode(settings):
        cfg, key = (_GROQ, settings.GROQ_API_KEY) if _groq_ready(settings) else (_OR, settings.OPENROUTER_API_KEY)
        return _build(cfg, key), cfg["main"], cfg["small"]
    if settings.AI_PROVIDER == "openrouter" or not settings.GROQ_API_KEY:
        return _build(_OR, settings.OPENROUTER_API_KEY), _OR["main"], _OR["small"]
    return _build(_GROQ, settings.GROQ_API_KEY), _GROQ["main"], _GROQ["small"]


def on_groq_rate_limit(error: RateLimitError, settings) -> tuple[AsyncOpenAI, str, str]:
    """Record Groq as rate-limited, log the wait, return an OpenRouter client."""
    wait = _parse_wait(error)
    _st.groq_blocked_until = time.monotonic() + wait
    h, rem = divmod(int(wait), 3600)
    logger.warning(f"Groq rate-limited — switching to OpenRouter for {h}h {rem // 60}m")
    return _build(_OR, settings.OPENROUTER_API_KEY), _OR["main"], _OR["small"]


def status_text(settings) -> str:
    lines: list[str] = []
    if _auto_mode(settings):
        if _groq_ready(settings):
            lines.append("Provider: Groq (primary) ✅")
        else:
            remaining = _st.groq_blocked_until - time.monotonic()
            h, rem = divmod(int(remaining), 3600)
            lines.append(f"Provider: OpenRouter ✅ (Groq rate-limited)")
            lines.append(f"Groq resumes in: {h}h {rem // 60}m")
        lines.append("Mode: auto-failover")
    else:
        lines.append(f"Provider: {settings.AI_PROVIDER}")
        lines.append("Mode: single provider")
    lines.append(f"GROQ_API_KEY: {'set' if settings.GROQ_API_KEY else 'not set'}")
    lines.append(f"OPENROUTER_API_KEY: {'set' if settings.OPENROUTER_API_KEY else 'not set'}")
    return "\n".join(lines)
