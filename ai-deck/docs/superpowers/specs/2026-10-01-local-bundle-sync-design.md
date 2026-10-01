# Local repository sync via git bundle — design

Status: approved direction (2026-10-01), not implemented.

## Problem

Some repositories live behind a VPN. The Mac can clone them; the coding worker
on the NAS cannot reach their Git host. Today coding mode only creates tasks
from a GitHub URL (`WorkspaceStore.create()` → `git clone --bare <url>`), so
these repositories cannot be worked on in ai-deck at all.

## Goal

Move a repository Mac → ai-deck → Mac with full Git history, using files the
browser or a small CLI can carry. The Mac stays the only machine that talks to
the private Git host.

Non-goals: NAS reaching the Mac as a Git remote; zip/tar transfer; pushing from
the worker to any remote for these projects.

## Transport: `git bundle`

A bundle is a packfile plus refs. `git clone`/`git fetch` read it like a remote.
Incremental bundles (`A..B`) carry only new commits, so round trips stay small.

## Concepts

- **Local project** — a workspace cache created from a bundle instead of a URL.
  Identity: `local:<slug>` (slug = user-chosen name, `[a-z0-9._-]{1,64}`).
  Cache path stays `_cache_path(owner, "local:<slug>")`.
- **Import** — first bundle; creates the cache and a task (`desk/<id>`).
- **Update** — later bundle into an existing local project; fetched into the
  same cache. Refs land under `refs/remotes/origin/*` so existing base-branch,
  status and rebase logic keep working unchanged.
- **Export** — bundle of `<base>..desk/<id>` for one task, downloaded to the Mac.

## Worker changes (`workspaces.py`, `workspace_api.py`)

1. `WorkspaceStore.import_bundle(owner, slug, bundle_path, branch="")`
   - `git bundle verify` before anything else (reject → 400, nothing created).
   - Reject bundles whose refs are not `refs/heads/*` / `HEAD`.
   - New cache: `git init --bare`, then `fetch <bundle> +refs/heads/*:refs/remotes/origin/*`.
     Existing cache with same slug: same fetch (= Update), no `--prune`
     (an incremental bundle omits untouched branches).
   - Then reuse current flow: pick base branch, `worktree add -b desk/<id>`.
   - Record gets `"source": "bundle"`, `"url": "local:<slug>"`, and
     `"base_sha"` = commit the task started from (export range start).
   - Bundle file deleted after import (success or failure).
2. `WorkspaceStore.update_bundle(owner, workspace_id, bundle_path)` — fetch into
   the task's cache; does not touch the worktree. Agent/user rebases via chat.
   Prerequisite commits missing → 409 with git's message ("send a full bundle").
3. `WorkspaceStore.export_bundle(owner, workspace_id)` → path to
   `desk-<slug>-<id8>.bundle` containing `base_sha..desk/<id>`, branch ref
   named `desk/<id>`. No new commits → 409 "nothing to export". Uncommitted
   changes → 409 unless `?force=1` (export only includes commits; message says so).
4. Per-workspace `git config user.name/user.email` from optional import fields,
   so work commits do not carry the worker's global personal identity.
5. Push/Deploy controls hidden when `source == "bundle"` (no reachable remote).

API (owner from existing authenticated header, like other `/code/*` routes):

| Method | Path | Body / result |
|---|---|---|
| PUT | `/code/projects/bundle?slug=&branch=&name=&email=` | raw bundle stream → workspace record |
| PUT | `/code/projects/bundle?workspace=<id>` | raw bundle stream → update cache |
| GET | `/code/projects/export?workspace=<id>[&force=1]` | `application/octet-stream` bundle |

Upload streams to `.part` under `/workspaces/incoming/<owner>/` then `os.replace`,
same pattern as `upload.py`. nginx route `^~ /code/projects/bundle` with
`client_max_body_size 300m`, `proxy_request_buffering off`.

## Secret warning

After import, scan tree of the base commit (`git ls-tree -r --name-only`) for
credential-shaped names (`.env*`, `*.pem`, `id_*`, `*.p12`, `credentials*`,
`*secret*`). Return list in the response; UI shows it as a warning, does not
block (the user already chose to send the bundle).

## UI (`ui/`)

- Projects dialog: tab **GitHub | Local bundle**. Local: file picker, project
  name (slug; existing local projects in a dropdown = Update), base branch,
  optional commit name/email.
- Current task (bundle source): **Download changes** button → export URL;
  **Upload update** → update PUT. Push/Deploy buttons hidden.

## Mac CLI: `scripts/desk-sync`

Bash, depends only on `git` + `curl`. Config `~/.config/desk-sync/config`
(`DESK_URL`, basic-auth user; password from macOS Keychain via
`security find-generic-password`, never in the file or argv shown in `ps` —
pass through `curl --netrc-file` temp file `0600`, deleted on exit).

State per repo in `.git/desk-sync` (gitignored by location): `slug`,
`workspace`, `last_sent` (SHA of last uploaded tip).

```
desk-sync up [--slug S] [--branch B]   # first: full bundle (--all) → import
                                       # later: last_sent..HEAD → update
desk-sync down                         # GET export → git fetch into desk/<id>
                                       # prints: git log/diff vs current branch
desk-sync status                       # slug, workspace, last_sent, ahead/behind
```

`down` never merges or checks out; review and merge/rebase stay manual.
`up` refuses with a dirty tree warning only (bundles carry commits, not edits).

## Security notes

- Bundle = untrusted input to `git fetch`. Verify first; run with existing
  worker sandbox (uid 1000, no docker socket). Hooks in a bundle are not
  executed (bundles carry objects/refs, not `.git/hooks`).
- Coding worker accounts share a UID; household users can read imported code.
  Documented, unchanged.
- Credentials never committed: Keychain only on Mac; nothing new in vault.

## Tests

- `workspaces`: import full bundle → task on correct base; update with
  incremental bundle; incremental with missing prerequisite → 409; bad bundle →
  400 and no cache left; export contains only `base_sha..desk/<id>` and
  `git fetch` of it on a fresh clone reproduces the task tip; nothing-to-export
  409; dirty worktree 409/force; per-workspace identity applied; secret scan list.
- API/nginx: streaming upload, size limit, owner isolation (other owner's
  workspace → 404).
- Chromium harness: Local bundle tab; push/deploy hidden for bundle source.
- `desk-sync`: shell test against a local fake server (curl to `python -m http.server`-style stub) for up (full then incremental) and down.

## Rollout

Feature behind existing `coding` profile. Docs: README "Coding projects" +
`docs/CODING_WALKTHROUGH.md` section. Deploy via runner as usual.
