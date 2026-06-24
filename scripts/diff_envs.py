#!/usr/bin/env python3
"""Semantic .env diff used during Phase A migration verification.

Two .env files are equivalent when, after unquoting and ignoring comments and
blank lines, they yield the same {key: value} mapping.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DiffResult:
    equivalent: bool
    missing: set[str] = field(default_factory=set)
    extra: set[str] = field(default_factory=set)
    changed: dict[str, tuple[str, str]] = field(default_factory=dict)


def _unquote(value: str) -> str:
    """Reverse the simple cases of compose-quote: strip surrounding ' or ".
    Multi-line/escaped values are out of scope (rejected by render_env).
    """
    s = value
    if len(s) >= 2:
        if s[0] == s[-1] == "'":
            return s[1:-1]
        if s[0] == s[-1] == '"':
            return s[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return s


def parse(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        out[key] = _unquote(value.strip())
    return out


def diff(a: Path, b: Path) -> DiffResult:
    ma = parse(a)
    mb = parse(b)
    keys_a = set(ma)
    keys_b = set(mb)
    missing = keys_a - keys_b
    extra = keys_b - keys_a
    changed: dict[str, tuple[str, str]] = {}
    for k in keys_a & keys_b:
        if ma[k] != mb[k]:
            changed[k] = (ma[k], mb[k])
    return DiffResult(
        equivalent=not (missing or extra or changed),
        missing=missing,
        extra=extra,
        changed=changed,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("a", type=Path, help="first .env file")
    p.add_argument("b", type=Path, help="second .env file")
    args = p.parse_args(argv)
    r = diff(args.a, args.b)
    if r.equivalent:
        print(f"EQUIVALENT: {args.a} == {args.b}")
        return 0
    print(f"DIFFER: {args.a} vs {args.b}")
    if r.missing:
        print(f"  Only in {args.a.name}: {sorted(r.missing)}")
    if r.extra:
        print(f"  Only in {args.b.name}: {sorted(r.extra)}")
    if r.changed:
        for k, (va, vb) in sorted(r.changed.items()):
            print(f"  {k}: '{va}'  -->  '{vb}'")
    return 1


if __name__ == "__main__":
    sys.exit(main())
