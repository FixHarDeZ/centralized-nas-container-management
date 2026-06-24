from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_hit(breadcrumb: str, text: str, url: str = "", score: float = 0.9):
    h = MagicMock()
    h.payload = {"breadcrumb": breadcrumb, "text": text, "page_url": url}
    h.score = score

    def _copy(update=None):
        new = MagicMock()
        new.payload = h.payload
        new.score = (update or {}).get("score", h.score)
        return new

    h.model_copy = _copy
    return h


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_ok(ac):
    client, fake_qdrant, _, __ = ac
    info = MagicMock()
    info.points_count = 77
    fake_qdrant.get_collection = AsyncMock(return_value=info)

    resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["qdrant_ok"] is True
    assert body["collection_stats"]["points_count"] == 77


@pytest.mark.asyncio
async def test_health_qdrant_down(ac):
    client, fake_qdrant, _, __ = ac
    fake_qdrant.get_collection = AsyncMock(side_effect=Exception("timeout"))

    resp = await client.get("/health")

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "error"
    assert body["qdrant_ok"] is False
    assert body["collection_stats"]["points_count"] == 0


# ---------------------------------------------------------------------------
# /query — hybrid (no Cohere)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_hybrid_returns_answer(ac):
    client, fake_qdrant, fake_model, fake_llm = ac

    hits = [_make_hit("Notes > Test", "Test content", "https://notion.so/1")]
    mock_result = MagicMock()
    mock_result.points = hits
    fake_qdrant.query_points = AsyncMock(return_value=mock_result)
    fake_llm.get_llm_response = AsyncMock(return_value="The answer is [1]")

    resp = await client.post(
        "/query",
        json={"question": "What is the answer?", "top_k_retrieve": 5, "top_k_final": 1},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "The answer is [1]"
    assert body["retrieval_method"] == "hybrid"
    assert len(body["sources"]) == 1
    assert body["sources"][0]["breadcrumb"] == "Notes > Test"
    assert isinstance(body["latency_ms"], int)


@pytest.mark.asyncio
async def test_query_top_k_final_slices_results(ac):
    """top_k_final=1 returns only 1 source even if Qdrant returns 3 hits."""
    client, fake_qdrant, _, fake_llm = ac

    hits = [
        _make_hit("A", "text a", score=0.9),
        _make_hit("B", "text b", score=0.8),
        _make_hit("C", "text c", score=0.7),
    ]
    mock_result = MagicMock()
    mock_result.points = hits
    fake_qdrant.query_points = AsyncMock(return_value=mock_result)
    fake_llm.get_llm_response = AsyncMock(return_value="[1]")

    resp = await client.post(
        "/query",
        json={"question": "q", "top_k_retrieve": 3, "top_k_final": 1},
    )

    assert resp.status_code == 200
    assert len(resp.json()["sources"]) == 1
    assert resp.json()["sources"][0]["breadcrumb"] == "A"


# ---------------------------------------------------------------------------
# /query — hybrid + Cohere rerank path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_rerank_path(ac):
    client, fake_qdrant, _, fake_llm = ac

    hits = [
        _make_hit("A", "text a", score=0.9),
        _make_hit("B", "text b", score=0.8),
    ]
    mock_result = MagicMock()
    mock_result.points = hits
    fake_qdrant.query_points = AsyncMock(return_value=mock_result)

    # Rerank response: index 1 first (re-orders hits so "B" wins)
    fake_rerank_result = MagicMock()
    fake_rerank_result.index = 1
    fake_rerank_result.relevance_score = 0.99
    fake_rerank_resp = MagicMock()
    fake_rerank_resp.results = [fake_rerank_result]

    fake_co = MagicMock()
    fake_co.rerank = AsyncMock(return_value=fake_rerank_resp)
    fake_llm.get_llm_response = AsyncMock(return_value="reranked answer [1]")

    with (
        patch("main.cohere") as mock_cohere,
        patch("main.COHERE_API_KEY", "co-test-key"),
    ):
        mock_cohere.AsyncClientV2.return_value = fake_co
        resp = await client.post(
            "/query",
            json={"question": "q", "top_k_retrieve": 2, "top_k_final": 1},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["retrieval_method"] == "hybrid+rerank"
    assert body["answer"] == "reranked answer [1]"
    # Rerank promoted index 1 ("B") to first position
    assert body["sources"][0]["breadcrumb"] == "B"
    assert body["sources"][0]["score"] == pytest.approx(0.99)


# ---------------------------------------------------------------------------
# /nous/auth and /nous/auth/status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nous_auth_status_unauthenticated(ac):
    client, _, __, ___ = ac

    fake_manager = MagicMock()
    fake_manager.auth_status.return_value = {"authenticated": False, "expires_at": None}

    with patch("main.nous_auth") as mock_nous_auth:
        mock_nous_auth.token_manager = fake_manager
        resp = await client.get("/nous/auth/status")

    assert resp.status_code == 200
    assert resp.json() == {"authenticated": False, "expires_at": None}


@pytest.mark.asyncio
async def test_nous_auth_starts_flow(ac):
    client, _, __, ___ = ac

    fake_manager = MagicMock()
    fake_manager.start_device_flow = AsyncMock(
        return_value={
            "authenticated": False,
            "verification_uri": "https://portal.nousresearch.com/manage-subscription?user_code=TEST-1234",
            "user_code": "TEST-1234",
            "expires_in": 300,
            "message": "Open https://portal.nousresearch.com/... and enter code: TEST-1234",
        },
    )

    with patch("main.nous_auth") as mock_nous_auth:
        mock_nous_auth.token_manager = fake_manager
        resp = await client.get("/nous/auth")

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_code"] == "TEST-1234"
    assert "verification_uri" in body
    fake_manager.start_device_flow.assert_awaited_once()


@pytest.mark.asyncio
async def test_nous_auth_start_portal_error(ac):
    client, _, __, ___ = ac

    fake_manager = MagicMock()
    fake_manager.start_device_flow = AsyncMock(
        side_effect=Exception("Connection refused"),
    )

    with patch("main.nous_auth") as mock_nous_auth:
        mock_nous_auth.token_manager = fake_manager
        resp = await client.get("/nous/auth")

    assert resp.status_code == 503
    body = resp.json()
    assert "error" in body


@pytest.mark.asyncio
async def test_nous_auth_status_authenticated(ac):
    client, _, __, ___ = ac

    fake_manager = MagicMock()
    fake_manager.auth_status.return_value = {
        "authenticated": True,
        "expires_at": 1234567890,
    }

    with patch("main.nous_auth") as mock_nous_auth:
        mock_nous_auth.token_manager = fake_manager
        resp = await client.get("/nous/auth/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["authenticated"] is True
    assert body["expires_at"] == 1234567890
