import asyncio
import logging
import time

import notion

logger = logging.getLogger(__name__)

PAGES_TTL = 300       # 5 min page list cache
HEADER_TTL = 600      # 10 min per-page header cache
INDEX_INTERVAL = 600  # background full rebuild every 10 min


class PageCache:
    def __init__(self) -> None:
        self._token = ""
        self._pages: list[dict] = []
        self._pages_ts = 0.0
        self._headers: dict[str, str] = {}
        self._header_ts: dict[str, float] = {}
        self._task: asyncio.Task | None = None

    def init(self, token: str) -> None:
        self._token = token

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        # Warm up immediately at startup, then refresh on interval
        try:
            await self._rebuild()
        except Exception as e:
            logger.error(f"Cache initial build error: {e}")
        while True:
            await asyncio.sleep(INDEX_INTERVAL)
            try:
                await self._rebuild()
            except Exception as e:
                logger.error(f"Cache rebuild error: {e}")

    async def _rebuild(self) -> None:
        if not self._token:
            return
        pages = await notion.list_all_pages(self._token)
        headers = await asyncio.gather(
            *[notion.get_page_headers(self._token, p["id"]) for p in pages],
            return_exceptions=True,
        )
        now = time.monotonic()
        self._pages = pages
        self._pages_ts = now
        for page, h in zip(pages, headers):
            if isinstance(h, str):
                self._headers[page["id"]] = h
                self._header_ts[page["id"]] = now
        logger.info(f"Cache rebuilt: {len(self._headers)} pages indexed")

    async def get_pages(self) -> list[dict]:
        if self._pages and time.monotonic() - self._pages_ts < PAGES_TTL:
            return self._pages
        pages = await notion.list_all_pages(self._token)
        self._pages = pages
        self._pages_ts = time.monotonic()
        return pages

    async def get_header(self, page_id: str) -> str:
        now = time.monotonic()
        cached_age = now - self._header_ts.get(page_id, 0.0)
        if page_id in self._headers and cached_age < HEADER_TTL:
            return self._headers[page_id]
        h = await notion.get_page_headers(self._token, page_id)
        self._headers[page_id] = h
        self._header_ts[page_id] = time.monotonic()
        return h


cache = PageCache()
