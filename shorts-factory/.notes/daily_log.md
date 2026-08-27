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

### Same day — the music mix was quietly attenuating the narration

Review caught what the earlier ducking measurement could not distinguish:
`amix` defaults to `normalize=1`, scaling every input by 1/n, so the presence of
*any* music dropped the voice by roughly 6dB. Comparing total RMS at the same
timestamps cannot tell "music ducked away" apart from "voice turned down and
music filling the hole" — both look like a small delta.

The test that separates them is a **silent** music track: any level change can
then only come from the filter chain. It measured -2.8dB and -5.5dB on the
narration. With `normalize=0`, whole-file RMS is -21.204dB without music against
-21.206dB with a silent track, and the peaks match too — the music path is now
an identity when there is nothing to mix.

Also turned off `alimiter`'s auto-level (`level=false`), which would otherwise
have made a clip with music louder than one without; peak protection was the
only thing wanted from it.

Two smaller fixes alongside: ADR 0003 still told readers to install
`fonts-noto-core` after the switch to Waree, which would have reintroduced the
tofu-box bug; and retiring the upload button used `editMessageText`, which
cannot touch a video message — that carries a caption, not text — so it now
uses `editMessageReplyMarkup`, which works on both.

## 2026-08-26 — thumbnail from the opening frame

After a successful upload the bot now grabs frame one of the clip and sets it
as the video's thumbnail. That frame is the hook card, which is the one screen
written specifically to stop a scroll, so it is already the right picture —
checked against a real clip rather than assumed: the opening frame shows the
hook text legible over its footage, not a black or mid-fade frame.

`thumbnails.set` accepts the `youtube.upload` scope already granted, so no
re-consent. Custom thumbnails do need a **phone-verified channel**; without one
YouTube answers 403. The video is already published by that point, so a
thumbnail failure is reported as a nuisance ("ตั้งเองใน Studio ได้") and never
as a failed upload.

Unrun, like the upload itself — it needs a real video id.

### 2026-08-26 — first upload, and what the thumbnail actually controls

First real upload: video `mOyx9mDhly8`, and it came back **`public`**. That
settles the open question behind ADR 0001 — an unaudited project did *not* have
its upload forced to private, at least for this account. `thumbnails.set`
returned success on the same run.

Then the cover looked wrong, and the investigation is worth keeping because the
code turned out to be correct:

- The JPEG sent is frame 0 exactly — re-extracting it from the finished clip and
  differencing gives a mean absolute difference of 0.00.
- The thumbnail YouTube actually serves
  (`i.ytimg.com/vi/<id>/maxresdefault.jpg`) **is** that image: the hook card over
  its footage, fitted into a 16:9 canvas with the sides filled by a zoomed,
  darkened copy. That letterboxing is why it reads as a different picture.
- **The Shorts feed ignores custom thumbnails entirely.** It picks its own frame,
  and there is no API for that cover — only the YouTube mobile app can set it,
  where the first option in the picker happens to be the opening frame.

So `thumbnails.set` still earns its place (search, channel page, suggestions),
but the Shorts cover cannot be automated. The upload message now says so and
tells the human the three taps, rather than leaving them to conclude the feature
is broken.

### 2026-08-26 — captions, upload history, performance feedback

Three additions, all free, all on demand — **no scheduler was added**, because
ADR 0002's "nothing needs to listen" is load-bearing for the whole shape. A
weekly digest would have broken it; `/stats` plus priming the prompt at
generation time gets the same value.

- **Captions.** `write_srt()` builds a subtitle track from the Card boundaries
  already computed for the video, so the timings cost nothing extra. It uses
  each Card's **raw** narration, not the `_speakable()` form: transliteration is
  right for the voice and wrong on screen, where "Docker" should read as
  "Docker". Attached after upload via `captions.insert`, which is a single
  multipart request rather than the resumable flow used for the video. The
  `.srt` is also kept beside the mp4 in `/volume1/shorts`.
- **History.** Every successful upload appends to `/data/history.json`. It is
  the only record of which videos are ours — YouTube is never enumerated — and
  it feeds the last 30 titles into the prompt as "already covered, do not repeat
  the same angle".
