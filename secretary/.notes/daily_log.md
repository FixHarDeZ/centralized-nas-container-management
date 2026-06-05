# Secretary Stack — Daily Log

## 2026-06-05 — Fix If2 type error in Secretary Bot workflow

### Problem
n8n execution 180 failed at **If2** node:
`Wrong type: 'AxiosError: timeout of 60000ms exceeded' is an object but was expecting a string [condition 0, item 0]`

### Root Cause
`HTTP Request1` (POST /query, `onError: "continueRegularOutput"`) puts `AxiosError` **object** into `$json.error` on timeout/failure.
If2 checked `$json.error` with operator `type: "string", operation: "notEmpty"`.
Even with `typeValidation: "loose"`, n8n v3 conditions cannot coerce an AxiosError object to string for notEmpty check → crash.

### Fix
Changed If2 `leftValue` from `={{ $json.error }}` → `={{ $json.error ? 'error' : '' }}`
Coerces any truthy value (object/string) to `'error'` before notEmpty string check. Works correctly for both normal responses (no error field) and error objects.

### Deployed
`./scripts/n8n_import.sh` → updated workflow id `syPPm4qxmVNENC9U`

---

## 2026-06-02 (evening) — Real fix for secretary-query OOM

### Symptoms
- n8n "Secretary Auto Sync" workflow ส่ง Telegram alert ทุกชั่วโมง:
  `500 - {"status":"error","summary":"...Loading weights: 100%|██████████| 391/391..."}`
- Subprocess `/ingest-trigger` ตายเงียบ (ไม่มี Python traceback) หลัง `qdrant points/delete` สำเร็จ

### Root cause (two layers)
1. **OOM kill ของ subprocess ใน secretary-query container** — dmesg ยืนยัน:
   `Memory cgroup out of memory: Killed process … (python) … anon-rss:3157172kB` ทุก ~1 ชม. ตรงกับ n8n Schedule Trigger
2. **The "fix" commit `bbbe6ac` (2026-06-02 บ่าย) เป็น no-op** — diff แทรก `deploy:` block ที่สอง **ก่อน** `depends_on:` ทำให้มี `deploy:` ซ้ำสองตัวที่ระดับเดียวกัน YAML กิน ตัวสุดท้าย (4G) ทับ. ต่อมา commit `b5405d4 update` มา "ล้าง" duplicate ด้วยการลบ block 6g ที่เพิ่งใส่เข้าไป — กลับสู่ 4G เหมือนเดิม. **secretary-query container ตอน OOM ยังเป็น container เดิมที่ถูกสร้าง 2026-06-01 23:14 + memory limit 4G** (`docker inspect ... HostConfig.Memory` = `4294967296`)
   - Daily log entry ก่อนหน้านี้เขียนว่า "container restart count = 2, RAM 1.5GB steady-state" — ที่จริงนั่นคือสภาพ **ระหว่าง crash loop เอง** ไม่ใช่ผลของ fix; verification อ่านผิด

### Real fix (this session)
- `secretary/docker-compose.yml:73-84` แก้ `memory: 4G` → `memory: 6G` (block เดียว ไม่มี duplicate)
- Deploy: `bash scripts/deploy.sh -s secretary -y`
- Verified post-deploy:
  - `docker inspect secretary-query --format '{{.HostConfig.Memory}}'` = `6442450944` (6 GiB ✓)
  - `POST /ingest-trigger` (ภายใน container) → `{"status":"done", ..., "Summary — pages: 155 | updated: 2 | skipped: 153 | chunks: 19 | errors: 0 | time: 115.3s"}` ใช้เวลา ~2 นาที ไม่ OOM, n8n auto-sync จะไม่ alert อีก

### Architecture note (load-bearing on 6G headroom)
`/ingest-trigger` ยังโหลด BGE-M3 ใน subprocess บน container ที่มี BGE-M3 resident อยู่แล้ว — ปลอดภัยเพราะ 6G ไม่ใช่เพราะ architecture ดี. Daily log 2026-06-01 ระบุชัดว่าเส้นทาง subprocess-in-query เป็น known limitation. ถ้าจะ refactor proper ในอนาคต: ให้ n8n เรียก `secretary-ingest` ผ่าน docker socket (one-shot container 6G dedicated) แทน

