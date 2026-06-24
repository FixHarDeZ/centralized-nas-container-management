# Shared HTTP Retry Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate scattered HTTP retry logic into a single `shared/http.py` module, then migrate stacks to use it — eliminating duplication and giving pricer/fetcher retry for free.

**Architecture:** One `shared/http.py` module exposes `get()` and `post()` wrappers around httpx with configurable retry (429 + 5xx + connection/timeout by default, exponential backoff). Vendored into stacks via `make sync-shared` like `notify.py`. Torrentwatch excluded (stateful relogin stays separate).

**Tech Stack:** httpx, pytest, stdlib time.sleep

## Global Constraints

- Python 3.12+
- httpx only (no requests) — game-codes migrates off requests
- stdlib `time.sleep` for sync backoff (no async)
- Return httpx `Response` directly (no wrapper)
- Vendored via `make sync-shared`, drift guarded by `tests/test_shared_sync.py`
- No `Co-Authored-By` trailers on commits

---

## File Structure

| File | Responsibility |
|------|----------------|
| `shared/http.py` | **NEW** — `get()`, `post()` with retry/backoff, mock-adapter seam |
| `shared/tests/test_http.py` | **NEW** — unit tests with mock adapter |
| `Makefile:10-11` | **MODIFY** — add `shared/http.py` to vendored copies list |
| `tests/test_shared_sync.py` | **MODIFY** — add `http.py` to hash-equality guard |
| `news-feed/app/pricer.py:15` | **MODIFY** — `httpx.get` → `from http import get` |
| `game-codes/game_code_notifier.py:20,162` | **MODIFY** — `import requests` → `from http import get`, delete inline retry loop |
| `game-codes/requirements.txt` | **MODIFY** — delete `requests==2.32.3`, add `httpx` |
| `game-codes/Dockerfile:9` | **MODIFY** — add `http.py` to COPY |
| `news-feed/app/summarizer.py:16-25` | **MODIFY** — delete `_with_retry`, use `shared.http.post` for OpenRouter |
| `news-feed/app/notify.py` | **VENDORED** — auto-synced by `make sync-shared` |
| `game-codes/http.py` | **VENDORED** — auto-synced by `make sync-shared` |

---

## Task 1: Create `shared/http.py` module

**Files:**
- Create: `shared/http.py`
- Create: `shared/tests/test_http.py`

**Interfaces:**
- Consumes: httpx library
- Produces: `get(url, **kwargs) -> httpx.Response`, `post(url, **kwargs) -> httpx.Response`

- [ ] **Step 1: Write the failing test for `get()` retry on 429**

Create `shared/tests/test_http.py`:

```python
"""Tests for the shared HTTP retry module — the interface is the test surface.

A fake adapter is injected at the transport seam so no network is hit.
"""
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from http import get, post  # noqa: E402


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
    stream = MagicMock()
    stream.read.return_value = text.encode()
    stream.is_stream_consumed = False
    return httpx.Response(
        status_code=status_code,
        text=text,
        stream=stream,
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
    # Default retries 429+5xx, but 503 is included in default
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd shared && python -m pytest tests/test_http.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'http'`

- [ ] **Step 3: Write the implementation**

Create `shared/http.py`:

```python
"""Shared HTTP client with retry — the interface is the test surface.

SINGLE SOURCE OF TRUTH: shared/http.py. Vendored into each stack directory
by `make sync-shared`; copies are committed and guarded by hash-equality
test (tests/test_shared_sync.py). DO NOT edit vendored copies — edit this
file and re-run `make sync-shared`.

Uses httpx only. stdlib time.sleep for sync backoff.
"""
from __future__ import annotations

import logging
import time
from typing import Sequence

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_RETRY_ON = frozenset({429, 500, 502, 503, 504})


def get(
    url: str,
    *,
    retries: int = 3,
    backoff: float = 1.0,
    retry_on: Sequence[int] = _DEFAULT_RETRY_ON,
    timeout: float = 30.0,
    _adapter=None,
    **kwargs,
) -> httpx.Response:
    """GET with retry. Returns httpx.Response. Raises on non-retryable status."""
    retry_on_set = frozenset(retry_on)
    last_exc = None
    for attempt in range(retries):
        try:
            if _adapter is not None:
                req = httpx.Request("GET", url, **kwargs)
                resp = _adapter.send(req, timeout=timeout)
            else:
                resp = httpx.get(url, timeout=timeout, **kwargs)
            if resp.status_code in retry_on_set and attempt < retries - 1:
                wait = backoff * (2 ** attempt)
                logger.warning(
                    "%d from %s, retry %d/%d in %.1fs",
                    resp.status_code, url, attempt + 1, retries, wait,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError:
            raise
        except Exception as exc:
            if attempt < retries - 1:
                wait = backoff * (2 ** attempt)
                logger.warning(
                    "error from %s, retry %d/%d in %.1fs: %s",
                    url, attempt + 1, retries, wait, exc,
                )
                time.sleep(wait)
                last_exc = exc
                continue
            raise
    raise last_exc


def post(
    url: str,
    *,
    retries: int = 3,
    backoff: float = 1.0,
    retry_on: Sequence[int] = _DEFAULT_RETRY_ON,
    timeout: float = 30.0,
    _adapter=None,
    **kwargs,
) -> httpx.Response:
    """POST with retry. Returns httpx.Response. Raises on non-retryable status."""
    retry_on_set = frozenset(retry_on)
    last_exc = None
    for attempt in range(retries):
        try:
            if _adapter is not None:
                req = httpx.Request("POST", url, **kwargs)
                resp = _adapter.send(req, timeout=timeout)
            else:
                resp = httpx.post(url, timeout=timeout, **kwargs)
            if resp.status_code in retry_on_set and attempt < retries - 1:
                wait = backoff * (2 ** attempt)
                logger.warning(
                    "%d from %s, retry %d/%d in %.1fs",
                    resp.status_code, url, attempt + 1, retries, wait,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError:
            raise
        except Exception as exc:
            if attempt < retries - 1:
                wait = backoff * (2 ** attempt)
                logger.warning(
                    "error from %s, retry %d/%d in %.1fs: %s",
                    url, attempt + 1, retries, wait, exc,
                )
                time.sleep(wait)
                last_exc = exc
                continue
            raise
    raise last_exc
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd shared && python -m pytest tests/test_http.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add shared/http.py shared/tests/test_http.py
git commit -m "feat(shared): add http.py retry module with get/post"
```

