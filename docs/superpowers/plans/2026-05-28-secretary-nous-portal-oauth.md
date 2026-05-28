# Secretary Query — Nous Portal OAuth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `norus` LLM provider in `secretary/query` with `nous` (Nous Portal), using OAuth 2.0 Device Code flow for authentication and Nous's OpenAI-compatible inference API.

**Architecture:** Add `nous_auth.py` as a standalone token manager that handles Device Code OAuth, token persistence to `/data/nous_token.json`, and auto-refresh. `llm_client.py` calls `token_manager.get_access_token()` then creates an `AsyncOpenAI` client with the Bearer token. Two new FastAPI endpoints (`GET /nous/auth`, `GET /nous/auth/status`) expose the auth flow to the operator.

**Tech Stack:** Python 3.12, FastAPI, `httpx` (already in requirements.txt), `openai` SDK (already in requirements.txt), pytest-asyncio

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `secretary/query/nous_auth.py` | **CREATE** | NousTokenManager: Device Code flow, token persistence, auto-refresh |
| `secretary/query/llm_client.py` | **MODIFY** | Remove norus block; rename `_openai_client`→`_openrouter_client`; add nous block |
| `secretary/query/main.py` | **MODIFY** | Import nous_auth; remove norus from `_active_model_name`; add 2 endpoints |
| `secretary/query/.env.example` | **MODIFY** | Remove NORUS_* vars; add `NOUS_MODEL` |
| `secretary/query/tests/test_llm_client.py` | **MODIFY** | Update `_reload` helper; remove test_norus; update openrouter patch target; add test_nous |
| `secretary/query/tests/test_nous_auth.py` | **CREATE** | Tests for NousTokenManager (device flow, token save/load, refresh, status, error) |
| `secretary/query/tests/test_main.py` | **MODIFY** | Add tests for GET /nous/auth and GET /nous/auth/status |

**Working directory for all commands:** `secretary/query/`

---

## Task 1: Remove norus from llm_client.py and tests

Rename `_openai_client` → `_openrouter_client`, remove the norus provider block, update tests accordingly.

**Files:**
- Modify: `secretary/query/llm_client.py`
- Modify: `secretary/query/tests/test_llm_client.py`

- [ ] **Step 1.1: Update test_llm_client.py — fix _reload helper and openrouter patch target**

Replace the entire content of `secretary/query/tests/test_llm_client.py`:

```python
import importlib
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _reload(monkeypatch, provider: str):
    """Reload llm_client with the given LLM_PROVIDER env var."""
    monkeypatch.setenv("LLM_PROVIDER", provider)
    import llm_client as m
    importlib.reload(m)
    m._openrouter_client = None  # reset singleton to ensure clean state per test
    return m


@pytest.mark.asyncio
async def test_anthropic_returns_text(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-test")
    m = _reload(monkeypatch, "anthropic")

    fake_content = MagicMock()
    fake_content.text = "hello from anthropic"
    fake_msg = MagicMock()
    fake_msg.content = [fake_content]
    fake_client = MagicMock()
    fake_client.messages.create = AsyncMock(return_value=fake_msg)

    with patch.object(m, "_anthropic_client", fake_client):
        result = await m.get_llm_response("system", "user")

    assert result == "hello from anthropic"
    fake_client.messages.create.assert_awaited_once()
    call_kwargs = fake_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-test"
    assert call_kwargs["system"] == "system"
    assert call_kwargs["messages"] == [{"role": "user", "content": "user"}]


@pytest.mark.asyncio
async def test_openrouter_returns_text(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-test")
    monkeypatch.setenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
    m = _reload(monkeypatch, "openrouter")

    fake_choice = MagicMock()
    fake_choice.message.content = "hello from openrouter"
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(return_value=fake_resp)

    with patch.object(m, "_openrouter_client", fake_client):
        result = await m.get_llm_response("system", "user")

    assert result == "hello from openrouter"
    fake_client.chat.completions.create.assert_awaited_once()
    call_kwargs = fake_client.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "anthropic/claude-test"
    assert call_kwargs["messages"][0] == {"role": "system", "content": "system"}
    assert call_kwargs["messages"][1] == {"role": "user", "content": "user"}


@pytest.mark.asyncio
async def test_unknown_provider_raises(monkeypatch):
    m = _reload(monkeypatch, "unknown-xyz")
    with pytest.raises(ValueError, match="unknown-xyz"):
        await m.get_llm_response("system", "user")
```

