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

Card timing follows the length of each card's audio, so the clip runs as long
as the narration takes. Each card also drifts — a slow zoom in or out that
spans exactly its narration, alternating direction card to card, so the clip
does not read as a slideshow. Cards are drawn 12% larger than the frame and the
zoom crops into that margin, which keeps the text at native resolution.

## Uploading to YouTube

Once configured, the bot puts an "อัปโหลดขึ้น YouTube" button under each
finished clip. Publishing is the one step that stays behind a tap: it goes
outward and cannot be taken back quietly.

Set it up once with `python3 scripts/youtube_auth.py <client_id> <client_secret>`
— that file's docstring lists the Google Cloud console steps. The consent screen
must be set to **In production**; left in "Testing", refresh tokens expire after
7 days and uploads start failing with `invalid_grant`.

The clip's first frame — the hook card — is set as the thumbnail straight
after upload. That needs a phone-verified channel; without one YouTube refuses
with a 403 and the video keeps its auto-generated thumbnail, which is reported
but does not count as a failed upload.

With no credentials in the vault, the button simply never appears.

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
