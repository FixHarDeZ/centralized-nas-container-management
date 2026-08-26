# shorts-factory — Index

Telegram bot that turns a one-line Topic into a 40-50s vertical Thai
DevOps/AI clip. Design decisions live in the repo root: `CONTEXT.md`
(vocabulary) and `docs/adr/0001..0003` (why no YouTube upload, why no HTTP
surface, why Pillow). Those ADRs are binding — read them before changing shape.

## Shape

- One container, no ports, no nginx, no scheduler. A single Telegram
  `getUpdates` long-poll loop is the entire interface.
- Flow: Topic → mimo returns a Script → human reviews it in Telegram →
  button → the whole narration is spoken in **one** edge-tts call, footage is
  fetched per Card, cards are drawn with Pillow → silent video segments cut to
  the sentence boundaries, concatenated, then the narration muxed over the
  whole thing → mp4 delivered to Telegram and to `/output`.
- **Card timing comes from `SentenceBoundary` events.** Thai emits no
  `WordBoundary` (no spaces), so per-word timing does not exist. If the
  boundaries do not line up with the Cards, it falls back to speaking each Card
  separately.
- Two card looks: over footage (transparent card + scrim, footage supplies the
  motion) or, when no footage came back, the gradient card with a Ken Burns
  move. The fallback is silent by design.
- State: `/data/state.json`. Working files under `/data`, wiped after each
  render. Finished clips and their metadata `.txt` land in `/output`
  (`/volume1/shorts` on the NAS, reachable over SMB).

## Settings

| Key | Source | Note |
| :--- | :--- | :--- |
| `MIMO_API_KEY` | `shared.llm.mimo_api_key` | shared with news-feed; ops-bot keeps its own copy |
| `TELEGRAM_BOT_TOKEN` | `stacks.shorts_factory.telegram.bot_token` | dedicated bot, not ops-bot's |
| `TELEGRAM_CHAT_ID` | `stacks.shorts_factory.telegram.chat_id` | only trust boundary — all other senders dropped |
| `TTS_VOICE` | literal | `th-TH-NiwatNeural` |
| `PEXELS_API_KEY` | `stacks.shorts_factory.pexels_api_key` | free key; absent = every card falls back to the gradient |
| `BGM_DIR` | literal `/output/bgm` | drop CC0 tracks in; empty or missing = no music |
| `YOUTUBE_*` | `stacks.shorts_factory.youtube.*` | empty until `scripts/youtube_auth.py` is run; no credentials = no upload button |

## Gotchas

- **Pillow needs `libraqm0` from apt.** The wheel does not bundle Raqm, and
  `ImageFont.Layout.RAQM` fails *silently* without it — Thai tone marks vanish
  with only a `UserWarning`. The Dockerfile asserts `features.check('raqm')` at
  build time so this can never ship broken again.
- **Use `Waree-Bold` (`fonts-thai-tlwg`), never Noto Sans Thai.** Noto Sans
  Thai's cmap has no Latin letters or digits, so any English word inside a Thai
  sentence renders as tofu boxes; Pillow does no font fallback.
- **ffmpeg `drawtext` cannot render Thai** (no shaping). Not an escape hatch.
- **Do not downgrade `edge-tts`.** 7.0.2 gets `403` from the synthesis endpoint;
  the `Sec-MS-GEC` token scheme moves server-side. 7.2.8 works.
- **No `cpus:` in compose.** DSM's kernel has no CFS bandwidth control and the
  daemon refuses to create the container. `mem_limit` works fine.
- Host RAM is under pressure (swap fully consumed; whole-box OOM on
  2026-08-19), hence `mem_limit`/`cpus` in the compose file.

## Gaps

- Built and verified on the NAS but **not running**: `/volume1/shorts` must be
  created as a shared folder in DSM first, and the human must press Start on
  `@JaFixShortsBot` (a bot cannot open a chat; `sendMessage` returns "chat not
  found" until then).
- **Answered 2026-08-26:** the first upload came back `public`, so an unaudited
  project did not force it to private — the caution in ADR 0001 did not bite.
- The Shorts feed cover cannot be set through the API; `thumbnails.set` only
  affects search, the channel page and suggestions.
- The Google API-audit and OAuth-refresh-token claims behind ADR 0001 were
  never checked against Google's own docs. Confirm before building any upload.
