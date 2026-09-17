<!-- PLAN-RELAY stage=done round=1 -->

# Doc-drift checker: CLAUDE.md stack table vs the filesystem

## CONTEXT

Repo root: `/Users/peerawat.ujaiyen/MyCode/centralized-nas-container-management`. Monorepo of Docker Compose stacks deployed to a Synology NAS. Work happens on branch `doc-drift-checker`.

Things you need to know, all verifiable in the repo:

- **Stack directory** = a top-level directory containing a `docker-compose.yml`. Examples: `ink-reader/`, `news-feed/`, `claude-desk/`. Non-stack top-level dirs that must be ignored: `docs/`, `scripts/`, `secrets/`, `shared/`, `tests/`, `screenshots/`.
- **`CLAUDE.md`** (repo root, ~99 KB) contains one Markdown table, the "Stacks & Ports Directory". Header line is:
  `| Directory | Purpose | Port (Internal / Proxy) | Critical Gotchas / Architecture |`
  followed by a `| :--- | :--- | :--- | :--- |` separator, then one row per stack. A row's first cell is the directory name in backticks with a trailing slash, e.g. ``| `homepage/` | Dashboard UI | 3000 / 443 | ... |``. Note `uptime-kuma/` has no space before the closing pipe of cell 1 — parse tolerantly, do not assume fixed spacing.
  Third cell is `Internal / Proxy`, e.g. `5068 / 15068`, `8096 / —`, `— / —`, and sometimes annotated: `9091 (Authelia) / 8222 (Vaultwarden)`, `5071 (dashboard) / 15071`.
- **`scripts/deploy.sh`** line ~125 defines `ALL_STACKS=(secretary n8n news-feed ...)` — a bash array of stack names deploy.sh iterates. A stack directory that exists but is absent from this array never gets deployed.
- **`<stack>/secrets.manifest.yaml`** declares the stack's secrets. `scripts/deploy.sh` treats a stack as needing a rendered `.env` when this file exists.
- **Known-true drift already confirmed by hand** (use these as seeds — the checker MUST find all three):
  1. `CLAUDE.md` says story-factory is not in `ALL_STACKS`, but `story-factory` IS in the array (`scripts/deploy.sh:125`).
  2. `CLAUDE.md` table has a row for `auth/` — no such directory exists.
  3. `CLAUDE.md` table has a row for `my-secretary/` — no such directory exists.
- **Precedent to imitate**: `tests/test_shared_sync.py` is an existing repo-drift guard. Read it first. It discovers its inputs via `git ls-files` instead of hardcoding a list, and its docstring tells the reader how to fix a failure. Follow both habits.
- **Test suite**: `python3 -m pytest tests -q` from the repo root. Currently `48 passed`. Config lives in `pyproject.toml` (`testpaths = ["tests"]`). Ruff config is there too: line-length 88, double quotes, target py312.
- Python 3.12. `yaml` (PyYAML) is importable — `scripts/render_env.py` already uses it. No new dependencies may be added.

## GOAL

A committed checker that fails when the root `CLAUDE.md` stack table, the stack directories on disk, and the `ALL_STACKS` array in `scripts/deploy.sh` disagree — so this class of drift is caught by the test suite instead of by a human reading a 99 KB file.

## SCOPE

- `scripts/check_doc_drift.py` — standalone, runnable directly, prints a human-readable report, exit 0 when clean / exit 1 when drift found.
- `tests/test_doc_drift.py` — pytest wrapper so the suite enforces it.
- Report/assert on exactly these three drift classes:
  1. **Ghost row** — table row whose directory does not exist.
  2. **Undocumented stack** — directory with `docker-compose.yml` and no table row.
  3. **Deploy-list mismatch** — stack directory not in `ALL_STACKS`, or name in `ALL_STACKS` with no matching directory.
- Fixing the drift the checker finds is NOT part of this delivery. The checker is allowed — expected — to fail on `main` as it stands.

## OUT OF SCOPE

