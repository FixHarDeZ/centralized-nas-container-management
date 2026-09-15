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

# The mimo-brained harness. Short alias because it is typed on a phone.
alias m='mimo-code'

if [ -z "${CLAUDE_DESK_BANNER_SHOWN:-}" ]; then
    export CLAUDE_DESK_BANNER_SHOWN=1
    printf '\e[38;5;214m▌\e[0m claude-desk — %s\n' "$(command claude --version 2>/dev/null || echo 'claude ?')"
    printf '\e[38;5;245m  in/  ← drop source files here (DS File)\n  out/ → finished pptx/docx/xlsx land here\n  type: claude  |  r = resume last\n  m = mimo-code (agent on mimo, slow+free)  |  mimo <ask> = one answer\e[0m\n\n'
fi
