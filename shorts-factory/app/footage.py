"""Finds a stock clip for a Card on Pexels.

Never raises: footage is a nice-to-have, and a Card that cannot get one falls
back to the gradient background it always had.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

SEARCH_URL = "https://api.pexels.com/videos/search"
CANDIDATES = 8
MIN_SECONDS = 4


def enabled() -> bool:
    return bool(os.environ.get("PEXELS_API_KEY"))


def _best_file(video: dict) -> dict | None:
    """Prefer the smallest portrait file that is still at least 1080 wide."""
    portrait = [f for f in video.get("video_files", []) if f.get("height", 0) >= f.get("width", 1)]
    big_enough = [f for f in portrait if f.get("width", 0) >= 1080]
    pool = big_enough or portrait or video.get("video_files") or []
    return min(pool, key=lambda f: f.get("width", 0) * f.get("height", 0)) if big_enough else (
        max(pool, key=lambda f: f.get("width", 0) * f.get("height", 0)) if pool else None
    )


async def fetch(query: str, dest: Path) -> Path | None:
    """Download one portrait clip matching `query`, or return None."""
    if not enabled() or not query.strip():
        return None
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            found = await client.get(
                SEARCH_URL,
                params={
                    "query": query,
                    "orientation": "portrait",
                    "per_page": CANDIDATES,
                },
                headers={"Authorization": os.environ["PEXELS_API_KEY"]},
            )
            found.raise_for_status()
            videos = [
                v for v in found.json().get("videos", [])
                if v.get("duration", 0) >= MIN_SECONDS
            ]
            if not videos:
                logger.info("ไม่มี footage สำหรับ %r", query)
                return None

            chosen = _best_file(videos[0])
            if not chosen or not chosen.get("link"):
                return None

            async with client.stream("GET", chosen["link"]) as stream:
                stream.raise_for_status()
                with dest.open("wb") as handle:
                    async for chunk in stream.aiter_bytes():
                        handle.write(chunk)
        logger.info("footage %r → %s (%sx%s)", query, dest.name, chosen.get("width"), chosen.get("height"))
        return dest
    except Exception:
        logger.exception("ดึง footage ไม่สำเร็จ (%r) — ใช้พื้นหลัง gradient แทน", query)
        return None