### Schedule observation (worth considering)
n8n auto-sync รันทุก 1 ชม. → จ่าย BGE-M3 cold load + Notion polling ทุกชั่วโมง สำหรับ updated pages 0–2 หน้า. ลดเป็น 4–6 ชม. ครั้งจะลด OOM exposure + CPU/network เกือบหมด

## 2026-06-02 (earlier — superseded by entry above)

### Attempted fix that landed as a no-op (kept for traceability)
- Commit `bbbe6ac` ตั้งใจเพิ่ม `deploy.resources.limits.memory: 6g` ใน secretary-query แต่ YAML duplicate-key bug ทำให้ไม่มีผล
- Commit `b5405d4 update` ตามมา ลบ block 6g ที่ duplicate ออก (แต่ลบผิดตัว) — กลับสู่ 4G
- Container ไม่เคยถูก recreate ด้วย 6G; OOM crash loop ดำเนินต่อจนกระทั่ง fix จริงด้านบน

## 2026-06-01

### Code Review of today's table-row chunking PR (commits 0555985…001e52f)
Reviewed 9 commits where hermes-agent (Mimo 2.5 Pro backend) rewrote `chunk_document()` to split Notion markdown tables into per-row chunks for better RAG retrieval. Verified findings (recall mode, 5 angles + verifier):

**CONFIRMED bugs (acceptable for now but worth tracking):**
- **Giant table row >500 tokens bypasses chunk size cap** (`ingest.py` ~528) — table branch in `chunk_document` skips the `_split_by_paragraph` 500-token guard. Single-row chunks with long Notes columns are not split. Low impact for credentials tables (short cells).
- **`keywords` and `category` payload fields are dead data** — `_extract_keywords` writes them in `upsert_chunks`, but `query/main.py` never filters on them. No payload index created in `ensure_collection()` either. Either drop them or actually use them in the query pipeline.
- **Pipe-in-cell breaks `_table_to_md` serializer** (`ingest.py:359-370`) — cells containing literal `|` are emitted unescaped, corrupting the markdown table downstream of the Notion serializer.
- **No timeout on `/ingest-trigger` subprocess** (`query/main.py:202` — `await proc.communicate()`) — this is the cause of the 150-second hang the user saw via the Hermes screenshot.
- **No SQLite write lock on `/ingest-trigger`** — concurrent requests race the state DB.
- **Degenerate breadcrumb when first table column is blank** — `primary_name` stays `""`, breadcrumb falls back to `Title > Heading` only.

**REFUTED candidates** (the change is actually safe):
- Merge-tiny-sections loop accidentally swallowing table rows — guarded by `is_table_row` check first.
- Stale Qdrant points after re-ingest — `delete_page_points(page_id)` is called before upsert.
- Mixed breadcrumb formats (table vs non-table) — breadcrumb is cosmetic, never parsed downstream.
- `subprocess env` losing PATH — `os.environ.copy()` preserves it.

**Suggestions for follow-up commits:**
1. Add `asyncio.wait_for(proc.communicate(), timeout=600)` to `/ingest-trigger` so the request returns a 504 instead of hanging forever.
2. Drop `keywords`/`category` writes OR wire them into the query filter to make them earn their storage cost.
3. Escape `|` → `\|` in `_table_to_md` cell text.
4. Add a single-row-too-large fallback inside `_split_table_to_rows` (paragraph-split the row if `_count_tokens(row_text) > 500`).

### Resource limits on docker-compose.yml
NAS hit 100% CPU during ingest, DSM became unreachable, 15-min load avg was 85. `secretary-query` was holding 5.5 GB at idle (model + leftover ingest subprocess).

First attempt added `cpus: N.M` to all 4 services. **Deploy failed with `NanoCPUs can not be set, as your kernel does not support CPU CFS scheduler`** — Synology DSM kernel ships without CFS quota support, so docker-level CPU limits are simply unavailable on this NAS. Removed all `cpus:` keys.

Working config:
- `deploy.resources.limits.memory` on every service — cgroup-enforced.
- `OMP_NUM_THREADS` / `MKL_NUM_THREADS` / `TOKENIZERS_PARALLELISM=false` on `secretary-query` (=2) and `secretary-ingest` (=3) — PyTorch + FlagEmbedding obey these, so even without docker cpus the model uses at most N threads.
- `logging.options.max-size=10m max-file=3` for all services (was unbounded).