- [ ] **Step 1.2: Run updated tests — expect test_norus to be gone, others to fail**

```bash
cd secretary/query && python -m pytest tests/test_llm_client.py -v
```

Expected: `test_anthropic_returns_text` FAILS (AttributeError on `_openrouter_client`), `test_openrouter_returns_text` FAILS (same). `test_norus_returns_text` should no longer exist. This confirms the tests are updated correctly before we fix the code.

- [ ] **Step 1.3: Update llm_client.py — remove norus, rename _openai_client**

Replace the entire content of `secretary/query/llm_client.py`:

```python
import os
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI


_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")

_anthropic_client: AsyncAnthropic | None = None
_openrouter_client: AsyncOpenAI | None = None


def _get_anthropic() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _anthropic_client


def _get_openrouter() -> AsyncOpenAI:
    global _openrouter_client
    if _openrouter_client is None:
        _openrouter_client = AsyncOpenAI(
            base_url=os.environ["OPENROUTER_BASE_URL"],
            api_key=os.environ["OPENROUTER_API_KEY"],
        )
    return _openrouter_client


async def get_llm_response(system: str, user: str) -> str:
    if _PROVIDER == "anthropic":
        client = _get_anthropic()
        model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        msg = await client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text

    if _PROVIDER == "openrouter":
        client = _get_openrouter()
        model = os.environ["OPENROUTER_MODEL"]
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        if not resp.choices:
            error_detail = getattr(resp, "error", None) or "null choices"
            raise RuntimeError(f"OpenRouter returned no choices: {error_detail}")
        return resp.choices[0].message.content or ""

    raise ValueError(f"Unknown LLM_PROVIDER: {_PROVIDER!r}")
```

- [ ] **Step 1.4: Run tests — all 3 should pass**

```bash
cd secretary/query && python -m pytest tests/test_llm_client.py -v
```

Expected:
```
PASSED tests/test_llm_client.py::test_anthropic_returns_text
PASSED tests/test_llm_client.py::test_openrouter_returns_text
PASSED tests/test_llm_client.py::test_unknown_provider_raises
```

- [ ] **Step 1.5: Commit**

```bash
git add secretary/query/llm_client.py secretary/query/tests/test_llm_client.py
git commit -m "refactor(secretary): remove norus provider, rename _openai_client to _openrouter_client"
```

---

## Task 2: Create nous_auth.py (TDD)

New module handling OAuth Device Code flow, token persistence to `/data/nous_token.json`, and auto-refresh.

**Files:**
- Create: `secretary/query/nous_auth.py`
- Create: `secretary/query/tests/test_nous_auth.py`

- [ ] **Step 2.1: Write failing tests — create test_nous_auth.py**

Create `secretary/query/tests/test_nous_auth.py`:

```python
import importlib
import json
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


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
```

- [ ] **Step 2.2: Run tests — all should FAIL with ImportError**

```bash
cd secretary/query && python -m pytest tests/test_nous_auth.py -v
```

Expected: `ModuleNotFoundError: No module named 'nous_auth'` on every test.

- [ ] **Step 2.3: Create nous_auth.py**

Create `secretary/query/nous_auth.py`:

