# secretary/tests/test_qdrant.py
import uuid
import numpy as np
from unittest.mock import MagicMock, patch
from qdrant_client.http.models import SparseVector
import ingest


def _make_embeddings(n: int) -> dict:
    return {
        "dense": np.random.rand(n, 1024).tolist(),
        "sparse": [SparseVector(indices=[0, 1], values=[0.5, 0.3]) for _ in range(n)],
    }


def _make_page_meta(page_id: str = "p1") -> dict:
    return {
        "id": page_id,
        "title": "Test Page",
        "url": "https://notion.so/test",
        "last_edited_time": "2025-01-01T00:00:00.000Z",
        "parent_id": "",
        "parent_type": "workspace",
        "tags": ["work"],
    }


def _make_chunks(n: int) -> list[dict]:
    return [
        {"text": f"chunk {i}", "breadcrumb": f"Test Page > Section {i}", "chunk_index": i}
        for i in range(n)
    ]


@patch("ingest._qdrant")
def test_ensure_collection_creates_if_absent(mock_qdrant_fn):
    client = MagicMock()
    client.get_collections.return_value.collections = []
    mock_qdrant_fn.return_value = client
    ingest.ensure_collection()
    client.create_collection.assert_called_once()
    call_kwargs = client.create_collection.call_args[1]
    assert call_kwargs["collection_name"] == "secretary_notes"
    assert "dense" in call_kwargs["vectors_config"]
    assert "sparse" in call_kwargs["sparse_vectors_config"]


@patch("ingest._qdrant")
def test_ensure_collection_skips_if_exists(mock_qdrant_fn):
    client = MagicMock()
    existing = MagicMock()
    existing.name = "secretary_notes"
    client.get_collections.return_value.collections = [existing]
    mock_qdrant_fn.return_value = client
    ingest.ensure_collection()
    client.create_collection.assert_not_called()


@patch("ingest._qdrant")
def test_delete_page_points(mock_qdrant_fn):
    client = MagicMock()
    mock_qdrant_fn.return_value = client
    ingest.delete_page_points("page123")
    client.delete.assert_called_once()
    call_kwargs = client.delete.call_args[1]
    assert call_kwargs["collection_name"] == "secretary_notes"


@patch("ingest._qdrant")
def test_upsert_chunks_sends_correct_count(mock_qdrant_fn):
    client = MagicMock()
    mock_qdrant_fn.return_value = client
    chunks = _make_chunks(3)
    embeddings = _make_embeddings(3)
    ingest.upsert_chunks(_make_page_meta(), chunks, embeddings)
    client.upsert.assert_called_once()
    points = client.upsert.call_args[1]["points"]
    assert len(points) == 3


@patch("ingest._qdrant")
def test_upsert_chunks_payload_fields(mock_qdrant_fn):
    client = MagicMock()
    mock_qdrant_fn.return_value = client
    chunks = _make_chunks(1)
    embeddings = _make_embeddings(1)
    meta = _make_page_meta("abc123")
    ingest.upsert_chunks(meta, chunks, embeddings)
    point = client.upsert.call_args[1]["points"][0]
    assert point.payload["source"] == "notion"
    assert point.payload["page_id"] == "abc123"
    assert point.payload["tags"] == ["work"]
    assert "dense" in point.vector
    assert "sparse" in point.vector


@patch("ingest._qdrant")
def test_upsert_chunks_dry_run_skips_write(mock_qdrant_fn):
    client = MagicMock()
    mock_qdrant_fn.return_value = client
    ingest.upsert_chunks(_make_page_meta(), _make_chunks(2), _make_embeddings(2), dry_run=True)
    client.upsert.assert_not_called()


@patch("ingest._qdrant")
def test_upsert_chunks_deterministic_id(mock_qdrant_fn):
    client = MagicMock()
    mock_qdrant_fn.return_value = client
    chunks = _make_chunks(1)
    embeddings = _make_embeddings(1)
    ingest.upsert_chunks(_make_page_meta("pid"), chunks, embeddings)
    point = client.upsert.call_args[1]["points"][0]
    expected_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, "pid0"))
    assert point.id == expected_id
