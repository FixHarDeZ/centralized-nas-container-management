---
allowed-tools: Bash(grep:*), Bash(git ls-files:*), Read
description: Scan all tracked files for hardcoded credentials and report what needs to move to .env
---

## Context

- Tracked files: !`git ls-files`

## Your task

Scan the repository for hardcoded secrets. Look for:

1. **Known credential patterns** in `docker-compose.yml`, `config/*.yaml`, `config/*.yml`, and any `.env` files that are tracked by git:
   - API keys and tokens: `_TOKEN`, `_KEY`, `_SECRET`, `_API_KEY`
   - Passwords: `PASSWORD`, `_PASS`
   - Usernames with actual values (not `${VAR}` references): `USERNAME=`, `USER=`
   - LINE tokens: `LINE_CHANNEL_ACCESS_TOKEN`, `LINE_USER_ID`
   - Plex/Jellyfin tokens

2. **Distinguish safe vs unsafe**:
   - `${VAR_NAME}` — safe (environment variable reference, no hardcoded value)
   - `VAR=actual_value_here` — **unsafe** (hardcoded)
   - Empty values `VAR=` — safe (disabled)

3. **Report findings**:
   - List each file and line with a hardcoded value (mask the actual secret: show only first 4 chars + `***`)
   - For each finding, suggest the env var name and which `.env.example` to add it to
   - Note: `CLAUDE.md` already documents known violations in `homepage/` — confirm if those are still present or have been fixed

4. **Summary**: Count of issues found. If none, confirm the repo is clean.
