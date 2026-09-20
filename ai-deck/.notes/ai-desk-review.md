# AI Desk implementation review — 2026-09-18

Scope: image/build pins, Compose and nginx routing, startup and persistent home,
terminal/session API, upload/download paths, chat subprocesses and SSE replay,
browser UI, tests, skills and user documentation. Vendored libraries/skills were
checked at their integration boundaries, not exhaustively audited upstream.

## Implemented

| Area | Finding and change |
| --- | --- |
| Naming | AI Desk is the visible name in the UI, PWA, auth realm and Homepage. Existing directory, container, volume, URL and environment names are retained, so no data migration is needed. |
| Onboarding/UI | Light/dark workspace layout, agent selector, document task starters, direct upload entry and Codex sign-in/terminal buttons. Fixed hidden drawers casting a shadow over the page; browser zoom is enabled. |
| Codex | Pinned CLI 0.155.0; ChatGPT device authorization via Terminal. JSONL adapter supports turns, resume, tools, errors and Stop, including uncooperative child processes. Completed messages render as bubbles; Codex is not falsely advertised as streaming token deltas. |
| Session ownership | Live chat agents and replay buffers are keyed by nginx-authenticated user and provider. Another user's New/Stop no longer drives the same child. Native saved histories remain shared and are filtered by provider/workspace. |
| Skills | Same office/workstation skill files are discoverable by Codex through `~/.agents/skills`; work instructions are also generated as `AGENTS.md`. No account credentials are copied. |
| Upload integrity | Unique hidden temporary files prevent same-name upload collisions and `.part` symlink writes. Premature EOF preserves the old file. Finished uploads remain readable by the nginx uid. |
| Downloads | nginx serves only `/files/in/` and `/files/out/`, with symlink traversal disabled; other workspace paths return 404. |
| Request validation | Chat rejects non-object JSON, invalid message types and oversized bodies rather than crashing or accepting truncated messages. |
| Startup permissions | Runtime smoke testing found BuildKit-created `/opt/claude-desk` lacked directory execute bits after file `COPY --chmod=0644`. Explicit 0755 on the runtime directories restores access for uid 1000. |
| Maintenance | Codex participates in `make desk-latest`; Compose explicitly targets the NAS's amd64 architecture because ttyd/rtk binaries are architecture-specific. Build smoke checks include `codex --version`. |

## Remaining improvements, in priority order

1. **Global job concurrency / resource accounting.** Separating chat ownership can
   create more agent processes than before. The 3 GB container limit includes
   terminals and LibreOffice. Add a shared admission queue and busy-agent view
   before increasing the user roster; per-user separation is not a memory quota.
2. **Service health/supervision.** Startup respawns upload/chat but does not expose
   a combined readiness check or bounded backoff. Add readiness and process health
   before treating a running ttyd container as proof that Chat/upload works.
3. **Account and history privacy.** Home, provider accounts, saved transcripts and
   `/work` intentionally remain shared. Strong privacy requires distinct homes,
   work directories and credential ownership, not just filtering the history UI.
   Users may deliberately resume the same saved conversation; avoid concurrent
   edits to that conversation or output file.
4. **Quota/notifications.** Claude's quota/finish files are account-wide. The UI
   hides Claude quota for Codex; it does not yet show Codex subscription limits or
   send provider-specific completion notifications. Codex token usage is available.
5. **History scale and restoration.** Native rollout scanning is sufficient for a
   small desk; add a bounded index/pagination for large archives. The selected
   active conversation is held in process memory, so after service restart choose
   the saved conversation from History. Skill and CLI protocol changes still need
   fixture updates when pins change.
6. **MiMo in Chat.** MiMo remains a terminal agent and `ask` helper. Add its own
   supported adapter if a unified three-provider Chat is wanted; do not parse its
   terminal screen or route Claude/Codex through a MiMo compatibility proxy.
7. **Dependency reproducibility.** CLI and office-skill versions are pinned, but
   Debian/Node/nginx image tags and several Python/npm document dependencies are
   floating. Lock/digest them in a dedicated maintenance change with update checks.

## Workstation skill migration

23 portable skills were copied from `~/.claude/skills` (including nested synced
office skills) to `~/.codex/skills`, retaining scripts, references and licenses.
Their entrypoints include Codex tool mapping and preserve session authorization.
48 other skills already resolve through `~/.agents/skills` and were left intact.
All 23 imports passed Codex's `quick_validate.py`.

Skipped: Claude-only `docs`, `chrome-browser`, `built-in-browser`, `computer-use`,
`import-memory`; MiMo's browser-runtime skill; and the imported `skill-creator`
because Codex already supplies its own. NotebookLM code was copied without its
browser profile, auth data or virtualenv; authenticate separately if using it.
The imported skills are discoverable by Codex; reopen the session if a client has cached its skill catalog.

## Validation boundaries

Python tests exercise existing Claude behavior plus a fake Codex subprocess using
the official JSONL event shapes, resume arguments, process cancellation, failures,
HTTP routing and upload integrity. Real Chrome tests cover mobile/desktop starter,
upload, login and terminal controls alongside existing streaming/reconnect tests.

ChatGPT account login and a paid/live Codex turn require the user's browser consent
and have not been performed by this implementation. No NAS deployment or volume
migration is part of the local verification.

Protocol/auth references:
- https://developers.openai.com/codex/noninteractive/
- https://developers.openai.com/codex/auth/

## Verification completed — 2026-09-19

- **124 tests passed, zero failures/errors/skips**, including real Chrome UI and streaming/reconnect tests.
- Native Mac/arm64 image build passed with Claude Code 2.1.276 and Codex 0.155.0.
- Credential-free, network-disabled container startup smoke passed: CLI binaries,
  Codex Chat state API, sessions API, skill discovery and generated AGENTS.md.
- nginx image build and `nginx -t` passed. Real HTTP probes returned 200 for
  `/files/in/probe.svg`, 404 for a workspace file outside in/out, and 403 for
  a symlink out of the download directories. Download prefixes use `^~` so the
  UI asset regex cannot intercept uploaded SVG/PNG/JS files.
- JavaScript/Python syntax, shell syntax, YAML parsing and `git diff --check` passed.
- Screenshots: `screenshots/ai-desk-desktop.png`, `screenshots/ai-desk-mobile.png`.
- **Not verified on NAS:** amd64 cross-build on this Mac crashed at the existing
  `claude --version` smoke step (Bun memory assertion under QEMU, before Codex).
  Native build with the same CLI versions passed. Build/run on the NAS's native
  amd64 host is still required before claiming production readiness.
- No deployment, real ChatGPT sign-in or live/paid Codex turn was performed.
