# secretary/ingest — Stack Index

## Purpose
Notion-to-Qdrant ingestion pipeline. Fetches Notion pages, converts to Markdown,
chunks by heading, embeds with BAAI/bge-m3 (BGE-M3 hybrid: dense 1024d + sparse lexical),
and upserts into Qdrant collection `secretary_notes`.

## Files
| File | Role |
|------|------|
| `ingest.py` | Main script — all ingestion logic |
| `requirements.txt` | Python deps |
| `Dockerfile` | python:3.12-slim, CPU-only torch |
| `.env.example` | Env var template |
| `README.md` | Usage + env table |

## Architecture
- **Embedding:** `BGEM3FlagModel("BAAI/bge-m3")` loaded at module level; single `.encode()` call per batch
- **Qdrant:** Named vectors — `"dense"` (VectorParams 1024d Cosine) + `"sparse"` (SparseVectorParams)
- **State:** SQLite at `/data/ingest_state.db` — tracks `page_id`, `last_edited_time`, `chunk_count`
- **UUID5 namespace:** `b3d1c2a0-4f5e-6789-abcd-ef0123456789` (fixed; changing orphans all points)
- **Chunking:** split by `##` → oversized (>500 tok) split by paragraph → tiny (<50 tok) merged with next sibling
- **Rate limiting:** `sleep(0.34)` before each Notion API call; tenacity retry 3×, wait 2s on 429/500

## Env Vars
See `.env.example` — key vars: `QDRANT_URL`, `NOTION_TOKEN`, `NOTION_SOURCE_TYPE`

## Volumes (docker-compose)
- `ingest_state` → `/data` (SQLite)
- `hf_cache` → `/root/.cache/huggingface` (model weights shared with secretary-query)
