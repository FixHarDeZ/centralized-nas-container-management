#!/usr/bin/env python3
"""Vendor the workstation's Claude Code skills into ai-deck/skills/.

    make desk-skills          # copy every skill named in ai-deck/skills.list
    make desk-skills ARGS=-n  # report what would change, write nothing

The desk gets its skills exactly the way it gets `work/CLAUDE.md`: a copy that
travels in git and is baked into the image (`COPY skills/ /opt/user-skills/`,
the last layer). A bind was tried first and does not work — a directory under
/volume2/docker is 0700 to uid 1000 through the DSM share ACL, and chmod on
the NAS does not stick. The image's own `/opt/skills` (the pinned Anthropic
pptx/docx/xlsx/pdf set) is untouched by this.

Why an allowlist instead of copying ~/.claude/skills wholesale:

- `notebooklm/` is 196 MB and carries `data/auth_info.json` plus a logged-in
  Chrome profile. Copying the tree would commit a live Google session to a
  public repo.
- Half the set cannot work in the container at all — anything that drives a
  browser (no display server, no Chrome) or that needs the age key / NAS SSH
  key, which the desk deliberately does not have.
- The desk is for documents, not for editing this repo, so the coding-flow
  skills would only be noise in its skill list.

Each name in the list is resolved through ~/.claude/skills, following the
symlinks that point into ~/.agents/skills, and copied with the junk
directories below pruned. A skill carrying anything that looks like a
credential is refused outright rather than filtered, because "we stripped the
secret for you" is a worse habit than "this one does not travel".
"""
import argparse
import filecmp
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIST = ROOT / "ai-deck" / "skills.list"
DEST = ROOT / "ai-deck" / "skills"
SOURCE = Path.home() / ".claude" / "skills"

# Pruned everywhere: build output and local state, none of which a skill needs
# in order to be read by the agent on the other end.
PRUNE_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    "data",
    "browser_state",
    "test",
    "tests",
    "benchmarks",
    "experiments",
    "generated",
}
PRUNE_SUFFIXES = {".pyc", ".log", ".png", ".jpg", ".jpeg", ".webm", ".zip"}

# Pruned by shape rather than by name: archify ships four rendered sample
# diagrams at ~700 KB each next to the JSON specs that produce them. The
# specs are what its instructions tell the agent to read; the renders are
# five sixths of the skill's weight.
PRUNE_GLOBS = ("examples/*.html",)

# Refuse the whole skill on sight of one of these. Matched against the path
# relative to the skill root, lowercased.
SECRET_MARKERS = (
    "auth_info",
    "credentials",
    "token.json",
    "cookies",
    ".env",
    "id_rsa",
    "id_ed25519",
    "keys.txt",
)


def wanted() -> list:
    """Skill names from skills.list, comments and blanks dropped."""
    names = []
    for line in LIST.read_text(encoding="utf-8").splitlines():
        name = line.split("#", 1)[0].strip()
        if name:
            names.append(name)
    return names


def secrets_in(skill: Path) -> list:
    """Paths under `skill` whose name reads like a credential."""
    hits = []
    for path in skill.rglob("*"):
        if path.is_dir():
            continue
        rel = str(path.relative_to(skill)).lower()
        if any(marker in rel for marker in SECRET_MARKERS):
            hits.append(rel)
    return hits


def copy_skill(src: Path, dst: Path) -> int:
    """Copy src → dst minus the pruned paths. Returns files written."""
    written = 0
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if any(part in PRUNE_DIRS for part in rel.parts):
            continue
        if path.is_dir():
            continue
        if path.suffix.lower() in PRUNE_SUFFIXES:
            continue
        if any(rel.match(pattern) for pattern in PRUNE_GLOBS):
            continue
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        written += 1
    return written


def size_kb(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) // 1024


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "-n", "--dry-run", action="store_true", help="report only, write nothing"
    )
    args = parser.parse_args()

    names = wanted()
    missing = [n for n in names if not (SOURCE / n).is_dir()]
    if missing:
        print(
            f"not on this workstation: {', '.join(missing)}\n"
            f"(install them under {SOURCE}, or drop them from {LIST.relative_to(ROOT)})",
            file=sys.stderr,
        )
        return 1

    unsafe = {n: secrets_in(SOURCE / n) for n in names}
    unsafe = {n: hits for n, hits in unsafe.items() if hits}
    if unsafe:
        for name, hits in unsafe.items():
            print(f"{name}: refusing, credential-shaped files: {', '.join(hits[:3])}", file=sys.stderr)
        return 1

    stale = [d.name for d in DEST.iterdir() if d.is_dir()] if DEST.is_dir() else []
    stale = sorted(set(stale) - set(names))

    if args.dry_run:
        for name in names:
            src = SOURCE / name
            dst = DEST / name
            state = "new" if not dst.is_dir() else (
                "unchanged"
                if not filecmp.dircmp(str(src), str(dst)).diff_files
                else "changed"
            )
            print(f"  {state:9} {name} ({size_kb(src)} KB on disk)")
        for name in stale:
            print(f"  remove    {name} (no longer in skills.list)")
        return 0

    DEST.mkdir(parents=True, exist_ok=True)
    for name in stale:
        shutil.rmtree(DEST / name)
        print(f"removed {name}")

    total = 0
    for name in names:
        dst = DEST / name
        if dst.is_dir():
            shutil.rmtree(dst)
        written = copy_skill(SOURCE / name, dst)
        total += written
        print(f"synced {name} ({written} files, {size_kb(dst)} KB)")

    print(f"\n{len(names)} skills, {total} files, {size_kb(DEST)} KB → {DEST.relative_to(ROOT)}")
    print("next: ./scripts/deploy.sh -s ai-deck -y  (rebuilds the last image\n      layer, ~1 min: apt/npm/pip stay cached)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
