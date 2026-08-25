# shorts-factory renders clips but does not upload them to YouTube

Uploading via the YouTube Data API is gated on Google-side approval, not code:
a project that has not passed the API compliance audit has every
`videos.insert` upload locked to `private` with no way to publish it, and an
OAuth consent screen left in `Testing` expires refresh tokens after 7 days,
which would kill an unattended uploader about a week after it shipped
(`youtube.upload` is a sensitive scope, so leaving `Testing` requires
verification). Rather than start the project with a Google paperwork queue, v1
renders the clip, delivers it over Telegram and to a shared folder, and the
human uploads it. Adding an upload step later is additive.

Both Google-side constraints above were recalled, not checked against Google's
own documentation when this was written; confirm them before building any
upload path. The decision stands regardless — v1 exists to find out whether the
clips are worth publishing at all.
