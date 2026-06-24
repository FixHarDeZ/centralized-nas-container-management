"""Guard: vendored copies of shared/{notify,http_client}.py must match the single source.

Each stack builds its own image with build context = its own dir, so these files
are vendored (committed) into each stack. If this fails, run `make sync-shared`.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

CASES = [
    (
        "shared/notify.py",
        [
            "news-feed/app/notify.py",
            "game-codes/notify.py",
            "watchtower/notifier/notify.py",
            "torrentwatch/notify.py",
        ],
    ),
    (
        "shared/http_client.py",
        [
            "news-feed/app/http_client.py",
            "game-codes/http_client.py",
            "maid-tracker/http_client.py",
        ],
    ),
    (
        "shared/sqlite_backup.py",
        [
            "maid-tracker/sqlite_backup.py",
            "news-feed/app/sqlite_backup.py",
            "torrentwatch/sqlite_backup.py",
        ],
    ),
]


@pytest.mark.parametrize(
    "canonical_rel,copies",
    CASES,
    ids=[c[0].split("/")[-1] for c in CASES],
)
def test_vendored_copy_matches_canonical(canonical_rel, copies):
    canonical = ROOT / canonical_rel
    for rel in copies:
        copy = ROOT / rel
        assert copy.exists(), f"{rel} missing — run `make sync-shared`"
        assert copy.read_bytes() == canonical.read_bytes(), (
            f"{rel} drifted from {canonical_rel} — run `make sync-shared`"
        )
