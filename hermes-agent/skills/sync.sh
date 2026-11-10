#!/usr/bin/env bash
# Copy the repo-owned Hermes skills into the live skills dir. Runs INSIDE hermes-gateway, from the clone:
#   docker exec -u hermes hermes-gateway bash -lc \
#     'cd /opt/data/centralized-nas-container-management && git pull --ff-only && bash hermes-agent/skills/sync.sh'
# (`make hermes-skills` on the workstation does exactly that over ssh. Hermes can run the same two
#  commands from its own terminal, so a change made from the phone does not need the Mac.)
#
# - Only git-tracked files are copied (no __pycache__, no local junk).
# - Runtime data lives OUTSIDE the skills: /opt/data/clips/{jobs,logs,flow-state} (created here if missing).
# - Afterwards every synced skill is pinned + locked (`hermes curator pin|lock`): the agent and the curator
#   cannot edit it in place; changes go through this repo. `hermes curator unlock` is refused to the agent.
# - A file that was synced before and is no longer tracked is deleted (manifest .repo-synced).
# - shopee-clip/scripts/check_delivery.py is also copied to /opt/data/scripts/ (the watchdog cron
#   can only run scripts from there).
# DRY=1 prints what would change. SKIP_TESTS=1 skips the test gate (emergencies only).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
SRC=hermes-agent/skills
DST=${HERMES_SKILLS_DIR:-/opt/data/skills}
SKILLS=(shopee-clip flow-driver gameplay-clips)
run() { if [ "${DRY:-}" = 1 ]; then echo "DRY: $*"; else "$@"; fi; }

# Tests gate the sync: router size budget, unique file names, clipjob/product_build behaviour.
if [ "${SKIP_TESTS:-}" != 1 ]; then
  if ! uv run -q --with pytest pytest -q -p no:cacheprovider tests/test_hermes_skills.py "$SRC/shopee-clip/scripts" "$SRC/gameplay-clips/scripts/test_source_check.py" >/tmp/hermes-skills-tests.log 2>&1; then
    tail -30 /tmp/hermes-skills-tests.log >&2
    echo "REFUSED: tests failed — nothing synced (fix in the repo, push, rerun)" >&2
    exit 1
  fi
  echo "tests: $(tail -1 /tmp/hermes-skills-tests.log)"
fi

for s in "${SKILLS[@]}"; do
  mapfile -t files < <(git ls-files "$SRC/$s" | sed "s#^$SRC/$s/##")
  [ "${#files[@]}" -gt 0 ] || { echo "no tracked files for $s" >&2; exit 2; }
  man="$DST/$s/.repo-synced"
  if [ -f "$man" ]; then
    while IFS= read -r old; do
      [ -n "$old" ] || continue
      if ! printf '%s\n' "${files[@]}" | grep -qxF -- "$old" && [ -e "$DST/$s/$old" ]; then
        run rm -f -- "$DST/$s/$old"; echo "removed $s/$old"
      fi
    done < "$man"
  fi
  n=0
  for f in "${files[@]}"; do
    if ! cmp -s "$SRC/$s/$f" "$DST/$s/$f" 2>/dev/null; then
      run mkdir -p "$(dirname "$DST/$s/$f")"
      run cp -p "$SRC/$s/$f" "$DST/$s/$f"
      n=$((n + 1))
    fi
  done
  [ "${DRY:-}" = 1 ] || printf '%s\n' "${files[@]}" > "$man"
  echo "$s: ${#files[@]} tracked, $n updated"
done
run mkdir -p /opt/data/clips/jobs /opt/data/clips/logs /opt/data/clips/flow-state
HERMES=${HERMES_BIN:-/opt/hermes/.venv/bin/hermes}
for s in "${SKILLS[@]}"; do
  if [ "${DRY:-}" != 1 ] && [ -x "$HERMES" ]; then
    "$HERMES" curator pin "$s" >/dev/null 2>&1 || echo "WARN: curator pin $s failed" >&2
    "$HERMES" curator lock "$s" >/dev/null 2>&1 || echo "WARN: curator lock $s failed" >&2
  fi
done
if ! cmp -s "$SRC/shopee-clip/scripts/check_delivery.py" /opt/data/scripts/check_delivery.py 2>/dev/null; then
  run cp -p "$SRC/shopee-clip/scripts/check_delivery.py" /opt/data/scripts/check_delivery.py
  echo "updated /opt/data/scripts/check_delivery.py"
fi
echo "synced at $(git rev-parse --short HEAD)"
