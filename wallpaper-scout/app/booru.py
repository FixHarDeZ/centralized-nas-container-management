"""Moebooru booru client (yande.re + konachan.net) — SFW anime/game wallpapers.

Both sites run Moebooru and share one API schema, so one client covers both.
konachan.com is Cloudflare-walled (403 "Just a moment..."); konachan.net serves
the same posts and passes with a browser User-Agent. yande.re needs no UA but a
browser UA is harmless. Only `rating:s` (safe) posts are requested.

Same interface as wallhaven: `search(...) -> [{"id", "path"}]` and
`download_image(url) -> bytes`. Image ids are namespaced (`yr:`/`kc:`) so they
can't collide with wallhaven's bare ids — or each other's numeric ids — in the
shared downloads dedup table.
"""
from __future__ import annotations

import re

import app.http_client as http_client

# (id-prefix, base_url)
_SITES = [("yr", "https://yande.re"), ("kc", "https://konachan.net")]

# konachan.net 403s an empty/curl UA; a browser UA passes. yande.re ignores it.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# Min resolution + orientation per purpose. Booru has no server-side ratio
# filter (unlike wallhaven), so we gate client-side on width/height.
# ponytail: pc floor is 1920x1080 (Full HD), not wallhaven's 2560x1440 — the
# booru corpus has far fewer 1440p+ images, so the stricter gate would shred
# most results. Raise it here if soft-on-4K bothers you.
_PRESETS = {
    "mobile": lambda w, h: h > w and w >= 1080 and h >= 1920,
    "pc": lambda w, h: w > h and w >= 1920 and h >= 1080,
    "best": lambda w, h: True,
}


def _tag(term: str) -> str:
    """Booru tags are lowercase with underscores for spaces."""
    return re.sub(r"\s+", "_", term.strip().lower())


def search(query_terms: list[str], purpose: str, sorting: str, page: int = 1) -> list[dict]:
    """One request per (site, alias), merged by namespaced id.

    `sorting` mirrors wallhaven's semantics: the initial "toplist" backfill maps
    to Moebooru `order:score` (best existing), recurring cycles map to
    `order:id` (newest first) so a static top ranking isn't re-scraped forever.
    """
    order = "order:score" if sorting == "toplist" else "order:id"
    fits = _PRESETS.get(purpose, _PRESETS["best"])
    seen: dict[str, dict] = {}
    for prefix, base in _SITES:
        for term in query_terms:
            tags = f"{_tag(term)} rating:s {order}"
            try:
                resp = http_client.get(
                    f"{base}/post.json",
                    params={"tags": tags, "limit": 40, "page": page},
                    headers={"User-Agent": _UA},
                    timeout=30.0,
                )
            except Exception:
                # One site or alias failing (Cloudflare hiccup, bad tag) must not
                # sink the rest — mirrors wallhaven's per-request resilience.
                continue
            for post in resp.json():
                url = post.get("file_url")
                w, h = post.get("width"), post.get("height")
                if not url or not w or not h or not fits(w, h):
                    continue
                iid = f"{prefix}:{post['id']}"
                seen.setdefault(iid, {"id": iid, "path": url})
    return list(seen.values())


def download_image(url: str) -> bytes:
    return http_client.get(url, headers={"User-Agent": _UA}, timeout=60.0).content
