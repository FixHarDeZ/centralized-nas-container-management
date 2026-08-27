# The learning loop is gated: experiments run between clips and nothing tunes itself

shorts-factory is meant to get better at writing clips by reading how its own
clips performed. The obvious shape — feed the best-performing titles back into
the prompt, keep whatever the numbers like — is already partly built
(`analytics.winning_examples()` puts the top three into every prompt) and it is
wrong at this scale. Measured on the NAS, 2026-08-27: 9 clips uploaded inside
19 hours, 206 views total, of which one clip holds 182; median 3 views per
clip; 5 likes on the channel, all on that one clip; and the YouTube Analytics
API returns no rows for any of those nine videos yet. The channel itself is not
new — 197 videos, 1,396 lifetime views, 8 subscribers — and its older,
human-made videos do get Shorts-feed traffic (382 of 458 views since 1 August,
with retention between 44% and 86%). So distribution is not blocked at the
channel level; the bot's own clips simply have not been measured yet. Learning from that is fitting one
data point, and the one data point is a personal-finance clip on a channel
whose brief is DevOps/AI — so the naive loop's first act would be to abandon
the subject matter.

So the loop is gated. The system records everything from now on but is
forbidden to draw conclusions or change its own prompt until an experiment has
at least 10 clips and 300 views per variant, and the channel has at least 30
clips. `winning_examples()` is switched off until then; the "do not repeat
these titles" list stays, because deduplication is not statistical inference.
Recommendations are labelled by provenance — from data, exploration, or guess
— and before the gate they are all guesses and say so. "Inconclusive" is a
first-class result of an experiment, not a failure.

Experiments are between-clip and randomised per clip. YouTube offers no
within-clip A/B for Shorts, so a variant can only be assigned to a whole clip
and compared against other clips. (That constraint was recalled, not checked
against Google's own documentation — no web access was available when this was
written — except for the half the repo has verified: the Shorts feed ignores
custom thumbnails. Confirm it before designing any within-clip test. The
decision stands either way: at nine clips and 206 views there is nothing a
within-clip test could resolve that a between-clip one cannot.) Alternating A/B/A/B by upload
order was rejected: it correlates the variant with day of week and posting
time. A bandit was rejected too — with this sample size it would lock onto a
false winner within a handful of clips, and it needs a signal that does not
exist yet. The decision rule is deliberately blunt: a median gap of at least 5
percentage points of `averageViewPercentage`, measured on every clip's day-7
snapshot, or no winner is declared. Day 7 is fixed because retention keeps
moving as views accrue, and comparing "latest numbers" compares old clips to
new ones rather than variant to variant.

Every generated Script is written to a Manifest whether or not the human
uploads it. Discarding the clips a variant writes badly, and keeping only its
survivors, would make a worse variant look equal to a better one; recording the
discards turns that bias into a measurement — the discard rate per variant is
itself a signal, and a faster one than retention while views are this thin.

The primary metric is `averageViewPercentage` with views as a guardrail (a
variant may not drop views below half the running median). Views were rejected
as the primary because a bait clip wins on views while the writing gets worse,
and because comparing view counts needs far more samples than comparing a
per-viewer average does.

Answered on 2026-08-27, against this channel's own videos: the Analytics API
**does** serve per-second retention for Shorts. `v7ljwc_6_jM` (PT21S, 361
views) returns 100 rows of `audienceWatchRatio` and
`relativeRetentionPerformance` over `elapsedVideoTimeRatio`, one per 1% of the
clip. Two other Shorts on the same channel — 27 and 12 views — return zero
rows, so the gate is views, not format: a Clip nobody watched has no curve.
That is why the earlier probe on a bot Clip was inconclusive, and why
`/retention` walks back through published Clips instead of assuming the newest
has data. Individual videos also answer 500 from time to time; a sick video is
skipped rather than allowed to abort the walk.
