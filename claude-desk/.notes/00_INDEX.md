# claude-desk — Index

**Port:** 5072 (nginx, LAN) / 15072 (DSM reverse proxy, HTTPS)
**Status:** deployed 2026-09-15, all containers up and verified on the NAS; waiting on the DSM RP WebSocket header before the phone can connect

---

## What it is

Claude Code reached from a phone browser, for generating pptx/docx/xlsx — not for coding. Design decisions were grilled in one session (2026-09-15); the outcome is the table in root `CLAUDE.md` and `README.md` here.

## Architecture

- `claude-desk` container: Debian bookworm-slim + Node 22 + `@anthropic-ai/claude-code@ARG CLAUDE_VERSION` + LibreOffice `*-nogui` + skills from `anthropics/skills@ARG SKILLS_REF`. PID 1 = `ttyd -W -m 1 -P 30 tmux new -A -s main`. uid 1000. `expose: 7681` only.
- `claude-desk-nginx`: `5072:80`, basic auth everywhere, serves `ui/`, proxies `/ws` + `/token` to ttyd, `/upload/` to upload.py (7682, `client_max_body_size 300m`), `autoindex_format json` on `/files/in/` and `/files/out/` (share mounted ro; `/files/` root itself 404).
- `upload.py` in the desk: stdlib `ThreadingHTTPServer`, PUT → `/work/in/<name>` (.part + `os.replace`), DELETE; rejects `..`, slashes, dot-files, >200 chars. Respawned by a loop in entrypoint if it dies; ttyd stays PID 1.
- `ui/`: own page (xterm.js vendored) that speaks ttyd's ws protocol. Key bar for the keys iOS lacks. Files drawer over `/files/`. PWA.

## File map

| File | Role |
|---|---|
| `Dockerfile` | image; pins CLAUDE_VERSION / SKILLS_REF / TTYD_VERSION(+sha256); build-time asserts soffice/claude/pptxgenjs/python libs |
| `entrypoint.sh` | mkdir in/out, symlink skills into home volume, copy `work/CLAUDE.md`, merge `claude-settings.json` hooks into `~/.claude/settings.json`, append prompt to `~/.bashrc`, exec ttyd |
| `upload.py` | PUT/DELETE receiver for the drawer's in/ tab (see architecture) |
| `claude-settings.json` | Claude Code settings template: `PreToolUse Bash → rtk hook claude` (rtk binary pinned in Dockerfile `RTK_VERSION`/`RTK_SHA256`) |
| `tmux.conf` | `escape-time 10`, `status off`, `mouse off`, login shell in /work |
| `profile.sh` | `/etc/profile.d`: alias `claude` → `--dangerously-skip-permissions`, `r` = `--continue`, banner |
| `docker-compose.yml` | two built services; `claude_desk_home` volume; `${CLAUDE_WORK_DIR}` bind (desk `/work`, nginx `/files` ro); `mem_limit: 2g`; watchtower off on both |
| `nginx/nginx.conf` | see architecture; `.htpasswd` gitignored |
| `nginx/Dockerfile` | `nginx:alpine` + `COPY ui/` — dir binds from the project dir are ACL-blocked for the worker uid |
| `.dockerignore` | keeps `.env`/`.htpasswd`/notes out of both build contexts |
| `secrets.manifest.yaml` | `CLAUDE_CODE_OAUTH_TOKEN`, `DASHBOARD_BASIC_AUTH_*`, literal `CLAUDE_WORK_DIR` |
| `ui/index.html` `style.css` `app.js` | the page; `?demo=1&mobile=1[&drawer=in|out][&theme=dark|light]` = design preview with no server |
| `ui/vendor/` | xterm 5.3.0, fit 0.8.0, web-links 0.9.0 (unpkg), `LICENSE.ttyd-wrapper` |
| `ui/fonts/` | Inter 4.1 Regular/SemiBold, JetBrains Mono 2.304 Regular/Bold (woff2) |
| `work/CLAUDE.md` | rules Claude sees inside `/work` (in/ read-only, out/ naming, render-and-look for decks) |

## .env

