# claude-desk

Claude Code as a document desk, driven from a phone browser. Not a place to
write code — a place to say "make me an 8-slide deck from `in/sales.xlsx`"
and download the `.pptx` a few minutes later.

![phone](../screenshots/claude-desk-phone.png)
![light theme](../screenshots/claude-desk-light.png)
![files drawer](../screenshots/claude-desk-files.png)
![upload](../screenshots/claude-desk-upload.png)

## What runs

```
phone ──HTTPS :15072 (DSM RP)──▶ claude-desk-nginx :5072
                                   ├─ /            static UI  (ui/)
                                   ├─ /ws, /token  ──▶ claude-desk :7681 (ttyd → tmux → bash → claude)
                                   ├─ /files/in/, /files/out/   autoindex JSON + the files (read-only)
                                   └─ /upload/<name>  PUT/DELETE ──▶ claude-desk :7682 (upload.py → /work/in)
```

- **`upload.py`** — stdlib HTTP server in the desk container (port 7682, only nginx can reach it): `PUT /upload/<name>` streams the body into `/work/in/<name>` via a `.part` temp file + atomic rename, `DELETE` removes. Flat names only, no `..`/slashes/dot-files. Size cap is nginx's `client_max_body_size 300m` on `/upload/` (DSM's reverse proxy has its own cap too).
- **`claude-desk`** — Debian + Node 22 + `@anthropic-ai/claude-code` (pinned `ARG CLAUDE_VERSION`), LibreOffice `*-nogui`, poppler, qpdf, Thai fonts, the Python and npm packages the official office skills need. PID 1 is `ttyd -W -m 1 -P 30 tmux new -A -s main`. Runs as uid 1000 (Claude Code refuses `--dangerously-skip-permissions` as root). Never published on the host.
- **`claude-desk-nginx`** — `nginx:alpine` with `ui/` baked in (`nginx/Dockerfile`): basic auth on every path (`nginx/.htpasswd` from the vault), proxies only the websocket and token endpoints to ttyd, and lists `out/` as JSON. `ui/` cannot be bind-mounted: directories under `/volume2/docker` carry the DSM share ACL, which the nginx worker (uid 101) cannot traverse → 403 on every file. Single-file binds (`nginx.conf`, `.htpasswd`) are read by the root master process and work.
- **`ui/`** — our own page instead of ttyd's: xterm.js 5.3 (vendored, no CDN), Inter + JetBrains Mono self-hosted, a key bar with `Esc ⇧Tab Tab Ctrl ↑↓←→ ↵NL` and `Paste / ^C A− A+ ⌨`, a right-hand drawer with `in/` (Add files → PUT, 🗑 delete) and `out/` (tap to open, ⬇ to save) tabs, a dark/light theme toggle, PWA manifest for Add-to-Home-Screen. Speaks ttyd's websocket protocol directly (touch scrolling and the iOS keyboard handling adapted from `pawprint0706/ttyd-wrapper`, MIT).

## Volumes

| Mount | What | Why |
|---|---|---|
| `claude_desk_home` → `/home/claude` | named volume | `claude --resume` across restarts; `~/.claude.json` lives outside `~/.claude`, hence the whole home |
| `/volume2/claude-work` → `/work` | DSM shared folder | `in/` for source files (drop via DS File / Synology Drive), `out/` for deliverables. `work/CLAUDE.md` is baked into the image and copied to `/work` on every start (same ACL reason — a `./work` bind is unreadable to uid 1000) |
| `/volume2/claude-work` → nginx `/files` (ro) | same share | download side; nginx only exposes `/files/out/` (binding `out/` directly races the entrypoint that creates it) |

**rtk** (the same Bash-output trimmer the workstation runs) is in the image, pinned like ttyd, and `entrypoint.sh` merges `claude-settings.json` (the `PreToolUse Bash → rtk hook claude` hook) into the home volume's `~/.claude/settings.json` on every start — additive, keyed by command string, so settings changed from inside the desk survive. `rtk gain` in the shell shows what it saved.

