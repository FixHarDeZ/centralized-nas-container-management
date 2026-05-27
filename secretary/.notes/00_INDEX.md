# secretary — Stack Index

> Memory index สำหรับ Claude Code — อ่านก่อนเริ่มงานใดๆ ใน stack นี้

---

## Overview

Stack สำหรับ AI secretary infrastructure บน Synology NAS:
- **Qdrant** — vector database สำหรับ hybrid search
- **Ollama** — local LLM inference (bge-m3 + อื่นๆ)
- **n8n** — workflow automation + trigger ingest jobs
- **secretary-ingest** — Notion→Qdrant ingest service (one-shot container)

---

## Services & Ports

| Service | Port | Notes |
|---|---|---|
| `qdrant` | 6333 | Vector DB, collection: `secretary_notes` |
| `ollama` | 11434 | Local LLM |
| `n8n` | 5678 | Workflow automation, triggers ingest |
| `secretary-ingest` | — | One-shot container, `restart: "no"` |

---

## secretary-ingest

### Purpose
Sync Notion pages → Qdrant `secretary_notes` collection with hybrid search (dense 1024d + sparse vectors via BGE-M3).

### Architecture
Single-file CLI: `ingest.py`
Sections (in order): CONFIG → STATE DB → NOTION → CONVERT → CHUNK → EMBED → QDRANT → SYNC → CLI

### Key Design Choices
- **FlagEmbedding-only** (BGEM3FlagModel) — produces both dense + sparse in one pass; no Ollama for embeddings
- **Incremental sync** — SQLite at `/data/ingest_state.db` tracks `last_edited_time` per page
- **Custom block converter** — handles all Notion block types listed below
- **Triggered by n8n** — Schedule Trigger + Execute Command node

### Notion Source Modes
| `NOTION_SOURCE_TYPE` | Mechanism | Required env var |
|---|---|---|
| `search` (default) | `POST /v1/search` — all accessible pages | — |
| `database` | `POST /v1/databases/{id}/query` (via `client.request()`) | `NOTION_DATABASE_ID` |
| `page` | Recursive child_page walk | `NOTION_ROOT_PAGE_ID` |

⚠️ **notion-client v3 gotcha**: `databases.query()` was removed. Use `client.request(path=f"databases/{db_id}/query", method="POST", body=...)`.

### CLI
```bash
python ingest.py              # incremental sync (default)
python ingest.py --full       # force re-ingest all
python ingest.py --page ID    # single page
python ingest.py --dry-run    # preview only
```

### Block Types Supported
paragraph, heading_1/2/3, bulleted_list_item, numbered_list_item, to_do, quote, callout, code, bookmark, embed, link_preview, image, divider, child_page (marker only), toggle, column_list/column, synced_block, table

### Qdrant Collection Schema
```
collection: secretary_notes
vectors:
  dense:  VectorParams(size=1024, distance=Cosine)
  sparse: SparseVectorParams(on_disk=False)
point_id: UUID5(page_id + str(chunk_index))
```

### Payload Fields
`source`, `page_id`, `page_url`, `page_title`, `breadcrumb`, `text`, `chunk_index`, `last_edited_time`, `parent_id`, `parent_type`, `tags`

---

## Environment Variables

```env
# secretary/.env (required)
QDRANT_URL=http://qdrant:6333
COLLECTION_NAME=secretary_notes
STATE_DB=/data/ingest_state.db

NOTION_TOKEN=ntn_xxxxx
NOTION_SOURCE_TYPE=search          # search | database | page
NOTION_DATABASE_ID=                # required if source_type=database
NOTION_ROOT_PAGE_ID=               # required if source_type=page

# n8n
N8N_BASIC_AUTH_USER=...
N8N_BASIC_AUTH_PASSWORD=...
N8N_WEBHOOK_URL=...
```

---

## Testing

```bash
cd secretary && python -m pytest tests/ -v   # 67 tests
```

Test files: `test_config`, `test_state`, `test_convert`, `test_chunk`, `test_notion`, `test_embed`, `test_qdrant`, `test_sync`, `test_cli`

**Gotcha for test_notion.py**: Module-level globals must be patched with `@patch("ingest.NOTION_SOURCE_TYPE", "value")`, NOT via `os.environ["NOTION_SOURCE_TYPE"] = "value"` (globals read at import time).

---

## Volumes
- `./qdrant_storage` — Qdrant vector data
- `./ollama_data` — Ollama model cache
- `./n8n_data` — n8n workflows + data
- `./ingest_data` — SQLite state DB (`ingest_state.db`)
- `hf_cache` (Docker named volume) — HuggingFace model cache (~2GB bge-m3)

---

## Deploy

```bash
scripts/deploy.sh   # upload + restart secretary stack on NAS
```

NAS path: `/volume2/docker/secretary`

**First run note:** BGE-M3 (~2GB) downloads on first `docker compose run --rm secretary-ingest`. Cached in `hf_cache` volume afterward.
