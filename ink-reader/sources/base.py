"""Abstract base class for scraper sources."""

from abc import ABC, abstractmethod


class Source(ABC):
    name: str
    base_url: str

    @abstractmethod
    def parse_listing(self, html: str) -> list[dict]:
        """Parse listing page HTML into items.

        Returns list of {"slug": str, "title": str, "url": str}.
        """

    @abstractmethod
    def parse_title_page(self, html: str) -> dict:
        """Parse title detail page HTML.

        Returns {"tags": list[str], "image_urls": list[str]}.
        """

    @abstractmethod
    def listing_url(self, page: int = 1) -> str:
        """Return the URL for the given listing page number."""
