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
# - shopee-clip/scripts/check_delivery.py + clip_heartbeat.py are also copied to /opt/data/scripts/ (the cron
#   can only run scripts from there).
# - hermes-agent/locales/*.yaml (i18n overlay: the gateway's Thai busy ack "📥 รับคิวแล้วค่ะ") is copied to
#   $HERMES_HOME/locales/. The gateway caches catalogs per process: a changed file shows after a gateway restart.
# `sync.sh --pull` (or PULL=1) goes the other way for in-place edits: each drifted live file is copied INTO
#   the clone's working tree and nothing live is touched. Review with git diff, commit, push, then sync.
#   This is how a lesson written into a live skill reaches the repo. A plain sync refuses while the
#   clone has uncommitted skill changes (it would copy them live under the wrong baseline commit).
# LIVE EDITS COME FIRST: a plain sync REFUSES (exit 3, nothing copied) while a live file carries an in-place
#   edit that was never pulled. Run `--pull`, merge it with the repo change, commit, push, then sync. `--pull`
#   records each pulled file's hash in <skill>/.pulled, so the sync that follows knows the edit is in the
#   repo's history and lets that file through. DRIFT_OK=1 = old behaviour (capture to skill-drift/, overwrite).
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
  if ! uv run -q --with pytest --with numpy --with pillow --with pyyaml pytest -q -p no:cacheprovider tests/test_hermes_skills.py tests/test_hermes_locales.py "$SRC/shopee-clip/scripts" "$SRC/gameplay-clips/scripts" "$SRC/flow-driver/scripts" >/tmp/hermes-skills-tests.log 2>&1; then
    tail -30 /tmp/hermes-skills-tests.log >&2
    echo "REFUSED: tests failed — nothing synced (fix in the repo, push, rerun)" >&2
    exit 1
  fi
  echo "tests: $(tail -1 /tmp/hermes-skills-tests.log)"
fi

CLIPS=${CLIPS_DIR:-/opt/data/clips}
SCRIPTS_DST=${HERMES_SCRIPTS_DIR:-/opt/data/scripts}
DRIFT_ROOT=$CLIPS/skill-drift
TS=$(date +%Y%m%d-%H%M%S)
drift_n=0
sum() { sha256sum "$1" | cut -d' ' -f1; }
# live file differs from the repo AND from what the last sync wrote = an in-place edit
drifted() {   # $1 skill  $2 file  $3 baseline commit
  local live="$DST/$1/$2"
  [ -f "$live" ] || return 1
  cmp -s "$SRC/$1/$2" "$live" && return 1
  if [ -n "$3" ] && git cat-file -e "$3:$SRC/$1/$2" 2>/dev/null; then
    git show "$3:$SRC/$1/$2" | cmp -s - "$live" && return 1
  fi
  return 0
}
baseline() { local b=""; [ -f "$DST/$1/.repo-synced" ] && b=$(sed -n 's/^#commit //p' "$DST/$1/.repo-synced" | head -1); echo "${b:-${SYNC_BASE:-}}"; }
pulled() { [ -f "$DST/$1/.pulled" ] && grep -qxF -- "$(sum "$DST/$1/$2")  $2" "$DST/$1/.pulled"; }

# Pass 1 (plain sync only): refuse before touching anything when a live edit has not been pulled.
if [ -z "$PULL" ] && [ "${DRIFT_OK:-}" != 1 ]; then
  unpulled=()
  for s in "${SKILLS[@]}"; do
    base=$(baseline "$s")
    while IFS= read -r f; do
      drifted "$s" "$f" "$base" && ! pulled "$s" "$f" && unpulled+=("$s/$f")
    done < <(git ls-files "$SRC/$s" | sed "s#^$SRC/$s/##")
  done
  if [ "${#unpulled[@]}" -gt 0 ]; then
    printf 'LIVE EDIT: %s\n' "${unpulled[@]}" >&2
    echo "REFUSED: ${#unpulled[@]} live in-place edit(s) are not in the repo — nothing synced." >&2
    echo "  bash $SRC/sync.sh --pull   (make hermes-skills ARGS=--pull) → merge with the repo change, commit, push, sync again." >&2
    echo "  DRIFT_OK=1 overwrites them (a copy goes to $DRIFT_ROOT)." >&2
    [ "${DRY:-}" = 1 ] || exit 3
  fi
