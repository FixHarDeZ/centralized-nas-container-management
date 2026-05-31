# Secretary Stack — Index

## Stack Overview
Personal knowledge base stack: ingests Notion pages into Qdrant, serves RAG queries via FastAPI, orchestrated with n8n Telegram bot workflows.

## Architecture
```
Notion API
    ↓ (secretary-ingest, one-shot)
Qdrant (secretary_notes collection)
    ↑ (hybrid search: BGE-M3 dense 1024d + sparse)
secretary-query (FastAPI :5065)
    ↑ (POST /query, POST /ingest-trigger)
n8n (:15678) → Telegram bot
```

## Services
| Service | Container | Port | Notes |
|---|---|---|---|
| qdrant | secretary-qdrant | 6333 (internal) | Collection: `secretary_notes`, named vectors `dense`+`sparse` |
| n8n | secretary-n8n | 15678→5678 | Webhook: `/webhook/telegram`. Basic auth via root `.env` |
| secretary-query | secretary-query | 15065→5065 | FastAPI RAG. LLM provider switchable via `LLM_PROVIDER` env |
| secretary-ingest | secretary-ingest | — | `restart: "no"`. Run: `docker compose run --rm secretary-ingest` |

## Volumes (NAS paths)
| Volume | Path |
|---|---|
| qdrant_storage | `/volume2/docker/secretary/qdrant_storage` |
| n8n_data | `/volume2/docker/secretary/n8n_data` |
| ingest_state | `/volume2/docker/secretary/ingest_state` |
| hf_cache | `/volume2/docker/secretary/hf_cache` |

## Env Files
- `secretary/.env` — n8n credentials (`N8N_BASIC_AUTH_*`, `N8N_WEBHOOK_URL`)
- `secretary/ingest/.env` — Notion token, Qdrant URL, source config
- `secretary/query/.env` — Qdrant URL, LLM provider keys, Cohere key

## Embedding Model
- **BGE-M3** (`BAAI/bge-m3`) via FlagEmbedding
- CPU-only torch (~200MB, not CUDA ~2.5GB)
- First run downloads ~2GB to `hf_cache` volume (shared between ingest + query)

## LLM Providers (query service)
`LLM_PROVIDER` env: `anthropic` (default) | `openrouter` | `nous`

| Provider | Auth | Notes |
|---|---|---|
| `anthropic` | `ANTHROPIC_API_KEY` | Default |
| `openrouter` | `OPENROUTER_API_KEY` | Via OpenAI-compat API |
| `nous` | OAuth 2.0 Device Code | Token persisted to `/data/nous_token.json`. Setup: `GET /nous/auth` → browser → approve |

### Nous OAuth Endpoints
- `GET /nous/auth` — starts device flow; returns `{verification_uri, user_code, expires_in, message}`; 503 if Nous Portal unreachable
- `GET /nous/auth/status` — returns `{authenticated: bool, expires_at: int|null}`

### Nous Auth Implementation
- File: `secretary/query/nous_auth.py` (`NousTokenManager`)
- OAuth endpoints: `portal.nousresearch.com/api/oauth/device/code` + `/token`, `client_id=hermes-cli`
- Inference URL: `https://inference-api.nousresearch.com/v1`
- Token auto-refresh with 60s buffer; `_poll_for_token` retries on network errors
- Override token path: `NOUS_TOKEN_FILE` env var

## Reranking
Optional Cohere reranking: set `COHERE_API_KEY` in `query/.env`. Model: `rerank-multilingual-v3.0`.

## Qdrant Collection Schema
- Dense vector: 1024d, Cosine distance
- Sparse vector: named `sparse`
- Payload fields: `source`, `page_id`, `page_url`, `page_title`, `breadcrumb`, `text`, `chunk_index`, `last_edited_time`, `tags`

## Tests
Run from `secretary/query/`:
```bash
pip install -r requirements-dev.txt
pip install -r requirements.txt
pytest -v   # 22 tests
```
Stubs: `FlagEmbedding` + `torch` + `cohere` mocked at `sys.modules` level (no model download needed).
Note: `ASGITransport` does not fire ASGI lifespan — conftest directly assigns `main.qdrant` and `main.app.state.model`.

## /ingest-trigger Behavior
The `POST /ingest-trigger` endpoint in `secretary-query` runs `ingest.py` as a subprocess (at `/ingest/ingest.py` inside the container, bind-mounted from `./ingest/ingest.py`). It inherits env vars from both `query/.env` and `ingest/.env`. State DB writes to `query-data` volume (`/data/ingest_state.db`), separate from the `ingest_state` volume used by `docker compose run --rm secretary-ingest`.

## /query Response — Sources Filtering (2026-05-28)
`sources` in the response now contains only chunks actually cited by the LLM (`[1]`, `[2]`, etc.), not all top_k_final hits. Regex parse in `main.py:147`. This fixes n8n showing unrelated reference links alongside the answer.

## n8n Workflow Backup
Manual scripts to export/import n8n workflows via REST API (SSH tunnel to NAS localhost:5678).

**Export:** `./scripts/n8n_export.sh` → saves workflow JSONs to `secretary/n8n-workflows/`
**Import:** `./scripts/n8n_import.sh [file.json]` → updates existing workflows by name (upsert)

Requires `N8N_API_KEY` in `secretary/.env` (generated from vault via `make secrets`).
Workflow files are git-tracked for version control.

## Gaps / TODOs
- (none)
