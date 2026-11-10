# Shopee clip modes — Telegram-only, mode-first, prompt-pack fallback (Hermes)

Status: BUILT + DEPLOYED 2026-11-10 (`c0d4a57`, `3a2ad0a`). Decisions: A = TTS in post (gameplay recipe), B = repo,
C = local state. Shot length corrected to 10 s (one Omni 1.1 Flash generation, 15 credits). Acceptance (four real
clips) NOT done yet.

## Problem (observed, 2026-11-09 / 2026-11-10)

- `flow-shopee-clips/SKILL.md` is 109 KB (over the 100 K `skill_manage` limit). Its references add
  pitfalls 55 KB, product-image-prep 41 KB and flow-browser-env 37 KB. Rules buried in that much prose
  get skipped. The fix for each skipped rule has been more prose.
- n8n `Presenter Shots` is a passive store. It ran only when the agent chose to call `shotboard.py`,
  and the agent did not call it on either real run (shelf, 11-09; shelf304, 11-10).
- The real failures are in inputs and Flow driving: ad crops used as product references, picker and
  chip verification failing over CDP, and Flow `unusual activity` rejects. One logged run passed when
  Fix submitted the same prompt and reference in his own browser. That is one run, and the cause is
  not confirmed.
- The n8n → Hermes webhook path was switched off on 2026-11-10 (`ef2e806`). Orders come in only through
  Telegram.

## Target flow (Telegram only)

```
Fix: ทำคลิป shopee + link + photos
 → [Q1 clarify] 🎮 gameplay footage / 🧑 presenter + graphic / 📦 graphic only (Flow product b-roll, no person)
 → product photo gate (all modes; no clean photo → ask, zero spend)
 → 🎮 → gameplay-clips (unchanged body) → deliver
 → 🧑/📦 → storyboard → Fix approves
        → [Q2 clarify] 📝 prompt pack per shot / 🤖 IU drives Flow
        → shots arrive (auto, or Fix's replies) → per-shot gates → review ✅/🔁
        → graphics post (always) → deliver
```

- Both questions use Hermes `clarify`. Raw Bot API inline buttons are dead clicks, because the gateway
  drops callback queries it does not own.
- Presenter without graphics is removed. Graphics are part of every Flow-mode clip.

## Components

### 1. `shopee-clip` router skill (new, small)

- Owns the trigger. Description: any Shopee clip order. Narrow the `gameplay-clips` and Flow skill
  descriptions so they read as "loaded by shopee-clip for mode X". Otherwise Hermes matches them
  directly and skips Q1.
- Covers intake (link and photos), Q1, the photo gate, `clipjob.py new`, storyboard for Flow modes, Q2,
  and hand-off. It names the next skill to load explicitly, because `related_skills` is metadata only
  (`tools/skills_tool.py`) and loads nothing.
- Size budget: SKILL.md ≤ 15 KB, enforced by a test or lint, not by a sentence.
- House rule written into it: a missed gate is fixed in code, not in prose.

### 2. `clipjob.py` — local job state

- File: `/opt/data/clips/jobs/<job>.json`. Holds mode, production (`auto` | `prompt`), shots
  (`pending → submitted → in_review → approved | regen_approved | failed`), the credit ledger (which
  shots spent credits), the fallback reason, and delivery hashes.
- Commands: `new`, `status`, `reserve` (auto-mode pacing, ≥300 s), `submitted`, `submit-failed`,
  `ingest <job> <k> <file>`, `ready` (gates), `decide`, `fallback`, `pack`, `deliver`, `close`, `cancel`.
- Ports the pure helpers from `shotboard.py`: CTA patterns, verdict, and the decision-text regex.
- Unit-tested: the state machine, the credit ledger, fallback-from-shot-k, and decision parsing.

### 3. Prompt pack (📝)

- `clipjob.py pack <job> [--from k]` sends the following for each remaining shot:
  - The reference images as photos, so Fix can save them and attach them in Flow on the phone.
  - The prompt text with a copy button.
  - A tag `[ช็อต k · <job>]` in the message text.