- Do not edit `CLAUDE.md`. Do not edit any `README.md`. Do not edit `scripts/deploy.sh`.
- Do not compare port numbers against `docker-compose.yml`. Ports are annotated in prose and would need fuzzy matching; that is a later round.
- Do not touch `.notes/` anywhere. This deliverable belongs to no single stack, so there is no valid `<stack>/.notes/daily_log.md` target, and writing to root `.notes/` is forbidden by `CLAUDE.md`. Skip the logging rule entirely for this task.
- Do not add dependencies, do not modify `pyproject.toml`, do not reformat unrelated files.
- Do not commit. Leave changes in the working tree.

## TASKS

1. **Read the precedent**
   - Input: `tests/test_shared_sync.py`, `pyproject.toml`.
   - Do: note the discovery-not-hardcoding pattern and the fix-hint docstring.
   - Output: none.
   - Verify: —

2. **Write `scripts/check_doc_drift.py`**
   - Input: `CLAUDE.md`, `scripts/deploy.sh`, the repo's top-level directories.
   - Do: implement these functions, each independently testable and each returning data rather than printing:
     - `stack_dirs(root) -> set[str]` — top-level directories containing `docker-compose.yml`. Discovered from the filesystem. **Never hardcode a stack list anywhere in this file**; a list that has to be edited when a stack is added is the bug this checker exists to catch.
     - `documented_stacks(claude_md_text) -> dict[str, int]` — stack name (no trailing slash) → 1-based line number of its row. Locate the table by its header line, read rows until the first line that is not a table row.
     - `deploy_stacks(deploy_sh_text) -> set[str]` — names inside the `ALL_STACKS=( ... )` array. The array may wrap lines; parse from `ALL_STACKS=(` to the closing `)`.
     - `find_drift(...) -> list[str]` — one string per finding, each naming the stack and the drift class.
   - Then a `main()` that prints findings and returns exit code 1 if any, 0 if none. Guard with `if __name__ == "__main__": raise SystemExit(main())`.
   - Every finding line must cite where the evidence is (`CLAUDE.md:37`, `scripts/deploy.sh:125`, or the directory path) so a reader can act on it without re-deriving anything.
   - Output: `scripts/check_doc_drift.py`.
   - Verify: `python3 scripts/check_doc_drift.py; echo "exit=$?"` — expect exit 1 and the three seeded findings present in the output.

3. **Write `tests/test_doc_drift.py`**
   - Input: the module from task 2.
   - Do: import the functions and test them against **literal fixture strings defined in the test file** (a small fake CLAUDE.md table, a small fake `ALL_STACKS=(...)` snippet) — not against the real repo files, whose content changes as the drift gets fixed. Cover: a ghost row, an undocumented stack, both deploy-list directions, a clean case yielding no findings, and the tolerant parsing of a row with no space before the pipe (`| `uptime-kuma/`| ... |`).
   - Module docstring must state what failure means and that `scripts/check_doc_drift.py` is the standalone entry point.
   - Output: `tests/test_doc_drift.py`.
   - Verify: `python3 -m pytest tests -q` — expect all tests passing, count strictly greater than 48.

4. **Lint**
   - Do: `ruff check scripts/check_doc_drift.py tests/test_doc_drift.py` and `ruff format --check` the same two files; fix what they report. If `ruff` is not installed, say so in a BLOCKED line rather than installing it.
   - Verify: both commands clean, or one BLOCKED line.

## CONSTRAINTS

- Standard library plus what the repo already imports. No new dependencies.
- Python 3.12, ruff-clean: line length 88, double quotes, import sorting (`I`), `select = ["F","E","W","I","UP","SIM","RUF"]`.
- Stack names are compared without the trailing slash. `auth/` in the table is the stack name `auth`.
- The three seeded drifts in CONTEXT are real. If your checker does not report all three, the checker is wrong — do not "fix" the repo to match the checker.
- No hardcoded stack lists, no hardcoded line numbers, in shipped code.
- Do not invent facts about stacks. Everything the checker knows must come from parsing a file.