```python
import asyncio
import json
import os
import time
from pathlib import Path

import httpx

_DEVICE_CODE_URL = "https://portal.nousresearch.com/api/oauth/device/code"
_TOKEN_URL = "https://portal.nousresearch.com/api/oauth/token"
_CLIENT_ID = "hermes-cli"
_REFRESH_BUFFER_SECS = 60


def _token_file() -> Path:
    return Path(os.getenv("NOUS_TOKEN_FILE", "/data/nous_token.json"))


class NousTokenManager:
    def __init__(self):
        self._tokens: dict | None = None
        self._poll_task: asyncio.Task | None = None
        self._load()

    def _load(self):
        path = _token_file()
        if path.exists():
            try:
                self._tokens = json.loads(path.read_text())
            except Exception:
                self._tokens = None

    def _save(self, tokens: dict):
        self._tokens = tokens
        path = _token_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(tokens))
        tmp.replace(path)

    def _is_valid(self) -> bool:
        return bool(
            self._tokens
            and self._tokens.get("expires_at", 0) > time.time() + _REFRESH_BUFFER_SECS
        )

    async def start_device_flow(self) -> dict:
        if self._is_valid():
            return {"authenticated": True, "message": "Already authenticated"}

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _DEVICE_CODE_URL,
                json={"client_id": _CLIENT_ID, "scope": "inference:invoke"},
            )
            resp.raise_for_status()
            data = resp.json()

        device_code = data["device_code"]
        interval = int(data.get("interval", 5))
        expires_in = int(data["expires_in"])

        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
        self._poll_task = asyncio.create_task(
            self._poll_for_token(device_code, interval, expires_in)
        )

        return {
            "authenticated": False,
            "verification_uri": data["verification_uri"],
            "user_code": data["user_code"],
            "expires_in": expires_in,
            "message": f"Open {data['verification_uri']} and enter code: {data['user_code']}",
        }

    async def _poll_for_token(self, device_code: str, interval: int, expires_in: int):
        deadline = time.time() + expires_in
        async with httpx.AsyncClient() as client:
            while time.time() < deadline:
                await asyncio.sleep(interval)
                try:
                    resp = await client.post(
                        _TOKEN_URL,
                        json={
                            "client_id": _CLIENT_ID,
                            "device_code": device_code,
                            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                        },
                    )
                    if resp.status_code == 200:
                        d = resp.json()
                        self._save({
                            "access_token": d["access_token"],
                            "refresh_token": d["refresh_token"],
                            "expires_at": int(time.time()) + int(d["expires_in"]),
                        })
                        return
                    if resp.status_code != 400:
                        return
                except Exception:
                    return

    async def get_access_token(self) -> str:
        if not self._tokens:
            raise RuntimeError("Nous not authenticated — call GET /nous/auth first")
        if not self._is_valid():
            await self._refresh()
        return self._tokens["access_token"]

    async def _refresh(self):
        if not self._tokens or not self._tokens.get("refresh_token"):
            raise RuntimeError("Nous not authenticated — call GET /nous/auth first")
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                _TOKEN_URL,
                json={
                    "client_id": _CLIENT_ID,
                    "refresh_token": self._tokens["refresh_token"],
                    "grant_type": "refresh_token",
                },
            )
            resp.raise_for_status()
            d = resp.json()
        self._save({
            "access_token": d["access_token"],
            "refresh_token": d.get("refresh_token", self._tokens["refresh_token"]),
            "expires_at": int(time.time()) + int(d["expires_in"]),
        })

    def auth_status(self) -> dict:
        if not self._tokens:
            return {"authenticated": False, "expires_at": None}
        expires_at = self._tokens.get("expires_at")
        authenticated = bool(expires_at and expires_at > time.time())
        return {"authenticated": authenticated, "expires_at": expires_at}


token_manager = NousTokenManager()
```

- [ ] **Step 2.4: Run tests — all 8 should pass**

```bash
cd secretary/query && python -m pytest tests/test_nous_auth.py -v
```

