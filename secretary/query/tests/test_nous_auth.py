import importlib
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_manager(monkeypatch, tmp_path):
    """Reload nous_auth with a temp token file path and return a fresh NousTokenManager."""
    monkeypatch.setenv("NOUS_TOKEN_FILE", str(tmp_path / "nous_token.json"))
    import nous_auth

    importlib.reload(nous_auth)
    return nous_auth.NousTokenManager()


@pytest.mark.asyncio
async def test_start_device_flow_returns_fields(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)

    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {
        "device_code": "dev-code-123",
        "user_code": "ABCD-1234",
        "verification_uri": "https://portal.nousresearch.com/manage-subscription?user_code=ABCD-1234",
        "expires_in": 300,
        "interval": 5,
    }

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = AsyncMock(return_value=fake_resp)

    import nous_auth

    with patch.object(nous_auth.httpx, "AsyncClient", return_value=mock_http):
        result = await manager.start_device_flow()

    assert result["authenticated"] is False
    assert result["user_code"] == "ABCD-1234"
    assert "verification_uri" in result
    assert result["expires_in"] == 300
    assert "message" in result


@pytest.mark.asyncio
async def test_start_device_flow_already_authenticated(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    manager._tokens = {
        "access_token": "valid-token",
        "refresh_token": "ref",
        "expires_at": int(time.time()) + 3600,
    }

    result = await manager.start_device_flow()

    assert result["authenticated"] is True


@pytest.mark.asyncio
async def test_get_access_token_returns_valid_token(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    manager._tokens = {
        "access_token": "good-token",
        "refresh_token": "ref",
        "expires_at": int(time.time()) + 3600,
    }

    token = await manager.get_access_token()

    assert token == "good-token"


@pytest.mark.asyncio
async def test_get_access_token_refreshes_when_expired(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    manager._tokens = {
        "access_token": "old-token",
        "refresh_token": "refresh-abc",
        "expires_at": int(time.time()) - 100,
    }

    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {
        "access_token": "new-token",
        "refresh_token": "new-refresh",
        "expires_in": 3600,
    }

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = AsyncMock(return_value=fake_resp)

    import nous_auth

    with patch.object(nous_auth.httpx, "AsyncClient", return_value=mock_http):
        token = await manager.get_access_token()

    assert token == "new-token"
    assert manager._tokens["access_token"] == "new-token"
    assert manager._tokens["refresh_token"] == "new-refresh"


@pytest.mark.asyncio
async def test_get_access_token_raises_when_no_tokens(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    manager._tokens = None

    with pytest.raises(RuntimeError, match="Nous not authenticated"):
        await manager.get_access_token()


def test_save_load_roundtrip(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    tokens = {
        "access_token": "tok-abc",
        "refresh_token": "ref-xyz",
        "expires_at": 9999999999,
    }
    manager._save(tokens)

    import nous_auth

    importlib.reload(nous_auth)
    manager2 = nous_auth.NousTokenManager()
    assert manager2._tokens == tokens


def test_auth_status_unauthenticated(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    manager._tokens = None

    status = manager.auth_status()

    assert status == {"authenticated": False, "expires_at": None}


def test_auth_status_authenticated(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)
    future_ts = int(time.time()) + 3600
    manager._tokens = {
        "access_token": "tok",
        "refresh_token": "ref",
        "expires_at": future_ts,
    }

    status = manager.auth_status()

    assert status["authenticated"] is True
    assert status["expires_at"] == future_ts


@pytest.mark.asyncio
async def test_poll_for_token_saves_on_success(monkeypatch, tmp_path):
    manager = _make_manager(monkeypatch, tmp_path)

    # First response: 400 authorization_pending, second: 200 success
    pending_resp = MagicMock()
    pending_resp.status_code = 400

    success_resp = MagicMock()
    success_resp.status_code = 200
    success_resp.json.return_value = {
        "access_token": "polled-token",
        "refresh_token": "polled-refresh",
        "expires_in": 3600,
    }

    mock_http = AsyncMock()
    mock_http.__aenter__ = AsyncMock(return_value=mock_http)
    mock_http.__aexit__ = AsyncMock(return_value=False)
    mock_http.post = AsyncMock(side_effect=[pending_resp, success_resp])

    import nous_auth

    with patch.object(nous_auth.httpx, "AsyncClient", return_value=mock_http):
        with patch("asyncio.sleep", new_callable=AsyncMock):
            await manager._poll_for_token("dev-code", interval=1, expires_in=60)

    assert manager._tokens is not None
    assert manager._tokens["access_token"] == "polled-token"
    assert manager._tokens["refresh_token"] == "polled-refresh"
