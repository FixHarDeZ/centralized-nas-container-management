# secretary-ingest

Notion → Qdrant ingestion pipeline using BGE-M3 hybrid (dense + sparse) embeddings.

## What it does

Pulls pages from Notion, converts blocks to Markdown, chunks by heading, embeds with
`BAAI/bge-m3` (1024d dense + sparse lexical weights), and upserts into a Qdrant
`secretary_notes` collection. Tracks ingestion state in SQLite for incremental syncs.

## CLI modes

```bash
python ingest.py              # incremental (skip unchanged pages)
python ingest.py --full       # re-ingest everything
python ingest.py --page <ID>  # single Notion page ID
python ingest.py --dry-run    # show changes without writing
```

## Environment variables

| Variable              | Required | Default                   | Description                                  |
|-----------------------|----------|---------------------------|----------------------------------------------|
| `QDRANT_URL`          | yes      | —                         | Qdrant endpoint e.g. `http://qdrant:6333`   |
| `COLLECTION_NAME`     | no       | `secretary_notes`         | Qdrant collection name                       |
| `STATE_DB`            | no       | `/data/ingest_state.db`   | SQLite path for incremental state            |
| `NOTION_TOKEN`        | yes      | —                         | Notion integration token (`ntn_xxx`)         |
| `NOTION_SOURCE_TYPE`  | no       | `search`                  | `search` / `database` / `page`              |
| `NOTION_DATABASE_ID`  | no       | —                         | Required when `NOTION_SOURCE_TYPE=database`  |
| `NOTION_ROOT_PAGE_ID` | no       | —                         | Required when `NOTION_SOURCE_TYPE=page`      |

## Volumes

- `/data` — SQLite state DB + persistent between runs (mount `ingest_state` volume)
- `/root/.cache/huggingface` — BGE-M3 model cache (mount `hf_cache` volume to avoid re-download)
