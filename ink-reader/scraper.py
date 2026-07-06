"""doujin-th.com scraper.

Site is SMF-forum-based (verified live via NAS, 2026-07-06). There is no
server-side zip/download endpoint — the page's "Download" button only builds
a PDF client-side in the browser from the reader images already in the page.
The scraper's only path is scraping those reader-page image URLs directly
(see scrape_cycle in this file, added in Task 4). Reader images are
hotlink-protected by the CDN: a direct GET returns 403 unless a `Referer`
header pointing at the title page is sent.
"""

import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

import config

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
