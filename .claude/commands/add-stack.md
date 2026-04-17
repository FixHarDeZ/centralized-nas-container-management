---
allowed-tools: Bash(ls:*), Bash(git status:*), Read, Write, Edit
description: Scaffold a new Docker Compose stack directory and register it in CLAUDE.md
---

## Context

- Existing stacks: !`ls -d */ | tr -d '/'`
- Current CLAUDE.md stacks table: !`grep -A 20 "## Stacks" CLAUDE.md | head -20`

## Your task

The user wants to add a new stack. If they haven't specified a name/port/purpose, ask for:
- **Directory name** (e.g. `my-service`)
- **Purpose** (one line description)
- **Port(s)** exposed on the host

Then:

1. **Create the directory and `docker-compose.yml`**
   - Scaffold a minimal `docker-compose.yml` with a named volume for persistent data (if applicable), `restart: unless-stopped`, and `TZ=Asia/Bangkok`.
   - If the stack needs secrets, also create a `.env.example` with placeholder values.

2. **Update `CLAUDE.md`**
   - Add a row to the Stacks table: `| directory/ | Purpose | Port(s) |`

3. **Remind the user** of the post-upload steps:
   - Run `/deploy` to upload files to the NAS.
   - In DSM → Container Manager → Project → Create, point to `/volume1/docker/<directory>`.
