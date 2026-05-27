# secretary/tests/test_embed.py
import numpy as np
from unittest.mock import MagicMock, patch
import ingest


def _mock_model(n: int):
    model = MagicMock()
    model.encode.return_value = {
        "dense_vecs": np.random.rand(n, 1024).astype(np.float32),
        "lexical_weights": [{0: 0.5, 1: 0.3} for _ in range(n)],
    }
    return model


def test_embed_chunks_empty():
    result = ingest.embed_chunks([])
    assert result == {"dense": [], "sparse": []}


@patch("ingest.load_model")
def test_embed_chunks_returns_correct_structure(mock_load):
    mock_load.return_value = _mock_model(3)
    result = ingest.embed_chunks(["text1", "text2", "text3"])
    assert len(result["dense"]) == 3
    assert len(result["sparse"]) == 3
    assert len(result["dense"][0]) == 1024


@patch("ingest.load_model")
def test_embed_chunks_sparse_vector_structure(mock_load):
    mock_load.return_value = _mock_model(1)
    result = ingest.embed_chunks(["hello world"])
    sparse = result["sparse"][0]
    assert hasattr(sparse, "indices")
    assert hasattr(sparse, "values")
    assert all(isinstance(v, float) for v in sparse.values)


@patch("ingest.load_model")
def test_embed_chunks_calls_model_once(mock_load):
    model = _mock_model(2)
    mock_load.return_value = model
    ingest.embed_chunks(["a", "b"])
    model.encode.assert_called_once()
    call_args = model.encode.call_args
    assert call_args[0][0] == ["a", "b"]
    assert call_args[1].get("return_dense") is True
    assert call_args[1].get("return_sparse") is True
