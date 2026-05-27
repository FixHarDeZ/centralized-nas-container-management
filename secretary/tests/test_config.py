"""Tests for CONFIG section in ingest.py."""


def test_import_succeeds():
    """Verify ingest module imports and CONFIG is loaded from env."""
    import ingest
    assert ingest.QDRANT_URL == "http://localhost:6333"
    assert ingest.COLLECTION_NAME == "secretary_notes"
    assert ingest.NOTION_TOKEN == "test_token"
    assert ingest.STATE_DB == "/tmp/test_ingest_state.db"
    assert ingest.NOTION_SOURCE_TYPE == "search"
