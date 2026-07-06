# ink-reader — Daily Log

## 2026-07-06 — Initial build (Tasks 1-9)

Built full stack via Subagent-Driven Development from
`docs/superpowers/plans/2026-07-06-ink-reader.md`:

- Task 1: scaffold, config, DB layer (titles table, lifecycle helpers)
- Task 2: CBZ builder (normalize downloaded pages into CBZ + cover extraction)
- Task 3: scraper parsers (listing + title page, against HTML fixtures;
  selectors verified live pre-implementation, see design spec Global
  Constraints)
- Task 4: scrape cycle orchestration (dedup via slug, `MAX_NEW_PER_CYCLE` cap,
  per-title error isolation)
- Task 5: OPDS feed (root nav + `new`/`kept` acquisition feeds)
- Task 6: scheduler (scrape / expiry / backup jobs) + sqlite_backup.py
  (verbatim copy of torrentwatch's)
- Task 7: FastAPI app (API + file/cover serving + OPDS routes, all
  unauthenticated in-app — nginx sidecar owns auth)
- Task 8: curation dashboard (vanilla JS, Thai UI, cover grid + keep/delete)
- Task 9: Docker/nginx/secrets/docs (this entry) + deploy + live verification

All tasks reviewed clean (byte-for-byte brief compliance + code quality) via
fresh implementer + reviewer subagent pairs per task; see
`.superpowers/sdd/progress.md` for the per-task ledger.

Deploy + live verification (Task 9 Steps 8-9), 2026-07-06:

- `./scripts/deploy.sh -s ink-reader -y` — build + restart on NAS, both
  `ink-reader` and `ink-reader-nginx` came up healthy on first try.
- Added `ink-reader` to `scripts/deploy.sh`'s `ALL_STACKS` array (was missing
  — needed for `-s all` restarts and the pre-upload `.env` presence check to
  cover this stack automatically going forward).
- Live scrape cycle against the real doujin-th.com: `found=11, downloaded=10`
  (capped by `INK_MAX_NEW_PER_CYCLE=10`), `error=null`. Parser selectors from
  Task 3 held with zero drift — no fixture/parser changes needed.
- Confirmed full lifecycle live via API: keep → `status=kept`,
  `expires_at=null`; delete → tombstone (`status=deleted`, `file_size=null`,
  CBZ+cover removed from disk); `/opds` root feed renders valid Atom XML.
- nginx basic auth confirmed: 401 without credentials, 200 with vault
  credentials (`stacks.ink_reader.dashboard.*`), on both `/` and `/api/status`.
- External port 5068 is LAN-only by design (matches spec) — verification was
  done via SSH to the NAS and curling `localhost:5068`, not from the
  workstation directly (workstation is off the NAS's LAN).
- Remaining, explicitly manual (per plan Step 10): DSM reverse proxy
  15068→5068 (only if outside-LAN dashboard access wanted), and KOReader
  setup/read test on the physical Meebook M8 — both are the user's own
  action, not automatable from here.
