# secretary-ingest

Syncs Notion pages into a Qdrant collection with hybrid search (dense 1024d + sparse via BGE-M3).

## Quick start

1. Copy env template and fill values:
   ```bash
   cp secretary/.env.example secretary/.env
   ```

2. Build and run incremental sync:
   ```bash
   docker compose -f secretary/docker-compose.yml run --rm secretary-ingest
   ```

3. Full re-ingest (ignore state):
   ```bash
   docker compose -f secretary/docker-compose.yml run --rm secretary-ingest python ingest.py --full
   ```

4. Dry-run (preview only):
   ```bash
   docker compose -f secretary/docker-compose.yml run --rm secretary-ingest python ingest.py --dry-run
   ```

5. Single page:
   ```bash
   docker compose -f secretary/docker-compose.yml run --rm secretary-ingest python ingest.py --page <NOTION_PAGE_ID>
   ```

## Creating a Notion Integration

1. Go to https://www.notion.so/profile/integrations → **New integration**
2. Name it (e.g. "secretary-ingest"), select your workspace, set type = Internal
3. Copy the **Internal Integration Secret** → set as `NOTION_TOKEN` in `.env`
4. Open each page/database you want to index → click **...** → **Connections** → add your integration

## Source modes

| `NOTION_SOURCE_TYPE` | What it indexes | Required env var |
|---|---|---|
| `search` (default) | All pages the integration can access | — |
| `database` | Rows of one specific database | `NOTION_DATABASE_ID` |
| `page` | All child pages under a root page | `NOTION_ROOT_PAGE_ID` |

## n8n trigger (scheduled sync)

In n8n, add a **Schedule Trigger** + **Execute Command** node:
```
docker compose -f /volume2/docker/secretary/docker-compose.yml run --rm secretary-ingest
```

## First run note

BGE-M3 (~2GB) is downloaded on first run and cached in the `hf_cache` Docker volume. Subsequent runs start in seconds.

## State database

Incremental state is stored at `/data/ingest_state.db` (SQLite). Reset it to force a full re-ingest without `--full`:
```bash
docker compose -f secretary/docker-compose.yml run --rm secretary-ingest python -c "import os; os.remove('/data/ingest_state.db')"
```
