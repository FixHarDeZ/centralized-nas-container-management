"""Reddit image source via OAuth (userless app-only token).

Reddit killed its unauthenticated JSON API (403 everywhere, even with a browser
UA). This uses the client_credentials ("userless") OAuth flow: HTTP-Basic
(client_id:secret) -> bearer token -> oauth.reddit.com. No reddit username or
password is stored — the app-only token covers public reads (search), which is
all a wallpaper scraper needs.

Intended for real-person / idol topics (fan-photo subs) that booru can't cover.
Same interface as the other sources: search(...) -> [{"id","path"}] and
download_image(url) -> bytes. Returns [] (not an error) when creds are unset, so
a topic can select "reddit" before the vault keys land without crashing cycles.
"""
from __future__ import annotations

import os
import time

import app.http_client as http_client

# Reddit requires a descriptive, unique UA or it rate-limits/blocks.
_UA = "wallpaper-scout/1.0 (by /u/fixhardez)"

_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
_SEARCH_URL = "https://oauth.reddit.com/search"

# Min resolution + orientation per purpose (reddit has no server-side filter),
# same floors as booru: pc = Full HD landscape, mobile = 1080x1920 portrait.
_PRESETS = {
    "mobile": lambda w, h: h > w and w >= 1080 and h >= 1920,
    "pc": lambda w, h: w > h and w >= 1920 and h >= 1080,
    "best": lambda w, h: True,
}

# Module-level token cache — client_credentials tokens are long-lived; refetch
# only when expired (with a margin). ponytail: single-process, no lock needed —
# APScheduler runs jobs on one BackgroundScheduler thread pool; worst case is a
# rare duplicate token fetch, which is harmless.
_token: dict = {"value": None, "exp": 0.0}


def _get_token() -> str:
    now = time.time()
    if _token["value"] and now < _token["exp"]:
        return _token["value"]
    cid = os.environ.get("REDDIT_CLIENT_ID", "")
    secret = os.environ.get("REDDIT_CLIENT_SECRET", "")
    resp = http_client.post(
        _TOKEN_URL,
        data={"grant_type": "client_credentials"},
        auth=(cid, secret),
        headers={"User-Agent": _UA},
        timeout=30.0,
    )
    j = resp.json()
    _token["value"] = j["access_token"]
    _token["exp"] = now + j.get("expires_in", 3600) - 60
    return _token["value"]


def _extract(data: dict):
    """Full-resolution source image from a post's preview, if any.

    raw_json=1 on the request keeps preview URLs unescaped (no &amp;), so the
    URL is directly fetchable.
    """
    prev = data.get("preview") or {}
    imgs = prev.get("images") or []
    if not imgs:
        return None
    src = imgs[0].get("source") or {}
    url, w, h = src.get("url"), src.get("width"), src.get("height")
    if not url or not w or not h:
        return None
    return url, w, h


def search(query_terms: list[str], purpose: str, sorting: str, page: int = 1) -> list[dict]:
    """One request per alias against reddit search, merged by post id.

    `sorting` mirrors the other sources: "toplist" -> reddit `sort=top`,
    recurring cycles -> `sort=new`. ponytail: global search (not sub-restricted)
    — idol fan subs vary per idol, so a generic query is the lazy universal path;
    the resolution/orientation gate + over_18 filter cull the noise. Tighten to
    specific subreddits here if global search proves too noisy in practice.
    """
    if not (os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET")):
        return []
    try:
        token = _get_token()
    except Exception:
        return []
    sort = "top" if sorting == "toplist" else "new"
    fits = _PRESETS.get(purpose, _PRESETS["best"])
    headers = {"User-Agent": _UA, "Authorization": f"bearer {token}"}
    seen: dict[str, dict] = {}
    for term in query_terms:
        params = {
            "q": term,
            "sort": sort,
            "limit": 50,
            "type": "link",
            "include_over_18": "off",
            "t": "all",
            "raw_json": 1,
        }
        try:
            resp = http_client.get(_SEARCH_URL, params=params, headers=headers, timeout=30.0)
            children = resp.json().get("data", {}).get("children", [])
        except Exception:
            continue
        for child in children:
            data = child.get("data", {})
            if data.get("over_18"):
                continue
            img = _extract(data)
            if img is None:
                continue
            url, w, h = img
            if not fits(w, h):
                continue
            iid = f"rd:{data['id']}"
            seen.setdefault(iid, {"id": iid, "path": url})
    return list(seen.values())


def download_image(url: str) -> bytes:
    return http_client.get(url, headers={"User-Agent": _UA}, timeout=60.0).content
