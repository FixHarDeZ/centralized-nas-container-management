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

Measured on the NAS (2026-10-15, 280 rendered clips, 1,506 non-final Cards): median Card span 6.8 s, p90 9.3 s, max 17.8 s. **518 Cards (34%) exceed 7.5 s.** One Card per 8 s shot would therefore force rewrites on most clips. Rewriting after 🎞 Studio would also ship Card text the human never approved. So Cards are not shortened. Instead, a long Card gets more shots:

- Every shot is exactly **8 seconds**. `script.md` lists shots, not Cards.
- **Narrate first, plan second.** When 🎞 Studio is pressed, the bot synthesises the full narration once with edge-tts (the same single call as rendering) and measures each Card's span. Card i then gets `shots_i = ceil((span_i + 0.5) / 8)` shots. The 0.5 s margin covers join silence and the voice tail. The last Card uses `span + TAIL_PAD`.
- The planner receives the shot count per Card. A Card with two or more shots gets distinct shots of the same beat, such as another angle, a closer framing, or the next action. `validate()` checks that each Card has exactly its shot count.
- The pack shows the total shot count and expected export length (Σ shots × 8 s), because each shot costs Flow credits. If that looks too expensive, the human can press ✂️ to get shorter Cards. ✂️ goes through the **normal revise path**: prefilled feedback naming the long Cards, then the Script returns to review. The bot never rewrites approved text by itself.
- The narration audio, Card starts and shot map are saved to `/data/studio/<clip_id>/`. That directory is separate from the render workdir, which is wiped after every render, and is removed when the `clip_wait` expires or is replaced. Render reuses the saved audio, so cut points match what was measured, and edge-tts cannot fail with `NoAudioReceived` at render time.
- `/say` staleness: the saved directory records a hash of `say.json`. If the hash differs at render, the bot re-synthesises, says so in chat, and relies on `tpad` for small drift. Otherwise it reuses the saved audio.

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

Each `[SCENE n]` block is one 8 s shot, so a Card with two shots appears as two blocks. Every block repeats both `@tag` and the full `locked_prompt_tag`. The tag text is the fallback if Flow does not bind the tag. In Shop, every scene that shows the product references `@Product`, which the human creates as a Prop from the real product photos.

### Delivery

- Telegram: `script.md` sent with the existing `send_document`, followed by a message that has the pack link and character buttons. That message's id becomes the reply target in `clip_wait`.
- Dashboard: read-only page `GET /storyboard/<clip_id>`, built from the pack stored in the Manifest (`/data:ro`). It also offers `GET /storyboard/<clip_id>/script.md` as a download. Boxes, in order of use:

| # | Box | Shown |
|---|---|---|
| 0 | Project checklist: 9:16, Photorealistic preset, 1 shot per scene, 8 s | always |
| 1 | Character: portrait prompt, tag, baseline details | expanded when not ticked as created in Flow, or when invented; otherwise collapsed with "use @Nong in your existing project" |
| 2 | Product prop: tag `@Product` + download chosen photo(s) | Shop only |
| 3 | Full script with Copy + Download `script.md` | always, primary |
| 4 | Per shot: image prompt + motion, with its Card's Thai narration and measured seconds | collapsed; for regenerating a scene Autofill got wrong |
| 5 | Export checklist: S shots × 8 s = X s, muted, in order, which message to reply to | always |

Copy buttons follow the Creator Studio page conventions. The dashboard stays free of PIL and edge-tts imports.

## Return leg: Shorts via Telegram

`clip_wait` gains `kind: "studio"` with the Script snapshot, shot map (shots per Card), locale, character id and the work directory. One wait at a time and the 72 h lifetime are unchanged. A reply to an older storyboard (no `kind`) keeps the current behaviour: file the clip as finished, no cutting.

On a reply with video:

