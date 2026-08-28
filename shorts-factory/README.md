# shorts-factory

Telegram bot that turns a one-line topic into a 40-50 second vertical Thai
DevOps/AI short.

Send it a topic. It asks mimo for a script, shows you the script, and waits.
Press **render** and it draws the cards, speaks them, assembles the clip, and
sends the mp4 back — plus a copy on the NAS at `/volume1/shorts` with the
title/description/hashtags in a `.txt` beside it. Press **เขียนใหม่** and it
asks what to change instead.

It does not upload to YouTube, and it has no web interface — no port, no
nginx, no dashboard. See `docs/adr/0001` and `docs/adr/0002` at the repo root
for why.

## Waiting for the model

Writing a script takes minutes, and how many depends on how long the model
decides to think rather than on the network. Measured on the NAS, same prompt:
93s for 3,092 completion tokens, 112s/4,016, 197s/7,010, 207s/5,415 and
347s/10,585 — roughly 30 tokens a second every time. The old 240s cap cut off
the long thinks and then retried, so a topic that needed 283s produced eight
minutes of silence and an error; the budget is now 600s and it is **shared
across both attempts**, because two full-length tries is twenty minutes of
someone staring at "กำลังเขียนสคริปต์...". A timeout is therefore never
retried — it has spent the whole budget by definition — while a script that
comes back malformed is, since that leaves time on the clock.

There is a second failure shape underneath that one. A request can take the
headers and never deliver a body: observed 2026-08-27 at 19:25:45, "200 OK"
logged instantly, silence until the deadline — and the same topic answered in
137s two hours later. Waiting a hang out costs ten minutes; cutting every slow
call off costs the long thinks that do finish. So after 240s a second request
goes out alongside the first and whichever answers first wins. It goes to
`mimo-v2.5` rather than to `mimo-v2.5-pro` again: an identical twin was tried
and both requests hung together in the same episode, while the smaller model
wrote the same script in 149s.

Streaming was tried and abandoned: reading the same answer as a stream took
400s against 137s unstreamed. It would have let silence be told from slowness,
but this endpoint does not go silent — it thinks — so the trade bought nothing
and cost three times the wall clock.

Long jobs run off the Telegram poll loop, so `/help`, `/stats` and the rest
still answer while a script is being written or a clip rendered. The bot takes
one job at a time: a second topic during either is refused rather than queued.

## Commands

`/help` prints the lot in Thai, inside the chat, which is where anyone would
look for it. The others: `/stats` (how published clips did), `/snapshot` (pull
today's numbers now rather than waiting for the daily run), `/experiment` (the
running A/B and whether it can be called yet), `/retention` (one clip's curve,
with the drop-offs named by card). Anything that is not a command is a Topic.

## Pipeline

```
topic → mimo → script (hook + cards + metadata) → your review
      → Pexels (one stock clip per card)  ┐
      → Pillow (one card image per card)  ├→ ffmpeg composite + concat → mp4
      → edge-tts (one audio per card)     ┘
```

Cards sit on real footage, dimmed by a scrim so the text reads. When Pexels has
nothing for a card — or the key is missing entirely — that card falls back to a
gradient background with a slow Ken Burns move, and the render carries on.

The whole script is spoken in one edge-tts call, which is what keeps the
delivery continuous — but the paragraph break that makes the endpoint report
one sentence boundary per card also buys a paragraph-length pause: measured
~1.0s at every card join against 0.12-0.53s at the voice's own clause breaks.
The render cuts each card out at those boundaries, trims its trailing silence
back to 0.30s and joins the pieces again, so the joins sit inside the voice's
natural rhythm instead of reading as a series of announcements.

Every card carries its narration twice: `narration` keeps English spelled as
English and goes to the subtitles, `spoken` is the same sentence transliterated
into Thai script and is the only one the voice ever reads. A Latin word left in
`spoken` makes the voice switch to English mid-sentence, where it reads at
English pace — a rushed, unclear burst inside Thai speech — so the validator
rejects it.

