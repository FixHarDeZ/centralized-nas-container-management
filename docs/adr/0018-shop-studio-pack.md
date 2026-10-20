# Product Clips can be made as Studio packs: Flow only, the character speaking

Status: accepted (2026-10-20). Amends 0015 (Product Clips), 0016 (Studio
packs) and 0017 (characters speak) for Product Clips.

## Context

The owner makes Shorts with 🎞 Studio packs and 🗣. They want Product Clips
(Shopee affiliate) made the same way, from both the Telegram `/shop` Brief and
the Creator Studio web job. Three constraints were set in chat:

- Flow only, no Pexels.
- The character always speaks.
- The product photos go into Flow as Ingredients, and there is no price end
  card.

## Decision

- A Pitch becomes a pack with one shot per beat plus the closing line as a shot
  (`app/shop_studio.py`, shared by both front ends). Every shot is Flow and
  speaks: 🗣 is forced, 🚫 is refused, and there are no 🎬/🖼 toggles.
- The product is `@Product`: an Asset Profile the human makes from the Brief's
  photos, which the pack page serves. Scene prompts name it and never describe
  it. The photos are the product.
- Lines too long for a 10 s shot are condensed under Shop's rules, not the
  Shorts defaults:
  - digits stay digits, and every number comes from the Brief;
  - no Latin and no "ครับ";
  - the subtitle stays the line word for word, at most two lines.
- Render keeps Shop's look (badge, burned-in subtitle at ~75 %) over each
  shot's own footage and voice. There is no TTS in the mix and no end card.
  The output is filed and captioned like any Product Clip. There is still no
  Manifest, history or Experiment (0015).
- Telegram: the pack takes the one `clip_wait` slot as `kind: "studio"` with a
  `product` record. The Brief closes and the bot goes idle. Everything ADR 0016
  built for the slot (inbox, reply, uneven/cut-evenly, expiry, adopt) carries
  it unchanged. ↩️ reopens the Pitch review.
- Creator Studio web (phase 2, same day): a job `mode: studio` and
  `character` on the product form.
  - The worker plans the pack (3-7 scenes; studio only allows 7). Page edits
    cannot change what is said.
  - One export upload (asset kind `export`) is cut by a fenced `cut_export`
    command into each scene's video and voice assets. It is refused when
    uneven unless the human asks to cut evenly.
  - Render branches in `build_snapshot` to the same `shop_studio` path the
    bot uses. n8n dispatch and per-scene acceptance are unchanged.
  - The shop API mounts `/config` read-only to list the characters.

## Consequences

- Veo may redraw packaging text or logos. A human checks every shot. A wrong
  label means regenerating that shot.
- A pack costs 12 credits per 8 s shot or 15 per 10 s shot, for beats + 1
  shots.
- The library has no gender field, and the Pitch is written as a woman. An
  invented character is told to be a woman. Both library characters today are
  women.
- Unverified live: whether two Asset Profiles (character + product) bind in
  one Storyboard Studio scene, whether Veo says prices right, and whether short
  beats in 8 s shots grow filler words.
