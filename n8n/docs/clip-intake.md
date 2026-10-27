# Clip Intake (Hermes) — n8n → Hermes clip request bridge

Workflow `n8n/workflows/Clip_Intake.json` (live as **Clip Intake (Hermes)**, id `IYayiImdn0Jd5yMS`).
Purpose: Fix (or anything) POSTs a clip job to n8n; Hermes picks it up and runs the
`flow-shopee-clips` pipeline end to end, delivering the clip + hashtags + basket link to Telegram.

## Endpoint

```
POST https://<NAS_DOMAIN>/webhook/clip-request     # production (workflow must be active)
POST https://<NAS_DOMAIN>/webhook-test/clip-request # test URL while listening in the editor
Content-Type: application/json
X-Clip-Token: <CLIP_INTAKE_TOKEN>
```

**The token is mandatory.** `/webhook/` is public (homepage nginx skips basic auth there for
Telegram, and `:15678` reaches n8n directly), and everything that passes is HMAC-signed and handed
to a Hermes agent that has a terminal, the NAS SSH key and the vault age key. Without the token the
URL was an unauthenticated prompt-injection path to a shell (found and closed 2026-10-27).

- Value: vault `stacks.secretary.n8n.clip_intake_token` → `CLIP_INTAKE_TOKEN` in `n8n/.env`.
  Hermes reads it from its own clone (`/opt/data/centralized-nas-container-management/n8n/.env`
  after `git pull && make secrets`), the same way it reads the HMAC secret.
- `Record job` compares it in constant time; missing/empty env = every request rejected.
- `Record job` also bounds every field before it reaches the agent prompt:

| Field | Rule |
|---|---|
| `product` | required, ≤200 chars |
| `link` | `https://` on `shopee.co.th`, `*.shopee.co.th` or `shope.ee` only |
| `duration_s` | 5–60 (default 10) |
| `category` | `[a-z0-9_-]`, ≤30 (default `gadget`) |
| `images` | ≤6 paths, each under `/opt/data/cache/scratch/`, no `..` |
| `note` / `requested_by` | ≤500 / ≤40 chars |

Control characters (newlines included) are flattened to spaces. Rejections are **not** errors:
`Respond accepted` answers `401`/`400 {"status":"rejected","reason":...}` and `Sign for Hermes`
returns `skipped` — so strangers hitting the URL cannot spam the Error Alerter, but every attempt
is still kept in the execution log.

Body:

```json
{
  "product": "Nintendo Switch 2 The Legend of Zelda 40th Anniversary Edition",
  "link": "https://s.shopee.co.th/9zypVT2OOt",
  "duration_s": 20,
  "category": "game",
  "images": ["/opt/data/cache/scratch/zelda/zelda_box_clean.jpg"],
  "note": "อย่าให้มีราคาในคลิป",
  "requested_by": "Fix"
}
```

Response is immediate: `200 {"status":"accepted","job":{...}}` (or `401`/`400` rejected) (`Respond accepted` runs before the
rest of the workflow). The workflow stores the job in its own execution data —
`saveDataSuccessExecution: all` is required, otherwise a successful run stores nothing to read back.

## Delivery path — push model (since 2026-10-27)

```
POST /webhook/clip-request
  -> Clip Request (webhook) -> Record job (code) -> Respond accepted (200, immediate)
  -> Sign for Hermes (code: HMAC + POST to Hermes) -> Log
```

The `Sign for Hermes` Code node signs the job and POSTs it to Hermes' **webhook platform**:

- Gateway side: `platforms.webhook` in `/opt/data/config.yaml` binds `0.0.0.0:8644`; the route is
  the **dynamic subscription `clip`** in `/opt/data/webhook_subscriptions.json` (hot-reloaded). The
  old static `clip-request` route in config.yaml was removed.
- Network: the hermes-agent stack publishes `8644:8644`; homepage nginx proxies
  `https://<NAS_DOMAIN>/webhooks/*` -> `http://host.docker.internal:8644/webhooks/*`. n8n posts to `/webhooks/clip`.
- Auth: `X-Webhook-Timestamp` = unix seconds, `X-Webhook-Signature-V2` =
  `hex(HMAC_SHA256(secret, "<timestamp>.<body>"))`. Replay window 300 s.
