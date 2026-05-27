# Design: Notion → Qdrant Ingest Service

**Date:** 2026-05-27
**Stack:** `secretary/`
**Status:** Approved

---

## Overview

A Python CLI service (`ingest.py`) that ingests Notion pages into a Qdrant collection with hybrid search support (dense 1024d + sparse vectors), both produced by a single `BGEM3FlagModel` pass. Runs as a Docker container triggered on-demand by n8n on a schedule. Supports incremental sync — only re-indexes pages that have changed since the last run.

---

## Decisions Made

| Question | Decision |
|---|---|
| Embedding approach | FlagEmbedding-only (`BGEM3FlagModel`) — one model pass yields both dense + sparse |
| Trigger mechanism | n8n "Execute Command" node (no Ollama dependency in this service) |
| Block converter | Custom implementation (~150 lines) — no `notion2md` dependency |
| Code structure | Single `ingest.py` with clearly delimited sections |

---

## File Layout

```
secretary/
├── ingest.py                    ← entry point, all logic
├── requirements.txt
├── Dockerfile
├── .env.example
├── docker-compose-snippet.yml   ← new service to add to existing compose
└── README.md
```

The existing `secretary/docker-compose.yml` already has `qdrant`, `ollama`, and `n8n`. The new `secretary-ingest` service is added to it.

---

## ingest.py Internal Structure

Sections in order, each clearly delimited with a comment banner:

```
# ── CONFIG ──────────────────────────────────────────────
#   read .env via python-dotenv, validate required vars

# ── STATE DB ────────────────────────────────────────────
#   SQLite at /data/ingest_state.db
#   schema: page_id TEXT PK, last_edited_time TEXT, chunk_count INT
#   helpers: init_db(), get_state(), upsert_state(), delete_state(), list_all_pages()

# ── NOTION ──────────────────────────────────────────────
#   list_pages()       — search | database | page modes (via NOTION_SOURCE_TYPE)
#   fetch_blocks()     — recursive block walk, depth limit 5
#   rate_limiter       — token bucket, 3 req/s
#   tenacity retry     — 429/500 → exponential backoff, max 3 attempts

# ── CONVERT ─────────────────────────────────────────────
#   blocks_to_markdown()  — custom converter
#   _rt()                 — rich text → plain text helper

# ── CHUNK ────────────────────────────────────────────────
#   chunk_markdown()      — split on ## headings, 300-500 tokens (tiktoken cl100k_base)
#   build_breadcrumb()    — "PageTitle > Section > Subsection"

# ── EMBED ────────────────────────────────────────────────
#   load_model()          — BGEM3FlagModel, cached globally (loaded once per process)
#   embed_chunks()        — batch encode, returns {dense: [], sparse: []}

# ── QDRANT ──────────────────────────────────────────────
#   ensure_collection()   — create "secretary_notes" if absent
#   delete_page_points()  — filter by payload.page_id
#   upsert_chunks()       — named vectors {"dense": [...], "sparse": {...}}

# ── SYNC ─────────────────────────────────────────────────
#   sync_page()           — diff → delete old → embed → upsert → update state
#   run_incremental()     — default; compare last_edited_time vs state DB
#   run_full()            — re-ingest all, ignore state
#   run_single(page_id)   — one page by ID

# ── CLI ──────────────────────────────────────────────────
#   python ingest.py              → incremental sync
#   python ingest.py --full       → full re-ingest
#   python ingest.py --page ID    → single page
#   python ingest.py --dry-run    → show changes, no writes
```

---

## Data Flow

```
list_pages()
    │
    ▼  (mode: search / database / page)
[page list: id, title, url, last_edited_time, parent_id, tags]
    │
    ├─ compare with state DB
    │     unchanged → log "↷ Skipped (unchanged): <title>"
    │     deleted   → delete Qdrant points + state row
    │
    ▼  changed / new
fetch_blocks(page_id)         ← recursive, depth 5, rate-limited 3 req/s
    │  tenacity: 429/500 → 2^n backoff, max 3 attempts
    │
    ▼
blocks_to_markdown()
    │  child_page → "[→ Child Page Title]" marker only (indexed separately)
    │  empty      → log "↷ Skipped (empty page)"
    │
    ▼
chunk_markdown()              ← split on ## headings, tiktoken cl100k_base
    │  >500 tokens → split on ### then paragraphs
    │  <50 tokens  → merge into previous
    │  chunk 0 = title + preamble
    │
    ▼
embed_chunks()                ← BGEM3FlagModel.encode(), batch all chunks per page
    │  returns dense: list[list[float]], sparse: list[SparseVector]
    │
    ▼
delete_page_points(page_id)   ← only if page existed in state DB before
upsert_chunks()
    │  point ID: UUID5(page_id + str(chunk_index))
    │
    ▼
state DB upsert
    │
    ▼
log "✓ Updated: <title> (N chunks)"
```

---

## Block Converter

### Inline blocks (no children fetch)

| Block type | Markdown output |
|---|---|
| `paragraph` | plain text |
| `heading_1/2/3` | `#` / `##` / `###` |
| `bulleted_list_item` | `- text` |
| `numbered_list_item` | `1. text` |
| `to_do` | `- [x] text` / `- [ ] text` |
| `quote` | `> text` |
| `callout` | `> [emoji] text` |
| `code` | ` ```lang\ncode\n``` ` |
| `bookmark` / `embed` / `link_preview` | `[Title](url)` |
| `image` | `![](url)` (external URL, no download) |
| `divider` | `---` |

