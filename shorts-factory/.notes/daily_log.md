# Daily Log — shorts-factory

## 2026-08-24 — Design settled, stack scaffolded

Ran a full design interview (`/grill-with-docs`) for a new stack that turns a
one-line Topic into a Thai vertical short. Outcome recorded as vocabulary in
the root `CONTEXT.md` and three ADRs in `docs/adr/`.

Decisions worth repeating here: no YouTube upload in v1 (Google's API
compliance audit locks API-uploaded videos to private, and a `Testing` OAuth
consent screen expires refresh tokens after 7 days); no HTTP surface at all,
so no nginx, no `.htpasswd`, no published port and no port reservation; cards
drawn with Pillow rather than headless chromium; no scheduler — the bot acts
when a Topic arrives.

Verified on the NAS before writing any render code, in a throwaway
`python:3.12-slim` container:

- Pillow 12.3.0's manylinux wheel reports `features.check("raqm") == False`.
  `ImageFont.Layout.RAQM` then falls back to basic layout with only a
  `UserWarning`, and the mai-ek over sara-ii in "ที่" is dropped. This would
  have shipped silently.
- `apt-get install libraqm0` flips it to `True` (Raqm 0.10.5) with no Pillow
  rebuild, and the same string renders correctly. Fonts come from
  `fonts-noto-core`.
- `edge-tts` has both Thai voices (`th-TH-NiwatNeural`,
  `th-TH-PremwadeeNeural`) and synthesised a mixed Thai/English line fine.

Found while writing the manifest that `shared.llm.mimo_api_key` already exists
and holds the same value ops-bot copied into its own namespace, so this stack
needs no new mimo secret and ops-bot stays untouched.

Scaffolded `Dockerfile`, `docker-compose.yml`, `requirements.txt`,
`secrets.manifest.yaml`. The Dockerfile asserts Raqm at build time. `app/` not
written yet.

### Same day — app written, built and verified on the NAS

Wrote `app/script.py` (mimo → validated Script), `app/render.py` (Pillow cards,
edge-tts narration, ffmpeg concat) and `app/main.py` (long-poll loop and the
idle → review → rendering state machine in `/data/state.json`), plus 14 tests.

Four things only showed up on the real hardware:

1. **`cpus: "3.0"` cannot be used.** The daemon refuses the container:
   "NanoCPUs can not be set, as your kernel does not support CPU CFS scheduler".
   Dropped it; `mem_limit: 2g` is fine.
2. **`edge-tts==7.0.2` is dead.** Synthesis returns `403` from the
   `speech.platform.bing.com` websocket — the `Sec-MS-GEC` token scheme moves
   server-side, so old pins rot. 7.2.8 works. Never downgrade this one.
3. **Noto Sans Thai has no Latin glyphs at all.** Verified against its cmap:
   no A-Z, a-z or digits. "เก็บ log ไว้ที่ไหน" rendered the English word as
   three tofu boxes, and Pillow does no font fallback. Every TLWG face covers
   both scripts; switched to `Waree-Bold` from `fonts-thai-tlwg`, which is also
   the heaviest of them and reads best on a phone.
4. **`scripts/deploy.sh` has a hardcoded `ALL_STACKS` list.** A stack missing
   from it gets its `.env` skipped on upload and the restart fails with
   "Failed to load ... .env: no such file or directory". Added `shorts-factory`.

Two review-flow bugs fixed before first run, both found by reading rather than
testing: `make_script` left the previous review message's buttons live, so
approving an older message would have rendered a newer script — it now retires
the old prompt first; and a transient mimo error during a revision reset the
state to idle, throwing away the Script being iterated on — it now re-posts the
pending Script and stays in review.

Verified on the NAS: 14/14 tests pass inside the image; a two-card smoke render
produced a 1080x1920 h264+aac mp4 and the extracted frames show Thai, Latin,
tone marks and the code box all correct; `mimo-v2.5-pro` returned a valid
5-card Script for a real topic on the first try, every line within the 22-char
limit. Generation takes a few minutes — slow, but it happens once per clip.