Expected:
```
PASSED tests/test_nous_auth.py::test_start_device_flow_returns_fields
PASSED tests/test_nous_auth.py::test_start_device_flow_already_authenticated
PASSED tests/test_nous_auth.py::test_get_access_token_returns_valid_token
PASSED tests/test_nous_auth.py::test_get_access_token_refreshes_when_expired
PASSED tests/test_nous_auth.py::test_get_access_token_raises_when_no_tokens
PASSED tests/test_nous_auth.py::test_save_load_roundtrip
PASSED tests/test_nous_auth.py::test_auth_status_unauthenticated
PASSED tests/test_nous_auth.py::test_auth_status_authenticated
```

- [ ] **Step 2.5: Commit**

```bash
git add secretary/query/nous_auth.py secretary/query/tests/test_nous_auth.py
git commit -m "feat(secretary): add NousTokenManager with Device Code OAuth flow"
```

---

## Task 3: Add nous provider to llm_client.py (TDD)

**Files:**
- Modify: `secretary/query/llm_client.py`
- Modify: `secretary/query/tests/test_llm_client.py`

- [ ] **Step 3.1: Add test_nous_returns_text to test_llm_client.py**

Append this test to `secretary/query/tests/test_llm_client.py` (after `test_unknown_provider_raises`):

```python
@pytest.mark.asyncio
async def test_nous_returns_text(monkeypatch):
    monkeypatch.setenv("NOUS_MODEL", "Hermes-4-test")
    m = _reload(monkeypatch, "nous")

    fake_choice = MagicMock()
    fake_choice.message.content = "hello from nous"
    fake_resp = MagicMock()
    fake_resp.choices = [fake_choice]
    fake_openai_instance = MagicMock()
    fake_openai_instance.chat.completions.create = AsyncMock(return_value=fake_resp)

    fake_token_manager = MagicMock()
    fake_token_manager.get_access_token = AsyncMock(return_value="test-bearer-token")

    with patch("llm_client.nous_auth") as mock_nous_auth, \
         patch("llm_client.AsyncOpenAI", return_value=fake_openai_instance):
        mock_nous_auth.token_manager = fake_token_manager
        result = await m.get_llm_response("system", "user")

    assert result == "hello from nous"
    fake_openai_instance.chat.completions.create.assert_awaited_once()
    call_kwargs = fake_openai_instance.chat.completions.create.call_args.kwargs
    assert call_kwargs["model"] == "Hermes-4-test"
    assert call_kwargs["messages"][0] == {"role": "system", "content": "system"}
    assert call_kwargs["messages"][1] == {"role": "user", "content": "user"}
```

- [ ] **Step 3.2: Run test — should FAIL**

```bash
cd secretary/query && python -m pytest tests/test_llm_client.py::test_nous_returns_text -v
```

Expected: FAIL — `Unknown LLM_PROVIDER: 'nous'`

- [ ] **Step 3.3: Add nous block to llm_client.py**

Replace the entire content of `secretary/query/llm_client.py`:

```python
import os
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

import nous_auth

_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")

_anthropic_client: AsyncAnthropic | None = None
_openrouter_client: AsyncOpenAI | None = None


def _get_anthropic() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    return _anthropic_client


def _get_openrouter() -> AsyncOpenAI:
    global _openrouter_client
    if _openrouter_client is None:
        _openrouter_client = AsyncOpenAI(
            base_url=os.environ["OPENROUTER_BASE_URL"],
            api_key=os.environ["OPENROUTER_API_KEY"],
        )
    return _openrouter_client


async def get_llm_response(system: str, user: str) -> str:
    if _PROVIDER == "anthropic":
        client = _get_anthropic()
        model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        msg = await client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return msg.content[0].text

    if _PROVIDER == "openrouter":
        client = _get_openrouter()
        model = os.environ["OPENROUTER_MODEL"]
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        if not resp.choices:
            error_detail = getattr(resp, "error", None) or "null choices"
            raise RuntimeError(f"OpenRouter returned no choices: {error_detail}")
        return resp.choices[0].message.content or ""

    if _PROVIDER == "nous":
        token = await nous_auth.token_manager.get_access_token()
        client = AsyncOpenAI(
            base_url="https://inference-api.nousresearch.com/v1",
            api_key=token,
        )
        model = os.getenv("NOUS_MODEL", "Hermes-4-70B")
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        if not resp.choices:
            raise RuntimeError("Nous returned no choices")
        return resp.choices[0].message.content or ""

    raise ValueError(f"Unknown LLM_PROVIDER: {_PROVIDER!r}")
```

