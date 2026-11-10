# delivery-log.jsonl — relative `path` rows break check_delivery.py

`check_delivery.py` verifies each ledger row with `os.path.isfile(r['path'])`. Rows whose `path`
was recorded as a bare relative name (e.g. `out.mp4`, when send_clip.py was invoked from inside
the scratch build dir) fail with `delivered file missing on disk <day> file=out.mp4` — a FALSE
alarm: the send itself verified fine (`ok: true`, `message_id`, `remote_size == size`).

## Diagnosis (always do this before touching the ledger)

1. Find candidate files by hand (same-day scratch dirs, Downloads).
2. sha256 the candidate and compare against `r['sha256']` from the ledger row.
3. Only if hash AND size both match → rewrite that row's `path` to the absolute path.

Never "fix" a row whose hash does not match; report it instead — that would be a real loss.

## Prevention

Always pass an ABSOLUTE path to send_clip.py (e.g. the copy in `~/Downloads/`), never a relative
`out.mp4` from the build directory.

Both diagnosed+repaired on 2026-11-03 (gameplay-11 → moomin-gp/out.mp4, gameplay-12 →
eternia/out.mp4, both hashes matched); check_delivery.py then returned RC=0.