---

## Task 2: Wire vendoring for `shared/http.py`

**Files:**
- Modify: `Makefile:10-11` — add `shared/http.py` copies list
- Modify: `tests/test_shared_sync.py` — add `http.py` to hash guard

**Interfaces:**
- Consumes: `shared/http.py` from Task 1
- Produces: vendored `http.py` in each stack, tested by sync guard

- [ ] **Step 1: Add `HTTP_COPIES` to Makefile**

In `Makefile`, after the `NOTIFY_COPIES` block (line 11), add:

```makefile
HTTP_COPIES = news-feed/app/http.py game-codes/http.py
```

And update the `sync-shared` target (line 32-33) to:

```makefile
sync-shared:    ## Copy shared/{notify,http}.py into each stack (vendored, committed)
	@for dst in $(NOTIFY_COPIES); do cp shared/notify.py $$dst && echo "synced $$dst"; done
	@for dst in $(HTTP_COPIES); do cp shared/http.py $$dst && echo "synced $$dst"; done
```

- [ ] **Step 2: Run `make sync-shared` to create vendored copies**

Run: `make sync-shared`
Expected: `synced news-feed/app/http.py` and `synced game-codes/http.py`

- [ ] **Step 3: Add `http.py` to sync guard**

Read `tests/test_shared_sync.py` first, then add `http.py` to the file list being compared. The test compares vendored copies against `shared/` originals by hash.

- [ ] **Step 4: Run sync guard test**

Run: `python -m pytest tests/test_shared_sync.py -v`
Expected: PASS (all vendored copies match originals)

- [ ] **Step 5: Commit**

```bash
git add Makefile tests/test_shared_sync.py news-feed/app/http.py game-codes/http.py
git commit -m "chore(shared): wire http.py vendoring into Makefile + sync guard"
```

---

## Task 3: Migrate `news-feed/app/pricer.py` (easiest)

**Files:**
- Modify: `news-feed/app/pricer.py:4,15` — `httpx.get` → `from http import get`

**Interfaces:**
- Consumes: `shared/http.py:get()` from Task 1 (vendored as `news-feed/app/http.py`)
- Produces: pricer uses retry-aware GET

- [ ] **Step 1: Update pricer import and call**

Change `news-feed/app/pricer.py`:

```python
# Line 4: replace "import httpx" with:
from http import get as http_get

# Line 15: replace "resp = httpx.get(_OPENROUTER_MODELS_URL, timeout=30.0)" with:
resp = http_get(_OPENROUTER_MODELS_URL, timeout=30.0)
```

- [ ] **Step 2: Run pricer tests**

Run: `cd news-feed && python -m pytest tests/test_pricer.py -v`
Expected: PASS (tests mock `httpx.get` — update mock target to `app.pricer.http_get` if needed)

- [ ] **Step 3: Commit**

```bash
git add news-feed/app/pricer.py
git commit -m "refactor(pricer): use shared http.get with retry"
```

---

## Task 4: Migrate `game-codes/game_code_notifier.py`

**Files:**
- Modify: `game-codes/game_code_notifier.py:20,158-170` — delete `import requests`, replace inline retry with `from http import get`
- Modify: `game-codes/requirements.txt` — delete `requests==2.32.3`, add `httpx==0.28.0`
- Modify: `game-codes/Dockerfile:9` — add `http.py` to COPY

**Interfaces:**
- Consumes: `shared/http.py:get()` from Task 1 (vendored as `game-codes/http.py`)
- Produces: game-codes uses retry-aware GET, no more `requests` dependency

- [ ] **Step 1: Update imports**

In `game-codes/game_code_notifier.py`, line 20:

```python
# Replace:
import requests
# With:
from http import get as http_get
```

- [ ] **Step 2: Replace `fetch()` function**

