# Trusted deployment runner

Coding workspaces can request deployment of an exact approved branch tip. Pushing code does not deploy it. The independent runner executes operator-configured deployment **and health** commands on a workstation or VM. Do not place it, its token, SSH credentials, age key, or production environment in the coding worker. The configured branch is a production code-execution trust boundary: protect it and require review. Repository scripts on that branch execute with production credentials.

Install Python 3.10+, Git, sops, age, SSH, curl, and PyYAML in the trusted host's Python environment. Copy `deploy_runner.py` and `run-nas-deploy.sh` into an operator-owned `/opt/ai-deck-runner/`. Copy `deploy-profiles.example.json` into an operator-only configuration directory and replace repository, allowed desk usernames, and health URL. The example's health URL must be replaced with a real unauthenticated readiness endpoint for the deployed application; a wrong endpoint correctly fails the deployment job. Commands are argv arrays, without shell expansion. Both command and health_command are required. The timeout applies separately to each command. All profiles are serialized by one runner.

Create a random shared token file readable only by the trusted runner and document backend (for example, `openssl rand -hex 32 > /secure/ai-deck-deploy-token`, then `chmod 600`). Configure a service manager to launch:

```sh
export AI_DECK_NAS_DEPLOY_ENV=/secure/nas/.env.deploy
export SOPS_AGE_KEY_FILE=/secure/nas/age-keys.txt
export AI_DECK_DEPLOY_PYTHON=/opt/ai-deck-runner/venv/bin/python
/opt/ai-deck-runner/venv/bin/python /opt/ai-deck-runner/deploy_runner.py \
  --profiles /secure/nas/deploy-profiles.json \
  --data /var/lib/ai-deck-deploy \
  --token-file /secure/ai-deck-deploy-token \
  --host 127.0.0.1 --port 8792
```

Keep `.env.deploy` and the age private key outside all workspaces/checkouts with mode `0600`. Bootstrap `.env.deploy` using the existing SOPS render flow on the trusted host, then move it to the external path above. It is shell configuration consumed by the existing deployment script and must be operator-controlled. The adapter renders stack environments with `scripts/render_env.py --exclude deploy`, copies only the operator `.env.deploy`, and invokes the checkout's `scripts/deploy.sh --yes --stacks ai-deck`. The repository deploy script uploads the repository and rendered stack environments even when only one stack is restarted. It may print completion after a failed service health check, which is why the runner requires an independent health argv. Adapter output suppresses potentially sensitive deployment-script diagnostics. Configure SSH known hosts/aliases on this host; the existing deployment script's connection behavior still applies.

Private GitHub repositories require independent read credentials on the runner, such as a protected `GIT_ASKPASS` helper. The runner disables system/global Git configuration and interactive prompts; do not rely on a global URL rewrite or credential helper. Public configuration accepts GitHub HTTPS repositories only. It creates a unique clean checkout under its own data directory, fetches only the configured branch, verifies the requested full lowercase SHA equals the fetched tip, and checks out that SHA detached before execution. It removes checkouts, including rendered secrets, after each job. A branch can advance after this verification; the deployed SHA remains fixed to the verified snapshot.

Configure **only the trusted document backend** with `AI_DECK_DEPLOY_URL` and `AI_DECK_DEPLOY_TOKEN_FILE`. The backend forwards authenticated requests with the bearer token and replaces `X-Desk-User` with the authenticated desk identity. Do not forward user-supplied identity headers. The runner trusts that identity only after constant-time bearer verification and then enforces each profile's allowed_users. The coding worker must have neither deployment setting nor token mount. Expose `/deploy/*` through that bridge, not through a direct public runner proxy. Loopback is the default; use a private tunnel or TLS plus firewall restrictions when the backend lives on another host. A container cannot reach workstation loopback directly: provide an explicit protected route/tunnel and set the backend URL accordingly.

API: GET `/deploy/profiles` and `/deploy/jobs` return `{ "items": [...] }`; POST `/deploy/jobs` accepts exactly `{ "profile": "nas-ai-deck", "sha": "<40 lowercase hex characters>" }`; GET `/deploy/jobs/<id>` returns an owner-visible job with status and log. Statuses are queued, running, succeeded, failed. Logs are bounded, secret environment values are redacted, and oversized command output is omitted. Jobs persist in private `jobs.json`; queued/running jobs from a stopped runner become failed on restart rather than repeating a potentially completed deployment. One process exclusively locks the data directory. Retain and back up this directory according to host policy; job history is not automatically pruned.

No deployment occurs merely by installing these files. Production credentials, profile values, network exposure, service supervision, and a real health endpoint must be provisioned on the trusted host.

## Mac installation used by this stack

The service layout is `~/.config/ai-deck-runner/{bin,venv,data,profiles.json,token,tls-cert.pem,tls-key.pem,nas.env.deploy}`. Keep the directory private (`0700`), token/private key/deployment environment `0600`, and scripts executable. Install `deploy_runner.py`, `run-nas-deploy.sh`, and `deploy_health.py` into `bin`. The dedicated Python venv needs PyYAML for the repository's SOPS renderer; Git, SSH, sops and age must be on the service PATH.

