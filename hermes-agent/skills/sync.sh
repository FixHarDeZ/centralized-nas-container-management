#!/usr/bin/env bash
# Copy the repo-owned Hermes skills into the live skills dir. Runs INSIDE hermes-gateway, from the clone:
#   docker exec -u hermes hermes-gateway bash -lc \
#     'cd /opt/data/centralized-nas-container-management && git pull --ff-only && bash hermes-agent/skills/sync.sh'
# (`make hermes-skills` on the workstation does exactly that over ssh. Hermes can run the same two
#  commands from its own terminal, so a change made from the phone does not need the Mac.)
#
# - Only git-tracked files are copied (no __pycache__, no local junk).
# - Runtime data lives OUTSIDE the skills: /opt/data/clips/{jobs,logs,flow-state} (created here if missing).
# - Afterwards every synced skill is pinned (`hermes curator pin`: the curator never archives/merges it).
#   NOT locked: the lock's terminal check is a heuristic and refused legit pipeline commands (2026-11-10:
#   an inline python that wrote vo_plan.json in the work dir, chained with a gameplay script path).
# - In-place edits (by the agent or the curator's background review) are CAPTURED, not lost: a live file
#   that differs from what the last sync wrote is copied to /opt/data/clips/skill-drift/<ts>/ with a
#   diff, then overwritten. Port anything worth keeping into the repo. Agent-created extra files are
#   reported and left in place.
# - A file that was synced before and is no longer tracked is deleted (manifest .repo-synced; its first
#   line records the synced commit, the baseline for drift detection).
# - shopee-clip/scripts/check_delivery.py is also copied to /opt/data/scripts/ (the watchdog cron
#   can only run scripts from there).
# `sync.sh --pull` (or PULL=1) goes the other way for in-place edits: each drifted live file is copied INTO
#   the clone's working tree and nothing live is touched. Review with git diff, commit, push, then sync.
#   This is how a lesson written into a live skill reaches the repo. A plain sync refuses while the
#   clone has uncommitted skill changes (it would copy them live under the wrong baseline commit).
# DRY=1 prints what would change. SKIP_TESTS=1 skips the test gate (emergencies only).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
SRC=hermes-agent/skills
DST=${HERMES_SKILLS_DIR:-/opt/data/skills}
SKILLS=(shopee-clip flow-driver gameplay-clips)
run() { if [ "${DRY:-}" = 1 ]; then echo "DRY: $*"; else "$@"; fi; }

# Tests gate the sync: router size budget, unique file names, clipjob/product_build behaviour.
[ "${1:-}" = "--pull" ] && PULL=1
PULL=${PULL:-}

# A dirty tree would be copied live while the manifest records HEAD, which breaks the drift baseline.
if [ -z "$PULL" ] && [ "${ALLOW_DIRTY:-}" != 1 ] && [ -n "$(git status --porcelain -- "$SRC")" ]; then
  git status --short -- "$SRC" >&2
  echo "REFUSED: uncommitted changes under $SRC — commit and push them first (ALLOW_DIRTY=1 overrides)" >&2
  exit 1
fi

# Tests gate the sync: router size budget, unique file names, clipjob/product_build/build_v5 behaviour.
if [ -z "$PULL" ] && [ "${SKIP_TESTS:-}" != 1 ]; then
  if ! uv run -q --with pytest --with numpy --with pillow pytest -q -p no:cacheprovider tests/test_hermes_skills.py "$SRC/shopee-clip/scripts" "$SRC/gameplay-clips/scripts" >/tmp/hermes-skills-tests.log 2>&1; then
    tail -30 /tmp/hermes-skills-tests.log >&2
    echo "REFUSED: tests failed — nothing synced (fix in the repo, push, rerun)" >&2
    exit 1
  fi
  echo "tests: $(tail -1 /tmp/hermes-skills-tests.log)"
fi

