from app.models import (
    article_exists, insert_article, update_article_summary,
    get_articles, get_article, get_article_count, get_last_fetch_time,
    get_source_counts, upsert_price, get_prices,
    insert_digest_log, get_digest_history, get_recent_articles_for_digest,
)


def test_article_not_exists_initially(db):
    assert not article_exists(db, "abc123")


def test_insert_and_exists(db, sample_article):
    insert_article(db, sample_article)
    assert article_exists(db, "abc123")


def test_insert_idempotent(db, sample_article):
    insert_article(db, sample_article)
    insert_article(db, sample_article)  # should not raise
    assert get_article_count(db) == 1


def test_update_summary(db, sample_article):
    insert_article(db, sample_article)
    update_article_summary(db, "abc123", "สรุปภาษาไทย")
    row = get_article(db, "abc123")
    assert row["summary_th"] == "สรุปภาษาไทย"


def test_get_articles_filter_source(db, sample_article):
    insert_article(db, sample_article)
    results = get_articles(db, source="techcrunch_ai")
    assert len(results) == 1
    results_other = get_articles(db, source="gsmarena")
    assert len(results_other) == 0


def test_get_article_returns_none_for_missing(db):
    assert get_article(db, "nope") is None


def test_get_article_count(db, sample_article):
    assert get_article_count(db) == 0
    insert_article(db, sample_article)
    assert get_article_count(db) == 1


def test_get_last_fetch_time_empty(db):
    assert get_last_fetch_time(db) is None


def test_get_source_counts(db, sample_article):
    insert_article(db, sample_article)
    counts = get_source_counts(db, hours=9999)
    assert any(c["source"] == "techcrunch_ai" and c["count"] == 1 for c in counts)


def test_upsert_price(db):
    upsert_price(db, {
        "model_id": "openai/gpt-4o", "provider": "openai", "name": "GPT-4o",
        "prompt_price": 5.0, "complete_price": 15.0, "context_length": 128000,
        "updated_at": "2026-05-23T00:00:00",
    })
    prices = get_prices(db)
    assert len(prices) == 1
    assert prices[0]["model_id"] == "openai/gpt-4o"


def test_upsert_price_updates_existing(db):
    base = {"model_id": "x/y", "provider": "x", "name": "Y",
            "prompt_price": 1.0, "complete_price": 2.0,
            "context_length": 4096, "updated_at": "2026-05-23T00:00:00"}
    upsert_price(db, base)
    upsert_price(db, {**base, "prompt_price": 0.5})
    prices = get_prices(db)
    assert len(prices) == 1
    assert prices[0]["prompt_price"] == 0.5


def test_get_prices_filter_provider(db):
    for p, mid in [("openai", "openai/gpt-4o"), ("anthropic", "anthropic/claude-3")]:
        upsert_price(db, {"model_id": mid, "provider": p, "name": mid,
                          "prompt_price": 1.0, "complete_price": 2.0,
                          "context_length": 4096, "updated_at": "2026-05-23T00:00:00"})
    assert len(get_prices(db, provider="openai")) == 1
    assert len(get_prices(db)) == 2


def test_insert_and_get_digest_log(db, sample_article):
    insert_article(db, sample_article)
    insert_digest_log(db, "2026-05-23T07:00:00", ["abc123"], "line,telegram")
    history = get_digest_history(db)
    assert len(history) == 1
    assert history[0]["article_ids"] == ["abc123"]
    assert history[0]["channels"] == "line,telegram"


def test_get_recent_articles_no_summary(db, sample_article):
    insert_article(db, sample_article)
    # summary_th is NULL — should not appear in digest
    results = get_recent_articles_for_digest(db, hours=9999, limit=10)
    assert results == []


def test_get_recent_articles_with_summary(db, sample_article):
    insert_article(db, sample_article)
    update_article_summary(db, "abc123", "สรุปทดสอบ")
    results = get_recent_articles_for_digest(db, hours=9999, limit=10)
    assert len(results) == 1
    assert results[0]["id"] == "abc123"
    assert results[0]["summary_th"] == "สรุปทดสอบ"


def test_get_recent_articles_respects_limit(db):
    for i in range(5):
        art = {
            "id": f"id{i}", "source": "techcrunch_ai", "title": f"Title {i}",
            "url": f"https://example.com/{i}", "published": "2026-05-23T07:00:00",
            "fetched_at": "2026-05-23T07:01:00",
        }
        insert_article(db, art)
        update_article_summary(db, f"id{i}", "สรุป")
    results = get_recent_articles_for_digest(db, hours=9999, limit=3)
    assert len(results) == 3
