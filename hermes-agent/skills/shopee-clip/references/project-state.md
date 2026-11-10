# Project state + clip log — the two files that stop re-discovery every run

Both live inside the skill so they survive sessions, browser restarts and
workspace churn (the browser `workspace/` path changes every session — never
store state there).

## 1. Per-project state: `/opt/data/clips/flow-state/<project-id>.json`

Read it in **step 0**, before touching the browser. Write it back after any
change (new opened `/edit` id, new character used, new settings saved).

```json
{
  "project_id": "b618e7a8-...",
  "project_name": "Shopee Affiliate",
  "updated": "2026-10-26",
  "video_defaults_saved": { "aspect": "9:16", "x": "x1", "model": "Omni 1.1 Flash" },
  "confirm_before_generating": "Never",
  "character_roster": ["น้องมิ้นท์", "น้องมิลค์", "น้องมายด์", "น้องมุก", "น้องพีช", "น้องออม"],
  "last_character_used": "น้องมุก",
  "known_edit_ids": ["1d10756a-6536-408c-9d11-3518e5efbafd"],
  "last_clip": { "date": "...", "product": "...", "category": "...", "edit_id": "...", "sha256": "...", "hook_id": "..." },
  "stale_agent_instruction": "what the drawer ACTUALLY shows now — Fix edits it himself, so re-read instead of assuming"
}
```

Why it exists: `/edit` ids **cannot be enumerated from any grid** (tiles carry
no `href`); the id only exists once you OPEN a tile. Keeping the ids you have
actually opened turns "is this the new clip?" from three browser round-trips
into one negative check — the two-sided text test only has to rule out ids you
already know, not the whole project history.

Rules
- `known_edit_ids` grows every time `page_info().url` shows an id you opened —
  append it, never re-derive it.
- `character_roster` is re-read from the sidebar's Characters page whenever a
  run shows a mismatch (characters can be added/retired); `last_character_used`
  supports ordering, but the pick itself stays RANDOM unless Fix names one.
- **Never re-roll the random pick from the picker's Characters list.** That list
  is windowed/stale: on 2026-11-06 it showed only 6 of the 12 roster names
  (เนย, คอรัล, มิลค์, มุก, ออม, มิรา), the rolled น้องพลอย came back
  `NOTFOUND`, and re-rolling over the visible six silently shrank the pool to
  half the roster — which biases later clips toward whoever happens to be
  listed. Roll over the roster in `/opt/data/clips/flow-state/<project-id>.json`; when that name is
  not in the picker, SCROLL the list and cross-check the sidebar's Characters
  page (a short picker list is stale, not a missing character) before
  substituting anyone, and say in the delivery that a substitution happened.
- `video_defaults_saved` records the Agent-settings write from step 5, so a
  later run does not re-open the drawer just to confirm it. **The inline
  `Settings trigger` panel is a different control and its tiles do NOT track
  the current order — the seconds AND the x1–x4 count come back stale, and the
  `x` saved in this file did not stop the panel opening on `x2` — so the only
  trustworthy read is the credits line: it must equal duration × rate ×
  generation count (Omni Flash 720p ≈ 1.5 cr/s; `8s · x2 · 24 credits` is
  8 × 1.5 × 2), i.e. exactly 15 for a 10 s x1 order. Adjust every tile until
  it lands there, and quote only that final figure. Read checked state off
  `mat-button-toggle`'s `className`, never with
  `querySelectorAll('mat-button-toggle-checked')` — that is a CLASS, not an
  element name, so it returns `[]` while a toggle IS selected and reads as
  "nothing checked".**

## 2. Clip log: `/opt/data/clips/logs/clip-log.jsonl` (one JSON object per line, append-only)

Append a row **in the delivery step** (step 9), before sending the message.
It is the basis for hook rotation (which `hook_id` is least-recently-used for
that category) and the only record of what actually shipped.

```json
{"date":"2026-10-26","product":"LEGO Batman: Legacy of the Dark Knight (Switch 2)","category":"game","character":"น้องมุก","edit_id":"1d10756a-...","sha256":"0f77...","hook_id":"game-1","hashtags":"#LEGOBatman ...","duration_s":10.005,"credits":null,"notes":"ad-graphic crop: cut price + QR + IMMERZIV"}
```

Fields
- `category` must be one of the pools in `templates/hashtags.md` (`game`,
  `gadget`, `home`, `beauty`, `fashion`, `food`) — it selects both the hook
  rotation and the hashtag pool.
- `hook_id` is the id chosen from `templates/hooks.md` for this clip.
- `credits` is the figure actually read off the confirm card / settings panel;
  `null` when agent mode never rendered one — never invent it.
- `notes` records crop decisions (what promo elements were cut) and any
  listing/art mismatch, so a regenerate can pick up where this left off.

Read the file with a real parse (`json.loads` per line), never by eyeballing:
counts and "least recently used" decisions must come from the data.

Editing the log or the state file: build the row as a Python dict and write it with `json.dumps(row, ensure_ascii=False)`. Patching a note into an existing line by string replace is what broke the file once: a raw double quote inside a value makes that line unparseable, and every later `json.loads` over the log fails. After any edit, re-parse every line before the next run.

## 3. See also — depth files opened when the run hits their point
- `references/queue-mode.md` — the moment a SECOND clip order is in play:
  crop/upload ordering (one file-input call serves the whole queue), prompt
  prep inside the previous clip's render window, and character exclusion
  across the whole sitting, not just the last clip.
- `references/frame-check.md` — during step 8's pixel gate: the defect
  classes that decide a verdict (price-shaped sticker, zoom-scope when date
  digits disagree) and the workflow when `vision_analyze` fails at the
  provider level mid-run.
- `references/run-gates.md` — at steps 5–9: proving a submit actually
  registered (prompt-text probe, timeout-vs-empty, `Failed to render response`
  vs a real `Failed` card), the download/verify gates, the credit-question
  gates before any spend, and the abort / partial close-out checklist.

