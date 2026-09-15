#!/usr/bin/env bash
# Prepare the home volume, then hand PID 1 to ttyd.
#
# /home/claude is a named volume so `claude --resume` and the onboarding
# state survive restarts. The skills live in the image (/opt/skills) and are
# re-linked on every start so a SKILLS_REF bump shows up without touching the
# volume.
set -euo pipefail

SKILLS_DIR="$HOME/.claude/skills"
mkdir -p "$SKILLS_DIR" /work/in /work/out

for skill in pptx docx xlsx pdf; do
    ln -sfn "/opt/skills/skills/$skill" "$SKILLS_DIR/$skill"
done

# The work-folder rules travel with the stack (work/CLAUDE.md) but live on
# the NAS share — copy on start so an edit in git reaches the desk.
if [[ -f /opt/claude-desk/work/CLAUDE.md ]]; then
    cp /opt/claude-desk/work/CLAUDE.md /work/CLAUDE.md
fi

# Debian's skeleton ~/.bashrc (copied into the home volume on first run)
# sets PS1 after /etc/profile.d has run, so the prompt has to be appended
# here rather than set in profile.sh. Idempotent.
if ! grep -q 'claude-desk prompt' "$HOME/.bashrc" 2>/dev/null; then
    cat >> "$HOME/.bashrc" <<'EOF'

# claude-desk prompt
PS1='\[\e[38;5;214m\]desk\[\e[0m\] \[\e[38;5;245m\]\w\[\e[0m\] › '
EOF
fi

# Merge the stack's Claude Code settings (rtk hook) into the home volume's
# ~/.claude/settings.json without clobbering anything set from inside the
# desk (theme, model, ...). Hooks from the template are added once, keyed by
# their command string.
python3 - "$HOME/.claude/settings.json" /opt/claude-desk/claude-settings.json <<'PY'
import json, sys, os
dst, src = sys.argv[1], sys.argv[2]
tmpl = json.load(open(src))
cur = json.load(open(dst)) if os.path.exists(dst) else {}
hooks = cur.setdefault("hooks", {})
for event, entries in tmpl.get("hooks", {}).items():
    have = {h.get("command") for e in hooks.get(event, []) for h in e.get("hooks", [])}
    for entry in entries:
        if not all(h.get("command") in have for h in entry.get("hooks", [])):
            hooks.setdefault(event, []).append(entry)
for k, v in tmpl.items():
    # _-prefixed keys are comments for whoever reads the template — JSON has
    # none of its own — and must not end up in Claude Code's settings.
    if k != "hooks" and not k.startswith("_"):
        cur.setdefault(k, v)
json.dump(cur, open(dst, "w"), indent=2)
PY

# MiMoCode config. Written on every start from the image copy, because
# ~/.config is inside the home volume and docker only seeds a volume while it
# is empty — shipping the file straight there would never reach this desk.
# The key is substituted here so it lives in .env rather than in git.
if [[ -n "${MIMO_API_KEY:-}" && -n "${MIMO_BASE_URL:-}" ]]; then
    mkdir -p "$HOME/.config/mimocode"
    # python rather than sed: an & or a | in a rotated key would be taken as
    # sed syntax and silently write the placeholder back.
    python3 - "$HOME/.config/mimocode/mimocode.jsonc" <<'PY'
import os, sys
src = open("/opt/claude-desk/mimocode.jsonc").read()
src = src.replace("__MIMO_BASE_URL__", os.environ["MIMO_BASE_URL"])
src = src.replace("__MIMO_API_KEY__", os.environ["MIMO_API_KEY"])
open(sys.argv[1], "w").write(src)
PY
    chmod 600 "$HOME/.config/mimocode/mimocode.jsonc"
else
    echo "WARNING: MIMO_API_KEY / MIMO_BASE_URL are empty — \`mimo\` and \`ask\` will not work" >&2
fi

if [[ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]]; then
    echo "WARNING: CLAUDE_CODE_OAUTH_TOKEN is empty — claude will ask you to log in" >&2
fi

# Upload receiver for the page's "Add files" button (PUT /upload/<name> →
# /work/in). Restarted by the loop if it ever dies; ttyd stays PID 1.
(
    while true; do
        python3 /opt/claude-desk/upload.py
        sleep 2
    done
) &

# -W        writable (ttyd >= 1.7 is read-only by default)
# -m 1      one browser at a time; the tmux session is shared anyway, and a
#           second client is either you on another device or an intruder
# -P 30     websocket ping so the DSM reverse proxy never idles us out
# tmux new -A: attach if `main` exists, create otherwise — a closed tab is
#           not a lost job
exec ttyd -W -p 7681 -m 1 -P 30 \
    -t disableLeaveAlert=true \
    tmux new-session -A -s main
