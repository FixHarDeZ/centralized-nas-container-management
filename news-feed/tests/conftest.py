import sqlite3
from pathlib import Path

import pytest
from app.main import app
from app.models import get_conn, init_db, insert_article, update_article_summary
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_api.db")
    app.state.db_path = db_path
    conn = get_conn(db_path)
    init_db(conn)
    insert_article(
        conn,
        {
            "id": "test01",
            "source": "techcrunch_ai",
            "title": "Test Article",
            "url": "https://example.com/test",
            "published": "2026-05-23T07:00:00",
            "fetched_at": "2026-05-23T07:01:00",
        },
    )
    update_article_summary(conn, "test01", "สรุปทดสอบ")
    conn.close()
    with TestClient(app) as c:
        yield c


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
