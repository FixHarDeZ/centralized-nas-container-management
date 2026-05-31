import os
import time
import logging
import httpx
import anthropic

logger = logging.getLogger(__name__)

_SYSTEM = "คุณคือผู้ช่วยสรุปข่าวเทคโนโลยีเป็นภาษาไทย กระชับ อ่านง่าย"


def _user_prompt(title: str, body: str) -> str:
    return f"สรุปบทความนี้ 2-3 ประโยค:\nTitle: {title}\nContent: {body[:1500]}"


def _with_retry(fn, retries: int = 3):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            logger.warning("summarize retry %d/%d after %ds: %s", attempt + 1, retries, wait, exc)
            time.sleep(wait)


def _summarize_anthropic(title: str, body: str, model: str) -> str:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

    def call():
        resp = client.messages.create(
            model=model,
            max_tokens=300,
            system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": _user_prompt(title, body)}],
        )
        return resp.content[0].text

    return _with_retry(call)


def _summarize_openrouter(title: str, body: str, model: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY", "")

    def call():
        resp = httpx.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "HTTP-Referer": "news-feed-nas",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 300,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": _user_prompt(title, body)},
                ],
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    return _with_retry(call)


def _summarize_mimo(title: str, body: str, model: str) -> str:
    api_key = os.getenv("MIMO_API_KEY", "")
    base_url = os.getenv("MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1").rstrip("/")

    def call():
        resp = httpx.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 300,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": _user_prompt(title, body)},
                ],
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]

    return _with_retry(call)


def summarize(title: str, body: str, config: dict) -> str:
    provider = config.get("summarizer_provider", "anthropic")
    model = config.get("summarizer_model", "claude-sonnet-4-6")
    if provider == "openrouter":
        return _summarize_openrouter(title, body, model)
    if provider == "mimo":
        return _summarize_mimo(title, body, model)
    return _summarize_anthropic(title, body, model)
