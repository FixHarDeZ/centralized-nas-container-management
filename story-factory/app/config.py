"""Environment reading.

Every value is read at call time, never at import time: the tests set env vars
around a call, and reading at import makes that silently not work.
"""

from __future__ import annotations

import os
from pathlib import Path


def _int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def data_dir() -> Path:
    return Path(os.environ.get("DATA_DIR", "/data"))


def output_dir() -> Path:
    return Path(os.environ.get("OUTPUT_DIR", "/output"))


# --- TTS ---------------------------------------------------------------------

def tts_voice() -> str:
    return os.environ.get("TTS_VOICE", "th-TH-Chirp3-HD-Achernar")


def tts_language_code() -> str:
    return os.environ.get("TTS_LANGUAGE_CODE", "th-TH")


def tts_speaking_rate() -> float:
    return _float("TTS_SPEAKING_RATE", 1.0)


def max_request_bytes() -> int:
    """The `synthesize` endpoint's own ceiling. Not a tuning knob."""
    return _int("TTS_MAX_REQUEST_BYTES", 5000)


def join_silence() -> float:
    return _float("JOIN_SILENCE", 0.30)


# --- Render ------------------------------------------------------------------

def render_preset() -> str:
    return os.environ.get("RENDER_PRESET", "veryfast")


def render_crf() -> int:
    return _int("RENDER_CRF", 20)


def render_threads() -> int:
    return _int("RENDER_THREADS", 3)


def backdrop_max_seconds() -> float:
    return _float("BACKDROP_MAX_SECONDS", 8.0)


# --- Editorial ---------------------------------------------------------------

def religion_gate_until_stories() -> int:
    return _int("RELIGION_GATE_UNTIL_STORIES", 10)


def chapters_per_story() -> int:
    return _int("CHAPTERS_PER_STORY", 7)


def words_per_chapter() -> int:
    return _int("WORDS_PER_CHAPTER", 700)


# --- Housekeeping ------------------------------------------------------------

def keep_workdirs() -> int:
    """Finished Story workdirs kept for listening back (raw speech chunks are
    the evidence for docs/adr/0012). Each is roughly 250 MB of wav."""
    return _int("KEEP_WORKDIRS", 3)