- Secret: vault `stacks.secretary.n8n.hermes_clip_webhook_secret` → `HERMES_CLIP_WEBHOOK_SECRET`
  in `n8n/.env` (signing). The gateway validates with the `secret` stored inside the `clip`
  subscription, so the two must match by hand. `HERMES_WEBHOOK_SECRET` (the platform-level secret
  of the removed static route) is no longer used by n8n.
- On accept the gateway answers `202 {"status":"accepted", ...}` and runs the route's agent turn in
  the background (`deliver: telegram` + `deliver_extra.chat_id`), so n8n is never blocked by the
  length of the clip run.
- Failure handling: `Sign for Hermes` retries 3× (5 s apart, 20 s socket timeout) and the workflow's
  `errorWorkflow` is **Secretary Error Alerter** (`SzcBUowHn6PKGUlF`, Telegram). That only covers
  *handing the job to Hermes*: once Hermes answers 202, n8n knows nothing more — a gateway restart
  mid-run still loses the job without any alert.

## n8n env requirements (all mandatory)

Set in `n8n/docker-compose.yml` `environment:` (the stack has **no** `env_file`, so values must be
interpolated from `n8n/.env`):

- `HERMES_CLIP_WEBHOOK_SECRET=${HERMES_CLIP_WEBHOOK_SECRET}` — the HMAC secret
- `CLIP_INTAKE_TOKEN=${CLIP_INTAKE_TOKEN}` — caller token (empty = reject everything)
- `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` — Code node `$env` is blocked by default. Trade-off: every
  Code node and expression in every workflow can now read all of n8n's env, including
  `N8N_BASIC_AUTH_PASSWORD`.
- `NODE_FUNCTION_ALLOW_BUILTIN=crypto,http,https` — `require('crypto')` is disallowed by default

## Why the Code node POSTs the request itself

n8n's **HTTP Request node** sent a body whose bytes did not match what the Code node signed → the
gateway answered `401 {"error":"Invalid signature"}` on every attempt. Proof it was a transport
problem, not a signing problem: replaying the exact `hermes_body` / `hermes_ts` / `hermes_sig` from
the execution data straight at the gateway returned `202 accepted`.

So the Code node signs *and* sends (`require('https')` + a `{hostname, port, path}` options object,
`Content-Length: Buffer.byteLength(body)`, `req.write(body)`), keeping signature and payload in
lockstep. Two more sandbox gotchas: `fetch` and `URL` are **not** defined in the Code node — do not
use them; only allow-listed builtins are.

## Testing

End-to-end ping through n8n (from the Hermes box, after `make secrets` in its clone):

```python
import json, urllib.request
env = dict(l.split('=', 1) for l in open('/opt/data/centralized-nas-container-management/n8n/.env').read().split()
           if '=' in l)
body = json.dumps({"product": "PING (ห้ามทำคลิป แค่ตอบว่า PONG)", "link": "https://s.shopee.co.th/ping",
                   "duration_s": 10, "category": "gadget", "images": [], "note": "test"}, ensure_ascii=False)
req = urllib.request.Request("https://<NAS_DOMAIN>/webhook/clip-request", data=body.encode(), method="POST",
    headers={"Content-Type": "application/json", "X-Clip-Token": env["CLIP_INTAKE_TOKEN"]})
print(urllib.request.urlopen(req, timeout=30).read().decode())   # -> {"status": "accepted", ...}
```

Negative check (safe — rejected before anything reaches Hermes): the same POST without the header
must answer `401`, on both `https://<NAS_DOMAIN>/webhook/clip-request` and
`https://<NAS_DOMAIN>:15678/webhook/clip-request`.

Then check the n8n execution (`GET /api/v1/executions/{id}?includeData=true`) — `Sign for Hermes`
must return `hermes_status: 202` — and `/opt/data/logs/gateway.log` for
`[webhook] POST ... route=clip` + `delivery mirrored into telegram:8663614341 session`.

## Diagnostics workflow (kept)

`Hermes Bridge Probe` (`0vwF1zobUF4FmYbR`) — `POST /webhook/hermes-probe` → HTTP GET a fixed
health URL → responds with the result. The URL is hardcoded (no SSRF) but points at the old
container IP `192.168.112.2:8645`, which is gone after recreate — it only ever times out now.
Not in git; delete it or repoint it at `host.docker.internal:8644`.

