#!/usr/bin/env python3
"""Sync root .env → per-stack .env files.

Reads the root .env and each stack's .env.example to determine which keys
each stack needs, then writes <stack>/.env with matching values.

Usage:
    python3 scripts/sync_env.py              # sync all stacks
    python3 scripts/sync_env.py --stack homepage  # sync one stack
    python3 scripts/sync_env.py --dry-run    # preview without writing
"""

import argparse
import os
import sys
from pathlib import Path

# ── Ambiguous key → stack-specific override map ──────────────────────────
# Keys that appear in multiple stacks with different values. Map:
#   (stack_dir, key_in_example) → key_in_root_env
OVERRIDES = {
    # hermes-agent uses the primary hermes bot
    ("hermes-agent", "TELEGRAM_BOT_TOKEN"): "TELEGRAM_BOT_TOKEN",
    ("hermes-agent", "TELEGRAM_ALLOWED_USERS"): "TELEGRAM_ALLOWED_USERS",
    # news-feed has its own bot
    ("news-feed", "TELEGRAM_BOT_TOKEN"): "NEWS_FEED_TELEGRAM_BOT_TOKEN",
    ("news-feed", "TELEGRAM_CHAT_ID"): "NEWS_FEED_TELEGRAM_CHAT_ID",
    # watchtower has its own bot
    ("watchtower", "TELEGRAM_BOT_TOKEN"): "WATCHTOWER_TELEGRAM_BOT_TOKEN",
    ("watchtower", "TELEGRAM_CHAT_ID"): "TELEGRAM_CHAT_ID",
    # torrentwatch has its own bot
    ("torrentwatch", "TELEGRAM_BOT_TOKEN"): "TORRENTWATCH_TELEGRAM_BOT_TOKEN",
    ("torrentwatch", "TELEGRAM_CHAT_ID"): "TORRENTWATCH_TELEGRAM_CHAT_ID",
    # secretary/ingest uses its own notion token (not the deploy sync one)
    ("secretary/ingest", "NOTION_TOKEN"): "SECRETARY_NOTION_TOKEN",
    # news-feed uses openrouter key
    ("news-feed", "OPENROUTER_API_KEY"): "OPENROUTER_API_KEY",
    # secretary/query uses openrouter
    ("secretary/query", "OPENROUTER_API_KEY"): "OPENROUTER_API_KEY",
}


def load_env(path: Path) -> dict[str, str]:
    """Parse a .env file into a dict. Ignores comments and blank lines."""
    env: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # strip surrounding quotes
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        env[key] = value
    return env


def parse_example_keys(path: Path) -> list[str]:
    """Extract key names from a .env.example file (order preserved)."""
    keys: list[str] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key = line.partition("=")[0].strip()
        if key:
            keys.append(key)
    return keys


def stack_label(stack_dir: Path, project_root: Path) -> str:
    """Return relative path string like 'homepage' or 'secretary/ingest'."""
    return str(stack_dir.relative_to(project_root))


def sync_stack(
    stack_dir: Path,
    project_root: Path,
    root_env: dict[str, str],
    dry_run: bool = False,
) -> tuple[list[str], list[str]]:
    """Write .env for one stack. Returns (written_keys, missing_keys)."""
    example = stack_dir / ".env.example"
    if not example.exists():
        return [], []

    label = stack_label(stack_dir, project_root)
    keys = parse_example_keys(example)

    lines: list[str] = []
    lines.append(f"# Auto-synced from root .env by scripts/sync_env.py")
    lines.append(f"# Stack: {label}")
    lines.append("")

    written: list[str] = []
    missing: list[str] = []

    for key in keys:
        # Check for stack-specific override
        override_key = OVERRIDES.get((label, key))
        lookup = override_key if override_key else key

        if lookup in root_env:
            lines.append(f"{key}={root_env[lookup]}")
            written.append(key)
        else:
            # Keep placeholder comment so compose doesn't break hard
            lines.append(f"# {key}=  # TODO: not found in root .env")
            missing.append(key)

    content = "\n".join(lines) + "\n"

    if not dry_run:
        env_file = stack_dir / ".env"
        env_file.write_text(content)

    return written, missing


def find_stacks(project_root: Path) -> list[Path]:
    """Find all directories containing .env.example (excluding root)."""
    stacks: list[Path] = []
    for p in sorted(project_root.rglob(".env.example")):
        if p.parent == project_root:
            continue  # skip root .env.example
        stacks.append(p.parent)
    return stacks


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync root .env to per-stack .env files")
    parser.add_argument("--stack", help="Sync only this stack (e.g. homepage, secretary/ingest)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    project_root = script_dir.parent
    root_env_path = project_root / ".env"

    if not root_env_path.exists():
        print(f"✘ Root .env not found at {root_env_path}", file=sys.stderr)
        print("  Copy .env.example to .env and fill in values first.", file=sys.stderr)
        return 1

    root_env = load_env(root_env_path)
    stacks = find_stacks(project_root)

    if args.stack:
        stacks = [s for s in stacks if stack_label(s, project_root) == args.stack]
        if not stacks:
            print(f"✘ Stack '{args.stack}' not found", file=sys.stderr)
            return 1

    if args.dry_run:
        print("▶ DRY RUN — no files will be written\n")

    total_ok = 0
    total_missing = 0

    for stack_dir in stacks:
        label = stack_label(stack_dir, project_root)
        written, missing = sync_stack(stack_dir, project_root, root_env, args.dry_run)

        if not written and not missing:
            continue

        status = "✔" if not missing else "⚠"
        prefix = "  [dry] " if args.dry_run else "  "

        if missing:
            print(f"{status} {label}: {len(written)} synced, {len(missing)} MISSING: {', '.join(missing)}")
        else:
            print(f"{status} {label}: {len(written)} synced")

        total_ok += len(written)
        total_missing += len(missing)

    print(f"\n{'─' * 50}")
    print(f"Total: {total_ok} keys synced, {total_missing} missing")
    if args.dry_run:
        print("(dry run — no files written)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
