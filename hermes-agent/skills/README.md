# Hermes skills owned by this repo

The live copies live in the `hermes_agent_data` volume at `/opt/data/skills/<name>/`. This directory is
the source of truth since 2026-11-10. Edit here, commit and push, then sync.

| Skill | Role |
|---|---|
| `shopee-clip` | Router for every Shopee clip order (Telegram only). Asks the mode, intake, photo gate, storyboard, prompt pack, per-shot review, post, single `deliver`. Holds the shared scripts and templates. |
| `flow-driver` | Mode 🤖: drives Google Flow over CDP, wrapped by `clipjob.py` (pacing, fallback to the prompt pack). |
| `gameplay-clips` | Mode 🎬: footage + TTS clips from official videos (game trailers; brand product films via `references/product-footage.md` + `scripts/source_check.py`), 0 credits. |

The retired `flow-shopee-clips` is archived at `/opt/data/skills-archive/flow-shopee-clips` (outside the scan path).

## Sync
```
make hermes-skills        # ssh → container: git pull --ff-only in Hermes' clone, then sync.sh
make hermes-skills ARGS=-n   # dry run
make hermes-skills ARGS=--pull   # copy live in-place edits INTO Hermes' clone (nothing live changes); review, commit, push, sync
```
`sync.sh` copies tracked files only. It never touches runtime data (that lives in `/opt/data/clips/`), and it
removes files that were synced before but are no longer tracked.

## Rules
- `sync.sh` **pins** the three skills (`hermes curator pin`: the curator never archives or merges them). They are
  NOT locked: `hermes curator lock`'s terminal check is a heuristic, and on 2026-11-10 it refused a legit pipeline
  command (an inline python writing `vo_plan.json` in the work dir, chained with a gameplay script path), which
  stalled a real clip. Instead, sync **captures drift**: any live file that differs from what the last sync wrote
  (agent or curator edit) is saved with a diff under `/opt/data/clips/skill-drift/<ts>/`, then overwritten. Agent-
  created extra files are reported and kept. Review the drift dir after syncs and port what is worth keeping. To change one,
  Hermes edits its clone, commits and pushes, then runs `bash hermes-agent/skills/sync.sh` from the clone (or Fix
  runs `make hermes-skills`). `sync.sh` runs the tests first and syncs nothing if they fail. It also refuses while the clone has uncommitted
  skill changes (they would go live under the wrong baseline); `--pull` is the way to bring live edits back.
- Runtime data lives outside the skills: `/opt/data/clips/jobs` (clipjob), `/opt/data/clips/logs`
  (clip-log, delivery-log, perf-log), `/opt/data/clips/flow-state` (Flow project state).
- Size budgets (`tests/test_hermes_skills.py` → `DOC_BUDGETS`): router ≤15 KB, `house-rules.md` ≤20 KB,
  `gameplay-clips/SKILL.md` ≤30 KB, `flow-driver/SKILL.md` ≤8 KB. Long versions live in references
  (`house-rules-history.md`, `gameplay-pitfalls.md`, `cover-sticker.md`, `flow-production-notes.md`). A missed gate is fixed in
  `clipjob.py` with a test, not by adding prose.
- File names are unique across the three skills (also tested), so a reference mentioned in one skill
  is found in exactly one place.
- Tests: `uv run --with pytest --with numpy --with pillow pytest -q tests/test_hermes_skills.py hermes-agent/skills/shopee-clip/scripts hermes-agent/skills/gameplay-clips/scripts`
