# Presenter Shots — per-shot state + clock for multi-shot Flow presenter clips

Workflow `n8n/workflows/Presenter_Shots.json` (live as **Presenter Shots**, id `yd3FsdXVEHSADE0D`).
Generated from `n8n/presenter-shots/core.js` by `build_workflow.py` — never edit the Code nodes in
the n8n editor; edit `core.js` + its tests, rebuild, re-import.

## Why

A presenter clip is 4–6 Flow shots. Each submit must wait ≥5 min after the previous one (Flow's
reCAPTCHA), each render takes 15–20 min, and Fix reviews every shot before stitching. That run spans
several agent turns, and the rules (pacing, start-frame chaining, "regen spends credits, ask Fix",
"no CTA before the last shot", "run detect_repeats on every shot") lived only as prose in the skill.
This workflow holds the state outside the agent and refuses out-of-order steps.

## Split of responsibilities

| Where | What |
|---|---|
| n8n `Presenter Shots` | state (workflow static data), rules (`core.js`), 5-minute stall alerts to Fix |
| Hermes `flow-shopee-clips/scripts/shotboard.py` | the only client; runs the per-shot gates where the files are; sends the shot + a reply keyboard to Telegram |
| Agent (IU) | drives Flow in the browser, vision-checks frames, writes the storyboard |
| Fix | taps ✅ ผ่าน / 🔁 gen ใหม่ under each shot |

The review buttons are a Telegram **reply keyboard**, not inline buttons: the Hermes gateway drops
callback queries it does not own, while a reply-keyboard tap arrives as an ordinary message in Fix's
DM session, so it wakes the agent with the whole run in context. The agent records it with
`shotboard.py decide --text "<button text>"`.

## Endpoint

```
POST https://<NAS_DOMAIN>/webhook/presenter-shots     (or http://<docker-host>:5678/webhook/presenter-shots on the LAN)
Content-Type: application/json
X-Clip-Token: <CLIP_INTAKE_TOKEN>        # same token as Clip Intake; empty env = everything 401
{"action": "...", ...}
```

Response: JSON body `{ok, ...}` with HTTP code 200 / 400 (bad input) / 401 (token) / 404 (no job) /
409 (rule) / 429 (pacing, `wait_s`). Rejected events never change the stored state.

## State machine (per shot)

```
pending ──reserve──▶ submitting ──submitted──▶ submitted ──ready──▶ in_review ──decide approve──▶ approved
   ▲                     │                        │                    │
   │      submit_failed (no credits) ◀────────────┘                    └─decide regen──▶ regen_approved ──reserve──▶ …
   │                                     submit_failed (credits spent) ──▶ failed ──decide regen──▶ regen_approved
```

Rules (`core.js`):

- `reserve` = "I am about to click Start generation". ≥300 s since the last reserve of **any** job
  (`test-*` jobs have their own clock), else 429 + `wait_s`.
- Shot k>1 needs shot k−1 `in_review` or `approved` (its last frame is the start frame).
- A shot that has rendered (`in_review`) or failed after spending credits can be submitted again only
  after Fix's `regen` decision.
- `assemble_check` = 200 with the files in shot order only when every shot is `approved`.
- Closed jobs older than 14 days are pruned on the next `create_job`.

Stall tick (every 5 min, **read-only** — it never writes static data, so it cannot clobber a webhook
execution): alerts Fix via the Secretary Bot when a reservation is unconfirmed for 10 min, a submitted
shot has no result after 45 min, or a job with unsent shots sat idle 30 min (or everything is approved
but not assembled). Each alert fires once when its threshold is crossed, then hourly. A shot waiting on
Fix's review never alerts.

## Build / test / deploy

```bash
node --test n8n/presenter-shots/                         # core + generated Code nodes (n8n globals mocked)
python3 n8n/presenter-shots/build_workflow.py            # regenerate the workflow JSON
uv run --with pytest pytest -q tests/test_presenter_shots_workflow.py   # drift test
./scripts/n8n_import.sh n8n/workflows/Presenter_Shots.json            # upsert by name (or PUT /api/v1/workflows/{id})
```

Settings: `saveDataSuccessExecution: none` (the tick runs 288×/day), errors saved,
`errorWorkflow` = Secretary Error Alerter. Static data persists without saving execution data
(verified live 2026-11-09).

## Verified live (2026-11-09)

- no / wrong token → 401 on the public URL; LAN URL works from the Hermes container.
- `test-live-1`: chaining 409, reserve 200, submitted, ready, second attempt 409 (credit guard),
  pacing 429 `wait_s 298`, regen 200, assemble 409 while a shot is pending.
- `test-sb` via `shotboard.py`: CTA gate caught "ลิงก์อยู่ใต้คลิป" in a non-final shot (whisper small
  spells it "ลิ้งอยู่ต้ายคลิป" — patterns are loose on purpose), review message with the reply keyboard
  delivered to Telegram (message 8080).
- Stall tick: `test-tick2` reserved 09:05:44 UTC, never confirmed → tick 09:20:15 sent
  `submit_unconfirmed` through the Secretary Bot (Telegram message 135); ticks at 09:10/09:15 stayed
  quiet. Ticks run at :x0:15 / :x5:15.
- Static data survives a `PUT /api/v1/workflows/{id}` (open jobs still listed after the re-import).
