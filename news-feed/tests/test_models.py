from app.models import (
    article_exists, insert_article, update_article_summary,
    get_articles, get_article, get_article_count, get_last_fetch_time,
    get_source_counts, upsert_price, get_prices, set_free_expiry,
    insert_digest_log, get_digest_history, get_recent_articles_for_digest,
    get_sent_article_ids, select_digest_articles,
    delete_all_articles, delete_articles_older_than,
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


def test_get_sent_article_ids_empty(db):
    assert get_sent_article_ids(db) == set()


def test_get_sent_article_ids(db, sample_article):
    insert_article(db, sample_article)
    insert_digest_log(db, "2026-05-23T07:00:00", ["abc123", "xyz789"], "line,telegram")
    insert_digest_log(db, "2026-05-23T12:00:00", ["def456"], "telegram")
    result = get_sent_article_ids(db)
    assert result == {"abc123", "xyz789", "def456"}


def _make_article(id, source):
    return {"id": id, "source": source, "title": "T", "url": f"https://x.com/{id}",
            "published": "2026-05-23T07:00:00", "fetched_at": "2026-05-23T07:01:00", "summary_th": "s"}


def test_select_digest_articles_basic():
    candidates = [_make_article("a1", "tc"), _make_article("a2", "vb"), _make_article("a3", "tc")]
    result = select_digest_articles(candidates, sent_ids=set())
    assert [a["id"] for a in result] == ["a1", "a2", "a3"]


def test_select_digest_articles_skips_sent():
    candidates = [_make_article("a1", "tc"), _make_article("a2", "vb")]
    result = select_digest_articles(candidates, sent_ids={"a1"})
    assert [a["id"] for a in result] == ["a2"]


def test_select_digest_articles_quota_per_source():
    candidates = [_make_article(f"tc{i}", "techcrunch") for i in range(5)]
    result = select_digest_articles(candidates, sent_ids=set(), max_per_source=2, total=5)
    assert len(result) == 2
    assert all(a["source"] == "techcrunch" for a in result)


def test_select_digest_articles_quota_mixed():
    candidates = (
        [_make_article(f"tc{i}", "techcrunch") for i in range(3)] +
        [_make_article(f"vb{i}", "venturebeat") for i in range(3)]
    )
    result = select_digest_articles(candidates, sent_ids=set(), max_per_source=2, total=5)
    ids = [a["id"] for a in result]
    assert ids == ["tc0", "tc1", "vb0", "vb1"]


def test_select_digest_articles_respects_total():
    candidates = [_make_article(f"a{i}", f"src{i}") for i in range(10)]
    result = select_digest_articles(candidates, sent_ids=set(), total=3)
    assert len(result) == 3



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


def _insert_test_price(db, model_id="openai/gpt-4o"):
    upsert_price(db, {
        "model_id": model_id, "provider": "openai", "name": "GPT-4o",
        "prompt_price": 5.0, "complete_price": 15.0, "context_length": 128000,
        "updated_at": "2026-05-23T00:00:00",
    })


def test_set_free_expiry(db):
    _insert_test_price(db)
    assert set_free_expiry(db, "openai/gpt-4o", "2025-12-31") is True
    prices = get_prices(db)
    assert prices[0]["free_expires_at"] == "2025-12-31"


def test_set_free_expiry_clear(db):
    _insert_test_price(db)
    set_free_expiry(db, "openai/gpt-4o", "2025-12-31")
    assert set_free_expiry(db, "openai/gpt-4o", None) is True
    prices = get_prices(db)
    assert prices[0]["free_expires_at"] is None


def test_set_free_expiry_not_found(db):
    assert set_free_expiry(db, "nonexistent/model", "2025-12-31") is False


def test_set_free_expiry_invalid_date(db):
    _insert_test_price(db)
    import pytest
    with pytest.raises(ValueError, match="Invalid date format"):
        set_free_expiry(db, "openai/gpt-4o", "31-12-2025")


def test_delete_all_articles(db, sample_article):
    insert_article(db, sample_article)
    assert get_article_count(db) == 1
    deleted = delete_all_articles(db)
    assert deleted == 1
    assert get_article_count(db) == 0


def test_delete_articles_older_than(db):
    # Old article (fetched 40 days ago) and a fresh one
    insert_article(db, {
        "id": "old1", "source": "techcrunch_ai", "title": "Old",
        "url": "https://example.com/old", "published": "2026-01-01T00:00:00Z",
        "fetched_at": "2026-01-01T00:00:00Z",
    })
    insert_article(db, {
        "id": "new1", "source": "techcrunch_ai", "title": "New",
        "url": "https://example.com/new", "published": "2026-05-29T00:00:00Z",
        "fetched_at": __import__("datetime").datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    deleted = delete_articles_older_than(db, days=30)
    assert deleted == 1
    assert get_article(db, "old1") is None
    assert get_article(db, "new1") is not None


def test_upsert_price_preserves_free_expires_at(db):
    model = {"model_id": "openai/gpt-4o", "provider": "openai", "name": "GPT-4o",
             "prompt_price": 5.0, "complete_price": 15.0, "context_length": 128000,
             "updated_at": "2026-01-01T00:00:00Z"}
    upsert_price(db, model)
    set_free_expiry(db, "openai/gpt-4o", "2026-12-31")
    # upsert again with updated prices
    upsert_price(db, {**model, "prompt_price": 3.0})
    prices = get_prices(db)
    assert prices[0]["prompt_price"] == 3.0  # updated
    assert prices[0]["free_expires_at"] == "2026-12-31"  # preserved
