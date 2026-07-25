#!/usr/bin/env bash
# Run Claude Code through pxpipe proxy (https://github.com/teamchong/pxpipe)
# Usage: ./scripts/claude-px.sh [claude args...]
set -euo pipefail

PXPIPE_PORT="${PXPIPE_PORT:-47821}"
PXPIPE_URL="http://127.0.0.1:${PXPIPE_PORT}"

# start proxy if not already up
if ! curl -sf -o /dev/null --max-time 2 "$PXPIPE_URL/"; then
  echo "starting pxpipe proxy on :$PXPIPE_PORT ..."
  nohup npx pxpipe-proxy >"${TMPDIR:-/tmp}/pxpipe.log" 2>&1 &
  for _ in $(seq 1 30); do
    curl -sf -o /dev/null --max-time 1 "$PXPIPE_URL/" && break
    sleep 1
  done
  curl -sf -o /dev/null "$PXPIPE_URL/" || {
    echo "pxpipe failed to start, see ${TMPDIR:-/tmp}/pxpipe.log" >&2
    exit 1
  }
fi

echo "pxpipe up: $PXPIPE_URL (dashboard: $PXPIPE_URL/)"
ANTHROPIC_BASE_URL="$PXPIPE_URL" exec claude "$@"
