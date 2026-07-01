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
    "laptop": {"ratios": "16x9,16x10", "atleast": "1920x1080"},
    "pc": {"ratios": "16x9,21x9,32x9", "atleast": "2560x1440"},
}


def _build_query(query_terms: list[str]) -> str:
    """Join alias terms with OR so one request covers all aliases."""
    parts = [f'"{t}"' if " " in t else t for t in query_terms]
    return " OR ".join(parts)


def search(query_terms: list[str], purpose: str, sorting: str, page: int = 1) -> list[dict]:
    preset = PURPOSE_PRESETS[purpose]
    params = {
        "q": _build_query(query_terms),
        "categories": "111",
        "purity": "100",
        "ratios": preset["ratios"],
        "atleast": preset["atleast"],
        "sorting": sorting,
        "order": "desc",
        "page": page,
    }
    api_key = os.environ.get("WALLHAVEN_API_KEY", "")
    if api_key:
        params["apikey"] = api_key
    resp = http_client.get(BASE_URL, params=params, timeout=30.0)
    return resp.json().get("data", [])


def download_image(url: str) -> bytes:
    resp = http_client.get(url, timeout=60.0)
    return resp.content
