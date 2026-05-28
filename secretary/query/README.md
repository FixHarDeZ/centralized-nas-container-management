# secretary-query

FastAPI RAG query service. Embeds questions with BGE-M3, retrieves from Qdrant via hybrid search (dense + sparse, RRF fusion), optionally reranks with Cohere, then answers via a configurable LLM.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/query` | RAG question answering |
| GET | `/health` | Qdrant connectivity + collection stats |
| POST | `/ingest-trigger` | Run `/ingest/ingest.py` and return output |

### POST /query payload

```json
{ "question": "...", "top_k_retrieve": 20, "top_k_final": 3, "session_id": "" }
```

> **`/ingest-trigger` note:** this endpoint blocks until the ingest process exits (can take several minutes on first run). The HTTP connection stays open throughout; plan for a generous client timeout (~10 min).

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `QDRANT_URL` | yes | Qdrant service URL |
| `COLLECTION_NAME` | yes | Qdrant collection name |
| `LLM_PROVIDER` | yes | `anthropic` / `openrouter` / `nous` |
| `ANTHROPIC_API_KEY` | if provider=anthropic | Anthropic API key |
| `ANTHROPIC_MODEL` | no | Default: `claude-sonnet-4-20250514` |
| `OPENROUTER_API_KEY` | if provider=openrouter | OpenRouter key |
| `OPENROUTER_MODEL` | if provider=openrouter | Model name |
| `OPENROUTER_BASE_URL` | if provider=openrouter | Base URL |
| `NOUS_MODEL` | if provider=nous | Model name (auth handled via OAuth) |
| `COHERE_API_KEY` | no | Enables reranking when set |
| `COHERE_RERANK_MODEL` | no | Default: `rerank-multilingual-v3.0` |

### Nous Portal one-time OAuth setup

1. `GET /nous/auth` — returns a URL and a device code
2. Open the URL in a browser and enter the code to approve
3. Token is saved to `/data/nous_token.json` and reused automatically on subsequent requests

## Local Testing

```bash
cp .env.example .env  # fill in real values
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt
uvicorn main:app --port 5065 --reload
curl http://localhost:5065/health
```
