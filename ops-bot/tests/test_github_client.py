import base64
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.github_client import create_fix_pr


@pytest.fixture
def gh_config(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    monkeypatch.setenv("GITHUB_REPO", "owner/repo")
    import app.config
    app.config._config = None
    yield
    app.config._config = None


def _resp(status, payload=None, text=""):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload or {}
    r.text = text
    return r


def _b64(s):
    return base64.b64encode(s.encode()).decode()


def _next(calls, method):
    m, resp = next(calls)
    assert m == method, f"expected call {m}, got {method}"
    return resp


def _client_with(sequence):
    """sequence: list of (method, response) consumed in call order.
    Each get/post/put pops the next entry and asserts the method matches."""
    calls = iter(sequence)
    client = MagicMock()
    client.get = AsyncMock(side_effect=lambda *a, **k: _next(calls, "get"))
    client.post = AsyncMock(side_effect=lambda *a, **k: _next(calls, "post"))
    client.put = AsyncMock(side_effect=lambda *a, **k: _next(calls, "put"))
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=client)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


@pytest.mark.asyncio
async def test_create_fix_pr_happy_path(gh_config):
    seq = [
        ("get", _resp(200, {"default_branch": "main"})),                 # repo
        ("get", _resp(200, {"object": {"sha": "base123"}})),             # base ref
        ("post", _resp(201, {})),                                        # create branch
        ("get", _resp(200, {"content": _b64("mem_limit: 3g\n"), "sha": "blob1"})),  # get file
        ("put", _resp(200, {})),                                         # put file
        ("post", _resp(201, {"html_url": "https://github.com/owner/repo/pull/7"})), # PR
    ]
    with patch("app.github_client.httpx.AsyncClient", return_value=_client_with(seq)):
        ok, url = await create_fix_pr(1, "bump mem", [{"path": "homepage/docker-compose.yml", "find": "mem_limit: 3g", "replace": "mem_limit: 5g"}])
    assert ok is True
    assert url == "https://github.com/owner/repo/pull/7"


@pytest.mark.asyncio
async def test_create_fix_pr_find_not_present(gh_config):
    seq = [
        ("get", _resp(200, {"default_branch": "main"})),
        ("get", _resp(200, {"object": {"sha": "base123"}})),
        ("post", _resp(201, {})),
        ("get", _resp(200, {"content": _b64("mem_limit: 8g\n"), "sha": "blob1"})),  # find missing
    ]
    with patch("app.github_client.httpx.AsyncClient", return_value=_client_with(seq)):
        ok, msg = await create_fix_pr(1, "bump", [{"path": "x.yml", "find": "mem_limit: 3g", "replace": "mem_limit: 5g"}])
    assert ok is False
    assert "ไม่เจอ" in msg


@pytest.mark.asyncio
async def test_create_fix_pr_file_missing(gh_config):
    seq = [
        ("get", _resp(200, {"default_branch": "main"})),
        ("get", _resp(200, {"object": {"sha": "base123"}})),
        ("post", _resp(201, {})),
        ("get", _resp(404, {}, "not found")),
    ]
    with patch("app.github_client.httpx.AsyncClient", return_value=_client_with(seq)):
        ok, msg = await create_fix_pr(1, "x", [{"path": "nope.yml", "find": "a", "replace": "b"}])
    assert ok is False


@pytest.mark.asyncio
async def test_create_fix_pr_no_config(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_REPO", raising=False)
    import app.config
    app.config._config = None
    ok, msg = await create_fix_pr(1, "x", [{"path": "a", "find": "b", "replace": "c"}])
    assert ok is False
    app.config._config = None


@pytest.mark.asyncio
async def test_create_fix_pr_no_changes(gh_config):
    ok, msg = await create_fix_pr(1, "x", [])
    assert ok is False
