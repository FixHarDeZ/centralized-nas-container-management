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
The source of truth is the repo (`hermes-agent/skills/`), and this skill is locked. Flow project state:
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
| right before clicking Start generation for shot K | `S/clipjob.py reserve <job> K --wait`. Exit 4 = pacing (it slept once already). Exit 1 = a rule refused (chaining, or a regen Fix has not approved). **Never click Start on a non-zero exit.** |
| the submit went out (two signals: prompt cleared + button state) | `clipjob.py submitted <job> K --edit-id <id> [--credits N]` |
| Flow refused before rendering, or a Failed card | `clipjob.py submit-failed <job> K --reason "<card text>" [--credits-spent]` |
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

## Pace and memory
- clipjob enforces ≥300 s between submits across all jobs. Fill the wait with the review of the previous shot.
- Chrome plus Flow in this 4 GB container: close every other tab, and run no whisper or render while Chrome
  holds a heavy page.
- End of the run (or a fallback): CDP `Browser.close`, then verify `curl -s http://127.0.0.1:9222/json/version`
  returns nothing.