- Fix replies to that shot's message with the mp4. Hermes gives the agent `reply_to_text`
  (`adapter.py _reply_context`), so the agent reads the tag and runs `ingest`. The mapping does not
  depend on message ids.
- An mp4 sent without a reply → ask which shot. Never guess.
- `ingest` runs ffprobe. Below 720×1280, or a low bitrate, means Telegram mobile re-encoded it ("send
  as video"). Flag it and tell Fix once to send shots as a file.
- Inbound cap: 20 MB (public Bot API, `adapter.py` `_max_doc_bytes`). An 8 s 720p shot fits.

### 4. Auto (🤖) and fallback

- The Flow driving references move **intact** into a `flow-driver` skill that loads only in auto mode:
  pitfalls, flow-browser-env, flow-picker-dom, picker-attach-helpers, unusual-activity notes and
  session cuts. These are hard-won; do not rewrite them.
- The submit helper calls `clipjob.py reserve` itself before it clicks Start generation.
- `clipjob.py fallback <job> --reason …` triggers:
  - the first `unusual activity` card;
  - picker or chip verification failing N times (N = 2);
  - a CDP or screenshot timeout on the same step twice.

  On fallback it records which shots already spent credits and runs `pack --from <first shot not yet
  rendered>`. It tells Fix in one message with the reason, the credits spent and the shots left. A shot
  that spent credits is never re-packed unless Fix taps 🔁.

### 5. Post-production (always graphics)

- 🧑 presenter keeps the current chain: `layout_probe → presenter_fx → post_presenter → graphics_layer
  --check`.
- 📦 graphic only: **not the same chain as-is.** `layout_probe` looks for faces and a plain pastel studio
  wall. Before 📦 ships, test it on real product b-roll and adapt it or add a product-frame variant.
  `post_presenter` subtitles come from ASR of the Flow audio, so this depends on decision A.

### 6. Delivery choke point

- `clipjob.py deliver <job>` is the one sanctioned send. It does verify-clip, the hashtag gate, the
  clip-log row, `send_clip.py`, copy buttons and the cover, in that order.
- It refuses unless every shot is `approved`, the graphics report has no `FLAG:`, and the verify-clip
  pass is for this job's file (by sha256).
- `check_delivery.py` audits afterwards. Honest limit: the agent has a terminal and could still send by
  hand. Gates hold because the compliant path is the easy one, not because bypass is impossible.

### 7. Migration

- Keep these scripts as they are: send_clip, verify-clip, detect_repeats, graphics_layer, presenter_fx,
  post_presenter, make_cover, send_copy_buttons, send_photo, intake_images, flow_upload_ref,
  check_delivery.
- Archive `flow-shopee-clips` (rename it out of the skill path; do not delete it). Leave the
  `gameplay-clips` body untouched and edit only its frontmatter description.
- Remove the stale n8n intake contract from the skill text. The route is already off.

## Acceptance

1. One real 🧑 clip delivered through 📝 prompt pack, with Fix running Flow.
2. One real 🧑 clip delivered through 🤖 auto. Or, if Flow rejects it, the fallback hands over to 📝
   mid-run with no shot paid for twice.
3. One real 📦 clip delivered.
4. One 🎮 order routed through Q1 to gameplay-clips.

Test jobs do not count. Presenter Shots passed every test job and never ran for real.

## Open decisions (Fix)

- **A. Voice for 📦 graphic only:** Flow-generated narration inside each shot (a voice with no person on
  screen), or TTS added in post. Recommendation: TTS in post. Flow narration without a speaker is less
  predictable, and TTS gives exact subtitle timing.
- **B. Skill source of truth:** repo (`hermes-agent/skills/…` plus a sync script run inside the
  container from Hermes's clone), or the volume only. Recommendation: repo. That gives diffs and review,
  and Hermes already commits from its clone. Rule: edit in the repo, then sync; never `skill_manage`
  these skills.
- **C. Presenter Shots (n8n):** retire it in favour of local `clipjob.py` state. Recommendation: local
  state. Pacing and stall alerts barely apply in prompt mode, and the alerts come from the Secretary
  Bot, not the Hermes bot. Deactivate the n8n workflow only after the new path has shipped a real clip.
