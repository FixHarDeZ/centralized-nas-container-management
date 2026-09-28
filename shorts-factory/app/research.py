"""Web search before a Script is written, so the model has something to cite.

The model has no web access. Left alone it writes the general-knowledge
skeleton of any Topic and, where the Topic calls for numbers, invents them
(six volleyball clips 2026-08-29..31, two reached YouTube). A handful of search
results handed over as a Fact sheet, plus a validator that refuses any number
the sheet does not contain, turns "make it up" into "cite or leave it out".

The Topic goes to Tavily as typed. Asking mimo to plan queries first was the
original design; it costs another 30-90s of thinking on a model that already
takes minutes, and Tavily takes natural language anyway.

Best effort by construction: no key, a timeout or any error returns None and
the Script is written the way it always was. The one exception is a
result-shaped Topic (app/main.py), which is refused when there is nothing to
cite — that is the case the guard exists for.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from urllib.parse import unquote

import httpx

logger = logging.getLogger(__name__)

URL = "https://api.tavily.com/search"
MAX_RESULTS = 5
# Handed to a model that thinks at ~30 tokens/s; every character is latency.
MAX_SHEET_CHARS = 3000
TIMEOUT = float(os.environ.get("RESEARCH_TIMEOUT_SECONDS", "20"))

# Digits with thousands separators or a decimal point, as one number.
NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def configured() -> bool:
    return bool(os.environ.get("TAVILY_API_KEY"))


async def research(topic: str, locale: str = "th") -> dict | None:
    """`{"query", "results": [{"title", "url", "content"}]}` or None."""
    if not configured():
        return None
    body = {
        "query": topic,
        "max_results": MAX_RESULTS,
        "search_depth": "basic",
        "topic": "general",
    }
    headers = {"Authorization": f"Bearer {os.environ['TAVILY_API_KEY']}"}
    try:
        # wait_for, not httpx's timeout alone: that one is per read.
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await asyncio.wait_for(
                client.post(URL, json=body, headers=headers), TIMEOUT)
        resp.raise_for_status()
        rows = resp.json().get("results") or []
    except Exception as exc:  # best effort: a Script without facts beats none
        logger.warning("research failed for %r: %s", topic, exc)
        return None
    results = [
        {"title": str(r.get("title", ""))[:200],
         "url": str(r.get("url", "")),
         "content": str(r.get("content", "")).strip()}
        for r in rows if str(r.get("content", "")).strip()
    ]
    if not results:
        return None
    return {"query": topic, "results": results}


def fact_sheet(found: dict | None) -> str:
    """The search results as prompt text, capped at MAX_SHEET_CHARS."""
    if not found:
        return ""
    parts, used = [], 0
    for i, row in enumerate(found["results"], 1):
        block = f"[{i}] {row['title']}\n{row['content']}"
        room = MAX_SHEET_CHARS - used
        if room <= 0:
            break
        parts.append(block[:room])
        used += len(block) + 2
    return "\n\n".join(parts)


def _norm(number: str) -> str:
    return number.replace(",", "")


def unsourced_numbers(text: str, sheet: str) -> list[str]:
    """Numbers in `text` that appear nowhere in `sheet`.

    A single digit is let through: card counts and enumerations ("3 ข้อ") are
    structure, not claims, and refusing them would fail almost every Script.
    """
    known = {_norm(n) for n in NUMBER.findall(sheet)}
    return [n for n in NUMBER.findall(text)
            if len(_norm(n).split(".")[0]) > 1 and _norm(n) not in known]


def sources_line(found: dict | None, limit: int = 3) -> str:
    """The review message's 📎 line, so the human can check from the phone."""
    if not found:
        return ""
    # Decoded: a Thai slug percent-encoded runs to 600 characters on a phone.
    return "\n".join(f"📎 {unquote(r['url'])}" for r in found["results"][:limit])