- **Performance.** `/stats` reports views and retention per uploaded clip,
  sorted by **percentage watched rather than views**, which for Shorts is the
  number that says whether the writing worked. The top three titles are fed
  into every subsequent generation as examples to write more like. Failure to
  fetch stats returns an empty list and never blocks writing a script.

Scopes were widened in one consent round (`youtube.force-ssl`,
`yt-analytics.readonly`). The old refresh token was kept until the new one was
proven — verified via `tokeninfo` that all three scopes were granted before
overwriting the vault. The YouTube Analytics API still needs enabling in the
Cloud project; it is separate from YouTube Data API v3 and currently answers
403.

### Same day — the bot froze twice, and the first fix was wrong

Two topics hung at "กำลังเขียนสคริปต์" with no error. The logs looked healthy —
`POST .../chat/completions "HTTP/1.1 200 OK"` — which is the trap: **httpx logs
that line when the headers arrive, not when the body finishes.** The connection
to mimo was still open 14 minutes later.

First fix set `timeout=180` on `AsyncOpenAI`, and it did not work. That value is
httpx's **per-read** timeout: a server trickling bytes resets the clock forever,
so it never fires. What was needed is a wall-clock deadline, so the call is now
wrapped in `asyncio.wait_for`.

Worth stating why this froze *everything* rather than one request: the Telegram
poll loop runs inline on the same task, so a hung model call takes the whole bot
down with it. The deadline bounds that; making generation concurrent with
polling would be the larger fix if it ever matters.

Verified afterwards against the topic that hung: a script came back in 73s with
six valid cards. Non-tech topics are handled fine by the prompt, so the freezes
were a mimo-side stall and nothing to do with the subject matter.

### 2026-08-26 (later) — why scripts kept failing, measured

Reports of frequent "เขียนสคริปต์ไม่สำเร็จ" and blank-looking covers. Both were
investigated rather than guessed at, and the script failures turned out to be
three separate causes stacked.

**The covers were never broken.** All six uploads have thumbnails served by
YouTube (60-115KB each), and downloading the newest one shows our own frame 0.
The grey tiles were the app's grid not having loaded. What *is* true is that the
Shorts feed and channel grid ignore custom thumbnails entirely, so setting one
only reaches search and suggestions. Per the request, `YOUTUBE_SET_THUMBNAIL`
now defaults to `false` — the code stays, the behaviour is opt-in.

**mimo is not down.** Benchmarked from the container: a trivial prompt answers
in 3-10s. The real prompt took 48-86s, and one run took 161s while burning
**10,457 completion tokens for 2,400 characters of output** — mimo-v2.5-pro is a
reasoning model and most of that is thinking. Latency therefore swings with how
long it chooses to think, and the tail was crossing the 180s deadline.

Three fixes, each measured:

1. `reasoning_effort="low"` — 79s / 3,796 tokens against 161s / 10,457 at the
   default, and the shorter run produced a *valid* script where the long one did
   not. `"minimal"` is rejected with a 400.
2. **A timeout now retries instead of failing.** The previous fix raised
   immediately on the deadline, so a single slow response lost the whole script
   even though the next attempt usually succeeds.
3. `HARD_MAX_CHARS_PER_LINE` 30 → 34, with the font floor 44px → 40px to match
   (34 wide Thai consonants measure 976px against 994px of usable width). The
   161s run failed validation on a 33-character line, and of three verification
   runs two produced longest lines of 30 and 31 — the old limit would have
   thrown away a third of otherwise good scripts.

Verified after: three real topics, 3/3 valid, 48-124s.

### 2026-08-26 (later) — Analytics API enabled; `/stats` is correct but early

With the API enabled the query works: channel totals return 75 views over 90
days and a per-video breakdown comes back fine. Filtering to the eight clips
this bot uploaded returns nothing, and the reason is visible in the day
dimension — **the most recent processed day is 2026-08-22 while today is the
26th.** YouTube Analytics runs a few days behind, and every clip in the history
was uploaded today, so there is genuinely nothing to report yet.

Since an empty result and a broken one look identical from Telegram, the empty
report now names the cut-off date ("ข้อมูลล่าสุด ... 2026-08-22"), fetched only
when there are no rows. Numbers should start appearing in a couple of days on
their own.

