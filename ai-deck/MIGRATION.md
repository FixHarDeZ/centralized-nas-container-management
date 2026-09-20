# Rename claude-desk → AI Deck

Status: source changes prepared locally; **not deployed**. Use this runbook for the first cutover only. Stop active chat/terminal jobs before taking the backup. Do not run both projects on port 5072.

## What changes

| Item | Before | After |
| --- | --- | --- |
| Repository/NAS stack directory | `claude-desk/` | `ai-deck/` |
| Compose project/main service/container | `claude-desk` | `ai-deck` |
| nginx container | `claude-desk-nginx` | `ai-deck-nginx` |
| Image runtime scripts | `/opt/claude-desk` | `/opt/ai-deck` |
| UI/Homepage/PWA name | Claude Desk / AI Desk | AI Deck |

Port 5072, external URL/DSM reverse proxy, `/work` bind source (`CLAUDE_WORK_DIR`), Unix user `/home/claude`, encrypted `stacks.claude_desk.*` vault keys, and browser storage keys deliberately remain unchanged. These identify existing data or provider configuration, not the Compose project. No vault decryption/key rotation is needed for this rename. The home volume is **external** so Compose refuses a missing volume instead of silently making an empty home.

## Preflight on NAS (read-only)

1. Confirm the old project's actual name and the volume mounted at `/home/claude`:

   ```sh
   sudo docker inspect claude-desk --format '{{ index .Config.Labels "com.docker.compose.project" }}'
   sudo docker inspect claude-desk --format '{{range .Mounts}}{{if eq .Destination "/home/claude"}}{{.Name}}{{end}}{{end}}'
   sudo docker inspect claude-desk --format '{{range .Mounts}}{{if eq .Destination "/work"}}{{.Source}}{{end}}{{end}}'
   ```

2. The default expected home volume is `claude-desk_claude_desk_home`. Verify it:

   ```sh
   sudo docker volume inspect claude-desk_claude_desk_home
   ```

   If the observed name differs, set `AI_DECK_HOME_VOLUME` in `ai-deck/secrets.manifest.yaml` under `literals`, render the environment again and verify `docker compose config --volumes`. Do not guess, create a replacement volume, or use `down -v`.

3. Retain the old directory, old images and nginx basic-auth file for rollback. Back up the home volume and the `/work` share with your existing NAS backup/snapshot process. Home contains credentials; keep its backup private. Confirm the backup completed before stopping the project.

## Cutover (future, explicitly authorized deployment)

1. Stage the new `ai-deck/` directory and rendered `.env`/`nginx/.htpasswd` using the repository's normal secret rendering/upload workflow. Confirm its work bind resolves to the same path as preflight. No NAS directory move is required; retain the old directory.
2. Stop and remove the old project's containers/network **without deleting volumes**. Use the observed project name if different:

   ```sh
   cd /volume2/docker/claude-desk
   sudo docker compose -p claude-desk down
   ```

3. From the workstation, deploy **only** the new stack after the above preflight and stop:

   ```sh
   ./scripts/deploy.sh -s ai-deck -y
   ```

   This command is not part of the local implementation. The first NAS build must run natively on amd64; a successful arm64 workstation build is not proof of amd64 readiness.
4. Startup migrates stack-owned status-line and completion-hook commands in existing `~/.claude/settings.json` from `/opt/claude-desk/` to `/opt/ai-deck/` before merging the new template. Other settings/hooks remain intact. Existing browser drafts/theme/provider/view keys continue to work on the same URL.
5. Check both users' login, saved Claude/Codex histories, files under `in/` and `out/`, Codex sign-in indicator, Model/Effort selectors, and terminal connections. Confirm the running home mount is the preflight volume. Existing PWA shortcuts may require reopening for the updated title. Deploy Homepage separately if its display label should change immediately.

## Rollback

Stop `ai-deck` without `-v`, then restart the old project's retained image and Compose file. Since startup rewrites provider hook settings, restore the pre-cutover `~/.claude/settings.json` backup (or replace only `/opt/ai-deck/` back to `/opt/claude-desk/` in stack-owned hook/status-line commands) before starting the old image. Do not overwrite new user work with an old full-volume backup. Port, proxy, credentials and work bind remain the same. Retain both stack directories until the new project has been verified.

## Fresh installation

An installation without previous data must explicitly create its chosen external home volume and configure `AI_DECK_HOME_VOLUME` before `up`. For a new installation use `ai-deck_home`; the legacy default is only for migration. Create the existing `/volume2/claude-work` share (or set `CLAUDE_WORK_DIR`) through the normal NAS share workflow.
