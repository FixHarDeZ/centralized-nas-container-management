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
from sources.hentaithai import HentaiThaiSource
from sources.mikudoujin import MikuDoujinSource

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
        # Fetch multiple listing pages. Dedup slugs across pages: sources
        # without real pagination (doujinth) return the same listing every
        # page, and paginated ones can repeat items (sticky topics, listing
        # shifting between fetches) — duplicates here caused UNIQUE
        # constraint errors on insert.
        all_items = []
        seen: set[str] = set()
        for page in range(1, config.LISTING_PAGES + 1):
            try:
                listing_html = fetch(source.listing_url(page)).decode("utf-8", "replace")
                items = [i for i in source.parse_listing(listing_html)
                         if i["slug"] not in seen]
                seen.update(i["slug"] for i in items)
                all_items.extend(items)
                if not items:
                    break  # no more pages (or page was all repeats)
            except Exception:
                break  # page fetch failed, stop pagination
            time.sleep(config.REQUEST_DELAY_SECONDS)

        known = db.known_slugs()
        fresh = [i for i in all_items if f"{source.name}-{i['slug']}" not in known]
        found = len(fresh)
        for item in fresh[: config.MAX_NEW_PER_CYCLE]:
            try:
                html = fetch(item["url"]).decode("utf-8", "replace")
                meta = source.parse_title_page(html)

                # Multi-episode sources: fetch episode pages for images
                if source.needs_episode_fetch and not meta["image_urls"]:
                    episode_urls = meta.get("episode_urls", [])
                    all_images = []
                    for ep_url in episode_urls:
                        ep_html = fetch(ep_url).decode("utf-8", "replace")
                        ep_meta = source.parse_episode_page(ep_html)
                        all_images.extend(ep_meta["image_urls"])
                        time.sleep(config.REQUEST_DELAY_SECONDS)
                    meta["image_urls"] = all_images

                _download_title(item, meta, source.name, fetch)
                downloaded += 1
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    pass  # image deleted from CDN, skip silently
                else:
                    errors.append(f"{source.name}/{item['slug']}: {e}")
            except ValueError as e:
                if "no reader images" in str(e):
                    pass  # JS-rendered or empty title, skip silently
                else:
                    errors.append(f"{source.name}/{item['slug']}: {e}")
            except Exception as e:
                errors.append(f"{source.name}/{item['slug']}: {e}")
            time.sleep(config.REQUEST_DELAY_SECONDS)
    except Exception as e:
        errors.append(f"{source.name}/listing: {e}")
    return found, downloaded, errors


def scrape_cycle(fetch=fetch_bytes) -> dict:
    """Orchestrate a single scrape cycle across all sources."""
    sources = [
        DoujintSource(config.SITE_BASE_URL),
        HentaiThaiSource(config.HENTAITHAI_BASE_URL),
        MikuDoujinSource(config.MIKUDOUJIN_BASE_URL),
    ]
    total_found, total_downloaded = 0, 0
    all_errors: list[str] = []
    for source in sources:
        found, downloaded, errors = _scrape_source(source, fetch)
        total_found += found
        total_downloaded += downloaded
        all_errors.extend(errors)
    db.log_scrape(total_found, total_downloaded, "; ".join(all_errors) if all_errors else None)
    purged = db.dedupe_titles()
    return {"found": total_found, "downloaded": total_downloaded, "errors": all_errors, "duplicates_purged": len(purged)}
