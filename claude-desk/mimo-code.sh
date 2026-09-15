#!/usr/bin/env bash
# `mimo-code` — the agent harness on the desk, with mimo as the brain.
#
# opencode (pinned in the Dockerfile) pointed at the mimo endpoint through
# /opt/claude-desk/opencode.json. It is a real tool loop — it reads, writes and
# runs things in /work on its own — which is what separates it from `mimo`,
# the one-shot answer command next to it.
#
#   mimo-code                 open the TUI in /work
#   mimo-code run "<task>"    one task, no TUI, prints what it did
#
# What to expect: mimo's wall time tracks the tokens it thinks (~30 tok/s), and
# an agent turn is never cheap — a trivial tool call measured ~28s against the
# live endpoint (2026-09-15). This is the slow, free brain; `claude` is the
# fast one that spends subscription quota. Pick per job.
set -euo pipefail

if [[ -z "${MIMO_API_KEY:-}" || -z "${MIMO_BASE_URL:-}" ]]; then
    echo "mimo-code: MIMO_API_KEY / MIMO_BASE_URL are not set (check the stack's .env)" >&2
    exit 1
fi

export OPENCODE_CONFIG=/opt/claude-desk/opencode.json

# Anything the agent starts inherits this environment, and permissions are off
# (see opencode.json). Keep the desk's Claude Code subscription token out of
# its reach — it has no use for it and it does not expire on its own.
unset CLAUDE_CODE_OAUTH_TOKEN

# in/ and out/ are the job, so a session started from somewhere else (the home
# directory a fresh tmux window opens in) lands in /work. A subdirectory of
# /work is left alone — that is someone scoping the agent on purpose.
[[ "$PWD" == /work* ]] || cd /work

exec opencode "$@"