- [ ] **Step 3.4: Run all llm_client tests — all 4 should pass**

```bash
cd secretary/query && python -m pytest tests/test_llm_client.py -v
```

Expected:
```
PASSED tests/test_llm_client.py::test_anthropic_returns_text
PASSED tests/test_llm_client.py::test_openrouter_returns_text
PASSED tests/test_llm_client.py::test_nous_returns_text
PASSED tests/test_llm_client.py::test_unknown_provider_raises
```

- [ ] **Step 3.5: Commit**

```bash
git add secretary/query/llm_client.py secretary/query/tests/test_llm_client.py
git commit -m "feat(secretary): add nous provider to llm_client with Bearer token auth"
```

---

## Task 4: Add nous endpoints to main.py (TDD)

**Files:**
- Modify: `secretary/query/main.py`
- Modify: `secretary/query/tests/test_main.py`

- [ ] **Step 4.1: Add nous endpoint tests to test_main.py**

Append these two tests at the end of `secretary/query/tests/test_main.py`:

```python
# ---------------------------------------------------------------------------
# /nous/auth and /nous/auth/status
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_nous_auth_status_unauthenticated(ac):
    client, _, __, ___ = ac

    fake_manager = MagicMock()
    fake_manager.auth_status.return_value = {"authenticated": False, "expires_at": None}

    with patch("main.nous_auth") as mock_nous_auth:
        mock_nous_auth.token_manager = fake_manager
        resp = await client.get("/nous/auth/status")

    assert resp.status_code == 200
    assert resp.json() == {"authenticated": False, "expires_at": None}


@pytest.mark.asyncio
async def test_nous_auth_starts_flow(ac):
    client, _, __, ___ = ac

    fake_manager = MagicMock()
    fake_manager.start_device_flow = AsyncMock(return_value={
        "authenticated": False,
        "verification_uri": "https://portal.nousresearch.com/manage-subscription?user_code=TEST-1234",
        "user_code": "TEST-1234",
        "expires_in": 300,
        "message": "Open https://portal.nousresearch.com/... and enter code: TEST-1234",
    })

    with patch("main.nous_auth") as mock_nous_auth:
        mock_nous_auth.token_manager = fake_manager
        resp = await client.get("/nous/auth")

    assert resp.status_code == 200
    body = resp.json()
    assert body["user_code"] == "TEST-1234"
    assert "verification_uri" in body
    fake_manager.start_device_flow.assert_awaited_once()
```

- [ ] **Step 4.2: Run new tests — should FAIL**

```bash
cd secretary/query && python -m pytest tests/test_main.py::test_nous_auth_status_unauthenticated tests/test_main.py::test_nous_auth_starts_flow -v
```

