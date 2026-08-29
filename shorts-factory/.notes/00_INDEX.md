# shorts-factory — Index

Telegram bot that turns a one-line Topic into a 40-50s vertical Thai
DevOps/AI clip. Design decisions live in the repo root: `CONTEXT.md`
(vocabulary) and `docs/adr/0001..0003` (why no YouTube upload, why no HTTP
surface, why Pillow). Those ADRs are binding — read them before changing shape.

## Shape

- One container, no ports, no nginx, no scheduler thread. A single Telegram
  `getUpdates` long-poll loop is the entire interface; the two recurring jobs
  (daily snapshots, `/trends` three times a day) ride that loop.
- Flow: Topic → mimo returns a Script → human reviews it in Telegram →
  button → the whole narration is spoken in **one** edge-tts call, footage is
  fetched per Card, cards are drawn with Pillow → silent video segments cut to
  the sentence boundaries, concatenated, then the narration muxed over the
  whole thing → mp4 delivered to Telegram and to `/output`.
- **Every Card has two narrations.** `narration` = screen/subtitle form
  (English stays English), `spoken` = Thai-script transliteration, the only one
  edge-tts reads. `validate()` rejects any Latin character in `spoken`, and
  `render._speakable()` strips hyphens/dashes before synthesis — the voice reads
  one as a ~1s pause ("เอฟ-35" became "เอฟ" … "35"), so model names are said whole.
- **Card joins are trimmed.** The paragraph break that produces the boundary
  events also produces ~1.0s of dead air per join (measured; clause breaks are
  0.12-0.53s). `render.tighten()` slices at the boundaries, trims each slice's
  tail back to `JOIN_SILENCE` (0.30s) and re-joins, recomputing the starts by
  measuring the trimmed slices — the endpoint's offsets overshoot the file.
- **Card timing comes from `SentenceBoundary` events.** Thai emits no
  `WordBoundary` (no spaces), so per-word timing does not exist. If the
  boundaries do not line up with the Cards, it falls back to speaking each Card
  separately.
- Two card looks: over footage (transparent card + scrim, footage supplies the
  motion) or, when no footage came back, the gradient card with a Ken Burns
  move. The fallback is silent by design.
- **Learning loop (ขั้น 1-2 ลงแล้ว 27/08).** แผน 6 ขั้นที่
  `.notes/plan-learning-loop.md`, เหตุผลที่ `docs/adr/0004`, ศัพท์ที่ root
  `CONTEXT.md`. หัวใจ: บันทึกทุกอย่างลง Manifest ต่อคลิป (รวม Script ที่ไม่ได้อัป)
  แต่**ห้ามสรุปหรือปรับพรอมป์เอง**จนกว่าจะผ่าน Gate. `winning_examples()` ต้องปิด
  ก่อนถึง Gate. **ลงแล้ว**: `app/manifest.py` (1 ไฟล์ต่อ Topic ที่ `/data/clips`,
  เก็บ draft ทุกรอบรวมที่กดทิ้ง + `render` details ที่ `build()` คืนกลับมา) และ
  `analytics.gate_note()` ที่ปิด `winning_examples()` จนกว่าจะครบ 30 คลิป.
  `app/snapshots.py` (job รายวันขี่ poll loop ไม่ใช้ scheduler thread, `/snapshot`
  สั่งมือได้, day-7 = ตัวเลขทางการ) และ `app/backfill.py` (กู้ manifest 9 คลิปเก่าจาก
  `.txt`/`.srt` ใน `/output` ตอน startup, idempotent, ติดธง `reconstructed`).
  `app/experiment.py` (factor `hook` 2 variant สุ่มต่อคลิปตอนเปิด Topic ไม่ re-roll,
  explore 1 ใน 3 ไม่นับผล, `/experiment` รายงาน + ปฏิเสธที่จะฟันธงก่อนถึงเกณฑ์).
  `app/retention.py` (เส้น retention + หา cliff + map กลับเป็น card + วาด PNG ด้วย Pillow,
  `/retention`) และ `app/trends.py` (Google Trends RSS ไทย + YouTube chart ไทย → mimo
  แปลงเป็นหัวข้อ, `/trends` — ลิสต์หัวข้อแนบปุ่มเลข กดแทนพิมพ์ได้ `callback_data`
  = `pick:<suggested_at>:<index>` เทียบ timestamp กันกดปุ่มของลิสต์เก่า). **หัวข้อไม่ล็อก DevOps/AI แล้ว** (ADR 0004 ท้ายไฟล์) —
  `category` เป็นมิติที่บันทึกไว้อ่านแบบสังเกตการณ์ ไม่ใช่ variant ที่สุ่ม.
  **ยังไม่ลง**: recommender (ขั้น 6 รอ Gate)
- **The bot starts Topics itself (28/08).** `auto_slot()` owes the newest
  passed hour of `TRENDS_HOURS` (default `8,12,17`, TZ Asia/Bangkok) and the
  slot is stamped *before* the run spawns — `suggest_topics()` takes minutes and
  an unstamped slot re-fires on the next 30s tick. The automatic list carries a
  ✋ button (callback `cancel:<suggested_at>`, stamp-checked like the 💡 ones,
  and its branch must stay **above** the `mode != "review"` return in
  `on_callback()` or the tap dies silently). No tap within `AUTO_PICK_MINUTES`
  (default 15) and while `mode == "idle"` → a random suggestion is written and
  **rendered unattended**. That Script is posted with no keyboard and no
  `message_id`: `do_render()` rewrites the message it tracks. Auto-render sits
  at the end of the success path *inside* `make_script()` — the failure handler
  returns with `script=None`. Uploading is still a button (ADR 0001).
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
| `MIMO_REASONING_EFFORT` | literal `low` | mimo-v2.5-pro is a reasoning model; the default budget doubles latency for no better script |
| `YOUTUBE_SET_THUMBNAIL` | literal `false` | the Shorts feed ignores custom thumbnails, so it is opt-in |
| `MIMO_TIMEOUT_SECONDS` | literal `600` | wall-clock deadline per model call — httpx's own timeout is per read and will not fire on a trickling server |
| `YOUTUBE_*` | `stacks.shorts_factory.youtube.*` | empty until `scripts/youtube_auth.py` is run; no credentials = no upload button |

## Gotchas

- **A model call must have `asyncio.wait_for` around it.** httpx logs
  `200 OK` on headers, so a stalled body looks like success in the log, and its
  `timeout` is per read, not a total budget. The poll loop is inline, so a hung
  call freezes the entire bot.
- **"mimo ไม่ตอบภายใน 600 วินาที" does not mean mimo was down.** The retry
  shares one deadline, so an attempt that answers slowly *and* fails
  `validate()` leaves the second attempt only the remainder. Read the log
  before blaming the endpoint: two hedge warnings mean the first attempt came
  back and was rejected. The `%d tokens (%.0f tokens/วินาที)` line from
  `once()` is the discriminator — a healthy think runs at about 30 tokens a
  second however long it takes, and a stalled request never logs at all while
  its hedged twin does. The `HTTP Request: POST ... 200 OK` line lands ~8s
  after every mimo call (httpx logs on headers) and says nothing about health.
- **The schema retry leads with `mimo-v2.5`, not the pro model.** It inherits
  only the remainder of the shared deadline, which can be shorter than a pro
  think (measured: 257s left against a 347s worst case). The hedge still goes
  to the *other* model either way.
- **`/stats` and prompt priming only know about clips uploaded through the
  bot** (`/data/history.json`). Anything published by hand is invisible to
  them.

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
