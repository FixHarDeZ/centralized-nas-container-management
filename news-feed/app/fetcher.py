import hashlib
import logging
from datetime import datetime, timezone

import feedparser
import httpx
from bs4 import BeautifulSoup

from app.config import SOURCES
from app.models import article_exists, get_conn, insert_article, update_article_summary
from app.summarizer import summarize

logger = logging.getLogger(__name__)

_HEADERS = {"User-Agent": "news-feed-bot/1.0 (NAS RSS reader)"}


def _entry_url(entry) -> str:
    return entry.get("link") or entry.get("id") or ""


def _entry_published(entry) -> str:
    for field in ("published", "updated"):
        val = entry.get(field)
        if val:
            return val
    return datetime.now(timezone.utc).isoformat()


def _fetch_body(url: str) -> str:
    try:
        r = httpx.get(url, headers=_HEADERS, timeout=15, follow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style", "nav", "header", "footer"]):
            tag.decompose()
        return soup.get_text(separator=" ", strip=True)[:1500]
    except Exception as exc:
        logger.warning("body fetch failed %s: %s", url, exc)
        return ""


def fetch_all(db_path: str, config: dict) -> list[str]:
    conn = get_conn(db_path)
    new_ids: list[str] = []
    try:
        for source_key in config.get("enabled_sources", []):
            url = SOURCES.get(source_key)
            if not url:
                continue
            try:
                feed = feedparser.parse(url)
            except Exception as exc:
                logger.error("feedparser error %s: %s", source_key, exc)
                continue
            for entry in feed.entries:
                entry_url = _entry_url(entry)
                if not entry_url:
                    continue
                article_id = hashlib.sha256(entry_url.encode()).hexdigest()[:16]
                if article_exists(conn, article_id):
                    continue
                fetched_at = datetime.now(timezone.utc).isoformat()
                insert_article(conn, {
                    "id": article_id,
                    "source": source_key,
                    "title": entry.get("title", ""),
                    "url": entry_url,
                    "published": _entry_published(entry),
                    "fetched_at": fetched_at,
                })
                body = _fetch_body(entry_url)
                try:
                    summary = summarize(entry.get("title", ""), body, config)
                    update_article_summary(conn, article_id, summary)
                except Exception as exc:
                    logger.error("summarize failed %s: %s", article_id, exc)
                new_ids.append(article_id)
    finally:
        conn.close()
    return new_ids
