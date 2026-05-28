# Secretary Query Service — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Validate, test, commit, and deploy the `secretary-query` FastAPI RAG service.

**Architecture:** All 6 service files already exist in `secretary/query/` (untracked). This plan adds a pytest suite, commits the full service, updates stack notes, and verifies the deploy on the NAS.

**Tech Stack:** Python 3.12, FastAPI, FlagEmbedding BGE-M3, Qdrant hybrid search (RRF), Cohere rerank (optional), pluggable LLM (anthropic/openrouter/norus), Docker.

---

## File Map

| Path | Status | Role |
|---|---|---|
| `secretary/query/main.py` | exists | FastAPI app, lifespan, all endpoints |
| `secretary/query/llm_client.py` | exists | LLM provider wrapper |
| `secretary/query/requirements.txt` | exists | Runtime deps |
| `secretary/query/Dockerfile` | exists | Container build |
| `secretary/query/.env.example` | exists (fixed) | Env var template |
| `secretary/query/README.md` | exists (fixed) | Docs |
| `secretary/query/tests/__init__.py` | **create** | Package marker |
| `secretary/query/tests/conftest.py` | **create** | Fixtures + sys.modules mocks |
| `secretary/query/tests/test_llm_client.py` | **create** | LLM provider unit tests |
| `secretary/query/tests/test_main.py` | **create** | Endpoint integration tests |
| `secretary/query/pytest.ini` | **create** | pytest config (asyncio_mode=auto) |
| `secretary/query/requirements-dev.txt` | **create** | Dev-only test deps |

---

## Task 1: Test infrastructure

**Files:**
- Create: `secretary/query/pytest.ini`
- Create: `secretary/query/requirements-dev.txt`
- Create: `secretary/query/tests/__init__.py`
- Create: `secretary/query/tests/conftest.py`

- [ ] **Step 1: Create pytest.ini**

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
```

Save to `secretary/query/pytest.ini`.

- [ ] **Step 2: Create requirements-dev.txt**

```
pytest>=8.0.0
pytest-asyncio>=0.23.0
httpx>=0.27.0
```

Save to `secretary/query/requirements-dev.txt`.

- [ ] **Step 3: Create tests/__init__.py**

Empty file. Save to `secretary/query/tests/__init__.py`.

- [ ] **Step 4: Create tests/conftest.py**

`FlagEmbedding` and `torch` are multi-GB dependencies that should not load in unit tests. We stub them at the `sys.modules` level so `from FlagEmbedding import BGEM3FlagModel` succeeds without downloading anything.

```python
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
    return qdrant


@pytest.fixture
async def ac(monkeypatch):
    """Async test client with model + qdrant mocked out."""
    monkeypatch.delenv("COHERE_API_KEY", raising=False)

    fake_model = _make_fake_model()
    fake_qdrant = _make_fake_qdrant()

    import main
    from unittest.mock import patch
    from httpx import AsyncClient, ASGITransport

    with patch("main.BGEM3FlagModel", return_value=fake_model), \
         patch("main.AsyncQdrantClient", return_value=fake_qdrant):
        async with AsyncClient(
            transport=ASGITransport(app=main.app), base_url="http://test"
        ) as client:
            yield client, fake_qdrant, fake_model
```

- [ ] **Step 5: Install dev deps and verify collection**

```bash
cd secretary/query
pip install -r requirements-dev.txt
pip install -r requirements.txt
pytest --collect-only
```

Expected output includes:
```
collected 0 items
```
(no tests yet — just checking the collection itself doesn't error)

---

## Task 2: LLM client unit tests

**Files:**
- Create: `secretary/query/tests/test_llm_client.py`

- [ ] **Step 1: Write failing tests**

```python
# secretary/query/tests/test_llm_client.py
import importlib
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _reload(monkeypatch, provider: str):
    """Reload llm_client with the given LLM_PROVIDER env var."""
    monkeypatch.setenv("LLM_PROVIDER", provider)
    import llm_client as m
    importlib.reload(m)
    return m


