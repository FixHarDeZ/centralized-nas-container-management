from __future__ import annotations

import collections
import hashlib
import re

DEFAULT_REGEX = re.compile(r"WARN|ERROR")

_TS_RE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:?\d{2})?"
)
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_HEX_RE = re.compile(r"\b0x[0-9a-fA-F]+\b")
_PATH_RE = re.compile(r"(?:/[\w.\-]+){2,}")
_NUM_RE = re.compile(r"\b\d+\b")


def normalize_message(line: str) -> str:
    """Strip transient values (timestamps, UUIDs, hex/memory addresses,
    machine-specific paths, bare numbers) so recurrences of the same
    logical error hash to the same fingerprint."""
    s = _TS_RE.sub("<TS>", line)
    s = _UUID_RE.sub("<UUID>", s)
    s = _HEX_RE.sub("<HEX>", s)
    s = _PATH_RE.sub("<PATH>", s)
    s = _NUM_RE.sub("<NUM>", s)
    return s


def fingerprint(container: str, line: str) -> str:
    normalized = normalize_message(line)
    digest = hashlib.sha256(f"{container}:{normalized}".encode()).hexdigest()
    return digest[:12]


class RingBuffer:
    """Per-container sliding window: keeps up to `before` lines seen so far;
    `capture()` combines them with the trigger line and up to `after` lines
    read immediately afterward."""

    def __init__(self, before: int = 30, after: int = 10):
        self._before: collections.deque[str] = collections.deque(maxlen=before)
        self._after_max = after

    def push(self, line: str) -> None:
        self._before.append(line)

    def capture(self, trigger_line: str, tail_lines: list[str]) -> str:
        return "\n".join([*self._before, trigger_line, *tail_lines[: self._after_max]])
