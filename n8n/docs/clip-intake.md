# Clip Intake (Hermes) — n8n → Hermes clip request bridge

Workflow `n8n/workflows/Clip_Intake.json` (live as **Clip Intake (Hermes)**, id `IYayiImdn0Jd5yMS`).
Purpose: Fix (or anything) POSTs a clip job to n8n; Hermes picks it up and runs the
`flow-shopee-clips` pipeline end to end, delivering the clip + hashtags + basket link to Telegram.

## Endpoint

```
POST https://fixhardez.synology.me/webhook/clip-request     # production (workflow must be active)
POST https://fixhardez.synology.me/webhook-test/clip-request # test URL while listening in the editor
Content-Type: application/json
```

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

Response is immediate: `200 {"status":"accepted","job":{...}}` (`Respond accepted` runs before the
rest of the workflow). The workflow stores the job in its own execution data —
`saveDataSuccessExecution: all` is required, otherwise a successful run stores nothing to read back.

## Delivery path — push model (since 2026-10-27)

```
POST /webhook/clip-request
  -> Clip Request (webhook) -> Record job (code) -> Respond accepted (200, immediate)
  -> Sign for Hermes (code: HMAC + POST to Hermes) -> Log
```

The `Sign for Hermes` Code node signs the job and POSTs it to Hermes' **webhook platform**:

- Gateway side: `platforms.webhook` in `/opt/data/config.yaml` — binds `0.0.0.0:8644`, route
  `clip-request`, secret `${HERMES_WEBHOOK_SECRET}` (from `hermes-agent/.env`).
- Network: the hermes-agent stack publishes `8644:8644`; homepage nginx proxies
  `https://fixhardez.synology.me/webhooks/*` -> `http://host.docker.internal:8644/webhooks/*`.
- Auth: `X-Webhook-Timestamp` = unix seconds, `X-Webhook-Signature-V2` =
  `hex(HMAC_SHA256(secret, "<timestamp>.<body>"))`. Replay window 300 s.
- Secret: vault `stacks.secretary.n8n.hermes_webhook_secret`, rendered into **both** `n8n/.env`
  (signing) and `hermes-agent/.env` (validation) by the two stack manifests.
- On accept the gateway answers `202 {"status":"accepted", ...}` and runs the route's agent turn in
  the background (`deliver: telegram` chat `8663614341`, `mirror_to_session: true`), so n8n is never
  blocked by the length of the clip run and failures surface in n8n's execution log + Error Alerter.

## n8n env requirements (all three mandatory)

Set in `n8n/docker-compose.yml` `environment:` (the stack has **no** `env_file`, so values must be
interpolated from `n8n/.env`):

- `HERMES_WEBHOOK_SECRET=${HERMES_WEBHOOK_SECRET}` — the HMAC secret
- `N8N_BLOCK_ENV_ACCESS_IN_NODE=false` — Code node `$env` is blocked by default
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

Signed ping (works from anywhere that can reach the NAS, or from the Hermes box itself):

```python
import hmac, hashlib, json, time, urllib.request
secret = open('/opt/data/centralized-nas-container-management/n8n/.env').read().split('HERMES_WEBHOOK_SECRET=')[1].split()[0]
body = json.dumps({"product": "PING (ห้ามทำคลิป แค่ตอบว่า PONG)", "link": "https://example.invalid",
                   "duration_s": 10, "category": "gadget", "images": [], "note": "test"}, ensure_ascii=False)
ts = str(int(time.time()))
sig = hmac.new(secret.encode(), f"{ts}.{body}".encode(), hashlib.sha256).hexdigest()
req = urllib.request.Request("http://127.0.0.1:8644/webhooks/clip-request", data=body.encode(), method="POST",
    headers={"Content-Type": "application/json", "X-Webhook-Timestamp": ts, "X-Webhook-Signature-V2": sig})
print(urllib.request.urlopen(req, timeout=30).read().decode())   # -> {"status": "accepted", ...}
```

Then check the n8n execution (`GET /api/v1/executions/{id}?includeData=true`) — `Sign for Hermes`
must return `hermes_status: 202` — and `/opt/data/logs/gateway.log` for
`[webhook] POST ... route=clip-request` + `delivery mirrored into telegram:8663614341 session`.

## Diagnostics workflow (kept)

`Hermes Bridge Probe` (`0vwF1zobUF4FmYbR`, active) — `POST /webhook/hermes-probe` → HTTP GET a
health URL → responds with the HTTP result. Useful to re-test n8n's outbound connectivity after any
network or gateway change; it is harmless and holds no credentials.

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
4. Fire a signed ping (snippet above) and watch the n8n execution + `/opt/data/logs/gateway.log`.

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
