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


## Amended 2026-08-27: the niche lock is gone, and category is an observation

The lock to DevOps/AI was chosen so that the subject could not swamp every
other variable. Evidence collected the same day killed the premise: a YouTube
search for `devops ไทย` over 30 days of Thai short-form returns **zero**
results, `kubernetes สอน` returns one clip with 123 views, and the channel's
own median is 3 views a clip against a personal-finance outlier at 182. A lock
that keeps the experiment clean but guarantees no audience produces a Gate that
can never be reached — cleanliness bought with the entire point of the
exercise. Topics are now free.

`/trends` supplies the outside signal the loop was missing: Google Trends'
RSS feed for TH (the `dailytrends` JSON endpoint is retired — it answers 404;
`/trending/rss?geo=TH` is what replaced it) and YouTube's own `mostPopular`
chart for TH. Both measure demand, and both are outside data, so the Gate does
not apply: that gate stops the bot learning from its own thin numbers, not from
the world. Suggestions are shown alongside the raw rows they came from and are
never fed into a Script automatically — the human still picks.

News, politics, sport results and anything about a real person are kept out —
but by different means on each path, and one of them is weaker than the other.
YouTube rows carry a category, so 25 (News & Politics) and 17 (Sports) are
dropped outright. Google Trends rows carry no category at all, so on that path
the prompt and the human's choice are the only filter: `นายกเฮง` and a live
volleyball match both reached the model, which declined them. That is one layer
where the other has two, which is why the raw rows are always printed alongside
the suggestions — a bad suggestion has to be visible against the thing it came
from. This is not taste, it is the
one place where an LLM writing confidently about a live story publishes an
invented claim about a named human being under this channel's name. Observed
before the rule was tightened: the model proposed *"is Tobey Maguire really
coming back?"* — exactly the shape to refuse.

Making **category** the randomised factor was considered and rejected on
implementation: the human chooses the Topic, so a category drawn at random
would simply be overruled, and randomisation is the only thing that separates
an experiment from a story. Category is therefore recorded on every Script and
reported as an **observation**, labelled as such in `/experiment` — with topics
free to roam it is the biggest thing moving the numbers, and refusing to look
at it would be worse than looking at it with the caveat attached. The
randomised factor stays `hook`.
