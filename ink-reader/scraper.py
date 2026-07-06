"""doujin-th.com scraper.

Site is SMF-forum-based (verified live via NAS, 2026-07-06). There is no
server-side zip/download endpoint — the page's "Download" button only builds
a PDF client-side in the browser from the reader images already in the page.
The scraper's only path is scraping those reader-page image URLs directly
(see scrape_cycle in this file, added in Task 4). Reader images are
hotlink-protected by the CDN: a direct GET returns 403 unless a `Referer`
header pointing at the title page is sent.
"""

import os
import re
import time
import uuid
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

import cbz
import config
import db

HEADERS = {"User-Agent": config.USER_AGENT}

_TOPIC_RE = re.compile(r"topic=(\d+)")


def fetch_bytes(url: str, referer: str | None = None) -> bytes:
    headers = dict(HEADERS)
    if referer:
        headers["Referer"] = referer
    with httpx.Client(headers=headers, follow_redirects=True, timeout=60) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content


def parse_listing(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items, seen = [], set()
    for a in soup.select("a.hentai-item[href], a.doujin-item[href]"):
        url = urljoin(base_url, a["href"])
        m = _TOPIC_RE.search(url)
        if not m:
            continue
        slug = m.group(1)
        if slug in seen:
            continue
        title_attr = a.get("title", "")
        title = title_attr.split(" - ", 1)[0].strip() if title_attr else a.get_text(strip=True)
        if not title:
            continue
        seen.add(slug)
        items.append({"slug": slug, "title": title, "url": url})
    return items


def parse_title_page(html: str, base_url: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    tags = [a.get_text(strip=True) for a in soup.select("a.tag")]
    container = soup.select_one("div.col-xs-12.col-md-8") or soup
    image_urls = [
        urljoin(base_url, img["src"])
        for img in container.select("img.img-responsive[src]")
        if "/image/other/" not in img["src"]
    ]
    return {"tags": tags, "image_urls": image_urls}


def _download_title(item: dict, meta: dict, fetch) -> None:
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
        tid = db.add_title(
            slug=item["slug"], title=item["title"], tags=",".join(meta["tags"]),
            pages=pages, file_size=size, source_url=item["url"],
        )
        os.replace(tmp_cbz, db.cbz_path(tid))
        os.replace(tmp_cover, db.cover_path(tid))
    finally:
        for p in (tmp_cbz, tmp_cbz + ".part", tmp_cover):
            if os.path.exists(p):
                os.remove(p)


def scrape_cycle(fetch=fetch_bytes) -> dict:
    """Orchestrate a single scrape cycle."""
    errors: list[str] = []
    downloaded = 0
    found = 0
    try:
        listing_html = fetch(config.SITE_BASE_URL + "/").decode("utf-8", "replace")
        items = parse_listing(listing_html, config.SITE_BASE_URL)
        known = db.known_slugs()
        fresh = [i for i in items if i["slug"] not in known]
        found = len(fresh)
        for item in fresh[: config.MAX_NEW_PER_CYCLE]:
            try:
                html = fetch(item["url"]).decode("utf-8", "replace")
                meta = parse_title_page(html, config.SITE_BASE_URL)
                _download_title(item, meta, fetch)
                downloaded += 1
            except Exception as e:
                errors.append(f"{item['slug']}: {e}")
            time.sleep(config.REQUEST_DELAY_SECONDS)
    except Exception as e:
        errors.append(f"listing: {e}")
    db.log_scrape(found, downloaded, "; ".join(errors) if errors else None)
    return {"found": found, "downloaded": downloaded, "errors": errors}
