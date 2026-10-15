# Storyboard Studio Pack

Date: 2026-10-15. Status: design approved by user in conversation; spec awaiting user review. No implementation yet.

## Problem

Shop Flow Studio and the 📋 storyboard both make the human repeat a loop per scene: copy prompt, download reference, generate in Flow, upload, accept. That loop is the effort the user wants removed. Automating Flow itself is ruled out: Flow has no API, every unofficial driver (flowkit, gflow-cli, Chrome extensions) runs against reCAPTCHA, gflow-cli cannot generate headless or in a container, and flowkit users report Google accounts blocked from manual Flow generation after automation (flowkit issues #58, #67, #74, September–October 2026). The paid Veo API is out because the user requires no new spend.

## Outcome

Use Google Flow's own **Storyboard Studio** (Script → Assets → Storyboard) as the generation surface. shorts-factory produces one pack per clip that the human pastes or uploads in a few steps, then takes back **one** exported, muted, stitched video and turns it into a finished Short with Thai narration, subtitles, music (and, for Shop, the price card).

Applies to both Shorts (TH/EN) and Shop. Everything is free: mimo (already used), edge-tts, Flow credits inside the user's existing subscription.

Per-clip human steps, target:

1. Telegram: pick Topic → review Script → press **🎞 Studio**.
2. Bot sends `script.md` plus a link to the dashboard pack page.
3. Flow: run through the project checklist, upload or paste `script.md`, Autofill, Animate every shot, stitch, export muted.
4. Reply to the pack message in Telegram with the mp4. The bot returns the finished clip with the usual upload button.

## One-time setup: recurring characters

A character library replaces asking about the character on every clip.

- `/settings` gains a Characters section. Each character has `id`, `tag` (e.g. `@Nong`), Thai description, optional English description, and a checkbox "Asset Profile created in Flow". The library also stores a default per channel: `{th, en, shop}`, each a character id or empty.
- The first time a character is used, the bot sends the English portrait prompt. The human generates the portrait in Flow and creates an Asset Profile with that tag in the Flow project used for clips, then ticks the checkbox. Later clips reuse the Asset Profile.

### Storage

The dashboard holds no mimo key (ADR 0007), so it cannot translate. The bot mounts `/config` read-only. Each file therefore has one writer:

| File | Writer | Content |
|---|---|---|
| `/config/characters.json` | dashboard, inside existing `POST /settings` | characters + per-channel defaults |
| `/data/character_tags.json` | bot | English `locked_prompt_tag` and portrait prompt, keyed by a hash of the Thai description |

If the English field is filled, it is used verbatim and nothing is translated. Otherwise the bot translates once and caches by hash, so the English text stays identical across clips until the Thai description is edited.

New module `app/characters.py`, following `app/model_choice.py`: read on every call (no restart), validate before writing, missing file or unknown id means "no recurring character". Unknown default falls back to the existing 🤖 behaviour. `WRITING_ROUTES` stays `{"/settings"}`.

## The pack

### Planning

🎞 Studio reuses `storyboard.py`: the same model call, `lock_to_script()` and `validate()`, with a new output format. The character comes from the channel default without a question. The pack message carries buttons to switch character, using the existing `sbchar` token mechanism:

`[@Nong ✓] [@Other] [🤖 invent] [🚫 no person]`

Pressing a different choice re-plans the board, which costs one more mimo call. The existing 📋 button (Ingredients to Video, one message per scene) stays unchanged.

When a library character is used, the board takes the cached `locked_prompt_tag` as given (`OWN` mode with fixed English text) rather than letting the model rewrite it.

### Timing rules (what makes the return leg deterministic)

- Every scene is exactly **8 seconds**, one shot per scene. Shorts already have 5–7 Cards, so a clip comes back at 40–56 s.
- At pack time the bot synthesises the full narration once with edge-tts (the same single call as rendering), measures each Card's span, and rejects any Card over **7.5 s**. A rejected Card is rewritten by mimo within the existing deadline. The 0.5 s margin covers join silence and the voice tail.
- The narration audio and Card starts are saved to `/data/work/<clip_id>/` and reused at render, so cut points match exactly what was measured. Reuse also avoids an edge-tts `NoAudioReceived` failure at render time.

### `script.md`

English only, and no dialogue or voiceover text. Thai narration in the file could make Veo animate speech. Structure (template held in one place in `storyboard.py` so the first live test can tune it):

```markdown
# <title>

STYLE: Photorealistic cinematic, vertical 9:16, one shot per scene, each shot exactly 8 seconds.
No dialogue, no voiceover, no on-screen text, no subtitles, no watermark, no UI, no split-screen.
Keep clean negative space in the centre of the frame for captions added later.

CHARACTERS: @Nong — <locked_prompt_tag>
PROPS: @Product — the product in the reference photos   (Shop only)

[SCENE 1]
INT. <PLACE> - <TIME>
<action naming @Nong and the locked_prompt_tag>
CAMERA: <motion>, 8 seconds.
```

Every scene repeats both `@tag` and the full `locked_prompt_tag`. The tag text is the fallback if Flow does not bind the tag. In Shop, every scene that shows the product references `@Product`, which the human creates as a Prop from the real product photos.

### Delivery

- Telegram: `script.md` sent with the existing `send_document`, followed by a message that has the pack link and character buttons. That message's id becomes the reply target in `clip_wait`.
- Dashboard: read-only page `GET /storyboard/<clip_id>`, built from the pack stored in the Manifest (`/data:ro`). It also offers `GET /storyboard/<clip_id>/script.md` as a download. Boxes, in order of use:

| # | Box | Shown |
|---|---|---|
| 0 | Project checklist: 9:16, Photorealistic preset, 1 shot per scene, 8 s | always |
| 1 | Character: portrait prompt, tag, baseline details | expanded when not ticked as created in Flow, or when invented; otherwise collapsed with "use @Nong in your existing project" |
| 2 | Product prop: tag `@Product` + download chosen photo(s) | Shop only |
| 3 | Full script with Copy + Download `script.md` | always, primary |
| 4 | Per scene: image prompt + motion, Thai narration and measured seconds | collapsed; for regenerating a scene Autofill got wrong |
| 5 | Export checklist: N × 8 s = X s, muted, in order, which message to reply to | always |

Copy buttons follow the Creator Studio page conventions. The dashboard stays free of PIL and edge-tts imports.

## Return leg: Shorts via Telegram

`clip_wait` gains `kind: "studio"` with the Script snapshot, scene count, scene seconds, locale, character id and the work directory. One wait at a time and the 72 h lifetime are unchanged. A reply to an older storyboard (no `kind`) keeps the current behaviour: file the clip as finished, no cutting.

On a reply with video:

1. **Download** with `download_footage()`. Over 20 MB returns the existing "send as a normal video" message.
2. **Probe** duration with ffprobe.
   - Within ±0.5 s of N × 8: cut at 0, 8, 16, …
   - Otherwise: say `got 41.2 s but storyboard has 6 scenes × 8 = 48 s` with a button **"cut evenly"**, which splits the actual length into N equal parts. Never cut silently on a guess (ADR 0005 matching rule).
3. **Cut**: scene i from i × 8 for that Card's narration span, audio removed (`-an`). The last Card runs to the end of narration plus `TAIL_PAD`.
4. **Render**: `render.build(script, supplied={i: seg_i}, narration=<saved audio and starts>)`. New `narration` parameter skips TTS. Cards are drawn, subtitles written, BGM mixed as today.
5. **Deliver** through the existing `deliver()`: mp4, upload button, `.srt`, Manifest with `footage_source: "flow-studio"` per Card so retention can later compare against Pexels clips.

If a Card's span is longer than its footage by a little, hold the last frame with `tpad`. Never loop: `-stream_loop` would visibly jump back. This applies only to supplied studio segments; the Pexels path is unchanged.

| Failure | Behaviour |
|---|---|
| download or probe fails | say so; `clip_wait` stays; resend works |
| render fails | segments and audio stay in the work dir; 🔁 button re-renders without resending |
| saved narration missing | say so, synthesise again, rely on `tpad` for small drift |
| `clip_wait` expires | existing expiry message |

## Return leg: Shop via Shop Studio

Shop is a web workflow with a 100 MiB upload, so the combined file is uploaded on the job page ("Upload combined clip from Storyboard Studio"), not through Telegram.

- The job page gets a character dropdown, defaulting to the `shop` channel default. 🚫 is allowed for hands-and-product clips.
- The worker applies the same probe/cut rules and stores each segment as that scene's media version through the existing media path, then marks every scene accepted in one action. The render then runs the existing path, with price card and `#ad`.
- Affiliate rule stays: nothing here touches `job.revision` outside the existing media/approval paths.
- Compose: `shop` and `shop-worker` mount `/config:ro` to read the library.

## ADR

Add ADR 0016 "Storyboard Studio pack". It extends 0005: Flow footage for every Card, assembled from one stitched export, still generated by the human. It also extends 0006: the bot now consumes a Flow export for Shorts. 0006's "no long-form assembly" stays. Record why Flow automation was rejected: no headless path, account blocks reported in flowkit #67.

## Testing

Unit tests, in the image, no network:

- `characters`: validate/save/load; per-channel defaults; unknown id falls back to 🤖; invalid input writes nothing.
- `script.md`: no Thai characters; every scene contains `@tag` and the full `locked_prompt_tag`; STYLE line contains 9:16, 8 seconds and no dialogue; no narration text present; Shop scenes reference `@Product`.
- Timing: with mocked audio durations, a Card over 7.5 s triggers a rewrite.
- Cutter: ffmpeg `testsrc` of 48 s gives 6 segments; 47.6 s accepted; 45 s refused with the button; "cut evenly" gives 6 equal segments.
- `render.build(narration=...)` makes no TTS call (mock asserts). A span longer than its footage holds the last frame rather than looping.
- Dashboard: `/storyboard/<id>` shows boxes per the conditions above; `WRITING_ROUTES` unchanged; invalid characters are rejected without writing.
- Shop: combined upload accepts all scenes; revision invariants hold.
- Shared-sync and the existing suite stay green.

Live acceptance (human, one real clip) answers what the docs could not:

1. Does Storyboard Studio honour the STYLE header?
2. Can 9:16 and 8 s per shot be set?
3. Does `@tag` bind to an existing Asset Profile?
4. Can the stitched video be exported muted?
5. What file size does a 48 s export have?

Adjust the template, and if needed the checklist boxes, from those answers before Phase 2.

## Phases

1. Character library + pack + Telegram return leg, Shorts TH/EN.
2. Live acceptance on one real clip; tune the template.
3. Shop combined upload and character dropdown.

Shop waits for step 2 so template changes land in one place.

## Out of scope

- Any Flow automation, browser driver or extension.
- Paid video APIs.
- Long-form assembly (ADR 0006).
- Automatic YouTube upload (ADR 0001).
