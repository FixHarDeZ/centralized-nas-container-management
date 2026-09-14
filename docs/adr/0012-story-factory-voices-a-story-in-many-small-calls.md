# A Story is voiced in twenty small calls, not one long one

Google's Text-to-Speech API has an endpoint built for exactly this stack:
`synthesizeLongAudio`, whose entire reason to exist is audio too long for a
normal request. A Story is thirty to forty minutes of narration, about 20,000
Thai characters. Everything about the name says use it. This stack uses the
ordinary `synthesize` endpoint instead, roughly twenty times per Story.

## Why the small calls win

`synthesize` caps a request at 5,000 bytes. Thai costs three bytes a character,
so the cap is about 1,600 Thai characters — around 400 words. A Chapter of ~700
words is ~8,400 bytes and therefore always needs two or three calls. There is no
setting that raises this; the cap is the endpoint.

`synthesizeLongAudio` removes the cap and charges for it in dependencies. It
writes only to an `output_gcs_uri` — there is no way to receive the bytes in the
response — so taking it means a GCS bucket, a bucket IAM policy, the storage
client in the image, and a download step, to end up with a file that could have
been in memory. It is served from `v1beta1` and labelled Pre-GA, it returns a
long-running operation that has to be polled rather than awaited, and its
support for the Chirp 3: HD voices this stack wants is not stated anywhere in
the documentation. Against that, chunking costs a sentence splitter and a loop.

So the audio is built from many files and the seams are ours to manage. Chunks
are cut at sentence boundaries, never at a raw 5,000-byte offset — a byte offset
lands mid-word, and in Thai, which does not space its words, it lands mid-word
with no way to tell. Chapter timestamps are the running sum of the measured
durations of the trimmed chunks, read from the files themselves.

## The risk this takes on, stated plainly

Each `synthesize` call is independent. No prosodic context crosses a chunk
boundary, so pitch and energy reset about twenty times inside something built to
be listened to for forty minutes without looking. That is the real cost of this
decision, and it is not the same as seam *timing*, which is trivial to fix by
trimming silence.

It is also the one thing `synthesizeLongAudio` might genuinely have solved — and
"might" is doing real work in that sentence, because Google does not claim
anywhere that the long endpoint synthesises with continuous prosody rather than
chunking internally. So this ADR names its own reversal condition: **if chunk
seams are audible in Thai narration, the GCS dependency becomes worth paying,
and the first step is then to verify that the long endpoint actually sounds
better — not to assume it.** The test is cheap: one Thai paragraph as a single
call, the same paragraph as three, listened to at the joins — with the
production silence trim already applied to the three, so that what is being
judged is a jump in pitch and level and not a gap the trim would have closed.

## What this settles alongside it

The decision drags a few smaller ones with it. Auth is a service-account JSON,
written to a file at startup and pointed at by `GOOGLE_APPLICATION_CREDENTIALS`
— no GCS scope needed. It is stored **base64-encoded** in
`secrets/vault.sops.yaml`: sops itself would hold the raw multiline JSON
happily, but `scripts/render_env.py` refuses to emit a newline into a `.env`
("docker-compose .env does not support multiline values") and would fail
`make secrets` for the whole repo. So the vault holds one long single-line
value and the container decodes it. Cost is not a consideration: Chirp 3: HD is $30 per
million characters with a million free every month, so a ~20,000-character Story
is about $0.60 and the free tier covers roughly fifty a month. Commercial use
and YouTube monetisation are permitted on every tier, including the free one. At
around twenty requests per Story against a 200-per-minute quota, the request
count this ADR chooses is not close to any limit.

Two things Chirp 3: HD takes away rather than gives. It accepts no SSML, and it
excludes `custom_pronunciations` for `th-th` specifically — so porting the `/say`
text-substitution trick from `shorts-factory` is not a design preference here,
it is the only mechanism available for fixing a mispronounced word. Its pause
tags (`[pause short]`, `[pause long]`) go in the `markup` field rather than
`text` and do work in Thai, but they are non-deterministic and so must never be
used to compute a Chapter timestamp.

Figures and API surface above were read from Google's documentation in September
2026, and two of its own pages contradict each other on whether `speaking_rate`
applies to Chirp 3: HD. Fire the API before trusting any of it.
