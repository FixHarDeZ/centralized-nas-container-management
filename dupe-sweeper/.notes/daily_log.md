# Daily Log — dupe-sweeper

## 2026-07-21 — new stack scaffolded
- Created `dupe-sweeper/` stack (port 5069) from the ink-reader/friendly-reminder pattern:
  FastAPI + SQLite + static dashboard behind nginx basic auth.
- Ported `avdedup.py` CLI code-extraction into `dedup.py`; added SKIP_DIRS
  (@eaDir/#recycle/.dupe-sweeper-trash) to the walk.
- Delete implemented as move-to-recycle with a realpath trust boundary (`recycle.py`):
  every target must resolve under `SCAN_ROOTS`, batch is all-or-nothing.
  `TRASH_DIR` on same volume as media so `os.rename` is atomic.
- Dashboard: root picker + subfolder + scan (bg thread, polled), group cards,
  per-file keep toggle (largest pre-kept), multi-part badge, confirm modal,
  light/dark toggle (CSS vars + localStorage).
- Fixed `.A/.B` part regex (double-separator bug). Tests: 18 passed
  (extraction + path-guard + all-or-nothing).
- Registered in `scripts/deploy.sh` ALL_STACKS and root CLAUDE.md table.
- Spec: `docs/superpowers/specs/2026-07-21-dupe-sweeper-dashboard-design.md`.

## 2026-07-21 — fix: static assets 404 (unstyled page, dead buttons)
- First NAS deploy rendered plain HTML, CSS+JS not loading. Cause: index.html
  references `/static/style.css` + `/static/app.js` but main.py never mounted
  StaticFiles → both 404. Fix: `app.mount("/static", StaticFiles(directory=STATIC_DIR))`.
- Needs container rebuild (`deploy.sh -s dupe-sweeper -y`) + hard reload.

## 2026-07-21 — fix: modal shown on load, Cancel dead
- `.modal{display:flex}` (author rule) overrode UA `[hidden]{display:none}`, so
  the confirm modal was visible at page load; its Cancel/Confirm handlers only
  bind inside recycleGroup(), so nothing was clickable. Fix: global
  `[hidden]{display:none!important}` in style.css. CSS-only, rebuild to redeploy.

## 2026-07-21 — features: mask (by file-set), rename, empty-recycle button
- **Mask** false-positive groups by EXACT file set (not code): `masks` table keyed on
  `mask_signature` = sha1(sorted normpath paths). New file same code -> set changes ->
  re-surfaces. groups() excludes masked sigs. "Not a duplicate" btn + Masked tab + unmask.
  Ceiling: path-based, renaming a masked file breaks the mask (no content hashing).
- **Rename** same-folder only (`recycle.rename`): old+new path validated under SCAN_ROOTS,
  new_name basename-only (reject / \ . .. empty), no overwrite. ✎ inline edit per file.
- **Empty recycle** (C2): `recycle.empty_trash` PERMANENT delete of trash contents, guarded by
  basename==.dupe-sweeper-trash + under-root + !=root (fat-finger TRASH_DIR=/media/<library> refuses).
  Recycle bar shows size/count, Empty button, confirm modal. trash_stats() for GET /api/trash.
- Frontend restructured: tabs (Duplicates|Masked) + recycle bar + generic confirmModal.
- Tests 29 passed (added rename escape/overwrite/outside-root, empty-trash basename guard,
  mask signature order-independence). Smoke: mask hides group 1->0.

## 2026-07-22 — features: jump-to-top + deletion history
- **Jump-to-top**: floating round btn `#to-top`, appears at scrollY>=400, smooth scroll.
  Pure frontend (index.html + `.to-top` css + scroll listener in app.js).
- **History tab**: audit log of completed recycles. New `deletions` table (batch, path,
  name, size, ok, error, created_at) — persists past Empty-recycle + records FAILED deletes,
  so "ย้อนหลัง" works regardless of trash state. Flat rows grouped by batch in UI (one section
  per Recycle click, header = timestamp + count + freed size).
  - `recycle.recycle()` now returns `batch` + per-file `size` (was only summed `freed`).
    Trust boundary untouched — sizes come from server, never client.
  - Log written in `main.py` api_delete AFTER recycle() (keeps recycle.py pure/testable).
    `db.log_deletions(batch, results)` derives name from path (no client trust).
  - `GET /api/deletions` (limit 500). ponytail: no retention, add purge if it grows.
  - Tests 30 passed (added log_deletions roundtrip incl. failed-row). db.py docstring updated
    (audit log of *completed* deletes ≠ the rejected pending-decisions table).

## 2026-07-22 — feature: restore from Recycle
- **Restore** button per file in Recycle tab → `POST /api/trash/restore` → `recycle.restore()`.
  Reconstructs origin from trash layout (`<trash>/<batch>/<orig_rel>` → `<owning_root>/<orig_rel>`),
  no schema change. Trust boundary: src must be inside trash, dest validated under SCAN_ROOTS,
  no-overwrite. Prunes emptied batch dirs. Single-root assumed (owning_root = root trash sits under);
  multi-root out of scope but dest still gated so no escape. Tests 34 passed (roundtrip+prune,
  no-overwrite, outside-trash reject).

## 2026-07-22 — feature: Recycle tab (view trash contents)
- New **Recycle** tab lists files currently in `.dupe-sweeper-trash`, grouped by batch folder
  (recycle timestamp), newest first. `recycle.list_trash()` walks trash → {name,path,size,mtime,batch}.
  `GET /api/trash/files`. Empty button (existing) permanently clears; list + count refresh after
  empty AND after each recycle. Read-only view (no restore — not requested). Tests 31 passed.

## 2026-07-22 — docs+dashboard: neutral wording (drop "porn"/"AV")
- Removed "porn" + "AV" from all .md (CLAUDE.md, README, .notes, specs, plan, jellyfin README)
  and dashboard text. "AV code" → "media code"; real paths masked as `<library>` placeholder
  (`/media/<library>`, `/volume1/private_media/<library>`) matching repo's `<NAS_HOST>` convention.
  Dashboard: subtitle → "Find and recycle duplicate video files by code", dropped 🎉 emoji.
- Scope = docs + dashboard only. Live config (docker-compose.yml, secrets.manifest.yaml, config.py)
  keeps real `/media/porn` mount — renaming it would resurface masks (path→signature) + need data
  migration for no gain. Docs use placeholder deliberately; source of truth is the compose file.
- index.html changed → rebuild+redeploy.

## 2026-07-22 — ui: mobile layout (≤640px media query)
- Scan panel stacks vertical + select/input/scan-btn full width (were min-width:160/180 → overflow
  on ~360px viewport). Tabs+recycle bar wrap. Group buttons drop margin-left:auto → wrap below.
  Tighter padding on topbar/main/group-head/file, jump-to-top to 16px corner. CSS-only, rebuilt+deployed.

## 2026-07-21 — ui: wrap long filenames/paths
- `.file-name`/`.file-sub` were nowrap+ellipsis, truncating long Thai names + deep paths.
  Switched to `overflow-wrap:anywhere; word-break:break-word` so they wrap fully. CSS-only.

### TODO before it works on NAS
- Add vault key `stacks.dupe_sweeper.dashboard.{username,password}`, generate `nginx/.htpasswd`.
- `make secrets` → deploy → create Project in Container Manager.
- Smoke-test a real delete on the NAS: confirm same-volume atomic rename + root can
  remove media files (dynamic-UID trap).
