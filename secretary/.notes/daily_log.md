# Secretary Stack — Daily Log

## 2026-05-27

### งานที่ทำ
- Restructured secretary stack from single `ingest.py` monolith to multi-service architecture
- Created `secretary/ingest/` service: ingest.py (Notion→Qdrant), Dockerfile (CPU-only torch), requirements.txt, .env.example, README.md
- Created `secretary/query/` service: main.py (FastAPI RAG :5065), llm_client.py (Anthropic/OpenRouter/Norus), Dockerfile, .env.example, README.md
- Updated `docker-compose.yml`: qdrant, ollama, n8n (15678), secretary-query (15065), secretary-ingest (one-shot)
- Added root `secretary/.env.example` for n8n credentials
- Added `secretary/` row to CLAUDE.md stacks table (ports 15065, 15678)
- Created `.notes/00_INDEX.md` with full architecture/volume/env documentation

### Architecture Changes
- Embedding: BGE-M3 via FlagEmbedding (CPU-only, shared `hf_cache` volume)
- Hybrid search: dense (1024d Cosine) + sparse vectors, RRF fusion
- LLM: switchable via `LLM_PROVIDER` (anthropic default)
- Reranking: optional Cohere `rerank-multilingual-v3.0`
- Ingest state: SQLite at `/data/ingest_state.db` for incremental sync

### Next Steps
1. Deploy to NAS: `/deploy`
2. Create NAS directories: `mkdir -p /volume2/docker/secretary/{qdrant_storage,ollama_data,n8n_data,ingest_state,hf_cache,ingest,query}`
3. Copy `.env.example` → `.env` for root, ingest/, query/ and fill real values
4. Run: `docker compose up -d qdrant ollama n8n && docker compose up -d --build`
5. First ingest: `docker compose run --rm secretary-ingest python ingest.py --full`
6. Set up n8n workflows (Phase 6 of checklist)

## 2026-05-28

### งานที่ทำ
- Review & validate secretary-query service against spec
- Fixed two gaps: removed unused `PORT` var from `.env.example`; added blocking-timeout note to README
- Added pytest suite: 9 tests covering llm_client (4 providers) + main endpoints (/health ok/down, /query hybrid, /query top_k_final slice, /query hybrid+rerank)
- Key discovery: `ASGITransport` doesn't fire ASGI lifespan — fixed by direct assignment of `main.qdrant` and `main.app.state.model` in conftest.py
- Written design spec: `docs/superpowers/specs/2026-05-28-secretary-query-design.md`
- Committed all query service files (12 files, commit adb366a)

### Next Steps
1. Deploy to NAS: `/deploy`
2. On NAS: `cp secretary/query/.env.example secretary/query/.env` and fill real keys
3. `docker compose up -d --build secretary-query`
4. Smoke test: `curl http://<NAS_HOST>:15065/health`
5. First ingest: `docker compose run --rm secretary-ingest`

## 2026-05-28

### Nous Portal OAuth integration
- Removed `norus` provider from llm_client.py, main.py, .env.example, and tests
- Created `nous_auth.py` (NousTokenManager) — handles OAuth 2.0 Device Code flow, token persistence to /data/nous_token.json, auto-refresh with 60s buffer
- `_poll_for_token` retries on network errors and unexpected status codes (logs warning, continues)
- Added `GET /nous/auth` endpoint — starts device flow, returns {verification_uri, user_code, expires_in, message}; returns 503 if Nous Portal unreachable
- Added `GET /nous/auth/status` endpoint — returns {authenticated: bool, expires_at: int|null}
- Added `nous` provider block in llm_client.py — creates fresh AsyncOpenAI client per call (Bearer token from nous_auth), inference URL: https://inference-api.nousresearch.com/v1
- OAuth endpoints: portal.nousresearch.com/api/oauth/device/code + /token, client_id=hermes-cli
- Token stored in /data/nous_token.json (atomic write), NOUS_TOKEN_FILE env var for override
- Setup: deploy → GET /nous/auth → open verification_uri in browser → enter user_code → approve → token auto-saved
