"""Guard: vendored copies of shared/*.py must match the single source.

Each stack builds its own image with build context = its own dir, so these files
are vendored (committed) into each stack. Copies are discovered by filename match
(not hardcoded) so adding/removing a vendored copy never needs a test edit.
If this fails, run `make sync-shared`.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED_DIR = ROOT / "shared"
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}

CANONICALS = sorted(
    p for p in SHARED_DIR.glob("*.py") if not p.name.startswith("test_")
)


def discover_copies(canonical: Path) -> list[Path]:
    return sorted(
        p
        for p in ROOT.rglob(canonical.name)
        if p != canonical and not SKIP_DIRS & set(p.parts)
    )


@pytest.mark.parametrize(
    "canonical",
    CANONICALS,
    ids=[p.name for p in CANONICALS],
)
def test_vendored_copy_matches_canonical(canonical):
    copies = discover_copies(canonical)
    for copy in copies:
        rel = copy.relative_to(ROOT)
        assert copy.read_bytes() == canonical.read_bytes(), (
            f"{rel} drifted from shared/{canonical.name} — run `make sync-shared`"
        )