The LaunchAgent is `~/Library/LaunchAgents/local.ai-deck.deploy-runner.plist`. It runs the daemon after user login with `KeepAlive`, explicit PATH/HOME, operator-owned profiles/data/token paths, and `--tls-cert` / `--tls-key`. The listener binds the Mac's private interface, not all interfaces. Keep that address stable (for example a DHCP reservation), and renew its certificate before expiry. The daemon checks client bearer authentication before accepting any asserted desk user.

The document backend trusts the certificate supplied as base64 PEM in `AI_DECK_DEPLOY_CA_B64`; HTTPS keeps hostname verification enabled. Configure the URL, token and certificate in `stacks.ai_desk.deploy_runner.{url,token,ca_b64}` via `make edit-vault`, then `make sync-test-vault` and `make secrets`. These are never added to coding-worker environment or mounts. `AI_DECK_DEPLOY_TOKEN_FILE` remains supported for external deployments instead of the environment token.

Profiles include an `environment_allowlist`. Only basic process environment plus those explicitly named variables reach the checkout commands. Runner token variables and Git configuration injection variables are always excluded. The NAS example needs `AI_DECK_NAS_DEPLOY_ENV`, `AI_DECK_DEPLOY_PYTHON`, `AI_DECK_NAS_HEALTH_URL` and `SOPS_AGE_KEY_FILE`; allow SSH agent or Git askpass variables only when used. This is credential hygiene, not a sandbox: reviewed code on the deployment branch runs as the trusted runner user and can access that user's files.

For AI Deck, set the health command to the installed `deploy_health.py` using the runner venv Python and configure `AI_DECK_NAS_HEALTH_URL` to `http://127.0.0.1:18793/health` (the local SSH health forward). This endpoint returns only readiness/revision and does not need dashboard credentials. The NAS adapter renders environments, appends the exact checkout SHA and `COMPOSE_PROFILES=coding` to the stack environment, deploys, then the runner checks the returned revision against the job commit. A stale but responding service fails this check.

Inspect the service with `launchctl print gui/$(id -u)/local.ai-deck.deploy-runner`. Restart after installing updated scripts with `launchctl kickstart -k gui/$(id -u)/local.ai-deck.deploy-runner`. Logs are in the private service directory. Startup never submits a job. Mac sleep/offline produces a connection error in the UI; it is not reported as a successful deployment. Interrupted jobs are marked failed on runner restart; inspect NAS state before explicitly retrying.


## Outbound SSH tunnel from the Mac

The NAS cannot directly reach this Mac. Install `runner_tunnel.py` in the same private `bin` directory and supervise it using a second LaunchAgent, `local.ai-deck.deploy-tunnel`. It takes `--config ~/.config/ai-deck-runner/tunnel.json`:

```json
{
  "ssh_host": "nas",
  "socket_path": "/volume2/ai-work/.runner/runner.sock",
  "runner_host": "127.0.0.1",
  "runner_port": 8792,
  "health_local_port": 18793,
  "health_remote_port": 5072
}
```

Set `RunAtLoad`, `KeepAlive`, and `ThrottleInterval: 15`, and the same explicit `HOME`/`PATH` as the runner. Use private stdout/stderr log paths. The process keeps an outgoing SSH connection alive and exits on tunnel failure so launchd can reconnect. It also forwards Mac loopback port 18793 to the NAS health port. The document backend uses `AI_DECK_DEPLOY_SOCKET=/work/.runner/runner.sock` while verifying HTTPS against `AI_DECK_DEPLOY_URL=https://127.0.0.1:8792`. The coding worker receives neither the shared document mount nor these variables.

On this Synology, SSH forwarding was disabled. A backed-up, syntax-checked `sshd_config` now enables only the deploy account using a scoped `Match User` block. Equivalent settings for another installation are:

```text
Match User <deploy-account>
    AllowTcpForwarding yes
    PermitOpen 127.0.0.1:5072
    PermitListen none
    AllowStreamLocalForwarding remote
    StreamLocalBindUnlink yes
    StreamLocalBindMask 0117
```

These restrict TCP destinations to the health endpoint and deny TCP reverse listeners. The SSH reverse listener is a Unix socket. Its directory must belong to the NAS group used by the document container (`users`, GID 100 here), mode `2770`. The setgid directory is necessary because Synology creates the socket as root; with bind mask `0117`, the socket becomes `root:users`, mode `0660`. The tunnel checks that its account can write the socket before reporting readiness. Local NAS accounts in this group can connect to the socket but still need the runner token and an allowed identity.

Before reloading SSH, back up the configuration and run `sshd -t`; retain a working session until a new connection succeeds. The deployment account's existing SSH key stays on the Mac. No router port or NAS TCP listener is opened by this feature. DSM updates may reset SSH configuration, so recheck forwarding if reconnect fails.

For diagnosis, inspect `local.ai-deck.deploy-tunnel` with `launchctl print`, and the private `tunnel.log`/`tunnel.err`. Stop both LaunchAgents to disable deployment. Restore the saved SSH configuration and validate before reload if removing this integration. Do not remove the normal NAS SSH service.
