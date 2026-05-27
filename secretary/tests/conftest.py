import os
os.environ.setdefault("NOTION_TOKEN", "test_token")
os.environ.setdefault("QDRANT_URL", "http://localhost:6333")
os.environ.setdefault("COLLECTION_NAME", "secretary_notes")
os.environ.setdefault("STATE_DB", "/tmp/test_ingest_state.db")
os.environ.setdefault("NOTION_SOURCE_TYPE", "search")
os.environ.setdefault("NOTION_DATABASE_ID", "")
os.environ.setdefault("NOTION_ROOT_PAGE_ID", "")
