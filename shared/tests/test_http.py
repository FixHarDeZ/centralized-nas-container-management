"""Tests for the shared HTTP retry module — the interface is the test surface.

A fake adapter is injected at the transport seam so no network is hit.
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from http_client import get, post  # noqa: E402

import httpx


class MockAdapter:
    """Fake httpx transport. Returns pre-configured responses in order."""

    def __init__(self, responses):
        self._responses = list(responses)
        self._call_count = 0
        self.calls = []

    def send(self, request, **kwargs):
        self._call_count += 1
        self.calls.append({"request": request, "kwargs": kwargs})
        resp = self._responses.pop(0)
        return resp


def _make_response(status_code=200, text="ok"):
    """Build a minimal httpx.Response for testing."""
    return httpx.Response(
        status_code=status_code,
        content=text.encode(),
        request=httpx.Request("GET", "http://test.com"),
    )


def _make_error(status_code):
    resp = _make_response(status_code)
    resp.raise_for_status()
    return resp


def test_get_returns_response():
    adapter = MockAdapter([_make_response(200, "hello")])
    resp = get("http://test.com", _adapter=adapter)
    assert resp.status_code == 200
    assert resp.text == "hello"
    assert adapter._call_count == 1


def test_get_retries_on_429(monkeypatch):
    adapter = MockAdapter([_make_response(429), _make_response(200, "ok")])
    monkeypatch.setattr(time, "sleep", lambda _: None)
    resp = get("http://test.com", retries=3, backoff=1.0, _adapter=adapter)
    assert resp.status_code == 200
    assert adapter._call_count == 2


def test_get_no_retry_on_404():
    adapter = MockAdapter([_make_response(404)])
    try:
        get("http://test.com", retries=3, _adapter=adapter)
        assert False, "should have raised"
    except httpx.HTTPStatusError as e:
        assert e.response.status_code == 404
    assert adapter._call_count == 1


def test_get_retries_on_500(monkeypatch):
    adapter = MockAdapter([_make_response(500), _make_response(200)])
    monkeypatch.setattr(time, "sleep", lambda _: None)
    resp = get("http://test.com", retries=3, backoff=1.0, _adapter=adapter)
    assert resp.status_code == 200
    assert adapter._call_count == 2


def test_get_exhausted_retries_raises(monkeypatch):
    adapter = MockAdapter([_make_response(429), _make_response(429), _make_response(429)])
    monkeypatch.setattr(time, "sleep", lambda _: None)
    try:
        get("http://test.com", retries=3, backoff=1.0, _adapter=adapter)
        assert False, "should have raised"
    except httpx.HTTPStatusError as e:
        assert e.response.status_code == 429
    assert adapter._call_count == 3


def test_get_custom_retry_on(monkeypatch):
    adapter = MockAdapter([_make_response(503), _make_response(200)])
    monkeypatch.setattr(time, "sleep", lambda _: None)
    resp = get("http://test.com", retries=3, backoff=1.0, _adapter=adapter)
    assert resp.status_code == 200


def test_post_returns_response():
    adapter = MockAdapter([_make_response(200, '{"ok":true}')])
    resp = post("http://test.com", json={"a": 1}, _adapter=adapter)
    assert resp.status_code == 200
    assert adapter._call_count == 1


def test_post_retries_on_429(monkeypatch):
    adapter = MockAdapter([_make_response(429), _make_response(200)])
    monkeypatch.setattr(time, "sleep", lambda _: None)
    resp = post("http://test.com", retries=3, backoff=1.0, _adapter=adapter)
    assert resp.status_code == 200
    assert adapter._call_count == 2


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-v"]))