Replace lines 158-170:

```python
def fetch(src: dict) -> list[dict]:
    """Download src['url'] and parse. Retries via shared http.get (429, 5xx, backoff)."""
    r = http_get(src["url"], headers=HEADERS, timeout=HTTP_TIMEOUT, retries=3, backoff=20.0)
    return _PARSERS[src["type"]](src, r.text)
```

Note: `retries` parameter removed from `fetch()` signature — retry is now handled by `shared.http.get`. `backoff=20.0` preserves the original 20s/40s cadence for game code sites.

- [ ] **Step 3: Update requirements.txt**

Replace `game-codes/requirements.txt`:

```
httpx==0.28.0
beautifulsoup4==4.12.3

pytest==8.3.4
```

- [ ] **Step 4: Update Dockerfile COPY**

In `game-codes/Dockerfile`, line 9:

```dockerfile
# Replace:
COPY --chown=app:app notify.py game_code_notifier.py ./
# With:
COPY --chown=app:app notify.py http.py game_code_notifier.py ./
```

- [ ] **Step 5: Update `fetch()` call sites**

Search `game-codes/game_code_notifier.py` for calls to `fetch(src)` — the signature changed (no `retries` param). Verify all callers pass only `src`.

- [ ] **Step 6: Run game-codes tests**

Run: `cd game-codes && python -m pytest tests/ -v`
Expected: PASS (test_runtime.py monkeypatches `g.fetch` — signature change doesn't affect mock)

- [ ] **Step 7: Commit**

```bash
git add game-codes/game_code_notifier.py game-codes/requirements.txt game-codes/Dockerfile
git commit -m "refactor(game-codes): migrate to shared http.get, drop requests"
```

---

## Task 5: Migrate `news-feed/app/summarizer.py` OpenRouter call

**Files:**
- Modify: `news-feed/app/summarizer.py:16-25,43-56` — delete `_with_retry`, replace `httpx.post` with `from http import post`

**Interfaces:**
- Consumes: `shared/http.py:post()` from Task 1 (vendored as `news-feed/app/http.py`)
- Produces: OpenRouter API call uses retry-aware POST

- [ ] **Step 1: Update import**

In `news-feed/app/summarizer.py`:

```python
# Add after existing imports:
from http import post as http_post

# Delete _with_retry function (lines 16-25)
```

- [ ] **Step 2: Replace `_summarize_openrouter` call**

In `_summarize_openrouter`, replace the `httpx.post` block with:

```python
def _summarize_openrouter(title: str, body: str, model: str) -> str:
    api_key = os.getenv("OPENROUTER_API_KEY", "")

    resp = http_post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [{"role": "user", "content": _user_prompt(title, body)}],
            "max_tokens": 300,
        },
        timeout=60.0,
        retries=3,
        backoff=1.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]
```

- [ ] **Step 3: Update Anthropic calls**

The `_summarize_anthropic` function uses `anthropic.Anthropic` client directly (not httpx) — keep `_with_retry` wrapper ONLY for Anthropic calls. Rename it to `_anthropic_retry` to make scope clear:

```python
def _anthropic_retry(fn, retries: int = 3):
    for attempt in range(retries):
        try:
            return fn()
        except Exception as exc:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            logger.warning("anthropic retry %d/%d after %ds: %s", attempt + 1, retries, wait, exc)
            time.sleep(wait)
```

- [ ] **Step 4: Run summarizer tests**

Run: `cd news-feed && python -m pytest tests/test_summarizer.py -v`
Expected: PASS (tests mock `httpx.post` — update mock target if needed)

- [ ] **Step 5: Commit**

```bash
git add news-feed/app/summarizer.py
git commit -m "refactor(summarizer): use shared http.post for OpenRouter, keep anthropic retry"
```

---

## Task 6: Final verification + deploy

**Files:**
- No new files — verification only

**Interfaces:**
- Consumes: all previous tasks
- Produces: all tests pass, stacks deployable

- [ ] **Step 1: Run all shared tests**

Run: `python -m pytest shared/tests/ -v`
Expected: PASS (test_notify.py + test_http.py)

- [ ] **Step 2: Run sync guard**

Run: `python -m pytest tests/test_shared_sync.py -v`
Expected: PASS (all vendored copies match)

- [ ] **Step 3: Run game-codes tests**

Run: `cd game-codes && python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 4: Run news-feed tests**

Run: `cd news-feed && python -m pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Deploy game-codes to NAS**

Run: `./scripts/deploy.sh -s game-codes -y`
Expected: Container rebuilds with httpx + shared http.py, starts successfully

- [ ] **Step 6: Verify game-codes container logs**

Run: `ssh nas "echo 'password' | sudo -S /usr/local/bin/docker logs game-codes --tail 5 2>&1"`
Expected: No import errors, loop mode starts

- [ ] **Step 7: Final commit (docs only)**

Update `game-codes/.notes/00_INDEX.md` and `game-codes/.notes/daily_log.md` with migration notes, then:

```bash
git add game-codes/.notes/
git commit -m "docs(game-codes): log httpx migration in notes"
```

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-24-shared-http-retry.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
