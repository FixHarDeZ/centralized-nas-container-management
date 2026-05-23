import sqlite3
import pytest
from pathlib import Path
from app.models import get_conn, init_db


@pytest.fixture
def db(tmp_path: Path) -> sqlite3.Connection:
    conn = get_conn(str(tmp_path / "test.db"))
    init_db(conn)
    yield conn
    conn.close()


@pytest.fixture
def sample_article() -> dict:
    return {
        "id": "abc123",
        "source": "techcrunch_ai",
        "title": "AI News",
        "url": "https://example.com/article",
        "published": "2026-05-23T07:00:00",
        "fetched_at": "2026-05-23T07:01:00",
    }


@pytest.fixture
def base_config() -> dict:
    return {
        "digest_times": ["07:00", "12:00", "18:00"],
        "enabled_sources": ["techcrunch_ai", "venturebeat"],
        "summarizer_provider": "anthropic",
        "summarizer_model": "claude-sonnet-4-6",
    }
