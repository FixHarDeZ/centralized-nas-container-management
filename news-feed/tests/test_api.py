import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models import get_conn, init_db, insert_article, update_article_summary


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "test_api.db")
    app.state.db_path = db_path
    conn = get_conn(db_path)
    init_db(conn)
    insert_article(conn, {
        "id": "test01",
        "source": "techcrunch_ai",
        "title": "Test Article",
        "url": "https://example.com/test",
        "published": "2026-05-23T07:00:00",
        "fetched_at": "2026-05-23T07:01:00",
    })
    update_article_summary(conn, "test01", "สรุปทดสอบ")
    conn.close()
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["article_count"] == 1


def test_list_news(client):
    r = client.get("/api/news")
    assert r.status_code == 200
    articles = r.json()
    assert len(articles) == 1
    assert articles[0]["id"] == "test01"


def test_get_news_item(client):
    r = client.get("/api/news/test01")
    assert r.status_code == 200
    assert r.json()["summary_th"] == "สรุปทดสอบ"


def test_get_news_item_404(client):
    r = client.get("/api/news/nope")
    assert r.status_code == 404


def test_get_schedule(client):
    r = client.get("/api/schedule")
    assert r.status_code == 200
    assert "digest_times" in r.json()


def test_post_schedule(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    r = client.post("/api/schedule", json={
        "summarizer_provider": "openrouter",
        "summarizer_model": "deepseek/deepseek-chat"
    })
    assert r.status_code == 200
    assert r.json()["summarizer_provider"] == "openrouter"


def test_digest_trigger_forbidden(client):
    r = client.post("/api/digest/trigger")
    assert r.status_code == 403


def test_digest_trigger_with_token(client, tmp_path, monkeypatch):
    monkeypatch.setenv("ADMIN_TOKEN", "secret")
    # Point DB_PATH to the same test DB used by the client fixture
    import app.config as _cfg
    monkeypatch.setattr(_cfg, "DB_PATH", app.state.db_path)
    r = client.post("/api/digest/trigger", headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    assert "sent_to" in r.json()


def test_digest_history(client):
    r = client.get("/api/digest/history")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_list_prices(client):
    r = client.get("/api/prices")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