@pytest.mark.asyncio
async def test_anthropic_returns_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test")
    m = _reload(monkeypatch, "anthropic")

    fake_content = MagicMock()
    fake_content.text = "hello from anthropic"
    fake_msg = MagicMock()
    fake_msg.content = [fake_content]
    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_msg)

    with patch.object(m, "_anthropic_client", fake_client):
        result = await m.get_llm_response("system", "user")

    assert result == "hello from anthropic"
    fake_client.messages.create.assert_awaited_once()
    call_kwargs = fake_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-test"
    assert call_kwargs["system"] == "system"
    assert call_kwargs["messages"] == [{"role": "user", "content": "user"}]


@pytest.mark.asyncio
async def test_openrouter_returns_text(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-test")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    m = _reload(monkeypatch, "openrouter")

    fake_choice = MagicMock()
    fake_choice.message.content = "hello from openrouter"
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(return_value=fake_resp)

    with patch.object(m, "_openai_client", fake_client):
        result = await m.get_llm_response("system", "user")

    assert result == "hello from openrouter"
    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "anthropic/claude-test"
    assert call_kwargs["messages"][0] == {"role": "system", "content": "system"}
    assert call_kwargs["messages"][1] == {"role": "user", "content": "user"}


@pytest.mark.asyncio
async def test_norus_returns_text(monkeypatch):
    monkeypatch.setenv("NORUS_API_KEY", "norus-test")
    monkeypatch.setenv("NORUS_MODEL", "norus-model-v1")
    monkeypatch.setenv("NORUS_BASE_URL", "https://api.norus.ai/v1")
    m = _reload(monkeypatch, "norus")

    fake_choice = MagicMock()
    fake_choice.message.content = "hello from norus"
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(return_value=fake_resp)

    with patch.object(m, "_openai_client", fake_client):
        result = await m.get_llm_response("system", "user")

    assert result == "hello from norus"


@pytest.mark.asyncio
async def test_unknown_provider_raises(monkeypatch):
    m = _reload(monkeypatch, "unknown-xyz")
    with pytest.raises(ValueError, match="unknown-xyz"):
        await m.get_llm_response("system", "user")
```

- [ ] **Step 2: Run tests — expect all to pass**

```bash
cd secretary/query
pytest tests/test_llm_client.py -v
```

Expected:
```
PASSED tests/test_llm_client.py::test_anthropic_returns_text
PASSED tests/test_llm_client.py::test_openrouter_returns_text
PASSED tests/test_llm_client.py::test_norus_returns_text
PASSED tests/test_llm_client.py::test_unknown_provider_raises
4 passed
```

---

## Task 3: Main endpoint tests

**Files:**
- Create: `secretary/query/tests/test_main.py`

- [ ] **Step 1: Write failing tests**

```python
# secretary/query/tests/test_main.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_hit(breadcrumb: str, text: str, url: str = "", score: float = 0.9):
    h = MagicMock()
    h.payload = {"breadcrumb": breadcrumb, "text": text, "page_url": url}
    h.score = score
    return h


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_ok(ac):
    client, fake_qdrant, _ = ac
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
    client, fake_qdrant, _ = ac
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
    client, fake_qdrant, fake_model = ac

    hits = [_make_hit("Notes > Test", "Test content", "https://notion.so/1")]
    result_obj = MagicMock()
    result_obj.points = hits
    fake_qdrant.query_points = AsyncMock(return_value=result_obj)

    with patch("main.llm_client") as mock_llm:
        mock_llm.get_llm_response = AsyncMock(return_value="42")
        resp = await client.post(
            "/query",
            json={"question": "What is the answer?", "top_k_retrieve": 5, "top_k_final": 1},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"] == "42"
    assert body["retrieval_method"] == "hybrid"
    assert len(body["sources"]) == 1
    assert body["sources"][0]["breadcrumb"] == "Notes > Test"
    assert isinstance(body["latency_ms"], int)


@pytest.mark.asyncio
async def test_query_top_k_final_slices_results(ac):
    """top_k_final=1 returns only 1 source even if Qdrant returns 3 hits."""
    client, fake_qdrant, _ = ac

    hits = [
        _make_hit("A", "text a", score=0.9),
        _make_hit("B", "text b", score=0.8),
        _make_hit("C", "text c", score=0.7),
    ]
    result_obj = MagicMock()
    result_obj.points = hits
    fake_qdrant.query_points = AsyncMock(return_value=result_obj)

    with patch("main.llm_client") as mock_llm:
        mock_llm.get_llm_response = AsyncMock(return_value="answer")
        resp = await client.post(
            "/query",
            json={"question": "q", "top_k_retrieve": 3, "top_k_final": 1},
        )

    assert resp.status_code == 200
    assert len(resp.json()["sources"]) == 1


# ---------------------------------------------------------------------------
# /query — hybrid + Cohere rerank path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_query_rerank_path(monkeypatch, ac):
    monkeypatch.setenv("COHERE_API_KEY", "co-test-key")

    client, fake_qdrant, _ = ac

    hits = [
        _make_hit("A", "text a", score=0.9),
        _make_hit("B", "text b", score=0.8),
    ]
    result_obj = MagicMock()
    result_obj.points = hits
    fake_qdrant.query_points = AsyncMock(return_value=result_obj)

    # Build fake Cohere rerank response: returns index 1 first (re-ordered)
    fake_rerank_result = MagicMock()
    fake_rerank_result.index = 1
    fake_rerank_result.relevance_score = 0.99
    fake_rerank_resp = MagicMock()
    fake_rerank_resp.results = [fake_rerank_result]

    fake_co = MagicMock()
    fake_co.rerank = AsyncMock(return_value=fake_rerank_resp)

    with patch("main.cohere") as mock_cohere, \
         patch("main.llm_client") as mock_llm, \
         patch("main.COHERE_API_KEY", "co-test-key"):
        mock_cohere.AsyncClientV2.return_value = fake_co
        mock_llm.get_llm_response = AsyncMock(return_value="reranked answer")
        resp = await client.post(
            "/query",
            json={"question": "q", "top_k_retrieve": 2, "top_k_final": 1},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["retrieval_method"] == "hybrid+rerank"
    assert body["answer"] == "reranked answer"
    # The reranked result came from index 1 ("B")
    assert body["sources"][0]["breadcrumb"] == "B"
```

- [ ] **Step 2: Run tests — expect all to pass**

```bash
cd secretary/query
pytest tests/test_main.py -v
```

Expected:
```
PASSED tests/test_main.py::test_health_ok
PASSED tests/test_main.py::test_health_qdrant_down
PASSED tests/test_main.py::test_query_hybrid_returns_answer
PASSED tests/test_main.py::test_query_top_k_final_slices_results
PASSED tests/test_main.py::test_query_rerank_path
5 passed
```

- [ ] **Step 3: Run full suite**

```bash
cd secretary/query
pytest -v
```

Expected: **9 passed**

---

## Task 4: Commit all query service files

**Files:** Everything in `secretary/query/`

- [ ] **Step 1: Stage all query files**

```bash
git -C /path/to/repo add secretary/query/
```

Verify with `git status secretary/query/` — all files should be in "new file" state.

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(secretary): add query service — FastAPI RAG on port 5065

BGE-M3 hybrid search (dense+sparse RRF), optional Cohere rerank,
pluggable LLM (anthropic/openrouter/norus), pytest suite (9 tests).

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: Update .notes

**Files:**
- Modify: `secretary/.notes/daily_log.md`
- Modify: `secretary/.notes/00_INDEX.md`

- [ ] **Step 1: Append to daily_log.md**

Append the following to `secretary/.notes/daily_log.md`:

```markdown
## 2026-05-28

### งานที่ทำ
- Review & validate secretary-query service against spec
- Fixed two gaps: removed unused `PORT` var from `.env.example`; added blocking-timeout note to README
- Added pytest suite: 9 tests covering llm_client (4 providers) + main endpoints (/health ok/down, /query hybrid, /query top_k_final slice, /query hybrid+rerank)
- Written design spec: `docs/superpowers/specs/2026-05-28-secretary-query-design.md`
- Committed all query service files

### Next Steps
1. Deploy to NAS: `/deploy`
2. On NAS: `cp secretary/query/.env.example secretary/query/.env` and fill real keys
3. `docker compose up -d --build secretary-query`
4. Smoke test: `curl http://<NAS_HOST>:15065/health`
5. First ingest: `docker compose run --rm secretary-ingest`
```

- [ ] **Step 2: Update 00_INDEX.md — add test info**

In `secretary/.notes/00_INDEX.md`, under **Gaps / TODOs**, replace:

```markdown
## Gaps / TODOs
- n8n workflow JSON not exported/committed yet
- Ollama service present in compose but no workflow uses it currently
```

with:

```markdown
## Tests
Run inside `secretary/query/`:
```bash
pip install -r requirements-dev.txt
pytest -v   # 9 tests
```
Mocks: `FlagEmbedding` + `torch` stubbed at `sys.modules` level (no model download needed).

## Gaps / TODOs
- n8n workflow JSON not exported/committed yet
- Ollama service present in compose but no workflow uses it currently
```

- [ ] **Step 3: Commit notes**

```bash
git add secretary/.notes/
git commit -m "docs(secretary): update notes for query service review session

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: NAS deployment smoke test

**Files:** None — verification only

- [ ] **Step 1: Deploy**

```bash
/deploy   # or: bash scripts/deploy.sh
```

- [ ] **Step 2: Create NAS volume dirs (first deploy only)**

```bash
ssh <NAS_USER>@<NAS_HOST> "mkdir -p /volume2/docker/secretary/{qdrant_storage,ollama_data,n8n_data,ingest_state,hf_cache}"
```

- [ ] **Step 3: Create .env on NAS (first deploy only)**

On the NAS:
```bash
cd /volume2/docker/secretary
cp query/.env.example query/.env
# Edit query/.env: fill ANTHROPIC_API_KEY (or other provider keys)
```

- [ ] **Step 4: Build and start query service**

```bash
ssh <NAS_USER>@<NAS_HOST> "cd /volume2/docker/secretary && docker compose up -d --build secretary-query"
```

- [ ] **Step 5: Smoke test /health**

Wait ~60 s for BGE-M3 to load (cached after first start), then:

```bash
curl http://<NAS_HOST>:15065/health
```

Expected (collection empty until ingest runs):
```json
{"status":"ok","qdrant_ok":true,"collection_stats":{"points_count":0}}
```

If `qdrant_ok` is false, Qdrant container may not be running — check with `docker compose ps`.

- [ ] **Step 6: First ingest**

```bash
ssh <NAS_USER>@<NAS_HOST> "cd /volume2/docker/secretary && docker compose run --rm secretary-ingest"
```

Then re-check `/health` — `points_count` should be > 0.

- [ ] **Step 7: Smoke test /query**

```bash
curl -X POST http://<NAS_HOST>:15065/query \
  -H "Content-Type: application/json" \
  -d '{"question": "สวัสดี มีข้อมูลอะไรบ้าง", "top_k_retrieve": 5, "top_k_final": 2}'
```

Expected: `{"answer": "...", "sources": [...], "retrieval_method": "hybrid", "latency_ms": ...}`

---

## Self-Review

**Spec coverage:**
- POST /query (embed → hybrid → rerank → LLM → return) → Tasks 3, 6 ✓
- GET /health → Task 3 ✓
- POST /ingest-trigger → not tested (subprocess; covered by Task 6 Step 6) ✓
- llm_client 3 providers + unknown raises → Task 2 ✓
- Dockerfile, .env.example, README → already exist, committed in Task 4 ✓
- .notes → Task 5 ✓

**Placeholder scan:** No TBD/TODO. All code blocks are complete.

**Type consistency:** `_make_hit` used in Task 3 tests matches `h.payload`/`h.score` access in `main.py:128–146`. `fake_model.encode.return_value` keys `dense_vecs`/`lexical_weights` match `main.py:90–95`. ✓
