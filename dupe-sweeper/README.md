# dupe-sweeper

Dashboard to find duplicate video files on the NAS grouped by media code, compare
their details, and recycle the ones you don't want — from the browser.
Supersedes the standalone `avdedup.py` CLI (its code-extraction logic lives in
`dedup.py`).

- **Port:** 5069 (nginx → dupe-sweeper:8000)
- **Auth:** nginx basic auth (`nginx/.htpasswd`, generated from vault)
- **Stack:** FastAPI + SQLite + static dashboard (vanilla JS, light/dark)

## How it works

1. Pick a scan root (a mounted media path) + optional subfolder → **Scan**.
2. Backend `os.walk`s in a background thread, extracts a media code per filename,
   groups files sharing a code (≥2 = a duplicate group). Synology junk
   (`@eaDir`, `#recycle`) and the recycle folder itself are skipped.
3. Dashboard shows each group: files largest-first, size / guessed-resolution /
   date / full path, with a **multi-part** badge for `cd1/cd2/.A/.B` sets
   (likely one title in parts — keep all).
4. Toggle **keep** per file (largest pre-kept). Un-kept files → **Recycle**.

Code matching handles: `SSNI-618 == SSNI-00618` (zero-pad), `FC2-PPV-…`,
`HEYZO` (incl. `heyzo_hd_…`), caribbean/1pondo date form (`010112-123`), and
standard `LETTERS-DIGITS`. Codec/quality tokens (`x264`, `1080p`, …) are
blocklisted so they aren't mistaken for a code.

## Delete is a trust boundary

`/api/delete` receives paths. Before moving anything, `recycle.py` `realpath`s
every target and asserts it's under a configured `SCAN_ROOTS` entry — one
violation rejects the whole request (no partial deletes). Deletion is a **move
to recycle**, not `os.remove`:

- `TRASH_DIR` is on the **same volume** as the media
  (`/media/<library>/.dupe-sweeper-trash`), so the move is an atomic `os.rename`, not a
  multi-GB cross-volume copy.
- Emptying the recycle folder is manual (File Station).

Runs as **root** on purpose: it must delete media owned by assorted Synology
users, and root sidesteps the dynamic-UID ownership trap. Safe because the
container is LAN-only behind basic auth and deletes are realpath-gated.

## Config (env)

| Var | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `/data` | SQLite DB location (named volume) |
| `SCAN_ROOTS` | `/media/<library>` | Comma-separated roots the container may scan/delete under |
| `TRASH_DIR` | `/media/<library>/.dupe-sweeper-trash` | Recycle folder (must be on same volume as media) |

## Setup

1. Mount your media path read-write in `docker-compose.yml` (default:
   `/volume1/private_media/<library>:/media/<library>`).
2. Add dashboard creds to the vault, then generate `.htpasswd`:
   ```bash
   make edit-vault          # add stacks.dupe_sweeper.dashboard.{username,password}
   htpasswd -cB nginx/.htpasswd <username>   # gitignored; enter the vault password
   make secrets             # renders dupe-sweeper/.env
   ./scripts/deploy.sh
   ```
3. In DSM → Container Manager → Project → Create, point at
   `/volume2/docker/dupe-sweeper`.

## Tests

`pytest dupe-sweeper/tests/` — code-extraction cases + the delete path-guard
(outside-root and traversal must be rejected; batch is all-or-nothing).

## Scope cuts (add later if needed)

- No `ffprobe` — resolution is guessed from the filename.
- No perceptual/content hashing (won't catch re-encodes at different bitrate).
- No auto-purge of the recycle folder.
