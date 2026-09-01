# shorts-factory read-only dashboard — design

**Date:** 2026-09-01
**Stack:** `shorts-factory/`
**Status:** approved for planning

## Problem

Everything shorts-factory learns about itself already lives on disk — one
Manifest per Topic under `/data/clips`, day-7 snapshots inside those Manifests,
the experiment arms, `history.json`, the `.txt`/`.srt` beside each finished mp4.
The only way to read any of it is to ask the bot in Telegram, one command at a
time, one answer per message. Comparing ten clips, or looking at what a Script
went through before it was rendered, is not something a chat transcript does
well.

This design adds a browser view of that record. It reads; it never writes.

## Non-goals

- **No control surface.** No button starts a render, edits `say.json`, approves
  a Script, or uploads to YouTube. Human-in-the-loop steps stay in Telegram, on
  the phone, where they already work. The dashboard has no non-GET route at all.
- **No new numbers.** Every figure shown comes from the existing modules
  (`manifest`, `experiment`, `analytics`, `history`), so the dashboard and the
  bot can never disagree.
- **No recommender.** ADR 0004's Gate still holds: nothing here summarises
  results back into a prompt.

## ADR position

`docs/adr/0002` states shorts-factory has no HTTP surface, and closes with "A
future dashboard would have to add the nginx layer back." This design does
exactly that, so it needs a new ADR — `0007` — recording that the bot process
itself is still Telegram-only and portless, and that the HTTP surface belongs to
a separate read-only container. ADR 0002 is amended, not deleted: its reasoning
about the bot's trust boundary is still correct and still binding.

## Architecture

A second service in the existing `shorts-factory/docker-compose.yml`, built from
the **same image** as the bot (`build: .`), started with a different command.

```
shorts-factory        (bot)        no ports          /data rw, /output rw
shorts-factory-dash   (uvicorn)    expose: 8000      /data ro, no credentials
shorts-factory-nginx  (nginx)      ports: 5067:80    basic auth, all paths
```

Sharing the image is what makes the dashboard import `app.manifest`,
`app.experiment`, `app.analytics` and `app.history` directly instead of
re-implementing their JSON reading. That is the whole reason to accept the
larger base image (ffmpeg, fonts) for a process that needs neither. A separate
slim Dockerfile would have to `COPY app/` anyway to reuse those modules, and
would add a second build for a few hundred MB of disk.

The bot keeps its current shape: no ports, no uvicorn, no second writer to
`state.json`. Running uvicorn inside `main.py` was rejected — the poll loop is
inline and Pillow card drawing is in-process CPU, so every HTTP request would
stall for the length of a render.

### Read-only, three times over

1. The data volume is mounted `:ro`, so the kernel refuses a write.
2. The application declares no POST/PUT/DELETE/PATCH route, so there is nothing
   to call. A test asserts this.
3. The container gets no `env_file`, so it holds neither the Telegram bot token
   nor the YouTube refresh token. The one process reachable from the LAN cannot
   act on the outside world even if it is reached — it needs only `DATA_DIR`.

Any one of the three would be enough; together they mean a future edit cannot
quietly turn the dashboard into a control panel without someone deleting a
guard on purpose.

For the same reason the dashboard does **not** import `app.render` for
`say_as()`: that would pull Pillow and edge-tts into this process for a
five-line JSON read. It reads `/data/say.json` itself. The rule about never
re-deriving a figure still binds everything that *is* a figure — the Manifests,
the tally, the Gate.

### Auth

nginx sidecar holds the published port; the app is `expose:`-only and never
reachable from the LAN. Basic auth covers **every** path — unlike ops-bot there
is no webhook needing an exception. Credentials come from the vault at
`stacks.shorts_factory.dashboard.{basic_auth_user,basic_auth_password}` and are
turned into `shorts-factory/nginx/.htpasswd` with `htpasswd -cB` at setup time.
That file is gitignored (`*/nginx/.htpasswd` is already covered) and
`deploy.sh` already chmods every `*/nginx/.htpasswd` to 644 after upload.

The app itself needs no new secret, so `secrets.manifest.yaml` gains no `env:`
entry — only a comment naming the vault path the `.htpasswd` is generated from,
following dupe-sweeper's precedent.

### Resources