| Var | Source |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` | `stacks.claude_desk.oauth_token` — **placeholder `REPLACE_ME_run_claude_setup-token` until the user runs `claude setup-token`** |
| `DASHBOARD_BASIC_AUTH_USER` / `_PASSWORD` | `stacks.claude_desk.dashboard.*` (user `desk`, 28-char random) → `nginx/.htpasswd` |
| `CLAUDE_WORK_DIR` | literal `/volume2/claude-work` |

## Gotchas

- **Do not `compose up` before the DSM shared folder `claude-work` exists** — docker creates a plain root dir at the bind path and DSM then refuses to create a share of that name.
- Claude Code refuses `--dangerously-skip-permissions` as root → `user: 1000:100` + `useradd -u 1000 -g 100` in the image.
- **Synology share ACL, not mode bits, decides access.** `claude-work` came as `drwxrwxrwx+` with ACL entries only for `group:administrators` and one user → uid 1000 *and* uid 1026 (share owner, admin via supplementary gid 101 over SSH) both got `Permission denied` inside a container (`mkdir: cannot create directory '/work'` — looks like a missing mount, is an ACL traverse denial). Fixed once with `synoacltool -add /volume2/claude-work group:users:allow:rwxpdDaARWc--:fd--` (sudo password needed; `sudo -n` only covers docker) and the container runs with gid 100. Re-do the ACL if the share is ever recreated.
- **Never bind-mount a directory from `/volume2/docker/<stack>` into a non-root process.** The project tree carries the `docker` share's ACL; uid 1000 got `Permission denied` on `./work`, and nginx's worker served 403 for the whole `./ui` bind. File binds are fine (read by root before privilege drop). Bake dirs into the image instead.
- **`tar | ssh` upload lands every file as 0700.** Anything COPYed into an image and read by a non-root uid needs `COPY --chmod=0644` (tmux.conf was silently ignored → status bar on, escape-time 500) or a `RUN chmod -R a+rX` (nginx html dir served 403). Bind-mounted single files are read as root, which is why other stacks never hit this.
- **DSM Reverse Proxy: "WebSocket" lives under the rule's *Custom Header* tab (Create → WebSocket)**, not the General tab. Without it the generated block has no `Upgrade`/`Connection` headers and `/ws` returns a DSM 404 page while `/` and `/token` work. Check with `sudo grep -A30 'listen 15072' /etc/nginx/sites-enabled/server.ReverseProxy.conf` — look for `proxy_set_header Upgrade`. The block also has `proxy_read_timeout 60`; ttyd's `-P 30` ping keeps the socket alive through it.
- **Theme lives in two places that must agree**: CSS `[data-theme="dark"|"light"]` blocks in `style.css` and the `THEMES` table in `app.js`. xterm paints from its own palette, so a CSS-only change leaves the terminal on the old colours. After swapping it, `term.refresh(0, term.rows - 1)` is required — a bare `term.options.theme = ...` only affects rows written afterwards (verified: without it, rows drawn under light stay dark-on-dark).
- Light mode inverts the ANSI "bright" end: `brightWhite` is the **darkest** colour there, because programs use bright for emphasis and `#fff` on white is invisible.
- **Headless Chrome reports `prefers-color-scheme: light`**, so screenshots need an explicit `?theme=dark` now that the page follows the system — otherwise the "dark" screenshots come out light.
- `PS1` cannot be set from `/etc/profile.d` — Debian's skel `~/.bashrc` overrides it later; entrypoint appends the prompt to `~/.bashrc` once.
- `claude` in the shell is an alias; `command claude` for the bare binary.
- ttyd ≥ 1.7 is read-only without `-W`.
- The ws URL in `app.js` is built relative to the page path, so the page works under a subpath too.
- Headless Chrome on macOS clamps window width to ~500 px — a 390 px screenshot is a crop, not a layout bug. Verify phone layout on the phone.
- `?demo=1` short-circuits `sendInput` to echo locally; never ship a page with that default on.
- Test suite: `tests/test_manifest_schema.py` needs `jsonschema` in the venv (missing on this Mac) — `pytest --ignore` it; 39 others pass.

## Verification status

- [x] `make check` exit 0, `make secrets` wrote `.env`, `.htpasswd` generated
- [x] `docker compose config` valid; `nginx -t` only fails on upstream DNS outside compose
- [x] UI mockup screenshots: `screenshots/claude-desk-{phone,files,desktop}.png`
- [x] image builds on NAS (after moving `ENV NODE_PATH` above the build assert)
- [x] shared folder `claude-work` on volume2 + ACL for `group:users`; token in vault
- [x] DSM RP 15072 reaches nginx (401 → 200 with auth, `/files/` JSON) — **websocket 404 until the Custom Header → WebSocket entry is added**
- [x] `claude -p` inside the container authenticates with the vault token (`DESK_OK`)
- [x] ttyd session via raw ws client on the NAS spawns tmux `main`, banner + shell in `/work`
- [x] upload path on the NAS: 3 MB PUT → byte-identical in `in/`, traversal name → 400, `/files/in/` JSON lists it, GET returns it, DELETE → 204
- [ ] end-to-end from phone: key bar, `claude` interactive, drawer upload/download

## Change log

- **2026-09-15** — dark/light theme toggle (header sun/moon, follows the system until first tap)
- **2026-09-15** — drawer gets in/ tab with upload (+delete) and ⬇ on out/; `upload.py` + `/upload/` + `/files/{in,out}/`
- **2026-09-15** — rtk 0.49.0 added (binary + settings merge in entrypoint); Headroom deliberately not added (2 GB ML install, would be a proxy sidecar — see daily_log)
- **2026-09-15** — stack created (Dockerfile, compose, nginx, UI, docs, vault keys, deploy.sh `ALL_STACKS`, homepage tile, root README/CLAUDE.md rows)