## 2026-08-27 — เสียงพูดไม่เป็นธรรมชาติ: ตัดความเงียบรอยต่อ card + บังคับทับศัพท์

**อาการที่แจ้ง:** พูดแล้วหยุดแปลกๆ ประมาณ 1 วิ กลางคลิป และพอเจอคำอังกฤษจะพูดรัวจนฟังไม่ทัน ไม่ชัด

**วัดของจริงก่อน** (สังเคราะห์สคริปต์คลิป 20260826-2028 ซ้ำในคอนเทนเนอร์ แล้ว `silencedetect`):

| ตัวคั่น card | SentenceBoundary | ความเงียบรอยต่อ |
| --- | --- | --- |
| `".\n\n"` (ของเดิม) | 1 อันต่อ card | 0.96-1.01 วิ |
| `"\n"` | 1 อันต่อ card | เท่ากันเป๊ะ |
| `". "` / `"."` / `", "` | ได้อันเดียวทั้งคลิป | 0.47 วิ |

สรุป: **ขึ้นบรรทัดใหม่** คือทั้งตัวจุด boundary และตัวที่ทำให้เงียบยาว (paragraph break)
ส่วนจุดไม่มีผลอะไรเลย. จังหวะหายใจปกติของเสียงนี้อยู่ที่ 0.12-0.53 วิ ดังนั้น 1.0 วิคือของแปลกปลอมจริง.
เอาตัวคั่นแบบอื่นไม่ได้ เพราะพอ boundary เหลืออันเดียว `narrate()` จะตีกลับแล้วหล่นไปทาง fallback
พูดทีละ card ซึ่งขาดกว่าเดิม.

**ที่แก้:**
- `render.tighten()` ตัดเสียงตาม boundary → เล็มหางเงียบเหลือ `JOIN_SILENCE` 0.30 วิ (`silenceremove`
  ต้อง `areverse` ครอบ เพราะมันทำงานกับหัวสตรีมอย่างเดียว) → ต่อกลับด้วย `concat_audio()` แบบ
  re-encode PCM (ถ้า `-c copy` mp3 จะลากส่วน padding ของ encoder เข้ามาที่รอยต่อ = เงียบกลับมาใหม่)
  แล้ววัด start ใหม่จากไฟล์ที่เล็มแล้ว ไม่เชื่อ offset ของ endpoint (มันยาวเกินจริง)
  - ⚠️ ต้อง seek ฝั่ง **input** (`-ss` ก่อน `-i`) เพราะ `-ss/-to` ฝั่ง output ทำงานหลัง filter chain
    ที่ `areverse` สลับ timestamp ไปแล้ว → ตัดไม่โดน เงียบสนิท ไม่ error (เสียเวลาไปหนึ่งรอบ)
  - วัดหลังแก้: รอยต่อ 0.92/0.87/0.90 → 0.39/0.43/0.42 วิ, คลิป 23.35 → 21.36 วิ
- การ์ดมี narration 2 ชุด: `narration` (คำอังกฤษคงไว้ → ขึ้นซับ) กับ `spoken` (ทับศัพท์ไทยล้วน →
  ให้เสียงอ่าน). `validate()` ตีกลับถ้า `spoken` มีอักษรละติน (retry loop ของ `generate()` แก้เอง).
  โมเดลเมินกฎทับศัพท์ในพรอมป์มาตลอด — คลิปนั้นเหลือ "Short Vertical Drama", "cliffhanger",
  "Netflix" ในบทพูด ซึ่งคือต้นเหตุที่พูดรัว/ไม่ชัด (เสียงสลับไปสำเนียงอังกฤษกลางประโยค)
- เทสต์: `test_card_joins_lose_their_dead_air` (tone-silence-tone ยืนยันว่าเงียบเหลือ 0.30 และ
  จำนวนช่วงพูดไม่หาย), `latin-in-spoken` / `missing-spoken` ใน parametrize เดิม

**ที่ไม่ได้แก้:** `TTS_RATE` ยัง `+10%` เท่าเดิม (ทดสอบ +12% ลดรอยต่อได้แค่ 1.01→0.90 เทียบกับ
0.40 ที่ได้จาก tighten — ปล่อยไว้เป็นปุ่มให้คนหมุนเอง)