## Retired: pull-model bridge

`/opt/data/n8n-bridge/clip_job_poller.py` (15 s poll of n8n executions → POST into a Hermes session
over loopback) is **stopped and kept only as reference**. It was replaced because it was an
unsupervised process (it died mid-job once and the clip order went silent), it polled n8n even when
idle, and it could not use the designed HMAC webhook path. Deleting `/opt/data/n8n-bridge/` is safe
once this push path has carried a real clip order.

## Bring-up checklist

1. `make secrets` (with `sops` on PATH and `$HOME/.config/sops/age/keys.txt` present) → renders
   `n8n/.env` + `hermes-agent/.env`, including the webhook secret.
2. Workflow updates go through `PUT /api/v1/workflows/{id}` (deactivate first, then activate) —
   `PATCH` is not allowed by the public API.
3. No bridge process to start anymore: the push path is gateway + nginx + n8n only.
4. Fire the ping (snippet above) plus the no-token negative check, and watch the n8n execution +
   `/opt/data/logs/gateway.log`.
5. Hermes-side state that lives **only in the volume** (not in git): `/opt/data/webhook_subscriptions.json`
   (route `clip`: `skills: [flow-shopee-clips]`, `toolsets: [hermes-cli]`, `deliver: telegram`,
   its own `secret`, and the prompt template) and the `TELEGRAM_BOT_TOKEN` line hand-copied into
   `/opt/data/.env` for `hermes send`. Losing the volume = rebuild both by hand; rotating the bot
   token in the vault does **not** update the copy in `/opt/data/.env`.

## Pitfalls worth remembering

- The Hermes container's LAN IP **changes on recreate** (was `192.168.112.2`, then `192.168.176.2`)
  — never hardcode it; the nginx → `host.docker.internal:8644` path is the stable one.
- `ss`/`netstat` are restricted inside the Hermes sandbox; read `/proc/net/tcp` instead.
- `deploy.sh -s <stacks>` restarts only the named stacks but uploads the whole project; `.env.deploy`
  is excluded from the upload, so a script copied to the NAS cannot read it.
- Full `make check` needs the CI age key to decrypt `secrets/test-vault.sops.yaml`; locally only the
  real-vault part (`scripts/render_env.py --check`) can pass.
- `sops` looks for age keys at `$HOME/.config/sops/age/keys.txt`; in this box `$HOME=/opt/data` but
  the key lives under `/opt/data/home/...` — a symlink at `/opt/data/.config/sops/age/keys.txt`
  fixes every `make secrets`/`make check` call.

## What makes the push path actually work (hard-won, 2026-10-27)

- **The route must grant tools.** A webhook session starts with a tiny toolset (clarify, vision,
  web_extract, web_search) — no terminal, no file tools — because the webhook adapter's
  `toolsets_for_source()` override wins over `platform_toolsets`. Set `"toolsets": ["hermes-cli"]`
  **manually** in `/opt/data/webhook_subscriptions.json` (the CLI deliberately refuses to set it, so
  an agent-created subscription cannot self-grant). The file is hot-reloaded on the next request —
  no gateway restart.
- **Never edit the subscription file while a delivery is in flight.** The reply leg re-validates the
  receipt against a digest of the *current* route; a mid-run edit makes it answer
  `Destination unavailable for webhook:v2:...` and the response (and any Telegram delivery) is
  dropped. Edit between runs only.
- **The text reply is delivered for you** (`deliver: telegram` + `deliver_extra.chat_id`), so the
  prompt must tell the agent *not* to send the summary itself — only files.
- **Files need `hermes send`.** `HOME=/opt/data /opt/hermes/.venv/bin/hermes send --to
  telegram:8663614341 'MEDIA:<path>'`. It only works once `TELEGRAM_BOT_TOKEN` is in
  `/opt/data/.env` (the token lives in the NAS vault as `stacks.hermes_agent.telegram.bot_token`,
  rendered as `HERMES_TELEGRAM_BOT_TOKEN` in `hermes-agent/.env` and mapped to `TELEGRAM_BOT_TOKEN`
  by compose — copy that value into `/opt/data/.env`, mode 600, keep one line).
- `execute_code` is BLOCKED in webhook sessions; `terminal`, `write_file`, `skills_*`, `web_*`,
  `vision_analyze`, `session_search` work.
