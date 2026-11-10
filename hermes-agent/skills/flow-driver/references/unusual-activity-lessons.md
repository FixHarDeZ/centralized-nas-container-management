# Flow "unusual activity" Failed cards: what held up (2026-11-09)

Applies when Flow shows `Failed: We noticed some unusual activity` on a bot-driven submit.

- Stop after one retry per Chrome session. Repeated bot submits in one sitting kept failing; the rule of thumb is one attempt, then report.
- Restarting Chrome and re-logging in did not fix it by itself. One later submit passed in a fresh session, and two others failed in the same session.
- The strongest result: the same prompt and the same product reference, pasted and submitted by Fix himself in his own browser, rendered without a Failed card. When the bot keeps failing, hand Fix the prompt, the reference image and the settings to run manually, then review the returned mp4 with ffprobe and frame checks.
- Synthetic input raises the risk: JS `element.click()` for picker buttons and `Input.insertText` for prompts are not what a person does. Prefer real mouse clicks via CDP and avoid JS-triggered clicks where possible.
- Browser vault `fill` on accounts.google.com fails with "No fillable login field matched" when a stale identifier tab is open alongside the password challenge tab. Close the stale tab, then fill again.
- Do not write a cause into the state file as fact. Google does not expose the risk score, so record the observed outcome only.