`mem_limit: 256m` on both the dashboard and nginx. No `cpus:` on any service —
DSM's kernel has no CFS bandwidth control and the daemon refuses to create the
container. The host has already had a whole-box OOM (2026-08-19), so every new
container gets an explicit cap.

## Pages

Server-rendered Jinja2. No JavaScript build, no bundler, no framework — the same
call the rest of this repo's dashboards make. One stylesheet, mounted as static
files.

| Route | Content |
| :--- | :--- |
| `/` | Every Clip, newest first: created, topic, variant (+ explore flag), outcome, published, views, day-7 retention. Gate progress from `analytics.gate_note()` across the top. |
| `/clip/{id}` | One Manifest in full: every draft in order including discarded ones, the rendered Script's cards with their `start` offsets, render params, the snapshot series by day, the storyboard if one was planned, a link to the YouTube video. |
| `/experiment` | `experiment.tally()` for both arms, `experiment.verdict()`, and `experiment.by_category()`. |
| `/now` | `state.json` as it stands — mode, current topic and clip_id, parked Clip with its 24h expiry, pending auto-pick deadline, last snapshot and last auto-trends stamps — plus the `say.json` substitutions. |
| `/healthz` | `{"ok": true}` for Uptime Kuma. |

An unknown `clip_id`, an unreadable Manifest, or a missing `state.json` renders
an empty state, not a 500: this is a view of a directory another process is
writing to, and a half-written file must never take the page down.

## Data flow

```
bot container  ──writes──▶  shorts_factory_data volume  ──reads (ro)──▶  dashboard
                            /data/clips/*.json                            │
                            /data/state.json                              │
                            /data/say.json                                │
                            /data/history.json                            │
                                                                          ▼
                                                      nginx :5067 ──▶ browser (LAN)
```

No shared memory, no IPC, no polling protocol. The dashboard reads the files on
each request; there is no cache to invalidate and at this scale (tens of
Manifests) there is no reason for one.

## Files

New:

- `shorts-factory/app/dashboard.py` — FastAPI app, routes, and `__main__` entry
  running uvicorn on `0.0.0.0:8000`
- `shorts-factory/app/templates/*.html` — base + one per page
- `shorts-factory/app/static/style.css`
- `shorts-factory/nginx/nginx.conf`
- `shorts-factory/nginx/.htpasswd` (generated, gitignored)
- `shorts-factory/tests/test_dashboard.py`
- `docs/adr/0007-dashboard-is-a-separate-read-only-container.md`

Modified:

- `shorts-factory/requirements.txt` — `fastapi`, `uvicorn`, `jinja2` (pinned)
- `shorts-factory/docker-compose.yml` — two services added
- `shorts-factory/README.md`, `shorts-factory/.notes/00_INDEX.md`,
  `shorts-factory/.notes/daily_log.md`
- root `CLAUDE.md` (port table row: `5067`), root `README.md`
- `docs/adr/0002-...md` — a closing line pointing at 0007

`deploy.sh` needs no change: `shorts-factory` is already in `ALL_STACKS` and the
new services live in that stack's compose file.

Port 5067 is the free slot: 5063, 5064, 5065, 5066, 5068, 5069 and 5070 are
taken, and 5060/5061 are unusable because browsers block them as SIP.

## Testing

One `tests/test_dashboard.py`, no fixtures beyond `tmp_path`:

- point `DATA_DIR` at a temp directory holding two hand-written Manifests, a
  `state.json` and a `say.json`
- `TestClient` GETs `/`, `/clip/{id}`, `/experiment`, `/now`, `/healthz` and
  asserts 200 plus one identifying string from each
- GET an unknown `clip_id` and assert a 404 page rather than a traceback
- assert every route in `app.routes` allows only `GET`/`HEAD` — the guard that
  makes "read-only" a property of the code and not just of the mount

## Risks

- **The larger image.** The dashboard carries ffmpeg and Thai fonts it never
  uses. Accepted: shared modules are worth more than image size, and the layers
  are already on the NAS for the bot.
- **A Manifest being written while a page reads it.** `manifest._save()` writes
  the whole file in one `write_text`, so a torn read is possible but rare and
  short-lived; a failed parse is logged and skipped, which is what
  `manifest.load()` already does.
- **New dependencies in the bot's image.** `fastapi`/`uvicorn`/`jinja2` are
  installed into the shared image but never imported by `app.main`, so the bot's
  runtime memory is unchanged.
