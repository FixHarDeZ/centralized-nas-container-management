#!/usr/bin/env bash
# Code worker owns its home and /workspaces; production credentials stay elsewhere.
set -euo pipefail
mkdir -p /workspaces "$HOME/.claude/skills" "$HOME/.agents/skills" "$HOME/.codex"
for skill in /opt/user-skills/*/; do
    [[ -f "$skill/SKILL.md" ]] || continue
    name=$(basename "$skill")
    for folder in "$HOME/.claude/skills" "$HOME/.agents/skills"; do
        if [[ ! -e "$folder/$name" || -L "$folder/$name" ]]; then
            ln -sfn "${skill%/}" "$folder/$name"
        fi
    done
done
git config --global credential.https://github.com.helper '!gh auth git-credential'
# No Git author is invented: gh login and git user.name/user.email are operator setup.
cd /workspaces
( while true; do python3 /opt/ai-deck/upload.py; sleep 2; done ) &
( while true; do python3 /opt/ai-deck/chat.py; sleep 2; done ) &
IFS=',' read -ra desks <<< "${DESK_USERS:-desk:7681}"
primary_port=''
primary_user=''
for entry in "${desks[@]}"; do
    user="${entry%%:*}"
    port="${entry##*:}"
    session=$(printf '%s' "$user" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_-' '-')
    if [[ -z "$primary_port" ]]; then
        primary_port="$port"; primary_user="$user"
    else
        ( while true; do ttyd -a -W -p "$port" -m 2 -P 30 -t disableLeaveAlert=true python3 /opt/ai-deck/coding_terminal.py "$user"; sleep 2; done ) &
    fi
done
exec ttyd -a -W -p "$primary_port" -m 2 -P 30 -t disableLeaveAlert=true python3 /opt/ai-deck/coding_terminal.py "$primary_user"
