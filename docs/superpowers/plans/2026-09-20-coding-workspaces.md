# Coding workspaces implementation plan

**Goal:** Use AI Deck to clone GitHub repositories, work on persistent branches, test, commit/push, and request deployments without uploading source folders.

**Approved architecture:** Option 2, approved by the user on 2026-09-20: a coding worker separate from the document desk, persistent repository/worktree storage, and a deployment runner with separately provisioned production credentials. The initial deploy adapter supports this NAS management repository. Existing document and terminal workflows remain available.

**Tech stack:** Python standard library, Git/GitHub CLI, existing Claude/Codex adapters, vanilla JavaScript, Docker Compose/nginx. No additional database or frontend framework.

## Global constraints

- GitHub HTTPS URLs only, no embedded credentials or arbitrary clone protocols from API inputs. No shell interpolation of request values.
- Each task has its own branch/worktree and authenticated-owner metadata. Agent identity includes user, provider, workspace; session/history/resume must match its working directory.
- Coding worker has no NAS admin key, age key, deployment environment, Docker socket, or document /work mount. It has its own home and workspace volume. User isolation within this initial trusted-household coding worker is logical, not an OS security boundary.
- Credentials are provisioned separately, never in repository files, URLs, API responses, logs or model prompts. Private GitHub access uses gh auth in the worker or an externally supplied token.
- Deployment accepts a configured profile ID and full commit SHA only. Runner verifies the SHA against the configured remote deployment branch. Arbitrary commands/URLs/paths from requests are forbidden.
- Runner stores durable job status/logs; serializes deployment, and must report failure rather than infer success. Health verification belongs to the configured deployment profile. No privileged worker mount.
- NAS deployment uses the repository's tar/SSH deployment flow; no rsync. Existing SOPS/age secrets stay on the runner host. No new vault keys invented.
- Unit/integration tests use local temporary Git repositories and fake model/deploy processes, never paid model turns or production writes.

## Task 1: Persistent Git workspaces

Files: `ai-deck/workspaces.py`, `ai-deck/tests/test_workspaces.py`.

Interface: `WorkspaceStore(root).list(owner)`, `.create(owner, url, branch='')`, `.get(owner, id)`, `.status(owner, id)`. Returned metadata: `id`, `owner`, `url`, `branch`, `path`, `created`. `WorkspaceError` has public `message`/`status`. `.create` clones repo once into an owner-scoped cache and adds a fresh `desk/<id>` branch/worktree at requested remote branch (default remote HEAD). IDs are random 32-character lowercase hex. Atomic metadata persists restart; list never trusts user-supplied paths. Status reports `head`, `branch`, porcelain changes, bounded diff. Git credential helpers work normally; no credential persistence in URLs. External API validates GitHub URLs; tests may inject a trusted URL resolver to local bare repos. Subprocesses have timeouts and safe errors, partial clone/worktree cleanup, per-store thread lock. Workspace root is outside document `/work`.

- [x] Test real clone, branch/worktree independence, persistent list/reopen, dirty changes, default branch, invalid paths/URLs, missing repo, cross-owner access, concurrent creation, redacted failures.
- [x] Implement minimal store with bounded Git commands and validate tests.

## Task 2: Workspace-aware coding chat and UI

Files: `chat.py`, new `workspace_api.py`, `ui/workspaces.js`, `ui/workspaces.css`, `ui/index.html`, `ui/app.js`, relevant tests.

Coding routes use `/code/chat/*` at nginx, rewritten to `/chat/*` in worker. Workspace API `/code/projects` lists/creates, `/code/projects/status?workspace=<id>` inspects; worker handler receives `/projects*`. All receive nginx-owned `X-Desk-User`. Chat adds `workspace=<id>` query and uses store authorization before creating agent. `/chat/sessions` lists only that workspace's transcripts; resume validates existence in current workspace for both providers. Browser project choice and composer drafts are scoped by workspace/provider. New project form asks GitHub URL and optional base branch; selecting opens Chat. Diff/status panel exposes path/branch/state and offers prefill commands for test/commit/push, never auto-sends. HTTP failure remains visible. Document mode remains default, terminal in document mode unchanged; coding mode can open a separately routed worker terminal for gh/Codex login.

- [x] Write failing ownership/session-isolation/resume tests.
- [x] Implement APIs and chat identity/cwd/history integration.
- [x] Add accessible project controls and preserve streaming/reload/draft/provider semantics.
- [x] Verify HTTP and browser flows with fake model and local Git fixture.

## Task 3: Separate deployment runner

Files: `ai-deck/deploy_runner.py`, `ai-deck/tests/test_deploy_runner.py`, `ai-deck/deploy-profiles.example.json`, `ai-deck/run-nas-deploy.sh`.

Runner runs on a trusted workstation/VM with its own credentials, listens on configurable loopback host/port by default. `/deploy/profiles` returns sanitized configured profiles, `/deploy/jobs` GET lists owner jobs / POST accepts `{profile, sha}`, `/deploy/jobs/<id>` returns status and bounded sanitized log. Authentication is a bearer token read from an environment or file; nginx proxy can be configured externally, never expose unauthenticated. Profile fields: id, repository (GitHub HTTPS), branch, checkout root under runner-owned data, command argv, health command argv, allowed users. Repositories clone/fetch independently of worker storage. Before executing, full SHA must equal configured remote branch tip. Commands run in clean detached checkout of that SHA, serialized, with explicit runner environment; branch tip mismatch fails. Logs exclude inherited secret values; stderr is never exposed unredacted. Process groups/timeouts, job persistence on restart with interrupted jobs marked failed. No production commands run during implementation. Supplied NAS adapter uses deployed checkout's `scripts/deploy.sh` and externally configured secrets provisioning, documents trust in main and how to bootstrap credentials. Settings are read-only operator config, not editable by workspace agent.

- [x] Test auth, owner isolation, strict request validation, immutable revision selection, queue serialization, failure/timeout/restart, secret redaction and health failure using local Git fixture.
- [x] Implement runner and executable NAS profile adapter.
- [x] Document host runner setup and network proxy wiring; UI shows configured/unavailable state and never pretends push means deployment.

## Task 4: Packaging and verification

Files: worker Dockerfile/entrypoint, Compose coding profile, nginx routing, README and stack memory.

- [x] Worker image has Git, gh, Node/Python tooling and existing agent adapters; own persistent home/workspaces, non-root; no production credentials.
- [x] nginx optional routes fail cleanly when coding profile is off; enable with documented Compose invocation without changing existing deployment defaults unexpectedly.
- [x] Run stack/repository relevant tests, JS/shell syntax, Compose render/build and browser checks; independently review changes and fix substantive findings.
- [x] Update stack README and both stack memory files with actual validation/commit/deploy status. Keep unrelated files untouched.

## Progress

- Design accepted; repository inspected. Implementation in `.worktrees/ai-deck-coding` on `feat/ai-deck-coding`.

## 2026-09-23 delivery checkpoint
Implementation, independent review and local verification complete. Mac runner/tunnel installed and live NAS-to-Mac TLS profiles check passed. Git delivery and NAS application rollout recorded in stack notes when complete.
