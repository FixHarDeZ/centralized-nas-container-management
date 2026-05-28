# Daily Log — secretary/ingest

## 2026-05-28

### Spec audit (no changes)

Audited all 5 output files against the full ingest spec. All 10 requirement areas confirmed covered:
- FlagEmbedding BGE-M3 (module-level load, dense+sparse in one encode call) ✓
- Notion integration (search/database/page modes, pagination) ✓
- Block→Markdown converter (all 16+ block types) ✓
- Heading-based chunker with paragraph fallback + tiny-section merge ✓
- Qdrant named-vector upsert (dense 1024d + sparse SparseVector) ✓
- Incremental sync via SQLite state DB ✓
- Deleted-page cleanup ✓
- Rate limiting (sleep 0.34s) + tenacity retry on 429/500 ✓
- CLI modes (--full, --page, --dry-run) ✓
- Docker (python:3.12-slim, CPU-only torch, restart:no, depends_on qdrant) ✓

Not runtime-verified (requires live Qdrant + Notion token).

---

## 2026-05-27

### Created: Full secretary/ingest/ service (5 files)

Built the complete Notion→Qdrant ingestion pipeline from spec:

- **ingest.py** — full pipeline: Notion fetch (search/database/page modes), custom block→Markdown
  converter (no notion2md dep), heading-based chunker with paragraph fallback + tiny-section merge,
  BGE-M3 hybrid embeddings, Qdrant upsert with named vectors, SQLite incremental state, CLI flags
  (`--full`, `--page`, `--dry-run`), tenacity retry, rate limiting
- **requirements.txt** — 5 deps (qdrant-client, flagembedding, notion-client, tiktoken, tenacity)
- **Dockerfile** — python:3.12-slim with CPU-only torch pre-installed
- **.env.example** — template with all 7 env vars
- **README.md** — <30 lines: what it does, CLI modes, env table, volume notes

### Key design decisions
- UUID5 namespace fixed at `b3d1c2a0-4f5e-6789-abcd-ef0123456789` for point stability
- Sparse vector upsert uses `SparseVector(indices, values)` in PointStruct vector dict
  (not `NamedSparseVector` which is query-side only)
- `lexical_weights` keys cast to `int`, zero-weight entries skipped
- Pagination loops on all 3 Notion endpoints (search, db query, blocks.list)
- Rate limit sleep before (not inside) retried function
