"""Guard: vendored copies of shared/*.py must match the single source.

Each stack builds its own image with build context = its own dir, so these files
are vendored (committed) into each stack. Copies are discovered by filename match
(not hardcoded) so adding/removing a vendored copy never needs a test edit.
If this fails, run `make sync-shared`.
"""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SHARED_DIR = ROOT / "shared"

CANONICALS = sorted(
    p for p in SHARED_DIR.glob("*.py") if not p.name.startswith("test_")
)


def discover_copies(canonical: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", f"--", f"*/{canonical.name}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(
        ROOT / rel
        for rel in out.splitlines()
        if not rel.startswith("shared/")
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
