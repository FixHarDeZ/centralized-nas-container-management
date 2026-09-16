#!/usr/bin/env python3
"""Bump claude-desk's pinned versions to whatever upstream calls latest.

    make desk-latest          # rewrite the pins, then deploy the stack
    make desk-latest ARGS=-n  # just say what is behind, change nothing

The desk pins every piece of software it installs, and nothing in the
container can update itself: both agents are npm globals owned by root while
the container runs as uid 1000, so `claude`'s own updater cannot write to its
own install — and a self-update would be thrown away by the next deploy
anyway, since that recreates the container. Watchtower is no help either;
this image is built here rather than pulled from a registry.

What is left is editing the pin and rebuilding, and the only tedious part of
that is finding the number. This does that part. The pin stays in git, so a
release that breaks the phone UI is one `git revert` from being undone —
which is why this writes a version rather than `@latest`.

Not covered: ttyd and rtk, which are pinned by sha256 as well as version, so
bumping them means downloading the artefact to hash it. They also change once
a year, unlike the agents.
"""
import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 20

NPM = "https://registry.npmjs.org/{}/latest"
GITHUB_HEAD = "https://api.github.com/repos/{}/commits/{}"


class Pin:
    """One pinned version: where it is written, and where to look it up."""

    def __init__(self, label, path, pattern, fetch, note=""):
        self.label = label
        self.path = ROOT / path
        # Three groups: everything before the value, the value, everything
        # after. Anchored enough that a near-miss raises instead of writing
        # into the wrong line.
        self.pattern = re.compile(pattern)
        self.fetch = fetch
        self.note = note

    def current(self) -> str:
        text = self.path.read_text(encoding="utf-8")
        found = self.pattern.findall(text)
        if len(found) != 1:
            raise SystemExit(
                f"{self.label}: expected exactly one pin in {self.path.relative_to(ROOT)}, "
                f"found {len(found)} — the file's shape changed, fix this script"
            )
        return found[0][1]

    def write(self, value: str) -> None:
        text = self.path.read_text(encoding="utf-8")
        new, count = self.pattern.subn(lambda m: m[1] + value + m[3], text, count=1)
        if count != 1:
            raise SystemExit(f"{self.label}: rewrite did not apply")
        self.path.write_text(new, encoding="utf-8")


def _get(url: str):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise SystemExit(f"could not read {url}: {exc}") from exc


def npm(package: str):
    # /latest is the dist-tag the registry itself serves, i.e. exactly what an
    # unpinned `npm install -g <pkg>` would have taken.
    return lambda: _get(NPM.format(package.replace("/", "%2f")))["version"]


def github_head(repo: str, branch: str = "main"):
    # Unauthenticated: 60 requests an hour from one address, which a manual
    # bump never approaches.
    return lambda: _get(GITHUB_HEAD.format(repo, branch))["sha"]


PINS = [
    Pin(
        "Claude Code",
        "claude-desk/docker-compose.yml",
        r'(CLAUDE_VERSION:\s*")([^"]+)(")',
        npm("@anthropic-ai/claude-code"),
    ),
    Pin(
        "MiMoCode",
        # Not in compose with the other two: the image installs it and nothing
        # passes it as a build arg, so the Dockerfile default is the pin.
        "claude-desk/Dockerfile",
        r"(ARG MIMO_CODE_VERSION=)([^\s]+)(\n)",
        npm("@mimo-ai/cli"),
    ),
    Pin(
        "Office skills",
        "claude-desk/docker-compose.yml",
        r'(SKILLS_REF:\s*")([^"]+)(")',
        github_head("anthropics/skills"),
        note="anthropics/skills@main",
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "-n", "--dry-run", action="store_true",
        help="report what is behind without editing anything",
    )
    args = parser.parse_args()

    behind = []
    for pin in PINS:
        current = pin.current()
        latest = pin.fetch()
        same = current == latest
        mark = "  " if same else "→ "
        shown = current[:12] if len(current) > 20 else current
        target = latest[:12] if len(latest) > 20 else latest
        line = f"{mark}{pin.label:<16} {shown}"
        if not same:
            line += f"  →  {target}"
            behind.append((pin, latest))
        print(line + (f"   ({pin.note})" if pin.note else ""))

    if not behind:
        print("\nAlready on the latest of everything.")
        return 0

    if args.dry_run:
        # Zero even when something is behind: reporting is what was asked for,
        # and a non-zero exit here only makes `make` print a failure at someone
        # who got exactly the answer they wanted.
        print(f"\n{len(behind)} behind. Drop -n to write the pins.")
        return 0

    touched = set()
    for pin, latest in behind:
        pin.write(latest)
        touched.add(pin.path.relative_to(ROOT))

    print("\nRewrote: " + ", ".join(sorted(str(p) for p in touched)))
    print("Next:    git diff  →  ./scripts/deploy.sh -s claude-desk -y")
    print("The rebuild takes a few minutes and drops the open tmux session.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
