# Secretary Stack — Daily Log

---

## 2026-05-27 — Notion→Qdrant Ingest Service (secretary-ingest)

### งานที่ทำ
สร้าง `secretary-ingest` service ใหม่ทั้งหมด: Python CLI ที่ sync Notion pages เข้า Qdrant collection `secretary_notes` ด้วย hybrid search (dense 1024d + sparse vectors) โดยใช้ BGE-M3 ผ่าน FlagEmbedding

### ไฟล์ที่สร้าง/แก้ไข
- `secretary/ingest.py` — single-file CLI ครอบคลุมทุก section (CONFIG, STATE DB, NOTION, CONVERT, CHUNK, EMBED, QDRANT, SYNC, CLI)
- `secretary/requirements.txt` — dependencies
- `secretary/Dockerfile` — python:3.12-slim + build-essential สำหรับ FlagEmbedding
- `secretary/.env.example` — config template
- `secretary/tests/` — test suite 67 tests ครอบคลุมทุก section
- `secretary/docker-compose.yml` — เพิ่ม `secretary-ingest` service + `hf_cache` volume
- `secretary/README.md` — setup + n8n trigger docs

### Decisions
- **FlagEmbedding-only** (ไม่ใช้ Ollama สำหรับ embeddings) — BGEM3FlagModel produce ทั้ง dense+sparse ใน one pass
- **n8n trigger** — Schedule Trigger + Execute Command node
- **Custom block converter** — ไม่ใช้ notion2md library

### Bug fixes ที่พบระหว่าง implement
- notion-client v3 ลบ `databases.query()` ออก — ใช้ `client.request()` แทน
- Module-level `NOTION_SOURCE_TYPE` global ต้อง patch ด้วย `@patch("ingest.NOTION_SOURCE_TYPE", ...)` ไม่ใช่ `os.environ`
- `_conn()` ใน test_sync.py ต้อง capture `init_db` ก่อน mock เพราะ `test_run_incremental_deletes_removed_pages` mock `ingest.init_db`

### Test results
67 tests passed, 0 failed

### Next steps
- Deploy ไป NAS แล้วทดสอบ real Notion token
- ตั้ง n8n workflow สำหรับ scheduled sync
- ทดสอบ Docker build บน NAS (Docker daemon ไม่ได้ run locally)
