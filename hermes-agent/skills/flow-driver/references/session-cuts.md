# Session cuts and resume (Flow clip runs)

Hermes caps tool calls per turn, and a full clip run routinely exceeds that cap. The turn then ends with "maximum number of tool-calling iterations" and no error. That is NOT a Flow failure, and NO credits were lost.

- All DOM state (chips, uploads, prompt text) survives as long as Chrome is alive. On a cut, report the exact resume point and DO NOT close Chrome.
- Resume next turn with `page_info()` and re-read the state. Do not assume the state from the last turn.
- An open overlay menu is page state too. A `Download media` menu left open survives into the next session, so a cut mid-download resumes as "re-hit-test the 720p item with one `click_at_xy`", not as a re-open of the editor. Name in the resume report which overlay was open and where its target sat.
- The cap is `agent.max_turns` in `/opt/data/config.yaml` (set to 100; default 20). Raising it does not rescue the current session: `hermes config set agent.max_turns <n>` applies only from the next session. Resume the cut run rather than expecting a longer leash mid-flight. Raising the cap in the middle of a run needs a Hermes restart, which costs the open browser and its chips, so it is Fix's call.
