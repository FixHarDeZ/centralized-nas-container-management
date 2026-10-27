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

## Why Hermes pulls instead of n8n pushing (verified 2026-10-27)

- The gateway API (`/v1/*`, `/api/sessions/*`) listens on **127.0.0.1:8642 only** (`API_SERVER_KEY`
  auth, key in `/opt/data/.env`), so nothing off-box can reach it.
- An `0.0.0.0:8645` forwarder on the Hermes box was started and confirmed reachable from that box's
  own LAN IP, yet an n8n HTTP node to `http://192.168.112.2:8645/health` **timed out** — n8n
  (NAS side, `192.168.50.200`) has no route/filter to that network. Same timeout for `:8642`.
- We *can* reach n8n: `https://fixhardez.synology.me:15678/api/v1/...` with `X-N8N-API-KEY`
  works from the Hermes box (key rendered into `n8n/.env` from vault `stacks.secretary.n8n.api_key`).

So the bridge **polls n8n** (15 s tick) and injects the job into Hermes over loopback.

## Bridge (Hermes side)

`/opt/data/n8n-bridge/clip_job_poller.py` — stdlib only, run as `python3 <script>` (detached).

- reads `poller.env.json` (mode 0600: `N8N_BASE`, `N8N_KEY`, `WF_ID`, `HERMES_KEY`, `STATE`, `LOG`)
- lists `GET /api/v1/executions?workflowId=…` → `GET /api/v1/executions/{id}?includeData=true`
  (without `includeData=true` the job payload is absent) → finds `{product, link}` in the run data
- picks the newest `source=telegram` session for user `8663614341` via `GET /api/sessions`
- `POST http://127.0.0.1:8642/api/sessions/{id}/chat` `{"message": "<rendered job>"}` with
  `Authorization: Bearer $API_SERVER_KEY`
- non-2xx → retries every 15 s (up to 160 attempts = 40 min), state in `poller_state.json`
  (`seen` = injected/abandoned, `pending` = attempt counts)

**Observed behaviour:** while the target session is mid-turn the gateway answers **500
"Server got itself in trouble"** rather than 429; the same chat POST on an idle/new session returns
`200 {"status":"completed"}`. The retry loop exists precisely for that — injection lands once the
session is idle.

**Not supervised yet:** the poller dies if the Hermes container restarts. Next step is an s6
supervision entry (see skill `hermes-s6-container-supervision`).

## Diagnostics workflow

`Hermes Bridge Probe` (`0vwF1zobUF4FmYbR`, active) — `POST /webhook/hermes-probe` → HTTP GET a
health URL → responds with the HTTP result. Use it to re-test connectivity after any network or
gateway change; it is harmless and holds no credentials.

## Bring-up checklist

1. `make secrets AGE_KEY=<prod key>` → renders `n8n/.env` (needs `.venv` with `pyyaml`, and `sops`
   on PATH).
2. Import/update the workflow: `POST /api/v1/workflows` (create) + `POST /api/v1/workflows/{id}/activate`
   — `PATCH` is not allowed by the public API.
3. Start the bridge: `python3 /opt/data/n8n-bridge/clip_job_poller.py &`
4. Fire a ping job and watch `/opt/data/n8n-bridge/poller.log`.
