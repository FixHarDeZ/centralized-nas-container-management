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