Card timing follows the length of each card's audio, so the clip runs as long
as the narration takes. Each card also drifts — a slow zoom in or out that
spans exactly its narration, alternating direction card to card, so the clip
does not read as a slideshow. Cards are drawn 12% larger than the frame and the
zoom crops into that margin, which keeps the text at native resolution.

## What it records

Every Script the bot writes gets a Manifest under `/data/clips/<id>.json` —
the drafts in order (a revision is appended, never overwritten), the render
parameters, the Card start times, and later the publication and its numbers.
It is written whether or not the clip is ever uploaded: keeping only the
scripts that survived review would flatter whichever way of writing produces
the ones you happen to throw away (`docs/adr/0004`).

The workdir is deleted after every render, so anything not captured there is
gone for good.

Once a day, after `SNAPSHOT_HOUR` (default 10:00), the bot pulls views, likes,
shares, comments, subscribers gained and retention for the youngest published
clips inside a 30-day window — the id filter is a URL and only 50 fit, so the
newest are kept and the oldest dropped — and appends a dated snapshot to each
Manifest. A failed pull still marks the day rather than retrying on every poll
tick; a missed day costs nothing, since the day-7 reading is the first one
taken at age seven or later. It rides the
Telegram poll loop rather than a scheduler thread — `getUpdates` already wakes
every 30 seconds — so the stack still has no port and no listener. `/snapshot`
runs it on demand. The **day-7** snapshot is the official figure: retention
keeps moving as views accrue, and comparing "latest" numbers compares old clips
to new ones instead of one way of writing to another.

The nine clips published before Manifests existed are reconstructed at startup
from the `.txt` and `.srt` left in `/output` — title and card boundaries
survive there, nothing else does — and flagged `reconstructed`.

Reading the numbers back is deliberately gated. Until the channel has 30 clips
(and, once experiments start, 300 views per variant), `winning_examples()`
returns nothing and `/stats` says in words that the figures cannot be used to
decide anything. Measured on 2026-08-27: 9 clips, 206 views, 182 of them on a
single clip — feeding that back into the prompt is learning from one sample.
The "do not repeat these titles" list keeps working; deduplication is not
inference.

## Where viewers leave

`/retention` draws one clip's retention curve with its card boundaries on it,
marks the cliffs, and names the card that was on screen at each one. It is the
reason the Manifest records card start times: `elapsedVideoTimeRatio` is a
fraction of the clip, and turning that back into a card needs the clip's own
duration and boundaries.

A cliff is a fall at least twice the clip's typical step and at least 5% of the
curve's height; neighbouring buckets are merged, since one cliff usually spans
two or three. Everything below that is the ordinary slope every clip has.

YouTube builds these curves only once a clip has been watched enough —
measured on this channel: 361 views yes, 27 views no — so `/retention` walks
back from the newest published clip until it finds one with data.

## Finding something to make

`/trends` reads two outside signals — Google Trends' RSS feed for Thailand
(what people search for, with volumes and the headline behind each spike) and
YouTube's own `mostPopular` chart for TH (what they watch) — and asks the model
to turn them into five topics you could actually be given. The raw rows are
sent too, so a suggestion that drifted from its source can be caught against
it. Nothing is fed into a script automatically: a topic you did not choose
becomes a clip you do not want to upload.

The suggestions carry a numbered button each, so picking one is a tap rather
than retyping a Thai sentence; typing a topic still works and is still the only
way to send one the model did not suggest. The button carries the list's
timestamp as well as the index, because the index alone means nothing: run
`/trends` twice and button 3 on the older message points into the newer list,
which would start writing a topic nobody chose. A tap on a superseded list is
refused. A tap while a script is waiting for review is refused too — starting a
new topic there would abandon the pending one without marking it discarded,
which is what 🗑 is for.

News, politics, sport results and anything about a real person are kept out.
YouTube rows carry a category, so 25 (News & Politics) and 17 (Sports) are
dropped before the model sees them; Google Trends rows carry no category, so
there the prompt and your own choice are the only filter — a politician and a
live match both reached the model in testing, and it declined them. That is why
the raw rows are always printed: on that path a bad suggestion is only
catchable against its source. This is not squeamishness — it is the one place
where a model writing confidently about a live story publishes an invented
claim about a named person under your channel's name.

