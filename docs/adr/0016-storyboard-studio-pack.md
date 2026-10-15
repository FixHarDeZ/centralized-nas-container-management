# Storyboard Studio packs: the human shoots in Flow, the bot assembles

Shop Flow Studio and the 📋 storyboard made the human loop per scene: copy a
prompt, generate, download, upload, accept. That loop was the cost.

Flow cannot be driven by code without risking the Google account. It has no
API. Every unofficial driver works against reCAPTCHA. gflow-cli cannot generate
headless or in a container. flowkit users report accounts blocked from
generating by hand after automating (flowkit #67, 2026-10). The paid Veo API is
excluded: no new spend.

## Decision

The bot meets Flow's own **Storyboard Studio** halfway. For the Cards the human
marks 🎬 (default: the hook; the rule `hook`/`none`/`all` lives in
`/config/characters.json`), it speaks the Script once, gives each Card
`ceil((span + 0.5) / 8)` shots of 8 s, and writes an English-only `script.md`
plus a copy-box page on the dashboard (`/storyboard/<clip_id>`). The human
generates and stitches in Flow and brings back **one** export. The bot cuts it
at multiples of 8 s, which was measured exact on a real export (24.000 s, cuts
at 8.0/16.0). It renders with the take it already spoke. Other Cards keep
Pexels. A wrong length (more than 0.5 s off `shots × 8`) is refused with a
"cut evenly" button, never cut on a guess (ADR 0005).

Boundaries kept: the bot still has no port (ADR 0002). Exports over Telegram's
20 MB ceiling go through one new Shop API route
(`POST /shop/api/studio-inbox/<token>`, Shop CSRF, 100 MiB cap, `ftyp` check,
no decoding) into `/output/studio-inbox`, which the poll loop collects. The
dashboard is still read-only apart from `/settings`, which now also stores the
character library (ADR 0009). The bot never rewrites approved text. ✂️ returns
the Script to review. Studio clips are left out of the hook experiment
(ADR 0004), both `tally` and `by_category`, because the footage, not the hook,
would be measured.

## As built

- The cut is re-encoded, not stream-copied: Flow exports carry a keyframe
  every 3 s, so a copy would start each Card on the wrong frame.
- Studio footage is held on its last frame (`tpad`) when the Card outlasts it,
  never looped: a loop visibly jumps back to the shot's first frame.
- The saved take is reused only while it still fits. A `/say` change since it
  was spoken, a missing file, or a start count that differs from the Card
  count all mean the renderer speaks afresh (cut points may drift slightly,
  and the bot says so).
- A 🎬 Card without a segment stops the render with a message. It is never
  quietly filled from Pexels. `render_studio` restores the Fact sheet, hook
  Variant and queued 🌏 half, which `to_idle()` cleared when 🎞 freed the bot.
- Each toggle or character change publishes a new pack version with its own
  token. Only the newest 5 versions accept an export, because an older shot
  map would cut on the wrong boundaries. A reply to either the pack message or
  its `script.md` document routes to that version.
- 📋 storyboards and 🎞 packs share the one `clip_wait` slot. Either replacing
  the other says so in chat, and a replaced pack's files are deleted.
- Files live in `/data/studio/<clip_id>/` and are deleted on YouTube upload,
  ✂️, replacement, or the 72-hour wait expiring. A clip with no YouTube
  credentials keeps them until expiry. Unclaimed inbox files go after 72 h.
- A restart puts back an export claimed (`.taken`) but not yet cut, so the
  next tick takes it again.
- Clip ids bumped on collision (`…-065-1`) are accepted.

## Unverified live

None of these have been tried on a real clip yet: Flow honouring the STYLE
header in `script.md`; `@tag` binding to a Flow Asset Profile; the Storyboard
frame aspect; whether the monthly credit allowance covers the expected use
(`FLOW_CREDITS_PER_SHOT`, default 12, is an estimate); and a web upload over
20 MB through the DSM reverse proxy, which may answer 413 before the stack's
nginx (102m) sees it. The Telegram reply (≤20 MB, a hook-only pack is about
7 MB per shot) and the LAN dashboard at `<NAS_HOST>:5071` are the fallbacks.

## Consequences

Extends 0005 (Flow footage for any Card, still human-generated) and 0006 (the
bot now consumes a Flow export for Shorts; no long-form assembly still holds).
