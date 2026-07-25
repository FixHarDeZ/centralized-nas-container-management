# dupe-sweeper — Index

Duplicate video finder dashboard. Group files by media code, compare, recycle.

## Files
```
main.py       FastAPI: /api/roots /api/scan(bg) /api/scan/{id} /api/groups/{id} /api/delete /api/status
              + /api/masks GET|POST, /api/masks/{id} DELETE, /api/rename, /api/trash GET, /api/trash/empty,
              /api/deletions GET (audit log). api_delete logs the batch via db.log_deletions AFTER recycle().
              /api/trash/files GET → recycle.list_trash (live folder contents, grouped by batch, for Recycle tab)
              /api/trash/restore POST → recycle.restore (move file back to origin, dest gated + no-overwrite)
dedup.py      extract_code + res_guess + scan() walker; SKIP_DIRS = @eaDir/#recycle/.dupe-sweeper-trash
recycle.py    TRUST BOUNDARY module: validate() + recycle() (all-or-nothing) + rename() (same-folder,
              basename-only, no overwrite) + empty_trash() (basename==.dupe-sweeper-trash guard, perm delete)
              + trash_stats(). TRASH_BASENAME const.
db.py         SQLite scan_jobs + files + masks + deletions; groups() excludes masked signatures
              (mask_signature = sha1 of sorted normpath'd paths). mask by exact FILE SET not code. no
              pending-decisions table. deletions = audit log of completed recycles (survives Empty, logs fails)
config.py     DATA_DIR / SCAN_ROOTS / TRASH_DIR from env
static/       index.html + style.css (CSS-var light/dark) + app.js (vanilla)
nginx/        nginx.conf (all behind basic auth) + .htpasswd (generated, gitignored)
tests/        test_dedup.py — extraction cases + path-guard
```

## Key facts / gotchas
- **Port 5069.** 5068 = ink-reader.
- **Delete = move to recycle**, not os.remove. `TRASH_DIR` MUST be same volume as media
  (`/media/<library>/.dupe-sweeper-trash`) so `os.rename` is atomic; cross-volume would copy GBs.
- **Trust boundary**: every delete path realpath'd + must be under a `SCAN_ROOTS` entry,
  else whole request rejected. Validation happens before any move. See `recycle.py`.
- **Runs as root** (no USER in Dockerfile) — must delete media owned by various Synology
  users; sidesteps dynamic-UID trap. OK because LAN-only + basic auth + realpath gate.
- **No app secrets.** Dashboard auth in nginx `.htpasswd` from vault `stacks.dupe_sweeper.dashboard.*`.
- Media mounted **read-write** in compose (`/volume1/private_media/<library>:/media/<library>`).
- Code match: SSNI-618 == SSNI-00618 (zero-pad stripped), FC2-PPV, HEYZO (heyzo_hd_2451),
  caribbean date form (010112-123, 123456_789), standard LETTERS-DIGITS. BLOCKLIST drops
  codec/quality tokens (x264/1080p/…). Multi-part badge for cd1/cd2/.A/.B (keep all).

## Gaps / not done
- Deployed to NAS + dashboard in active use (scan/mask/rename/recycle/history/restore all wired,
  mobile layout, neutral wording). Vault key + `.htpasswd` created. Tests 34 passed locally.
- **Not yet exercised end-to-end on NAS**: a real delete→restore round-trip through the dashboard
  hasn't been confirmed. Restore writes back into the media tree AS ROOT — the write-direction of
  the dynamic-UID concern; unit tests can't see it. Do one live delete+restore to be sure.
- No ffprobe (resolution guessed from name), no content hashing, no auto-purge of trash.
- Restore/mask assume single scan root; deletions audit log has no retention.
