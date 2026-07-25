# dupe-sweeper — Duplicate Video Finder Dashboard

**Date:** 2026-07-21
**Status:** Approved, ready for implementation plan

## Purpose

Web dashboard to find duplicate video files on the NAS grouped by media code
(files with the same code but different names/sizes), compare their details
side by side, and decide per file which to keep and which to remove — all
from the browser. Deletion moves files to a recycle folder (reversible),
not permanent removal.

Supersedes the standalone `avdedup.py` CLI (its `extract_code`/`scan` logic
is reused as the backend core).

## Stack

New stack `dupe-sweeper/`, port **5069** (5068 taken by ink-reader). Mirrors the
`ink-reader`/`friendly-reminder` pattern: FastAPI + SQLite + static dashboard
behind nginx basic auth.

```
dupe-sweeper/
  main.py              FastAPI app + endpoints
  dedup.py             extract_code / scan core (ported from avdedup.py)
  db.py                SQLite: scan_jobs, files
  static/
    index.html         dashboard
    app.js             fetch + render + light/dark toggle
    style.css          CSS-variable theming
  nginx/
    nginx.conf         basic auth reverse proxy
    .htpasswd          generated from vault (gitignored)
  Dockerfile
  docker-compose.yml
  requirements.txt
  secrets.manifest.yaml
  .notes/{00_INDEX.md,daily_log.md}
```

## Data flow

1. User picks a scan root (from mounted roots) + optional subpath, clicks Scan.
2. Backend runs `os.walk` in a background task, extracts code per file,
   groups by code, persists files + job to SQLite.
3. Dashboard polls job status, then renders dupe groups (code with ≥2 files).
4. Per group: file cards showing size / guessed-resolution / mtime / full path,
   largest first, multipart badge (cd1/cd2/A.B) when detected.
5. User checks keep/delete per file, confirms, backend moves the delete set
   to the recycle folder.

## Components

### dedup.py
Ports from `avdedup.py`: `extract_code(name)`, `_strip0`, `res_guess`,
`human`, `BLOCKLIST`, `DEFAULT_EXTS`, and a `scan(root, exts)` walker.
**Additions:**
- Walk skips `@eaDir`, `#recycle`, and the trash dir (Synology + our own junk).
- No behavior change to code extraction (already validated against real names).

### db.py
SQLite at `/data/dupe-sweeper.db`.
- `scan_jobs(id, root, status, total_files, dup_groups, started_at, finished_at, error)`
- `files(id, job_id, path, name, size, mtime, code, part, res)`

No `decisions` table — the frontend holds the keep/delete selection and POSTs
the delete list. A re-scan invalidates any prior selection (paths move), so
persisting decisions has no value.

### main.py — endpoints
- `POST /api/scan {root, subpath?}` → starts background scan, returns job id.
  Validates `realpath(root+subpath)` is under an allowed scan root; else 400.
- `GET /api/scan/{id}` → job status + progress.
- `GET /api/groups/{id}?min=2` → dupe groups with file details.
- `POST /api/delete {paths:[...]}` → move each to recycle. **Trust boundary
  (see Security).** Returns per-path result + bytes freed.
- `GET /api/roots` → configured scan roots (from `SCAN_ROOTS` env).
- `GET /api/status` → healthcheck.

### Frontend
Single static page, vanilla JS (no build step — matches repo pattern).
- Root picker + subpath input + Scan button + progress bar.
- Group list: collapsible cards, largest file pre-checked as "keep".
- Detail table per group: size, res, date, path, multipart badge.
- Delete button per group + confirm modal listing what moves to recycle.
- Light/dark toggle: CSS custom properties, persisted in `localStorage`,
  respects `prefers-color-scheme` on first load.

## Security (trust boundary — non-negotiable)

`/api/delete` receives arbitrary paths. Before moving ANY file:
- `os.path.realpath()` each target.
- Assert the resolved path starts with one of the allowed scan roots
  (resolved). Reject the whole request on any violation — no partial deletes.
- This guards against malformed requests AND our own path-assembly bugs.
  Basic auth is not a substitute.

Allowed roots come from `SCAN_ROOTS` env (comma-separated), each `realpath`'d
at startup.

## Recycle (delete implementation)

- Trash root: `/volume1/private_media/.dupe-sweeper-trash/` — SAME volume as the
  media, so `os.rename` is an atomic metadata move (cross-volume `shutil.move`
  would copy multi-GB files, minutes each, non-atomic).
- Preserve relative path under trash + timestamp prefix to avoid collisions.
- Emptying trash is manual (File Station or a single explicit button later —
  no auto-purge in v1).

## Deployment / ops

- `docker-compose.yml`: `dupe-sweeper` service (expose 8000) + `nginx` (port 5069).
- Mount media **read-write**: `/volume1/private_media/<library>:/media/<library>`.
  Container must run as the UID/GID owning those files (Synology dynamic-UID
  trap) or the move fails — verify with a real delete on the NAS, not locally.
- `SCAN_ROOTS=/media/<library>`, `TRASH_DIR=/media/<library>/.dupe-sweeper-trash` (inside the
  mounted path so it lands on volume1).
- SQLite DB on a named docker volume (`/data`), separate from media.
- Basic auth creds from vault key `stacks.dupe_sweeper.dashboard.*`
  (`user`, `password` → htpasswd), rendered via the manifest.
- Register in `deploy.manifest.yaml` and root `CLAUDE.md` stacks table.

## Testing

- `test_dedup.py`: `extract_code` cases (SSNI-618 == SSNI-00618, FC2-PPV,
  HEYZO hd, caribbean date form, multipart cd1/A.B, BLOCKLIST rejects), and
  the delete path-guard (target outside root → rejected).
- Real-delete smoke test on the NAS (dynamic-UID + same-volume rename).

## Scope cuts (YAGNI)

- No ffprobe / real video metadata — filename-guessed resolution only (user
  chose A). Add later if quality-accurate keep matters.
- No perceptual/content hashing (re-encode dupes at different bitrate).
- No auto-purge of trash.
- No decisions persistence.
