"""miku-doujin.com source (multi-episode doujin)."""

from urllib.parse import urljoin

from sources.base import Source


class MikuDoujinSource(Source):
    name = "mikudoujin"
    needs_episode_fetch = True

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def listing_url(self, page: int = 1) -> str:
        if page <= 1:
            return self.base_url + "/"
        return f"{self.base_url}/page/{page}/"

    def parse_listing(self, html: str) -> list[dict]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        items, seen = [], set()
        for a in soup.select("a.inz-a[href]"):
            href = a["href"].rstrip("/")
            # Extract slug from URL like https://miku-doujin.com/r-vp2/
            slug = href.split("/")[-1]
            if not slug or slug in seen or slug in ("page", "category", "search"):
                continue
            title_el = a.select_one(".inz-title")
            title = title_el.get_text(strip=True) if title_el else ""
            if not title:
                continue
            url = urljoin(self.base_url + "/", href + "/")
            seen.add(slug)
            items.append({"slug": slug, "title": title, "url": url})
        return items

    def parse_title_page(self, html: str) -> dict:
        """Parse title page — extracts tags + episode URLs (no images here)."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        tags = [
            a.get_text(strip=True)
            for a in soup.select("a.badge.badge-secondary.badge-up")
        ]
        # Episode links: <a href=".../ep-<n>/">
        episode_urls = []
        for a in soup.select("td a[href]"):
            href = a.get("href", "")
            if "/ep-" in href:
                episode_urls.append(urljoin(self.base_url + "/", href))
        # Also check for single-episode (no episode list, images directly)
        image_urls = self._extract_page_images(soup)
        return {
            "tags": tags,
            "image_urls": image_urls,
            "episode_urls": episode_urls,
        }

    def parse_episode_page(self, html: str) -> dict:
        """Parse an episode page to extract reader images."""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        return {"tags": [], "image_urls": self._extract_page_images(soup)}

    def _extract_page_images(self, soup) -> list[str]:
        """Extract reader images from img elements.

        Handles two patterns:
        - img.page-img[src] — direct loading (episode pages)
        - img[data-src] with 'uploads' in data-src — lazy loading (title pages)
        """
        seen, image_urls = set(), []
        # Direct loading: img.page-img with src
        for img in soup.select("img.page-img[src]"):
            src = img.get("src", "")
            if src and src not in seen:
                seen.add(src)
                image_urls.append(urljoin(self.base_url + "/", src))
        # Lazy loading: img with data-src containing uploads
        for img in soup.select("img[data-src]"):
            data_src = img.get("data-src", "")
            if data_src and "uploads" in data_src and data_src not in seen:
                seen.add(data_src)
                image_urls.append(urljoin(self.base_url + "/", data_src))
        return image_urls
