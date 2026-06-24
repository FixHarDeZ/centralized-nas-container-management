from app.models import get_price_history, snapshot_all_prices, upsert_price


def _seed_prices(conn):
    upsert_price(
        conn,
        {
            "model_id": "openai/gpt-4o",
            "provider": "openai",
            "name": "GPT-4o",
            "prompt_price": 2.5,
            "complete_price": 10.0,
            "context_length": 128000,
            "updated_at": "2026-06-05T00:00:00Z",
        },
    )
    upsert_price(
        conn,
        {
            "model_id": "anthropic/claude-3",
            "provider": "anthropic",
            "name": "Claude 3",
            "prompt_price": 3.0,
            "complete_price": 15.0,
            "context_length": 200000,
            "updated_at": "2026-06-05T00:00:00Z",
        },
    )


# ── model layer ──────────────────────────────────────────────────────────────


def test_snapshot_all_prices_returns_count(db):
    _seed_prices(db)
    count = snapshot_all_prices(db, "2026-06-05")
    assert count == 2


def test_get_price_history_returns_entries(db):
    _seed_prices(db)
    snapshot_all_prices(db, "2026-06-05")
    history = get_price_history(db, "openai/gpt-4o")
    assert len(history) == 1
    assert history[0]["date"] == "2026-06-05"
    assert history[0]["prompt_price"] == 2.5
    assert history[0]["complete_price"] == 10.0


def test_snapshot_idempotent_same_day(db):
    _seed_prices(db)
    snapshot_all_prices(db, "2026-06-05")
    snapshot_all_prices(
        db,
        "2026-06-05",
    )  # second call → INSERT OR REPLACE, still 1 row
    history = get_price_history(db, "openai/gpt-4o")
    assert len(history) == 1


def test_snapshot_multiple_days(db):
    _seed_prices(db)
    snapshot_all_prices(db, "2026-06-04")
    snapshot_all_prices(db, "2026-06-05")
    history = get_price_history(db, "openai/gpt-4o")
    assert len(history) == 2
    assert history[0]["date"] == "2026-06-04"  # chronological
    assert history[1]["date"] == "2026-06-05"


def test_get_price_history_days_limit(db):
    _seed_prices(db)
    for day in range(1, 35):
        snapshot_all_prices(db, f"2026-05-{day:02d}")
    history = get_price_history(db, "openai/gpt-4o", days=30)
    assert len(history) == 30


def test_get_price_history_unknown_model(db):
    assert get_price_history(db, "unknown/model") == []


# ── API layer ────────────────────────────────────────────────────────────────


def test_api_history_empty(client):
    r = client.get("/api/prices/openai%2Fgpt-4o/history")
    assert r.status_code == 200
    assert r.json() == []


def test_api_history_invalid_days(client):
    r = client.get("/api/prices/openai%2Fgpt-4o/history?days=999")
    assert r.status_code == 422
