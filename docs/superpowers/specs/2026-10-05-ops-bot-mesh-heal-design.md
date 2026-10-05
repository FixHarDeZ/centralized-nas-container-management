# ops-bot: Mesh Node auto-heal — design

Date: 2026-10-05. Approved by user in chat the same day.

## Problem

The AiMesh node (`<MESH_NODE_IP>`) uses Ethernet backhaul to router port
`eth2`. When that link flaps, the node sometimes ends up half-attached: the
router still has its ARP entry and bridge MAC, but nothing answers on its IP.
It stays that way until the router restarts its network stack. Rebooting the
node does not help.

Evidence (router syslog, kept on the NAS at `~/router-evidence-2026-10-05/`):
`eth2` Link DOWN/Up 10:48:43–10:49:41, then wireless-backhaul assoc/disassoc
loop until 10:50:08, then silence. Kuma showed DOWN from 10:49 until the fix.

The DHCP page "Apply" fixes it because its hidden `action_script` is
`restart_net_and_phy` (read from `/www/Advanced_DHCP_Content.asp` on the
router). Running `service restart_net_and_phy` over SSH on 2026-10-05 15:36:17
brought the node back in about 50 s (Kuma UP 15:37:07).

Kuma history since 2026-04: 129 outages, 106 recovered by themselves within
5 minutes, 23 lasted longer than 5 minutes.

## Decision

When Kuma reports Mesh Node DOWN for 5 continuous minutes, ops-bot runs
`service restart_net_and_phy` on the router over SSH, automatically. Telegram
gets a notice; there is no confirm button. The fix restarts the whole home LAN
(about 1 minute; outbound internet from the NAS drops too).

Rejected:
- Bot probes the node itself on a timer, ignoring Kuma — two detectors for one fact.
- ASUS HTTP `login.cgi`/`applyapp.cgi` — admin password in the vault, single
  admin web session collides with the user, login lockout risk.
- Password SSH login — the password is the full router admin password.

## Flow

1. Kuma DOWN for the Mesh Node monitor → `mesh_heal.on_down()` records
   `down_since` in a JSON state file on the data volume (survives restarts).
   Nothing else happens. Mesh Node never reaches the LLM path, the deploy-window
   hold, or the debounce.
2. Kuma UP before the threshold → `down_since` cleared, silent (LINE and the
   other Telegram bot already report blips).
3. A 30-second watcher (`mesh_heal.tick()`, same pattern as `maintenance._watch`)
   sees `down_since` older than `MESH_DOWN_MINUTES` (5).
4. Pre-check: TCP connect to the node's port 80 from the container (3 s). If it
   connects, the node is back (or the UP was missed during a restart) → clear
   state, log, do nothing. ARP/bridge state is not a liveness check: both looked
   healthy while the node was broken.
5. Guards (all configurable):
   - cooldown: no new episode within `MESH_COOLDOWN_MINUTES` (30) of the last
     fix; the watcher waits, then acts if still down.
   - cap: at most `MESH_DAILY_CAP` (3) fix commands in a rolling 24 h. Hitting
     it → one Telegram message asking a human to check, then stop until UP.
6. Telegram notice **before** acting (the fix cuts the NAS's internet).
7. Open a quiet window of `MESH_QUIET_MINUTES` (3): DOWN alerts from other
   monitors (DDNS, the group) are held like in a deploy window; ones that
   recover inside it are silent, ones still down after it go to the normal
   diagnosis.
8. Router SSH: separate Paramiko client, key-only, host key pinned by SHA256
   fingerprint, one constant command. Not the NAS `SSHClient`, and nothing is
   added to `ALLOWED_PREFIXES` (that list feeds the LLM and stays read-only).
9. Wait up to `MESH_VERIFY_MINUTES` (5) for Kuma UP.
   - UP → Telegram "fixed in N s", action row marked success, failure count reset.
   - No UP → failure. Under `MESH_MAX_FAILURES` (2) → retry once right away
     (still counts toward the daily cap, exempt from cooldown). At the limit →
     Telegram asks a human to check, automation pauses until the next UP.
   - SSH error also counts as a failure.
10. Telegram sends after the fix retry with backoff (up to ~3 min) because the
    internet may still be coming back.

Group alert: a DOWN for `Home Network Monitor` whose message lists only the
Mesh Node (`Child monitors down: Mesh Node`) skips the LLM, and its later UP is
silent. If other children are listed (e.g. DDNS), it is diagnosed as today.

Every fix is recorded: one `incidents` row per episode (service `Mesh Node`)
and one `actions` row per command, so the dashboard shows how often it happens
(useful to judge a cable replacement).

## Components

- `app/router_client.py` — `restart_network() -> RouterResult(ok, output)`.
  Paramiko, pinned fingerprint policy, constant command, timeout. A dropped
  session after the command was sent counts as sent.
- `app/mesh_heal.py` — state file, `on_down`, `on_up`, `tick`, group-message
  check, watcher start/stop. Pure decisions take `now` so tests don't sleep.
- `app/maintenance.py` — add `quiet(until)`: an in-memory deadline that makes
  `active()` true without a marker file (no 🚀/✅ notices for it).
- `app/webhook.py` — branch for the Mesh Node monitor and the Mesh-only group
  alert **before** the maintenance check and debounce.
- `app/main.py` — start/stop the watcher.
- `app/config.py` — settings below. Feature off unless router host and node host
  are set, so tests and unconfigured deployments behave as today.

## Configuration

| Env | Default | Source |
|---|---|---|
| `MESH_NODE_HOST` | "" | vault `stacks.ops_bot.mesh_node.host` |
| `ROUTER_SSH_HOST` | "" | vault `stacks.ops_bot.router.host` |
| `ROUTER_SSH_USER` | "" | vault `stacks.ops_bot.router.user` |
| `ROUTER_SSH_PORT` | 22 | literal |
| `ROUTER_SSH_HOST_KEY_SHA256` | "" | literal (public fingerprint) |
| `HOST_ROUTER_KEY_PATH` | — | literal, compose mounts it at `/app/data/ssh/router_ed25519:ro` |
| `MESH_MONITOR_NAME` / `MESH_GROUP_NAME` | `Mesh Node` / `Home Network Monitor` | default |
| `MESH_NODE_PROBE_PORT` | 80 | default |
| `MESH_DOWN_MINUTES` / `MESH_VERIFY_MINUTES` / `MESH_QUIET_MINUTES` | 5 / 5 / 3 | default |
| `MESH_COOLDOWN_MINUTES` / `MESH_DAILY_CAP` / `MESH_MAX_FAILURES` | 30 / 3 / 2 | default |

Vault values go in before the manifest entries (a manifest key without a vault
value breaks `make secrets` for the whole repo).

## Testing

- Unit: threshold, UP reset, pre-check reachable → no action, cooldown,
  rolling cap, verify timeout → retry → give up, SSH error = failure, state
  survives reload, group-message parsing (only Mesh / Mesh + DDNS / other).
- Webhook: Mesh DOWN/UP never call `handle_incident`/`handle_recovery`, even
  inside a deploy window; Mesh-only group alert skipped, mixed group diagnosed;
  collateral DOWN during quiet window held.
- Router client: fingerprint mismatch refuses; constant command only.
- Live after deploy: Paramiko connect from inside the container to the router;
  link Kuma notification `ops-bot` to the Mesh Node monitor; first real outage
  confirms the failing-side probe (port 80 refused/timeout while broken).

## Out of scope

- Fixing the root cause (Ethernet cable/port on router `eth2`) — user's task.
- Kuma `maxretries` for Mesh Node (still 0).