1. **Download** with `download_footage()`. Over 20 MB returns the existing "send as a normal video" message, which makes Telegram recompress. Here the footage is the whole picture, so recompression costs more than it does for a hook clip. Step 0 measures real export sizes. If they routinely exceed 20 MB, Phase 1 adds an authenticated upload for Shorts studio clips to the existing Shop API service, which already accepts 100 MiB behind nginx. The read-only dashboard stays read-only. Until step 0 answers, the Telegram path is the only one.
2. **Probe** duration with ffprobe. Let S be the total shot count.
   - Within ±0.5 s of S × 8: shot j starts at j × 8.
   - Otherwise: say `got 41.2 s but storyboard has 6 shots × 8 = 48 s` with a button **"cut evenly"**, which splits the actual length into S equal shots. Never cut silently on a guess (ADR 0005 matching rule).
3. **Cut**: Card i's footage is its consecutive shots, joined and trimmed to that Card's narration span, with audio removed (`-an`). The last Card runs to the end of narration plus `TAIL_PAD`.
4. **Render**: `render.build(script, supplied={i: seg_i}, narration=<saved audio and starts>)`. New `narration` parameter skips TTS. Cards are drawn, subtitles written, BGM mixed as today.
5. **Deliver** through the existing `deliver()`: mp4, upload button, `.srt`, Manifest with `footage_source: "flow-studio"` per Card so retention can later compare against Pexels clips.

**Experiments (ADR 0004).** An all-Flow clip is a large confounder for day-7 retention. Studio clips keep their hook variant in the Manifest, but `experiment.tally` excludes any clip whose Cards have `footage_source == "flow-studio"`, the same way explore clips are excluded. Studio clips still count toward the Gate and appear in `/stats`. Comparing Studio and Pexels clips is a separate question for later, answered from `footage_source`.

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
- Timing: mocked spans map to shot counts. 7.4 s gives 1 shot, 7.6 s gives 2, and 13.3 s gives 2. `validate()` rejects a board whose shots per Card differ from the map. ✂️ enters the revise path and never rewrites by itself.
- Cutter: ffmpeg `testsrc` of 48 s gives 6 shots. 47.6 s is accepted. 45 s is refused with the button. "cut evenly" gives 6 equal shots. A 2-shot Card's footage is shot j and shot j+1 joined, then trimmed to its span.
- Experiments: a clip with `flow-studio` footage is excluded from `tally` and still included in the Gate count.
- `say.json` hash changed: render re-synthesises. Unchanged: render reuses the saved audio.
- `render.build(narration=...)` makes no TTS call (mock asserts). A span longer than its footage holds the last frame rather than looping.
- Dashboard: `/storyboard/<id>` shows boxes per the conditions above; `WRITING_ROUTES` unchanged; invalid characters are rejected without writing.
- Shop: combined upload accepts all scenes; revision invariants hold.
- Shared-sync and the existing suite stay green.

## Phases

**Step 0: live probe before any code.** The return leg rests on Flow behaviour that only third-party tutorials describe. Those tutorials show per-panel Animate clips. None confirms that Storyboard Studio exports one stitched file. Before planning, the human runs a hand-written `script.md`, built from a real Script, through Flow and answers:

1. Does Storyboard Studio honour the STYLE header, or must each setting be set in the app?
2. Can 9:16 and 8 s per shot be set?
3. Does `@tag` bind to an existing Asset Profile?
4. Can all shots be stitched (Storyboard Studio or Scene Builder) and exported as **one muted** file? If not, how do shots leave Flow?
5. What file size does the export have, and at what length?
6. **Credits:** how many Flow credits does one 8 s Animate cost, and what is the monthly AI Pro allowance? At 1–2 clips a day plus Shop, and with 8–11 shots per clip as the measured spans imply, does the allowance cover it?

How the answers change the design:
- (4) fails → the return leg becomes per-shot upload in one batch, and the cutter is dropped.
- (5) usually over 20 MB → Phase 1 adds the Shop API upload for Shorts.
- (6) cannot cover it → mix Flow and Pexels shots per Card, as an amendment to this spec before planning.

1. Character library + pack + return leg, Shorts TH/EN, shaped by step 0.
2. A second live clip end to end; tune the template.
3. Shop combined upload and character dropdown.

Shop waits for step 2 so template changes land in one place. writing-plans starts only after the step 0 answers are in.

## Out of scope

- Any Flow automation, browser driver or extension.
- Paid video APIs.
- Long-form assembly (ADR 0006).
- Automatic YouTube upload (ADR 0001).