DRIFT_ROOT=/opt/data/clips/skill-drift
TS=$(date +%Y%m%d-%H%M%S)
drift_n=0
for s in "${SKILLS[@]}"; do
  mapfile -t files < <(git ls-files "$SRC/$s" | sed "s#^$SRC/$s/##")
  [ "${#files[@]}" -gt 0 ] || { echo "no tracked files for $s" >&2; exit 2; }
  man="$DST/$s/.repo-synced"
  base=""
  [ -f "$man" ] && base=$(sed -n 's/^#commit //p' "$man" | head -1)
  base=${base:-${SYNC_BASE:-}}     # SYNC_BASE=<commit>: baseline for manifests written before drift capture
  # drift: live file differs from what the last sync wrote (baseline commit), or from the repo when unknown
  for f in "${files[@]}"; do
    live="$DST/$s/$f"
    [ -f "$live" ] || continue
    cmp -s "$SRC/$s/$f" "$live" && continue
    if [ -n "$base" ] && git cat-file -e "$base:$SRC/$s/$f" 2>/dev/null; then
      git show "$base:$SRC/$s/$f" | cmp -s - "$live" && continue      # untouched since last sync = repo change
    fi
    if [ -n "$PULL" ]; then
      run cp -p "$live" "$SRC/$s/$f"
      echo "PULLED: $s/$f (live edit copied into the clone)"
      drift_n=$((drift_n + 1))
      continue
    fi
    out="$DRIFT_ROOT/$TS/$s/$f"
    run mkdir -p "$(dirname "$out")"
    run cp -p "$live" "$out"
    [ "${DRY:-}" = 1 ] || diff -u "$SRC/$s/$f" "$live" > "$out.diff" 2>/dev/null || true
    echo "DRIFT: $s/$f edited in place — saved to $out"
    drift_n=$((drift_n + 1))
  done
  # extra files the agent created inside the skill (left in place, reported)
  while IFS= read -r extra; do
    rel=${extra#"$DST/$s/"}
    printf '%s\n' "${files[@]}" | grep -qxF -- "$rel" && continue
    echo "EXTRA (not in repo, kept): $s/$rel"
  done < <(find "$DST/$s" -type f ! -name .repo-synced ! -path '*/__pycache__/*' ! -path '*/.pytest_cache/*' 2>/dev/null)
  [ -n "$PULL" ] && continue
  if [ -f "$man" ]; then
    while IFS= read -r old; do
      [ -n "$old" ] || continue
      [[ "$old" == "#"* ]] && continue
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
  [ "${DRY:-}" = 1 ] || { echo "#commit $(git rev-parse HEAD)"; printf '%s\n' "${files[@]}"; } > "$man"
  echo "$s: ${#files[@]} tracked, $n updated"
done
if [ -n "$PULL" ]; then
  echo "pulled $drift_n live edit(s) into the clone — review with git diff, commit, push, then sync"
  exit 0
fi
run mkdir -p /opt/data/clips/jobs /opt/data/clips/logs /opt/data/clips/flow-state
HERMES=${HERMES_BIN:-/opt/hermes/.venv/bin/hermes}
for s in "${SKILLS[@]}"; do
  if [ "${DRY:-}" != 1 ] && [ -x "$HERMES" ]; then
    "$HERMES" curator pin "$s" >/dev/null 2>&1 || echo "WARN: curator pin $s failed" >&2
  fi
done
if ! cmp -s "$SRC/shopee-clip/scripts/check_delivery.py" /opt/data/scripts/check_delivery.py 2>/dev/null; then
  run cp -p "$SRC/shopee-clip/scripts/check_delivery.py" /opt/data/scripts/check_delivery.py
  echo "updated /opt/data/scripts/check_delivery.py"
fi
[ "$drift_n" -gt 0 ] && echo "⚠️  $drift_n in-place edit(s) captured in $DRIFT_ROOT/$TS — review and port to the repo"
echo "synced at $(git rev-parse --short HEAD)"
