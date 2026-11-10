# Run mode: when "don't ask me" still keeps the gates

Read when a user says to run a clip end to end without questions, or when the only reference
images are ads, review screenshots or crops.

## Autonomy vs gates
- "Don't ask me every step" removes PER-STEP confirmations. It does not remove the standing gates:
  storyboard approval before any generation, the multi-scene review (every raw scene shown
  before stitching), and the credit cost in any question that spends credits.
- For a multi-scene clip, the scene review is the gate. Unless the user explicitly waives it for
  THIS clip, send each raw scene for review and stop before stitching. If the user waives it,
  record the waiver in the state file and in the delivery, then run without the wait.
- If it is unclear whether a waiver was given, ask ONE question with the choice written as
  buttons: waive the scene review or keep it. Do not guess, and do not treat "keep going" as a waiver.

## Reference images that are not product shots
- A review screenshot or ad crop is not a clean product photo. Vision-check it before attaching:
  - Is the product installed in the position the shot needs (for example, on the microwave)?
    If the crop shows the part lying on cardboard, the generated product will be guessed, not copied.
  - Does it contain price, rating, UI chrome, a person or hands? Any of those disqualifies the crop.
- When the crop shows the product in a different state from the shot, say so in the question
  text with the credit cost, and ask once. An approval given with that risk stated is valid.
- Never fill a missing reference with a guessed product. If the user declines, hold at zero spend.
