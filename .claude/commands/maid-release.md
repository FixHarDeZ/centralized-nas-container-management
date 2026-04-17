---
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git tag:*), Bash(git add:*), Bash(git commit:*), Bash(git push:*), Bash(gh release create:*)
description: Commit maid-tracker changes, bump version tag, push, and create a GitHub release
---

## Context

- Changed files in maid-tracker/: !`git diff --name-only HEAD -- maid-tracker/`
- Unstaged maid-tracker/ diff: !`git diff -- maid-tracker/`
- Recent commits: !`git log --oneline -5`
- Latest tag: !`git tag --sort=-v:refname | head -1`

## Your task

Same as `/release` but scoped to `maid-tracker/` only.

1. **Determine next version**: Read the latest tag. Ask whether to bump `patch`, `minor`, or `major` — compute new version. If the user specified the bump type as an argument (e.g. `/maid-release patch`), skip asking.

2. **Commit**: Stage only files under `maid-tracker/` that are modified. Write a concise Conventional Commits message reflecting the actual changes. Always append:
   ```
   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
   ```

3. **Tag**: Create the new version tag on the commit.

4. **Push**: Push `main` branch and the new tag to `origin`.

5. **GitHub Release**: Create with `gh release create`:
   - Title: `<version> — <short description>`
   - Notes: bullet points summarizing maid-tracker changes, written in English

Do all steps sequentially without asking for confirmation between steps.
