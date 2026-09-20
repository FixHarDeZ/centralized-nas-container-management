#!/usr/bin/env bash
#
# Stop hook: leave a mark saying a turn just ended, for the page to notice.
#
# The page has no other way to know. Its websocket carries terminal bytes, and
# "Claude stopped talking" is not something you can read out of a byte stream
# without guessing at Claude Code's drawing. This hook is the one place that
# knows for sure.
#
# Claude Code feeds the hook its session JSON on stdin. The page only needs to
# know that *something* finished and which session it was, so the file stays a
# couple of fields; upload.py hands it over with /api/status.
#
# Never fails: a non-zero exit from a Stop hook is reported back into the
# session, and a notification is not worth interrupting anyone over.
set -uo pipefail

out="$HOME/.claude/desk-done.json"
session=$(jq -r '.session_id // empty' 2>/dev/null) || session=""
tmp="$out.$$"

# Temp + rename, because upload.py reads this while Claude writes it.
if printf '{"at":%s,"session_id":"%s"}' "$(date +%s)" "$session" > "$tmp" 2>/dev/null; then
    mv -f "$tmp" "$out" 2>/dev/null || rm -f "$tmp" 2>/dev/null
fi

exit 0
