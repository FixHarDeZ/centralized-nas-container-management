"""
LLM-based query expansion for wallpaper search aliases.

Expands user search topics (e.g., "IU") into synonyms
(romanization, translations, well-known alternate names) to widen
search recall on image sites. Follows news-feed/app/summarizer.py's dispatch shape, but
MiMo primary + anthropic fallback (same vault keys, reversed
priority order). No vision/image analysis here — only turns topic
string into small list of alternate search terms (romanization,
alt names) to widen Wallhaven recall.
"""

from __future__ import annotations

import json
import logging
import os
import time

import anthropic

import app.http_client as http_client

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You expand wallpaper-search topic into alternate search terms "
    "(romanization, translations, well-known alternate names) to widen "
    "search recall on image site. Respond ONLY with JSON array of "
    "strings, at most 5 items, including original term."
)


def _anthropic_retry(fn, retries: int = 3):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            if attempt == retries - 1:
                raise
            wait = 2**attempt
            logger.warning("anthropic retry %d/%d %ds: %s", attempt + 1, retries, wait, exc)
            time.sleep(wait)


def _expand_anthropic(topic: str, model: str) -> str:
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY", ""))

    def call():
        resp = client.messages.create(
            model=model,
            max_tokens=200,
            system=_SYSTEM,
            messages=[{"role": "user", "content": topic}],
        )
        return resp.content[0].text

    return _anthropic_retry(call)


def _expand_mimo(topic: str, model: str) -> str:
    api_key = os.getenv("MIMO_API_KEY", "")
    base_url = os.getenv("MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1").rstrip("/")

    resp = http_client.post(
        f"{base_url}/chat/completions",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": topic},
            ],
            "temperature": 0.7,
        },
        headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _dispatch(provider: str, topic: str, model: str) -> str:
    if provider == "mimo":
        return _expand_mimo(topic, model)
    elif provider == "anthropic":
        return _expand_anthropic(topic, model)
    else:
        raise ValueError(f"Unknown provider: {provider}")


def _parse(text: str, topic: str) -> list[str]:
    try:
        data = json.loads(text)
        if isinstance(data, list) and data and all(isinstance(x, str) for x in data):
            return data[:5]
    except (json.JSONDecodeError, TypeError):
        pass
    return [topic]


def expand_query(topic: str) -> list[str]:
    chain = [
        {
            "provider": os.getenv("LLM_PROVIDER", "mimo"),
            "model": os.getenv("LLM_MODEL", "xiaomi/mimo-v2.5"),
        },
        {
            "provider": os.getenv("LLM_FALLBACK_PROVIDER", "anthropic"),
            "model": os.getenv("LLM_FALLBACK_MODEL", "claude-sonnet-4-6"),
        },
    ]
    for slot in chain:
        try:
            text = _dispatch(slot["provider"], topic, slot["model"])
            return _parse(text, topic)
        except Exception as exc:
            logger.warning("expand_query failed provider=%s: %s", slot["provider"], exc)
    return [topic]
