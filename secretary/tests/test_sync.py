# secretary/tests/test_sync.py
import sqlite3
from unittest.mock import MagicMock, patch
from qdrant_client.http.models import SparseVector
import ingest

# Capture the real init_db before any @patch decorator can replace it.
# Without this, _conn() inside test_run_incremental_deletes_removed_pages
# would call the mock (already active when the function body runs) and
# return a MagicMock instead of a real sqlite connection.
_REAL_INIT_DB = ingest.init_db


def _conn():
    return _REAL_INIT_DB(":memory:")


def _page(page_id: str = "p1", title: str = "Page", ts: str = "2025-01-01T00:00:00.000Z") -> dict:
    return {
        "id": page_id, "title": title, "url": "https://notion.so/p1",
        "last_edited_time": ts, "parent_id": "", "parent_type": "workspace", "tags": [],
    }


def _mock_embeddings(n: int) -> dict:
    return {
        "dense": [[0.1] * 1024 for _ in range(n)],
        "sparse": [SparseVector(indices=[0], values=[0.5]) for _ in range(n)],
    }


@patch("ingest.upsert_chunks")
@patch("ingest.embed_chunks")
@patch("ingest.chunk_markdown")
@patch("ingest.blocks_to_markdown")
@patch("ingest.fetch_blocks")
def test_sync_page_new(mock_fetch, mock_md, mock_chunk, mock_embed, mock_upsert):
    conn = _conn()
    mock_fetch.return_value = []
    mock_md.return_value = "## Section\nContent here."
    mock_chunk.return_value = [{"text": "Content here.", "breadcrumb": "Page > Section", "chunk_index": 0}]
    mock_embed.return_value = _mock_embeddings(1)
    result = ingest.sync_page(_page(), conn)
    assert result["status"] == "updated"
    assert result["chunks"] == 1
    mock_upsert.assert_called_once()
    assert ingest.get_state(conn, "p1") is not None


@patch("ingest.upsert_chunks")
@patch("ingest.embed_chunks")
@patch("ingest.chunk_markdown")
@patch("ingest.blocks_to_markdown")
@patch("ingest.fetch_blocks")
def test_sync_page_unchanged_skips(mock_fetch, mock_md, mock_chunk, mock_embed, mock_upsert):
    conn = _conn()
    ingest.upsert_state(conn, "p1", "2025-01-01T00:00:00.000Z", 3)
    result = ingest.sync_page(_page("p1", ts="2025-01-01T00:00:00.000Z"), conn)
    assert result["status"] == "skipped"
    mock_fetch.assert_not_called()
    mock_upsert.assert_not_called()


@patch("ingest.delete_page_points")
@patch("ingest.upsert_chunks")
@patch("ingest.embed_chunks")
@patch("ingest.chunk_markdown")
@patch("ingest.blocks_to_markdown")
@patch("ingest.fetch_blocks")
def test_sync_page_changed_deletes_old_points(mock_fetch, mock_md, mock_chunk, mock_embed, mock_upsert, mock_delete):
    conn = _conn()
    ingest.upsert_state(conn, "p1", "2025-01-01T00:00:00.000Z", 3)
    mock_fetch.return_value = []
    mock_md.return_value = "## New\nUpdated content."
    mock_chunk.return_value = [{"text": "Updated content.", "breadcrumb": "Page > New", "chunk_index": 0}]
    mock_embed.return_value = _mock_embeddings(1)
    result = ingest.sync_page(_page("p1", ts="2025-06-01T00:00:00.000Z"), conn)
    assert result["status"] == "updated"
    mock_delete.assert_called_once_with("p1")


@patch("ingest.upsert_chunks")
@patch("ingest.embed_chunks")
@patch("ingest.chunk_markdown")
@patch("ingest.blocks_to_markdown")
@patch("ingest.fetch_blocks")
def test_sync_page_empty_skips(mock_fetch, mock_md, mock_chunk, mock_embed, mock_upsert):
    conn = _conn()
    mock_fetch.return_value = []
    mock_md.return_value = ""
    result = ingest.sync_page(_page(), conn)
    assert result["status"] == "skipped"
    mock_upsert.assert_not_called()


@patch("ingest.fetch_blocks")
def test_sync_page_error_returns_error_status(mock_fetch):
    conn = _conn()
    mock_fetch.side_effect = RuntimeError("network failure")
    result = ingest.sync_page(_page(), conn)
    assert result["status"] == "error"
    assert "network failure" in result["error"]


@patch("ingest.upsert_chunks")
@patch("ingest.embed_chunks")
@patch("ingest.chunk_markdown")
@patch("ingest.blocks_to_markdown")
@patch("ingest.fetch_blocks")
def test_sync_page_dry_run_no_writes(mock_fetch, mock_md, mock_chunk, mock_embed, mock_upsert):
    conn = _conn()
    mock_fetch.return_value = []
    mock_md.return_value = "## Section\nContent."
    mock_chunk.return_value = [{"text": "Content.", "breadcrumb": "Page > Section", "chunk_index": 0}]
    mock_embed.return_value = _mock_embeddings(1)
    ingest.sync_page(_page(), conn, dry_run=True)
    mock_upsert.assert_called_once()
    assert mock_upsert.call_args[1].get("dry_run") is True
    assert ingest.get_state(conn, "p1") is None


@patch("ingest.sync_page")
@patch("ingest.delete_page_points")
@patch("ingest.delete_state")
@patch("ingest.ensure_collection")
@patch("ingest.list_pages")
@patch("ingest.init_db")
def test_run_incremental_deletes_removed_pages(
    mock_db, mock_list, mock_ensure, mock_del_state, mock_del_points, mock_sync
):
    conn = _conn()
    ingest.upsert_state(conn, "old_page", "2025-01-01T00:00:00.000Z", 2)
    mock_db.return_value = conn
    mock_list.return_value = []
    mock_sync.return_value = {"status": "skipped", "chunks": 0}
    ingest.run_incremental()
    mock_del_points.assert_called_once_with("old_page")
    mock_del_state.assert_called_once_with(conn, "old_page")
