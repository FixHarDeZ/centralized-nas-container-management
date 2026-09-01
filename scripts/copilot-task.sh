#!/usr/bin/env bash
# Run a bulk implementation task through Copilot CLI, non-interactively.
# Usage: scripts/copilot-task.sh "<task prompt>"
set -euo pipefail

[ $# -ge 1 ] || { echo "usage: $0 <task prompt>" >&2; exit 2; }

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# ponytail: deny-tool is pattern matching, not a real boundary; the agent body
# also forbids constructing push commands. Tighten only if it proves leaky.
exec copilot -C "$REPO_ROOT" -p "$*" \
  --allow-all-tools \
  --deny-tool='shell(git push)' \
  --deny-tool='shell(gh)' \
  --no-ask-user \
  --no-color \
  --log-level error
