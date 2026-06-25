"""Translate a free-text Thai chore reminder into my/en/lo/km via MiMo (Xiaomi).

Copied from news-feed/app/summarizer.py::_summarize_mimo. MiMo v2.5 is a
reasoning model — keep max_tokens high or it returns empty content.
Returns None on ANY failure; callers fall back to Thai-only.
"""

import json
import logging
import os

from http_client import post as http_post

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You translate a short Thai household-chore reminder. Reply with ONLY a JSON "
    'object: {"my":..., "en":..., "lo":..., "km":...} — Burmese, English, Lao, '
    "Khmer. Keep each translation short and natural. No extra text, no markdown."
)


def translate_reminder(text: str) -> dict | None:
    api_key = os.getenv("MIMO_API_KEY", "")
    if not api_key:
        return None
    base_url = os.getenv(
        "MIMO_BASE_URL", "https://token-plan-sgp.xiaomimimo.com/v1"
    ).rstrip("/")
    model = os.getenv("MIMO_MODEL", "xiaomi/mimo-v2.5")
    try:
        resp = http_post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                # reasoning model burns ~1400 tokens thinking before output;
                # 1500 truncated the JSON mid-string. 4000 leaves ample room.
                "max_tokens": 4000,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": text},
                ],
            },
            timeout=60.0,
            retries=3,
            backoff=1.0,
        )
        resp.raise_for_status()
        content = (resp.json()["choices"][0]["message"]["content"] or "").strip()
        if not content:
            logger.warning("reminder_translate: empty content (token starvation?)")
            return None
        # MiMo may wrap JSON in a code fence; strip it down to the object.
        if content.startswith("```"):
            content = content.strip("`")
            content = content[content.find("{"): content.rfind("}") + 1]
        data = json.loads(content)
        out = {k: str(data[k]) for k in ("my", "en", "lo", "km") if k in data}
        return out if len(out) == 4 else None
    except Exception as exc:
        logger.warning("reminder_translate failed: %s", exc)
        return None
