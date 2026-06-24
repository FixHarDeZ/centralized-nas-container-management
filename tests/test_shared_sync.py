"""Guard: vendored copies of shared/notify.py must match the single source.

Each stack builds its own image with build context = its own dir, so notify.py
is vendored (committed) into each stack. If this fails, run `make sync-shared`.
"""
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CANONICAL = ROOT / "shared" / "notify.py"
COPIES = [
    "news-feed/app/notify.py",
    "game-codes/notify.py",
    "watchtower/notifier/notify.py",
    "torrentwatch/notify.py",
]


@pytest.mark.parametrize("rel", COPIES)
def test_vendored_copy_matches_canonical(rel):
    copy = ROOT / rel
    assert copy.exists(), f"{rel} missing — run `make sync-shared`"
    assert copy.read_bytes() == CANONICAL.read_bytes(), (
        f"{rel} drifted from shared/notify.py — run `make sync-shared`"
    )
