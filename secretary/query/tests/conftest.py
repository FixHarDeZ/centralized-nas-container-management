# secretary/query/tests/conftest.py
import sys
import numpy as np
import pytest
from unittest.mock import MagicMock, AsyncMock

# Stub out heavy deps before main.py is ever imported.
# These mocks persist for the entire test session.
_flag_embedding_stub = MagicMock()
sys.modules.setdefault("FlagEmbedding", _flag_embedding_stub)
# torch is pulled in transitively; stub it too.
sys.modules.setdefault("torch", MagicMock())
sys.modules.setdefault("cohere", MagicMock())


def _make_fake_model():
    """Return a mock that mimics BGEM3FlagModel.encode output."""
    model = MagicMock()
    model.encode.return_value = {
        "dense_vecs": [np.zeros(1024, dtype=np.float32)],
        "lexical_weights": [{"42": 0.8, "99": 0.2}],
    }
    return model


def _make_fake_qdrant():
    qdrant = MagicMock()
    qdrant.close = AsyncMock()
    mock_result = MagicMock()
    mock_result.points = []
    qdrant.query_points = AsyncMock(return_value=mock_result)
    return qdrant


@pytest.fixture
async def ac(monkeypatch):
    """Async test client with model, qdrant, and llm_client mocked out."""
    monkeypatch.delenv("COHERE_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    fake_model = _make_fake_model()
    fake_qdrant = _make_fake_qdrant()

    import main
    from unittest.mock import patch
    from httpx import AsyncClient, ASGITransport

    fake_llm = MagicMock()
    fake_llm.get_llm_response = AsyncMock(return_value="mocked answer")

    with patch("main.llm_client", fake_llm):
        # ASGITransport does not fire ASGI lifespan events, so the lifespan
        # hook that normally assigns these never runs.  Assign directly so the
        # endpoints see the fakes they expect.
        main.qdrant = fake_qdrant          # /health reads module-level qdrant
        main.app.state.model = fake_model  # /query reads app.state.model
        async with AsyncClient(
            transport=ASGITransport(app=main.app), base_url="http://test"
        ) as client:
            yield client, fake_qdrant, fake_model, fake_llm