Expected: FAIL — `404 Not Found` (endpoints don't exist yet).

- [ ] **Step 4.3: Update main.py — add import, update _active_model_name, add 2 endpoints**

In `secretary/query/main.py`, make these three changes:

**Change 1** — add `import nous_auth` after `import llm_client` (line ~20):

```python
import llm_client
import nous_auth
```

**Change 2** — replace the `_active_model_name` function (currently lines 58-64):

```python
def _active_model_name(provider: str) -> str:
    mapping = {
        "anthropic": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
        "openrouter": os.getenv("OPENROUTER_MODEL", ""),
        "nous": os.getenv("NOUS_MODEL", "Hermes-4-70B"),
    }
    return mapping.get(provider, "unknown")
```

**Change 3** — append two new endpoints before the end of the file (after `/ingest-trigger`):

```python
@app.get("/nous/auth")
async def nous_auth_start():
    return await nous_auth.token_manager.start_device_flow()


@app.get("/nous/auth/status")
async def nous_auth_status():
    return nous_auth.token_manager.auth_status()
```

- [ ] **Step 4.4: Run all main tests — all should pass**

```bash
cd secretary/query && python -m pytest tests/test_main.py -v
```

Expected:
```
PASSED tests/test_main.py::test_health_ok
PASSED tests/test_main.py::test_health_qdrant_down
PASSED tests/test_main.py::test_query_hybrid_returns_answer
PASSED tests/test_main.py::test_query_top_k_final_slices_results
PASSED tests/test_main.py::test_query_rerank_path
PASSED tests/test_main.py::test_nous_auth_status_unauthenticated
PASSED tests/test_main.py::test_nous_auth_starts_flow
```

- [ ] **Step 4.5: Commit**

```bash
git add secretary/query/main.py secretary/query/tests/test_main.py
git commit -m "feat(secretary): add /nous/auth and /nous/auth/status endpoints"
```

---

## Task 5: Update .env.example

**Files:**
- Modify: `secretary/query/.env.example`

- [ ] **Step 5.1: Replace .env.example content**

Replace the entire content of `secretary/query/.env.example`:

```
QDRANT_URL=http://qdrant:6333
COLLECTION_NAME=secretary_notes

# LLM provider: anthropic | openrouter | nous
LLM_PROVIDER=anthropic

ANTHROPIC_API_KEY=sk-ant-xxx
ANTHROPIC_MODEL=claude-sonnet-4-20250514

OPENROUTER_API_KEY=sk-or-xxx
OPENROUTER_MODEL=anthropic/claude-sonnet-4
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1

# Nous Portal (OAuth Device Code — run GET /nous/auth once after first deploy)
NOUS_MODEL=Hermes-4-70B

COHERE_API_KEY=xxx
COHERE_RERANK_MODEL=rerank-multilingual-v3.0
```

- [ ] **Step 5.2: Commit**

```bash
git add secretary/query/.env.example
git commit -m "chore(secretary): update .env.example — replace NORUS_* with NOUS_MODEL"
```

---

## Task 6: Full test suite + final commit

- [ ] **Step 6.1: Run full test suite**

```bash
cd secretary/query && python -m pytest -v
```

Expected: All tests in `tests/test_llm_client.py`, `tests/test_nous_auth.py`, and `tests/test_main.py` pass (12 tests total).

If any test fails, fix before proceeding.

- [ ] **Step 6.2: Write daily_log entry**

Append to `secretary/.notes/daily_log.md`:

```markdown
## 2026-05-28

### Nous Portal OAuth integration
- Removed `norus` provider from llm_client.py, main.py, .env.example, and tests
- Created `nous_auth.py` (NousTokenManager) — handles OAuth 2.0 Device Code flow, token persistence to /data/nous_token.json, auto-refresh
- Added `GET /nous/auth` endpoint (starts device flow, returns verification_uri + user_code)
- Added `GET /nous/auth/status` endpoint (returns authenticated bool + expires_at)
- Added `nous` provider block in llm_client.py (OpenAI-compat client using Bearer token)
- OAuth endpoints: portal.nousresearch.com/api/oauth/device/code + /token, client_id=hermes-cli
- Inference: https://inference-api.nousresearch.com/v1 (OpenAI-compatible)
- Setup: deploy → call GET /nous/auth → open verification_uri in browser → approve → container stores token in /data/nous_token.json automatically
```

- [ ] **Step 6.3: Update 00_INDEX.md**

In `secretary/.notes/00_INDEX.md`, update the LLM provider section to reflect that `norus` is removed and `nous` (Device Code OAuth) is the third provider option.

- [ ] **Step 6.4: Final commit**

```bash
git add secretary/.notes/daily_log.md secretary/.notes/00_INDEX.md
git commit -m "docs(secretary): update notes — Nous Portal OAuth integration complete"
```
