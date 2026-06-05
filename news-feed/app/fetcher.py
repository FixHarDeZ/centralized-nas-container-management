import hashlib
import logging
from datetime import datetime, timezone

import feedparser
from bs4 import BeautifulSoup

from app.config import get_all_sources
from app.models import article_exists, get_conn, insert_article, update_article_summary
from app.summarizer import summarize

logger = logging.getLogger(__name__)

_ENTRIES_PER_SOURCE = 10


def _entry_url(entry) -> str:
    return entry.get("link") or entry.get("id") or ""


_DT_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _entry_published(entry) -> str:
    """Return UTC ISO-8601 string with Z suffix, safe for new Date() in all browsers."""
    for field in ("published_parsed", "updated_parsed"):
        val = entry.get(field)
        if val:
            return datetime(*val[:6], tzinfo=timezone.utc).strftime(_DT_FMT)
    return datetime.now(timezone.utc).strftime(_DT_FMT)


def _entry_body(entry) -> str:
    """Extract text from RSS entry.summary — no HTTP fetch needed."""
    raw = entry.get("summary") or entry.get("description") or ""
    if not raw:
        return ""
    return BeautifulSoup(raw, "html.parser").get_text(separator=" ", strip=True)[:1500]


def fetch_all(db_path: str, config: dict) -> list[str]:
    conn = get_conn(db_path)
    new_ids: list[str] = []
    try:
        all_sources = get_all_sources(config)
        for source_key in config.get("enabled_sources", []):
            url = all_sources.get(source_key)
            if not url:
                continue
            try:
                feed = feedparser.parse(url)
            except Exception as exc:
                logger.error("feedparser error %s: %s", source_key, exc)
                continue
            for entry in feed.entries[:_ENTRIES_PER_SOURCE]:
                entry_url = _entry_url(entry)
                if not entry_url:
                    continue
                article_id = hashlib.sha256(entry_url.encode()).hexdigest()[:16]
                if article_exists(conn, article_id):
                    continue
                fetched_at = datetime.now(timezone.utc).strftime(_DT_FMT)
                insert_article(conn, {
                    "id": article_id,
                    "source": source_key,
                    "title": entry.get("title", ""),
                    "url": entry_url,
                    "published": _entry_published(entry),
                    "fetched_at": fetched_at,
                })
                body = _entry_body(entry)
                try:
                    summary = summarize(entry.get("title", ""), body, config)
                    update_article_summary(conn, article_id, summary)
                except Exception as exc:
                    logger.error("summarize failed %s: %s", article_id, exc)
                new_ids.append(article_id)
    finally:
        conn.close()
    return new_ids
