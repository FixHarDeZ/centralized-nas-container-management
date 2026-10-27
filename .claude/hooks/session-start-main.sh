#!/usr/bin/env bash
# Cloud sessions start on a per-session claude/* branch. This repo works on
# main directly, so move the checkout back to an up-to-date main — but only
# when nothing would be lost (clean tree, no commits beyond origin/main).
# Always exits 0: a failing SessionStart hook would be reported into the session.
[ "${CLAUDE_CODE_REMOTE:-}" = "true" ] || exit 0
cd "${CLAUDE_PROJECT_DIR:-.}" 2>/dev/null || exit 0

branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null) || exit 0
git fetch -q origin main 2>/dev/null || { echo "session-start: fetch origin main failed, staying on $branch"; exit 0; }

if [ "$branch" != "main" ]; then
  if [ -n "$(git status --porcelain)" ]; then
    echo "session-start: $branch has uncommitted changes, not switching to main"; exit 0
  fi
  if [ -n "$(git log --oneline origin/main..HEAD)" ]; then
    echo "session-start: $branch has commits not on main, not switching"; exit 0
  fi
  git checkout -q -B main origin/main && echo "session-start: switched $branch -> main" || exit 0
else
  git pull -q --ff-only origin main 2>/dev/null || echo "session-start: main could not fast-forward"
fi
git branch --set-upstream-to=origin/main main >/dev/null 2>&1
echo "session-start: on main @ $(git rev-parse --short HEAD) — commit and push to main directly (see CLAUDE.md)"
exit 0
