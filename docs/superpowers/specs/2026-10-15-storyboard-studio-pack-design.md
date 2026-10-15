# Storyboard Studio Pack

Date: 2026-10-15. Status: design approved by user in conversation. Step 0 live probe mostly answered (see end). Spec awaiting user review. No implementation yet.

## Problem

Shop Flow Studio and the 📋 storyboard both make the human repeat a loop for every scene: copy the prompt, download the reference, generate in Flow, upload, accept. The user wants that loop gone.

Automating Flow is ruled out:
- Flow has no API.
- Every unofficial driver (flowkit, gflow-cli, Chrome extensions) runs against reCAPTCHA.
- gflow-cli cannot generate headless or inside a container.
- flowkit users report Google accounts blocked from manual Flow generation after automation (flowkit issues #58, #67, #74, September–October 2026).

The paid Veo API is also out, because the user requires no new spend.

## Outcome

Google Flow's own **Storyboard Studio** becomes the generation surface. It runs Script → Assets → Storyboard frames, then Animate and Scenes export. shorts-factory produces one pack per clip. The pack holds only the Cards the human chose to make in Flow. The human takes back **one** stitched export, and the bot turns it into a finished Short with Thai narration, subtitles and music (and, for Shop, the price card). Cards not made in Flow keep Pexels footage.

Applies to Shorts (TH/EN) and Shop. Everything is free: mimo (already used), edge-tts, and Flow credits inside the user's existing AI Pro subscription.

Per-clip human steps, target:

1. Telegram: pick a Topic, review the Script, press **🎞 Studio**. Adjust Flow/Pexels per Card if wanted (default: hook = Flow).
2. Bot sends `script.md` plus a link to the dashboard pack page.
3. In Flow: upload or paste `script.md`, Autofill, Animate each shot from the pack's copy boxes, stitch in Scenes, export.
4. On the pack page (same desktop browser), upload the export. The bot renders and returns the finished clip in Telegram with the usual upload button.

If every Card is Pexels, steps 2–4 vanish and the bot renders straight away, as 🎬 does today.

## Footage source per Card

Each Card's footage source is either 🎬 Flow or 🖼 Pexels.

- **Default:** Card 1 (the hook) is Flow and the rest are Pexels. The default is editable in `/settings` and stored with the character library.
- **Telegram:** the pack message carries one toggle button per Card, plus "✅ all Pexels — render now":

  ```
  [1 🎬 Flow] [2 🖼 Pexels] [3 🖼 Pexels]
  [4 🖼 Pexels] [5 🖼 Pexels] [6 🎬 Flow]
  [✅ all Pexels — render now]
  ```

- Every toggle creates a **new pack version**: a new shot map and a new `script.md` with only the Flow Cards, plus an updated estimate (`3 shots ≈ 36 credits`). The new version is sent as a new message. Older pack messages remain valid for their own version.
- The return leg cuts according to the version the export was uploaded or replied against. Versions are keyed by token or `message_id`, never by guessing.

Changing your mind later:

| When | Change | Result |
|---|---|---|
| before the export is returned | any | new pack version, as above |
| after render | Flow → Pexels | 🔁 re-render with the new choice. Footage is kept, so nothing is resent. |
| after render | Pexels → Flow | bot sends a single-Card pack for that Card. Its export comes back through the same upload/reply, and the bot re-renders with the new footage merged with the kept footage. |

Footage source, cut segments, narration and the shot map for every version live in `/data/studio/<clip_id>/`. They are deleted when the clip is uploaded to YouTube or after the 72 h `clip_wait` lifetime. The Manifest records `footage_source` per Card as `flow-studio` or `pexels`.

## One-time setup: recurring characters

A character library replaces asking about the character on every clip.

- `/settings` gains a Characters section. Each character has an `id`, a `tag` (e.g. `@Nong`), a Thai description, an optional English description, and a checkbox "Asset Profile created in Flow". The library also stores a default per channel, `{th, en, shop}`, each a character id or empty, plus the default footage source rule.
- The first time a character is used, the bot sends the English portrait prompt. The human generates the portrait in Flow, creates an Asset Profile with that tag in the Flow project used for clips, and ticks the checkbox. Later clips reuse the Asset Profile.

### Storage

The dashboard holds no mimo key (ADR 0007), so it cannot translate. The bot mounts `/config` read-only. Each file therefore has one writer:

| File | Writer | Content |
|---|---|---|
| `/config/characters.json` | dashboard, inside the existing `POST /settings` | characters, per-channel defaults, default footage rule |
| `/data/character_tags.json` | bot | English `locked_prompt_tag` and portrait prompt, keyed by a hash of the Thai description |

If the English field is filled, the bot uses it verbatim and translates nothing. Otherwise the bot translates once and caches the result by hash. The English text then stays identical across clips until the Thai description changes.

New module `app/characters.py` follows the pattern of `app/model_choice.py`:
- It reads the file on every call, so no restart is needed.
- It validates before writing.
- A missing file or unknown id means "no recurring character", and an unknown default falls back to the existing 🤖 behaviour.
- `WRITING_ROUTES` stays `{"/settings"}`.

## The pack

### Planning

🎞 Studio reuses `storyboard.py` with a new output format. The model call, `lock_to_script()` and `validate()` stay the same. The planner receives only the Flow Cards.

The character comes from the channel default without asking. The pack message carries buttons to switch character, using the existing `sbchar` token mechanism:

`[@Nong ✓] [@Other] [🤖 invent] [🚫 no person]`

Switching re-plans, which is one more mimo call. With a library character, the board takes the cached `locked_prompt_tag` as given (`OWN` mode with fixed English text). The model does not rewrite it. The existing 📋 button stays unchanged.

### Timing rules

Measured on the NAS (2026-10-15, 280 rendered clips, 1,506 non-final Cards): the median Card span is 6.8 s, p90 9.3 s and the maximum 17.8 s. **518 Cards (34%) exceed 7.5 s.** One shot per Card would force rewrites on most clips, and a rewrite after 🎞 Studio would ship text the human never approved. So Cards are not shortened. Instead, long Cards get more shots.

- Every shot is exactly **8 s**. The step 0 export confirmed this: 3 shots gave 24.000 s, with scene changes at exactly 8.0 s and 16.0 s.
- **Narrate first, plan second.** On 🎞 Studio, the bot synthesises the full narration once (the same single edge-tts call used for rendering) and measures each Card's span.
  - A Flow Card gets `shots_i = ceil((span_i + 0.5) / 8)` shots. The 0.5 s covers join silence and the voice tail. The last Card uses `span + TAIL_PAD`.
- The planner receives the shot count per Flow Card. Multiple shots of one Card are distinct views of the same beat: another angle, a closer framing, or the next action. `validate()` checks that the counts match exactly.
- The pack shows the total shots, the export length (Σ shots × 8 s) and estimated credits. The rate comes from the `FLOW_CREDITS_PER_SHOT` setting (default 12, measured for Omni 1.1 Flash 720p 8 s).
- ✂️ shortens long Cards through the **normal revise path**: the feedback is prefilled with the long Cards' names, and the Script returns to review. The bot never rewrites approved text by itself.
- The saved narration is reused at render, so cut points match exactly what was measured, and a render cannot fail with edge-tts `NoAudioReceived`.
- **`/say` staleness:** the saved directory records a hash of `say.json`. If the hash differs at render time, the bot re-synthesises, says so in chat, and relies on `tpad` to absorb small drift.

### `script.md`

The file is English only, with no dialogue and no voiceover text. Thai narration in it could make Veo animate speech. The template lives in one place in `storyboard.py`.

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

Each `[SCENE n]` block is one 8 s shot, so a Card with two shots appears as two blocks.
- Every block repeats both the `@tag` and the full `locked_prompt_tag`. The full text is the fallback in case Flow does not bind the tag.
- In Shop, every block that shows the product references `@Product`. The human creates that Prop from the real product photos.

### Animate with Ingredients

Animate in Flow is a separate generation from the composer, and Ingredients accepts **3 images** (confirmed in step 0). Each shot's copy box says what to attach:
- the character's Asset Profile or portrait
- the storyboard frame for that shot
- `@Product` (Shop), or a second frame of the same scene otherwise

The box also gives the motion prompt to paste, and the settings to use: Video · Ingredients · 9:16 · 720p · 8s · x1.

### Delivery

- **Telegram:** `script.md` is sent with the existing `send_document`. A follow-up message carries the pack link, the footage toggles and the character buttons. That message's id is the reply target for that pack version.
- **Dashboard:** read-only page `GET /storyboard/<clip_id>`, built from pack data the bot writes under `/data/studio/` (the dashboard mounts `/data:ro`). It also serves `GET /storyboard/<clip_id>/script.md`. Boxes, in order of use:

| # | Box | Shown |
|---|---|---|
| 0 | Project checklist: 9:16, Photorealistic preset, shots per scene, 8 s | always |
| 1 | Character: portrait prompt, tag, baseline details | expanded until ticked as created in Flow, or when invented; otherwise collapsed with "use @Nong in your existing project" |
| 2 | Product prop: tag `@Product` + download chosen photo(s) | Shop only |
| 3 | Full script with Copy + Download `script.md` | always, primary |
| 4 | Per shot: Ingredients to attach, motion prompt, settings, the Card's Thai narration and span | always; one box per Animate |
| 5 | Export + upload: "S shots × 8 s = X s", which Scenes order, upload form | always |

Copy buttons follow the Creator Studio conventions. The dashboard stays free of PIL and edge-tts imports.

## Return leg

### Upload path (primary)

Step 0 measured the export at **21.3 MB for 24 s** (720×1280, 24 fps, about 7.4 Mbps). A full Flow-heavy clip would be roughly 45–80 MB, which is over Telegram's 20 MB `getFile` ceiling. "Send as a normal video" would recompress to roughly 1–2 Mbps, and the footage is the point of the clip. Uploads therefore go through the web:

- The upload form on box 5 posts to a new route on the existing **Shop API** service (`PUT /shop/studio-inbox/<token>`). That service already accepts 100 MiB uploads behind nginx Basic Auth and mounts `/output`.
- The route validates only the token format and the media (decode-validated as Shop media is today). It writes `/output/studio-inbox/<token>.mp4` as `.part` and then renames it.
- The token is random per pack version and is minted by the bot. The Shop API holds no bot state.
- The bot's poll loop (no new port, ADR 0002) picks up an inbox file whose token matches a live `clip_wait` version and processes it. Unknown or stale inbox files are deleted after 72 h.
- The read-only dashboard stays read-only. Its page only links the form to the Shop API route.

A reply in Telegram still works for exports up to 20 MB, such as a single-Card pack.

### Processing

`clip_wait` gains `kind: "studio"`, with the Script snapshot, locale, character id, and the versions (each with token, `message_id` and shot map). One wait at a time and the 72 h lifetime are unchanged. A reply to an older storyboard (no `kind`) keeps current behaviour: the clip is filed as finished, with no cutting.

1. **Probe** the duration with ffprobe and drop audio. Scenes export always carries Veo audio, and there is no mute option. Let S be the version's shot count.
   - Within ±0.5 s of S × 8: shot j starts at j × 8.
   - Otherwise: the bot says `got 41.2 s but this pack has 6 shots × 8 = 48 s` and offers a **"cut evenly"** button, which splits the real length into S equal parts. It never cuts silently on a guess (ADR 0005 matching rule).
2. **Cut:** a Flow Card's footage is its consecutive shots joined, trimmed to the Card's narration span, with `-an`. Re-encoding is required, because exports have keyframes every 3 s.
3. **Render:** `render.build(script, supplied={i: seg_i for Flow Cards}, narration=<saved audio and starts>)`. The new `narration` parameter skips TTS. Pexels Cards fetch as today. 720p footage scales to 1080×1920, as supplied Footage does now.
4. **Deliver** through the existing `deliver()`: the mp4, the upload button, the `.srt`, and the Manifest with per-Card `footage_source`.

If a span is slightly longer than its footage, the last frame is held with `tpad`. Footage is never looped, because a loop visibly jumps back. This applies only to studio segments.

**Experiments (ADR 0004):** a clip with any `flow-studio` Card is excluded from `experiment.tally`, the same way explore clips are. It still counts toward the Gate and appears in `/stats`. Comparing Flow and Pexels clips is a later question, answered from `footage_source`.

| Failure | Behaviour |
|---|---|
| upload or probe fails | say so; the version stays live; resend works |
| render fails | segments and audio stay in `/data/studio/`; 🔁 re-renders without resending |
| saved narration missing | say so, synthesise again, rely on `tpad` |
| `clip_wait` expires | existing expiry message; inbox and studio files are cleaned |

## Shop

Shop already chooses a source per scene and uploads on its web job page. It adopts the pack like this:

- The job page gets a character dropdown (default: the `shop` channel default; 🚫 is allowed) and the same pack boxes for its Flow scenes.
- "Upload combined clip from Storyboard Studio" sends the file to the worker, which applies the same probe and cut rules. It stores each segment as that scene's media version through the existing media path, then accepts those scenes in one action. Render runs the existing path, with the price card and `#ad`.
- Affiliate rule: nothing touches `job.revision` outside the existing media and approval paths.
- Compose: `shop` mounts `/config:ro`, which the worker already has.

## ADR

Add ADR 0016, "Storyboard Studio pack". It records:
- It extends ADR 0005: Flow footage for any Card, chosen per Card, assembled from one stitched export, and still generated by the human.
- It extends ADR 0006: the bot now consumes a Flow export for Shorts. 0006's "no long-form assembly" still stands.
- It amends ADR 0007/0002 boundaries only by adding one Shop API write route into `/output/studio-inbox`. The bot still has no port, and the dashboard stays read-only.
- Why Flow automation was rejected: there is no headless path, and flowkit #67 reports account blocks.

## Testing

Unit tests run in the image with no network:

- **`characters`:** validate, save, load; per-channel defaults; default footage rule; unknown id falls back to 🤖; invalid input writes nothing.
- **Footage toggles:** default hook = Flow; a toggle creates a new version and token; all-Pexels renders without waiting; Flow → Pexels after render re-renders without new footage; Pexels → Flow produces a single-Card pack.
- **`script.md`:** contains only Flow Cards; no Thai characters; every block has the `@tag` and the full `locked_prompt_tag`; the STYLE line has 9:16, 8 seconds and no dialogue; no narration text; Shop blocks reference `@Product`.
- **Timing:** spans map to shots (7.4 s → 1, 7.6 s → 2, 13.3 s → 2); `validate()` rejects mismatched counts; ✂️ enters the revise path.
- **Cutter:** an ffmpeg `testsrc` of 24 s gives 3 shots; 23.6 s is accepted; 21 s is refused with the button; "cut evenly" gives 3 equal shots; a 2-shot Card is shots j and j+1 joined and trimmed; audio is dropped.
- **Inbox:** Shop API accepts a valid token and media, writes `.part` and renames; it rejects a bad token or bad media. The bot ignores unknown tokens and processes a matching one exactly once. Stale files are cleaned.
- **Render:** `render.build(narration=...)` makes no TTS call; a span longer than its footage holds the last frame; when the `say.json` hash changes, the bot re-synthesises.
- **Experiments:** a clip with a `flow-studio` Card is excluded from `tally` and counted in the Gate.
- **Dashboard:** `/storyboard/<id>` boxes follow the conditions above, and `WRITING_ROUTES` is unchanged.
- **Shop:** a combined upload accepts the right scenes, and revision invariants hold.
- Shared-sync and the existing suite stay green.

## Step 0 results (2026-10-15, user in Flow web)

| Question | Answer |
|---|---|
| 9:16 and 8 s per shot | Yes. Durations 4/6/8/10 s, x1–x4, 360p/720p. |
| Credits per shot | Omni 1.1 Flash · 720p · 8 s · x1 = 12 credits |
| Ingredients | 3 images accepted |
| Storyboard Studio frames | 3 frames per scene by default. Animate is a separate composer generation. |
| Stitched export | Yes, from Scenes, as one mp4. It always includes audio, which the bot drops. |
| Export measured | 24.000 s for 3 × 8 s; cuts at exactly 8.0 and 16.0 s; 720×1280, 24 fps, 21.3 MB |
| STYLE header honoured | Not confirmed. Grid frames looked 16:9. |
| `@tag` binds to Asset Profile | Not confirmed |
| Monthly allowance, cost of other models | Not yet known. Per-Card choice keeps clips affordable whatever the answer. |

Open items are checked during the Phase 1 live clip. The template and the checklist box absorb the answers.

## Phases

1. Character library, per-Card source, pack, upload inbox and return leg, for Shorts TH/EN.
2. Live end-to-end clip; tune the template and checklist (STYLE, `@tag`, frame aspect).
3. Shop: pack boxes, combined upload and character dropdown.

## Out of scope

- Any Flow automation, browser driver or extension.
- Paid video APIs.
- Long-form assembly (ADR 0006).
- Automatic YouTube upload (ADR 0001).
