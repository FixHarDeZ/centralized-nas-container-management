# claude-desk: chat is a second view driving its own agent, not a wrapper around the terminal

**2026-09-16**

## Context

The desk is a terminal in a browser: ttyd → tmux → bash → `claude`. It works, and
a session's worth of fixes (OSC 52 copy out of a TUI, a status line that sizes
itself, an on-screen key bar for the keys iOS lacks) is invested in it.

A terminal wraps hard at `COLUMNS`. On a phone that is about 40 columns of Thai,
and a long answer is painful to read — which is the one complaint that survives
every other fix. Bubbles reflow. A chat view was asked for after seeing one over
Codex.

## Decision

The chat view is a **second view in the same page**, driving a **second Claude
Code** through `--input-format stream-json --output-format stream-json`
(`claude-desk/chat.py`). The terminal is untouched.

Rejected: rendering bubbles from what the terminal already receives. The page
would have to reconstruct message boundaries, tool calls and turn ends by
parsing ANSI out of xterm.js — a screen, not an interface. It breaks whenever
Claude Code changes how it draws, and it puts the working half of the desk at
risk of a cosmetic upstream change. The stream-json protocol is documented,
versioned and was probed against 2.1.273 before any of this was written:
multi-turn input on one process, `content_block_delta` for token-by-token text,
`tool_use`/`tool_result` for pills, a control request for interrupt.

Transport is server-sent events plus two POSTs, not a websocket: one direction
streams, the other is request-shaped, and SSE needs no dependency beyond the
standard library — which is what the rest of this stack is built from.

## Consequences

**Two agents can work in `/work` at once.** This reverses "one agent at a time",
which is why `mimo` never got a stack of its own. It is *not* prevented, because
the only signal available is `tmux` `pane_current_command`, and that reports
`claude` whenever a session is merely *open* — refusing on it would block the
normal case and the feature would appear broken. The chat header says when the
terminal also has an agent up, and the judgement is left to the person holding
the phone.

**The chat covers `claude` only.** `mimo` (MiMoCode) and `ask` do not speak this
protocol, so the terminal remains the only way to reach them, a shell, or
anything else on the desk. The chat view is an addition, never a replacement.

**A second node process inside `mem_limit: 2g`.** The agent is spawned on the
first message rather than at boot, so an idle desk pays only for a python
process, and `POST /chat/new` disposes of it.

**The chat child carries `--dangerously-skip-permissions` itself.** In the
terminal that flag comes from a shell alias; a child spawned straight from the
binary has to pass it. Same bargain as the terminal: a tap per tool call makes
the desk unusable from a phone, and the container is the cage.

**No transcript on the server.** A reload starts a fresh view of the same live
session rather than replaying it. `GET /chat/state` returns only whether a turn
is in flight, so a page that comes back mid-turn shows the stop button. Keeping
a transcript means `chat.py` owning a model of what the page renders; that is
worth doing once the event→bubble mapping has settled, not before.