Memory allotment (NAS = 12 GB total):
- qdrant: 1.5 GB
- n8n: 1 GB
- secretary-query: **6 GB** *(bumped from 4 GB on 2026-06-02 after repeated OOM kills)*
- secretary-ingest: 6 GB *(bumped from 4 GB after OOM kill on the User-Password page — FlagEmbedding's batch encode of 20–50 chunks spikes RAM transiently past the resident ~2 GB model footprint.)*

### Known limitation — `/ingest-trigger` OOMs on table-heavy pages
The `/ingest-trigger` endpoint in `secretary-query` spawns `ingest.py` as a subprocess **inside the query container**. The subprocess loads its own BGE-M3 (~2 GB) on top of the parent's already-resident BGE-M3 (~2 GB), so the query container's 4 GB ceiling is exhausted before chunking even starts on a page with many table rows. **Workaround:** run page-targeted re-ingests in the dedicated container instead:
```bash
docker compose run --rm secretary-ingest python ingest.py --page <NOTION_PAGE_ID>
```
This was the path used to backfill the User-Password page. The standalone container has its own 6 GB budget and doesn't compete with secretary-query's resident model.

### End-to-end verification
- Bumped local main to origin/main (was 10 commits behind — first deploy uploaded the OLD `query/main.py` without the `page_id` parameter, which is why `/ingest-trigger?page_id=…` seemed to "ignore" the filter and silently ran a full incremental skip across all 155 pages).
- Removed orphan `secretary-ollama` container (compose dropped the service 2026-05-29 but the container was never `docker rm`'d).
- `docker compose run --rm secretary-ingest python ingest.py --page 5edc5884-7666-4bdd-b758-86cc24c95f0a` → `Updated: User-Password (29 chunks)` in 379 s.
- Qdrant point count for that `page_id`: **29** (was 0 after my earlier failed runs left the page deleted-but-not-upserted).
- `POST /query {"question": "ขอ user pass discord"}` → returns `User: fixkychicky@gmail.com, Password: REDACTED@1` with breadcrumb `User-Password > Website > Discord`. The per-row chunking is working as intended — Hermes's diagnosis was correct, just never successfully applied because every previous re-ingest attempt died on memory or timeout.

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

## 2026-05-31

### Phase B: NORUS → NOUS manifest fix
- **Bug:** `secretary/query/secrets.manifest.yaml` ใช้ `NORUS_API_KEY`, `NORUS_BASE_URL`, `NORUS_MODEL` (มี R) แต่โค้ดจริง (`llm_client.py`, `main.py`) ใช้ `NOUS_MODEL` (ไม่มี R) และใช้ OAuth device code flow ไม่ได้ใช้ API key
- **Fix:** ลบ `NORUS_API_KEY` และ `NORUS_BASE_URL` จาก manifest `env:` (dead vars), เปลี่ยน `NORUS_MODEL` → `NOUS_MODEL` ใน manifest `literals:`
- ผล: `make secrets` + `make test` (43 tests) ผ่าน, `secretary/query/.env` ไม่มี NORUS vars อีก, มี `NOUS_MODEL=xxx` ถูกต้อง

## 2026-06-05

### งานที่ทำ
- สร้าง n8n workflow `Secretary Error Alerter` — Error Trigger → Telegram alert ที่ chat `8663614341`
- Set เป็น global Error Workflow ใน n8n Settings → General → Error Workflow
- ทดสอบด้วย `_Test Error` workflow → ได้รับ alert ใน Telegram ✅
- Fix `scripts/n8n_import.sh`: create-path ส่งเฉพาะ minimal fields ที่ POST API ยอมรับ (ไม่ส่ง read-only fields เช่น `active`, `meta`)

### Architecture Change
- n8n Error Workflow ครอบทุก workflow อัตโนมัติ (Secretary Auto Sync, Secretary Bot, และ future workflows)
- Credential ใช้ "Secretary Bot" telegramApi ตัวเดิม (id: QiUZ8rINLwwPL1qu)