Not running yet. `/volume1/shorts` does not exist, and compose refuses to start
without it (it does not auto-create the bind path, so there is no cruft to clean
up). The bot `@JaFixShortsBot` also returns "chat not found" until the human
presses Start.

### Same day — Ken Burns motion on every card

First clips looked fine but read as a slideshow, so cards now move. Each card is
drawn oversized (`OVERSCAN = 1.12`, so 1210x2150) and ffmpeg's `zoompan` crops a
1080x1920 window that slowly pushes in or pulls out across exactly the length of
that card's narration; direction alternates per card. Drawing oversized is the
point — zooming a card rendered at frame size would scale text past its native
pixels and soften it.

The zoom is driven off the frame counter (`on`) rather than accumulating into
`zoom`. Accumulation rounds at every step and the drift is visible as stutter on
a slow move. Card duration now needs `ffprobe`, so `audio_seconds()` reads it
before encoding.

Verified on the NAS: 17/17 tests pass in the image, and measuring the hook
card's yellow text across a rendered clip shows it growing 680px wide at t=0.2
to 724px at t=2.0 — the move is really happening, not just configured. Sampling
the final card at six points gives 864, 876, 894, 906, 921, 936 px: a clean
ramp, not the per-input-frame sawtooth `zoompan` produces when it is fed a
looped still the wrong way.

Timed a full-length render because the motion pass makes every frame distinct
where `-tune stillimage` used to coast on identical ones: a real 5-card Script
produced a **36.4s clip in 17.4s** inside the 2g cap, no OOM kill. Roughly half
real-time, so the render button stays a button.

### Same day — stock footage behind every card

Ken Burns alone still read as a moving slideshow, so cards now sit on real
video. Each Card carries a `query` (2-4 English words, something that can
actually be filmed) and `app/footage.py` pulls one portrait clip per Card from
the free Pexels API.

Two rendering paths now, picked per Card:

- **Footage found** — the card is drawn transparent at frame size with a drop
  shadow behind the text, the clip is scaled/cropped to fill 1080x1920, held
  back by a `black@0.5` scrim, and the card is overlaid. `-stream_loop -1`
  covers narration longer than the clip; no zoompan, the footage already moves.
- **No footage** — the original gradient card with the Ken Burns move.

`footage.fetch()` never raises: no key, no result, a timeout or a bad download
all return `None` and the Card quietly falls back to the gradient. That is the
whole failure story for this feature.

Verified on the NAS: 20/20 tests pass, and the same 5-card Script rendered to
36.4s in **54.7s** with footage (17.4s without) inside the 2g cap — three
Pexels downloads and five composites cost about 37 extra seconds. Extracted
frames confirm the footage is really behind the text, the scrim holds it back
far enough to read, and the code box stays legible over it.

`PEXELS_API_KEY` lives at `stacks.shorts_factory.pexels_api_key`. One test had
to stop hardcoding chat id 42 — it now reads `main.CHAT_ID`, because this suite
also runs with the real `.env` mounted.

### Same day — first real topic failed on a one-character overrun

"สายงานใหม่ AIOps กำลังมาหรอ?" came back with `card 4: บรรทัดยาว 23 ตัว เกิน 22`
and the whole clip was refused, twice, since the retry could not fix it either.

The rule was wrong, not the model. `validate()` was enforcing a limit the
renderer already handles — `_fit()` measures real pixel width and shrinks the
font — and character count is a bad proxy for width in Thai, where vowels and
tone marks have no advance at all. mimo naturally writes 17-23 character lines,
so a limit of 22 sat exactly on the boundary and rejected good scripts.

Split the number in two: 22 stays as the target in the prompt, and the enforced
limit is now 30, measured rather than guessed. At the renderer's smallest font
(44px, lowered from 52) thirty full-width Thai consonants measure 947px against
994px of usable card width and 32 overflow, while a natural 34-character Thai
line measures only ~788px. So 30 is the worst case still guaranteed to fit, and
anything under it renders without a hard failure.

