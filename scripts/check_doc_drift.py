#!/usr/bin/env python3
"""Doc-drift checker: CLAUDE.md stack table vs the filesystem vs deploy.sh.

Compares three sources of truth about which stacks exist:

1. The "Stacks & Ports Directory" table in root `CLAUDE.md`.
2. The top-level directories that actually contain a `docker-compose.yml`.
3. The `ALL_STACKS=( ... )` array in `scripts/deploy.sh`.

A finding means one of these three disagrees with the other two. Fix it by
editing whichever source is wrong: add/remove a CLAUDE.md table row, add/
remove the stack directory, or add/remove the name in `ALL_STACKS` in
`scripts/deploy.sh`. Run directly: `python3 scripts/check_doc_drift.py`.
Exit 0 means no drift found, exit 1 means findings were printed above.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Non-stack top-level directories that must never be treated as stacks even
# if they happen to contain a docker-compose.yml (none currently do).
IGNORED_TOP_LEVEL = {"docs", "scripts", "secrets", "shared", "tests", "screenshots"}

TABLE_HEADER = (
    "| Directory | Purpose | Port (Internal / Proxy) | "
    "Critical Gotchas / Architecture |"
)

ROW_RE = re.compile(r"^\|\s*`([^`/]+)/`\s*\|")

# An explicit "this stack is not deployed" claim, Thai or English.
ABSENCE_CLAIM_RE = re.compile(
    r"(ไม่อยู่ใน|ยังไม่ได้เพิ่มใน|ยังไม่อยู่ใน|not in|missing from|absent from)"
    r"\s*`?ALL_STACKS"
)


def stack_dirs(root: Path) -> set[str]:
    """Top-level directories containing docker-compose.yml, discovered live."""
    found = set()
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name in IGNORED_TOP_LEVEL or entry.name.startswith("."):
            continue
        if (entry / "docker-compose.yml").exists():
            found.add(entry.name)
    return found


def documented_stacks(claude_md_text: str) -> dict[str, int]:
    """Stack name (no trailing slash) -> 1-based line number of its table row.

    Locates the table by its header line, then reads rows (lines starting
    with `` | `name/` `` optionally followed by whitespace then `|`) until
    the first line that is not a table row.
    """
    return {name: line for name, line, _ in table_rows(claude_md_text)}


def table_rows(claude_md_text: str) -> list[tuple[str, int, str]]:
    """Every table row as (stack name, 1-based line number, full row text)."""
    lines = claude_md_text.splitlines()
    result: list[tuple[str, int, str]] = []
    in_table = False
    for i, line in enumerate(lines, start=1):
        if not in_table:
            if line.strip() == TABLE_HEADER:
                in_table = True
            continue
        # Skip the separator row right after the header.
        if line.strip().startswith("| :---"):
            continue
        match = ROW_RE.match(line)
        if not match:
            # First non-row line after the header ends the table.
            break
        result.append((match.group(1), i, line))
    return result


def stale_deploy_claims(
    claude_md_text: str, deployed: set[str], deploy_sh_line: int
) -> list[str]:
    """Rows claiming a stack is absent from ALL_STACKS while it is in the array.

    Deliberately narrow: the row must state the absence, not merely mention the
    array — a row correcting itself ("อยู่ใน `ALL_STACKS` แล้ว") names it too,
    and matching on the name alone turns the fix into a fresh finding. Anything
    subtler than an explicit absence claim is left to a human reader.
    """
    findings = []
    for name, line, text in table_rows(claude_md_text):
        if not ABSENCE_CLAIM_RE.search(text):
            continue
        if name in deployed:
            findings.append(
                f"Stale deploy claim: `{name}/`'s CLAUDE.md row "
                f"(CLAUDE.md:{line}) says it is not in ALL_STACKS, but `{name}` "
                f"IS in the array (scripts/deploy.sh:{deploy_sh_line}) — drop "
                f"the stale claim."
            )
    return findings


def deploy_stacks(deploy_sh_text: str) -> set[str]:
    """Names inside the ALL_STACKS=( ... ) array in scripts/deploy.sh."""
    match = re.search(r"ALL_STACKS=\((.*?)\)", deploy_sh_text, re.S)
    if not match:
        return set()
    return set(match.group(1).split())


def deploy_stacks_line(deploy_sh_text: str) -> int:
    """1-based line number where the ALL_STACKS=( assignment starts."""
    idx = deploy_sh_text.index("ALL_STACKS=(")
    return deploy_sh_text.count("\n", 0, idx) + 1


def find_drift(
    disk_stacks: set[str],
    documented: dict[str, int],
    deployed: set[str],
    deploy_sh_line: int,
) -> list[str]:
    """One finding string per drifted stack, each citing its evidence."""
    findings: list[str] = []

    for name in sorted(set(documented) - disk_stacks):
        line = documented[name]
        findings.append(
            f"Ghost row: `{name}/` has a CLAUDE.md table row (CLAUDE.md:{line}) "
            f"but no such directory exists on disk."
        )

    for name in sorted(disk_stacks - set(documented)):
        findings.append(
            f"Undocumented stack: `{name}/` contains docker-compose.yml "
            f"({name}/docker-compose.yml) but has no row in the CLAUDE.md "
            f"Stacks & Ports Directory table."
        )

    for name in sorted(disk_stacks - deployed):
        findings.append(
            f"Deploy-list mismatch: `{name}/` is a stack directory "
            f"({name}/docker-compose.yml) but is missing from ALL_STACKS "
            f"(scripts/deploy.sh:{deploy_sh_line})."
        )

    for name in sorted(deployed - disk_stacks):
        findings.append(
            f"Deploy-list mismatch: `{name}` is listed in ALL_STACKS "
            f"(scripts/deploy.sh:{deploy_sh_line}) but no matching stack "
            f"directory exists on disk."
        )

    return findings


def main() -> int:
    claude_md_text = (REPO_ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    deploy_sh_text = (REPO_ROOT / "scripts" / "deploy.sh").read_text(encoding="utf-8")

    disk_stacks = stack_dirs(REPO_ROOT)
    documented = documented_stacks(claude_md_text)
    deployed = deploy_stacks(deploy_sh_text)
    deploy_sh_line = deploy_stacks_line(deploy_sh_text)

    findings = find_drift(disk_stacks, documented, deployed, deploy_sh_line)
    findings += stale_deploy_claims(claude_md_text, deployed, deploy_sh_line)

    if not findings:
        print("No doc drift found.")
        return 0

    print(f"Doc drift found ({len(findings)} finding(s)):")
    for finding in findings:
        print(f"  - {finding}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
