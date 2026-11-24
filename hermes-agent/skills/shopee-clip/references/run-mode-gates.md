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

- **Two jobs at once: a 📝 approval for job B while job A is mid-run = `new` + `pack B` NOW (two calls), then back to A.** Fix renders B's shots in his Flow while A's post runs. ps2-hdd-175-pres 11-24: approved 11:50, packed 13:09 after the ✋ job delivered — 78 min with Fix holding an approved board and nothing to render.

## Board stamp
- Run `clipjob.py board <job>` right after the board message goes out and BEFORE the approval clarify — every
  board sent, a revised board too (the newest stamp counts).
- Flow `new` refuses when the job has no intake/board record, and when `state.db` holds no reply from Fix AFTER
  the stamp (his message, or an answered `clarify`). A last answer meaning แก้/ยกเลิก/เลิกทำ/พักงาน/ไม่ผ่าน is
  refused too. An unreadable db is recorded as `board.unverified`, not refused.
- A message Fix sent BEFORE the stamp is not an approval, whatever it says: it was queued while the intake turn
  ran (plaid 11-23: "ไอยูทำใน flow ให้เลยนะ" typed before the board existed, replayed after it, 60 cr spent on a
  board he never saw). Ask the clarify and wait.
- **Stamped late — the stamp went out AFTER Fix already answered the approval clarify** (you sent the board,
  asked, got the tap, and only then ran `board`): `new` refuses with `no reply from Fix since the board went out at
  <time>` although his approval is real, because the gate can only see replies newer than the stamp. Do NOT re-run
  `board` (it moves the stamp even later, still after his answer) and never hand-edit the job JSON. Recovery = ONE
  short confirmation clarify — a single line naming the board and the credit total with ผ่าน / แก้ / ยกเลิก buttons;
  his answer lands after the stamp and `new` passes. That is the allowed second ask of the same approval, not a new
  question, and it costs zero while unanswered. Prevention: `board` belongs in the same breath as the send, before
  the approval clarify is even composed.

## Reference images that are not product shots
- A review screenshot or ad crop is not a clean product photo. Vision-check it before attaching:
  - Is the product installed in the position the shot needs (for example, on the microwave)?
    If the crop shows the part lying on cardboard, the generated product will be guessed, not copied.
  - Does it contain price, rating, UI chrome, a person or hands? Any of those disqualifies the crop.
- When the crop shows the product in a different state from the shot, say so in the question
  text with the credit cost, and ask once. An approval given with that risk stated is valid.
- Never fill a missing reference with a guessed product. If the user declines, hold at zero spend.

## Close-out with no clip (router step 12b)
Fix orders the skip ("ข้ามทุก step ส่ง hashtag + ปักตะกร้า จบงาน") while
   `status` shows no shot file: `deliver` cannot run, so never stage or imply a clip. Run
   `S/send_copy_buttons.py "<tags>" "<link>" [chat_id] "<label>"` directly — tags per `templates/hashtags.md`
   gates, link must be https (exit 0 = both buttons echoed = verified) — then
   `clipjob.py cancel <job> --reason "<his order>; no clip produced, 0 credits"`. One message reports:
   buttons message_id, that no clip exists, `spent_shots`, and that prompts/refs stay in the workdir for a
   re-order. His explicit skip waives the pipeline, not the honesty gates — do not re-ask for the videos.

## Talking to Fix: detail
- **A real `FLAG` needs his call: ask once with `clarify`, then end the turn and wait.** An unanswered clarify blocks the run for its whole timeout, so re-asking the same question stalls it twice — report the flag with its frame time and wait for his reply instead of passing `--ack` as if he had chosen.
- **Pre-flight with `deliver` before asking anything.** It validates the whole package in one output — flags, hashtags, gfx, cover file, shot approval, verify — and a refusal sends NOTHING: clear the mechanical refusals yourself, then put only the remaining flags into ONE clarify. A clean pass ships the clip, so pre-flight only when that is the intent; asking before it buys a second stall for the next blocker.
- The senders parse no flags — `S/send_status.py "<line>"` posts its FIRST argument verbatim as the message body, so probing one with `--help` or any flag posts that literal text to the chat. Read the script's docstring instead of running it to ask what it does.

## Re-send of an already-delivered package
12c. **Re-send of an already-delivered package** (`ขอคลิป hashtag และปักตะกร้า`, `สรุปอีกรอบ`): resolve WHICH
   clip first — the newest `clip-log.jsonl` row only when one job landed today; with several, scroll recent
   sessions (`session_search`) for the one the last summary named, never guess among the day's jobs. Read the
   job's `delivery.sent` (`clip`/`copy_buttons`/`cover`) to see what already went out, then re-run
   `S/send_copy_buttons.py "<tags>" "<link>" 8663614341 "<product>"` directly — tags from the clip-log row,
   `link` from the job JSON; exit 0 with both buttons echoed = verified. Attach `<workdir>/final.mp4` only when
   he asks for the คลิป itself (cleanup already deleted the Downloads copy). The recap comes from the
   clip-log row — gates passed once, no re-check — and the day's other clips are offered in one line, not
   dumped.
