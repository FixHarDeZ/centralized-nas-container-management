# Secretary Stack — Daily Log

## 2026-05-28 (session 2)

### งานที่ทำ
- Diagnosed RAG inconsistency: ปัญหาหลักคือ retrieval ไม่ใช่ system prompt — `top_k_final=3` ตัด chunks ที่ถูกต้องทิ้ง + Thai query vs English content semantic gap
- Fix 1: เพิ่ม `top_k_final` default จาก 3 → 6 ใน `query/main.py:QueryRequest`
- Fix 2: ปรับ SYSTEM_PROMPT — เพิ่ม rule "ถ้า partial context มีอยู่ให้รายงานที่เจอแทนการบอกว่าไม่พบ" เพื่อลด false "ไม่พบข้อมูล"
- สร้าง `secretary/README.md` (ไม่เคยมีมาก่อน) — ครอบคลุม quickstart, services, volumes, env files, LLM providers, API endpoints, ingest commands
- อัปเดต root `README.md`: ลบ `my-secretary/` (ถูกลบออกจาก project แล้ว), เพิ่ม `secretary/` row, อัปเดต Reverse Proxy, env vars, Architecture Notes

### Code Cleanup (session 3)
- Cohere client: ย้ายจาก per-request → `app.state.cohere` init ครั้งเดียวใน lifespan
- `/ingest-trigger`: เปลี่ยน error response จาก HTTP 200 → HTTP 500
- Nous client (`llm_client.py`): cache ตาม token string แทน per-call construction
- Extract `_text_from_openai()` helper — ลบ openrouter/nous duplication
- `asyncio.Lock` ใน `NousTokenManager.get_access_token` — กัน concurrent refresh stampede
- `_TERMINAL_OAUTH_ERRORS` constant + stop polling on terminal errors (access_denied ฯลฯ)
- Deployed และ health check ผ่าน: `{"status":"ok","qdrant_ok":true,"collection_stats":{"points_count":345}}`

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

### Fix /ingest-trigger (POST /ingest-trigger → python /ingest/ingest.py not found)
- **Root cause:** `/ingest-trigger` in `query/main.py:185` runs `python /ingest/ingest.py` as subprocess inside `secretary-query` container, but `ingest.py` was moved to `secretary/ingest/` subdirectory as a separate service — file never copied into query container
- **Fix 1:** `docker-compose.yml` — added `./ingest/ingest.py:/ingest/ingest.py:ro` bind mount + `./ingest/.env` env_file to `secretary-query` service (ingest env vars needed by subprocess)
- **Fix 2:** `query/requirements.txt` — added `notion-client>=2.2.0`, `tiktoken>=0.7.0`, `tenacity>=8.2.0` (required by ingest.py but missing from query container)
- **Note:** State DB (`STATE_DB=/data/ingest_state.db`) when triggered via `/ingest-trigger` writes to query-data volume (`/volume2/docker/secretary/query-data/`), separate from `ingest_state` volume used by standalone `secretary-ingest` service — incremental sync works independently per trigger method

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

## 2026-05-29

### งานที่ทำ
- ลบ `ollama` service และ `ollama_data` volume ออกจาก `docker-compose.yml` — ไม่เคยมีโค้ดส่วนไหน connect มันเลย ทั้ง ingest ใช้ FlagEmbedding โดยตรง และ query ใช้ external LLM APIs
- อัปเดต `query/.env.example`: เปลี่ยน default `LLM_PROVIDER=openrouter`, `OPENROUTER_MODEL=google/gemini-2.5-flash`
- `query/.env` จริง: user เลือกใช้ `deepseek/deepseek-v4-flash` (ถูกกว่า Gemini Flash)

---

## 2026-05-28 — Fix: filter sources to cited-only

**Problem:** `/query` endpoint returned all top_k_final=6 sources, n8n displayed all as references even when LLM only used 1.

**Root cause:** `sources` was built from all `hits` unconditionally.

**Fix:** After LLM answer, parse citation numbers with `re.findall(r"\[(\d+)\]", answer)`, filter `hits` to only cited indices before building `sources` array (`main.py:147-156`).

**Tests:** Updated 3 test mocks to include `[1]` in LLM return values. Pre-existing `test_query_rerank_path` failure (KeyError 'cohere' in app.state) unchanged.
