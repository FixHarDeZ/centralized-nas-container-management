# log-medic — Index

## Gaps / TODOs
- `nginx/.htpasswd` not generated yet — run `htpasswd -c log-medic/nginx/.htpasswd <user>` before first deploy (same manual step as `friendly-reminder`).
- Vault keys not added yet — run `make edit-vault`, add `stacks.log_medic.dashboard.{user,password}` and `stacks.log_medic.github_token`.
- `/volume2/docker/log-medic/workspaces/<repo>/` must be `git clone`d once manually on the NAS before first use — the app only ever runs `git fetch` there.
