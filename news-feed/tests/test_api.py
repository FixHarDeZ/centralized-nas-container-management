import os
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.models import get_conn, init_db, insert_article, update_article_summary, insert_digest_log


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


def test_sent_ids_empty(client):
    r = client.get("/api/news/sent-ids")
    assert r.status_code == 200
    assert r.json()["sent_ids"] == []


def test_sent_ids_after_digest(tmp_path, monkeypatch):
    db_path = str(tmp_path / "sent_ids.db")
    app.state.db_path = db_path
    conn = get_conn(db_path)
    init_db(conn)
    insert_article(conn, {
        "id": "art01", "source": "techcrunch_ai", "title": "T",
        "url": "https://x.com/1", "published": "2026-05-23T07:00:00",
        "fetched_at": "2026-05-23T07:01:00",
    })
    insert_digest_log(conn, "2026-05-23T07:00:00", ["art01"], "line,telegram")
    conn.close()
    with TestClient(app) as c:
        r = c.get("/api/news/sent-ids")
    assert r.status_code == 200
    assert "art01" in r.json()["sent_ids"]


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


def test_patch_expiry(client):
    from app.models import get_conn, upsert_price
    conn = get_conn(app.state.db_path)
    upsert_price(conn, {
        "model_id": "openai/gpt-4o", "provider": "openai", "name": "GPT-4o",
        "prompt_price": 5.0, "complete_price": 15.0, "context_length": 128000,
        "updated_at": "2026-05-23T00:00:00",
    })
    conn.close()
    r = client.patch("/api/prices/openai/gpt-4o/expiry", json={"expires_at": "2025-12-31"})
    assert r.status_code == 200
    data = r.json()
    assert data["model_id"] == "openai/gpt-4o"
    assert data["free_expires_at"] == "2025-12-31"


def test_patch_expiry_model_not_found(client):
    r = client.patch("/api/prices/nonexistent/model/expiry", json={"expires_at": "2025-12-31"})
    assert r.status_code == 404


def test_patch_expiry_invalid_date(client):
    from app.models import get_conn, upsert_price
    conn = get_conn(app.state.db_path)
    upsert_price(conn, {
        "model_id": "openai/gpt-4o", "provider": "openai", "name": "GPT-4o",
        "prompt_price": 5.0, "complete_price": 15.0, "context_length": 128000,
        "updated_at": "2026-05-23T00:00:00",
    })
    conn.close()
    r = client.patch("/api/prices/openai/gpt-4o/expiry", json={"expires_at": "not-a-date"})
    assert r.status_code == 422


def test_clear_all_news(client):
    r = client.delete("/api/news")
    assert r.status_code == 200
    assert r.json()["deleted"] >= 1
    assert client.get("/api/health").json()["article_count"] == 0


def test_news_cleanup_removes_old(client):
    from app.models import get_conn, insert_article
    conn = get_conn(app.state.db_path)
    insert_article(conn, {
        "id": "ancient", "source": "techcrunch_ai", "title": "Ancient",
        "url": "https://example.com/ancient", "published": "2000-01-01T00:00:00Z",
        "fetched_at": "2000-01-01T00:00:00Z",
    })
    conn.close()
    r = client.post("/api/news/cleanup")
    assert r.status_code == 200
    assert r.json()["deleted"] >= 1
    assert client.get("/api/news/ancient").status_code == 404


def test_fetch_now(client, monkeypatch):
    import app.api.fetch as fetch_mod
    monkeypatch.setattr(fetch_mod, "fetch_all", lambda db_path, config: ["a", "b"])
    r = client.post("/api/fetch/now")
    assert r.status_code == 200
    assert r.json()["new_articles"] == 2