Topics are no longer locked to DevOps/AI. A search of Thai short-form for
`devops ไทย` over 30 days returns nothing at all, so the lock was buying clean
experiments on an audience that does not exist. Each script now names its own
category, and `/experiment` reports how the categories did — labelled as an
observation, because you choose the topics and nothing about that is
randomised.

## The experiment

One factor is varied at a time, currently the hook: a Clip opens either with a
shock number or with a question. The Variant is drawn at random when a Topic
arrives — before the Script exists — and never re-rolled, so rewriting a script
you dislike cannot quietly pick the winner. One Clip in three is an **Explore
clip** instead: written deliberately outside the pattern, flagged, and left out
of every calculation. A loop that only ever learns from its own past stops
improving.

The clause that defines a Variant is stored verbatim in the Manifest, because
the base prompt drifts and a Variant name alone would not say what it meant on
the day.

`/experiment` reports clips, discard rate, views and median day-7 retention per
Variant. It names a winner only when both arms have 10 clips and 300 views and
their medians differ by at least 5 percentage points; below that it says
*inconclusive*, which is a result and not a failure. The discard rate is a
signal in its own right — a Variant whose scripts you keep throwing away is
losing, whatever its retention says.

## Uploading to YouTube

Once configured, the bot puts an "อัปโหลดขึ้น YouTube" button under each
finished clip. Publishing is the one step that stays behind a tap: it goes
outward and cannot be taken back quietly.

Set it up once with `python3 scripts/youtube_auth.py <client_id> <client_secret>`
— that file's docstring lists the Google Cloud console steps. The consent screen
must be set to **In production**; left in "Testing", refresh tokens expire after
7 days and uploads start failing with `invalid_grant`.

The clip's first frame — the hook card — is set as the thumbnail straight
after upload. Note what that does and does not cover: it is the thumbnail on
search, the channel page and suggestions, but **the Shorts feed ignores custom
thumbnails** and picks its own frame. There is no API for the Shorts cover; only
the YouTube mobile app can set it (Edit → Cover, where the first option is the
opening frame). The bot says so after each upload. That needs a phone-verified channel; without one YouTube refuses
with a 403 and the video keeps its auto-generated thumbnail, which is reported
but does not count as a failed upload.

With no credentials in the vault, the button simply never appears.

## Subtitles, history and `/stats`

Each upload gets a Thai caption track built from the same sentence boundaries
the video is cut on, and the `.srt` is kept beside the mp4.

Uploads are recorded in `/data/history.json`. Recent titles go into the prompt
so the bot stops repeating itself, and `/stats` reports views and retention per
clip — sorted by how much of each clip was actually watched, which is the number
that matters for Shorts. The top performers are fed back in as examples. Both
only see clips uploaded through the bot.

## Background music

Put royalty-free tracks in `/volume1/shorts/bgm/` and one is picked at random
per clip, ducked under the narration by a sidechain compressor keyed on the
speech itself. An empty or missing folder means no music, which is the default.

Nothing downloads music automatically — the risk with background music is
Content ID, not plumbing, so the tracks are yours to vet.

## Configuration

`.env` is generated from the vault — see `secrets.manifest.yaml`. Never edit
it by hand.

```bash
make secrets                    # render .env from vault + manifest
./scripts/deploy.sh -s shorts-factory -y
```

The `/volume1/shorts` shared folder must exist on the NAS before first run;
create it in DSM (Control Panel → Shared Folder), it is not created by the
stack.

## Thai text rendering

Pillow's wheel does not include Raqm. Without the `libraqm0` package,
`ImageFont.Layout.RAQM` quietly degrades to basic layout and Thai tone marks
are dropped — no error, just wrong pixels. The Dockerfile installs it and then
asserts `features.check('raqm')` so a broken image fails the build instead of
shipping. ffmpeg's `drawtext` does no shaping at all and is not an alternative.

The face is Waree Bold from `fonts-thai-tlwg`, chosen because it covers Thai
and Latin in one file. Noto Sans Thai does not: its cmap has no A-Z or digits,
so `เก็บ log ไว้` comes out with the English word as empty boxes.