fi
for s in "${SKILLS[@]}"; do
  mapfile -t files < <(git ls-files "$SRC/$s" | sed "s#^$SRC/$s/##")
  [ "${#files[@]}" -gt 0 ] || { echo "no tracked files for $s" >&2; exit 2; }
  man="$DST/$s/.repo-synced"
  base=$(baseline "$s")            # SYNC_BASE=<commit>: baseline for manifests written before drift capture
  # drift: live file differs from what the last sync wrote (baseline commit), or from the repo when unknown
  for f in "${files[@]}"; do
    live="$DST/$s/$f"
    drifted "$s" "$f" "$base" || continue
    if [ -n "$PULL" ]; then
      run cp -p "$live" "$SRC/$s/$f"
      [ "${DRY:-}" = 1 ] || echo "$(sum "$live")  $f" >> "$DST/$s/.pulled"
      echo "PULLED: $s/$f (live edit copied into the clone)"
      drift_n=$((drift_n + 1))
      continue
    fi
    pulled "$s" "$f" && continue      # already pulled into the repo's history: the merged version replaces it
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
  done < <(find "$DST/$s" -type f ! -name .repo-synced ! -name .pulled ! -path '*/__pycache__/*' ! -path '*/.pytest_cache/*' 2>/dev/null)
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
  [ "${DRY:-}" = 1 ] || { { echo "#commit $(git rev-parse HEAD)"; printf '%s\n' "${files[@]}"; } > "$man"; rm -f "$DST/$s/.pulled"; }
  echo "$s: ${#files[@]} tracked, $n updated"
done
if [ -n "$PULL" ]; then
  echo "pulled $drift_n live edit(s) into the clone — review with git diff, commit, push, then sync"
  exit 0
fi
run mkdir -p "$CLIPS/jobs" "$CLIPS/logs" "$CLIPS/flow-state"
HERMES=${HERMES_BIN:-/opt/hermes/.venv/bin/hermes}
for s in "${SKILLS[@]}"; do
  if [ "${DRY:-}" != 1 ] && [ -x "$HERMES" ]; then
    "$HERMES" curator pin "$s" >/dev/null 2>&1 || echo "WARN: curator pin $s failed" >&2
  fi
done
for cron_script in check_delivery.py clip_heartbeat.py; do     # Hermes' no-agent cron runs scripts from here only
  if ! cmp -s "$SRC/shopee-clip/scripts/$cron_script" "$SCRIPTS_DST/$cron_script" 2>/dev/null; then
    run mkdir -p "$SCRIPTS_DST"
    run cp -p "$SRC/shopee-clip/scripts/$cron_script" "$SCRIPTS_DST/$cron_script"
    echo "updated $SCRIPTS_DST/$cron_script"
  fi
done
LOCALES_DST=${HERMES_LOCALES_DIR:-/opt/data/locales}
while IFS= read -r f; do               # i18n overlay (partial catalog over the bundled locales/)
  if ! cmp -s "$f" "$LOCALES_DST/$(basename "$f")" 2>/dev/null; then
    run mkdir -p "$LOCALES_DST"
    run cp -p "$f" "$LOCALES_DST/$(basename "$f")"
    echo "updated $LOCALES_DST/$(basename "$f") — restart the gateway to load it (catalogs are cached per process)"
  fi
done < <(git ls-files 'hermes-agent/locales/*.yaml')
[ "$drift_n" -gt 0 ] && echo "⚠️  $drift_n in-place edit(s) captured in $DRIFT_ROOT/$TS — review and port to the repo"
echo "synced at $(git rev-parse --short HEAD)"