Re-ran the same topic: 7 cards, longest line 23 characters — the exact case
that used to fail — with sensible footage queries on every card.

### Same day — narration prosody made configurable

Feedback was that the voice does not sound natural enough. Worth recording that
**edge-tts is Azure's neural voices** — it calls Edge's read-aloud endpoint —
so paying for Azure Speech buys the same audio. A real quality jump would mean
a different vendor (Google's Thai Chirp/Neural2, or a Thai specialist), not a
paid tier of what is already here.

Within edge-tts there are exactly three levers: voice (Thai has only Niwat and
Premwadee), `rate`/`pitch`, and the text itself. `speak()` now passes `TTS_RATE`
and `TTS_PITCH` through, defaulting to `+10%` / `+0Hz` — the stock rate reads
slow and flat.

Wrote ten A/B samples of one real narration line to `/volume1/shorts/tts-samples/`
for the human to listen to: both voices at +0/+10/+15%, pitch ±20Hz, plus two
text variants — one with commas inserted for breath pauses, one with the English
tech terms transliterated into Thai ("ด็อกเกอร์", "ล็อก") to test whether the
mid-sentence switch between Thai and English phonemes is what sounds wrong. If a
text variant wins, the fix belongs in the mimo prompt, not in the audio settings.

### Same day — narration rules moved into the prompt

The listening test picked samples 06 and 07: commas for breath pauses, and
English tech terms transliterated into Thai. Both are text properties, so the
fix went into mimo's system prompt rather than the audio settings, exactly where
the A/B was designed to point.

The important split: transliteration applies to `narration` **only**. On-screen
`lines` keep the English spelling, because "Docker" reads better on a card than
"ด็อกเกอร์" and the flags have to be shown verbatim to be useful. Command flags
that would be nonsense spoken (`--log-opt`) are described in words instead.

No validation added for this. Character-count enforcement had just caused a
hard failure on a good script, and the same trap applies here: a rule like "no
Latin letters in narration" would reject clips over a stray "Production".

Checked against a regenerated Script: cards came back with 1-3 commas each and
narration like "เอไอออปส์ คือการเอาเอไอ มาช่วยจัดการ โอเปอเรชันส์, ใช้เมชีนเลิร์นนิง
วิเคราะห์ข้อมูลปริมาณมหาศาล". Compliance is high but not total — one card still
had "Production" in Latin. Left as is; if it turns out to grate, a small
substitution table for the most common terms would be the deterministic fix.

`TTS_RATE` now defaults to `+10%`, which both winning samples used.

### Same day — narration is now one take, and the images are cut to it

Outside advice, and it was right: speak the whole Script as one continuous file
and mark where the images change, instead of synthesising per Card. Speaking
Card by Card restarts the intonation on every card and leaves silence at each
join, which is a large part of why the delivery sounded stitched together.

Finding the cut points took two probes. **Thai emits no `WordBoundary` events
at all** — no spaces to boundary on — so word-level timing is not available.
But the endpoint does emit **one `SentenceBoundary` per Card** when the Cards
are joined with `".\n\n"`, carrying `offset`, `duration` and `text`; it did not
split on a `?` inside a Card. As a cross-check, `silencedetect` separates the
joins cleanly too: card joins measure ~0.9s of silence against 0.4-0.5s for the
commas inside a sentence.

Architecture change that falls out of it: segments are now **video only**
(`-an`, duration from `-t`), concatenated, and the single narration is muxed
over the result. Nothing cuts the audio, so there is no join to click. Two
traps, both avoided deliberately:

- Sentence `duration` overshoots the file (last event ended at 19.98s on a
  19.30s file), so the final span comes from `audio_seconds()` and the video is
  padded `TAIL_PAD = 0.2s` past the audio, letting `-shortest` trim video
  instead of clipping the last words.
- A matching boundary count is not alignment — one Card split and two merged
  counts right too. Each boundary's `text` is checked against the start of its
  Card, and any mismatch falls back to the old per-Card path.

Verified end to end on a real 6-card Script: narration 38.136s, silent video
38.333s (the pad), final clip 38.136s with both streams — no truncated speech.
`silencedetect` found exactly five long gaps for five card joins. Frame
differencing across each join scored 29-51 against 4-22 for samples inside a
card, so every image change really does land on a sentence start. Render took
64.3s for a 38s clip under the 2g cap.

### Same day — background music, ducked under the narration

Now that the narration is a single continuous track, music is one filter rather
than a per-segment problem. `mux()` optionally takes a track, drops it to 0.35,
fades it out over the last 2s, and runs it through `sidechaincompress` keyed on
the narration itself, followed by `alimiter`. Speech stays on top because the
compressor is driven by the speech, not because a level was guessed.

Music comes from a folder (`BGM_DIR`, default `/output/bgm` = `/volume1/shorts/bgm`)
and one track is picked at random per clip. No folder or no tracks means no
music at all — that is the default state, since the folder does not exist yet.
Deliberately no music API: the risk here is Content ID, not integration.

Measured on two renders of the same Script, one with music and one without:

| window | no music | with music | delta |
| :--- | ---: | ---: | ---: |
| in a card gap | -90.0 dB (silence) | -27.9 dB | +62.1 dB |
| while speaking | -41.4 dB | -39.3 dB | +2.1 dB |

Music fills the gaps between cards and all but disappears under the voice.

Fetched six candidate tracks to `/volume1/shorts/bgm-candidates/` with 30-second
previews and a `LICENSES.txt`. All six are CC0, so no credit line is needed.
Worth recording how they were chosen: archive.org's `licenseurl` metadata is
supplied by uploaders and cannot be trusted on its own — a plain CC0 search
returns Pacman and Sega "game over" jingles tagged CC0, which they plainly are
not. Restricting to `collection:netlabels`, which is netlabel releases published
under CC from the start, gives real licences.

### Same day — YouTube upload behind a button

Closing the gap ADR 0001 left open. Chosen: `public`, a button rather than
automatic, and mimo's own title/description/hashtags.

`app/youtube.py` refreshes the token and does a resumable upload with plain
httpx — no `google-api-python-client`, since that is one POST and two requests.
The **privacy status is read back from the response instead of assumed**, which
turns the untested claim in ADR 0001 into a measurement: if an unaudited
project really does force uploads to private, the bot will say so on the first
upload rather than leaving someone to wonder why the video is not visible.

`scripts/youtube_auth.py` handles the one-time consent on the workstation:
stdlib only (no pip install), loopback redirect on :8765, `access_type=offline`
plus `prompt=consent` — without the latter Google omits the refresh token on
every authorisation after the first, which is a classic hour lost.

The button only appears when all three credentials are set, so the feature is
invisible until it is actually configured. Publishing stays behind a tap
because it is outward-facing and cannot be undone quietly, unlike everything
before it in the pipeline.

Vault keys `stacks.shorts_factory.youtube.{client_id,client_secret,refresh_token}`
exist but are empty, waiting on the Google Cloud setup, which needs the account
owner. 32/32 tests pass. The upload path itself is unrun — it cannot be
exercised until those credentials exist.

### Same day — YouTube credentials in place

First consent attempt failed with `Error 403: access_denied` — "the app is
currently being tested, and can only be accessed by developer-approved testers".
That is the Testing-status trap the script's docstring warns about, hit in its
other form: not the 7-day token expiry but an outright block. Publishing the app
(Google Auth Platform → Audience → Publish app) fixed it. Verification was not
needed; the unverified-app warning is clicked through once by the app's owner.

Also fixed the script's wait loop, which was a `while ... : pass` spin — now a
`threading.Event` with a 10-minute timeout.

Credentials are in the vault and deployed. Verified the refresh token by
exchanging it for an access token inside the container: it works. A follow-up
call to the channels endpoint returned `403 Insufficient Permission`, which is
the correct result — the grant is `youtube.upload` only, so reading channel
data is legitimately out of scope.

Still unproven: whether an upload actually lands, and what `privacyStatus`
YouTube applies to it. That needs a real upload, which stays a human button
press by design.
