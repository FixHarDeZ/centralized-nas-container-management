# Repository instructions

Read `CLAUDE.md` for this repository's shared instructions, including stack memory and deployment rules.

## Closing work

When the user says **“จบงาน”** or otherwise asks to close the task, always update both files in each stack worked on before the final response:

- `<stack>/.notes/daily_log.md`: completed changes, verification results, remaining work, and actual deployment/commit status.
- `<stack>/.notes/00_INDEX.md`: current index memory, even when there was no structural change.

Do this without asking for another reminder. Verify both updates, then confirm closure. Never write stack memory to the repository-root `.notes/`.