def test_post_schedule_retention(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    r = client.post("/api/schedule", json={"retention_days": 7})
    assert r.status_code == 200
    assert r.json()["retention_days"] == 7


def test_post_schedule_retention_invalid_dropped(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    r = client.post("/api/schedule", json={"retention_days": "abc"})
    assert r.status_code == 200
    assert r.json()["retention_days"] == 30  # invalid value dropped, default kept


def test_post_schedule_custom_sources_saved(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    payload = {"custom_sources": [{"key": "custom_reg", "name": "The Register", "url": "https://reg.com/feed"}]}
    r = client.post("/api/schedule", json=payload)
    assert r.status_code == 200
    cs = r.json()["custom_sources"]
    assert len(cs) == 1
    assert cs[0]["key"] == "custom_reg"
    assert cs[0]["url"] == "https://reg.com/feed"


def test_post_schedule_custom_sources_invalid_url_dropped(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    payload = {"custom_sources": [
        {"key": "custom_bad", "name": "Bad", "url": "ftp://bad.com"},  # not http
        {"key": "custom_ok", "name": "OK", "url": "https://ok.com/feed"},
    ]}
    r = client.post("/api/schedule", json=payload)
    assert r.status_code == 200
    keys = [c["key"] for c in r.json()["custom_sources"]]
    assert "custom_ok" in keys
    assert "custom_bad" not in keys


def test_post_schedule_custom_sources_not_list_dropped(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    r = client.post("/api/schedule", json={"custom_sources": "not-a-list"})
    assert r.status_code == 200
    # invalid type silently dropped — existing value preserved (empty list from env default)
    assert isinstance(r.json().get("custom_sources", []), list)


def test_schedule_post_accepts_tuning_keys(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    r = client.post("/api/schedule", json={
        "digest_window_buffer_hours": 2.0,
        "digest_size_base": 3,
        "digest_size_max": 8,
        "digest_max_per_source": 3,
    })
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["digest_window_buffer_hours"] == 2.0
    assert cfg["digest_size_base"] == 3
    assert cfg["digest_size_max"] == 8
    assert cfg["digest_max_per_source"] == 3


def test_schedule_post_rejects_out_of_range(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    r = client.post("/api/schedule", json={
        "digest_size_base": 999,        # > 20, ignored
        "digest_size_max": -5,          # < 1, ignored
        "digest_max_per_source": 0,     # < 1, ignored
        "digest_window_buffer_hours": 100.0,  # > 6, ignored
    })
    assert r.status_code == 200
    cfg = r.json()
    # All four keys should retain defaults because each value was rejected
    assert cfg["digest_size_base"] == 5
    assert cfg["digest_size_max"] == 10
    assert cfg["digest_max_per_source"] == 2
    assert cfg["digest_window_buffer_hours"] == 1.0


def test_schedule_post_rejects_max_less_than_base(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Setting base=8 alone is fine
    r = client.post("/api/schedule", json={"digest_size_base": 8})
    assert r.status_code == 200
    assert r.json()["digest_size_base"] == 8
    # But setting max=3 while base=8 is invalid → max should be ignored
    r = client.post("/api/schedule", json={"digest_size_max": 3})
    assert r.status_code == 200
    assert r.json()["digest_size_max"] == 10  # unchanged from default


def test_schedule_post_rejects_bool_for_int_keys(client, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    r = client.post("/api/schedule", json={
        "digest_size_base": True,
        "digest_max_per_source": False,
        "digest_window_buffer_hours": True,
    })
    assert r.status_code == 200
    cfg = r.json()
    # All defaults preserved — bool was rejected
    assert cfg["digest_size_base"] == 5
    assert cfg["digest_max_per_source"] == 2
    assert cfg["digest_window_buffer_hours"] == 1.0


def test_digest_test_returns_new_shape(client, monkeypatch):
    monkeypatch.setattr("app.api.digest.send_digest", lambda articles, cfg: ["line"])
    r = client.post("/api/digest/test")
    assert r.status_code == 200
    body = r.json()
    assert "window_computed_hours" in body
    assert "candidates_in_window" in body
    assert "config" in body
    assert set(body["config"].keys()) == {"size_base", "size_max", "max_per_source"}
    # Old fields are gone
    assert "available_12h" not in body
    assert "window_used" not in body