## ACCEPTANCE CRITERIA

- [ ] `python3 scripts/check_doc_drift.py` exits 1.
- [ ] Its output contains a finding naming `story-factory`, one naming `auth`, and one naming `my-secretary`.
- [ ] Every finding line cites a file path, and rows sourced from the table cite a `CLAUDE.md:<line>` location.
- [ ] `python3 -m pytest tests -q` passes with more than 48 tests.
- [ ] `grep -nE '"(news-feed|ink-reader|claude-desk)"' scripts/check_doc_drift.py` returns nothing — i.e. no hardcoded stack names in the checker.
- [ ] `git status --short` shows exactly two added files: `scripts/check_doc_drift.py`, `tests/test_doc_drift.py`. Nothing else modified.
- [ ] `ruff check` and `ruff format --check` clean on both files (or one BLOCKED line explaining ruff is unavailable).

## DELIVERY FORMAT

- Full contents of `scripts/check_doc_drift.py` and `tests/test_doc_drift.py` — complete files, not diffs, not a summary of what you did.
- Pasted real output of every Verify command above, including the `echo "exit=$?"` line and the `git status --short` output.
- One `BLOCKED: <task> — <reason>` line per step you could not complete.

---

## REVIEW (round 1, Manager)

Delivery accepted. Independent re-parse of `CLAUDE.md` / disk / `ALL_STACKS`
matched the checker's output exactly (disk 18, rows 20, array 18; `rows - disk
= {auth, my-secretary}`, all other set differences empty).

**The plan was wrong, not the delivery.** CONTEXT seed 1 described a drift the
SCOPE's three classes structurally cannot express: `story-factory` is
consistent across directory, table row and `ALL_STACKS` — the contradiction
lives in the row's *prose*. The Officer raised it as BLOCKED instead of
hardcoding a check or editing `CLAUDE.md` to match. Correct call.

Manager fixed directly (small gap):
- `stale_deploy_claims()` — 4th class, deliberately narrow: only rows that name
  `ALL_STACKS` in their prose are examined.
- 3 tests for it, including the silent cases.

Final: `python3 scripts/check_doc_drift.py` exits 1 with all three seeds
reported; `pytest tests -q` 61 passed; ruff clean.

**Out-of-scope action to be aware of:** the Officer ran `uv sync`, which
stripped `.venv` (the committed `uv.lock` pins zero packages), then reinstalled
pytest/jsonschema/pyyaml to restore a working suite. `.venv` is healthy and
`uv.lock` is unmodified, but the lockfile is a live trap for anyone running a
bare `uv sync`. Separate task.

## ROUND 2 (no relay — Manager inline)

Deliberately not relayed: three judgment calls plus one test, well under the
threshold in the plan-relay skill's "When NOT to use".

Evidence gathered before editing:
- `auth/` removed in `8b48688` (2026-05-26), `my-secretary/` in `509472d`
  (2026-05-28, replaced by `secretary/`). Root `README.md` was updated in both
  commits; the CLAUDE.md table row was missed. Rows deleted.
- `story-factory` IS in `ALL_STACKS` since `908f2e3` (2026-09-15), but has no
  `stacks.story_factory.*` keys in the vault and its `secrets.manifest.yaml`
  keeps `env:` fully commented. Only the `ALL_STACKS` clause was stale; the
  "ยังไม่ deploy" claim is true and stays.

Checker change: `stale_deploy_claims()` now requires an explicit absence claim
(`ABSENCE_CLAIM_RE`, Thai + English) instead of any mention of the array — the
corrected row names `ALL_STACKS` too, and mention-matching turned the fix into
a fresh finding.

GOAL now actually met: `test_the_real_repo_has_no_doc_drift` reads the real
`CLAUDE.md`, disk and `deploy.sh`. Verified red by creating a throwaway
`zz-fake-stack/docker-compose.yml` (suite failed naming it twice), green after
removal. `python3 scripts/check_doc_drift.py` → "No doc drift found", exit 0;
63 passed; ruff clean.
