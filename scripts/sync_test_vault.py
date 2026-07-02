#!/usr/bin/env python3
"""Regenerate secrets/test-vault.sops.yaml from the real vault's *structure*.

`make check` validates manifests against BOTH the real vault and test-vault.
Every secret added to the real vault must also exist in test-vault or check
fails ("manifest references missing vault path ..."). This script mirrors the
real vault's key tree, replacing every leaf value with a dummy `test-<dotted
path>`, then re-encrypts to test-vault (which uses a different age recipient
per .sops.yaml). Run after adding/removing any vault key.

Usage: python scripts/sync_test_vault.py   (or `make sync-test-vault`)
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
REAL = ROOT / "secrets" / "vault.sops.yaml"
TEST = ROOT / "secrets" / "test-vault.sops.yaml"


def dummify(node, path=()):
    """Walk the tree; replace every scalar leaf with test-<dotted.path>."""
    if isinstance(node, dict):
        return {k: dummify(v, (*path, k)) for k, v in node.items() if k != "sops"}
    return "test-" + "-".join(path)


def main() -> int:
    plain = subprocess.run(
        ["sops", "-d", str(REAL)], capture_output=True, text=True, check=False,
    )
    if plain.returncode != 0:
        print(f"sops decrypt failed: {plain.stderr.strip()}", file=sys.stderr)
        return 1

    dummy = dummify(yaml.safe_load(plain.stdout) or {})

    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(dummy, f, sort_keys=True)
        tmp = f.name

    enc = subprocess.run(
        ["sops", "-e", "--input-type", "yaml", "--output-type", "yaml",
         "--filename-override", str(TEST), tmp],
        capture_output=True, text=True, check=False,
    )
    Path(tmp).unlink()
    if enc.returncode != 0:
        print(f"sops encrypt failed: {enc.stderr.strip()}", file=sys.stderr)
        return 1

    TEST.write_text(enc.stdout)
    print(f"synced {TEST.relative_to(ROOT)} from {REAL.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
