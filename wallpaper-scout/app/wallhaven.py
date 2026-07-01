"""Wallhaven public API client — search + image download.

API docs: https://wallhaven.cc/help/api
No auth required; WALLHAVEN_API_KEY (if set) raises rate limits.
"""
from __future__ import annotations

import os

import app.http_client as http_client

BASE_URL = "https://wallhaven.cc/api/v1/search"

PURPOSE_PRESETS: dict[str, dict[str, str]] = {
    "mobile": {"ratios": "9x16,9x19.5,9x20", "atleast": "1080x1920"},
    "pc": {"ratios": "16x9,21x9,32x9", "atleast": "2560x1440"},
}


def _quote(term: str) -> str:
    return f'"{term}"' if " " in term else term


def search(query_terms: list[str], purpose: str, sorting: str, page: int = 1) -> list[dict]:
    """Search each alias term as its own request and merge results by id.

    Wallhaven's `q` parameter has no OR/union syntax — multiple terms in one
    query are effectively AND'd together, which reliably returns zero results
    for alias sets like ["IU", "Lee Ji-eun", ...] (no wallpaper is tagged
    with all of them at once). One request per alias, merged by wallhaven id,
    is the only way to actually widen recall across aliases.
    """
    preset = PURPOSE_PRESETS[purpose]
    api_key = os.environ.get("WALLHAVEN_API_KEY", "")
    seen: dict[str, dict] = {}
    for term in query_terms:
        params = {
            "q": _quote(term),
            "categories": "111",
            "purity": "100",
            "ratios": preset["ratios"],
            "atleast": preset["atleast"],
            "sorting": sorting,
            "order": "desc",
            "page": page,
        }
        if api_key:
            params["apikey"] = api_key
        resp = http_client.get(BASE_URL, params=params, timeout=30.0)
        for item in resp.json().get("data", []):
            seen.setdefault(item["id"], item)
    return list(seen.values())


def download_image(url: str) -> bytes:
    resp = http_client.get(url, timeout=60.0)
    return resp.content
