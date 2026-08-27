# Plan — the learning loop

Agreed with the human on 2026-08-27 after a design interview. The reasoning
behind the shape lives in `docs/adr/0004`; the vocabulary lives in the root
`CONTEXT.md`. This file is the build order and the acceptance test for each
step. Stop after any step: every one of the first three is worth having even if
every experiment later fails.

## What was measured before deciding anything

- 9 Clips published, all inside 19 hours (26/08 17:12 → 27/08 08:28)
- views per Clip: 182, 7, 5, 3, 3, 3, 2, 1, 0 — total 206, median 3
- likes: 5, all on the 182-view Clip; the top Clip is personal finance, not the
  channel's DevOps/AI brief
- `analytics.performance()` returns `[]` — no video-level rows yet
- the channel is **not** new: 197 videos, 1,396 lifetime views, 8 subscribers.
  The bot's 9 Clips are a small minority of it
- channel traffic since 1 August: `SHORTS` 382, `YT_CHANNEL` 48, `YT_SEARCH` 8,
  `NO_LINK_OTHER` 7, `EXT_URL` 6, `YT_OTHER_PAGE` 5, `SUBSCRIBER` 2. **All of
  it belongs to older, human-made videos** — not one bot Clip appears in the
  top-videos report. Those older videos run 44-86% `averageViewPercentage`,
  which is a usable baseline to judge the bot's Clips against
- the Analytics API accepts `audienceWatchRatio` +
  `relativeRetentionPerformance` over `elapsedVideoTimeRatio` (200, correct
  schema, zero rows)

## Settled decisions

| Decision | Value |
| --- | --- |
| Primary metric | `averageViewPercentage`, measured on the day-7 snapshot |
| Guardrail | views may not fall below half the running median |
| Gate | 10 Clips **and** 300 views per Variant; 30 Clips on the channel |
| Niche | locked to DevOps/AI |
| Experiment unit | between-clip, randomised per Clip |
| First factor | hook archetype, two levels: shock number vs question |
| Decision rule | median gap ≥ 5 percentage points, else *inconclusive* |
| Explore rate | 1 Clip in 3, flagged, excluded from the arithmetic |
| Surface | PNG into Telegram; no HTTP (ADR 0002 stands) |
| Cadence | 3 Clips/day, upload still behind the human's button (ADR 0001) |
| Long-form | not designed for; but no schema may assume vertical/40-50s |

## 1. Manifest — done 2026-08-27

Write `/data/clips/<id>.json` for **every** Script the bot generates, published
or not. Contents: the Script verbatim, the Card start times from
`_narration_track()`, the rendering parameters actually used (voice, rate,
pitch, `JOIN_SILENCE`, whether BGM played and which track, clip duration,
frame size), the Variant and the exact prompt clause that defined it, the
explore flag, `published`, and later the performance snapshots.

Unpublished Scripts key on a generated id; `video_id` is filled in on upload.

*Why first:* the workdir is deleted after every render (`main.py`), so
everything above is currently thrown away and cannot be recovered later.

**Done when:** generating a Script that is never uploaded still leaves a
Manifest, and an uploaded Clip's Manifest names its `video_id` and its Card
start times.

## 2. Stop learning from noise — done 2026-08-27

Switch `analytics.winning_examples()` off until the Gate. Keep
`history.recent_titles()` feeding the "do not repeat" list — deduplication is
not inference.

**Done when:** the prompt for a new Script contains the avoid-list and no
performance examples, and `/stats` says in words that there is not enough data
to conclude anything.

## 3. Daily snapshots + backfill — done 2026-08-27

A daily job pulls views, likes, shares, comments, subscribersGained,
`averageViewPercentage` and `averageViewDuration` for every Clip aged 1-30 days
and appends a dated snapshot to its Manifest. The day-7 snapshot is the
official number for experiments; the rest are for watching a Clip mature.

Backfill the 8 older Clips from the `.srt` and `.txt` still in `/volume1/shorts`
— narration text and Card boundaries survive there. Flag them
`reconstructed: true`: their `lines`, footage queries and audio parameters are
gone for good.

**Done when:** a Manifest carries more than one dated snapshot, and the 8 old
Clips have Manifests marked reconstructed.

## 4. Retention curves — verified and built 2026-08-27

**First** query `audienceWatchRatio` over `elapsedVideoTimeRatio` for a Clip
that by then has real views. If rows come back, render the curve as a PNG with
the Card boundaries drawn on it and send it to Telegram, marking the Cards
where the fall is sharper than the Clip's own baseline. If rows stay empty on a
Clip that has views, Shorts are not covered: say so, drop this step, and live
with one retention number per Clip.

**Done when:** either a curve PNG exists for a real Clip, or the ADR records
that Shorts have no curve.

## 5. First experiment — done 2026-08-27

Randomise `hook` per Clip at generation time, record it in the Manifest, and
never re-roll — a Script rewritten on feedback keeps its Variant. Explore clips
skip assignment.

Report per Variant: clip count, views, median `averageViewPercentage` at day 7,
and the discard rate (`published: false` over total). Apply the decision rule
only once the Gate is met; before that the report shows counts and the words
"not enough data".

**Done when:** ten Clips are assigned, and the report refuses to name a winner.

## 6. Recommender

Only after the Gate. Five topics per request, each tagged `[from data]`,
`[explore]` or `[guess]`, with the evidence behind a `[from data]` tag shown.
Before the Gate everything is `[guess]` and the report says so.

## Risks to keep visible

- **The Gate may never be reached at the current distribution.** At the median
  of 3 views per Clip, 300 views per Variant needs hundreds of Clips. The
  channel's older videos do reach the Shorts feed, so this is not a channel
  level block — but if the bot's Clips keep failing to reach it, the honest
  conclusion is that the bottleneck is distribution, not writing, and the
  experiment queue should move to posting time, title and hashtags rather than
  script internals.
- **The older videos are a comparison set, not training data.** They were made
  by a human in a different format; their 44-86% retention says what this
  channel's audience is capable of watching, not what the bot should imitate.
- ~~**Shorts retention curves may not exist over the API.**~~ Answered: they do.
  The gate is views (361 yes, 27 no), not format — so the curve arrives late,
  and only for Clips that actually travelled.
- **The human's taste is part of the experiment.** Discarded Scripts are
  recorded for exactly this reason; if the discard rate diverges sharply
  between Variants, that is the result, whatever retention says.
