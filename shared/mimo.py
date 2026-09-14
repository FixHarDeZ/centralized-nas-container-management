"""mimo (OpenAI wire format): one completion, bounded by a wall clock.

SINGLE SOURCE OF TRUTH: shared/mimo.py. Vendored into each stack's `app/` by
`make sync-shared`; copies are committed and guarded by a hash-equality test
(tests/test_shared_sync.py). DO NOT edit vendored copies.

Only the single call lives here. Retry loops, parsing and validation are the
stack's business — a Shorts Script and a Story Chapter fail in different ways.
What is shared is every rule about the call itself, each bought with an
incident in shorts-factory:

  * the call is wrapped in `asyncio.wait_for`. httpx's timeout is per read, so a
    server that trickles bytes never times out, and a bot whose poll loop was
    waiting on it froze whole (2026-08-27);
  * `max_tokens` is never sent. This is a reasoning model and it spends that
    budget on thinking first, then returns `content=''`;
  * `reasoning_effort` defaults to "low": the model default burned 10,457
    tokens / 161s against 3,796 / 79s at low, for a worse script;
  * latency tracks thinking, ~30 tokens/s (93s/3k, 112s/4k, 197s/7k,
    347s/10.6k). A slow answer is usually a long think, not a stall. The
    per-call log line is how the two are told apart afterwards;
  * a stall is a *window*, not a request. Hedging with parallel requests was
    tried and, across every logged case, never once rescued a call — the twins
    hung together. `Stalled` is raised so the caller can wait the window out.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "mimo-v2.5-pro"
DEFAULT_FALLBACK = "mimo-v2.5"
DEFAULT_BUDGET = 600.0


class Stalled(Exception):
    """No answer inside the budget. Not a bad answer — the endpoint is sick for
    a few minutes and the same prompt succeeds afterwards."""


class Truncated(Exception):
    """The reply arrived but is not an answer: cut off by the token cap
    (`finish_reason == "length"`) or empty. Retry, do not parse."""


def model() -> str:
    return os.environ.get("MIMO_MODEL", DEFAULT_MODEL)


def fallback_model() -> str:
    """The smaller, faster model. Not a hedge target: it is for a retry that
    has only the tail of a shared budget left to finish in (149s measured
    against a 347s worst case for the pro model)."""
    return os.environ.get("MIMO_FALLBACK_MODEL", DEFAULT_FALLBACK)


def budget() -> float:
    """Wall-clock ceiling for one *task*, shared across its retries."""
    return float(os.environ.get("MIMO_TIMEOUT_SECONDS", str(DEFAULT_BUDGET)))


def client() -> AsyncOpenAI:
    """Read at call time, never at import: importing must work without keys."""
    return AsyncOpenAI(
        api_key=os.environ["MIMO_API_KEY"],
        base_url=os.environ.get("MIMO_BASE_URL"),
        # Belt and braces under `wait_for`; on its own this is per read.
        timeout=budget(),
        max_retries=1,
    )


class Deadline:
    """A budget that retries share. `remaining` only ever goes down."""

    def __init__(self, seconds: float | None = None):
        self.ends = time.monotonic() + (budget() if seconds is None else seconds)

    @property
    def remaining(self) -> float:
        return max(0.0, self.ends - time.monotonic())

    def expired(self, floor: float = 0.0) -> bool:
        """True when less than `floor` is left — the caller's notion of the
        shortest attempt worth starting."""
        return self.remaining <= floor


async def complete(
    api: AsyncOpenAI,
    messages: list[dict],
    *,
    within: float,
    model_name: str | None = None,
    temperature: float | None = None,
) -> str:
    """One chat completion, or `Stalled` after `within` seconds, or
    `Truncated` if what came back is not usable."""
    if within <= 0:
        raise Stalled("no time left in the budget")
    name = model_name or model()
    kwargs: dict = {
        "model": name,
        "messages": messages,
        "reasoning_effort": os.environ.get("MIMO_REASONING_EFFORT", "low"),
    }
    if temperature is not None:
        kwargs["temperature"] = temperature

    started = time.monotonic()
    try:
        reply = await asyncio.wait_for(api.chat.completions.create(**kwargs), timeout=within)
    except asyncio.TimeoutError as exc:
        raise Stalled(f"{name} silent for {within:.0f}s") from exc

    spent = time.monotonic() - started
    usage = getattr(reply, "usage", None)
    tokens = getattr(usage, "completion_tokens", 0) or 0
    choice = reply.choices[0]
    finish_reason = getattr(choice, "finish_reason", None)
    logger.info(
        "%s answered in %.0fs, %d tokens (%.0f tokens/s) finish_reason=%s",
        name, spent, tokens, tokens / spent if spent else 0, finish_reason,
    )
    content = choice.message.content or ""
    if finish_reason == "length" or not content.strip():
        raise Truncated(f"{name} reply unusable (finish_reason={finish_reason}, {len(content)} chars)")
    return content