Skills live in the image at `/opt/skills` (clone of `anthropics/skills`, pinned `ARG SKILLS_REF`); `entrypoint.sh` re-links `pptx docx xlsx pdf` into `~/.claude/skills` on every start so a ref bump reaches the volume.

## Secrets

`secrets.manifest.yaml` → `.env`:

- `stacks.claude_desk.oauth_token` → `CLAUDE_CODE_OAUTH_TOKEN` — from `claude setup-token` on a machine with a browser (subscription token, ~1 year). No API key: a deck burns tokens.
- `stacks.claude_desk.dashboard.basic_auth_user` / `basic_auth_password` → `nginx/.htpasswd` (gitignored; regenerate on a fresh clone):

```bash
cd claude-desk
U=$(awk -F= '/^DASHBOARD_BASIC_AUTH_USER=/{print $2}' .env)
P=$(awk -F= '{if(/^DASHBOARD_BASIC_AUTH_PASSWORD=/){sub(/^[^=]*=/,"");print}}' .env)
printf '%s:%s\n' "$U" "$(openssl passwd -apr1 "$P")" > nginx/.htpasswd
chmod 644 nginx/.htpasswd
```

Literal: `CLAUDE_WORK_DIR=/volume2/claude-work`.

## First-time setup (in this order)

1. DSM → Control Panel → Shared Folder → create **`claude-work`** on volume2, then in Permissions give the **`users` group Read/Write** — a fresh share's ACL only lists `administrators`, and mode bits (777) are ignored; without it the container gets `Permission denied` on `/work` even as the share owner (SSD — keep the pptx/soffice churn off the big HDD) (`synoshare --add` refuses; and if compose runs first, docker creates a plain root-owned dir with that name and the share can never be created).
2. On the Mac: `claude setup-token` → `sops set secrets/vault.sops.yaml '["stacks"]["claude_desk"]["oauth_token"]' '"<token>"'` → `make sync-test-vault && make secrets`.
3. DSM → Login Portal → Reverse Proxy: `https://<domain>:15072` → `http://localhost:5072`, WebSocket enabled (the RP must pass `Upgrade`; DSM's "Enable WebSocket" checkbox on the rule).
4. `./scripts/deploy.sh -y -s claude-desk` — first build pulls LibreOffice, takes several minutes.
5. Open `https://<domain>:15072` on the phone, sign in, tap ⋯ → Add to Home Screen.

## Theme

The sun/moon button in the header switches dark ↔ light and remembers the
choice in `localStorage`. Until it is tapped once the page follows the phone's
appearance setting and keeps following it, so a nightly auto-switch works
without doing anything. Both palettes live in `style.css` (`[data-theme]`
blocks) and `app.js` (`THEMES`, the terminal's own ANSI set — xterm paints
from its palette, not from CSS, so the two must be kept in step). `?theme=light`
forces one for a screenshot.

Colours emitted as 256-palette codes (the shell banner and prompt from
`profile.sh`, and some Claude Code output) are not part of either palette and
look the same in both themes.

## Using it

- Tap the folder icon → **in/** → **Add files** to upload sources from the phone (or drop them into `claude-work/in/` from DS File — same folder). Type `claude` (alias for `claude --dangerously-skip-permissions`), describe the document. `r` resumes the last session.
- Finished files appear under **out/** in the same drawer: tap to open (iOS previews pptx/xlsx inline), ⬇ to save to Files.
- Close the tab any time — tmux keeps the session; reopening attaches to the same screen.
- `?demo=1&mobile=1` on the URL shows the UI with a canned session and no server, for design work.

## Limits accepted

- Basic auth is the only gate in front of a shell with permission prompts off. The container is the sandbox: no docker socket, no other mounts, `mem_limit: 2g`. Keep the password long; `-m 1` refuses a second concurrent browser.
- One session, one person. Not multi-user.
- `cpus:` does nothing on DSM; a heavy soffice render can pin a few cores for a minute.
