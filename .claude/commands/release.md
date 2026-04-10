---
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(git log:*), Bash(git tag:*), Bash(git add:*), Bash(git commit:*), Bash(git push:*), Bash(gh release create:*)
description: Commit staged changes, bump version tag, push to GitHub, and create a GitHub release
---

## Context

- Current git status: !`git status`
- Staged and unstaged changes: !`git diff HEAD`
- Recent commits: !`git log --oneline -5`
- Latest tag: !`git tag --sort=-v:refname | head -1`

## Your task

1. **Determine next version**: Read the latest tag above (e.g. `v1.2.3`). Ask the user whether to bump `patch`, `minor`, or `major` — then compute the new version (e.g. `v1.2.4`, `v1.3.0`, `v2.0.0`). If the user already specified the bump type as an argument (e.g. `/release minor`), skip asking and use that.

2. **Commit**: Stage all modified tracked files and create a commit. Write a concise commit message that reflects the actual changes. Follow the Conventional Commits format (`feat:`, `fix:`, `docs:`, etc.). Always append:
   ```
   Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
   ```

3. **Tag**: Create the new version tag on the commit.

4. **Push**: Push `main` branch and the new tag to `origin`.

5. **GitHub Release**: Create a release with `gh release create` using:
   - Title: `<version> — <short description>`
   - Notes: bullet points summarizing what changed, written in English

Do all steps sequentially. Do not ask for confirmation between steps — just do it.