### Blocks that recurse into children

| Block type | Handling |
|---|---|
| `toggle` | `## Toggle Title\n` + recurse children |
| `column_list` / `column` | recurse children, render sequentially |
| `table` | fetch `table_row` children → markdown table |
| `child_page` | `[→ Child Page Title]` marker only |
| `synced_block` | recurse into `synced_from` source |

Rich text: `_rt(rich_text[])` extracts `plain_text` only — bold/italic annotations ignored (not needed for RAG).

---

## Qdrant Collection Schema

```python
VectorsConfig({
    "dense":  VectorParams(size=1024, distance=Distance.COSINE),
    "sparse": SparseVectorParams(index=SparseIndexParams(on_disk=False))
})
```

### Point Payload

```json
{
  "source":           "notion",
  "page_id":          "abc123",
  "page_url":         "https://notion.so/...",
  "page_title":       "Meeting Notes",
  "breadcrumb":       "Meeting Notes > Action Items > Q2",
  "text":             "chunk text here",
  "chunk_index":      2,
  "last_edited_time": "2025-05-20T10:00:00Z",
  "parent_id":        "def456",
  "parent_type":      "page",
  "tags":             ["work", "planning"]
}
```

Point ID: `UUID5(namespace=NAMESPACE_DNS, name=page_id + str(chunk_index))`

---

## Incremental Sync Logic

1. Call `list_pages()` → current page set from Notion
2. Call `list_all_pages()` from state DB → known page set
3. **Deleted pages** (in state DB but not in Notion): delete Qdrant points + state row
4. **New pages** (in Notion but not in state DB): ingest
5. **Changed pages** (`last_edited_time` in Notion > state DB): delete old Qdrant points, re-ingest
6. **Unchanged pages**: skip

`--full` flag skips step 2-3 comparison — force re-ingest everything.

---

## Notion Source Modes

| `NOTION_SOURCE_TYPE` | Mechanism | Required env var |
|---|---|---|
| `search` | `POST /v1/search` with empty query — returns all pages the integration can access | — |
| `database` | `POST /v1/databases/{id}/query` | `NOTION_DATABASE_ID` |
| `page` | `GET /v1/blocks/{id}/children` recursive walk of child_pages | `NOTION_ROOT_PAGE_ID` |

Rate limit: token bucket, 3 requests/second, enforced globally across all Notion API calls.

---

## End-of-Run Summary Log

```
────────────────────────────────────────
Pages processed:   42
  ✓ Updated:       8  (34 chunks created)
  ↷ Skipped:       31
  ✗ Errors:        2  (see above)
  🗑 Deleted:       1
Notion API calls:  67
Total time:        48.3s
────────────────────────────────────────
```

---

## Docker Setup

### Dockerfile

```dockerfile
FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends git build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY ingest.py .
ENV HF_HOME=/hf_cache
CMD ["python", "ingest.py"]
```

### docker-compose-snippet.yml

```yaml
secretary-ingest:
  build:
    context: ./secretary
    dockerfile: Dockerfile
  container_name: secretary-ingest
  depends_on:
    - qdrant
  volumes:
    - ./secretary/ingest_data:/data
    - hf_cache:/hf_cache
  env_file: ./secretary/.env
  restart: "no"

volumes:
  hf_cache:   # persists bge-m3 model (~2GB) across runs
```

### n8n Trigger

"Execute Command" node (scheduled, e.g. every 6 hours):
```
docker compose -f /volume2/docker/secretary/docker-compose.yml run --rm secretary-ingest
```

For full re-ingest: append `python ingest.py --full` as the command override.

---

## Configuration (.env.example)

```env
QDRANT_URL=http://qdrant:6333
COLLECTION_NAME=secretary_notes
STATE_DB=/data/ingest_state.db

NOTION_TOKEN=ntn_xxxxx
NOTION_SOURCE_TYPE=search          # search | database | page
NOTION_DATABASE_ID=                # required if NOTION_SOURCE_TYPE=database
NOTION_ROOT_PAGE_ID=               # required if NOTION_SOURCE_TYPE=page
```

`OLLAMA_URL` is **not required** — FlagEmbedding runs locally inside the container.

---

## requirements.txt

```
notion-client>=2.2.0
qdrant-client>=1.9.0
FlagEmbedding>=1.2.10
tiktoken>=0.7.0
tenacity>=8.2.0
python-dotenv>=1.0.0
```

---

## Error Handling

| Scenario | Behaviour |
|---|---|
| Notion 429 | tenacity retry: wait 2^n seconds, max 3 attempts, then log error and continue next page |
| Notion 500 | same as 429 |
| Qdrant unavailable | fatal — raise on startup after `ensure_collection()` fails |
| Empty page (no text) | skip, no state DB entry |
| Page with > depth 5 nesting | truncate at depth 5, log warning |
| `--dry-run` | all Notion reads happen normally; Qdrant writes and state DB writes are skipped |

---

## Out of Scope

- Downloading/storing images locally (spec: emit URL only)
- Notion database property indexing beyond `multi_select` tags
- Serving search queries (this is ingest-only; search is handled by n8n/my-secretary)
- Auth/HTTPS for the ingest container (it has no HTTP server)
