# Pronunciation checklist implementation plan

> Execute inline in this session using executing-plans. User approved the spec and implementation on 2026-10-08. Scope edits to shorts-factory and these two design/plan documents; preserve concurrent news-feed edits.

**Goal:** Send a script-specific list of words to listen to after every successful Script, including revisions and unattended generation.

**Architecture:** Add optional per-Card model metadata and a stdlib module that checks it against the narration/spoken text, adds conservative fallback candidates, merges repeats and formats Thai messages. Send the checklist separately through the existing chunked Telegram transport; keep the review message id and keyboard attached to the Script.

**Tech stack:** Python, existing mimo completion, Telegram Bot adapter, pytest. No new dependencies.

## Global constraints

- Spec: `docs/superpowers/specs/2026-10-08-shorts-factory-pronunciation-checks-design.md`.
- Metadata must not reject a valid Script; old Scripts work through fallback.
- Analysis includes only spoken narration. Do not invent pronunciation mappings.
- Show Script wording and note `/say` overrides; no audio correctness claims.
- Checklist send failures cannot block review/auto-render; do not catch cancellation.
- Shared vendored `mimo.py`/`telegram.py` remain managed by `make sync-shared`.
- User subsequently authorized commit, merge main, push and deploy on 2026-10-08. Keep actual delivery status in both stack memory files; YouTube publication remains a separate human action.

## Task 1: Validated checklist extraction and presentation

Files: create `shorts-factory/app/pronunciation.py` and `shorts-factory/tests/test_pronunciation.py`.

Interfaces:

```python
def normalize(script: dict) -> dict:
    # Sanitize optional pronunciation_checks on each Card in place.
    # Require actual term/narration and spoken/spoken substrings + allowed kind.
    return script

def collect(script: dict, locale: str = "th") -> list[dict]:
    # Return term, spoken, kind, cards, contexts; merge equal term/readings.
    # Thai Latin fallback; English initialisms/model-name fallback only.
    # Metadata-free terms have spoken="" and retain Card spoken context.
    return sorted(grouped.values(), key=lambda item: KINDS[item["kind"]][0])

def format_checks(script: dict, locale: str = "th") -> str:
    # Thai text, Card indices start at 1, no length truncation.
    # Wrap individual long lines before the shared transport sees them.
    return "\n".join(lines)
```

- [x] Write failing behavior checks for model metadata, Thai-only loanwords, multiword names, deduplication, different readings, priority, old Scripts, dotted initials/model names, exclusion of unsaid text, and malformed metadata.
- [x] Run `PYTHONPATH=shorts-factory .venv/bin/python -m pytest shorts-factory/tests/test_pronunciation.py -q`; verify missing feature failures.
- [x] Implement the three interfaces using regex and dictionaries. Match Latin term boundaries so `AI` cannot match `RAID`. Skip unknown/bad metadata without guessing the reading. Show fallback context explicitly.
- [x] Run the same tests and verify they pass.

## Task 2: Prompt and Telegram integration

Files: modify `shorts-factory/app/script.py`, `shorts-factory/app/main.py`, `shorts-factory/tests/test_shorts_factory.py`.

Interfaces consumed: `pronunciation.normalize(script)`, `pronunciation.format_checks(script, locale)`.

New bot seam:

```python
async def send_pronunciation_checks(client: httpx.AsyncClient,
                                    script: dict, locale: str) -> None:
    try:
        await say(client, pronunciation.format_checks(script, locale))
    except Exception:
        logger.exception("ส่งรายการคำที่ควรฟังตรวจไม่สำเร็จ")
```

- [x] Write integration tests for fresh/manual/auto generation, revision success/failure, saved normalized metadata, preserving message id/keyboard, a failed checklist delivery followed by render, English locale and actual Telegram chunking over 4096 characters.
- [x] Verify new tests fail before integration: `PYTHONPATH=shorts-factory .venv/bin/python -m pytest shorts-factory/tests/test_shorts_factory.py -q -k pronunciation`.
- [x] Add metadata instructions/schema to both Script prompts. Return `pronunciation.normalize(script)` from successful `validate()` and normalize mocked/legacy generated Scripts before `manifest.add_script()` as well.
- [x] Call the new send seam after posting successful Scripts and after reposting the previous Script on a failed revision. Save the review transition/message id before checklist delivery; auto-render stays after it. Preserve existing review/footer behavior.
- [x] Run extraction plus integration tests and existing stack tests; compare environment failures with the captured baseline.

## Task 3: Documentation and final verification

Files: update `shorts-factory/README.md`, `shorts-factory/.notes/daily_log.md`, `shorts-factory/.notes/00_INDEX.md`, and this plan's status.

- [x] Document the checklist, script-derived limitations, fallback/context, and `/say` + `/redo` workflow in README/help.
- [x] Review the actual diff for unrelated edits, incorrect audio claims, dropped text, stale draft metadata and changed render behavior. Fix concrete issues and run affected tests only when changes warrant it.
- [x] Run `PYTHONPATH=shorts-factory .venv/bin/python -m pytest shorts-factory/tests -q` and `.venv/bin/python -m pytest tests/test_shared_sync.py -q`.
- [x] Run Ruff on the new module/test plus changed files, distinguishing existing findings, and `git diff --check` on task files.
- [x] Record actual checks and local/commit/deploy status in both stack memory files. Report results and any limitations to the user.

## Review

Spec coverage checked: metadata, both Locales, duplicate readings, fallback, failure tolerance, message limits, old Scripts, revisions/auto-run and stack memory are assigned above. Dashboard, audio preview/timestamps and automatic pronunciation edits are outside this change.

Execution and release complete on 2026-10-08. Commit `eb474e5` fast-forwarded into
main and pushed; deployed through `scripts/deploy.sh -s shorts-factory -y` from a clean
managed worktree. All 284 tests passed in the deployed NAS image (283 network-free
plus the single real TTS check); shared-sync 5 passed. Source hashes, prompt/checklist
smoke, Raqm and dashboard health verified; three services running with zero restarts
or logged errors. Ruff new files clean with no introduced findings in existing files.
Code review findings resolved; both stack memory files updated with actual delivery.
