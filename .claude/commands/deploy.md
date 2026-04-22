---
allowed-tools: Bash(git status:*), Bash(git diff:*), Bash(cat .deploy.env:*), Bash(ls:*), Bash(./deploy.sh:*)
description: Upload the project to the NAS via deploy.sh and optionally restart stacks
---

## Context

- Git status: !`git status --short`
- Uncommitted changes: !`git diff --stat HEAD`
- Deploy config exists: !`ls .deploy.env 2>/dev/null && echo "YES — .deploy.env found" || echo "NO — .deploy.env missing (copy from .deploy.env.example and fill in NAS details)"`

## Your task

1. **Pre-flight checks**
   - If `.deploy.env` is missing, stop and tell the user to run `cp .deploy.env.example .deploy.env` and fill in their NAS details (SSH key path, sudo password, etc.).
   - If there are uncommitted changes, warn the user that the working tree will be uploaded as-is (not just committed files). Ask if they want to commit first or continue.

2. **Run deploy**
   - Run `./deploy.sh` interactively so the user can respond to its prompts (restart all / per-stack / skip).
   - SSH auth is key-based (no `sshpass` needed). If the connection fails, check that `NAS_SSH_KEY` in `.deploy.env` points to the correct private key and that the key is present in `~/.ssh/authorized_keys` on the NAS.

3. **Report**
   - Confirm which stacks were restarted (if any).
   - Remind the user: if a stack has a local build (e.g. `maid-tracker`, `watchtower`), the `--build` flag in the script ensures the image is rebuilt on the NAS.
   - If `NAS_SUDO_PASSWORD` is not set, the restart step is skipped automatically — remind the user to add it if they want auto-restart.
