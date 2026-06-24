"""Shared HTTP client with retry — the interface is the test surface.

SINGLE SOURCE OF TRUTH: shared/http_client.py. Vendored into each stack directory
by `make sync-shared`; copies are committed and guarded by hash-equality
test (tests/test_shared_sync.py). DO NOT edit vendored copies — edit this
file and re-run `make sync-shared`.

Uses httpx only. stdlib time.sleep for sync backoff.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional, Sequence

import httpx

logger = logging.getLogger(__name__)

_DEFAULT_RETRY_ON = frozenset({429, 500, 502, 503, 504})


def _request(
    method: str,
    url: str,
    *,
    retries: int = 3,
    backoff: float = 1.0,
    retry_on: Sequence[int] = _DEFAULT_RETRY_ON,
    timeout: float = 30.0,
    _adapter: Optional[Any] = None,
    **kwargs,
) -> httpx.Response:
    if retries < 1:
        raise ValueError(f"retries must be >= 1, got {retries}")
    retry_on_set = frozenset(retry_on)
    for attempt in range(retries):
        try:
            if _adapter is not None:
                req = httpx.Request(method, url, **kwargs)
                resp = _adapter.send(req, timeout=timeout)
            else:
                resp = httpx.request(method, url, timeout=timeout, **kwargs)
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
                continue
            raise
    raise RuntimeError("unexpected: retry loop exhausted without return/raise")


def get(
    url: str,
    *,
    retries: int = 3,
    backoff: float = 1.0,
    retry_on: Sequence[int] = _DEFAULT_RETRY_ON,
    timeout: float = 30.0,
    _adapter: Optional[Any] = None,
    **kwargs,
) -> httpx.Response:
    """GET with retry. Returns httpx.Response. Raises on non-retryable status."""
    return _request(
        "GET", url, retries=retries, backoff=backoff,
        retry_on=retry_on, timeout=timeout, _adapter=_adapter, **kwargs,
    )


def post(
    url: str,
    *,
    retries: int = 3,
    backoff: float = 1.0,
    retry_on: Sequence[int] = _DEFAULT_RETRY_ON,
    timeout: float = 30.0,
    _adapter: Optional[Any] = None,
    **kwargs,
) -> httpx.Response:
    """POST with retry. Returns httpx.Response. Raises on non-retryable status."""
    return _request(
        "POST", url, retries=retries, backoff=backoff,
        retry_on=retry_on, timeout=timeout, _adapter=_adapter, **kwargs,
    )
