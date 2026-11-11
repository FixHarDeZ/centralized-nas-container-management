---
name: flow-driver
description: Mode 🤖 of shopee-clip — drive Google Flow in Chrome over CDP for one clipjob. Load only after Fix chose 🤖 and `clipjob.py production <job> auto` is set. Not an entry point for clip orders.
version: 1.0.0
author: Hermes (IU) + Fix
license: MIT
metadata:
  hermes:
    tags: [google-flow, browser, cdp, chrome]
    related_skills: [shopee-clip]
---
# Flow driver (🤖 auto)

The browser mechanics from the retired `flow-shopee-clips` skill are kept intact in `references/`.
This file covers only how a 🤖 run is wrapped by `clipjob.py` (S = `/opt/data/skills/shopee-clip/scripts`).
The source of truth is the repo (`hermes-agent/skills/`); every sync overwrites this skill. Flow project state:
`/opt/data/clips/flow-state/<project-id>.json` (read it in step 0, write it during the run).

## Before anything
- **Read `references/flow-browser-env.md`** for the Chrome launch flags, profile, layout detection and
  download dirs. It is mandatory every session.
- The mechanics, step by step: `references/flow-steps.md` steps 0–8: project state, character pick, attaching
  references, typing the prompt, Start generation, wait, download, verify.
  - Its delivery steps 9–12 are **replaced by `clipjob.py deliver`**.
  - Its multi-scene review is **replaced by `clipjob.py ready`/`decide`**.
- Picker DOM recipes: `references/flow-picker-dom.md`, `templates/picker-attach-helpers.md`. Failure catalogue:
  `references/pitfalls.md`. Tool-call cap: `references/session-cuts.md`.

## The wrap — each step has its clipjob call
| Flow step | clipjob call |
|---|---|
| right before clicking Start generation for shot K | `S/clipjob.py reserve <job> K --wait`. Exit 4 = pacing: it slept ≤150 s (the terminal tool times out at 180 s), so run the same command again. Exit 1 = a rule refused: shot K-1 not rendered, shot K-1 in review with a failed gate (wait for Fix's ✅/🔁), or a regen Fix has not approved. **Never click Start on a non-zero exit.** |
| the submit went out (two signals: prompt cleared + button state) | `clipjob.py submitted <job> K [--credits N]` — add `--edit-id <id>` only when the real id is already known |
| the shot's tile is opened on its own `/edit/<id>` | `clipjob.py edit-id <job> K <id>` |
| Flow refused before rendering, or a Failed card | `clipjob.py submit-failed <job> K --reason "<card text>" [--credits-spent]`. With `--credits-spent` it sends Fix the 🔁 button for that shot itself |
| a picker, chip, upload or CDP step failed (overlay empty, wrong chip, screenshot timeout) | `clipjob.py trouble <job> --step <picker\|chip\|upload\|cdp\|download> --reason "…"` |
| downloaded + 3-frame vision check | `clipjob.py ready <job> K --raw <file> --frame pass\|flag:<what>` |

**Fallback is decided by clipjob, not by you.** It fires on the first `unusual activity`, the second submit
failure in the job, or the second `trouble` on the same step. When an output says `"FALLBACK": true`:
1. Stop touching Flow and close Chrome with CDP `Browser.close`.
2. Send Fix one line: the reason, credits spent, shots left (taken from the output).
3. Run `clipjob.py pack <job>`.

The shopee-clip router takes over from there as 📝. Shots that already spent credits (`credits_spent_shots`)
are never re-packed unless Fix taps 🔁. A shot still rendering (`in_flight`) may finish: if it shows up in
Flow, download it and `ready` it.

Retrying by hand after a fallback, outside clipjob, is exactly what produced the rejects. Do not do it.

## Verifying a submitted render
- A submit is confirmed by the editor opening on a NEW `/edit/<id>` holding that shot's own phrase, found by enumerating the project tiles (see `references/flow-browser-env.md` → Desktop). Never conclude "not rendered" from a tile count, the first tile, or a 15-minute poll alone.
- **A placeholder edit id that was never replaced means the submit is UNVERIFIED, not rendered.** Prove it against the payload, not the grid: the media-list RPC check in `references/flow-browser-env.md` (grep the captured project list for the shot's own phrase). When the phrase is nowhere in it, the shot never became an item — reset with `clipjob.py submit-failed <job> K --reason "…"` and NO `--credits-spent`, which returns the shot to `pending` and leaves `production=auto`, so the run can be re-driven. `reserve` refuses a shot still reading `submitted`, so an abandoned placeholder deadlocks the job; and do not run `fallback` just to hand over a pack you can send by message — once a job records a fallback it can never go back to `auto`.
- Run `submitted` without an id as soon as the submit goes out, and `clipjob.py edit-id <job> K <id>` once the tile is opened. Never invent a placeholder id and never edit the job JSON by hand: `pending-…` ids are stored as null, and the clip-log only takes real ids.
- When Fix taps 🔁 on shot K, clipjob drops shot K+1's unsent reservation. If shot K+1 already rendered, clipjob flags it (its start frame is gone) and asks Fix keep/regen itself, and `assemble-check` waits for that answer. A shot K+1 still rendering shows the same warning in its review message.

## Pace and memory
- clipjob enforces ≥300 s between submits across all jobs. Fill the wait with the review of the previous shot.
- Chrome plus Flow in this 4 GB container: close every other tab, and run no whisper or render while Chrome
  holds a heavy page.
- End of the run (or a fallback): CDP `Browser.close`, then verify `curl -s http://127.0.0.1:9222/json/version`
  returns nothing.
