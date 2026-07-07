"""Multi-source doujin scraper.

Shared download pipeline: fetch → parse → CBZ build → DB insert.
Each source provides its own listing/title parsers via sources/*.py.
"""

import os
import time
import uuid

import httpx

import cbz
import config
import db
from sources.doujinth import DoujintSource

HEADERS = {"User-Agent": config.USER_AGENT}


def fetch_bytes(url: str, referer: str | None = None) -> bytes:
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    with httpx.Client(headers=headers, follow_redirects=True, timeout=60) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content


def _download_title(item: dict, meta: dict, source_name: str, fetch) -> None:
    """Build CBZ in temp location, then insert DB row and move files into place."""
    tmp_cbz = os.path.join(config.LIBRARY_DIR, f".tmp-{uuid.uuid4().hex}.cbz")
    tmp_cover = tmp_cbz + ".cover.jpg"
    try:
        if not meta["image_urls"]:
            raise ValueError("no reader images found")
        images = [
            (os.path.splitext(u.split("?")[0])[1].lower() or ".jpg", fetch(u, referer=item["url"]))
            for u in meta["image_urls"]
        ]
        pages, size = cbz.build_cbz(images, tmp_cbz, tmp_cover)
        namespaced_slug = f"{source_name}-{item['slug']}"
        tid = db.add_title(
            slug=namespaced_slug, title=item["title"], tags=",".join(meta["tags"]),
            pages=pages, file_size=size, source_url=item["url"], source=source_name,
        )
        os.replace(tmp_cbz, db.cbz_path(tid))
        os.replace(tmp_cover, db.cover_path(tid))
    finally:
        for p in (tmp_cbz, tmp_cbz + ".part", tmp_cover):
            if os.path.exists(p):
                os.remove(p)


def _scrape_source(source, fetch) -> tuple[int, int, list[str]]:
    """Run a single scrape cycle for one source. Returns (found, downloaded, errors)."""
    errors: list[str] = []
    downloaded = 0
    found = 0
    try:
        listing_html = fetch(source.listing_url()).decode("utf-8", "replace")
        items = source.parse_listing(listing_html)
        known = db.known_slugs()
        fresh = [i for i in items if f"{source.name}-{i['slug']}" not in known]
        found = len(fresh)
        for item in fresh[: config.MAX_NEW_PER_CYCLE]:
            try:
                html = fetch(item["url"]).decode("utf-8", "replace")
                meta = source.parse_title_page(html)
                _download_title(item, meta, source.name, fetch)
                downloaded += 1
            except Exception as e:
                errors.append(f"{source.name}/{item['slug']}: {e}")
            time.sleep(config.REQUEST_DELAY_SECONDS)
    except Exception as e:
        errors.append(f"{source.name}/listing: {e}")
    return found, downloaded, errors


def scrape_cycle(fetch=fetch_bytes) -> dict:
    """Orchestrate a single scrape cycle across all sources."""
    sources = [DoujintSource(config.SITE_BASE_URL)]
    total_found, total_downloaded = 0, 0
    all_errors: list[str] = []
    for source in sources:
        found, downloaded, errors = _scrape_source(source, fetch)
        total_found += found
        total_downloaded += downloaded
        all_errors.extend(errors)
    db.log_scrape(total_found, total_downloaded, "; ".join(all_errors) if all_errors else None)
    return {"found": total_found, "downloaded": total_downloaded, "errors": all_errors}
