# Secretary Query Service — Design Spec

**Date:** 2026-05-28  
**Stack:** `secretary/query/`  
**Port:** 5065 (internal) / 15065 (reverse proxy)

---

## Purpose

FastAPI service that answers natural-language questions about personal notes stored in Qdrant. Sits alongside the ingest service (`secretary/ingest/`) in the `secretary` Docker Compose stack.

---

## Architecture

```
Telegram / n8n
      │
      ▼ POST /query
secretary-query (FastAPI, port 5065)
      │
      ├── BGEM3FlagModel (BGE-M3, loaded once at startup)
      │       └── dense vec (1024d) + sparse (lexical weights)
      │
      ├── AsyncQdrantClient → qdrant:6333
      │       collection: secretary_notes
      │       hybrid prefetch (dense + sparse) → RRF fusion
      │
      ├── [optional] Cohere rerank (rerank-multilingual-v3.0)
      │
      └── LLM (anthropic | openrouter | norus) → answer
```

Single container. No Ollama dependency. HuggingFace model cached in shared `hf_cache` volume with the ingest service.

---

## Files

| File | Role |
|---|---|
| `main.py` | FastAPI app, lifespan (model load), all endpoints |
| `llm_client.py` | Provider-switching LLM wrapper (anthropic / openrouter / norus) |
| `requirements.txt` | Python deps |
| `Dockerfile` | python:3.12-slim, CPU-only torch, healthcheck |
| `.env.example` | All required env vars with placeholder values |
| `README.md` | Endpoints, env var reference, local dev instructions |

---

## Endpoints

### `POST /query`

```json
// request
{ "question": "...", "top_k_retrieve": 20, "top_k_final": 3, "session_id": "" }

// response
{
  "answer": "...",
  "sources": [{ "breadcrumb": "...", "page_url": "...", "score": 0.92 }],
  "retrieval_method": "hybrid+rerank" | "hybrid",
  "latency_ms": 1234
}
```

Pipeline:
1. Embed question → dense + sparse (single `BGEM3FlagModel.encode` call, in thread to avoid blocking event loop)
2. Qdrant hybrid search: `prefetch` dense (limit=top_k_retrieve) + sparse (limit=top_k_retrieve) → `FusionQuery(RRF)` → limit=top_k_retrieve
3. If `COHERE_API_KEY` set → rerank via `AsyncClientV2.rerank` → top_k_final results; else slice to top_k_final
4. Build numbered context blocks `[1] breadcrumb\ntext`
5. Call `llm_client.get_llm_response(SYSTEM_PROMPT, user_msg)` → answer
6. Return answer + sources + retrieval_method + latency_ms

### `GET /health`

```json
{ "status": "ok", "qdrant_ok": true, "collection_stats": { "points_count": 1234 } }
```

Calls `qdrant.get_collection(COLLECTION_NAME)`. Returns `status: "error"` on any exception.

### `POST /ingest-trigger`

Runs `python /ingest/ingest.py` as subprocess. Blocks until exit. Returns:

```json
{ "status": "done" | "error", "summary": "<stdout+stderr>" }
```

> **Caller timeout:** this can take several minutes on first run. Use a client timeout of at least 10 minutes.

---

## LLM System Prompt

```
You are a personal secretary assistant for the user.
Answer based ONLY on the numbered context blocks provided.
Rules:
- Respond in the SAME LANGUAGE as the question (Thai or English)
- Use ONLY the provided context, no outside knowledge
- If context is insufficient, say:
    Thai: "ไม่พบข้อมูลในบันทึก ลองเพิ่มหัวข้อ: <suggested topic>"
    English: "Not found in notes. Consider adding: <suggested topic>"
- Cite sources inline with [1] [2] [3]
- Be concise, use bullet points for lists
- If ambiguous, ask ONE clarifying question
```

---

## LLM Providers (`llm_client.py`)

| `LLM_PROVIDER` | SDK | Notes |
|---|---|---|
| `anthropic` (default) | `anthropic.AsyncAnthropic` | Key: `ANTHROPIC_API_KEY`, model: `ANTHROPIC_MODEL` |
| `openrouter` | `openai.AsyncOpenAI` with `OPENROUTER_BASE_URL` | Key: `OPENROUTER_API_KEY`, model: `OPENROUTER_MODEL` |
| `norus` | `openai.AsyncOpenAI` with `NORUS_BASE_URL` | Key: `NORUS_API_KEY`, model: `NORUS_MODEL` |

Provider is fixed at import time (`_PROVIDER = os.getenv(...)`). Unknown value raises `ValueError`.  
Provider + model are logged at startup via lifespan in `main.py`.

---

## Environment Variables

| Variable | Required | Default |
|---|---|---|
| `QDRANT_URL` | yes | `http://qdrant:6333` |
| `COLLECTION_NAME` | yes | `secretary_notes` |
| `LLM_PROVIDER` | yes | `anthropic` |
| `ANTHROPIC_API_KEY` | if anthropic | — |
| `ANTHROPIC_MODEL` | no | `claude-sonnet-4-20250514` |
| `OPENROUTER_API_KEY` | if openrouter | — |
| `OPENROUTER_MODEL` | if openrouter | — |
| `OPENROUTER_BASE_URL` | if openrouter | — |
| `NORUS_API_KEY` | if norus | — |
| `NORUS_MODEL` | if norus | — |
| `NORUS_BASE_URL` | if norus | — |
| `COHERE_API_KEY` | no | — (reranking disabled if unset) |
| `COHERE_RERANK_MODEL` | no | `rerank-multilingual-v3.0` |

---

## Docker

- Base: `python:3.12-slim`
- CPU-only torch installed first (avoids ~2.5 GB CUDA pull)
- `EXPOSE 5065`
- `HEALTHCHECK --interval=30s --timeout=10s --start-period=60s` → `GET /health`
- Volume: `hf_cache:/root/.cache/huggingface` (shared with ingest service)
- `depends_on: qdrant`

---

## Known Constraints

- BGE-M3 (~2 GB) downloads on first container start; cache is persisted in `hf_cache` volume
- `/ingest-trigger` is blocking (not streaming); caller must handle long timeouts
- `_openai_client` is a module-level singleton — safe because `_PROVIDER` is fixed at startup
- Qdrant named vectors must match ingest schema exactly: `"dense"` (1024d cosine) + `"sparse"` (sparse index)
