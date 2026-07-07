"""doujin-th.com source (SMF forum-based)."""

import re
from urllib.parse import urljoin

from sources.base import Source

_TOPIC_RE = re.compile(r"topic=(\d+)")


class DoujintSource(Source):
    name = "doujinth"

    def __init__(self, base_url: str):
        self.base_url = base_url

    def parse_listing(self, html: str) -> list[dict]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        items, seen = [], set()
        for a in soup.select("a.hentai-item[href], a.doujin-item[href]"):
            url = urljoin(self.base_url, a["href"])
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

    def parse_title_page(self, html: str) -> dict:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        tags = [a.get_text(strip=True) for a in soup.select("a.tag")]
        container = soup.select_one("div.col-xs-12.col-md-8") or soup
        image_urls = [
            urljoin(self.base_url, img["src"])
            for img in container.select("img.img-responsive[src]")
            if "/image/other/" not in img["src"]
        ]
        return {"tags": tags, "image_urls": image_urls}

    def listing_url(self, page: int = 1) -> str:
        return self.base_url + "/"
