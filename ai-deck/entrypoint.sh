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

# The workstation's skills (ai-deck/skills, see skills.list). Linked, not
# copied, so a deploy that changes one is live without touching the home
# volume — but a skill added to the list still needs this loop to run, i.e. a
# restart. Stale links are cleared first: dropping a name from skills.list
# has to remove it from the desk too.
for link in "$SKILLS_DIR"/*; do
    [[ -L "$link" && "$(readlink "$link")" == /opt/user-skills/* ]] || continue
    [[ -d "$link/" ]] || rm -f "$link"
done
if [[ -d /opt/user-skills ]]; then
    for skill in /opt/user-skills/*/; do
        [[ -f "$skill/SKILL.md" ]] || continue
        name=$(basename "$skill")
        # ln -sfn onto a real directory of the same name would put the link
        # *inside* it (skill-creator run on the desk can make one). Leave the
        # desk's own copy alone and say so.
        if [[ -e "$SKILLS_DIR/$name" && ! -L "$SKILLS_DIR/$name" ]]; then
            echo "skills: keeping the desk's own $name, not linking the vendored one" >&2
            continue
        fi
        ln -sfn "${skill%/}" "$SKILLS_DIR/$name"
    done
fi

# The work-folder rules travel with the stack (work/CLAUDE.md) but live on
# the NAS share — copy on start so an edit in git reaches the desk.
if [[ -f /opt/ai-deck/work/CLAUDE.md ]]; then
    cp /opt/ai-deck/work/CLAUDE.md /work/CLAUDE.md
fi

# Debian's skeleton ~/.bashrc (copied into the home volume on first run)
# sets PS1 after /etc/profile.d has run, so the prompt has to be appended
# here rather than set in profile.sh. Idempotent.
if ! grep -Eq '(claude-desk|ai-deck) prompt' "$HOME/.bashrc" 2>/dev/null; then
    cat >> "$HOME/.bashrc" <<'EOF'

# ai-deck prompt
PS1='\[\e[38;5;214m\]desk\[\e[0m\] \[\e[38;5;245m\]\w\[\e[0m\] › '
EOF
fi

# Merge the stack's Claude Code settings (rtk hook) into the home volume's
# ~/.claude/settings.json without clobbering anything set from inside the
# desk (theme, model, ...). Hooks from the template are added once, keyed by
# their command string.
python3 - "$HOME/.claude/settings.json" /opt/ai-deck/claude-settings.json <<'PY'
import json, sys, os
dst, src = sys.argv[1], sys.argv[2]
tmpl = json.load(open(src))
cur = json.load(open(dst)) if os.path.exists(dst) else {}
# Migrate only commands owned by this stack. Existing home volumes still
# reference the old image directory; setdefault alone would leave broken hooks.
def migrate_command(item):
    command = item.get("command") if isinstance(item, dict) else None
    if isinstance(command, str) and command.startswith(("/opt/claude-desk/", "bash /opt/claude-desk/")):
        item["command"] = command.replace("/opt/claude-desk/", "/opt/ai-deck/", 1)

migrate_command(cur.get("statusLine"))
for entries in cur.get("hooks", {}).values():
    for entry in entries:
        for hook in entry.get("hooks", []):
            migrate_command(hook)
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

# Codex shares the installed document/workstation skills, with its own auth
# and session files retained in the existing home volume.
mkdir -p "$HOME/.agents/skills" "$HOME/.codex"
for skill in "$SKILLS_DIR"/*; do
    [[ -f "$skill/SKILL.md" ]] || continue
    name=$(basename "$skill")
    dest="$HOME/.agents/skills/$name"
    if [[ ! -e "$dest" || -L "$dest" ]]; then
        ln -sfn "$skill" "$dest"
    fi
done
cp /opt/ai-deck/work/CLAUDE.md /work/AGENTS.md

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
src = open("/opt/ai-deck/mimocode.jsonc").read()
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
# /work/in), and the desk API behind the header and the sessions sheet.
# Restarted by the loop if it ever dies; ttyd stays PID 1.
(
    while true; do
        python3 /opt/ai-deck/upload.py
        sleep 2
    done
) &

# Chat view: drives a second Claude Code over stream-json. Same deal — its own
# respawn loop, never PID 1. It spawns the agent on the first message, so an
# idle desk pays nothing for this beyond the python process.
(
    while true; do
        python3 /opt/ai-deck/chat.py
        sleep 2
    done
) &

# ── The desks ─────────────────────────────────────────────────────────────
# One ttyd per person, each with its own tmux session, because ttyd's
# --max-clients is per instance and a shared `main` would mean two people on
# one keyboard. DESK_USERS is the roster, `<basic auth user>:<port>`; nginx
# routes /ws by $remote_user to the same ports (nginx/nginx.conf keeps its
# own copy of this map — tests/test_desks.py fails if the two drift).
#
# -W        writable (ttyd >= 1.7 is read-only by default)
# -m 2      two browsers per desk: one person on a phone and a laptop. Not
#           more — the tmux session is shared, so every extra client is
#           another keyboard in the same pane. A backgrounded iOS tab keeps
#           its slot (the browser answers the ws ping without waking the
#           page), which is what -m 1 made fatal: the second device could
#           never get in and the page just said "reconnecting" forever.
# -P 30     websocket ping so the DSM reverse proxy never idles us out
# tmux new -A: attach if the session exists, create otherwise — a closed tab
#           is not a lost job
desk_session() {
    # tmux refuses '.' and ':' in a session name; the desk is named after the
    # person either way. upload.py derives the same name from the same
    # roster, so keep the two rules identical.
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]' | tr -c 'a-z0-9_-' '-'
}

run_desk() {
    local port="$1" session="$2"
    ttyd -W -p "$port" -m 2 -P 30 \
        -t disableLeaveAlert=true \
        tmux new-session -A -s "$session"
}

IFS=',' read -ra DESKS <<< "${DESK_USERS:-desk:7681}"
primary_port=""
primary_session=""
for entry in "${DESKS[@]}"; do
    user="${entry%%:*}"
    port="${entry##*:}"
    session="$(desk_session "$user")"
    if [[ -z "$primary_port" ]]; then
        primary_port="$port"
        primary_session="$session"
        continue
    fi
    echo "desk: $user -> tmux '$session' on :$port" >&2
    (
        while true; do
            run_desk "$port" "$session"
            sleep 2
        done
    ) &
done

# The first desk on the roster is PID 1: if it dies the container restarts,
# which is the behaviour this stack had when there was only one.
echo "desk: primary -> tmux '$primary_session' on :$primary_port" >&2
exec ttyd -W -p "$primary_port" -m 2 -P 30 \
    -t disableLeaveAlert=true \
    tmux new-session -A -s "$primary_session"
