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


async def _search(query: str, **extra) -> list[dict] | None:
    """One Tavily call. Rows with content only; None on any failure."""
    body = {
        "query": query,
        "max_results": MAX_RESULTS,
        "search_depth": "basic",
        "topic": "general",
        **extra,
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
        logger.warning("research failed for %r: %s", query, exc)
        return None
    return [
        {"title": str(r.get("title", ""))[:200],
         "url": str(r.get("url", "")),
         "content": str(r.get("content", "")).strip(),
         "published": str(r.get("published_date") or "")}
        for r in rows if str(r.get("content", "")).strip()
    ]


async def research(topic: str, locale: str = "th") -> dict | None:
    """`{"query", "results": [{"title", "url", "content"}]}` or None."""
    if not configured():
        return None
    results = await _search(topic)
    if not results:
        return None
    return {"query": topic, "results": results}


# A trend Topic is about what just happened. `topic=general` with a
# `time_range` still returned a 2011 Mubarak article and spam for Thai terms
# (probed 2026-11-23); `topic=news` + `days` comes back dated, and a row
# without a date is not evidence of anything recent.
RECENT_DAYS = int(os.environ.get("RESEARCH_RECENT_DAYS", "7"))


def _mentions(row: dict, query: str) -> bool:
    """Whether a result names what was searched for. Tavily matches on meaning:
    "คนโง่รักเขลา" (series "Fool in Love") came back as a BBC story about an
    online predator. Words under 3 characters ("6" in "GTA 6") prove nothing."""
    words = [w.casefold() for w in query.split() if len(w) >= 3]
    if not words:
        return True
    text = f"{row.get('title', '')} {row.get('content', '')}".casefold()
    return any(word in text for word in words)


async def recent(queries: list[str], locale: str = "th") -> dict | None:
    """This week's news for the first query that has any, or None.

    Queries go in order — the picker's short search term first, then the raw
    trend, then the Topic — because a long video title or a whole sentence
    finds far less news than "GTA 6".
    """
    if not configured():
        return None
    for query in dict.fromkeys(q.strip() for q in queries if q and q.strip()):
        rows = await _search(query, topic="news", days=RECENT_DAYS) or []
        dated = [r for r in rows if r.get("published") and _mentions(r, query)]
        if dated:
            return {"query": query, "results": dated, "recent": True}
    return None


def fact_sheet(found: dict | None) -> str:
    """The search results as prompt text, capped at MAX_SHEET_CHARS."""
    if not found:
        return ""
    parts, used = [], 0
    for i, row in enumerate(found["results"], 1):
        date = f" ({row['published'][:16]})" if row.get("published") else ""
        block = f"[{i}] {row['title']}{date}\n{row['content']}"
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
