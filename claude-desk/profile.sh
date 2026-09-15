# Shell defaults for the desk session (sourced by the login shell tmux opens).
#
# `claude` here always skips the permission prompts: every tool call would
# otherwise need a tap on the phone, and the container is the sandbox — no
# docker socket, no other volumes, only /work is writable from outside.
alias claude='command claude --dangerously-skip-permissions'
alias c='claude'
alias r='claude --continue'

# The office skills may leave soffice worker processes around after a crash;
# a quick way to see and clear them from the phone.
alias soffice-kill='pkill -f soffice.bin || true'

# MiMoCode, the second agent (see mimocode.jsonc). Permissions are skipped
# for the same reason `claude` skips them: every tool call would otherwise
# need a tap on the phone, and the container is the sandbox.
# CLAUDE_CODE_OAUTH_TOKEN is cleared because MiMoCode's first-run auth
# offers to import Claude Code credentials — it has its own key and no
# business with the subscription one. Hygiene, not a wall: bash is allowed
# and ttyd runs as this same uid.
alias mimo='CLAUDE_CODE_OAUTH_TOKEN= command mimo --dangerously-skip-permissions'
alias m='mimo'

if [ -z "${CLAUDE_DESK_BANNER_SHOWN:-}" ]; then
    export CLAUDE_DESK_BANNER_SHOWN=1
    printf '\e[38;5;214m▌\e[0m claude-desk — %s\n' "$(command claude --version 2>/dev/null || echo 'claude ?')"
    printf '\e[38;5;245m  in/  ← drop source files here (DS File)\n  out/ → finished pptx/docx/xlsx land here\n  claude | r = resume | m = mimo agent\n  ask <question> = one answer\e[0m\n\n'
fi
