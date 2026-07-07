"""hentaithai.net source (Thai-translated doujin)."""

from urllib.parse import urljoin

from sources.base import Source


class HentaiThaiSource(Source):
    name = "hentaithai"

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def listing_url(self, page: int = 1) -> str:
        if page <= 1:
            return self.base_url + "/"
        return f"{self.base_url}/page-{page}"

    def parse_listing(self, html: str) -> list[dict]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        items, seen = [], set()
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if "/t" not in href:
                continue
            # Extract numeric ID from href like //HentaiThai.net/t50579
            slug = href.rstrip("/").split("/t")[-1]
            if not slug or not slug.isdigit():
                continue
            if slug in seen:
                continue
            title = a.get("title", "").split(" - ", 1)[0].strip()
            if not title:
                h3 = a.select_one("h3.font_name")
                title = h3.get_text(strip=True) if h3 else ""
            if not title:
                continue
            url = urljoin(self.base_url + "/", href).lower()
            seen.add(slug)
            items.append({"slug": slug, "title": title, "url": url})
        return items

    def parse_title_page(self, html: str) -> dict:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        tags = [
            a.get_text(strip=True)
            for a in soup.select("a.badge.badge-pill.badge-secondary")
        ]
        # Images are in the main content area, inside <p> tags with <img class="img-fluid">
        # Filter out decorative images (change-to-bw, stickers, ads, credit)
        image_urls = []
        for img in soup.select("p > img.img-fluid[src], div img.img-fluid[src]"):
            src = img.get("src", "")
            if not src:
                continue
            # Skip decorative images
            if any(skip in src for skip in (
                "/other/", "/sticker/", "/credit/", "change-to-bw",
            )):
                continue
            image_urls.append(urljoin(self.base_url + "/", src).lower())
        return {"tags": tags, "image_urls": image_urls}
